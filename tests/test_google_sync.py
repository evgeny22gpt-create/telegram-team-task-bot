from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from database import Task, get_all_tasks, initialize_database, upsert_tasks_from_sync
from google_sync import (
    SHEET_HEADERS,
    SyncAction,
    SyncConflictError,
    build_sync_plan,
    decide_task_sync,
    execute_sync,
    parse_utc_timestamp,
    tasks_from_sheet_values,
)


BASE_TASK = Task(
    id=1,
    text="Подготовить вопросы",
    user="@bay22",
    created_at="2026-07-11T21:00:19+00:00",
    status="Новая",
    category="Без категории",
    updated_at="2026-07-11T21:00:19+00:00",
)


class FakeWorksheet:
    """Запоминает обращения как Google-лист, не выполняя сетевых запросов."""

    def __init__(self, values: list[list[str]]) -> None:
        self.values = [row.copy() for row in values]
        self.update_requests: list[dict[str, object]] = []
        self.appended_rows: list[list[str]] = []

    def get(self, range_name: str) -> list[list[str]]:
        if range_name != "A:G":
            raise AssertionError(f"Неожиданный диапазон: {range_name}")
        return [row.copy() for row in self.values]

    def batch_update(
        self,
        data: list[dict[str, object]],
        *,
        value_input_option: str,
    ) -> None:
        self.update_requests.extend(data)
        if value_input_option != "RAW":
            raise AssertionError("Ожидался RAW-режим записи.")

    def append_rows(
        self,
        values: list[list[str]],
        *,
        value_input_option: str,
    ) -> None:
        self.appended_rows.extend(values)
        if value_input_option != "RAW":
            raise AssertionError("Ожидался RAW-режим записи.")


class GoogleSyncTests(unittest.TestCase):
    """Проверяет правила синхронизации без обращения к настоящей таблице."""

    def test_z_suffix_is_parsed_as_utc(self) -> None:
        timestamp = parse_utc_timestamp("2026-07-12T10:00:00Z")
        self.assertEqual("2026-07-12T10:00:00+00:00", timestamp.isoformat())

    def test_equal_content_requires_no_change(self) -> None:
        decision = decide_task_sync(BASE_TASK, BASE_TASK)
        self.assertEqual(SyncAction.NO_CHANGE, decision.action)

    def test_newer_sqlite_version_is_pushed(self) -> None:
        sqlite_task = replace(
            BASE_TASK,
            status="В работе",
            updated_at="2026-07-12T10:05:00+00:00",
        )
        decision = decide_task_sync(sqlite_task, BASE_TASK)
        self.assertEqual(SyncAction.PUSH_TO_GOOGLE, decision.action)
        self.assertEqual(sqlite_task, decision.source_task)

    def test_newer_google_version_is_pulled(self) -> None:
        google_task = replace(
            BASE_TASK,
            category="Подготовка",
            updated_at="2026-07-12T10:05:00+00:00",
        )
        decision = decide_task_sync(BASE_TASK, google_task)
        self.assertEqual(SyncAction.PULL_TO_SQLITE, decision.action)
        self.assertEqual(google_task, decision.source_task)

    def test_equal_timestamp_with_different_content_is_conflict(self) -> None:
        google_task = replace(BASE_TASK, status="Готово")
        decision = decide_task_sync(BASE_TASK, google_task)
        self.assertEqual(SyncAction.CONFLICT, decision.action)
        self.assertIsNone(decision.source_task)

    def test_plan_handles_tasks_existing_on_only_one_side(self) -> None:
        google_only = replace(BASE_TASK, id=2)
        decisions = build_sync_plan([BASE_TASK], [google_only])
        self.assertEqual([1, 2], [decision.task_id for decision in decisions])
        self.assertEqual(
            [SyncAction.PUSH_TO_GOOGLE, SyncAction.PULL_TO_SQLITE],
            [decision.action for decision in decisions],
        )

    def test_sheet_values_are_validated_and_parsed(self) -> None:
        values = [
            list(SHEET_HEADERS),
            [
                "1",
                BASE_TASK.text,
                BASE_TASK.user,
                BASE_TASK.created_at,
                BASE_TASK.status,
                BASE_TASK.category,
                BASE_TASK.updated_at,
            ],
        ]
        self.assertEqual([BASE_TASK], tasks_from_sheet_values(values))

    def test_duplicate_sheet_id_is_rejected(self) -> None:
        row = [
            "1",
            BASE_TASK.text,
            BASE_TASK.user,
            BASE_TASK.created_at,
            BASE_TASK.status,
            BASE_TASK.category,
            BASE_TASK.updated_at,
        ]
        with self.assertRaisesRegex(ValueError, "повторяется"):
            tasks_from_sheet_values([list(SHEET_HEADERS), row, row])


class SyncExecutionTests(unittest.TestCase):
    """Проверяет применение плана на временной SQLite и фальшивом листе."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "tasks.db"
        self.backup_dir = Path(self.temp_dir.name) / "backups"
        initialize_database(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @staticmethod
    def sheet_values(*tasks: Task) -> list[list[str]]:
        return [
            list(SHEET_HEADERS),
            *[
                [
                    str(task.id),
                    task.text,
                    task.user,
                    task.created_at,
                    task.status,
                    task.category,
                    task.updated_at,
                ]
                for task in tasks
            ],
        ]

    def test_dry_run_does_not_write_or_create_backup(self) -> None:
        upsert_tasks_from_sync(self.db_path, [BASE_TASK])
        worksheet = FakeWorksheet(self.sheet_values(BASE_TASK))

        report = execute_sync(
            self.db_path,
            worksheet,
            apply=False,
            backup_dir=self.backup_dir,
        )

        self.assertFalse(report.applied)
        self.assertIsNone(report.backup_path)
        self.assertEqual([], worksheet.update_requests)
        self.assertEqual([], worksheet.appended_rows)
        self.assertFalse(self.backup_dir.exists())

    def test_apply_pulls_newer_google_version_and_creates_backup(self) -> None:
        upsert_tasks_from_sync(self.db_path, [BASE_TASK])
        google_task = replace(
            BASE_TASK,
            status="В работе",
            updated_at="2026-07-12T10:00:00+00:00",
        )
        worksheet = FakeWorksheet(self.sheet_values(google_task))

        report = execute_sync(
            self.db_path,
            worksheet,
            apply=True,
            backup_dir=self.backup_dir,
            now=datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc),
        )

        self.assertTrue(report.applied)
        self.assertTrue(report.backup_path and report.backup_path.is_file())
        self.assertEqual([google_task], get_all_tasks(self.db_path))
        self.assertEqual([BASE_TASK], get_all_tasks(report.backup_path))

    def test_apply_appends_task_existing_only_in_sqlite(self) -> None:
        upsert_tasks_from_sync(self.db_path, [BASE_TASK])
        worksheet = FakeWorksheet(self.sheet_values())

        report = execute_sync(
            self.db_path,
            worksheet,
            apply=True,
            backup_dir=self.backup_dir,
            now=datetime(2026, 7, 12, 12, 1, tzinfo=timezone.utc),
        )

        self.assertTrue(report.applied)
        self.assertEqual([[str(BASE_TASK.id), BASE_TASK.text, BASE_TASK.user,
                           BASE_TASK.created_at, BASE_TASK.status,
                           BASE_TASK.category, BASE_TASK.updated_at]],
                         worksheet.appended_rows)

    def test_conflict_blocks_all_writes_and_backup(self) -> None:
        upsert_tasks_from_sync(self.db_path, [BASE_TASK])
        google_task = replace(BASE_TASK, status="Готово")
        worksheet = FakeWorksheet(self.sheet_values(google_task))

        with self.assertRaises(SyncConflictError):
            execute_sync(
                self.db_path,
                worksheet,
                apply=True,
                backup_dir=self.backup_dir,
            )

        self.assertEqual([BASE_TASK], get_all_tasks(self.db_path))
        self.assertEqual([], worksheet.update_requests)
        self.assertEqual([], worksheet.appended_rows)
        self.assertFalse(self.backup_dir.exists())


if __name__ == "__main__":
    unittest.main()

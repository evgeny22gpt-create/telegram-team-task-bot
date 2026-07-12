from __future__ import annotations

import unittest

from bot import (
    build_add_success_text,
    build_csv_filename,
    build_start_text,
    build_sync_preview_text,
    build_sync_apply_text,
    build_tasks_list_text,
    build_user_label,
    build_whoami_text,
    format_created_at,
    is_sync_owner,
)
from database import Task
from google_sync import SyncAction, SyncDecision, SyncReport


class StartTextTests(unittest.TestCase):
    """Проверяет приветствие без подключения к Telegram."""

    def test_start_text_uses_first_name(self) -> None:
        text = build_start_text("Евгений")

        self.assertIn("Привет, Евгений!", text)
        self.assertIn("/start", text)
        self.assertIn("/add", text)

    def test_start_text_has_safe_fallback_without_user(self) -> None:
        text = build_start_text(None)

        self.assertIn("Привет, друг!", text)

    def test_user_label_prefers_public_username(self) -> None:
        self.assertEqual("@evgeny", build_user_label("evgeny", "Евгений"))

    def test_user_label_falls_back_to_full_name(self) -> None:
        self.assertEqual("Евгений", build_user_label(None, "Евгений"))

    def test_whoami_contains_numeric_id_and_username(self) -> None:
        result = build_whoami_text(123456789, "bay22")

        self.assertIn("ID: 123456789", result)
        self.assertIn("Username: @bay22", result)

    def test_whoami_handles_missing_username(self) -> None:
        result = build_whoami_text(123456789, None)

        self.assertIn("ID: 123456789", result)
        self.assertIn("Username: не задан", result)

    def test_add_success_text_contains_saved_data(self) -> None:
        text = build_add_success_text(7, "Подготовить отчёт", "@evgeny")

        self.assertIn("Задача #7 сохранена", text)
        self.assertIn("Подготовить отчёт", text)
        self.assertIn("@evgeny", text)

    def test_format_created_at_converts_utc_to_moscow(self) -> None:
        result = format_created_at("2026-07-11T21:00:19+00:00")

        self.assertEqual("12.07.2026 00:00 МСК", result)

    def test_empty_tasks_list_has_add_hint(self) -> None:
        result = build_tasks_list_text([])

        self.assertIn("Список задач пока пуст", result)
        self.assertIn("/add", result)

    def test_tasks_list_preserves_received_order(self) -> None:
        tasks = [
            Task(1, "Первая задача", "Анна", "2026-07-11T10:00:00+00:00"),
            Task(2, "Вторая задача", "Илья", "2026-07-11T10:05:00+00:00"),
        ]

        result = build_tasks_list_text(tasks)

        self.assertLess(result.index("#1 Первая задача"), result.index("#2 Вторая задача"))
        self.assertIn("Автор: Анна", result)

    def test_csv_filename_uses_moscow_time(self) -> None:
        from datetime import datetime, timezone

        result = build_csv_filename(datetime(2026, 7, 11, 21, 15, tzinfo=timezone.utc))

        self.assertEqual("tasks_2026-07-12_00-15_msk.csv", result)

    def test_sync_preview_reports_matching_sources(self) -> None:
        report = SyncReport(
            decisions=(
                SyncDecision(1, SyncAction.NO_CHANGE, "Совпадает"),
                SyncDecision(2, SyncAction.NO_CHANGE, "Совпадает"),
            ),
            applied=False,
        )

        result = build_sync_preview_text(report)

        self.assertIn("Без изменений: 2", result)
        self.assertIn("уже совпадают", result)

    def test_sync_preview_warns_about_conflict(self) -> None:
        report = SyncReport(
            decisions=(
                SyncDecision(1, SyncAction.CONFLICT, "Одинаковое время"),
            ),
            applied=False,
        )

        result = build_sync_preview_text(report)

        self.assertIn("Конфликты: 1", result)
        self.assertIn("заблокирована", result)

    def test_sync_preview_explains_that_changes_are_not_applied(self) -> None:
        report = SyncReport(
            decisions=(
                SyncDecision(1, SyncAction.PULL_TO_SQLITE, "Google новее"),
            ),
            applied=False,
        )

        result = build_sync_preview_text(report)

        self.assertIn("Google → SQLite: 1", result)
        self.assertIn("ничего не записывает", result)

    def test_only_configured_owner_is_allowed_to_apply_sync(self) -> None:
        self.assertTrue(is_sync_owner(222, {111, 222}))
        self.assertFalse(is_sync_owner(333, {111, 222}))
        self.assertFalse(is_sync_owner(None, {111, 222}))

    def test_sync_apply_reports_noop_without_backup(self) -> None:
        report = SyncReport(
            decisions=(SyncDecision(1, SyncAction.NO_CHANGE, "Совпадает"),),
            applied=False,
        )

        result = build_sync_apply_text(report)

        self.assertIn("Изменения не требуются", result)

    def test_sync_apply_reports_directions_and_backup(self) -> None:
        from pathlib import Path

        report = SyncReport(
            decisions=(
                SyncDecision(1, SyncAction.PULL_TO_SQLITE, "Google новее"),
                SyncDecision(2, SyncAction.PUSH_TO_GOOGLE, "SQLite новее"),
            ),
            applied=True,
            backup_path=Path("tasks_before_sync_test.db"),
        )

        result = build_sync_apply_text(report)

        self.assertIn("SQLite → Google: 1", result)
        self.assertIn("Google → SQLite: 1", result)
        self.assertIn("tasks_before_sync_test.db", result)


if __name__ == "__main__":
    unittest.main()

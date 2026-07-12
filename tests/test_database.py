from __future__ import annotations

from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from database import (
    Task,
    add_task,
    create_database_backup,
    get_all_tasks,
    initialize_database,
    upsert_tasks_from_sync,
)


class DatabaseTests(unittest.TestCase):
    """Проверяет базу отдельно от Telegram и настоящего токена."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_tasks.db"
        initialize_database(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_table_has_task_and_sync_columns(self) -> None:
        connection = sqlite3.connect(self.db_path)
        try:
            rows = connection.execute("PRAGMA table_info(tasks)").fetchall()
        finally:
            connection.close()

        column_names = [row[1] for row in rows]
        self.assertEqual(
            [
                "id",
                "text",
                "user",
                "created_at",
                "status",
                "category",
                "updated_at",
            ],
            column_names,
        )

    def test_tasks_survive_reopen_and_keep_insertion_order(self) -> None:
        first_id = add_task(
            self.db_path,
            "Подготовить вопросы к встрече",
            "Анна",
            created_at="2026-07-11T10:00:00+00:00",
        )
        second_id = add_task(
            self.db_path,
            "Проверить презентацию",
            "Илья",
            created_at="2026-07-11T10:05:00+00:00",
        )

        # Имитируем следующий запуск: повторная инициализация не стирает таблицу.
        initialize_database(self.db_path)
        tasks = get_all_tasks(self.db_path)

        self.assertEqual([first_id, second_id], [task.id for task in tasks])
        self.assertEqual(
            ["Подготовить вопросы к встрече", "Проверить презентацию"],
            [task.text for task in tasks],
        )
        self.assertEqual(["Новая", "Новая"], [task.status for task in tasks])
        self.assertEqual(
            ["Без категории", "Без категории"],
            [task.category for task in tasks],
        )
        self.assertEqual(
            [task.created_at for task in tasks],
            [task.updated_at for task in tasks],
        )

    def test_old_four_column_database_is_migrated_without_data_loss(self) -> None:
        legacy_db_path = Path(self.temp_dir.name) / "legacy_tasks.db"
        connection = sqlite3.connect(legacy_db_path)
        try:
            connection.execute(
                """
                CREATE TABLE tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    user TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO tasks (text, user, created_at)
                VALUES (?, ?, ?)
                """,
                (
                    "Старая задача",
                    "@legacy_user",
                    "2026-07-11T09:00:00+00:00",
                ),
            )
            connection.commit()
        finally:
            connection.close()

        # Два запуска проверяют и саму миграцию, и её повторную безопасность.
        initialize_database(legacy_db_path)
        initialize_database(legacy_db_path)
        tasks = get_all_tasks(legacy_db_path)

        self.assertEqual(1, len(tasks))
        self.assertEqual(1, tasks[0].id)
        self.assertEqual("Старая задача", tasks[0].text)
        self.assertEqual("Новая", tasks[0].status)
        self.assertEqual("Без категории", tasks[0].category)
        self.assertEqual(tasks[0].created_at, tasks[0].updated_at)

        connection = sqlite3.connect(legacy_db_path)
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            connection.close()
        self.assertEqual("ok", integrity)

    def test_empty_task_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            add_task(self.db_path, "   ", "Анна")

    def test_sync_upsert_updates_existing_and_inserts_new_task(self) -> None:
        add_task(
            self.db_path,
            "Старая формулировка",
            "@bay22",
            created_at="2026-07-11T10:00:00+00:00",
        )
        tasks = [
            Task(
                id=1,
                text="Новая формулировка",
                user="@bay22",
                created_at="2026-07-11T10:00:00+00:00",
                status="В работе",
                category="Подготовка",
                updated_at="2026-07-12T10:00:00+00:00",
            ),
            Task(
                id=2,
                text="Задача из Google",
                user="@bay22",
                created_at="2026-07-12T10:05:00+00:00",
                status="Новая",
                category="Без категории",
                updated_at="2026-07-12T10:05:00+00:00",
            ),
        ]

        upsert_tasks_from_sync(self.db_path, tasks)

        self.assertEqual(tasks, get_all_tasks(self.db_path))

    def test_sqlite_backup_is_created_and_passes_integrity_check(self) -> None:
        add_task(
            self.db_path,
            "Задача для резервной копии",
            "@bay22",
            created_at="2026-07-11T10:00:00+00:00",
        )

        backup_path = create_database_backup(
            self.db_path,
            Path(self.temp_dir.name) / "backups",
            timestamp="20260712_120000_000000",
        )

        self.assertTrue(backup_path.is_file())
        self.assertEqual(get_all_tasks(self.db_path), get_all_tasks(backup_path))


if __name__ == "__main__":
    unittest.main()

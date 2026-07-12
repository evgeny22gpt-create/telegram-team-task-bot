from __future__ import annotations

import csv
from io import StringIO
import unittest

from database import Task
from exporter import build_tasks_csv, safe_spreadsheet_cell


class CsvExporterTests(unittest.TestCase):
    """Проверяет CSV без Telegram и без создания постоянного файла."""

    def setUp(self) -> None:
        self.tasks = [
            Task(1, "Первая задача", "Анна", "2026-07-11T10:00:00+00:00"),
            Task(2, "Вторая задача", "Илья", "2026-07-11T10:05:00+00:00"),
        ]

    def test_csv_has_utf8_bom_and_experiment_columns(self) -> None:
        payload = build_tasks_csv(self.tasks)
        decoded = payload.decode("utf-8-sig")
        rows = list(csv.reader(StringIO(decoded), delimiter=";"))

        self.assertTrue(payload.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(
            ["ID", "Задача", "Пользователь", "Создано (UTC)", "Статус", "Категория"],
            rows[0],
        )
        self.assertEqual("Новая", rows[1][4])
        self.assertEqual("Без категории", rows[1][5])

    def test_csv_keeps_task_order(self) -> None:
        decoded = build_tasks_csv(self.tasks).decode("utf-8-sig")
        rows = list(csv.reader(StringIO(decoded), delimiter=";"))

        self.assertEqual(["1", "2"], [rows[1][0], rows[2][0]])

    def test_formula_like_text_is_neutralized(self) -> None:
        self.assertEqual("'=2+2", safe_spreadsheet_cell("=2+2"))
        self.assertEqual("Обычная задача", safe_spreadsheet_cell("Обычная задача"))

    def test_valid_telegram_username_has_no_visible_apostrophe(self) -> None:
        tasks = [
            Task(1, "Задача", "@bay22", "2026-07-11T10:00:00+00:00"),
        ]
        decoded = build_tasks_csv(tasks).decode("utf-8-sig")
        rows = list(csv.reader(StringIO(decoded), delimiter=";"))

        self.assertEqual("@bay22", rows[1][2])

    def test_csv_uses_status_and_category_from_database_task(self) -> None:
        tasks = [
            Task(
                1,
                "Подготовить материалы",
                "@bay22",
                "2026-07-11T10:00:00+00:00",
                status="В работе",
                category="Подготовка",
                updated_at="2026-07-11T10:15:00+00:00",
            ),
        ]
        decoded = build_tasks_csv(tasks).decode("utf-8-sig")
        rows = list(csv.reader(StringIO(decoded), delimiter=";"))

        self.assertEqual("В работе", rows[1][4])
        self.assertEqual("Подготовка", rows[1][5])


if __name__ == "__main__":
    unittest.main()

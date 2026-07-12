from __future__ import annotations

from collections import Counter
from pathlib import Path
import sys

import gspread


# При прямом запуске файла Python сначала видит папку tools.
# Добавляем корень проекта, чтобы импортировать общий модуль config.py.
PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from config import load_settings  # noqa: E402
from database import get_all_tasks  # noqa: E402
from google_sync import (  # noqa: E402
    SHEET_HEADERS,
    SyncAction,
    build_sync_plan,
    tasks_from_sheet_values,
)


# Эта область доступа разрешает только чтение Google Таблиц.
# Проверочная программа не сможет изменить или удалить ячейки.
READ_ONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"

def count_nonempty_data_rows(values: list[list[str]]) -> int:
    """Считает заполненные строки после строки заголовков, не выводя их содержимое."""

    return sum(
        1
        for row in values[1:]
        if any(str(cell).strip() for cell in row)
    )


def main() -> None:
    """Проверяет безопасный доступ к нужной таблице и структуру листа «Задачи»."""

    settings = load_settings()
    if not settings.google_sync_configured:
        raise RuntimeError(
            "Google-синхронизация не настроена: проверьте .env и JSON-ключ."
        )

    # gspread читает JSON-ключ, получает временный токен Google
    # и создаёт клиента для запросов к Sheets API.
    client = gspread.service_account(
        filename=str(settings.google_service_account_file),
        scopes=[READ_ONLY_SCOPE],
    )

    # Открытие по ID надёжнее открытия по названию: названия таблиц могут повторяться.
    spreadsheet = client.open_by_key(settings.google_spreadsheet_id)
    worksheet = spreadsheet.worksheet(settings.google_sheet_name)

    # Читаем только используемые в проекте семь колонок.
    # Тексты строк остаются в памяти и не выводятся в терминал.
    values = worksheet.get("A:G")
    google_tasks = tasks_from_sheet_values(values)
    sqlite_tasks = get_all_tasks(settings.db_path)
    plan = build_sync_plan(sqlite_tasks, google_tasks)
    action_counts = Counter(decision.action for decision in plan)

    print("GOOGLE_SHEET_ACCESS=read-only <verified>")
    print(f"SPREADSHEET_TITLE={spreadsheet.title}")
    print(f"WORKSHEET_TITLE={worksheet.title}")
    print(f"HEADER_COLUMNS={len(SHEET_HEADERS)}")
    print(f"DATA_ROWS={count_nonempty_data_rows(values)}")
    print(f"PLAN_PUSH_TO_GOOGLE={action_counts[SyncAction.PUSH_TO_GOOGLE]}")
    print(f"PLAN_PULL_TO_SQLITE={action_counts[SyncAction.PULL_TO_SQLITE]}")
    print(f"PLAN_NO_CHANGE={action_counts[SyncAction.NO_CHANGE]}")
    print(f"PLAN_CONFLICT={action_counts[SyncAction.CONFLICT]}")


if __name__ == "__main__":
    main()

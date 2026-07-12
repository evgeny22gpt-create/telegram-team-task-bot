from __future__ import annotations

import argparse
from pathlib import Path
import sys

import gspread


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from config import load_settings  # noqa: E402
from database import initialize_database  # noqa: E402
from google_sync import SyncAction, execute_sync  # noqa: E402


READ_ONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
READ_WRITE_SCOPE = "https://www.googleapis.com/auth/spreadsheets"


def parse_args() -> argparse.Namespace:
    """Читает флаг --apply; без него всегда используется безопасный dry-run."""

    parser = argparse.ArgumentParser(
        description="Сравнить SQLite с Google Таблицей и показать план синхронизации."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="применить план; без этого флага данные не изменяются",
    )
    return parser.parse_args()


def main() -> None:
    """Открывает лист с минимально необходимыми правами и запускает синхронизацию."""

    args = parse_args()
    settings = load_settings()
    if not settings.google_sync_configured:
        raise RuntimeError(
            "Google-синхронизация не настроена: проверьте .env и JSON-ключ."
        )

    initialize_database(settings.db_path)
    scope = READ_WRITE_SCOPE if args.apply else READ_ONLY_SCOPE
    client = gspread.service_account(
        filename=str(settings.google_service_account_file),
        scopes=[scope],
    )
    spreadsheet = client.open_by_key(settings.google_spreadsheet_id)
    worksheet = spreadsheet.worksheet(settings.google_sheet_name)

    report = execute_sync(
        settings.db_path,
        worksheet,
        apply=args.apply,
        backup_dir=PROJECT_DIR / "backups",
    )

    print(f"SYNC_MODE={'apply' if args.apply else 'dry-run'}")
    print(f"PUSH_TO_GOOGLE={report.count(SyncAction.PUSH_TO_GOOGLE)}")
    print(f"PULL_TO_SQLITE={report.count(SyncAction.PULL_TO_SQLITE)}")
    print(f"NO_CHANGE={report.count(SyncAction.NO_CHANGE)}")
    print(f"CONFLICT={report.count(SyncAction.CONFLICT)}")
    print(f"CHANGES_APPLIED={'yes' if report.applied else 'no'}")
    if report.backup_path is not None:
        print(f"SQLITE_BACKUP={report.backup_path.name}")


if __name__ == "__main__":
    main()

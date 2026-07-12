from __future__ import annotations

from pathlib import Path
import sqlite3
import sys


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from config import load_settings  # noqa: E402
from database import initialize_database  # noqa: E402


def main() -> None:
    """Создаёт рабочую базу и печатает только её схему и число строк."""

    settings = load_settings()
    initialize_database(settings.db_path)

    connection = sqlite3.connect(settings.db_path)
    try:
        columns = connection.execute("PRAGMA table_info(tasks)").fetchall()
        row_count = connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    finally:
        connection.close()

    column_names = ",".join(column[1] for column in columns)
    print(f"DB_FILE={settings.db_path.name}")
    print(f"DB_SCHEMA={column_names}")
    print(f"DB_ROWS={row_count}")


if __name__ == "__main__":
    main()

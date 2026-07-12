from __future__ import annotations

import csv
from io import StringIO
from pathlib import Path
import sys


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from config import load_settings  # noqa: E402
from database import get_all_tasks  # noqa: E402
from exporter import build_tasks_csv  # noqa: E402


def main() -> None:
    """Создаёт проверочный CSV из рабочей базы и сверяет его структуру."""

    settings = load_settings()
    tasks = get_all_tasks(settings.db_path)
    payload = build_tasks_csv(tasks)

    output_dir = PROJECT_DIR / "evidence" / "exports"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "tasks_preview.csv"
    output_path.write_bytes(payload)

    decoded = payload.decode("utf-8-sig")
    rows = list(csv.reader(StringIO(decoded), delimiter=";"))

    print("CSV_BOM=<ok>" if payload.startswith(b"\xef\xbb\xbf") else "CSV_BOM=<missing>")
    print("CSV_HEADER=" + "|".join(rows[0]))
    print(f"CSV_ROWS={max(0, len(rows) - 1)}")
    print(f"CSV_FILE={output_path}")


if __name__ == "__main__":
    main()

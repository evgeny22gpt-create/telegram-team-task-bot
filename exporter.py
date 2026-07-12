from __future__ import annotations

from collections.abc import Sequence
import csv
from io import StringIO
import re

from database import DEFAULT_CATEGORY, DEFAULT_STATUS, Task


TELEGRAM_USERNAME_PATTERN = re.compile(r"^@[A-Za-z0-9_]{5,32}$")


def safe_spreadsheet_cell(value: object) -> str:
    """Не даёт пользовательскому тексту стать формулой в Excel/LibreOffice."""

    text = str(value)
    dangerous_start = text.lstrip().startswith(("=", "+", "-", "@"))
    if dangerous_start or text.startswith(("\t", "\r")):
        return "'" + text
    return text


def safe_user_cell(value: object) -> str:
    """Сохраняет обычный @username без апострофа, прочие подписи защищает."""

    text = str(value)
    if TELEGRAM_USERNAME_PATTERN.fullmatch(text):
        return text
    return safe_spreadsheet_cell(text)


def build_tasks_csv(tasks: Sequence[Task]) -> bytes:
    """Создаёт CSV в памяти и возвращает готовые для Telegram байты."""

    buffer = StringIO(newline="")
    writer = csv.writer(
        buffer,
        delimiter=";",
        quoting=csv.QUOTE_MINIMAL,
        lineterminator="\n",
    )

    writer.writerow(
        [
            "ID",
            "Задача",
            "Пользователь",
            "Создано (UTC)",
            "Статус",
            "Категория",
        ]
    )

    for task in tasks:
        writer.writerow(
            [
                task.id,
                safe_spreadsheet_cell(task.text),
                safe_user_cell(task.user),
                task.created_at,
                safe_spreadsheet_cell(task.status or DEFAULT_STATUS),
                safe_spreadsheet_cell(task.category or DEFAULT_CATEGORY),
            ]
        )

    # utf-8-sig добавляет BOM: Excel легче распознаёт русскую кодировку.
    return buffer.getvalue().encode("utf-8-sig")

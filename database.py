from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3


DEFAULT_STATUS = "Новая"
DEFAULT_CATEGORY = "Без категории"
ALLOWED_STATUSES = frozenset({"Новая", "В работе", "Готово", "Отложена"})


# SQL вынесен в константу, чтобы структура таблицы была видна в одном месте.
CREATE_TASKS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    user TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Новая',
    category TEXT NOT NULL DEFAULT 'Без категории',
    updated_at TEXT NOT NULL DEFAULT ''
)
"""


@dataclass(frozen=True, slots=True)
class Task:
    """Понятное Python-представление одной строки таблицы tasks."""

    id: int
    text: str
    user: str
    created_at: str
    status: str = DEFAULT_STATUS
    category: str = DEFAULT_CATEGORY
    updated_at: str = ""


def _connect(db_path: str | Path) -> sqlite3.Connection:
    """Открывает SQLite и настраивает удобный доступ к колонкам по имени."""

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(path, timeout=10.0)
    connection.row_factory = sqlite3.Row
    return connection


def _task_column_names(connection: sqlite3.Connection) -> set[str]:
    """Возвращает имена уже существующих столбцов таблицы tasks."""

    rows = connection.execute("PRAGMA table_info(tasks)").fetchall()
    return {str(row["name"]) for row in rows}


def _migrate_tasks_table(connection: sqlite3.Connection) -> None:
    """Без потери строк дополняет старую таблицу полями для синхронизации.

    ALTER TABLE выполняется только для отсутствующих столбцов. Благодаря этому
    миграцию безопасно запускать повторно при каждом старте приложения.
    """

    column_names = _task_column_names(connection)

    if "status" not in column_names:
        connection.execute(
            "ALTER TABLE tasks ADD COLUMN status TEXT NOT NULL DEFAULT 'Новая'"
        )
    if "category" not in column_names:
        connection.execute(
            "ALTER TABLE tasks ADD COLUMN category TEXT NOT NULL DEFAULT 'Без категории'"
        )
    if "updated_at" not in column_names:
        # SQLite требует постоянное значение DEFAULT при добавлении NOT NULL-столбца.
        connection.execute(
            "ALTER TABLE tasks ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''"
        )

    # Эти UPDATE также восстанавливают данные после возможной старой или
    # прерванной миграции, в которой столбец уже появился, но остался пустым.
    connection.execute(
        """
        UPDATE tasks
        SET status = ?
        WHERE status IS NULL OR TRIM(status) = ''
        """,
        (DEFAULT_STATUS,),
    )
    connection.execute(
        """
        UPDATE tasks
        SET category = ?
        WHERE category IS NULL OR TRIM(category) = ''
        """,
        (DEFAULT_CATEGORY,),
    )
    # Для прежних задач временем последнего изменения считаем время их создания.
    connection.execute(
        """
        UPDATE tasks
        SET updated_at = created_at
        WHERE updated_at IS NULL OR TRIM(updated_at) = ''
        """
    )


def initialize_database(db_path: str | Path) -> None:
    """Создаёт таблицу tasks или безопасно обновляет её старую структуру.

    Конструкция IF NOT EXISTS делает функцию безопасной для каждого запуска:
    существующая таблица и данные не удаляются и не создаются заново. После неё
    миграция добавляет только отсутствующие столбцы для Google-синхронизации.
    """

    connection = _connect(db_path)
    try:
        connection.execute(CREATE_TASKS_TABLE_SQL)
        _migrate_tasks_table(connection)
        connection.commit()
    except Exception:
        # При ошибке ни одна часть миграции не должна остаться полуприменённой.
        connection.rollback()
        raise
    finally:
        connection.close()


def _validate_task_text(text: str) -> str:
    """Убирает пробелы по краям и не разрешает сохранить пустую задачу."""

    clean_text = text.strip()
    if not clean_text:
        raise ValueError("Текст задачи не должен быть пустым.")
    return clean_text


def _validate_user(user: str) -> str:
    """Проверяет подпись автора задачи перед записью в базу."""

    clean_user = user.strip()
    if not clean_user:
        raise ValueError("Имя пользователя не должно быть пустым.")
    return clean_user


def add_task(
    db_path: str | Path,
    text: str,
    user: str,
    *,
    created_at: str | None = None,
    status: str = DEFAULT_STATUS,
    category: str = DEFAULT_CATEGORY,
) -> int:
    """Добавляет задачу и возвращает её новый числовой id.

    created_at можно передать явно в тестах. В обычной работе функция сама
    записывает текущее время UTC в однозначном формате ISO 8601.
    """

    clean_text = _validate_task_text(text)
    clean_user = _validate_user(user)
    clean_status = status.strip()
    if clean_status not in ALLOWED_STATUSES:
        allowed = ", ".join(sorted(ALLOWED_STATUSES))
        raise ValueError(f"Неизвестный статус. Разрешены: {allowed}.")
    clean_category = category.strip() or DEFAULT_CATEGORY
    timestamp = created_at or datetime.now(timezone.utc).isoformat(timespec="seconds")

    connection = _connect(db_path)
    try:
        # Знаки ? отделяют SQL-команду от пользовательских данных. Это безопаснее,
        # чем вставлять текст задачи в запрос через f-строку.
        cursor = connection.execute(
            """
            INSERT INTO tasks (
                text, user, created_at, status, category, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                clean_text,
                clean_user,
                timestamp,
                clean_status,
                clean_category,
                timestamp,
            ),
        )
        connection.commit()
        task_id = cursor.lastrowid
    finally:
        connection.close()

    if task_id is None:
        raise RuntimeError("SQLite не вернул id новой задачи.")
    return int(task_id)


def get_all_tasks(db_path: str | Path) -> list[Task]:
    """Возвращает все задачи в порядке их добавления."""

    connection = _connect(db_path)
    try:
        rows = connection.execute(
            """
            SELECT id, text, user, created_at, status, category, updated_at
            FROM tasks
            ORDER BY id ASC
            """
        ).fetchall()
    finally:
        connection.close()

    return [Task(**dict(row)) for row in rows]


def upsert_tasks_from_sync(db_path: str | Path, tasks: list[Task]) -> None:
    """Одной транзакцией добавляет или обновляет задачи, пришедшие из синхронизации.

    UPSERT означает: если такого id ещё нет — создать строку; если id уже есть —
    заменить её поля. Транзакция гарантирует принцип «всё или ничего» для SQLite.
    """

    prepared_rows: list[tuple[object, ...]] = []
    for task in tasks:
        clean_text = _validate_task_text(task.text)
        clean_user = _validate_user(task.user)
        clean_status = task.status.strip()
        if clean_status not in ALLOWED_STATUSES:
            raise ValueError(f"Неизвестный статус задачи #{task.id}: {task.status!r}.")
        clean_category = task.category.strip() or DEFAULT_CATEGORY
        if task.id <= 0:
            raise ValueError("ID синхронизируемой задачи должен быть положительным.")
        if not task.created_at.strip() or not task.updated_at.strip():
            raise ValueError(f"У задачи #{task.id} отсутствует обязательная дата.")

        prepared_rows.append(
            (
                task.id,
                clean_text,
                clean_user,
                task.created_at.strip(),
                clean_status,
                clean_category,
                task.updated_at.strip(),
            )
        )

    connection = _connect(db_path)
    try:
        connection.executemany(
            """
            INSERT INTO tasks (
                id, text, user, created_at, status, category, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                text = excluded.text,
                user = excluded.user,
                created_at = excluded.created_at,
                status = excluded.status,
                category = excluded.category,
                updated_at = excluded.updated_at
            """,
            prepared_rows,
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def create_database_backup(
    db_path: str | Path,
    backup_dir: str | Path,
    *,
    timestamp: str,
) -> Path:
    """Создаёт проверенную резервную копию SQLite встроенным backup API."""

    source_path = Path(db_path)
    target_dir = Path(backup_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"tasks_before_sync_{timestamp}.db"
    if target_path.exists():
        raise FileExistsError(f"Резервная копия уже существует: {target_path}")

    source = _connect(source_path)
    destination = sqlite3.connect(target_path)
    try:
        source.backup(destination)
        integrity = destination.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(
                f"Проверка резервной копии SQLite завершилась ошибкой: {integrity}"
            )
    except Exception:
        destination.close()
        source.close()
        target_path.unlink(missing_ok=True)
        raise
    else:
        destination.close()
        source.close()

    return target_path

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Iterable, Protocol, Sequence

from database import (
    ALLOWED_STATUSES,
    DEFAULT_CATEGORY,
    Task,
    create_database_backup,
    get_all_tasks,
    upsert_tasks_from_sync,
)


SHEET_HEADERS = (
    "ID",
    "Задача",
    "Пользователь",
    "Создано (UTC)",
    "Статус",
    "Категория",
    "Обновлено (UTC)",
)


class SyncAction(str, Enum):
    """Перечисляет возможные решения для одной задачи."""

    PUSH_TO_GOOGLE = "push_to_google"
    PULL_TO_SQLITE = "pull_to_sqlite"
    NO_CHANGE = "no_change"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class SyncDecision:
    """Описывает безопасное действие, которое позже выполнит синхронизатор."""

    task_id: int
    action: SyncAction
    reason: str
    source_task: Task | None = None


@dataclass(frozen=True, slots=True)
class SyncReport:
    """Содержит план, факт применения и путь к резервной копии."""

    decisions: tuple[SyncDecision, ...]
    applied: bool
    backup_path: Path | None = None

    def count(self, action: SyncAction) -> int:
        """Считает решения выбранного типа."""

        return sum(decision.action is action for decision in self.decisions)


class WorksheetProtocol(Protocol):
    """Минимальный интерфейс gspread.Worksheet, нужный синхронизатору."""

    def get(self, range_name: str) -> Sequence[Sequence[str]]: ...

    def batch_update(
        self,
        data: list[dict[str, object]],
        *,
        value_input_option: str,
    ) -> object: ...

    def append_rows(
        self,
        values: list[list[str]],
        *,
        value_input_option: str,
    ) -> object: ...


class SyncConflictError(RuntimeError):
    """Сообщает, что применение заблокировано неоднозначными версиями."""


def parse_utc_timestamp(value: str) -> datetime:
    """Преобразует ISO 8601 в UTC-время и отклоняет неоднозначное время без зоны."""

    clean_value = value.strip()
    if clean_value.endswith("Z"):
        clean_value = clean_value[:-1] + "+00:00"

    try:
        result = datetime.fromisoformat(clean_value)
    except ValueError as error:
        raise ValueError(f"Некорректная дата ISO 8601: {value!r}.") from error

    if result.tzinfo is None:
        raise ValueError(f"У даты отсутствует часовой пояс: {value!r}.")
    return result.astimezone(timezone.utc)


def task_to_sheet_row(task: Task) -> list[str]:
    """Преобразует объект Task в семь ячеек Google Таблицы."""

    return [
        str(task.id),
        task.text,
        task.user,
        task.created_at,
        task.status,
        task.category,
        task.updated_at,
    ]


def task_from_sheet_row(row: Sequence[str], *, row_number: int) -> Task:
    """Проверяет строку Google Таблицы и превращает её в Task."""

    cells = [str(cell).strip() for cell in row]
    if len(cells) > len(SHEET_HEADERS):
        raise ValueError(f"В строке {row_number} больше семи поддерживаемых колонок.")
    cells.extend([""] * (len(SHEET_HEADERS) - len(cells)))

    try:
        task_id = int(cells[0])
    except ValueError as error:
        raise ValueError(f"В строке {row_number} указан некорректный ID.") from error
    if task_id <= 0:
        raise ValueError(f"В строке {row_number} ID должен быть положительным.")

    text, user, created_at = cells[1], cells[2], cells[3]
    status = cells[4]
    category = cells[5] or DEFAULT_CATEGORY
    updated_at = cells[6]

    if not text:
        raise ValueError(f"В строке {row_number} отсутствует текст задачи.")
    if not user:
        raise ValueError(f"В строке {row_number} отсутствует пользователь.")
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"В строке {row_number} указан неизвестный статус: {status!r}.")

    # Даты проверяем заранее, чтобы ошибка не появилась посреди записи в базу.
    parse_utc_timestamp(created_at)
    parse_utc_timestamp(updated_at)

    return Task(
        id=task_id,
        text=text,
        user=user,
        created_at=created_at,
        status=status,
        category=category,
        updated_at=updated_at,
    )


def tasks_from_sheet_values(values: Sequence[Sequence[str]]) -> list[Task]:
    """Проверяет заголовки и читает все непустые строки листа."""

    if not values:
        raise ValueError("Google Таблица не содержит строки заголовков.")

    actual_headers = tuple(str(cell).strip() for cell in values[0])
    if actual_headers != SHEET_HEADERS:
        raise ValueError("Заголовки Google Таблицы не совпадают со структурой проекта.")

    tasks: list[Task] = []
    seen_ids: set[int] = set()
    for row_number, row in enumerate(values[1:], start=2):
        if not any(str(cell).strip() for cell in row):
            continue
        task = task_from_sheet_row(row, row_number=row_number)
        if task.id in seen_ids:
            raise ValueError(f"ID {task.id} повторяется в Google Таблице.")
        seen_ids.add(task.id)
        tasks.append(task)
    return tasks


def _task_content(task: Task) -> tuple[str, str, str, str, str]:
    """Возвращает изменяемое содержимое без служебных id и updated_at."""

    return (
        task.text,
        task.user,
        task.created_at,
        task.status,
        task.category,
    )


def decide_task_sync(sqlite_task: Task, google_task: Task) -> SyncDecision:
    """Выбирает направление синхронизации для двух версий одной задачи."""

    if sqlite_task.id != google_task.id:
        raise ValueError("Нельзя сравнивать задачи с разными ID.")

    if _task_content(sqlite_task) == _task_content(google_task):
        return SyncDecision(
            task_id=sqlite_task.id,
            action=SyncAction.NO_CHANGE,
            reason="Данные совпадают.",
        )

    sqlite_time = parse_utc_timestamp(sqlite_task.updated_at)
    google_time = parse_utc_timestamp(google_task.updated_at)
    if sqlite_time > google_time:
        return SyncDecision(
            task_id=sqlite_task.id,
            action=SyncAction.PUSH_TO_GOOGLE,
            reason="Версия SQLite обновлена позже.",
            source_task=sqlite_task,
        )
    if google_time > sqlite_time:
        return SyncDecision(
            task_id=sqlite_task.id,
            action=SyncAction.PULL_TO_SQLITE,
            reason="Версия Google Таблицы обновлена позже.",
            source_task=google_task,
        )

    return SyncDecision(
        task_id=sqlite_task.id,
        action=SyncAction.CONFLICT,
        reason="Данные различаются, но updated_at одинаковый.",
    )


def _tasks_by_id(tasks: Iterable[Task], *, source_name: str) -> dict[int, Task]:
    """Строит индекс по ID и останавливается при неоднозначных дублях."""

    result: dict[int, Task] = {}
    for task in tasks:
        if task.id in result:
            raise ValueError(f"ID {task.id} повторяется в источнике {source_name}.")
        result[task.id] = task
    return result


def build_sync_plan(
    sqlite_tasks: Iterable[Task],
    google_tasks: Iterable[Task],
) -> list[SyncDecision]:
    """Строит детерминированный план синхронизации в порядке ID."""

    sqlite_by_id = _tasks_by_id(sqlite_tasks, source_name="SQLite")
    google_by_id = _tasks_by_id(google_tasks, source_name="Google")

    decisions: list[SyncDecision] = []
    for task_id in sorted(sqlite_by_id.keys() | google_by_id.keys()):
        sqlite_task = sqlite_by_id.get(task_id)
        google_task = google_by_id.get(task_id)

        if sqlite_task is None and google_task is not None:
            decisions.append(
                SyncDecision(
                    task_id=task_id,
                    action=SyncAction.PULL_TO_SQLITE,
                    reason="Задача существует только в Google Таблице.",
                    source_task=google_task,
                )
            )
        elif google_task is None and sqlite_task is not None:
            decisions.append(
                SyncDecision(
                    task_id=task_id,
                    action=SyncAction.PUSH_TO_GOOGLE,
                    reason="Задача существует только в SQLite.",
                    source_task=sqlite_task,
                )
            )
        elif sqlite_task is not None and google_task is not None:
            decisions.append(decide_task_sync(sqlite_task, google_task))

    return decisions


def _google_row_numbers(values: Sequence[Sequence[str]]) -> dict[int, int]:
    """Связывает ID задачи с фактическим номером строки Google Таблицы."""

    row_numbers: dict[int, int] = {}
    for row_number, row in enumerate(values[1:], start=2):
        if not any(str(cell).strip() for cell in row):
            continue
        task_id = int(str(row[0]).strip())
        row_numbers[task_id] = row_number
    return row_numbers


def execute_sync(
    db_path: str | Path,
    worksheet: WorksheetProtocol,
    *,
    apply: bool = False,
    backup_dir: str | Path | None = None,
    now: datetime | None = None,
) -> SyncReport:
    """Строит план и, только при apply=True, применяет безопасные изменения.

    По умолчанию функция работает как dry-run. При реальной записи сначала
    создаётся резервная копия SQLite. Любой конфликт блокирует весь запуск.
    """

    values = worksheet.get("A:G")
    google_tasks = tasks_from_sheet_values(values)
    sqlite_tasks = get_all_tasks(db_path)
    decisions = tuple(build_sync_plan(sqlite_tasks, google_tasks))
    preview = SyncReport(decisions=decisions, applied=False)

    if not apply:
        return preview

    conflicts = [
        decision.task_id
        for decision in decisions
        if decision.action is SyncAction.CONFLICT
    ]
    if conflicts:
        ids = ", ".join(str(task_id) for task_id in conflicts)
        raise SyncConflictError(
            f"Синхронизация заблокирована конфликтами в задачах: {ids}."
        )

    changes = [
        decision
        for decision in decisions
        if decision.action in {SyncAction.PUSH_TO_GOOGLE, SyncAction.PULL_TO_SQLITE}
    ]
    if not changes:
        return preview

    timestamp_value = now or datetime.now(timezone.utc)
    timestamp = timestamp_value.astimezone(timezone.utc).strftime(
        "%Y%m%d_%H%M%S_%f"
    )
    backup_path = create_database_backup(
        db_path,
        backup_dir or Path(db_path).resolve().parent / "backups",
        timestamp=timestamp,
    )

    pull_tasks = [
        decision.source_task
        for decision in changes
        if decision.action is SyncAction.PULL_TO_SQLITE
        and decision.source_task is not None
    ]
    row_numbers = _google_row_numbers(values)
    update_requests: list[dict[str, object]] = []
    append_values: list[list[str]] = []
    for decision in changes:
        if (
            decision.action is not SyncAction.PUSH_TO_GOOGLE
            or decision.source_task is None
        ):
            continue
        row = task_to_sheet_row(decision.source_task)
        row_number = row_numbers.get(decision.task_id)
        if row_number is None:
            append_values.append(row)
        else:
            update_requests.append(
                {
                    "range": f"A{row_number}:G{row_number}",
                    "values": [row],
                }
            )

    try:
        # Сначала применяем входящие изменения одной транзакцией SQLite.
        # Если последующая отправка в Google прервётся, более новая SQLite-версия
        # сохранится и следующий запуск снова предложит PUSH_TO_GOOGLE.
        if pull_tasks:
            upsert_tasks_from_sync(db_path, pull_tasks)
        if update_requests:
            worksheet.batch_update(
                update_requests,
                value_input_option="RAW",
            )
        if append_values:
            worksheet.append_rows(
                append_values,
                value_input_option="RAW",
            )
    except Exception as error:
        raise RuntimeError(
            "Применение синхронизации прервано. "
            f"Резервная копия SQLite: {backup_path}"
        ) from error

    return SyncReport(
        decisions=decisions,
        applied=True,
        backup_path=backup_path,
    )

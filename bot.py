from __future__ import annotations

import asyncio
from collections.abc import Collection, Sequence
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command, CommandStart
from aiogram.filters.command import CommandObject
from aiogram.types import BufferedInputFile, Message
import gspread

from config import Settings, load_settings
from database import Task, add_task, get_all_tasks, initialize_database
from exporter import build_tasks_csv
from google_sync import (
    SyncAction,
    SyncConflictError,
    SyncReport,
    execute_sync,
)


# Router хранит правила обработки сообщений нашего приложения.
router = Router(name="team_tasks")

# Москва постоянно использует UTC+3. Фиксированная зона не требует внешних пакетов.
MOSCOW_TZ = timezone(timedelta(hours=3), name="МСК")
GOOGLE_SHEETS_READ_ONLY_SCOPE = (
    "https://www.googleapis.com/auth/spreadsheets.readonly"
)
GOOGLE_SHEETS_READ_WRITE_SCOPE = "https://www.googleapis.com/auth/spreadsheets"


def build_start_text(first_name: str | None) -> str:
    """Создаёт приветствие отдельно от Telegram, чтобы его легко тестировать."""

    clean_name = first_name.strip() if first_name and first_name.strip() else "друг"
    return (
        f"Привет, {clean_name}! 👋\n\n"
        "Я командный бот для хранения задач.\n"
        "Доступные команды:\n"
        "/start — показать это приветствие;\n"
        "/add Текст задачи — сохранить новую задачу.\n\n"
        "/list — показать все сохранённые задачи;\n"
        "/list_csv — выгрузить задачи в CSV;\n"
        "/sync — проверить план синхронизации с Google Таблицей;\n"
        "/sync_apply confirm — применить план (только владелец);\n"
        "/whoami — показать ваш постоянный Telegram ID."
    )


def build_user_label(username: str | None, full_name: str | None) -> str:
    """Выбирает понятную подпись автора для колонки user в SQLite."""

    clean_username = username.strip().lstrip("@") if username else ""
    if clean_username:
        return f"@{clean_username}"

    clean_full_name = full_name.strip() if full_name else ""
    return clean_full_name or "Неизвестный пользователь"


def build_whoami_text(user_id: int, username: str | None) -> str:
    """Формирует ответ с постоянным Telegram ID без каких-либо секретов."""

    public_name = f"@{username.strip().lstrip('@')}" if username and username.strip() else "не задан"
    return (
        "Ваш Telegram ID 👤\n\n"
        f"ID: {user_id}\n"
        f"Username: {public_name}\n\n"
        "Числовой ID нужен, чтобы разрешить опасные команды только владельцу бота."
    )


def build_add_success_text(task_id: int, text: str, user: str) -> str:
    """Создаёт подтверждение, которое пользователь видит после записи."""

    return (
        f"Задача #{task_id} сохранена ✅\n\n"
        f"Текст: {text.strip()}\n"
        f"Автор: {user}"
    )


def format_created_at(value: str) -> str:
    """Преобразует сохранённое UTC-время в понятное московское время."""

    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        # Если в старой записи оказался неизвестный формат, показываем его как есть.
        return value

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)

    return moment.astimezone(MOSCOW_TZ).strftime("%d.%m.%Y %H:%M МСК")


def build_tasks_list_text(tasks: Sequence[Task]) -> str:
    """Формирует читаемый Telegram-список из объектов Task."""

    if not tasks:
        return (
            "Список задач пока пуст 📭\n\n"
            "Добавьте первую задачу:\n"
            "/add Подготовить вопросы к встрече"
        )

    lines = ["Список задач 📋", ""]
    for task in tasks:
        # Переводы строк убираются только для показа; исходный текст в БД не меняется.
        one_line_text = " ".join(task.text.split())
        lines.extend(
            [
                f"#{task.id} {one_line_text}",
                f"Автор: {task.user}",
                f"Создано: {format_created_at(task.created_at)}",
                "",
            ]
        )

    return "\n".join(lines).rstrip()


def build_csv_filename(moment: datetime | None = None) -> str:
    """Создаёт уникальное и понятное имя CSV по московскому времени."""

    current = moment or datetime.now(MOSCOW_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=MOSCOW_TZ)
    current = current.astimezone(MOSCOW_TZ)
    return current.strftime("tasks_%Y-%m-%d_%H-%M_msk.csv")


def build_sync_preview_text(report: SyncReport) -> str:
    """Формирует понятный результат dry-run без содержимого самих задач."""

    push_count = report.count(SyncAction.PUSH_TO_GOOGLE)
    pull_count = report.count(SyncAction.PULL_TO_SQLITE)
    unchanged_count = report.count(SyncAction.NO_CHANGE)
    conflict_count = report.count(SyncAction.CONFLICT)

    lines = [
        "План синхронизации 🔎",
        "",
        f"SQLite → Google: {push_count}",
        f"Google → SQLite: {pull_count}",
        f"Без изменений: {unchanged_count}",
        f"Конфликты: {conflict_count}",
        "",
    ]
    if conflict_count:
        lines.append(
            "⚠️ Есть конфликтующие версии. Автоматическая запись заблокирована."
        )
    elif push_count or pull_count:
        lines.append(
            "Изменения найдены. Команда /sync работает как безопасный dry-run "
            "и пока ничего не записывает."
        )
    else:
        lines.append("SQLite и Google Таблица уже совпадают ✅")
    return "\n".join(lines)


def is_sync_owner(
    user_id: int | None,
    owner_ids: Collection[int],
) -> bool:
    """Разрешает опасную команду только ID из локального списка владельцев."""

    return user_id is not None and user_id in owner_ids


def build_sync_apply_text(report: SyncReport) -> str:
    """Сообщает владельцу результат применения без содержимого задач."""

    if not report.applied:
        return "SQLite и Google Таблица уже совпадают. Изменения не требуются ✅"

    lines = [
        "Синхронизация применена ✅",
        "",
        f"SQLite → Google: {report.count(SyncAction.PUSH_TO_GOOGLE)}",
        f"Google → SQLite: {report.count(SyncAction.PULL_TO_SQLITE)}",
    ]
    if report.backup_path is not None:
        lines.extend(["", f"Резервная копия: {report.backup_path.name}"])
    return "\n".join(lines)


def run_google_sync_preview(settings: Settings) -> SyncReport:
    """Подключается к Google с правами только чтения и строит dry-run план."""

    client = gspread.service_account(
        filename=str(settings.google_service_account_file),
        scopes=[GOOGLE_SHEETS_READ_ONLY_SCOPE],
    )
    spreadsheet = client.open_by_key(settings.google_spreadsheet_id)
    worksheet = spreadsheet.worksheet(settings.google_sheet_name)
    return execute_sync(settings.db_path, worksheet, apply=False)


def run_google_sync_apply(settings: Settings) -> SyncReport:
    """Подключается с правом записи и применяет защищённый план синхронизации."""

    client = gspread.service_account(
        filename=str(settings.google_service_account_file),
        scopes=[GOOGLE_SHEETS_READ_WRITE_SCOPE],
    )
    spreadsheet = client.open_by_key(settings.google_spreadsheet_id)
    worksheet = spreadsheet.worksheet(settings.google_sheet_name)
    return execute_sync(
        settings.db_path,
        worksheet,
        apply=True,
        backup_dir=settings.db_path.resolve().parent / "backups",
    )


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    """Отвечает на /start персональным приветствием."""

    first_name = message.from_user.first_name if message.from_user else None
    await message.answer(build_start_text(first_name))


@router.message(Command("whoami"))
async def handle_whoami(message: Message) -> None:
    """Показывает отправителю его числовой Telegram ID."""

    telegram_user = message.from_user
    if telegram_user is None:
        await message.answer("Telegram не передал данные пользователя для этого сообщения.")
        return

    await message.answer(
        build_whoami_text(telegram_user.id, telegram_user.username)
    )


@router.message(Command("add"))
async def handle_add(
    message: Message,
    command: CommandObject,
    db_path: Path,
) -> None:
    """Обрабатывает `/add текст`, сохраняет задачу и сообщает её id."""

    if not command.args:
        await message.answer(
            "После /add напишите текст задачи.\n\n"
            "Пример: /add Подготовить вопросы к встрече"
        )
        return

    telegram_user = message.from_user
    user_label = build_user_label(
        telegram_user.username if telegram_user else None,
        telegram_user.full_name if telegram_user else None,
    )

    try:
        task_id = add_task(db_path, command.args, user_label)
    except ValueError as error:
        await message.answer(f"Не удалось добавить задачу: {error}")
        return

    await message.answer(build_add_success_text(task_id, command.args, user_label))


@router.message(Command("list"))
async def handle_list(message: Message, db_path: Path) -> None:
    """Читает все задачи из SQLite и отправляет их в порядке добавления."""

    tasks = get_all_tasks(db_path)
    await message.answer(build_tasks_list_text(tasks))


@router.message(Command("list_csv"))
async def handle_list_csv(message: Message, db_path: Path) -> None:
    """Создаёт CSV в памяти и отправляет его пользователю документом."""

    tasks = get_all_tasks(db_path)
    if not tasks:
        await message.answer(
            "Выгружать пока нечего 📭\n\n"
            "Добавьте первую задачу командой /add."
        )
        return

    document = BufferedInputFile(
        build_tasks_csv(tasks),
        filename=build_csv_filename(),
    )
    await message.answer_document(
        document=document,
        caption=f"Выгружено задач: {len(tasks)}",
    )


@router.message(Command("sync"))
async def handle_sync(message: Message, settings: Settings) -> None:
    """Показывает план Google-синхронизации, не изменяя ни один источник."""

    if not settings.google_sync_configured:
        await message.answer(
            "Google-синхронизация пока не настроена. Проверьте .env и JSON-ключ."
        )
        return

    await message.answer("Проверяю SQLite и Google Таблицу…")
    try:
        # gspread выполняет обычные блокирующие HTTP-запросы. to_thread переносит
        # их из цикла aiogram, поэтому бот продолжает отвечать другим пользователям.
        report = await asyncio.to_thread(run_google_sync_preview, settings)
    except Exception:
        logging.exception("Не удалось построить план Google-синхронизации")
        await message.answer(
            "Не удалось проверить Google Таблицу. Подробности записаны в журнал бота."
        )
        return

    await message.answer(build_sync_preview_text(report))


@router.message(Command("sync_apply"))
async def handle_sync_apply(
    message: Message,
    command: CommandObject,
    settings: Settings,
) -> None:
    """Применяет синхронизацию только после проверки владельца и подтверждения."""

    telegram_user = message.from_user
    user_id = telegram_user.id if telegram_user else None
    if not is_sync_owner(user_id, settings.telegram_owner_ids):
        await message.answer("Эта команда доступна только владельцу бота.")
        return

    confirmation = command.args.strip().casefold() if command.args else ""
    if confirmation != "confirm":
        await message.answer(
            "Команда может изменить SQLite и Google Таблицу.\n\n"
            "Сначала проверьте план: /sync\n"
            "Для применения отправьте: /sync_apply confirm"
        )
        return

    await message.answer("Применяю проверенный план синхронизации…")
    try:
        report = await asyncio.to_thread(run_google_sync_apply, settings)
    except SyncConflictError as error:
        await message.answer(f"Синхронизация не применена ⚠️\n\n{error}")
        return
    except Exception:
        logging.exception("Не удалось применить Google-синхронизацию")
        await message.answer(
            "Не удалось применить синхронизацию. Подробности записаны в журнал бота."
        )
        return

    await message.answer(build_sync_apply_text(report))


async def main() -> None:
    """Собирает части приложения и запускает постоянное получение сообщений."""

    # config.py возвращает проверенный токен и стабильный путь к базе.
    settings = load_settings()

    # Таблица создаётся до запуска Telegram, поэтому обработчики увидят готовую БД.
    initialize_database(settings.db_path)

    # Dispatcher — главный диспетчер, Router — наши конкретные правила команд.
    dispatcher = Dispatcher()
    dispatcher.include_router(router)

    # Общий путь кладём в контекст Dispatcher. Aiogram передаст его обработчику
    # handle_add по имени параметра db_path — это встроенный механизм зависимостей.
    dispatcher["db_path"] = settings.db_path
    dispatcher["settings"] = settings

    # Bot использует секретный токен только для запросов к Telegram API.
    bot = Bot(token=settings.bot_token)
    try:
        bot_info = await bot.get_me()
        logging.info("Запускается бот @%s", bot_info.username)

        # Polling держит процесс запущенным и получает новые события Telegram.
        await dispatcher.start_polling(
            bot,
            close_bot_session=False,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
    finally:
        # Сетевую сессию нужно закрыть даже после Ctrl+C или ошибки запуска.
        await bot.session.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    asyncio.run(main())

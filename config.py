from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


# Все локальные пути строятся от папки проекта, а не от текущей папки терминала.
PROJECT_DIR = Path(__file__).resolve().parent
ENV_FILE = PROJECT_DIR / ".env"


@dataclass(frozen=True, slots=True)
class Settings:
    """Хранит уже проверенные настройки приложения."""

    bot_token: str
    db_path: Path
    google_spreadsheet_id: str
    google_sheet_name: str
    google_service_account_file: Path
    telegram_owner_ids: frozenset[int]

    @property
    def google_sync_configured(self) -> bool:
        """Показывает, готовы ли обязательные настройки Google-синхронизации."""

        return bool(
            self.google_spreadsheet_id
            and self.google_sheet_name
            and self.google_service_account_file.is_file()
        )


def _remove_matching_quotes(value: str) -> str:
    """Убирает одну пару одинаковых кавычек вокруг значения из .env."""

    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def load_env_fallback(path: Path = ENV_FILE) -> None:
    """Загружает простой .env, не заменяя переменные процесса."""

    if not path.exists():
        return

    for source_line in path.read_text(encoding="utf-8").splitlines():
        line = source_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = _remove_matching_quotes(value.strip())
        if key:
            # setdefault сохраняет приоритет системной переменной окружения.
            os.environ.setdefault(key, value)


def _resolve_project_path(configured_value: str, default_value: str) -> Path:
    """Преобразует путь из настроек в абсолютный путь внутри проекта."""

    value = configured_value.strip() or default_value
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_DIR / path
    return path


def _parse_telegram_owner_ids(value: str) -> frozenset[int]:
    """Преобразует список Telegram ID из `.env` в проверенное множество чисел."""

    owner_ids: set[int] = set()
    for item in value.split(","):
        clean_item = item.strip()
        if not clean_item:
            continue
        try:
            owner_id = int(clean_item)
        except ValueError as error:
            raise RuntimeError(
                "TELEGRAM_OWNER_IDS должен содержать числовые ID через запятую."
            ) from error
        if owner_id <= 0:
            raise RuntimeError("Telegram ID владельца должен быть положительным.")
        owner_ids.add(owner_id)
    return frozenset(owner_ids)


def load_settings() -> Settings:
    """Читает настройки и останавливает запуск при отсутствующем токене."""

    load_env_fallback()

    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token or token == "PASTE_YOUR_BOTFATHER_TOKEN_HERE":
        raise RuntimeError(
            "BOT_TOKEN не настроен. Добавьте токен в переменную процесса "
            "или локальный файл .env."
        )

    db_path = _resolve_project_path(
        os.environ.get("TASKS_DB", ""),
        "tasks.db",
    )

    # Google-настройки пока необязательны: без них основные команды бота
    # продолжают работать, а будущая команда синхронизации покажет подсказку.
    spreadsheet_id = os.environ.get("GOOGLE_SPREADSHEET_ID", "").strip()
    sheet_name = os.environ.get("GOOGLE_SHEET_NAME", "").strip() or "Задачи"
    service_account_file = _resolve_project_path(
        os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", ""),
        "credentials/google-service-account.json",
    )
    telegram_owner_ids = _parse_telegram_owner_ids(
        os.environ.get("TELEGRAM_OWNER_IDS", "")
    )

    return Settings(
        bot_token=token,
        db_path=db_path,
        google_spreadsheet_id=spreadsheet_id,
        google_sheet_name=sheet_name,
        google_service_account_file=service_account_file,
        telegram_owner_ids=telegram_owner_ids,
    )

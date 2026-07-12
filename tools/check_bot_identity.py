from __future__ import annotations

import asyncio
from pathlib import Path
import sys

from aiogram import Bot


# Добавляем корень проекта, чтобы служебная проверка могла импортировать config.py.
PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from config import load_settings  # noqa: E402


EXPECTED_USERNAME = "evgeny_team_tasks_2026_bot"


async def check_identity() -> None:
    """Запрашивает getMe и печатает только публичный username, не токен."""

    settings = load_settings()
    bot = Bot(token=settings.bot_token)
    try:
        bot_info = await bot.get_me()
    finally:
        await bot.session.close()

    actual_username = bot_info.username or ""
    if actual_username.casefold() != EXPECTED_USERNAME.casefold():
        raise RuntimeError(
            "Токен принадлежит другому боту: "
            f"ожидался @{EXPECTED_USERNAME}, получен @{actual_username or '<без username>'}."
        )

    print(f"BOT_IDENTITY=@{actual_username} <verified>")


if __name__ == "__main__":
    asyncio.run(check_identity())

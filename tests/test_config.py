from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from config import load_settings


class GoogleConfigTests(unittest.TestCase):
    """Проверяет Google-настройки без чтения настоящего .env и секретов."""

    def test_google_sync_is_ready_when_id_and_key_file_exist(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            key_file = root / "service-account.json"
            key_file.write_text("{}", encoding="utf-8")

            environment = {
                "BOT_TOKEN": "test-token",
                "TASKS_DB": str(root / "tasks.db"),
                "GOOGLE_SPREADSHEET_ID": "test-spreadsheet-id",
                "GOOGLE_SHEET_NAME": "Задачи",
                "GOOGLE_SERVICE_ACCOUNT_FILE": str(key_file),
                "TELEGRAM_OWNER_IDS": "111, 222,111",
            }
            with (
                patch.dict(os.environ, environment, clear=True),
                patch("config.load_env_fallback"),
            ):
                settings = load_settings()

            self.assertEqual("test-spreadsheet-id", settings.google_spreadsheet_id)
            self.assertEqual("Задачи", settings.google_sheet_name)
            self.assertTrue(settings.google_sync_configured)
            self.assertEqual(frozenset({111, 222}), settings.telegram_owner_ids)

    def test_google_sync_is_not_ready_without_key_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            environment = {
                "BOT_TOKEN": "test-token",
                "GOOGLE_SPREADSHEET_ID": "test-spreadsheet-id",
                "GOOGLE_SERVICE_ACCOUNT_FILE": str(root / "missing.json"),
            }
            with (
                patch.dict(os.environ, environment, clear=True),
                patch("config.load_env_fallback"),
            ):
                settings = load_settings()

            self.assertFalse(settings.google_sync_configured)

    def test_invalid_owner_id_is_rejected(self) -> None:
        environment = {
            "BOT_TOKEN": "test-token",
            "TELEGRAM_OWNER_IDS": "not-a-number",
        }
        with (
            patch.dict(os.environ, environment, clear=True),
            patch("config.load_env_fallback"),
        ):
            with self.assertRaisesRegex(RuntimeError, "числовые ID"):
                load_settings()


if __name__ == "__main__":
    unittest.main()

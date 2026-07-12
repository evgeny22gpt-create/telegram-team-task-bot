# Проверка Google Sheets API

Дата проверки: 2026-07-12.

## Проект

- Project name: Telegram Tasks Bot 2026
- Project ID: `[redacted for public repository]`

## API

- Название: Google Sheets API
- Service name: sheets.googleapis.com
- Тип: Public API
- Status: Enabled
- Страница проверки: Google Cloud Console → Google Sheets API → Overview.

## Подтверждение

- верхняя панель показывает проект Telegram Tasks Bot 2026;
- страница API/Service Details показывает Status: Enabled;
- вместо кнопки Enable отображается кнопка Disable API;
- API включён только после явного выбора нужного проекта.

## Границы шага

- Google Drive API не включался;
- другие Google Workspace API не включались;
- Start free не нажимался;
- сервисный аккаунт и JSON-ключ пока не создавались.

## Следующий отдельный шаг

Создать сервисный аккаунт для Python-бота и сохранить JSON-ключ только локально
в исключённой из Git папке credentials.

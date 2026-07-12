# Проверка публикации на GitHub

Дата проверки: 2026-07-12 (МСК).

## Репозиторий

- URL: https://github.com/evgeny22gpt-create/telegram-team-task-bot
- Видимость: public
- Основная ветка: `main`
- Локальная ветка настроена на отслеживание `origin/main`.

## Проверки перед первым коммитом

- автоматические тесты: 43 из 43 пройдены;
- `pip check`: конфликтов зависимостей нет;
- синтаксис Python и Google Apps Script проверен;
- битых локальных ссылок README: 0;
- файлов крупнее 10 МБ: 0;
- Git email автора заменён на GitHub `noreply`.

## Аудит конфиденциальности

В подготовленных к публикации файлах не обнаружены:

- Telegram Bot API token;
- числовой Telegram ID владельца;
- реальный Spreadsheet ID;
- закрытый ключ или маркер `BEGIN PRIVATE KEY`;
- service-account email;
- Google project ID и project number;
- личный Gmail автора.

На стороне GitHub дополнительно проверено отсутствие `.env`, JSON-ключей, SQLite-файлов, резервных копий и журналов. Локальный и удалённый commit SHA совпали после первой отправки.

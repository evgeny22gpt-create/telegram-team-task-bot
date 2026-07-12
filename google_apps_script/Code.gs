/**
 * Автоматически обновляет колонку G при ручном редактировании задачи.
 *
 * Простая функция с именем onEdit запускается самой Google Таблицей.
 * Развёртывание и отдельный устанавливаемый триггер для неё не нужны.
 */
function onEdit(e) {
  if (!e || !e.range) {
    return;
  }

  const TASKS_SHEET_NAME = 'Задачи';
  const HEADER_ROW = 1;
  const UPDATED_AT_COLUMN = 7;
  const WATCHED_COLUMNS = new Set([2, 5, 6]); // B: задача, E: статус, F: категория.

  const editedRange = e.range;
  const sheet = editedRange.getSheet();
  if (sheet.getName() !== TASKS_SHEET_NAME) {
    return;
  }

  const firstEditedColumn = editedRange.getColumn();
  const lastEditedColumn = firstEditedColumn + editedRange.getNumColumns() - 1;
  const touchesWatchedColumn = [...WATCHED_COLUMNS].some(
    (column) => column >= firstEditedColumn && column <= lastEditedColumn,
  );
  if (!touchesWatchedColumn) {
    return;
  }

  // Строку заголовков не изменяем, даже если пользователь вставил целый диапазон.
  const firstDataRow = Math.max(HEADER_ROW + 1, editedRange.getRow());
  const lastEditedRow = editedRange.getRow() + editedRange.getNumRows() - 1;
  if (lastEditedRow < firstDataRow) {
    return;
  }

  const rowCount = lastEditedRow - firstDataRow + 1;
  const timestamp = new Date().toISOString();
  const timestamps = Array.from({ length: rowCount }, () => [timestamp]);

  // Скриптовая запись setValues не запускает onEdit повторно.
  sheet
    .getRange(firstDataRow, UPDATED_AT_COLUMN, rowCount, 1)
    .setValues(timestamps);
}

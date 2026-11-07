import Papa from "papaparse";
import { fromMatrix, MAX_COLUMNS, MAX_ROWS, type TableDataset, type Value } from "./model";

export interface ImportedSheet { name: string; matrix: Value[][] }
export async function readTableFile(file: File): Promise<ImportedSheet[]> {
  if (file.size > 10 * 1024 * 1024) throw new Error("Размер файла не должен превышать 10 МБ.");
  if (/\.(csv|tsv)$/i.test(file.name)) {
    const parsed = Papa.parse<string[]>(await file.text(), { skipEmptyLines: "greedy", preview: MAX_ROWS + 2, delimiter: /\.tsv$/i.test(file.name) ? "\t" : "" });
    const error = parsed.errors.find(e => e.code !== "UndetectableDelimiter");
    if (error) throw new Error(`Ошибка CSV, строка ${(error.row ?? 0) + 1}: ${error.message}`);
    if (parsed.meta.truncated || parsed.data.length > MAX_ROWS + 1) throw new Error(`В файле больше ${MAX_ROWS.toLocaleString("ru")} строк.`);
    return [{ name: file.name.replace(/\.[^.]+$/, ""), matrix: parsed.data }];
  }
  if (!/\.xlsx$/i.test(file.name)) throw new Error("Выберите CSV, TSV или Excel (.xlsx).");
  const { default: ExcelJS } = await import("exceljs");
  const workbook = new ExcelJS.Workbook();
  await workbook.xlsx.load(await file.arrayBuffer());
  const sheets: ImportedSheet[] = [];
  for (const sheet of workbook.worksheets) {
    if (!sheet.rowCount) continue;
    if (sheet.rowCount > MAX_ROWS + 1 || sheet.columnCount > MAX_COLUMNS) throw new Error(`Лист «${sheet.name}» превышает лимит ${MAX_ROWS} строк или ${MAX_COLUMNS} столбцов.`);
    const matrix: Value[][] = [];
    for (let i = 1; i <= sheet.rowCount; i++) {
      const row: Value[] = [];
      for (let j = 1; j <= sheet.columnCount; j++) {
        const cell = sheet.getRow(i).getCell(j);
        let v = cell.value;
        if (v && typeof v === "object" && "formula" in v) v = v.result ?? null;
        row.push(v instanceof Date ? v.toISOString().slice(0, 10) : typeof v === "object" && v !== null ? cell.text : v ?? null);
      }
      matrix.push(row);
    }
    sheets.push({ name: sheet.name, matrix });
  }
  if (!sheets.length) throw new Error("В книге нет листов с данными.");
  return sheets;
}

export function downloadCsv(name: string, matrix: Value[][]) {
  const blob = new Blob(["\uFEFF", Papa.unparse(matrix, { escapeFormulae: true, delimiter: ";" })], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a"); link.href = url; link.download = `${name.replace(/[<>:"/\\|?*]/g, "_")}.csv`; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function demoDataset(): TableDataset {
  return fromMatrix("Кредитный портфель · пример", [
    ["Регион", "Продукт", "Решение", "Сумма", "Ставка"],
    ["Москва", "Ипотека", "Одобрено", 8500000, 18.5], ["Москва", "Кредит", "Одобрено", 450000, 24],
    ["Казань", "Ипотека", "Одобрено", 6200000, 18], ["Казань", "Кредит", "Отказ", 180000, 26],
    ["Санкт-Петербург", "Ипотека", "Одобрено", 7800000, 19], ["Москва", "Кредит", "Отказ", 320000, 25],
    ["Санкт-Петербург", "Кредит", "Одобрено", 600000, 23], ["Казань", "Кредит", "Одобрено", 250000, 24],
    ["Москва", "Ипотека", "Одобрено", 9100000, 18], ["Санкт-Петербург", "Кредит", "Отказ", 150000, 27],
    ["Казань", "Ипотека", "Отказ", 4500000, 20], ["Москва", "Кредит", "Одобрено", 700000, 22],
  ], "Демонстрационные данные");
}

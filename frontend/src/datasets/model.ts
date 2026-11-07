export type Value = string | number | boolean | null;
export interface Field { id: string; name: string; type: "text" | "number" }
export type Operation = "count" | "sum" | "avg" | "min" | "max";
export interface PivotConfig { rows: string[]; columns: string[]; value: string; operation: Operation; filterField: string; filterValue: string }
export interface TableDataset {
  id: string; name: string; fields: Field[]; rows: Value[][]; updatedAt: string;
  source: string; pivot: PivotConfig;
}
export const MAX_ROWS = 20000;
export const MAX_COLUMNS = 200;
export const operations: Record<Operation, string> = { count: "Количество строк", sum: "Сумма", avg: "Среднее", min: "Минимум", max: "Максимум" };

/** A decimal's value without spelling differences (trailing zeroes or exponent notation).
 * Do not expand exponents: even untrusted, very small/large values stay bounded by input size.
 */
function decimalKey(text: string): string | null {
  const match = /^([+-]?)(\d+(?:\.\d*)?|\.\d+)(?:e([+-]?\d+))?$/i.exec(text);
  if (!match) return null;
  const [whole, fraction = ""] = match[2]!.split(".");
  const digits = (whole + fraction).replace(/^0+/, "");
  if (!digits) return "0";
  const significant = digits.replace(/0+$/, "");
  const exponent = Number(match[3] ?? 0) - fraction.length + digits.length - significant.length;
  if (!Number.isSafeInteger(exponent)) return null;
  return `${match[1] === "-" ? "-" : ""}${significant}e${exponent}`;
}

export function numberValue(value: Value | undefined): number | null {
  if (typeof value === "number") return Number.isFinite(value) && (!Number.isInteger(value) || Number.isSafeInteger(value)) ? value : null;
  if (typeof value !== "string" || !value.trim()) return null;
  const text = value.trim().replace(/[\s\u00a0\u202f]/g, "").replace(",", ".");
  const n = Number(text);
  if (!Number.isFinite(n) || (Number.isInteger(n) && !Number.isSafeInteger(n))) return null;
  // Accept a string only if Number's shortest decimal representation preserves its decimal value.
  // This allows ordinary decimals (0.1) but rejects underflow and lost fractional/significant digits.
  return decimalKey(text) === decimalKey(String(n)) ? n : null;
}

export function fromMatrix(name: string, matrix: Value[][], source: string): TableDataset {
  const [header, ...data] = matrix;
  if (!header?.length) throw new Error("В таблице нет столбцов. Первая строка должна содержать заголовки.");
  const width = Math.max(header.length, ...data.map(row => row.length));
  if (width > MAX_COLUMNS || data.length > MAX_ROWS) throw new Error(`Поддерживается до ${MAX_ROWS.toLocaleString("ru")} строк и ${MAX_COLUMNS} столбцов. Разделите таблицу на несколько файлов.`);
  const names = new Set<string>();
  const fields: Field[] = Array.from({ length: width }, (_, index) => {
    const base = String(header[index] ?? "").trim() || `Столбец ${index + 1}`;
    let name = base; let suffix = 2;
    while (names.has(name)) name = `${base} (${suffix++})`;
    names.add(name);
    const values = data.map(row => row[index]).filter(v => v != null && String(v).trim() !== "");
    const numeric = values.length > 0 && values.every(v => numberValue(v) !== null && !(typeof v === "string" && /^0\d/.test(v.trim())));
    return { id: `c${index}`, name, type: numeric ? "number" : "text" };
  });
  const rows = data.map(row => fields.map((field, index) => field.type === "number" ? numberValue(row[index]) : row[index] ?? null));
  const value = fields.find(f => f.type === "number")?.id ?? "";
  return { id: crypto.randomUUID(), name, fields, rows, source, updatedAt: new Date().toISOString(),
    pivot: { rows: fields.filter(f => f.type === "text").slice(0, 1).map(f => f.id), columns: [], value, operation: value ? "sum" : "count", filterField: "", filterValue: "" } };
}

export function display(value: Value | undefined): string { return value == null || value === "" ? "(пусто)" : String(value); }
export function formatNumber(value: number | null): string { return value === null ? "—" : new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 4 }).format(value); }

interface Bucket { count: number; numeric: number; sum: number; correction: number; integerSum: bigint | null; min: number; max: number }
const bucket = (): Bucket => ({ count: 0, numeric: 0, sum: 0, correction: 0, integerSum: 0n, min: Infinity, max: -Infinity });
function add(b: Bucket, value: Value | undefined) {
  b.count++;
  const n = numberValue(value);
  if (n !== null) {
    b.numeric++;
    const next = b.sum + n;
    b.correction += Math.abs(b.sum) >= Math.abs(n) ? (b.sum - next) + n : (n - next) + b.sum;
    b.sum = next;
    // Keep integer totals exact even when an intermediate sum exceeds Number's range.
    b.integerSum = b.integerSum !== null && Number.isInteger(n) ? b.integerSum + BigInt(n) : null;
    b.min = Math.min(b.min, n); b.max = Math.max(b.max, n);
  }
}
function result(b: Bucket | undefined, operation: Operation): number | null {
  if (!b) return null;
  if (operation === "count") return b.count;
  if (!b.numeric) return null;
  if (operation === "min") return b.min;
  if (operation === "max") return b.max;
  let value: number;
  if (b.integerSum !== null) {
    // Divide before converting so a representable mean does not require a safe total.
    const count = BigInt(b.numeric);
    value = operation === "sum" ? Number(b.integerSum) : Number(b.integerSum / count) + Number(b.integerSum % count) / b.numeric;
  } else {
    const sum = b.sum + b.correction;
    value = operation === "sum" ? sum : sum / b.numeric;
  }
  if (!Number.isFinite(value) || (Number.isInteger(value) && !Number.isSafeInteger(value))) {
    throw new Error("Результат выходит за диапазон точного расчёта. Уменьшите значения, задайте фильтр или выберите другую агрегацию.");
  }
  return value;
}
export function buildPivot(dataset: TableDataset, config: PivotConfig) {
  const index = (id: string) => dataset.fields.findIndex(f => f.id === id);
  const rowIndexes = config.rows.map(index); const colIndexes = config.columns.map(index);
  if ([...rowIndexes, ...colIndexes].some(i => i < 0)) throw new Error("Выбранное поле больше не существует.");
  const valueIndex = index(config.value);
  if (config.operation !== "count" && valueIndex < 0) throw new Error("Выберите числовой показатель.");
  const rows = new Map<string, Value[]>(); const columns = new Map<string, Value[]>();
  const cells = new Map<string, Bucket>(); const rowTotals = new Map<string, Bucket>(); const columnTotals = new Map<string, Bucket>();
  const total = bucket(); const filterIndex = index(config.filterField);
  const group = (row: Value[], indexes: number[]) => indexes.map(i => row[i] === "" || row[i] == null ? null : row[i]!);
  for (const row of dataset.rows) {
    if (filterIndex >= 0 && config.filterValue !== "" && JSON.stringify(row[filterIndex] ?? null) !== config.filterValue) continue;
    const r = group(row, rowIndexes); const c = group(row, colIndexes);
    const rk = JSON.stringify(r); const ck = JSON.stringify(c); const key = JSON.stringify([rk, ck]);
    rows.set(rk, r); columns.set(ck, c);
    if (rows.size > 1000 || columns.size > 100 || rows.size * columns.size > 40000) throw new Error("Слишком много групп для сводной. Выберите менее детальные поля или задайте фильтр (до 1 000 строк и 100 столбцов).");
    for (const [map, k] of [[cells, key], [rowTotals, rk], [columnTotals, ck]] as const) {
      if (!map.has(k)) map.set(k, bucket());
      add(map.get(k)!, row[valueIndex]);
    }
    add(total, row[valueIndex]);
  }
  // Validate every subtotal here, inside the UI's error boundary, before rendering/exporting cells.
  for (const map of [cells, rowTotals, columnTotals]) for (const b of map.values()) result(b, config.operation);
  const sorted = (map: Map<string, Value[]>) => [...map].sort((a, b) => a[1].map(display).join(" / ").localeCompare(b[1].map(display).join(" / "), "ru", { numeric: true }));
  return { rows: sorted(rows), columns: sorted(columns), count: total.count, numeric: total.numeric,
    cell: (r: string, c: string) => result(cells.get(JSON.stringify([r, c])), config.operation),
    rowTotal: (r: string) => result(rowTotals.get(r), config.operation),
    columnTotal: (c: string) => result(columnTotals.get(c), config.operation), total: result(total, config.operation) };
}

import { describe, expect, it } from "vitest";
import { buildPivot, fromMatrix, numberValue } from "./model";

describe("dataset tables", () => {
  it("handles localized numbers, preserves identifiers and deduplicates headers", () => {
    const table = fromMatrix("data", [["ID", "Сумма", "Сумма", ""], ["001", "1 234,50", 10, null], ["002", "", 20, "text"]], "test");
    expect(table.fields.map(f => f.name)).toEqual(["ID", "Сумма", "Сумма (2)", "Столбец 4"]);
    expect(table.rows[0]).toEqual(["001", 1234.5, 10, null]);
    expect(numberValue(" ")).toBeNull(); expect(numberValue(true)).toBeNull(); expect(numberValue("Infinity")).toBeNull();
    expect(fromMatrix("ids", [["ID"], ["12345678901234567890"]], "test").rows[0]![0]).toBe("12345678901234567890");
  });
  it("groups multiple axes without delimiter collisions and retains zero", () => {
    const table = fromMatrix("data", [["A", "B", "C", "Value"], ["a|b", "c", "X", 0], ["a", "b|c", "X", 5]], "test");
    const result = buildPivot(table, { ...table.pivot, rows: ["c0", "c1"], columns: ["c2"], value: "c3", operation: "sum" });
    expect(result.rows).toHaveLength(2); expect(result.total).toBe(5);
    expect(result.rows.map(([key]) => result.rowTotal(key)).sort()).toEqual([0, 5]);
  });
  it("calculates weighted mean totals from source rows and excludes blank values", () => {
    const table = fromMatrix("data", [["Region", "Product", "Value"], ["A", "X", 10], ["A", "X", 20], ["B", "Y", 90], ["B", "Y", null]], "test");
    const result = buildPivot(table, { ...table.pivot, rows: ["c0"], columns: ["c1"], value: "c2", operation: "avg" });
    expect(result.total).toBe(40); expect(result.count).toBe(4); expect(result.numeric).toBe(3);
    expect(result.cell(result.rows[0]![0], result.columns[1]![0])).toBeNull();
    const filtered = buildPivot(table, { ...table.pivot, value: "c2", operation: "sum", filterField: "c0", filterValue: JSON.stringify("B") });
    expect(filtered.total).toBe(90); expect(filtered.count).toBe(2);
  });
  it("distinguishes literal empty labels, rejects partial results and handles no rows", () => {
    const table = fromMatrix("data", [["Group", "Value"], [null, 2], ["(пусто)", 3]], "test");
    expect(buildPivot(table, { ...table.pivot, rows: ["c0"], operation: "count" }).rows).toHaveLength(2);
    const empty = buildPivot({ ...table, rows: [] }, { ...table.pivot, operation: "count" });
    expect(empty.count).toBe(0); expect(empty.total).toBe(0);
    expect(() => fromMatrix("large", [Array(201).fill("x")], "test")).toThrow(/200 столбцов/);
    const many = { ...table, rows: Array.from({ length: 1001 }, (_, i) => [String(i), i]) };
    expect(() => buildPivot(many, { ...table.pivot, rows: ["c0"] })).toThrow(/Слишком много групп/);
  });
});

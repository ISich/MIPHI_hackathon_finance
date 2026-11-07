// @vitest-environment node
import { describe, expect, it } from "vitest";
import ExcelJS from "exceljs";
import { readTableFile } from "./files";
import { fromMatrix } from "./model";

describe("table import", () => {
  it("preserves precision-sensitive CSV cells through parsing and type inference", async () => {
    const sheets = await readTableFile(new File(["Value\n1e-400\n9007199254740990.5\n"], "precision.csv"));
    const table = fromMatrix("precision", sheets[0]!.matrix, "precision.csv");
    expect(table.fields[0]!.type).toBe("text");
    expect(table.rows).toEqual([["1e-400"], ["9007199254740990.5"]]);
  });
  it("reads semicolon CSV with BOM, quoted newlines and Russian decimals", async () => {
    const sheets = await readTableFile(new File(['\uFEFFРегион;Сумма;Комментарий\r\nМосква;"1 200,50";"две\nстроки"\r\n'], "data.csv"));
    expect(sheets[0]!.matrix).toEqual([["Регион", "Сумма", "Комментарий"], ["Москва", "1 200,50", "две\nстроки"]]);
  });
  it("reads every Excel worksheet and cached formula values", async () => {
    const workbook = new ExcelJS.Workbook();
    const sheet = workbook.addWorksheet("Портфель");
    sheet.addRow(["Регион", "Сумма"]); sheet.addRow(["Москва", 125]); sheet.addRow(["Казань", { formula: "B2*2", result: 250 }]);
    workbook.addWorksheet("Ещё лист").addRow(["ID", "Название"]);
    const buffer = await workbook.xlsx.writeBuffer();
    const sheets = await readTableFile(new File([new Uint8Array(buffer)], "data.xlsx"));
    expect(sheets.map(s => s.name)).toEqual(["Портфель", "Ещё лист"]);
    expect(sheets[0]!.matrix[2]).toEqual(["Казань", 250]);
  });
  it("rejects oversized and malformed files rather than silently dropping data", async () => {
    await expect(readTableFile(new File(['A,B\n"broken'], "bad.csv"))).rejects.toThrow(/Ошибка CSV/);
    await expect(readTableFile(new File(["x"], "old.xls"))).rejects.toThrow(/xlsx/);
    await expect(readTableFile(new File(["A\n" + "x\n".repeat(20001)], "large.csv"))).rejects.toThrow(/20/);
  });
});

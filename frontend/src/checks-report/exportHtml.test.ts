import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { ReportChecks } from "../api/types";
import { renderReportHtml } from "./exportHtml";

const report = (): ReportChecks => JSON.parse(readFileSync(join(__dirname, "../../../backend/docs/examples/13_checks_initial.json"), "utf8"));
const parse = (html: string) => new DOMParser().parseFromString(html, "text/html");

describe("portable HTML report", () => {
  it("exports every stored row of a real backend response in a single seven-column table", () => {
    const data = report();
    const html = parse(renderReportHtml(data, "https://example.org"));
    expect(html.querySelectorAll("table")).toHaveLength(1);
    expect([...html.querySelectorAll("thead th")].map(element => element.textContent)).toEqual([
      "Проверка", "Срез", "Аргумент", "Числа", "Метрика", "Результат", "Заявки",
    ]);
    const rows = [...html.querySelectorAll("tbody tr")];
    expect(rows).toHaveLength(data.checks.length);
    data.checks.forEach((row, index) => {
      const cells = rows[index]!.children;
      expect(cells[0]!.textContent).toBe(row.LABEL);
      expect(cells[2]!.textContent).toBe(row.ARGUMENT || "—");
      expect(cells[3]!.textContent).toBe(`${row.CNT} / ${row.TOTAL}`);
      expect(cells[4]!.textContent).toBe(String(row.METRIC));
      expect(cells[5]!.textContent).toBe(row.RESULT);
    });
    expect(html.body.textContent).toContain(data.run_id);
    expect(html.body.textContent).toContain(data.report_id);
    const appLink = html.querySelector<HTMLAnchorElement>("td.apps a")!;
    const url = new URL(appLink.href);
    expect(url.origin).toBe("https://example.org");
    expect(url.pathname).toBe(`/runs/${data.run_id}/reports/${data.report_id}`);
    expect(url.searchParams.get("app_id")).toBe(data.checks.find(row => row.APP_IDS.length)!.APP_IDS[0]);
    expect(html.querySelector("script, link[rel=stylesheet], img")).toBeNull();
  });

  it("escapes report text and application links, including diagnostics", () => {
    const data = report();
    const hostile = '<script>alert("x")</script>&\'"';
    data.checks = [{ ...data.checks[0]!, LABEL: hostile, ARGUMENT: '<img src=x onerror="alert(1)">', APP_IDS: [hostile] }];
    data.diagnostics = [{ check: hostile, error_type: "ValueError", message: hostile }];
    const html = parse(renderReportHtml(data, "https://example.org"));
    expect(html.querySelector("script, img, iframe")).toBeNull();
    expect(html.querySelector("tbody th")!.textContent).toBe(hostile);
    expect(html.querySelector(".argument")!.textContent).toBe(data.checks[0]!.ARGUMENT);
    expect(html.querySelector("li")!.textContent).toContain(hostile);
    expect(new URL(html.querySelector<HTMLAnchorElement>(".apps a")!.href).searchParams.get("app_id")).toBe(hostile);
  });

  it("keeps execution errors and zero-row checks distinct from PASS/FAIL rows", () => {
    const data = report();
    data.checks = [];
    data.completeness = "INCOMPLETE";
    data.executions = [
      { ...data.executions[0]!, label: "Broken", execution_status: "ERROR", rows_count: 0 },
      { ...data.executions[1]!, label: "Empty", execution_status: "SUCCEEDED", rows_count: 0 },
    ];
    data.diagnostics = [{ check: "Broken", error_type: "ValueError", message: "bad input" }];
    const html = parse(renderReportHtml(data, "https://example.org", true));
    expect(html.querySelectorAll("tbody tr")).toHaveLength(0);
    expect(html.querySelectorAll(".result")).toHaveLength(0);
    expect(html.body.textContent).toContain("INCOMPLETE");
    expect(html.body.textContent).toContain("ValueError — bad input");
    expect(html.body.textContent).toContain("Без строк результата: Empty");
    expect(html.body.textContent).toContain("Демонстрационный отчёт");
  });

  it("rejects invalid data and non-HTTP origins before creating a file", () => {
    const data = report();
    expect(() => renderReportHtml(data, "javascript:alert(1)")).toThrow(/HTTP/);
    expect(() => renderReportHtml({ ...data, checks: undefined } as unknown as ReportChecks, "https://example.org")).toThrow(/неполный/);
    data.checks[0]!.RESULT = "ERROR" as "FAIL";
    expect(() => renderReportHtml(data, "https://example.org")).toThrow(/некорректная строка/);
  });
});

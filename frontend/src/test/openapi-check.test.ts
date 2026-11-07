// The OpenAPI contract checker must FAIL on incompatible route bindings, not
// only on missing routes. Fixture: backend-night openapi.json (feat/backend-night cc8fc9c).
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const SCRIPT = join(__dirname, "../../scripts/check-openapi.mjs");
const FIXTURE = join(__dirname, "../../scripts/fixtures/backend-openapi.json");
type Spec = { paths: Record<string, Record<string, any>>; components: { schemas: Record<string, any> } };
const load = (): Spec => JSON.parse(readFileSync(FIXTURE, "utf8"));

function run(spec: Spec): { ok: boolean; out: string } {
  const dir = mkdtempSync(join(tmpdir(), "oas-"));
  const file = join(dir, "openapi.json");
  writeFileSync(file, JSON.stringify(spec));
  try {
    return { ok: true, out: execFileSync("node", [SCRIPT, file], { encoding: "utf8" }) };
  } catch (e) {
    const err = e as { stdout?: string };
    return { ok: false, out: String(err.stdout ?? "") };
  }
}

describe("check-openapi", () => {
  it("passes on the real backend spec", () => {
    const r = run(load());
    expect(r.out).toContain("OpenAPI contract check: OK");
    expect(r.ok).toBe(true);
  });

  it("fails when a route's response is bound to a different schema", () => {
    const s = load();
    s.paths["/api/runs/{run_id}"]!.get.responses["200"].content["application/json"].schema = { $ref: "#/components/schemas/Report" };
    const r = run(s);
    expect(r.ok).toBe(false);
    expect(r.out).toMatch(/GET \/api\/runs\/\{run_id\}.*Report.*expected Run/);
  });

  it("fails when a list route returns items of another schema", () => {
    const s = load();
    s.paths["/api/datasets"]!.get.responses["200"].content["application/json"].schema.items = { $ref: "#/components/schemas/Script" };
    expect(run(s).ok).toBe(false);
  });

  it("fails when the request body schema requires a field the UI does not send", () => {
    const s = load();
    s.components.schemas.RunCreate.required = ["configuration_id", "priority"];
    s.components.schemas.RunCreate.properties.priority = { type: "integer" };
    const r = run(s);
    expect(r.ok).toBe(false);
    expect(r.out).toMatch(/RunCreate.*priority/);
  });

  it("fails when a field the UI reads as non-null becomes nullable or optional", () => {
    const s = load();
    s.components.schemas.Run.properties.status = { anyOf: [{ type: "string" }, { type: "null" }] };
    const r = run(s);
    expect(r.ok).toBe(false);
    expect(r.out).toMatch(/Run\.status/);
    const s2 = load();
    s2.components.schemas.Run.required = s2.components.schemas.Run.required.filter((f: string) => f !== "run_id");
    expect(run(s2).ok).toBe(false);
  });

  it("fails when a field type changes", () => {
    const s = load();
    s.components.schemas.EventPage.properties.next_after = { type: "string" };
    const r = run(s);
    expect(r.ok).toBe(false);
    expect(r.out).toMatch(/EventPage\.next_after/);
  });

  it("fails when a request field changes type (RunCreate.configuration_id → integer)", () => {
    const s = load();
    s.components.schemas.RunCreate.properties.configuration_id = { type: "integer" };
    const r = run(s);
    expect(r.ok).toBe(false);
    expect(r.out).toMatch(/RunCreate\.configuration_id/);
  });

  it("fails when an array field's items bind to another schema (RunPage.items → Report)", () => {
    const s = load();
    s.components.schemas.RunPage.properties.items = { type: "array", items: { $ref: "#/components/schemas/Report" } };
    const r = run(s);
    expect(r.ok).toBe(false);
    expect(r.out).toMatch(/RunPage\.items/);
  });

  it("fails when a nested request array binds to another schema (CheckRunCreate.checks)", () => {
    const s = load();
    s.components.schemas.CheckRunCreate.properties.checks = { type: "array", items: { $ref: "#/components/schemas/SlotRef" } };
    expect(run(s).ok).toBe(false);
  });
});

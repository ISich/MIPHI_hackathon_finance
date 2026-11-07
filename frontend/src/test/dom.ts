// Small DOM helpers for @vue/test-utils tests (no extra testing libraries).
import { flushPromises } from "@vue/test-utils";

/** Retries `fn` until it stops throwing (or the timeout elapses), flushing promises in between. */
export async function waitFor<T>(fn: () => T, timeout = 2000): Promise<T> {
  const start = Date.now();
  for (;;) {
    try {
      return fn();
    } catch (e) {
      if (Date.now() - start > timeout) throw e;
      await flushPromises();
      await new Promise((r) => setTimeout(r, 5));
    }
  }
}

export function byTestId(_w: unknown, id: string): HTMLElement {
  const el = document.querySelector<HTMLElement>(`[data-testid="${id}"]`);
  if (!el) throw new Error(`no [data-testid=${id}]`);
  return el;
}
export function allByTestId(_w: unknown, id: string): HTMLElement[] {
  return [...document.querySelectorAll<HTMLElement>(`[data-testid="${id}"]`)];
}
const norm = (s: string | null | undefined) => (s ?? "").replace(/\s+/g, " ").trim();

export function button(_w: unknown, name: string | RegExp): HTMLButtonElement {
  const b = [...document.querySelectorAll("button")].find((x) => (typeof name === "string" ? norm(x.textContent) === name : name.test(norm(x.textContent))));
  if (!b) throw new Error(`no button ${name}`);
  return b;
}
export function link(_w: unknown, name: string | RegExp): HTMLAnchorElement {
  const a = [...document.querySelectorAll("a")].find((x) => (typeof name === "string" ? norm(x.textContent) === name : name.test(norm(x.textContent))));
  if (!a) throw new Error(`no link ${name}`);
  return a;
}
/** <select> by aria-label, or by the text of the <label> that wraps it. */
export function select(_w: unknown, name: string): HTMLSelectElement {
  const doc = document;
  const byAria = doc.querySelector<HTMLSelectElement>(`select[aria-label="${name}"]`);
  if (byAria) return byAria;
  const lbl = [...doc.querySelectorAll("label")].find((l) => l.querySelector("select") && norm(l.firstChild?.textContent) === name);
  if (!lbl) throw new Error(`no select ${name}`);
  return lbl.querySelector("select")!;
}
export function table(_w: unknown, name: string): HTMLTableElement {
  const t = document.querySelector<HTMLTableElement>(`table[aria-label="${name}"]`);
  if (!t) throw new Error(`no table ${name}`);
  return t;
}
export function text(_w: unknown): string {
  return norm(document.body.textContent);
}
export function alertEl(_w: unknown): HTMLElement {
  const a = document.querySelector<HTMLElement>('[role="alert"]');
  if (!a) throw new Error("no alert");
  return a;
}
export async function choose(sel: HTMLSelectElement, value: string): Promise<void> {
  sel.value = value;
  sel.dispatchEvent(new Event("change"));
  await flushPromises();
}
export async function click(el: HTMLElement): Promise<void> {
  el.click();
  await flushPromises();
}
export async function typeInto(el: HTMLInputElement | HTMLTextAreaElement, value: string): Promise<void> {
  el.value = value;
  el.dispatchEvent(new Event("input"));
  await flushPromises();
}
export async function upload(input: HTMLInputElement, file: File): Promise<void> {
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  input.dispatchEvent(new Event("change"));
  await flushPromises();
}

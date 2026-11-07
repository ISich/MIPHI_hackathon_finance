import { onScopeDispose, shallowRef, type ShallowRef } from "vue";

/** Minimal hash router: "#/runs/abc?x=1" → {path: "/runs/abc", query}. */
export interface Route {
  path: string;
  parts: string[];
  query: URLSearchParams;
}

export function parseHash(hash: string): Route {
  const raw = hash.replace(/^#/, "") || "/runs";
  const [path = "/runs", qs = ""] = raw.split("?", 2);
  return { path, parts: path.split("/").filter(Boolean).map(decodeURIComponent), query: new URLSearchParams(qs) };
}

/** Reactive current route; follows `hashchange` while the calling scope is alive. */
export function useRoute(): ShallowRef<Route> {
  const route = shallowRef(parseHash(window.location.hash));
  const on = () => (route.value = parseHash(window.location.hash));
  window.addEventListener("hashchange", on);
  onScopeDispose(() => window.removeEventListener("hashchange", on));
  return route;
}

export function href(...parts: Array<string | number>): string {
  return "#/" + parts.map((p) => encodeURIComponent(String(p))).join("/");
}

/** Application card link carrying the place to return to (same Run only; validated by safeReturn). */
export function appHref(runId: string, appId: string, ret: string): string {
  return `${href("runs", runId, "apps", appId)}?ret=${encodeURIComponent(ret)}`;
}

/** A return target is accepted only as an in-app hash route of the same Run. */
export function safeReturn(ret: string | null | undefined, runId: string): string | null {
  if (!ret) return null;
  const prefix = href("runs", runId) + "/";
  return ret.startsWith(prefix) && !/[\s<>"]/.test(ret) ? ret : null;
}

export function navigate(to: string): void {
  window.location.hash = to.replace(/^#/, "");
}

/**
 * The backend's HTML report links to {DD_REPORT_UI_BASE}/runs/{run}/reports/{report}
 * (a path, not a hash). Rewrite it to the pivot of that Run with report context.
 * Returns the hash to use, or null if the path is not such a link.
 */
export function deepLinkToHash(pathname: string): string | null {
  const m = pathname.match(/^\/runs\/([^/]+)\/reports\/([^/]+)\/?$/);
  if (!m) return null;
  const run = decodeURIComponent(m[1]!);
  const report = decodeURIComponent(m[2]!);
  return `${href("runs", run, "pivot")}?report=${encodeURIComponent(report)}`;
}

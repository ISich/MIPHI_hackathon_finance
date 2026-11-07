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

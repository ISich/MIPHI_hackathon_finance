import { useEffect, useState } from "react";

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

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseHash(window.location.hash));
  useEffect(() => {
    const on = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

export function href(...parts: Array<string | number>): string {
  return "#/" + parts.map((p) => encodeURIComponent(String(p))).join("/");
}

export function navigate(to: string): void {
  window.location.hash = to.replace(/^#/, "");
}

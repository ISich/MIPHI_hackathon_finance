import { afterEach } from "vitest";

afterEach(() => {
  if (typeof document === "undefined") return;
  document.body.innerHTML = "";
  window.location.hash = "";
});

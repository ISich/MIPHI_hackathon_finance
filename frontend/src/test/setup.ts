import { afterEach } from "vitest";

afterEach(() => {
  document.body.innerHTML = "";
  window.location.hash = "";
});

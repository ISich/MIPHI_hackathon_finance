import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { deepLinkToHash } from "./router";
import "./styles.css";

const deep = deepLinkToHash(window.location.pathname);
if (deep) window.history.replaceState(null, "", "/" + deep);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App.tsx";

// "ResizeObserver loop completed with undelivered notifications" — browser upozorenje
// (ne greška aplikacije; ne utiče na raspored). Zaustavlja se pre prikaza kao uncaught greška.
window.addEventListener(
  "error",
  (e) => {
    if (e.message?.includes("ResizeObserver loop")) e.stopImmediatePropagation();
  },
  { capture: true }
);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);

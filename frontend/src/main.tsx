import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { TerminalView } from "./components/TerminalView";
import "./index.css";

const root = document.getElementById("root");
if (!root) throw new Error("#root não encontrado");

createRoot(root).render(
  <StrictMode>
    <TerminalView />
  </StrictMode>,
);

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";

import { App } from "./app/App";
import { TooltipProvider } from "./components/ui/tooltip";
import "./index.css";

const root = document.getElementById("root");
if (!root) throw new Error("#root não encontrado");

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <HashRouter>
          <App />
        </HashRouter>
      </TooltipProvider>
    </QueryClientProvider>
  </StrictMode>,
);

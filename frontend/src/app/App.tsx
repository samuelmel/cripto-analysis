import type { ReactNode } from "react";
import { Route, Routes } from "react-router-dom";

import { AppShell } from "../components/layout/AppShell";
import { AssetPage } from "../features/market/AssetPage";
import { MarketPage } from "../features/market/MarketPage";
import { MethodologyPage } from "../features/methodology/MethodologyPage";
import { OverviewPage } from "../features/overview/OverviewPage";
import { PortfoliosPage } from "../features/portfolios/PortfoliosPage";
import { ResearchPage } from "../features/research/ResearchPage";
import { StudyPage } from "../features/research/StudyPage";

function NotFound(): ReactNode {
  return (
    <div className="mx-auto max-w-xl py-20 text-center">
      <div className="text-[11px] uppercase tracking-[0.16em] text-signal">404</div>
      <h1 className="display mt-2 text-4xl font-semibold">Página não encontrada</h1>
      <p className="mt-3 text-[14px] text-muted">O endereço não existe neste painel.</p>
    </div>
  );
}

export function App(): ReactNode {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<OverviewPage />} />
        <Route path="carteiras" element={<PortfoliosPage />} />
        <Route path="carteiras/:portfolioId" element={<PortfoliosPage />} />
        <Route path="pesquisa" element={<ResearchPage />} />
        <Route path="pesquisa/:studyId" element={<StudyPage />} />
        <Route path="mercado" element={<MarketPage />} />
        <Route path="mercado/:symbol" element={<AssetPage />} />
        <Route path="metodologia" element={<MethodologyPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}

import { useState } from "react";
import type { Dashboard } from "../types/signals";
import { GlossaryList } from "./Glossary";
import { LabPanel } from "./Research";
import { RegimesPanel } from "./Regimes";
import { BacktestPanel, HowItWorks } from "./Sections";
import { Panel, Segmented } from "./ui";

type Part = "regra" | "lab" | "regimes" | "como" | "glossario";
const PARTS: Readonly<Record<Part, string>> = {
  regra: "Regra de tendência",
  lab: "Laboratório",
  regimes: "Regimes (experimental)",
  como: "Como funciona",
  glossario: "Glossário",
};

/** Pesquisa: cada grupo de análise numa visão própria, para não empilhar tudo numa página só. */
export function ResearchView({ data }: { readonly data: Dashboard }) {
  const [part, setPart] = useState<Part>("regra");
  return (
    <div className="space-y-3">
      <Segmented label="Análise" value={part} options={PARTS} onChange={setPart} />
      {part === "regra" && <BacktestPanel performance={data.performance} trades={data.trades} />}
      {part === "lab" && (
        <Panel
          id="laboratorio"
          title="Laboratório de estratégias"
          note="outras ideias testadas com o mesmo motor da regra do painel; mostra também o que perdeu"
          bodyClassName="p-0"
        >
          <LabPanel rows={data.lab} />
        </Panel>
      )}
      {part === "regimes" && <RegimesPanel rows={data.marketRegimes} />}
      {part === "como" && <HowItWorks />}
      {part === "glossario" && (
        <Panel id="glossario" title="Glossário" note="os termos do painel em português simples; nos cartões, passe o mouse sobre o termo sublinhado">
          <GlossaryList />
        </Panel>
      )}
    </div>
  );
}

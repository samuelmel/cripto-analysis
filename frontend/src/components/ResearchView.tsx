import { useState } from "react";
import type { Dashboard } from "../types/signals";
import { GlossaryList } from "./Glossary";
import { EntrySignalsPanel } from "./EntrySignals";
import { EvidencePanel, LabPanel } from "./Research";
import { RegimesPanel } from "./Regimes";
import { BacktestPanel, HowItWorks } from "./Sections";
import { Panel, Segmented } from "./ui";

type Part = "sinais" | "regra" | "evidencia" | "lab" | "regimes" | "como" | "glossario";
const PARTS: Readonly<Record<Part, string>> = {
  sinais: "Sinais de entrada",
  regra: "Regra de tendência",
  evidencia: "Validação por moeda",
  lab: "Laboratório",
  regimes: "Regimes (experimental)",
  como: "Como funciona",
  glossario: "Glossário",
};

/** Pesquisa: cada grupo de análise numa visão própria, para não empilhar tudo numa página só. */
export function ResearchView({ data }: { readonly data: Dashboard }) {
  const [part, setPart] = useState<Part>("sinais");
  return (
    <div className="space-y-3">
      <Segmented label="Análise" value={part} options={PARTS} onChange={setPart} />
      {part === "sinais" && (
        <Panel
          id="sinais"
          title="Sinais de entrada"
          note="COMPRAR só com sinal validado no estudo agregado; promissor fica em observação"
          bodyClassName="p-0"
        >
          <EntrySignalsPanel levels={data.entryLevels} signals={data.signals} />
        </Panel>
      )}
      {part === "regra" && <BacktestPanel performance={data.performance} trades={data.trades} />}
      {part === "evidencia" && (
        <Panel
          id="evidencia"
          title="Validação do sinal SMA 200 por moeda"
          note="só informação: desde 2026-10-17 o COMPRAR depende do sinal de entrada, não da moeda"
          bodyClassName="p-0"
        >
          <EvidencePanel rows={data.evidence} />
        </Panel>
      )}
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

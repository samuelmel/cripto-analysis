import type { Kpi } from "../data/kpis";
import { TEXT_TONE } from "./ui";

/** Faixa de indicadores: uma linha no desktop, grade de 2 colunas no celular. Cada célula sai de um campo publicado. */
export function KpiStrip({ items }: { readonly items: readonly Kpi[] }) {
  return (
    <section
      aria-label="Indicadores do dia"
      className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-hairline bg-hairline sm:grid-cols-4 xl:grid-cols-8"
    >
      {items.map((k) => (
        <div key={k.key} className="min-w-0 bg-surface px-3 py-1.5">
          <p className="truncate text-[11px] text-muted" title={k.label}>{k.label}</p>
          <p className={`num text-[13px] font-semibold leading-tight ${TEXT_TONE[k.tone]}`}>{k.value}</p>
          <p className="truncate text-[11px] text-muted" title={k.note}>{k.note}</p>
        </div>
      ))}
    </section>
  );
}

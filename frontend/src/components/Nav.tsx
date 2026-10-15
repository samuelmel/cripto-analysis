import type { KeyboardEvent } from "react";

export const VIEWS = [
  { id: "geral", label: "Visão geral" },
  { id: "historico", label: "Histórico" },
  { id: "previsoes", label: "Previsões" },
  { id: "pesquisa", label: "Pesquisa" },
] as const;

export type ViewId = (typeof VIEWS)[number]["id"];

export const tabId = (id: ViewId): string => `aba-${id}`;
export const panelId = (id: ViewId): string => `painel-${id}`;

/** Abas em texto sobre uma linha; setas do teclado trocam de visão. */
export function Nav({ view, onChange }: { readonly view: ViewId; readonly onChange: (id: ViewId) => void }) {
  const move = (e: KeyboardEvent<HTMLButtonElement>, index: number): void => {
    const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (step === 0) return;
    e.preventDefault();
    const next = VIEWS[(index + step + VIEWS.length) % VIEWS.length];
    if (next !== undefined) {
      onChange(next.id);
      document.getElementById(tabId(next.id))?.focus();
    }
  };
  return (
    <nav aria-label="Visões do painel" className="mt-6 border-b border-hairline">
      <div role="tablist" className="-mb-px flex flex-wrap gap-x-2">
        {VIEWS.map((v, i) => {
          const active = v.id === view;
          return (
            <button
              key={v.id}
              id={tabId(v.id)}
              role="tab"
              type="button"
              aria-selected={active}
              aria-controls={panelId(v.id)}
              tabIndex={active ? 0 : -1}
              onClick={() => onChange(v.id)}
              onKeyDown={(e) => move(e, i)}
              className={`whitespace-nowrap border-b-2 px-3 py-2 text-[15px] transition-colors ${
                active ? "border-signal font-medium text-ink" : "border-transparent text-muted hover:text-ink"
              }`}
            >
              {v.label}
            </button>
          );
        })}
      </div>
    </nav>
  );
}

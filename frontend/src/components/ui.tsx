import type React from "react";
import type { ReactNode } from "react";
import type { Tone } from "../data/analytics";

/* Primitivas do DESIGN.md. Componentes de seção usam só estas peças e os tokens.
   Painel de análise: bordas finas, cabeçalho de uma linha, corpo compacto, sem sombra e sem card dentro de card. */

export const TEXT_TONE: Record<Tone, string> = {
  good: "text-good",
  critical: "text-critical",
  warning: "text-warning",
  neutral: "text-ink",
  signal: "text-signal",
};

const BADGE_TONE: Record<Tone, string> = {
  good: "bg-good-bg text-good",
  critical: "bg-critical-bg text-critical",
  warning: "bg-warning-bg text-warning",
  neutral: "bg-ground text-muted",
  signal: "bg-signal-bg text-signal",
};

/** Painel: cabeçalho de uma linha (título, nota e ações) e corpo. `fill` faz o corpo ocupar a altura do painel. */
export function Panel({ id, title, note, actions, children, className = "", bodyClassName = "p-3", fill = false }: {
  readonly id?: string;
  readonly title: ReactNode;
  readonly note?: ReactNode;
  readonly actions?: ReactNode;
  readonly children: ReactNode;
  readonly className?: string;
  readonly bodyClassName?: string;
  readonly fill?: boolean;
}) {
  return (
    <section aria-labelledby={id} className={`flex min-w-0 flex-col rounded-md border border-hairline bg-surface ${className}`}>
      <header className="flex min-h-9 flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-hairline px-3 py-1.5">
        <h2 id={id} className="flex min-w-0 flex-wrap items-baseline gap-x-2 text-[13px] font-semibold">
          <span className="md:whitespace-nowrap">{title}</span>
          {note !== undefined && <span className="min-w-0 text-[12px] font-normal text-muted">{note}</span>}
        </h2>
        {actions !== undefined && <div className="flex min-w-0 max-w-full flex-wrap items-center gap-2">{actions}</div>}
      </header>
      <div className={`${fill ? "min-h-0 flex-1" : ""} ${bodyClassName}`}>{children}</div>
    </section>
  );
}

/** Seção solta (fora de painel), usada só em textos longos de ajuda. */
export function Section({ id, title, icon, lead, children }: {
  readonly id: string;
  readonly title: string;
  readonly icon?: ReactNode;
  readonly lead?: ReactNode;
  readonly children: ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="mt-6 first:mt-0">
      <h2 id={id} className="flex items-center gap-2 text-[15px] font-semibold">{icon}{title}</h2>
      {lead !== undefined && <p className="mt-1 max-w-[80ch] text-muted">{lead}</p>}
      <div className="mt-3">{children}</div>
    </section>
  );
}

export function Block({ children, className = "" }: { readonly children: ReactNode; readonly className?: string }) {
  return <div className={`rounded-md border border-hairline bg-surface p-4 ${className}`}>{children}</div>;
}

export function Badge({ tone, children }: { readonly tone: Tone; readonly children: ReactNode }) {
  return (
    <span className={`inline-block rounded-sm px-1.5 py-0.5 text-[12px] font-medium leading-tight md:whitespace-nowrap ${BADGE_TONE[tone]}`}>
      {children}
    </span>
  );
}

export function Figure({ label, value, tone = "neutral", note }: {
  readonly label: string;
  readonly value: string;
  readonly tone?: Tone;
  readonly note?: string;
}) {
  return (
    <div>
      <p className="text-[12px] text-muted">{label}</p>
      <p className={`num text-[22px] font-medium leading-tight ${TEXT_TONE[tone]}`}>{value}</p>
      {note !== undefined && <p className="text-[12px] text-muted">{note}</p>}
    </div>
  );
}

/** Texto longo recolhível: a informação continua a um clique, sem ocupar altura. */
export function Collapsible({ summary, children, className = "" }: {
  readonly summary: ReactNode;
  readonly children: ReactNode;
  readonly className?: string;
}) {
  return (
    <details className={`group text-[13px] ${className}`}>
      <summary className="cursor-pointer select-none text-muted marker:text-muted hover:text-ink">{summary}</summary>
      <div className="mt-2 text-muted">{children}</div>
    </details>
  );
}

/** Seletor compacto de uma opção entre poucas (substitui grupos de botões grandes). */
export function Segmented<T extends string>({ label, value, options, onChange }: {
  readonly label: string;
  readonly value: T;
  readonly options: Readonly<Record<T, string>>;
  readonly onChange: (v: T) => void;
}) {
  return (
    <div role="group" aria-label={label} className="scroll-thin flex max-w-full overflow-x-auto rounded-sm border border-hairline sm:inline-flex">
      {(Object.keys(options) as T[]).map((k) => (
        <button
          key={k}
          type="button"
          aria-pressed={k === value}
          onClick={() => onChange(k)}
          className={`shrink-0 whitespace-nowrap border-r border-hairline px-2.5 py-1 text-[12px] transition-colors last:border-r-0 ${
            k === value ? "bg-signal-bg font-medium text-signal" : "bg-surface text-muted hover:bg-ground hover:text-ink"
          }`}
        >
          {options[k]}
        </button>
      ))}
    </div>
  );
}

/** Estado vazio ou de erro dentro de um painel (nunca um número inventado no lugar do dado). */
export function Empty({ title, children, tone = "neutral" }: {
  readonly title: string;
  readonly children?: ReactNode;
  readonly tone?: Tone;
}) {
  return (
    <div className="px-1 py-2">
      <p className={`font-medium ${TEXT_TONE[tone]}`}>{title}</p>
      {children !== undefined && <div className="mt-1 text-[13px] text-muted">{children}</div>}
    </div>
  );
}

export interface Column {
  readonly label: string;
  readonly numeric?: boolean;
  /** "hide": some abaixo de 768px; "wide": só aparece a partir de 1536px (detalhe de telas largas). */
  readonly narrow?: "hide" | "wide";
}

/** Classe das células das colunas com `narrow: "hide"`. */
export const hideNarrow = "hidden md:table-cell";
/** Classe das células das colunas com `narrow: "wide"`. */
export const hideWide = "hidden 2xl:table-cell";

/**
 * Tabela compacta. `maxHeight` (classe do Tailwind, ex.: "max-h-72") limita a altura e liga a rolagem interna, com o
 * cabeçalho fixo; a rolagem horizontal, quando preciso, também é interna: a página nunca rola na horizontal.
 */
export function Table({ columns, caption, children, maxHeight, flush = false }: {
  readonly columns: readonly Column[];
  readonly caption: string;
  readonly children: ReactNode;
  readonly maxHeight?: string;
  /** Sem borda própria (a tabela está dentro de um painel). */
  readonly flush?: boolean;
}) {
  return (
    <div className={`scroll-thin overflow-auto ${maxHeight ?? ""} ${flush ? "" : "rounded-md border border-hairline bg-surface"}`}>
      <table className="w-full border-collapse text-left text-[13px]">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-hairline">
            {columns.map((c, i) => (
              <th
                key={`${i}:${c.label}`}
                scope="col"
                className={`sticky top-0 z-[1] bg-surface px-2 py-1.5 text-[12px] font-medium text-muted md:whitespace-nowrap ${c.numeric === true ? "text-right" : ""} ${c.narrow === "hide" ? hideNarrow : c.narrow === "wide" ? hideWide : ""}`}
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="[&>tr:last-child]:border-0">{children}</tbody>
      </table>
    </div>
  );
}

export const cell = "px-2 py-1.5 md:whitespace-nowrap";
export const numCell = `${cell} num text-right`;

/* ---------- formulários ---------- */

type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";

const BUTTON_VARIANT: Record<ButtonVariant, string> = {
  primary: "bg-signal text-surface hover:bg-signal-hover active:bg-signal-active",
  secondary: "border border-hairline bg-surface text-ink hover:bg-ground active:bg-hairline",
  danger: "border border-critical-mark bg-surface text-critical hover:bg-critical-bg",
  ghost: "text-muted hover:bg-ground hover:text-ink",
};

export function Button({ variant = "secondary", icon, busy = false, children, ...rest }: {
  readonly variant?: ButtonVariant;
  readonly icon?: ReactNode;
  readonly busy?: boolean;
  readonly children: ReactNode;
} & Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "children">) {
  return (
    <button
      type="button"
      {...rest}
      disabled={busy || rest.disabled === true}
      aria-busy={busy}
      className={`inline-flex items-center gap-1.5 rounded-sm px-2.5 py-1.5 text-[13px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${BUTTON_VARIANT[variant]}`}
    >
      {icon}
      {children}
    </button>
  );
}

export function Field({ label, hint, children }: { readonly label: string; readonly hint?: string; readonly children: ReactNode }) {
  return (
    <label className="block">
      <span className="text-[12px] font-medium text-muted">{label}</span>
      <span className="mt-0.5 block">{children}</span>
      {hint !== undefined && <span className="mt-0.5 block text-[12px] text-muted">{hint}</span>}
    </label>
  );
}

export const inputClass =
  "w-full rounded-sm border border-hairline bg-surface px-2.5 py-1.5 text-[14px] num focus-visible:border-signal aria-[invalid=true]:border-critical-mark";

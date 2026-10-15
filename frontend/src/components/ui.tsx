import type React from "react";
import type { ReactNode } from "react";
import type { Tone } from "../data/analytics";

/* Primitivas do DESIGN.md. Componentes de seção usam só estas peças e os tokens. */

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

export function Section({ id, title, icon, lead, children }: {
  readonly id: string;
  readonly title: string;
  readonly icon?: ReactNode;
  readonly lead?: ReactNode;
  readonly children: ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="mt-16 first:mt-0">
      <h2 id={id} className="flex items-center gap-2 text-lg font-semibold">{icon}{title}</h2>
      {lead !== undefined && <p className="mt-1 max-w-[68ch] text-muted">{lead}</p>}
      <div className="mt-5">{children}</div>
    </section>
  );
}

export function Block({ children, className = "" }: { readonly children: ReactNode; readonly className?: string }) {
  return <div className={`rounded-md border border-hairline bg-surface p-6 ${className}`}>{children}</div>;
}

export function Badge({ tone, children }: { readonly tone: Tone; readonly children: ReactNode }) {
  return (
    <span className={`inline-block rounded-sm px-2 py-0.5 md:whitespace-nowrap text-[13px] font-medium ${BADGE_TONE[tone]}`}>
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
      <p className="text-[13px] text-muted">{label}</p>
      <p className={`mt-1 text-[32px] font-medium leading-tight ${TEXT_TONE[tone]}`}>{value}</p>
      {note !== undefined && <p className="mt-1 text-[13px] text-muted">{note}</p>}
    </div>
  );
}

export interface Column {
  readonly label: string;
  readonly numeric?: boolean;
  /** "hide": a coluna some abaixo de 768px (a leitura completa fica no desktop). */
  readonly narrow?: "hide";
}

/** Classe das células das colunas com `narrow: "hide"`. */
export const hideNarrow = "hidden md:table-cell";

export function Table({ columns, caption, children }: {
  readonly columns: readonly Column[];
  readonly caption: string;
  readonly children: ReactNode;
}) {
  return (
    <div className="overflow-x-auto rounded-md border border-hairline bg-surface">
      <table className="w-full border-collapse text-left">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-hairline">
            {columns.map((c, i) => (
              <th
                key={`${i}:${c.label}`}
                scope="col"
                className={`px-2 py-3 text-[13px] font-medium text-muted md:whitespace-nowrap md:px-4 ${c.numeric === true ? "text-right" : ""} ${c.narrow === "hide" ? hideNarrow : ""}`}
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

export const cell = "px-2 py-3 md:whitespace-nowrap md:px-4";
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
      className={`inline-flex items-center gap-2 rounded-sm px-3 py-2 text-[14px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${BUTTON_VARIANT[variant]}`}
    >
      {icon}
      {children}
    </button>
  );
}

export function Field({ label, hint, children }: { readonly label: string; readonly hint?: string; readonly children: ReactNode }) {
  return (
    <label className="block">
      <span className="text-[13px] font-medium text-muted">{label}</span>
      <span className="mt-1 block">{children}</span>
      {hint !== undefined && <span className="mt-1 block text-[13px] text-muted">{hint}</span>}
    </label>
  );
}

export const inputClass =
  "w-full rounded-sm border border-hairline bg-surface px-3 py-2 text-[15px] num focus-visible:border-signal aria-[invalid=true]:border-critical-mark";

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

export function Section({ id, title, lead, children }: {
  readonly id: string;
  readonly title: string;
  readonly lead?: ReactNode;
  readonly children: ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="mt-16 first:mt-0">
      <h2 id={id} className="text-lg font-semibold">{title}</h2>
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
    <span className={`inline-block whitespace-nowrap rounded-sm px-2 py-0.5 text-[13px] font-medium ${BADGE_TONE[tone]}`}>
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
}

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
                className={`whitespace-nowrap px-4 py-3 text-[13px] font-medium text-muted ${c.numeric === true ? "text-right" : ""}`}
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

export const cell = "whitespace-nowrap px-4 py-3";
export const numCell = `${cell} num text-right`;

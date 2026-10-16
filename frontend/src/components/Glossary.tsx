import { useId, useState, type KeyboardEvent, type ReactNode } from "react";
import { GLOSSARY, GLOSSARY_ORDER, type TermId } from "../data/glossary";

/** Termo com dica: sublinhado pontilhado, abre ao passar o mouse ou focar, fecha com Esc. */
export function Term({ id, children }: { readonly id: TermId; readonly children?: ReactNode }) {
  const tipId = useId();
  const entry = GLOSSARY[id];
  /** A dica abre para a esquerda quando o termo está perto da borda direita da janela. */
  const [alignRight, setAlignRight] = useState(false);
  const place = (el: HTMLElement): void => setAlignRight(el.getBoundingClientRect().left + 270 > window.innerWidth);
  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>): void => {
    if (e.key === "Escape") e.currentTarget.blur();
  };
  return (
    <span className="group relative inline">
      <button
        type="button"
        aria-describedby={tipId}
        onKeyDown={onKeyDown}
        onMouseEnter={(e) => place(e.currentTarget)}
        onFocus={(e) => place(e.currentTarget)}
        className="cursor-help border-b border-dotted border-muted text-left text-inherit"
      >
        {children ?? entry.label}
      </button>
      <span
        id={tipId}
        role="tooltip"
        className={`hidden absolute top-full z-20 w-64 pt-1 ${alignRight ? "right-0" : "left-0"} group-focus-within:block group-hover:block max-md:fixed max-md:inset-x-4 max-md:bottom-4 max-md:top-auto max-md:w-auto max-md:pt-0`}
      >
        <span className="block rounded-md border border-hairline bg-surface p-3 text-left text-[13px] font-normal leading-snug text-ink">
          <strong className="block font-medium">{entry.label}</strong>
          {entry.text}
        </span>
      </span>
    </span>
  );
}

/** Todos os termos de uma vez, para a aba Pesquisa. */
export function GlossaryList() {
  return (
    <dl className="grid gap-x-8 gap-y-4 md:grid-cols-2">
      {GLOSSARY_ORDER.map((id) => (
        <div key={id} className="border-t border-hairline pt-3">
          <dt className="font-medium">{GLOSSARY[id].label}</dt>
          <dd className="mt-1 text-muted">{GLOSSARY[id].text}</dd>
        </div>
      ))}
    </dl>
  );
}

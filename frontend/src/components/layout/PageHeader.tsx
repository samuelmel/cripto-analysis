import type { ReactNode } from "react";

export function PageHeader({
  eyebrow,
  title,
  description,
  meta,
  actions,
}: {
  eyebrow: string;
  title: string;
  description: string;
  meta?: ReactNode;
  actions?: ReactNode;
}): ReactNode {
  return (
    <header className="reveal mb-8 flex flex-col gap-5 border-b border-hairline pb-6 lg:flex-row lg:items-end lg:justify-between">
      <div className="min-w-0">
        <div className="text-[11px] font-medium uppercase tracking-[0.17em] text-signal">{eyebrow}</div>
        <h1 className="display mt-2 max-w-4xl text-[34px] font-semibold text-ink sm:text-[44px]">{title}</h1>
        <p className="mt-3 max-w-3xl text-[14px] leading-relaxed text-muted">{description}</p>
        {meta ? <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-[11px] text-faint">{meta}</div> : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap gap-2">{actions}</div> : null}
    </header>
  );
}

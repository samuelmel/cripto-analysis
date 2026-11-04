import type { ButtonHTMLAttributes, ReactNode } from "react";
import { AlertTriangle, Inbox, RotateCcw } from "lucide-react";

import { cn } from "../../lib/cn";
import { TONE_CLASS } from "../../lib/format";
import type { Tone } from "../../schemas/api";

type ButtonVariant = "primary" | "secondary" | "ghost";

const BUTTON_VARIANT: Record<ButtonVariant, string> = {
  primary: "bg-signal text-white hover:bg-signal-deep border-signal",
  secondary: "bg-raised text-ink hover:bg-sunken border-hairline-strong",
  ghost: "bg-transparent text-muted hover:bg-sunken hover:text-ink border-transparent",
};

export function buttonClass(variant: ButtonVariant = "secondary", className?: string): string {
  return cn(
    "inline-flex h-9 items-center justify-center gap-2 rounded-md border px-3 text-[13px] font-medium transition-colors",
    BUTTON_VARIANT[variant],
    className,
  );
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
}

export function Button({ variant = "secondary", className, type = "button", ...props }: ButtonProps): ReactNode {
  return <button type={type} className={buttonClass(variant, className)} {...props} />;
}

export function Badge({
  tone = "neutral",
  children,
  dot = false,
  className,
}: {
  tone?: Tone;
  children: ReactNode;
  dot?: boolean;
  className?: string;
}): ReactNode {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium tracking-[0.01em]",
        TONE_CLASS[tone],
        className,
      )}
    >
      {dot ? <span className="size-1.5 rounded-full bg-current" aria-hidden /> : null}
      {children}
    </span>
  );
}

export function Panel({
  children,
  className,
  as: Tag = "section",
}: {
  children: ReactNode;
  className?: string;
  as?: "section" | "div" | "article";
}): ReactNode {
  return <Tag className={cn("border border-hairline bg-surface", className)}>{children}</Tag>;
}

export function Stat({
  label,
  value,
  note,
  tone = "neutral",
  mono = true,
}: {
  label: string;
  value: ReactNode;
  note?: ReactNode;
  tone?: Tone;
  mono?: boolean;
}): ReactNode {
  const toneClass =
    tone === "positive" ? "text-good" : tone === "critical" ? "text-critical" : tone === "warning" ? "text-warning" : "text-ink";
  return (
    <div className="min-w-0">
      <div className="text-[11px] font-medium uppercase tracking-[0.13em] text-faint">{label}</div>
      <div className={cn("mt-1 truncate text-[22px] leading-tight", mono && "num", toneClass)}>{value}</div>
      {note ? <div className="mt-1 text-[12px] leading-snug text-muted">{note}</div> : null}
    </div>
  );
}

export function SectionHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}): ReactNode {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 border-b border-hairline pb-4">
      <div className="min-w-0">
        {eyebrow ? (
          <div className="mb-1 text-[11px] font-medium uppercase tracking-[0.16em] text-signal">{eyebrow}</div>
        ) : null}
        <h2 className="display text-[24px] font-semibold text-ink">{title}</h2>
        {description ? <p className="mt-1 max-w-3xl text-[13px] leading-relaxed text-muted">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }): ReactNode {
  return <div className={cn("animate-pulse rounded-sm bg-sunken", className)} aria-hidden />;
}

export function LoadingBlock({ label = "Carregando dados" }: { label?: string }): ReactNode {
  return (
    <div className="space-y-3" role="status" aria-live="polite">
      <span className="sr-only">{label}</span>
      <Skeleton className="h-8 w-56" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-24 w-full" />
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
  icon,
}: {
  title: string;
  description: string;
  action?: ReactNode;
  icon?: ReactNode;
}): ReactNode {
  return (
    <div className="flex flex-col items-start gap-3 border border-dashed border-hairline-strong bg-sunken/40 p-6">
      <div className="text-faint">{icon ?? <Inbox size={22} strokeWidth={1.6} />}</div>
      <div>
        <h3 className="text-[15px] font-semibold text-ink">{title}</h3>
        <p className="mt-1 max-w-xl text-[13px] leading-relaxed text-muted">{description}</p>
      </div>
      {action}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }): ReactNode {
  return (
    <div className="flex flex-col items-start gap-3 border border-critical/20 bg-critical-wash/50 p-6">
      <AlertTriangle size={22} strokeWidth={1.6} className="text-critical" />
      <div>
        <h3 className="text-[15px] font-semibold text-ink">Não foi possível carregar</h3>
        <p className="mt-1 max-w-xl text-[13px] leading-relaxed text-muted">{message}</p>
      </div>
      {onRetry ? (
        <Button variant="secondary" onClick={onRetry}>
          <RotateCcw size={14} />
          Tentar de novo
        </Button>
      ) : null}
    </div>
  );
}

export function InlineNote({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: Tone;
}): ReactNode {
  return (
    <div className={cn("border-l-2 px-3 py-2 text-[12.5px] leading-relaxed", TONE_CLASS[tone].replace("border-", "border-l-"))}>
      {children}
    </div>
  );
}

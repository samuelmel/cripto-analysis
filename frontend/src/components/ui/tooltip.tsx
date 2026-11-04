import * as RadixTooltip from "@radix-ui/react-tooltip";
import { Info } from "lucide-react";
import type { ReactNode } from "react";

export function TooltipProvider({ children }: { children: ReactNode }): ReactNode {
  return <RadixTooltip.Provider delayDuration={220}>{children}</RadixTooltip.Provider>;
}

export function Hint({ text }: { text: string }): ReactNode {
  return (
    <RadixTooltip.Root>
      <RadixTooltip.Trigger asChild>
        <button
          type="button"
          aria-label={text}
          className="inline-flex size-5 items-center justify-center rounded-full text-faint hover:text-ink"
        >
          <Info size={13} />
        </button>
      </RadixTooltip.Trigger>
      <RadixTooltip.Portal>
        <RadixTooltip.Content
          sideOffset={6}
          className="z-50 max-w-64 rounded-md border border-hairline bg-raised px-2.5 py-1.5 text-[12px] leading-snug text-ink shadow-float"
        >
          {text}
          <RadixTooltip.Arrow className="fill-raised" />
        </RadixTooltip.Content>
      </RadixTooltip.Portal>
    </RadixTooltip.Root>
  );
}

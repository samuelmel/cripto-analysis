import * as Tabs from "@radix-ui/react-tabs";
import type { ReactNode } from "react";

import { cn } from "../../lib/cn";

export function SegmentedTabs({
  value,
  onValueChange,
  options,
  label,
}: {
  value: string;
  onValueChange: (value: string) => void;
  options: readonly { readonly value: string; readonly label: string; readonly count?: number }[];
  label: string;
}): ReactNode {
  return (
    <Tabs.Root value={value} onValueChange={onValueChange}>
      <Tabs.List
        aria-label={label}
        className="flex flex-wrap gap-1 rounded-md border border-hairline bg-sunken/70 p-1"
      >
        {options.map((option) => (
          <Tabs.Trigger
            key={option.value}
            value={option.value}
            className={cn(
              "rounded-[4px] px-2.5 py-1.5 text-[12px] font-medium text-muted transition-colors",
              "hover:text-ink data-[state=active]:bg-raised data-[state=active]:text-ink data-[state=active]:shadow-[0_1px_2px_rgb(21_22_19/0.08)]",
            )}
          >
            {option.label}
            {option.count === undefined ? null : (
              <span className="num ml-1.5 text-[10px] text-faint">{option.count}</span>
            )}
          </Tabs.Trigger>
        ))}
      </Tabs.List>
    </Tabs.Root>
  );
}

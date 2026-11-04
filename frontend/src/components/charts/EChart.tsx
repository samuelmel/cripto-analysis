import { useEffect, useId, useRef, type ReactNode } from "react";

import { init, type EChartsCoreOption, type EChartsType } from "../../lib/echarts";
import { cn } from "../../lib/cn";

export function EChart({
  option,
  height = 280,
  label,
  className,
}: {
  option: EChartsCoreOption;
  height?: number;
  label: string;
  className?: string;
}): ReactNode {
  const container = useRef<HTMLDivElement>(null);
  const chart = useRef<EChartsType | null>(null);
  const id = useId();

  useEffect(() => {
    const node = container.current;
    if (!node) return;
    const instance = init(node, undefined, { renderer: "canvas" });
    chart.current = instance;
    const observer = new ResizeObserver(() => instance.resize());
    observer.observe(node);
    return () => {
      observer.disconnect();
      instance.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    chart.current?.setOption(option, { notMerge: true });
  }, [option]);

  return (
    <div
      id={id}
      ref={container}
      role="img"
      aria-label={label}
      className={cn("w-full", className)}
      style={{ height }}
    />
  );
}

import { coinName } from "../data/analytics";
import { coinFullName, coinLogo } from "../data/coins";

export function CoinLogo({ symbol, size = 24 }: { readonly symbol: string; readonly size?: number }) {
  const src = coinLogo(symbol);
  if (src === null) {
    return <span aria-hidden className="inline-block rounded-full bg-hairline" style={{ width: size, height: size }} />;
  }
  return <img src={src} alt="" width={size} height={size} className="shrink-0" />;
}

/** Logo + ticker, com o nome completo embaixo quando `detailed`. */
export function CoinLabel({ symbol, detailed = false, size = 24 }: {
  readonly symbol: string;
  readonly detailed?: boolean;
  readonly size?: number;
}) {
  return (
    <span className="flex items-center gap-3">
      <CoinLogo symbol={symbol} size={size} />
      <span className="leading-tight">
        <span className="font-medium">{coinName(symbol)}</span>
        {detailed && <span className="block text-[13px] text-muted">{coinFullName(symbol)}</span>}
      </span>
    </span>
  );
}

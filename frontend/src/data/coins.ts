/** Logos das moedas (src/assets/coins, CC0). Chave: ticker em minúsculas, ex.: "btc". */
const logos = import.meta.glob<string>("../assets/coins/*.svg", { eager: true, query: "?url", import: "default" });

const byTicker = new Map(
  Object.entries(logos).map(([file, url]) => [file.split("/").at(-1)?.replace(".svg", "") ?? "", url]),
);

export const coinLogo = (symbol: string): string | null =>
  byTicker.get(symbol.split("/")[0]?.toLowerCase() ?? "") ?? null;

const NAMES: Record<string, string> = {
  BTC: "Bitcoin", ETH: "Ethereum", BNB: "BNB", SOL: "Solana", XRP: "XRP", ADA: "Cardano", DOGE: "Dogecoin",
  TRX: "Tron", AVAX: "Avalanche", LINK: "Chainlink", DOT: "Polkadot", LTC: "Litecoin", BCH: "Bitcoin Cash",
  ATOM: "Cosmos", XLM: "Stellar",
};

export const coinFullName = (symbol: string): string => {
  const ticker = symbol.split("/")[0] ?? symbol;
  return NAMES[ticker] ?? ticker;
};

/** Moedas com recomendação de compra. Espelha RECOMMENDED em src/config.py. */
export const RECOMMENDED_SYMBOLS: ReadonlySet<string> = new Set(["BTC/USDT", "ETH/USDT"]);

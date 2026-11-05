"""Esteira de testes de 3 famílias de tendência, com separação estrita In-Sample / Out-of-Sample (dinheiro fictício).

Dados: candles de 1h da Binance em `data/archive_1h` (`research/download_1h.py`): BTC, ETH, BNB, SOL, XRP, ADA, DOGE.

Protocolo (fixado no código, antes de ver resultado):
    divisão     In-Sample até 2022-12-31 23:00 UTC (só aqui os parâmetros são escolhidos); Out-of-Sample de 2023-01-01 até o fim
                (avaliado UMA vez, com os parâmetros já congelados). Indicadores são causais: o OOS usa o histórico anterior só
                para aquecimento, sem nenhum dado futuro.
    seleção     UM conjunto de parâmetros por família, comum às 7 moedas: o de maior Calmar médio no IS (sem otimizar por moeda;
                menos graus de liberdade = menos curve-fitting). Configuração com poucas operações no IS é desclassificada.
    execução    sinal ao fechar o candle t, ordem na ABERTURA do candle t+1; custo fixo de 0,25% por transação (a cada mudança de posição).
    posição     comprado ou fora (sem alavancagem, sem venda a descoberto).
    métricas    CAGR, Calmar (CAGR / |drawdown máximo|), Sharpe (anualizado, 8.766 candles/ano) e drawdown máximo, contra comprar-e-segurar
                na mesma janela.
    famílias    1) Donchian (rompimento da máxima de N candles; saída na mínima de N/2)
                2) Média adaptativa (HMA ou KAMA): comprado com o fechamento acima da média
                3) Cruzamento de médias simples habilitado só com ADX acima de um limite (regime de tendência)
    Nº de configurações testadas por família é impresso: mais configurações = mais chance de acerto por sorte.

    uv run python research/strategy_tester.py
"""
from __future__ import annotations

import itertools
import warnings
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", message="Mean of empty slice")
COINS = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE"]
DATA_DIR = Path("data/archive_1h")
COST = 0.0025                                   # por transação
PER_YEAR = 365.25 * 24
SPLIT = pd.Timestamp("2023-01-01", tz="UTC")    # OOS começa aqui
MIN_TRADES_IS = 10                              # abaixo disso a configuração não é elegível
DAY = 24

Params = tuple[float, ...]
Signal = Callable[[pd.DataFrame, Params], pd.Series]


# ---------------------------------------------------------------- indicadores (puros, causais)

def wma(x: pd.Series, n: int) -> pd.Series:
    """Média móvel ponderada linear (peso maior no mais recente), em O(len) via somas acumuladas. Aceita NaN no início."""
    n = max(int(n), 1)
    out = pd.Series(np.nan, index=x.index)
    valid = x.dropna()
    if len(valid) < n:
        return out
    v = valid.to_numpy(dtype="float64")
    scale = float(np.mean(v)) or 1.0
    v = v / scale
    idx = np.arange(len(v), dtype="float64")
    s, w = np.cumsum(v), np.cumsum(idx * v)
    s0, w0 = np.r_[np.zeros(n), s[:-n]], np.r_[np.zeros(n), w[:-n]]
    num = (n - idx) * (s - s0) + (w - w0)       # soma de (n - k) * x[t-k], k = 0..n-1
    res = num / (n * (n + 1) / 2) * scale
    res[: n - 1] = np.nan
    out.loc[valid.index] = res
    return out


def hma(x: pd.Series, n: int) -> pd.Series:
    """Hull MA: WMA(2 * WMA(n/2) - WMA(n), sqrt(n))."""
    half, root = max(n // 2, 1), max(int(round(math.sqrt(n))), 1)
    return wma(2 * wma(x, half) - wma(x, n), root)


def kama(x: pd.Series, n: int, fast: int = 2, slow: int = 30) -> pd.Series:
    """Kaufman Adaptive MA: a suavização depende da eficiência (|variação líquida| / soma das variações) em n candles."""
    change = (x - x.shift(n)).abs()
    vol = x.diff().abs().rolling(n).sum()
    er = (change / vol.replace(0.0, np.nan)).fillna(0.0).to_numpy()
    sc = (er * (2 / (fast + 1) - 2 / (slow + 1)) + 2 / (slow + 1)) ** 2
    px = x.to_numpy(dtype="float64")
    out = np.full(len(px), np.nan)
    start = n
    if len(px) > start:
        out[start] = px[start]
        for i in range(start + 1, len(px)):
            out[i] = out[i - 1] + sc[i] * (px[i] - out[i - 1])
    return pd.Series(out, index=x.index)


def adx(df: pd.DataFrame, n: int) -> pd.Series:
    """ADX de Wilder (suavização exponencial com alpha = 1/n)."""
    up, dn = df["high"].diff(), -df["low"].diff()
    plus = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    pdi = 100 * plus.ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / atr
    mdi = 100 * minus.ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0.0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def daily_adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """ADX(14) calculado no gráfico DIÁRIO (a escala dos limites 20/25/30), com o valor do dia anterior já fechado (causal),
    repetido nos candles de 1h do dia seguinte."""
    d = df.resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    return adx(d, n).shift(1).reindex(df.index, method="ffill")


# ---------------------------------------------------------------- famílias: devolvem posição desejada (0/1) ao fechar cada candle

def donchian(df: pd.DataFrame, p: Params) -> pd.Series:
    n = int(p[0])
    upper = df["high"].rolling(n).max().shift(1)                      # máxima dos N candles ANTERIORES
    lower = df["low"].rolling(max(n // 2, 1)).min().shift(1)
    state = pd.Series(np.nan, index=df.index)
    state[df["close"] > upper] = 1.0
    state[df["close"] < lower] = 0.0
    return state.ffill().fillna(0.0)


def adaptive_ma(df: pd.DataFrame, p: Params) -> pd.Series:
    kind, n = int(p[0]), int(p[1])                                    # kind: 0 = HMA, 1 = KAMA
    ma = hma(df["close"], n) if kind == 0 else kama(df["close"], n)
    return (df["close"] > ma).astype(float).where(ma.notna(), 0.0)


def sma_cross_adx(df: pd.DataFrame, p: Params) -> pd.Series:
    fast, slow, thr = int(p[0]), int(p[1]), float(p[2])
    f, s = df["close"].rolling(fast).mean(), df["close"].rolling(slow).mean()
    strong = daily_adx(df) > thr
    return ((f > s) & strong).astype(float).where(s.notna() & strong.notna(), 0.0)


def sma_cross_adx_1h(df: pd.DataFrame, p: Params) -> pd.Series:
    """Tudo na escala de 1h (períodos em horas): SMA rápida x SMA lenta, habilitado só com ADX(n horas) acima do limite."""
    fast, slow, n_adx, thr = int(p[0]), int(p[1]), int(p[2]), float(p[3])
    f, s = df["close"].rolling(fast).mean(), df["close"].rolling(slow).mean()
    a = adx(df, n_adx)
    return ((f > s) & (a > thr)).astype(float).where(s.notna() & a.notna(), 0.0)


@dataclass(frozen=True)
class Family:
    name: str
    signal: Signal
    grid: list[Params]
    describe: Callable[[Params], str]
    min_trades: int = MIN_TRADES_IS


FAMILIES = [
    Family("Donchian", donchian, [(float(d * DAY),) for d in (5, 10, 20, 40, 60)],
           lambda p: f"N={int(p[0]) // DAY}d"),
    Family("MA adaptativa", adaptive_ma, [(float(k), float(d * DAY)) for k in (0, 1) for d in (5, 10, 20, 40)],
           lambda p: f"{'HMA' if p[0] == 0 else 'KAMA'} {int(p[1]) // DAY}d"),
    Family("SMA cruz + ADX", sma_cross_adx,
           [(float(f * DAY), float(s * DAY), float(t)) for f, s, t in itertools.product((5, 10, 20), (40, 60, 100), (20, 25, 30))],
           lambda p: f"SMA {int(p[0]) // DAY}/{int(p[1]) // DAY}d ADX>{int(p[2])}"),
    # tudo em 1h; exige >= 100 operações no IS em TODAS as moedas para ser elegível
    Family("SMA+ADX 1h", sma_cross_adx_1h,
           [(float(f), float(sl), float(n), float(t)) for f, sl, n, t in itertools.product((24, 48), (168, 336), (48, 72), (15, 20, 25))],
           lambda p: f"SMA {int(p[0])}/{int(p[1])}h ADX{int(p[2])}h>{int(p[3])}", min_trades=100),
]


# ---------------------------------------------------------------- motor de backtest vetorizado

def load(symbol: str) -> pd.DataFrame:
    return pd.read_parquet(DATA_DIR / f"{symbol}_USDT.parquet").set_index("timestamp").sort_index()[["open", "high", "low", "close"]]


def strategy_returns(df: pd.DataFrame, pos: pd.Series) -> pd.Series:
    """Retorno por candle: a posição decidida no fechamento de t-1 executa na abertura de t e rende até a abertura de t+1."""
    oo = (df["open"].shift(-1) / df["open"] - 1.0).fillna(0.0)
    held = pos.shift(1).fillna(0.0)
    return held * oo - held.diff().abs().fillna(held.abs()) * COST


def buy_hold_returns(df: pd.DataFrame) -> pd.Series:
    oo = (df["open"].shift(-1) / df["open"] - 1.0).fillna(0.0)
    r = oo.copy()
    r.iloc[0] -= COST                                                 # entrada única
    return r


def metrics(ret: pd.Series) -> dict[str, float]:
    eq = (1.0 + ret).cumprod()
    years = len(ret) / PER_YEAR
    cagr = float(eq.iloc[-1]) ** (1 / years) - 1 if years > 0 and float(eq.iloc[-1]) > 0 else -1.0
    maxdd = float((eq / eq.cummax() - 1.0).min())
    sd = float(ret.std())
    return {"cagr": cagr, "maxdd": maxdd, "calmar": cagr / abs(maxdd) if maxdd < 0 else math.nan,
            "sharpe": float(ret.mean() / sd * math.sqrt(PER_YEAR)) if sd > 0 else math.nan}


def n_trades(pos: pd.Series) -> int:
    return int(pos.shift(1).fillna(0.0).diff().abs().sum() // 2)


def split(x: pd.DataFrame | pd.Series, part: str) -> pd.DataFrame | pd.Series:
    return x[x.index < SPLIT] if part == "IS" else x[x.index >= SPLIT]


def evaluate(df: pd.DataFrame, fam: Family, p: Params, part: str) -> tuple[dict[str, float], dict[str, float], int, float]:
    pos = fam.signal(df, p)                                           # indicador calculado na série inteira (causal)
    ret = split(strategy_returns(df, pos), part)
    p_part = split(pos, part)
    assert isinstance(ret, pd.Series) and isinstance(p_part, pd.Series)
    bh = split(buy_hold_returns(df), part)
    assert isinstance(bh, pd.Series)
    return metrics(ret), metrics(bh), n_trades(p_part), float(p_part.shift(1).fillna(0.0).mean())


# ---------------------------------------------------------------- seleção no IS e teste cego no OOS

def select_in_sample(frames: dict[str, pd.DataFrame], fam: Family) -> tuple[Params, pd.DataFrame]:
    """Escolhe, SÓ com dados do IS, o parâmetro de maior Calmar médio entre as moedas. Devolve também a tabela do IS."""
    rows = []
    for p in fam.grid:
        per = [evaluate(df, fam, p, "IS") for df in frames.values()]
        calmars = [m["calmar"] for m, _, _, _ in per]
        rows.append({"param": fam.describe(p), "_p": p, "calmar_is": float(np.nanmean(calmars)),
                     "sharpe_is": float(np.nanmean([m["sharpe"] for m, _, _, _ in per])),
                     "maxdd_is%": float(np.nanmean([m["maxdd"] for m, _, _, _ in per])) * 100,
                     "min_ops": min(t for _, _, t, _ in per)})
    table = pd.DataFrame(rows)
    ok = table[table["min_ops"] >= fam.min_trades]
    table["elegivel"] = table["min_ops"] >= fam.min_trades
    if ok.empty:
        print(f"AVISO: nenhuma configuração de '{fam.name}' tem >= {fam.min_trades} operações no IS em todas as moedas; "
              "escolha feita SEM o filtro (menos confiável).")
    best = (ok if not ok.empty else table).sort_values("calmar_is", ascending=False).iloc[0]
    return best["_p"], table.drop(columns="_p").sort_values("calmar_is", ascending=False)


def main() -> None:
    frames = {c: load(c) for c in COINS}
    pd.set_option("display.width", 220, "display.max_rows", 200)
    print(f"IS: início de cada moeda até {SPLIT:%Y-%m-%d} (exclusive) | OOS: {SPLIT:%Y-%m-%d} em diante | custo {COST:.2%} por transação\n")
    total_cfg = sum(len(f.grid) for f in FAMILIES)
    summary = []
    for fam in FAMILIES:
        p, table = select_in_sample(frames, fam)
        print(f"=== {fam.name}: {len(fam.grid)} configurações no IS | escolhida: {fam.describe(p)} ===")
        print(table.head(5).round(2).to_string(index=False))
        rows = []
        for sym, df in frames.items():                                # OOS: uma única avaliação, parâmetros congelados
            m, b, trades, expo = evaluate(df, fam, p, "OOS")
            rows.append({"moeda": sym, "cagr%": m["cagr"] * 100, "calmar": m["calmar"], "sharpe": m["sharpe"], "maxdd%": m["maxdd"] * 100,
                         "bh_cagr%": b["cagr"] * 100, "bh_calmar": b["calmar"], "bh_sharpe": b["sharpe"], "bh_maxdd%": b["maxdd"] * 100,
                         "expo%": expo * 100, "ops": trades})
        oos = pd.DataFrame(rows)
        oos["bate_calmar"], oos["bate_sharpe"] = oos["calmar"] > oos["bh_calmar"], oos["sharpe"] > oos["bh_sharpe"]
        oos["dd_menor"] = oos["maxdd%"] > oos["bh_maxdd%"]
        print(f"\nOOS (teste cego) — {fam.describe(p)}:")
        print(oos.drop(columns=["bate_calmar", "bate_sharpe", "dd_menor"]).round(2).to_string(index=False))
        mean = oos[["cagr%", "calmar", "sharpe", "maxdd%", "bh_cagr%", "bh_calmar", "bh_sharpe", "bh_maxdd%"]].mean()
        print("média:", ", ".join(f"{k}={v:.2f}" for k, v in mean.items()))
        print(f"bate comprar-e-segurar em: Calmar {oos['bate_calmar'].sum()}/7, Sharpe {oos['bate_sharpe'].sum()}/7, drawdown menor {oos['dd_menor'].sum()}/7\n")
        summary.append({"familia": fam.name, "param": fam.describe(p), "calmar": mean["calmar"], "bh_calmar": mean["bh_calmar"], "sharpe": mean["sharpe"],
                        "bh_sharpe": mean["bh_sharpe"], "maxdd%": mean["maxdd%"], "bh_maxdd%": mean["bh_maxdd%"],
                        "bate_calmar": int(oos["bate_calmar"].sum()), "bate_sharpe": int(oos["bate_sharpe"].sum())})
    print(f"=== RESUMO OOS (médias das 7 moedas; {total_cfg} configurações testadas no IS no total) ===")
    print(pd.DataFrame(summary).round(2).to_string(index=False))
    print("\nObservação: resultado exploratório, sem intervalo de confiança nem correção para múltiplos testes; "
          "ordem dentro do candle de 1h suposta (OHLC); 7 ativos correlacionados.")


if __name__ == "__main__":
    main()

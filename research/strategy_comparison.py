"""Pesquisa que embasa a regra de compra: compara estratégias em carteira, treino x teste.

Reproduz a tabela do README. Uso (da raiz do projeto, com a base local já montada pelo pipeline):

    uv run python research/strategy_comparison.py

Metodologia (a mesma de `src.transformers.trade_simulator.evaluate_portfolio`):
    - a posição decidida no fechamento do dia t vale para o retorno de t+1;
    - taxa de 0,1% sobre a mudança de posição;
    - carteira de peso igual entre as moedas que já têm dados;
    - todas as estratégias só começam quando a SMA 200 da moeda existe;
    - treino 2018–2022 (onde a regra foi escolhida) e teste 2023–2026 (dados que a escolha não viu).

Estratégias:
    1 comprar e segurar
    2 regra antiga (pânico: zscore_90 < -2.5, RSI < 30, F&G < 25, com as saídas antigas)
    3 tendência: fechamento acima da SMA 200 da própria moeda
    4 tendência + BTC em alta: a regra do painel (3 mais o filtro do BTC), sem o STOP de -20%
    5 cruzamento: SMA 50 acima da SMA 200
    6 momento: retorno de 90 dias positivo
    7 queda dentro da alta: compra a queda (zscore_90 < -1) com a moeda acima da SMA 200

Limitações: universo = moedas que existem hoje (viés de sobrevivência); uma única amostra histórica,
com poucos ciclos de mercado; sem impostos; execução ideal no fechamento. Passado não garante futuro.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import FEE_PER_SIDE, RECOMMENDED, TEST_PERIOD, TRAIN_PERIOD, UNIVERSE  # noqa: E402
from src.loaders.market_store import read_fng, read_ohlcv  # noqa: E402
from src.transformers.anomaly_detector import classify_history  # noqa: E402
from src.transformers.panic_backtest import panic_trades  # noqa: E402
from src.transformers.trade_simulator import evaluate_portfolio, positions_from_trades, wide  # noqa: E402

BENCHMARK = "BTC/USDT"


def dip_in_uptrend(
    px: pd.DataFrame, sma200: pd.DataFrame, z: pd.DataFrame, enter_z: float = -1.0, exit_z: float = 1.0
) -> pd.DataFrame:
    """Compra a queda (z < enter_z) com a moeda acima da SMA 200; sai com z >= exit_z ou 3% abaixo da SMA 200."""
    pos = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    for c in px.columns:
        inside = False
        out: list[float] = []
        for p, s2, zz in zip(px[c].to_numpy(), sma200[c].to_numpy(), z[c].to_numpy(), strict=True):
            up = bool(p > s2) if not np.isnan(s2) else False
            if not inside and up and zz < enter_z:
                inside = True
            elif inside and (zz >= exit_z or (not np.isnan(s2) and p < s2 * 0.97)):
                inside = False
            out.append(1.0 if inside else 0.0)
        pos[c] = out
    return pos


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    candles = read_ohlcv(list(UNIVERSE))
    if candles.empty:
        print("base local vazia: rode `uv run python -m src.pipeline` antes")
        return 1
    history = classify_history(candles, read_fng())

    px = wide(history, "close")
    z = wide(history, "zscore_90")
    ret = px.pct_change(fill_method=None)
    sma50 = px.rolling(50).mean()
    sma200 = wide(history, "sma_200")
    valid = sma200.notna()
    btc_up = px[BENCHMARK] > sma200[BENCHMARK]

    strategies: dict[str, pd.DataFrame] = {
        "1 comprar e segurar": pd.DataFrame(1.0, index=px.index, columns=px.columns),
        "2 regra antiga (pânico)": positions_from_trades(panic_trades(history), pd.DatetimeIndex(px.index), px.columns),
        "3 tendência (> SMA200)": (px > sma200).astype(float),
        "4 tendência + BTC em alta": ((px > sma200) & btc_up.to_numpy()[:, None]).astype(float),
        "5 cruzamento SMA50 > SMA200": (sma50 > sma200).astype(float),
        "6 momento 90 dias > 0": (px / px.shift(90) - 1 > 0).astype(float),
        "7 queda dentro da alta": dip_in_uptrend(px, sma200, z),
    }
    periods = {
        "treino 2018–2022": tuple(pd.Timestamp(d, tz="UTC") for d in TRAIN_PERIOD),
        "teste 2023–2026": tuple(pd.Timestamp(d, tz="UTC") for d in TEST_PERIOD),
    }
    universes = {"15 moedas": list(px.columns), "só BTC e ETH": [s for s in RECOMMENDED if s in px.columns]}

    pd.set_option("display.width", 200)
    for universe, cols in universes.items():
        for label, (start, end) in periods.items():
            rows = []
            for name, positions in strategies.items():
                m = evaluate_portfolio(positions[cols], ret[cols], valid[cols], start, end, FEE_PER_SIDE)
                rows.append(
                    (name, m["total"], m["annual"], m["drawdown"], m["sharpe"], m["invested"])
                )
            table = pd.DataFrame(
                rows, columns=["estratégia", "total %", "ao ano %", "pior queda %", "sharpe", "tempo comprado %"]
            ).round(1)
            print(f"\n=== {universe} · {label} · peso igual, taxa {FEE_PER_SIDE:.1%} ===")
            print(table.sort_values("sharpe", ascending=False).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

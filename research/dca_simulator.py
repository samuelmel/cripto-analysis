"""Simulador de Smart DCA x DCA fixo com aporte SEMANAL e caixa finito. Dinheiro fictício; nenhuma ordem real.

Regras (fixadas aqui antes da execução; mudar qualquer uma é um protocolo novo):
    aporte      R$ 100 por semana, no fechamento do domingo (a decisão é tomada com dados até esse fechamento)
    execução    abertura do dia seguinte, custo de 0,25% sobre o valor comprado; sem alavancagem, sem venda
    DCA fixo    compra todo o aporte da semana; o caixa nunca acumula
    DCA inteligente  recebe o mesmo aporte no cofre; compra `m x f x aporte`, com `f` o lote-base (fração do aporte) e `m` conforme
                a queda `dd` do fechamento contra a máxima histórica de fechamento conhecida até o dia:
                dd > -20% -> 1x; -40% < dd <= -20% -> 3x; dd <= -40% -> 5x. Sem saldo para o múltiplo, compra o que o cofre permite (esvazia).
                O que não é usado fica no caixa e sofre o arrasto de não estar investido (cash drag).
    janelas     inícios anuais (1º de janeiro) de 2013 a 2022, horizontes de 3 e de 5 anos; só entram janelas que cabem inteiras na base
                (ETH só tem dados desde 2017-08; BTC desde 2011-08). Janelas sobrepostas: não são independentes.
    principal   f = 0,5 (sensibilidade descritiva: 0,25 e 0,75)
    isolamento  `isolate_infinite_cash`: SEM restrição de caixa; o gasto é reescalado para o MESMO total do DCA fixo, só para medir se o preço médio cai.
                A reescala usa o total da janela (conhecido só depois): é análise de isolamento, não uma regra operável.
    critério    promissor se vencer o fixo em valor final por real aportado em > 60% das janelas nos dois horizontes e com diferença média > 0.
                "Fatal": janela em que o inteligente perde mais de 5% do valor final por real aportado para o fixo.

    uv run python research/dca_simulator.py            # BTC e ETH, instâncias independentes
    uv run python research/dca_simulator.py --asset BTC
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import cast
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dca_study import load  # noqa: E402

CONTRIBUTION = 100.0                       # R$ por semana
COST = 0.0025
LOT_TIERS = ((-0.40, 5.0), (-0.20, 3.0))   # dd <= limiar -> multiplicador (do mais fundo ao mais raso); acima de -20%: 1x
PRIMARY_F = 0.5
SENSITIVITY_F = (0.25, 0.75)
START_YEARS = range(2013, 2023)
HORIZONS = (3, 5)
FATAL_LOSS_PCT = -5.0
WIN_SHARE = 0.60
FIXED, SMART = "fixo", "inteligente"


def multiplier(drawdown: float) -> float:
    """Multiplicador do lote-base conforme a queda contra a máxima histórica (drawdown <= 0)."""
    for limit, m in LOT_TIERS:
        if drawdown <= limit:
            return m
    return 1.0


@dataclass(frozen=True)
class Outcome:
    value_per_real: float     # (inventário x último fechamento + caixa) / total aportado
    avg_price: float          # gasto / unidades compradas (custo de execução incluído)
    deployed_pct: float       # gasto / aportado
    idle_cash_pct: float      # caixa não comprometido / patrimônio, média nos fechamentos de domingo
    max_drawdown_pct: float   # pior queda da razão patrimônio / aportado acumulado
    spent: float
    units: float


def price(px: pd.DataFrame, col: str, day: pd.Timestamp) -> float:
    return float(cast(float, px[col].loc[day]))


def decision_days(px: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    """Domingos da janela com abertura do dia seguinte dentro da janela (a ordem precisa ter onde ser executada)."""
    idx = pd.DatetimeIndex(px.index)
    days = idx[(idx >= start) & (idx <= end) & (idx.weekday == 6)]
    return pd.DatetimeIndex([d for d in days if d + pd.Timedelta(days=1) <= end])


def simulate(px: pd.DataFrame, ath: pd.Series, start: pd.Timestamp, end: pd.Timestamp, mode: str, f: float = PRIMARY_F) -> Outcome:
    """Itera os domingos mantendo o estado Caixa e Inventário. `mode`: FIXED ou SMART (caixa finito)."""
    days = decision_days(px, start, end)
    cash = units = spent = contributed = 0.0
    ratios: list[float] = []
    idle: list[float] = []
    for d in days:
        close, next_open = price(px, "close", d), price(px, "open", d + pd.Timedelta(days=1))
        cash += CONTRIBUTION
        contributed += CONTRIBUTION
        if mode == FIXED:
            desired = CONTRIBUTION
        else:
            desired = multiplier(close / float(ath.loc[d]) - 1.0) * f * CONTRIBUTION
        spend = min(desired, cash)                                        # fallback: sem saldo, compra o que o cofre permite
        cash -= spend
        equity = cash + spend + units * close                             # a ordem reservada vale seu valor de face até executar
        ratios.append(equity / contributed)
        idle.append(cash / equity if equity > 0 else 0.0)
        units += spend / (next_open * (1.0 + COST))
        spent += spend
    last_close = float(px.loc[:end, "close"].iloc[-1])
    value = cash + units * last_close
    r = np.asarray(ratios)
    return Outcome(value / contributed, spent / units if units > 0 else float("nan"), spent / contributed * 100.0,
                   float(np.mean(idle)) * 100.0, float((r / np.maximum.accumulate(r) - 1.0).min()) * 100.0, spent, units)


def isolate_infinite_cash(px: pd.DataFrame, ath: pd.Series, start: pd.Timestamp, end: pd.Timestamp, fixed: Outcome, f: float = PRIMARY_F) -> tuple[float, float]:
    """Isolamento: Smart DCA com caixa infinito (compra sempre `m x f x aporte`), com o gasto reescalado para o MESMO total do fixo.
    Devolve (preço médio, valor final por real gasto). A reescala usa o total da janela: análise, não regra operável."""
    spent = units = 0.0
    for d in decision_days(px, start, end):
        spend = multiplier(price(px, "close", d) / float(ath.loc[d]) - 1.0) * f * CONTRIBUTION
        units += spend / (price(px, "open", d + pd.Timedelta(days=1)) * (1.0 + COST))
        spent += spend
    scale = fixed.spent / spent
    units *= scale
    last_close = float(px.loc[:end, "close"].iloc[-1])
    return fixed.spent / units, units * last_close / fixed.spent


def build_windows(px: pd.DataFrame, years: int) -> tuple[list[tuple[pd.Timestamp, pd.Timestamp]], list[int]]:
    ok, skipped = [], []
    for y in START_YEARS:
        s = pd.Timestamp(year=y, month=1, day=1, tz="UTC")
        e = s + pd.DateOffset(years=years) - pd.Timedelta(days=1)
        if s >= px.index.min() and e <= px.index.max():
            ok.append((s, e))
        else:
            skipped.append(y)
    return ok, skipped


def evaluate(px: pd.DataFrame, years: int) -> tuple[pd.DataFrame, list[int]]:
    """Uma linha por janela: fixo x inteligente (f principal e sensibilidade) e o isolamento de caixa infinito."""
    ath = px["close"].cummax()
    windows, skipped = build_windows(px, years)
    rows = []
    for s, e in windows:
        fixed = simulate(px, ath, s, e, FIXED)
        row: dict[str, float | str | int] = {"ano": s.year, "fixo": fixed.value_per_real, "fixo_dd%": fixed.max_drawdown_pct}
        for f in (PRIMARY_F, *SENSITIVITY_F):
            o = simulate(px, ath, s, e, SMART, f)
            row[f"dif_f{f}%"] = (o.value_per_real / fixed.value_per_real - 1.0) * 100.0
            if f == PRIMARY_F:
                row.update({"inteligente": o.value_per_real, "preco_medio_rel": o.avg_price / fixed.avg_price, "investido%": o.deployed_pct,
                            "ocioso%": o.idle_cash_pct, "int_dd%": o.max_drawdown_pct})
        avg_inf, value_inf = isolate_infinite_cash(px, ath, s, e, fixed)
        row["inf_preco_medio_rel"] = avg_inf / fixed.avg_price
        row["inf_valor_rel%"] = (value_inf / (fixed.value_per_real * fixed.deployed_pct / 100.0) - 1.0) * 100.0
        row["alta_ativo%"] = (float(px.loc[:e, "close"].iloc[-1]) / float(px.loc[:s, "close"].iloc[-1]) - 1.0) * 100.0
        rows.append(row)
    return pd.DataFrame(rows), skipped


def summarize(table: pd.DataFrame, col: str) -> dict[str, float]:
    d = table[col]
    return {"n": float(len(d)), "wins": float((d > 0).sum()), "win_rate": float((d > 0).mean()), "mean": float(d.mean()),
            "median": float(d.median()), "worst": float(d.min()), "best": float(d.max())}


def report(asset: str, px: pd.DataFrame) -> bool | None:
    pd.set_option("display.width", 250, "display.max_columns", 40)
    line = "=" * 100
    print(f"\n{line}\n{asset}: dados de {px.index.min():%Y-%m-%d} a {px.index.max():%Y-%m-%d} | aporte R$ {CONTRIBUTION:.0f}/semana | custo {COST:.2%} | lote-base f={PRIMARY_F}\n{line}")
    verdict: dict[int, dict[str, float]] = {}
    for years in HORIZONS:
        t, skipped = evaluate(px, years)
        print(f"\n--- {asset}, horizonte de {years} anos: {len(t)} janelas" + (f" (anos sem janela completa: {skipped})" if skipped else "") + " ---")
        if t.empty:
            continue
        t["resultado"] = np.where(t["dif_f0.5%"] > 0, "VITORIA", np.where(t["dif_f0.5%"] <= FATAL_LOSS_PCT, "FATAL", "derrota"))
        show = ["ano", "fixo", "inteligente", "dif_f0.5%", "resultado", "preco_medio_rel", "investido%", "ocioso%", "int_dd%", "fixo_dd%", "alta_ativo%"]
        print("Valor final por real aportado (caixa que sobrou incluído); preco_medio_rel = preço médio do inteligente / do fixo")
        print(t[show].round(3).to_string(index=False))
        for f in (PRIMARY_F, *SENSITIVITY_F):
            s = summarize(t, f"dif_f{f}%")
            tag = "PRINCIPAL" if f == PRIMARY_F else "sensibilidade"
            print(f"  f={f} ({tag}): vitórias {int(s['wins'])}/{int(s['n'])} ({s['win_rate']:.0%}); média {s['mean']:+.2f}%, mediana {s['median']:+.2f}%, "
                  f"pior {s['worst']:+.2f}%, melhor {s['best']:+.2f}%")
        fatal = t[t["resultado"] == "FATAL"]
        if len(fatal):
            print(f"  Janelas FATAIS (perda > {-FATAL_LOSS_PCT:.0f}% para o fixo): " + "; ".join(
                f"{int(r['ano'])} (dif {r['dif_f0.5%']:+.1f}%, ocioso médio {r['ocioso%']:.1f}%, ativo {r['alta_ativo%']:+.0f}% no período)"
                for _, r in fatal.iterrows()))
            print("  -> nesses anos a reserva ficou parada enquanto o ativo subia: o arrasto de caixa superou o ganho de comprar mais nas quedas.")
        else:
            print(f"  Nenhuma janela fatal (perda > {-FATAL_LOSS_PCT:.0f}%).")
        print(f"  Isolamento (caixa infinito, mesmo gasto total do fixo): preço médio relativo médio {t['inf_preco_medio_rel'].mean():.4f} "
              f"(< 1 = mais barato), menor em {int((t['inf_preco_medio_rel'] < 1).sum())}/{len(t)} janelas; valor final relativo médio {t['inf_valor_rel%'].mean():+.2f}%")
        verdict[years] = summarize(t, "dif_f0.5%")
    if len(verdict) < len(HORIZONS):
        print(f"\n>>> {asset}: sem janelas suficientes para um veredito nos dois horizontes.")
        return None
    ok = all(v["win_rate"] > WIN_SHARE and v["mean"] > 0 for v in verdict.values())
    print(f"\n>>> {asset}: {'PROMISSOR' if ok else 'REJEITADO'} (critério: > {WIN_SHARE:.0%} de vitórias nos dois horizontes e diferença média > 0): "
          + "; ".join(f"{y}a: {v['win_rate']:.0%} de {int(v['n'])} janelas, média {v['mean']:+.2f}%" for y, v in verdict.items()))
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="Smart DCA x DCA fixo (caixa finito)")
    ap.add_argument("--asset", choices=("BTC", "ETH"), default=None)
    args = ap.parse_args()
    for asset in ([args.asset] if args.asset else ["BTC", "ETH"]):
        report(asset, load(asset))                      # instâncias independentes por ativo
    print("\nExploratório: um caminho de preços por ativo, janelas sobrepostas, sem intervalo de confiança.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

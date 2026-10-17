"""Estudo das regras de saída das posições. Protocolo: docs/exit_rules.md (fixado antes dos resultados).

Entrypoint (CLAUDE.md §1): lê a base point-in-time, chama as funções puras de `exit_rules` e grava Parquet.

    uv run python research/exit_rules_study.py

Saídas (versionadas, lidas pelo pipeline diário): `evidence/exit_rules.parquet` (o que cada regra fez e o trailing adotado,
se houver), `evidence/exit_rules_trailing.parquet` (grade do trailing) e `evidence/exit_rules_trades.parquet` (operações da
referência, desenvolvimento). O teste final só é avaliado se um trailing for adotado, e só pode revogá-lo.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.loaders.parquet_loader import write_parquet  # noqa: E402
from src.transformers.exit_rules import (  # noqa: E402
    EXIT_TRAILING,
    TRAILING_GRID,
    ExitParams,
    adopted_trailing,
    compare_trailing,
    holdout_vetoes,
    rule_report,
    simulate_trades,
)
from src.transformers.signal_validation import ValidationRules, prepare  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from signal_evidence_study import EVIDENCE_DIR, load_candles  # noqa: E402

RULES_PATH = EVIDENCE_DIR / "exit_rules.parquet"
GRID_PATH = EVIDENCE_DIR / "exit_rules_trailing.parquet"
TRADES_PATH = EVIDENCE_DIR / "exit_rules_trades.parquet"

EXIT_RULES_SCHEMA: dict[str, str] = {
    "rule": "string",
    "adopted": "bool",
    "param": "float64",
    "n": "Int64",
    "mean_return": "float64",
    "median_return": "float64",
    "mean_post_exit_30d": "float64",
    "share_fell_after": "float64",
    "note": "string",
}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    rules = ValidationRules()
    candles = load_candles()
    prep = prepare(candles, rules)
    data_end = pd.Timestamp(candles["timestamp"].max())
    dev_end, hold_start = rules.dev_end, rules.hold_start

    base_params = ExitParams()
    base = simulate_trades(prep, base_params, entries_from=None, entries_to=dev_end, data_end=dev_end)
    variants = {x: simulate_trades(prep, ExitParams(trailing=x), entries_from=None, entries_to=dev_end, data_end=dev_end) for x in TRAILING_GRID}
    grid = compare_trailing(base, variants)
    chosen = adopted_trailing(grid)

    vetoed = False
    hold_note = "teste final não avaliado: nenhum trailing foi adotado no desenvolvimento"
    if chosen is not None:
        h_base = simulate_trades(prep, base_params, entries_from=hold_start, entries_to=data_end, data_end=data_end)
        h_trail = simulate_trades(prep, ExitParams(trailing=chosen), entries_from=hold_start, entries_to=data_end, data_end=data_end)
        vetoed = holdout_vetoes(h_base, h_trail)
        hold_note = f"teste final: {len(h_base)} operações, {'revogou' if vetoed else 'não revogou'} o trailing"
        if vetoed:
            chosen = None

    report = rule_report(base)
    rows = []
    for r in report.itertuples():
        rows.append({"rule": r.rule, "adopted": True, "param": config_param(str(r.rule)), "n": r.n, "mean_return": r.mean_return,
                     "median_return": r.median_return, "mean_post_exit_30d": r.mean_post_exit_30d,
                     "share_fell_after": r.share_fell_after, "note": "referência, desenvolvimento até " + str(rules.development_end)})
    trail_rep = rule_report(variants[chosen]) if chosen is not None else rule_report(variants[0.20])
    t = trail_rep[trail_rep["rule"].eq(EXIT_TRAILING)]
    rows.append({
        "rule": EXIT_TRAILING, "adopted": chosen is not None, "param": float(chosen if chosen is not None else 0.20),
        "n": int(t["n"].iloc[0]) if len(t) else 0,
        "mean_return": float(t["mean_return"].iloc[0]) if len(t) else float("nan"),
        "median_return": float(t["median_return"].iloc[0]) if len(t) else float("nan"),
        "mean_post_exit_30d": float(t["mean_post_exit_30d"].iloc[0]) if len(t) else float("nan"),
        "share_fell_after": float(t["share_fell_after"].iloc[0]) if len(t) else float("nan"),
        "note": ("adotado" if chosen is not None else "NÃO adotado (sem evidência no desenvolvimento ou revogado); x = 20% só como alerta") + "; " + hold_note,
    })
    out = pd.DataFrame(rows).astype(EXIT_RULES_SCHEMA)
    write_parquet(out, RULES_PATH)
    write_parquet(grid, GRID_PATH)
    write_parquet(base, TRADES_PATH)

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print(f"operações da referência (desenvolvimento): {len(base)} · moedas {base['symbol'].nunique()}")
    print("\n=== regras da referência (STOP -20% + TENDENCIA + MERCADO) ===")
    print(report.round(4).to_string(index=False))
    print("\n=== trailing contra a referência (diferença pareada do retorno líquido por operação) ===")
    print(grid.round(4).to_string(index=False))
    print(f"\ntrailing adotado: {chosen if chosen is not None else 'nenhum'} · {hold_note}")
    return 0


def config_param(rule: str) -> float:
    from src.transformers.exit_rules import EXIT_STOP, STOP_LOSS

    return float(STOP_LOSS) if rule == EXIT_STOP else float("nan")


if __name__ == "__main__":
    raise SystemExit(main())

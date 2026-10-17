"""Quanto a correção de continuidade (docs/data_continuity.md) descarta ou muda. Só contagens, nenhum retorno.

    uv run python research/continuity_impact.py

Compara a base original com a base segmentada: pares e quebras por motivo, segmentos criados e, por horizonte, os sinais
independentes do desenvolvimento cuja janela de retorno (entrada em t+1, saída em t+1+h) atravessava uma quebra.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.signal_evidence_study import CONTINUITY_DIR, load_candles  # noqa: E402
from src.loaders.parquet_loader import write_parquet  # noqa: E402
from src.transformers.pooled_validation import pooled_signals  # noqa: E402
from src.transformers.series_continuity import ContinuityRules, split_discontinuities  # noqa: E402
from src.transformers.signal_validation import ValidationRules, prepare  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    rules = ValidationRules()
    original = load_candles(False)
    segmented, report = split_discontinuities(original, ContinuityRules())
    print(f"pares com quebra: {report['symbol'].nunique()} · quebras: {len(report)} · "
          f"segmentos novos: {report['segment_symbol'].nunique()}")
    print(report["reason"].value_counts().to_string())
    print(report.assign(break_day=report["break_day"].dt.strftime("%Y-%m-%d")).round(6).to_string(index=False))

    old_prep, new_prep = prepare(original, rules), prepare(segmented, rules)
    rows = []
    for h in rules.horizons:
        old = pooled_signals(old_prep, h, "DESENVOLVIMENTO", rules)
        new = pooled_signals(new_prep, h, "DESENVOLVIMENTO", rules)
        breaks = report.groupby("symbol", observed=True)["break_day"].apply(list).to_dict()
        crossing = 0
        for symbol, day in zip(old["symbol"].astype(str), old["day"], strict=True):
            if any(day + pd.Timedelta(days=1) < b <= day + pd.Timedelta(days=1 + h) for b in breaks.get(symbol, [])):
                crossing += 1
        eligible = old_prep.eligible
        fwd_ok = old_prep.forward[h].notna()
        base_crossing = 0
        for symbol, days in breaks.items():
            col = (eligible[symbol] & fwd_ok[symbol]).to_numpy()
            for b in days:
                lo, hi = b - pd.Timedelta(days=1 + h), b - pd.Timedelta(days=2)
                base_crossing += int(col[(eligible.index >= lo) & (eligible.index <= hi)].sum())
        rows.append({
            "horizon": h, "baseline_windows_crossing_a_break": base_crossing, "signals_before": len(old), "signals_after": len(new), "signals_crossing_a_break": crossing,
            "coins_before": old["symbol"].nunique(), "coins_after": new["symbol"].nunique(),
            "baseline_windows_before": int((old_prep.eligible & fwd_ok).to_numpy().sum()),
            "baseline_windows_after": int((new_prep.eligible & new_prep.forward[h].notna()).to_numpy().sum()),
        })
    impact = pd.DataFrame(rows).astype("int64")
    write_parquet(impact, CONTINUITY_DIR / "continuity_impact.parquet")
    print(impact.to_string(index=False))
    np.seterr(all="ignore")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

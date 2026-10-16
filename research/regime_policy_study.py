"""Fase 5 (pesquisa): selecionar a estratégia pelo regime de mercado melhora o resultado contra alternativas fixas?

Uso (da raiz do projeto, com a base local montada pelo pipeline):

    uv run python research/regime_policy_study.py

Protocolo, hipóteses, políticas e critérios: docs/regime_policy.md (escritos ANTES da primeira execução).
O estudo só lê a base local e grava em data/research/ (nada em frontend/public/, nada no pipeline):

    experiments.parquet                      registro append-only (um registro por experimento)
    regime_policy_<id>.parquet               resultados em formato longo
    regime_policy_<id>_decisions.parquet     decisões de cada política em cada dia de rebalanceamento
    regime_policy_<id>_mappings.parquet      tabelas aprendidas por P5, ano a ano

Reexecutar com os mesmos dados e a mesma configuração reproduz o mesmo ID e o mesmo hash de resultados
("reproduzido"); se o hash divergir, o registro é recusado e nada é sobrescrito.

"Hoje" não vem do relógio: `as_of` é o fechamento do último candle da base. O relógio só é usado para carimbar a data
da execução no registro. Resultado: avaliação histórica EXPLORATÓRIA (não existe teste prospectivo).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import REGIME_SYMBOL, UNIVERSE  # noqa: E402
from src.loaders.experiment_log import NEW, REGISTRY_PATH, append_experiment  # noqa: E402
from src.loaders.market_store import read_ohlcv  # noqa: E402
from src.loaders.parquet_loader import write_parquet  # noqa: E402
from src.transformers.data_quality import clean_candles  # noqa: E402
from src.transformers.policy_evaluation import data_fingerprint, experiment_id, results_digest  # noqa: E402
from src.transformers.policy_study import FAMILY_BASELINES, POLICY_NAMES, PRIMARY_REFERENCE, Protocol, run_study  # noqa: E402
from src.transformers.regime_policy import POLICY_PRIMARY, POLICY_VERSION  # noqa: E402
from src.transformers.regimes import CLASSIFIER_VERSION, RegimeRules  # noqa: E402
from src.transformers.universe import select_universe  # noqa: E402

OUT = Path("data/research")
STATUS = "EXPLORATORIO"
LIMITATIONS = (
    "Sem teste prospectivo: toda a história já foi inspecionada em fases anteriores. Uma só história de mercado; "
    "viés de sobrevivência (moedas de hoje); spread e slippage estimados; execução no fechamento (o motor não tem "
    "D+1 na abertura); Fase 3 inexistente (bootstrap e Holm mínimos implementados aqui); janelas anuais correlacionadas."
)


def git_state() -> tuple[str, bool]:
    """HEAD e se há alterações não commitadas (para identificar o estado do código; sem Git: 'desconhecido')."""
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=True).stdout.strip())
        return head, dirty
    except (OSError, subprocess.CalledProcessError):
        return "desconhecido", True


def show(results: pd.DataFrame) -> None:
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    pd.set_option("display.max_rows", 500)
    m = results[results["section"].eq("metricas") & results["scenario"].eq("base")]
    primary = m[m["window"].eq("PRIMARIA")].pivot(index="key", columns="metric", values="value")
    cols = ["total_return_pct", "annual_return_pct", "vol_ann_pct", "sharpe", "sortino", "max_drawdown_pct", "recovery_days",
            "longest_underwater_days", "avg_exposure_pct", "days_invested_pct"]
    print("\n=== janela primária (base) ===\n" + primary[cols].round(2).to_string())
    costs = results[results["section"].eq("custos") & results["scenario"].eq("base")].pivot(index="key", columns="metric", values="value")
    trocas = results[results["section"].eq("trocas") & results["scenario"].eq("base")].set_index("key")["value"].rename("trocas")
    print("\n=== custos e giro (base, janela primária) ===\n" + costs.join(trocas).round(2).to_string())
    years = m[m["window"].str.fullmatch(r"\d{4}") & m["metric"].eq("sharpe")].pivot(index="key", columns="window", values="value")
    print("\n=== Sharpe por ano (cada ano é correlacionado com os demais) ===\n" + years.round(2).to_string())
    split = m[m["window"].isin(["VALIDACAO", "TESTE"]) & m["metric"].eq("sharpe")].pivot(index="key", columns="window", values="value")
    print("\n=== Sharpe VALIDACAO / TESTE ===\n" + split.round(2).to_string())
    comp = results[results["section"].eq("comparacao")].pivot(index="key", columns="metric", values="value")
    print("\n=== comparação pareada de Sharpe (bootstrap em blocos; família de 20; Holm) ===\n"
          + comp[["diff", "ci_low", "ci_high", "p_value", "p_holm", "n", "n_eff"]].round(3).to_string())
    rob = results[results["section"].eq("robustez")].pivot(index="key", columns="scenario", values="value")
    print(f"\n=== robustez: diferença de Sharpe contra {PRIMARY_REFERENCE} (estimativa pontual) ===\n" + rob.round(2).T.to_string())
    ric = results[results["section"].eq("robustez_ic")].pivot(index="scenario", columns="metric", values="value")
    print(f"\n=== suplementar: {POLICY_PRIMARY} vs {PRIMARY_REFERENCE} com IC em cada variante (fora da família, sem ajuste) ===\n"
          + ric[["diff", "ci_low", "ci_high", "p_value"]].round(3).to_string())
    sens = results[results["section"].eq("sensibilidade_bloco")].pivot(index="key", columns=["note", "metric"], values="value")
    print("\n=== sensibilidade ao tamanho do bloco ===\n" + sens.round(3).to_string())


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    raw = read_ohlcv(list(UNIVERSE))
    if raw.empty or REGIME_SYMBOL not in set(raw["symbol"]):
        print("base local vazia ou sem BTC: rode `uv run python -m src.pipeline` antes")
        return 1
    kept = select_universe(UNIVERSE, raw).kept
    candles = clean_candles(raw[raw["symbol"].isin(kept)])
    as_of = pd.Timestamp(candles["timestamp"].max()) + pd.Timedelta(days=1)  # fechamento do último candle da base
    protocol = Protocol()
    study = run_study(candles, as_of, protocol)

    fingerprint = data_fingerprint(candles)
    exp_id = experiment_id({**study.config, "universe": sorted(str(s) for s in kept), "as_of": str(as_of)}, fingerprint)
    digest = results_digest(study.results)
    results_file = OUT / f"regime_policy_{exp_id}.parquet"
    head, dirty = git_state()
    record: dict[str, object] = {
        "experiment_id": exp_id, "created_at": pd.Timestamp.now(tz="UTC"), "code_version": head, "working_tree_dirty": dirty,
        "data_fingerprint": fingerprint, "classifier_version": CLASSIFIER_VERSION,
        "classifier_params_hash": RegimeRules().fingerprint(), "policy_version": POLICY_VERSION,
        "universe": ",".join(sorted(str(s) for s in kept)), "period_start": study.period[0], "period_end": study.period[1],
        "seed": protocol.seed, "bootstrap_block": protocol.block, "bootstrap_resamples": protocol.resamples,
        "n_policies": study.n_policies, "n_variants": study.n_variants, "n_hypotheses": study.n_hypotheses,
        "config_json": pd.Series([study.config]).astype(str).iloc[0], "results_digest": digest,
        "results_file": str(results_file), "status": STATUS, "limitations": LIMITATIONS,
    }
    outcome = append_experiment(record, REGISTRY_PATH)
    if outcome == NEW or not results_file.exists():
        for path, frame in ((results_file, study.results),
                            (OUT / f"regime_policy_{exp_id}_decisions.parquet", study.decisions),
                            (OUT / f"regime_policy_{exp_id}_mappings.parquet", study.mappings)):
            if not path.exists():  # nunca sobrescreve
                write_parquet(frame, path)

    print(f"experimento {exp_id} ({outcome}) · dados {fingerprint[:12]} · código {head[:10]}{' (árvore com alterações)' if dirty else ''}")
    print(f"período {study.period[0]:%Y-%m-%d} a {study.period[1]:%Y-%m-%d} · {study.n_policies} políticas · "
          f"{study.n_variants} variantes · {study.n_hypotheses} hipóteses · semente {protocol.seed} · status {STATUS}")
    show(study.results)
    print(f"\nresultados: {results_file} ({len(study.results)} linhas) · hash {digest}")
    print(f"família: {len(POLICY_NAMES)} políticas × {len(FAMILY_BASELINES)} baselines · primária: {POLICY_PRIMARY} vs {PRIMARY_REFERENCE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Universo point-in-time: quais pares eram elegíveis em cada dia, usando só o que se sabia até aquele dia.

Puro (CLAUDE.md §1) e vetorizado. Substitui, para pesquisa e backtest, o filtro de `universe.select_universe`, que
decide com o volume e o histórico de HOJE e aplica o resultado a todo o passado (seleção retroativa). Aqui:

    - a decisão do dia D é tomada depois do fechamento do candle de D (00:00 UTC de D+1) e usa só candles com
      timestamp <= D: truncar os dados depois de D não muda o universo de D (testado);
    - candidatas = todos os pares presentes nos candles (no arquivo da Binance, vivos e deslistados), não a lista
      de moedas que existem hoje;
    - volume médio e histórico são medidos até D; o limite de tamanho escolhe as de maior volume EM D (não a
      ordem de market cap atual do config);
    - uma lacuna maior que `episode_gap_days` encerra o episódio de negociação: o que voltar depois é outro ativo
      (histórico zerado). Ex.: LUNAUSDT (Terra antiga até maio de 2022, Terra 2.0 depois);
    - um par sem candle há mais de `max_stale_days` não é negociável naquele dia (suspenso ou deslistado).

Ordem dos motivos (o primeiro que se aplica): EXCLUIDA, ALAVANCADA, SEM_NEGOCIACAO, ELEGIVEL, HISTORICO_CURTO,
VOLUME_BAIXO; senão FORA_DO_LIMITE. As moedas `always_include` (config.RECOMMENDED) seguem a regra do universo ao
vivo: nunca saem por histórico, volume ou limite.

Limites que este módulo NÃO resolve (documentados em docs/QUANT_ROADMAP_PROGRESS.md): só enxerga o que a Binance
listou (moedas nunca listadas nela não entram); o fim de uma série é "sem candles depois de X", não o anúncio
oficial de deslistagem; renomeações (MATIC -> POL) aparecem como saída de um par e entrada de outro.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .. import config

REASON_ELIGIBLE = "ELEGIVEL"
REASON_EXCLUDED = "EXCLUIDA"
REASON_LEVERAGED = "ALAVANCADA"
REASON_NOT_TRADING = "SEM_NEGOCIACAO"
REASON_SHORT_HISTORY = "HISTORICO_CURTO"
REASON_LOW_VOLUME = "VOLUME_BAIXO"
REASON_OUTSIDE_LIMIT = "FORA_DO_LIMITE"

EVENT_FIRST = "PRIMEIRO_CANDLE"
EVENT_GAP = "LACUNA"              # fim de episódio seguido de retomada (suspensão ou troca de ativo)
EVENT_LAST = "ULTIMO_CANDLE"      # sem candles depois disto até `as_of` (deslistagem INFERIDA, não anunciada)

UNIVERSE_HISTORY_SCHEMA: dict[str, str] = {
    "timestamp": "datetime64[ns, UTC]",  # dia D (decisão após o fechamento do candle de D)
    "symbol": "string",
    "episode": "Int64",                  # episódio de negociação do par (0, 1, ...)
    "eligible": "bool",
    "reason": "string",
    "history_days": "Int64",             # candles do episódio até D
    "days_since_candle": "Int64",        # 0 = há candle em D
    "avg_volume_usd": "float64",         # volume médio (quote) da janela terminada em D
    "volume_rank": "Int64",              # posição por volume em D entre as que passam nos demais filtros
}

EVENT_SCHEMA: dict[str, str] = {
    "symbol": "string",
    "episode": "Int64",
    "event": "string",
    "timestamp": "datetime64[ns, UTC]",
    "inferred": "bool",                  # True: deduzido da série, sem anúncio oficial
    "evidence": "string",
}


@dataclass(frozen=True)
class PointInTimeRules:
    min_history_days: int = config.MIN_HISTORY_DAYS
    min_avg_volume_usd: float = config.MIN_AVG_QUOTE_VOLUME_USD
    volume_window_days: int = config.VOLUME_WINDOW_DAYS
    max_stale_days: int = config.MAX_STALE_DAYS
    episode_gap_days: int = config.EPISODE_GAP_DAYS
    max_size: int = config.MAX_UNIVERSE_SIZE
    always_include: tuple[str, ...] = config.RECOMMENDED
    excluded: Mapping[str, str] = field(default_factory=lambda: {**config.EXCLUDED_BASES, **config.NON_CRYPTO_BASES})
    leveraged_suffixes: tuple[str, ...] = config.LEVERAGED_SUFFIXES

    def __post_init__(self) -> None:
        if self.min_history_days < 1 or self.volume_window_days < 1 or self.max_size < 1:
            raise ValueError("min_history_days, volume_window_days e max_size precisam ser >= 1")
        if self.max_stale_days < 0 or self.episode_gap_days <= self.max_stale_days:
            raise ValueError("precisa 0 <= max_stale_days < episode_gap_days")


def _base(symbol: str) -> str:
    return symbol.split("/", 1)[0].upper()


def _daily(candles: pd.DataFrame) -> pd.DataFrame:
    """symbol, timestamp (meia-noite UTC), quote_volume, um candle por par e dia, só preço válido."""
    c = candles[["symbol", "timestamp", "close", "quote_volume"]].copy()
    c["symbol"] = c["symbol"].astype("string")
    c["timestamp"] = c["timestamp"].dt.floor("D")
    ok = pd.to_numeric(c["close"], errors="coerce")
    c = c[np.isfinite(ok.to_numpy(dtype="float64")) & ok.gt(0)]
    return c.drop_duplicates(["symbol", "timestamp"], keep="last").sort_values(["symbol", "timestamp"], ignore_index=True)


def assign_episodes(candles: pd.DataFrame, gap_days: int = config.EPISODE_GAP_DAYS) -> pd.DataFrame:
    """Acrescenta `episode` (0, 1, ...) por par: um novo começa depois de mais de `gap_days` dias sem candle.
    Causal: o episódio de um candle só depende dos candles anteriores do mesmo par."""
    c = candles.sort_values(["symbol", "timestamp"], ignore_index=True)
    gap = c.groupby("symbol", observed=True, sort=False)["timestamp"].diff().dt.days
    return c.assign(episode=gap.gt(gap_days).astype("int64").groupby(c["symbol"], observed=True).cumsum().astype("Int64"))


def _flags(symbols: list[str], rules: PointInTimeRules) -> tuple[pd.Series, pd.Series]:
    """(excluída, alavancada) por par. Alavancado = base de outro par + sufixo (ex.: BTCUP, ETHBEAR)."""
    bases = {_base(s) for s in symbols}
    excluded = pd.Series([_base(s) in rules.excluded for s in symbols], index=symbols, dtype="bool")
    leveraged = pd.Series(
        [any(_base(s).endswith(sfx) and _base(s)[: -len(sfx)] in bases for sfx in rules.leveraged_suffixes) for s in symbols],
        index=symbols,
        dtype="bool",
    )
    return excluded, leveraged


def universe_history(candles: pd.DataFrame, rules: PointInTimeRules = PointInTimeRules()) -> pd.DataFrame:
    """Elegibilidade de cada par em cada dia desde o seu primeiro candle (UNIVERSE_HISTORY_SCHEMA)."""
    c = _daily(candles)
    if c.empty:
        return pd.DataFrame({k: pd.Series(dtype=t) for k, t in UNIVERSE_HISTORY_SCHEMA.items()})
    c = assign_episodes(c, rules.episode_gap_days)
    c["history_days"] = c.groupby(["symbol", "episode"], observed=True).cumcount() + 1
    days = pd.date_range(c["timestamp"].min(), c["timestamp"].max(), freq="D")
    symbols = sorted(c["symbol"].unique().tolist())

    def wide(col: str) -> pd.DataFrame:
        return c.pivot(index="timestamp", columns="symbol", values=col).reindex(index=days, columns=symbols)

    origin = c["timestamp"].min()
    c["day_num"] = (c["timestamp"] - origin).dt.days.astype("float64")
    seen = wide("day_num")
    has = seen.notna()
    last_seen = seen.ffill()
    day_num = (days - origin).days.to_numpy(dtype="float64")
    days_since = pd.DataFrame(day_num[:, None] - last_seen.to_numpy(dtype="float64"), index=days, columns=symbols)
    episode = wide("episode").astype("float64").ffill()
    history = wide("history_days").astype("float64").ffill()
    volume = wide("quote_volume").astype("float64").where(has)
    min_periods = max(1, math.ceil(rules.volume_window_days * 2 / 3))
    avg_volume = volume.rolling(rules.volume_window_days, min_periods=min_periods).mean()

    listed = last_seen.notna()
    excluded, leveraged = _flags(symbols, rules)
    exc = pd.DataFrame(np.broadcast_to(excluded.to_numpy(), has.shape), index=days, columns=symbols)
    lev = pd.DataFrame(np.broadcast_to(leveraged.to_numpy(), has.shape), index=days, columns=symbols)
    not_trading = days_since.gt(rules.max_stale_days)
    short = history.lt(rules.min_history_days)
    low_volume = ~avg_volume.ge(rules.min_avg_volume_usd)  # NaN (janela incompleta) conta como baixo
    passing = listed & ~exc & ~lev & ~not_trading & ~short & ~low_volume

    forced = pd.Series([s in set(rules.always_include) for s in symbols], index=symbols, dtype="bool")
    # Mesma regra do universo ao vivo (`universe.select_universe`): as moedas-núcleo nunca saem por histórico,
    # volume ou limite; só por exclusão, alavancagem ou falta de negociação. A estratégia ainda exige seus próprios
    # dados (ex.: SMA 200) antes de comprar.
    forced_ok = (listed & ~exc & ~lev & ~not_trading) & forced.to_numpy()
    extra = passing & ~forced.to_numpy()
    rank = avg_volume.where(extra).rank(axis=1, ascending=False, method="first")
    slots = max(rules.max_size - len(rules.always_include), 0)
    eligible = forced_ok | (extra & rank.le(slots))

    reason = np.select(
        [exc.to_numpy(), lev.to_numpy(), not_trading.to_numpy(), eligible.to_numpy(), short.to_numpy(),
         low_volume.to_numpy()],
        [REASON_EXCLUDED, REASON_LEVERAGED, REASON_NOT_TRADING, REASON_ELIGIBLE, REASON_SHORT_HISTORY,
         REASON_LOW_VOLUME],
        REASON_OUTSIDE_LIMIT,
    )
    panel = {
        "episode": episode,
        "eligible": eligible.astype(float),
        "reason": pd.DataFrame(reason, index=days, columns=symbols),
        "history_days": history,
        "days_since_candle": days_since,
        "avg_volume_usd": avg_volume,
        "volume_rank": avg_volume.where(passing).rank(axis=1, ascending=False, method="first"),
        "_listed": listed.astype(float),
    }
    long = pd.concat(panel, axis=1).stack(level=1, future_stack=True)
    long.index = long.index.set_names(["timestamp", "symbol"])
    long = long[long["_listed"].astype(float).gt(0)].drop(columns="_listed").reset_index()
    long["eligible"] = long["eligible"].astype(float).gt(0)
    return long[list(UNIVERSE_HISTORY_SCHEMA)].astype(UNIVERSE_HISTORY_SCHEMA)


def universe_on(history: pd.DataFrame, day: pd.Timestamp) -> tuple[str, ...]:
    """Pares elegíveis no dia `day` (de `universe_history`), em ordem alfabética."""
    d = (day if day.tzinfo else day.tz_localize("UTC")).floor("D")
    rows = history[history["timestamp"].eq(d) & history["eligible"]]
    return tuple(sorted(rows["symbol"].astype(str)))


def listing_events(candles: pd.DataFrame, as_of: pd.Timestamp, rules: PointInTimeRules = PointInTimeRules()) -> pd.DataFrame:
    """Registro de inclusão e exclusão observado nos candles (EVENT_SCHEMA): primeiro candle de cada episódio,
    lacunas que encerraram episódios e o último candle de pares sem negociação em `as_of`.

    Tudo é INFERIDO da série (`inferred=True`): o arquivo da Binance não traz o anúncio de deslistagem. Um anúncio
    oficial verificado pode ser acrescentado depois como evento com `inferred=False` (ver `merge_events`)."""
    c = _daily(candles)
    if c.empty:
        return pd.DataFrame({k: pd.Series(dtype=t) for k, t in EVENT_SCHEMA.items()})
    c = assign_episodes(c, rules.episode_gap_days)
    g = c.groupby(["symbol", "episode"], observed=True)["timestamp"]
    spans = pd.DataFrame({"first": g.min(), "last": g.max()}).reset_index()
    spans["newest"] = spans.groupby("symbol", observed=True)["episode"].transform("max")
    cutoff = (as_of if as_of.tzinfo else as_of.tz_localize("UTC")).floor("D") - pd.Timedelta(days=1 + rules.max_stale_days)

    rows: list[dict[str, object]] = []
    for rec in spans.to_dict("records"):
        symbol, episode = str(rec["symbol"]), int(rec["episode"])
        first, last = pd.Timestamp(rec["first"]), pd.Timestamp(rec["last"])
        rows.append({"symbol": symbol, "episode": episode, "event": EVENT_FIRST, "timestamp": first,
                     "inferred": True, "evidence": "primeiro candle diário do episódio no arquivo da Binance"})
        if episode < int(rec["newest"]):
            rows.append({"symbol": symbol, "episode": episode, "event": EVENT_GAP, "timestamp": last,
                         "inferred": True,
                         "evidence": f"mais de {rules.episode_gap_days} dias sem candle depois deste dia; a série voltou depois"})
        elif last < cutoff:
            rows.append({"symbol": symbol, "episode": episode, "event": EVENT_LAST, "timestamp": last,
                         "inferred": True,
                         "evidence": f"sem candles depois deste dia até {cutoff + pd.Timedelta(days=1 + rules.max_stale_days):%Y-%m-%d}"})
    out = pd.DataFrame(rows)
    return out[list(EVENT_SCHEMA)].astype(EVENT_SCHEMA).sort_values(["symbol", "timestamp", "event"], ignore_index=True)


def merge_events(inferred: pd.DataFrame, official: pd.DataFrame) -> pd.DataFrame:
    """Junta eventos inferidos da série com eventos oficiais verificados (`inferred=False`, com a fonte em
    `evidence`). Nenhum é descartado: a divergência entre os dois fica visível."""
    frames = [f[list(EVENT_SCHEMA)].astype(EVENT_SCHEMA) for f in (inferred, official) if not f.empty]
    if not frames:
        return pd.DataFrame({k: pd.Series(dtype=t) for k, t in EVENT_SCHEMA.items()})
    return pd.concat(frames, ignore_index=True).sort_values(["symbol", "timestamp", "event"], ignore_index=True)


TOKENIZED_EQUITY_SINCE = "2025-01"
"""Ações tokenizadas apareceram no spot da Binance só em 2025 (ex.: AAPLB, TSLAB, SPYB)."""


def review_flags(catalog: pd.DataFrame, rules: PointInTimeRules = PointInTimeRules()) -> pd.DataFrame:
    """Pares que pedem revisão humana antes de entrar em qualquer conclusão, SEM excluí-los do universo:
    possível ação tokenizada (base de 3+ letras terminada em B, primeiro arquivo a partir de 2025-01). É uma
    heurística sobre o nome: erra para os dois lados e por isso só sinaliza."""
    rows: list[dict[str, str]] = []
    for symbol, first in zip(catalog["symbol"].astype(str), catalog["first_month"].astype(str), strict=True):
        base = _base(symbol)
        if base in rules.excluded:
            continue
        if len(base) >= 4 and base.endswith("B") and base[:-1].isalpha() and first >= TOKENIZED_EQUITY_SINCE:
            rows.append({"symbol": symbol, "flag": "POSSIVEL_ACAO_TOKENIZADA",
                         "detail": f"base terminada em B, listada em {first}; confira antes de tratar como cripto"})
    return pd.DataFrame(rows, columns=["symbol", "flag", "detail"]).astype("string")


def survivorship_summary(history: pd.DataFrame, current_universe: Collection[str], ended: Collection[str]) -> pd.DataFrame:
    """Por ano: quantos pares foram elegíveis em média por dia, quantos destes estão na lista de moedas de HOJE
    (config.UNIVERSE) e quantos deixaram de negociar depois. Mede o tamanho do viés que a lista atual causaria."""
    h = history[history["eligible"]]
    if h.empty:
        return pd.DataFrame(columns=["year", "eligible_per_day", "distinct_eligible", "in_current_universe", "later_ended"])
    cur, gone = set(current_universe), set(ended)
    by_year: dict[int, set[str]] = {}
    for ts, sym in zip(h["timestamp"], h["symbol"].astype(str), strict=True):
        by_year.setdefault(pd.Timestamp(ts).year, set()).add(sym)
    per_day = h.groupby("timestamp").size()
    per_day_year = pd.Series(per_day.to_numpy(), index=pd.DatetimeIndex(per_day.index).year)
    mean_per_day = per_day_year.groupby(level=0).mean()
    years = sorted(by_year)
    out = pd.DataFrame(
        {
            "year": years,
            "eligible_per_day": [float(mean_per_day.loc[y]) for y in years],
            "distinct_eligible": [len(by_year[y]) for y in years],
            "in_current_universe": [len(by_year[y] & cur) for y in years],
            "later_ended": [len(by_year[y] & gone) for y in years],
        }
    )
    return out.reset_index(drop=True)

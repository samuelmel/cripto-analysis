"""Adaptador do arquivo público oficial da Binance (data.binance.vision): klines spot diários em ZIP com SHA-256.

Por que existe: a REST (`binance_adapter.py`) só serve pares que ainda negociam. O arquivo guarda também os pares
que já foram deslistados (LUNA, FTT, UST, ...), então é a fonte verificável para montar o universo histórico sem
inventar dados. O conteúdo é o mesmo kline da Binance (mesmo fornecedor, `source = "binance"`); a origem de cada
arquivo (chave, ETag, SHA-256, quando foi baixado) vai para o manifesto (`manifest_frame`).

Estrutura do arquivo (bucket S3 `data.binance.vision`):
    data/spot/monthly/klines/<SYMBOL>/1d/<SYMBOL>-1d-YYYY-MM.zip      (+ .CHECKSUM)   meses fechados
    data/spot/daily/klines/<SYMBOL>/1d/<SYMBOL>-1d-YYYY-MM-DD.zip     (+ .CHECKSUM)   dias do mês corrente
A listagem (XML do S3) só existe no endpoint do bucket; os arquivos podem vir dele ou do CDN data.binance.vision.

Garantias:
    - todo ZIP é conferido contra o .CHECKSUM publicado; sem checksum ou com divergência = ExtractorError (nunca
      grava dado não verificado);
    - só entram candles fechados até `end` (o candle do dia D fecha às 00:00 UTC de D+1);
    - `known` (chave -> ETag já ingerido) evita baixar de novo o que não mudou; ETag diferente = arquivo revisado
      na fonte, que é baixado de novo (a revisão fica registrada pelo loader);
    - nada aqui deduz deslistagem: o arquivo não traz anúncio oficial. O fim da série é só "sem candles depois de X".

`fetch`, `list_symbols` e `list_keys` fazem I/O; `to_frame`, `manifest_frame`, `parse_keys` e `catalog_frame`
são puros.
"""

from __future__ import annotations

import hashlib
import io
import re
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import ClassVar

import pandas as pd

from .base_extractor import BaseExtractor, ExtractorError
from .binance_adapter import BinanceAdapter
from .http import get_bytes

LISTING_HOST = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
CDN_HOST = "https://data.binance.vision"
ALLOWED_HOSTS = (LISTING_HOST, CDN_HOST)
"""O endpoint do bucket responde a listagem e aos downloads; o CDN só aos downloads. Só estes hosts são aceitos."""

MONTHLY_PREFIX = "data/spot/monthly/klines/"
DAILY_PREFIX = "data/spot/daily/klines/"
INTERVAL = "1d"
DEFAULT_WORKERS = 8
TIMEOUT = 60.0
_S3_NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
_KEY_RE = re.compile(r"^data/spot/(monthly|daily)/klines/([A-Z0-9]+)/1d/\2-1d-(\d{4}-\d{2}(?:-\d{2})?)\.zip$")
_CSV_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_volume", "trades", "taker_buy_base_volume", "taker_buy_quote_volume", "ignore",
]

MANIFEST_SCHEMA: dict[str, str] = {
    "symbol": "string",
    "key": "string",               # caminho do ZIP no arquivo
    "kind": "string",              # monthly / daily
    "period": "string",            # YYYY-MM ou YYYY-MM-DD
    "etag": "string",              # ETag do S3 (muda se a Binance republicar o arquivo)
    "last_modified": "datetime64[ns, UTC]",
    "size": "int64",
    "sha256": "string",            # conferido contra o .CHECKSUM publicado
    "rows": "int64",               # candles fechados aproveitados do arquivo
    "first_ts": "datetime64[ns, UTC]",
    "last_ts": "datetime64[ns, UTC]",
}

CATALOG_SCHEMA: dict[str, str] = {
    "symbol": "string",            # BASE/QUOTE (ex.: LUNA/USDT)
    "archive_symbol": "string",    # como no arquivo (ex.: LUNAUSDT)
    "first_month": "string",       # primeiro mês com arquivo mensal (YYYY-MM)
    "last_month": "string",        # último mês com arquivo mensal
    "months": "int64",             # meses com arquivo
    "missing_months": "int64",     # meses sem arquivo entre o primeiro e o último (suspensão, troca de ativo)
    "last_daily": "string",        # último arquivo diário (YYYY-MM-DD), vazio se não há
}


@dataclass(frozen=True)
class ArchiveKey:
    """Um ZIP listado no arquivo (sem o conteúdo)."""

    key: str
    etag: str
    last_modified: str
    size: int


@dataclass(frozen=True)
class ArchiveFile:
    """Um ZIP baixado e verificado."""

    symbol: str          # BASE/QUOTE
    key: ArchiveKey
    sha256: str
    content: bytes


def archive_symbol(symbol: str) -> str:
    """'LUNA/USDT' -> 'LUNAUSDT'."""
    return symbol.replace("/", "").upper()


def pair_symbol(archive_name: str, quote: str) -> str:
    """'LUNAUSDT' -> 'LUNA/USDT' (exige que termine com `quote`)."""
    if not archive_name.endswith(quote) or len(archive_name) == len(quote):
        raise ValueError(f"{archive_name} não é um par em {quote}")
    return f"{archive_name[: -len(quote)]}/{quote}"


# ---------------------------------------------------------------------------------------------
# Puros: chaves, catálogo, parse dos ZIPs e manifesto
# ---------------------------------------------------------------------------------------------

def parse_listing(xml: bytes) -> tuple[list[ArchiveKey], list[str], str | None]:
    """XML de uma página da listagem do S3 -> (arquivos, prefixos comuns, marcador da próxima página ou None)."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ExtractorError("arquivo Binance: listagem não é XML válido") from exc
    keys = [
        ArchiveKey(
            key=c.findtext("s3:Key", "", _S3_NS),
            etag=c.findtext("s3:ETag", "", _S3_NS).strip('"'),
            last_modified=c.findtext("s3:LastModified", "", _S3_NS),
            size=int(c.findtext("s3:Size", "0", _S3_NS)),
        )
        for c in root.findall("s3:Contents", _S3_NS)
    ]
    prefixes = [p.findtext("s3:Prefix", "", _S3_NS) for p in root.findall("s3:CommonPrefixes", _S3_NS)]
    truncated = root.findtext("s3:IsTruncated", "false", _S3_NS) == "true"
    if not truncated:
        return keys, prefixes, None
    marker = root.findtext("s3:NextMarker", None, _S3_NS) or (keys[-1].key if keys else (prefixes[-1] if prefixes else None))
    if marker is None:
        raise ExtractorError("arquivo Binance: listagem truncada sem marcador de continuação")
    return keys, prefixes, marker


def zip_keys(keys: Iterable[ArchiveKey]) -> list[tuple[ArchiveKey, str, str]]:
    """Só os ZIPs de klines 1d: (chave, kind, período). Ignora .CHECKSUM e qualquer outro arquivo."""
    out: list[tuple[ArchiveKey, str, str]] = []
    for k in keys:
        m = _KEY_RE.match(k.key)
        if m:
            out.append((k, m.group(1), m.group(3)))
    return out


def plan_files(
    keys: Sequence[ArchiveKey], start: datetime | None, end: datetime, known: Mapping[str, str]
) -> list[ArchiveKey]:
    """Quais ZIPs baixar para cobrir [start, end): mensais dos meses fechados e diários só dos meses que ainda não
    têm arquivo mensal. Pula o que já foi ingerido com o mesmo ETag (`known`)."""
    parsed = zip_keys(keys)
    monthly = {period for _, kind, period in parsed if kind == "monthly"}
    first = None if start is None else start.astimezone(timezone.utc)
    last = end.astimezone(timezone.utc)
    chosen: list[ArchiveKey] = []
    for key, kind, period in parsed:
        if kind == "monthly":
            begin = datetime.strptime(period, "%Y-%m").replace(tzinfo=timezone.utc)
            finish = (begin + timedelta(days=32)).replace(day=1)
        else:
            if period[:7] in monthly:
                continue  # o mensal já cobre o dia
            begin = datetime.strptime(period, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            finish = begin + timedelta(days=1)
        if begin >= last or (first is not None and finish <= first):
            continue
        if known.get(key.key) == key.etag:
            continue
        chosen.append(key)
    return chosen


def catalog_frame(listings: Mapping[str, Sequence[ArchiveKey]], quote: str) -> pd.DataFrame:
    """Um registro por par: meses com arquivo, primeiro e último, lacunas e último diário (CATALOG_SCHEMA).
    `listings`: nome no arquivo (ex.: LUNAUSDT) -> chaves listadas (mensais e diárias)."""
    rows: list[dict[str, object]] = []
    for name, keys in sorted(listings.items()):
        parsed = zip_keys(keys)
        months = sorted({p for _, kind, p in parsed if kind == "monthly"})
        days = sorted(p for _, kind, p in parsed if kind == "daily")
        if not months and not days:
            continue
        span = 0
        if months:
            a, b = pd.Period(months[0], "M"), pd.Period(months[-1], "M")
            span = (b - a).n + 1
        rows.append(
            {
                "symbol": pair_symbol(name, quote),
                "archive_symbol": name,
                "first_month": months[0] if months else "",
                "last_month": months[-1] if months else "",
                "months": len(months),
                "missing_months": span - len(months),
                "last_daily": days[-1] if days else "",
            }
        )
    if not rows:
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in CATALOG_SCHEMA.items()})
    return pd.DataFrame(rows)[list(CATALOG_SCHEMA)].astype(CATALOG_SCHEMA)


def _verify(name: str, content: bytes, checksum: bytes | None) -> str:
    """SHA-256 do ZIP conferido contra o .CHECKSUM publicado ('<hex>  <arquivo>')."""
    if checksum is None:
        raise ExtractorError(f"arquivo Binance: {name} sem .CHECKSUM publicado; não gravamos dado não verificado")
    parts = checksum.decode("utf-8", errors="replace").split()
    digest = hashlib.sha256(content).hexdigest()
    if not parts or parts[0].lower() != digest:
        raise ExtractorError(f"arquivo Binance: checksum inválido em {name}")
    return digest


def parse_zip(content: bytes) -> pd.DataFrame:
    """ZIP de klines (CSV com ou sem cabeçalho) -> timestamp, open, high, low, close, volume, quote_volume, trades."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = zf.namelist()
            if len(names) != 1:
                raise ExtractorError(f"arquivo Binance: ZIP com {len(names)} arquivos (esperado 1)")
            raw = zf.read(names[0])
    except zipfile.BadZipFile as exc:
        raise ExtractorError("arquivo Binance: ZIP corrompido") from exc
    if not raw.strip():
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "quote_volume", "trades"])
    has_header = not raw.split(b",", 1)[0].strip().isdigit()
    df = pd.read_csv(io.BytesIO(raw), header=0 if has_header else None)
    if df.shape[1] != len(_CSV_COLUMNS):
        raise ExtractorError(f"arquivo Binance: {df.shape[1]} colunas no CSV (esperado {len(_CSV_COLUMNS)})")
    df.columns = pd.Index(_CSV_COLUMNS)
    ts = pd.to_numeric(df["open_time"], errors="coerce").astype("Int64")
    if ts.isna().any():
        raise ExtractorError("arquivo Binance: open_time inválido no CSV")
    ts = ts.where(ts < 10**14, ts // 1000)  # desde 2025-01-01 o spot vem em microssegundos
    numeric = ["open", "high", "low", "close", "volume", "quote_volume"]
    out = pd.DataFrame({c: pd.to_numeric(df[c], errors="coerce") for c in numeric})
    out.insert(0, "timestamp", pd.to_datetime(ts.astype("int64"), unit="ms", utc=True))
    out["trades"] = pd.to_numeric(df["trades"], errors="coerce").astype("Int64")
    return out


def _closed(frame: pd.DataFrame, end: datetime) -> pd.DataFrame:
    """Só candles diários já fechados em `end` (abre em D, fecha em D+1 00:00 UTC)."""
    limit = pd.Timestamp(end).tz_convert("UTC") if pd.Timestamp(end).tzinfo else pd.Timestamp(end, tz="UTC")
    return frame[frame["timestamp"] + pd.Timedelta(days=1) <= limit]


# ---------------------------------------------------------------------------------------------
# Adaptador
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class ArchivePayload:
    files: tuple[ArchiveFile, ...]
    end: datetime


class BinanceArchiveAdapter(BaseExtractor):
    source: ClassVar[str] = BinanceAdapter.source
    value_columns: ClassVar[dict[str, str]] = dict(BinanceAdapter.value_columns)

    def __init__(
        self,
        symbols: list[str],
        *,
        quote: str = "USDT",
        host: str = LISTING_HOST,
        known: Mapping[str, str] | None = None,
        workers: int = DEFAULT_WORKERS,
        listings: Mapping[str, Sequence[ArchiveKey]] | None = None,
    ) -> None:
        if host not in ALLOWED_HOSTS:
            raise ValueError(f"host do arquivo Binance não suportado: {host} (aceitos: {', '.join(ALLOWED_HOSTS)})")
        if workers < 1:
            raise ValueError("workers precisa ser >= 1")
        for s in symbols:
            if not s.endswith(f"/{quote}"):
                raise ValueError(f"{s}: o adaptador do arquivo só aceita pares em {quote}")
        self.symbols = symbols
        self.quote = quote
        self.host = host
        self.known = dict(known or {})
        self.workers = workers
        self.listings = dict(listings or {})  # nome no arquivo -> chaves já listadas (evita listar de novo)

    # ---- I/O ----------------------------------------------------------------------------------

    @staticmethod
    def list_page(prefix: str, marker: str = "") -> bytes:
        query: dict[str, str | int] = {"prefix": prefix, "delimiter": "/"}
        if marker:
            query["marker"] = marker
        body = get_bytes(LISTING_HOST, query, timeout=TIMEOUT)
        if body is None:
            raise ExtractorError("arquivo Binance: listagem vazia")
        return body

    @classmethod
    def list_all(cls, prefix: str, start_after: str = "") -> tuple[list[ArchiveKey], list[str]]:
        keys: list[ArchiveKey] = []
        prefixes: list[str] = []
        marker = start_after
        while True:
            page_keys, page_prefixes, nxt = parse_listing(cls.list_page(prefix, marker))
            keys += page_keys
            prefixes += page_prefixes
            if nxt is None:
                return keys, prefixes
            marker = nxt

    @classmethod
    def list_symbols(cls, quote: str = "USDT") -> list[str]:
        """Todos os pares (nome do arquivo, ex.: LUNAUSDT) com klines mensais e cotação `quote`, vivos ou não."""
        _, prefixes = cls.list_all(MONTHLY_PREFIX)
        names = [p[len(MONTHLY_PREFIX):].rstrip("/") for p in prefixes]
        return sorted(n for n in names if n.endswith(quote) and len(n) > len(quote))

    @classmethod
    def list_keys(cls, name: str) -> list[ArchiveKey]:
        """ZIPs (e checksums) 1d mensais e diários de um par. Os diários só são listados a partir do mês seguinte ao
        último mensal (os anteriores já estão cobertos e seriam descartados por `plan_files`): uma página em vez de
        várias para pares que negociam há anos."""
        monthly, _ = cls.list_all(f"{MONTHLY_PREFIX}{name}/{INTERVAL}/")
        months = sorted(p for _, kind, p in zip_keys(monthly) if kind == "monthly")
        daily_prefix = f"{DAILY_PREFIX}{name}/{INTERVAL}/"
        after = f"{daily_prefix}{name}-{INTERVAL}-{months[-1]}-99" if months else ""  # depois do último dia do mês
        daily, _ = cls.list_all(daily_prefix, start_after=after)
        return monthly + daily

    def _download(self, symbol: str, key: ArchiveKey) -> ArchiveFile:
        url = f"{self.host}/{urllib.parse.quote(key.key)}"
        content = get_bytes(url, timeout=TIMEOUT)
        if content is None:
            raise ExtractorError(f"arquivo Binance: {key.key} sumiu entre a listagem e o download")
        checksum = get_bytes(url + ".CHECKSUM", timeout=TIMEOUT, missing_ok=True)
        return ArchiveFile(symbol, key, _verify(key.key, content, checksum), content)

    def fetch(self, start: datetime | None, end: datetime) -> ArchivePayload:
        jobs: list[tuple[str, ArchiveKey]] = []
        for symbol in self.symbols:
            name = archive_symbol(symbol)
            keys = list(self.listings[name]) if name in self.listings else self.list_keys(name)
            jobs += [(symbol, k) for k in plan_files(keys, start, end, self.known)]
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            files = list(pool.map(lambda job: self._download(*job), jobs))
        return ArchivePayload(tuple(files), end)

    # ---- puros --------------------------------------------------------------------------------

    def to_frame(self, raw: ArchivePayload) -> pd.DataFrame:
        frames = [
            _closed(parse_zip(f.content), raw.end).assign(symbol=f.symbol, archive_key=f.key.key)
            for f in raw.files
        ]
        frames = [f for f in frames if not f.empty]
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    @staticmethod
    def manifest_frame(raw: ArchivePayload, frame: pd.DataFrame) -> pd.DataFrame:
        """Origem de cada ZIP baixado (MANIFEST_SCHEMA), inclusive dos que não trouxeram candle fechado."""
        counts: dict[str, int] = {}
        first: dict[str, pd.Timestamp] = {}
        last: dict[str, pd.Timestamp] = {}
        if not frame.empty:
            ts = frame.groupby("archive_key")["timestamp"]
            counts = {str(k): int(v) for k, v in ts.size().items()}
            first = {str(k): pd.Timestamp(v) for k, v in ts.min().items()}
            last = {str(k): pd.Timestamp(v) for k, v in ts.max().items()}
        rows: list[dict[str, object]] = []
        for f in raw.files:
            m = _KEY_RE.match(f.key.key)
            rows.append(
                {
                    "symbol": f.symbol,
                    "key": f.key.key,
                    "kind": m.group(1) if m else "",
                    "period": m.group(3) if m else "",
                    "etag": f.key.etag,
                    "last_modified": pd.Timestamp(f.key.last_modified) if f.key.last_modified else pd.NaT,
                    "size": f.key.size,
                    "sha256": f.sha256,
                    "rows": counts.get(f.key.key, 0),
                    "first_ts": first.get(f.key.key, pd.NaT),
                    "last_ts": last.get(f.key.key, pd.NaT),
                }
            )
        if not rows:
            return pd.DataFrame({c: pd.Series(dtype=t) for c, t in MANIFEST_SCHEMA.items()})
        return pd.DataFrame(rows)[list(MANIFEST_SCHEMA)].astype(MANIFEST_SCHEMA)

    def extract_with_manifest(self, start: datetime | None, end: datetime) -> tuple[pd.DataFrame, pd.DataFrame]:
        """(candles padronizados, manifesto dos ZIPs usados)."""
        raw = self.fetch(start, end)
        frame = self.to_frame(raw)
        return self.standardize(frame), self.manifest_frame(raw, frame)

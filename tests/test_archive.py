"""Arquivo da Binance (sem rede): listagem, plano de download, checksum, parse, manifesto e CLI incremental."""

from __future__ import annotations

import hashlib
import io
import urllib.parse
import zipfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from src import archive as cli
from src.extractors import ExtractorError
from src.extractors import binance_archive as ba
from src.extractors.binance_archive import ArchiveKey, BinanceArchiveAdapter, catalog_frame, parse_listing, plan_files
from src.loaders import archive_store
from src.loaders.market_store import read_revisions

END = datetime(2026, 10, 16, 0, 10, tzinfo=timezone.utc)
DAY_MS = 86_400_000


def _csv(start: str, n: int, price: float = 10.0, micro: bool = False, header: bool = False) -> bytes:
    first = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    lines = ["open_time,open,high,low,close,volume,close_time,quote_volume,count,tb_base,tb_quote,ignore"] if header else []
    for i in range(n):
        t = first + i * DAY_MS
        ts = t * 1000 if micro else t
        p = price + i
        lines.append(f"{ts},{p},{p + 1},{p - 1},{p + 0.5},100,{ts + DAY_MS - 1},{1000 * p},42,1,1,0")
    return ("\n".join(lines) + "\n").encode()


def _zip(csv: bytes, name: str = "x.csv") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, csv)
    return buf.getvalue()


def _listing(keys: list[ArchiveKey], truncated: bool = False, next_marker: str | None = None) -> bytes:
    items = "".join(
        f"<Contents><Key>{k.key}</Key><LastModified>{k.last_modified}</LastModified><ETag>&quot;{k.etag}&quot;</ETag>"
        f"<Size>{k.size}</Size></Contents>"
        for k in keys
    )
    marker = f"<NextMarker>{next_marker}</NextMarker>" if next_marker else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?><ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        f"<IsTruncated>{'true' if truncated else 'false'}</IsTruncated>{marker}{items}</ListBucketResult>"
    ).encode()


def _key(sym: str, period: str, etag: str = "e1") -> ArchiveKey:
    kind = "daily" if len(period) == 10 else "monthly"
    return ArchiveKey(f"data/spot/{kind}/klines/{sym}/1d/{sym}-1d-{period}.zip", etag, "2026-10-01T00:00:00.000Z", 100)


class FakeArchive:
    """Substitui http.get_bytes: listagem por prefixo e ZIPs com checksum correto (ou adulterado)."""

    def __init__(self, files: dict[str, bytes], etags: dict[str, str] | None = None, bad_checksum: set[str] | None = None,
                 no_checksum: set[str] | None = None) -> None:
        self.files = files
        self.etags = etags or {}
        self.bad = bad_checksum or set()
        self.no_checksum = no_checksum or set()
        self.downloads: list[str] = []

    def __call__(self, url: str, params: dict[str, str | int] | None = None, headers: dict[str, str] | None = None,
                 **kwargs: object) -> bytes | None:
        if params is not None and "prefix" in params:
            prefix = str(params["prefix"])
            keys = [ArchiveKey(k, self.etags.get(k, "e1"), "2026-10-01T00:00:00.000Z", len(v))
                    for k, v in sorted(self.files.items()) if k.startswith(prefix)]
            return _listing(keys)
        path = urllib.parse.unquote(urllib.parse.urlsplit(url).path).lstrip("/").removeprefix("data.binance.vision/")
        if path.endswith(".CHECKSUM"):
            key = path.removesuffix(".CHECKSUM")
            if key in self.no_checksum:
                return None
            digest = "0" * 64 if key in self.bad else hashlib.sha256(self.files[key]).hexdigest()
            return f"{digest}  {key.rsplit('/', 1)[-1]}".encode()
        self.downloads.append(path)
        return self.files.get(path)


def _install(monkeypatch: pytest.MonkeyPatch, fake: Callable[..., bytes | None]) -> None:
    monkeypatch.setattr(ba, "get_bytes", fake)


def _files() -> dict[str, bytes]:
    return {
        _key("LUNAUSDT", "2026-08").key: _zip(_csv("2026-08-01", 31)),
        _key("LUNAUSDT", "2026-09").key: _zip(_csv("2026-09-01", 30, micro=True, header=True)),
        _key("LUNAUSDT", "2026-10-14").key: _zip(_csv("2026-10-14", 1)),
        _key("LUNAUSDT", "2026-10-15").key: _zip(_csv("2026-10-15", 1)),
    }


# ---- puros ------------------------------------------------------------------------------------------

def test_parse_listing_reads_keys_and_pagination_marker() -> None:
    keys = [_key("BTCUSDT", "2020-01"), _key("BTCUSDT", "2020-02")]
    got, prefixes, marker = parse_listing(_listing(keys, truncated=True))
    assert [k.key for k in got] == [k.key for k in keys] and prefixes == []
    assert marker == keys[-1].key
    assert parse_listing(_listing(keys))[2] is None
    with pytest.raises(ExtractorError):
        parse_listing(b"<html>")


def test_plan_downloads_monthly_and_only_daily_files_not_covered_by_a_monthly() -> None:
    keys = [_key("XUSDT", "2026-08"), _key("XUSDT", "2026-09"), _key("XUSDT", "2026-09-30"), _key("XUSDT", "2026-10-15"),
            ArchiveKey("data/spot/monthly/klines/XUSDT/1d/XUSDT-1d-2026-09.zip.CHECKSUM", "c", "", 1)]
    plan = [k.key for k in plan_files(keys, None, END, {})]
    assert plan == [keys[0].key, keys[1].key, keys[3].key]  # 30/09 já está no mensal; .CHECKSUM ignorado
    assert [k.key for k in plan_files(keys, datetime(2026, 9, 15, tzinfo=timezone.utc), END, {})] == [keys[1].key, keys[3].key]


def test_plan_skips_known_etag_and_redownloads_a_republished_file() -> None:
    keys = [_key("XUSDT", "2026-08", "e1"), _key("XUSDT", "2026-09", "e2")]
    known = {keys[0].key: "e1", keys[1].key: "velho"}
    assert [k.key for k in plan_files(keys, None, END, known)] == [keys[1].key]


def test_catalog_counts_months_gaps_and_last_daily() -> None:
    listings = {"LUNAUSDT": [_key("LUNAUSDT", "2022-04"), _key("LUNAUSDT", "2022-07"), _key("LUNAUSDT", "2022-07-02")],
                "BTCUSDT": [_key("BTCUSDT", "2017-08")]}
    cat = catalog_frame(listings, "USDT").set_index("symbol")
    assert cat.loc["LUNA/USDT", "first_month"] == "2022-04" and cat.loc["LUNA/USDT", "last_month"] == "2022-07"
    assert cat.loc["LUNA/USDT", "months"] == 2 and cat.loc["LUNA/USDT", "missing_months"] == 2
    assert cat.loc["LUNA/USDT", "last_daily"] == "2022-07-02"


def test_parse_zip_handles_header_and_microseconds() -> None:
    a = ba.parse_zip(_zip(_csv("2026-09-01", 2, micro=True, header=True)))
    b = ba.parse_zip(_zip(_csv("2026-09-01", 2)))
    pd.testing.assert_frame_equal(a, b)
    assert a["timestamp"].iloc[0] == pd.Timestamp("2026-09-01", tz="UTC")
    assert a["trades"].dtype == "Int64"
    with pytest.raises(ExtractorError):
        ba.parse_zip(b"nao e zip")


def test_hosts_are_allowlisted() -> None:
    with pytest.raises(ValueError):
        BinanceArchiveAdapter(["BTC/USDT"], host="https://exemplo.test")
    with pytest.raises(ValueError):
        BinanceArchiveAdapter(["BTC/BRL"])


# ---- adaptador com rede falsa ----------------------------------------------------------------------

def test_extract_verifies_checksums_drops_unclosed_and_builds_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeArchive(_files())
    _install(monkeypatch, fake)
    end = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)  # o candle de 15/10 ainda não fechou
    candles, manifest = BinanceArchiveAdapter(["LUNA/USDT"], workers=2).extract_with_manifest(None, end)
    assert candles["timestamp"].max() == pd.Timestamp("2026-10-14", tz="UTC")
    assert len(candles) == 31 + 30 + 1
    assert candles["symbol"].eq("LUNA/USDT").all() and candles["source"].eq("binance").all()
    assert not candles.duplicated(["symbol", "timestamp"]).any()
    m = manifest.set_index("period")
    assert m.loc["2026-10-15", "rows"] == 0 and m.loc["2026-09", "rows"] == 30
    assert all(len(h) == 64 for h in manifest["sha256"])


def test_checksum_mismatch_or_missing_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    files = _files()
    bad = next(iter(files))
    _install(monkeypatch, FakeArchive(files, bad_checksum={bad}))
    with pytest.raises(ExtractorError, match="checksum"):
        BinanceArchiveAdapter(["LUNA/USDT"]).extract(None, END)
    _install(monkeypatch, FakeArchive(files, no_checksum={bad}))
    with pytest.raises(ExtractorError, match="CHECKSUM"):
        BinanceArchiveAdapter(["LUNA/USDT"]).extract(None, END)


# ---- CLI: incremental, idempotente, falha isolada --------------------------------------------------

@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_second_sync_downloads_nothing_and_does_not_duplicate(workdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeArchive(_files())
    _install(monkeypatch, fake)
    assert cli.cmd_sync(["LUNA/USDT"], False, 2, END) == 0
    first = archive_store.read_archive_candles()
    n_downloads = len(fake.downloads)
    manifest_rows = len(archive_store.read_manifest())
    assert cli.cmd_sync(["LUNA/USDT"], False, 2, END) == 0
    second = archive_store.read_archive_candles()
    assert len(fake.downloads) == n_downloads  # nada baixado de novo
    assert len(archive_store.read_manifest()) == manifest_rows
    pd.testing.assert_frame_equal(first, second)
    assert read_revisions(archive_store.ARCHIVE_DIR).empty
    log = archive_store.read_sync_log()
    assert log["status"].eq("ok").all() and log["files"].tolist() == [4, 0]


def test_republished_file_is_reingested_and_the_change_is_audited(workdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    files = _files()
    _install(monkeypatch, FakeArchive(files))
    cli.cmd_sync(["LUNA/USDT"], False, 2, END)
    key = _key("LUNAUSDT", "2026-08").key
    files[key] = _zip(_csv("2026-08-01", 31, price=11.0))  # a Binance republicou o mês com outro preço
    _install(monkeypatch, FakeArchive(files, etags={key: "e2"}))
    cli.cmd_sync(["LUNA/USDT"], False, 2, END)
    revisions = read_revisions(archive_store.ARCHIVE_DIR)
    assert not revisions.empty
    assert set(revisions["column"]) >= {"open", "close"}
    first = revisions[(revisions["column"] == "close")].sort_values("timestamp").iloc[0]
    assert (first["old_value"], first["new_value"]) == (10.5, 11.5)
    assert archive_store.read_archive_candles()["close"].iloc[0] == 11.5


def test_failed_pair_is_logged_and_does_not_touch_existing_data(workdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    files = _files()
    _install(monkeypatch, FakeArchive(files))
    cli.cmd_sync(["LUNA/USDT"], False, 2, END)
    before = archive_store.read_archive_candles()
    files[_key("LUNAUSDT", "2026-10-15").key] = _zip(_csv("2026-10-15", 1, price=99.0))
    _install(monkeypatch, FakeArchive(files, etags={_key("LUNAUSDT", "2026-10-15").key: "novo"},
                                      bad_checksum={_key("LUNAUSDT", "2026-10-15").key}))
    assert cli.cmd_sync(["LUNA/USDT"], False, 2, END) == 1  # falha parcial não sai com código 0
    pd.testing.assert_frame_equal(before, archive_store.read_archive_candles())
    log = archive_store.read_sync_log()
    assert log["status"].tolist() == ["ok", "erro"]
    assert "checksum" in str(log["detail"].iloc[-1])


def test_parallel_pairs_store_the_same_data_as_sequential(workdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    files = {**_files(), **{k.replace("LUNAUSDT", "BTCUSDT"): v for k, v in _files().items()}}
    _install(monkeypatch, FakeArchive(files))
    assert cli.cmd_sync(["LUNA/USDT", "BTC/USDT"], False, 2, END, pairs=2) == 0
    parallel = archive_store.read_archive_candles()
    assert sorted(parallel["symbol"].unique()) == ["BTC/USDT", "LUNA/USDT"]
    assert len(archive_store.read_manifest()) == 8
    assert archive_store.read_sync_log()["status"].eq("ok").all()


def test_universe_command_writes_point_in_time_outputs(workdir: Path, monkeypatch: pytest.MonkeyPatch,
                                                       capsys: pytest.CaptureFixture[str]) -> None:
    _install(monkeypatch, FakeArchive(_files()))
    cli.cmd_sync(["LUNA/USDT"], False, 2, END)
    assert cli.cmd_universe(END) == 0
    for name in ("universe_history", "listing_events", "survivorship"):
        assert (workdir / "data" / "archive" / "point_in_time" / f"{name}.parquet").is_file()
    assert "universo point-in-time" in capsys.readouterr().out

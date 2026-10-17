"""Registro das suas compras. Depois de cada mudança, reavalia as posições com a base local e atualiza o painel.

Uso (da raiz do projeto):
    uv run python -m src.positions add BTC/USDT 83169 0.01            compra hoje a 83169, qtd 0.01
    uv run python -m src.positions add SOL/USDT 106.8 2 --date 2026-10-01
    uv run python -m src.positions list
    uv run python -m src.positions close <id> 95000                    vendeu a 95000
    uv run python -m src.positions remove <id>                         apaga um registro errado

As posições ficam em `data/state/positions.parquet`, um worktree da branch `state` (ver `src/state_sync.py`). Cada
comando que altera algo traz a branch antes e envia o resultado depois, para o GitHub Actions avisar mesmo com o PC
desligado. Use `--no-sync` para trabalhar só localmente.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timezone

import pandas as pd

from .config import UNIVERSE
from .loaders.positions_store import POSITIONS_SCHEMA, read_positions, write_positions
from . import state_sync
from .pipeline import refresh_positions


def _parse_day(value: str | None) -> pd.Timestamp:
    today = pd.Timestamp(datetime.now(timezone.utc)).floor("D")
    if value is None:
        return today
    try:
        day = pd.Timestamp(datetime.strptime(value, "%Y-%m-%d"), tz="UTC")
    except ValueError:
        raise SystemExit(f"data inválida: {value} (use AAAA-MM-DD)") from None
    if day > today:
        raise SystemExit("a data não pode estar no futuro")
    return day


def add(symbol: str, price: float, qty: float, date: str | None) -> str:
    symbol = symbol.upper()
    if symbol not in UNIVERSE:
        raise SystemExit(f"{symbol} não está em src/config.py (UNIVERSE). Moedas: {', '.join(UNIVERSE)}")
    if price <= 0 or qty <= 0:
        raise SystemExit("preço e quantidade devem ser positivos")
    position_id = uuid.uuid4().hex[:8]
    values = {
        "position_id": position_id, "symbol": symbol, "entry_ts": _parse_day(date), "entry_price": price,
        "qty": qty, "closed": False, "exit_ts": None, "exit_price": None,
    }
    row = pd.DataFrame({c: pd.Series([values[c]], dtype=t) for c, t in POSITIONS_SCHEMA.items()})
    current = read_positions()
    write_positions(row if current.empty else pd.concat([current, row], ignore_index=True))
    return position_id


def _require(df: pd.DataFrame, position_id: str) -> "pd.Series[bool]":
    mask = df["position_id"].eq(position_id).fillna(False).astype(bool)
    if not mask.any():
        raise SystemExit(f"posição {position_id} não encontrada (veja: python -m src.positions list)")
    return mask


def close(position_id: str, price: float, date: str | None) -> None:
    df = read_positions()
    mask = _require(df, position_id)
    df = df.assign(
        closed=df["closed"] | mask,
        exit_ts=df["exit_ts"].mask(mask, _parse_day(date)),
        exit_price=df["exit_price"].mask(mask, price),
    )
    write_positions(df)


def remove(position_id: str) -> None:
    df = read_positions()
    write_positions(df[~_require(df, position_id)])


def show() -> str:
    df = read_positions()
    if df.empty:
        return "nenhuma posição registrada."
    view = df.assign(
        entry_ts=df["entry_ts"].dt.strftime("%Y-%m-%d"),
        status=df["closed"].map({True: "fechada", False: "aberta"}),
        result=((df["exit_price"] / df["entry_price"] - 1) * 100).round(1),
    )[["position_id", "symbol", "entry_ts", "entry_price", "qty", "status", "exit_price", "result"]]
    return view.to_string(index=False)


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description="Registro das suas posições")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--no-sync", action="store_true", help="não traz nem envia a branch `state` (só local)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_add = sub.add_parser("add", help="registra uma compra", parents=[common])
    p_add.add_argument("symbol")
    p_add.add_argument("price", type=float)
    p_add.add_argument("qty", type=float)
    p_add.add_argument("--date", help="AAAA-MM-DD (padrão: hoje)")
    p_close = sub.add_parser("close", help="registra a venda", parents=[common])
    p_close.add_argument("position_id")
    p_close.add_argument("price", type=float)
    p_close.add_argument("--date")
    p_rm = sub.add_parser("remove", help="apaga um registro", parents=[common])
    p_rm.add_argument("position_id")
    sub.add_parser("list", help="lista as posições")
    args = parser.parse_args(argv)

    if args.cmd == "list":
        print(show())
        return 0
    sync = not bool(getattr(args, "no_sync", False))
    if sync:
        try:
            state_sync.init()
            state_sync.pull()
        except state_sync.StateSyncError as exc:
            print(f"aviso: não consegui sincronizar o estado antes de alterar: {exc}")
            return 1
    if args.cmd == "add":
        print(f"posição registrada: {add(args.symbol, args.price, args.qty, args.date)}")
    elif args.cmd == "close":
        close(args.position_id, args.price, args.date)
        print(f"posição {args.position_id} fechada.")
    elif args.cmd == "remove":
        remove(args.position_id)
        print(f"posição {args.position_id} removida.")

    if sync:
        try:
            sent = state_sync.push(f"posições: {args.cmd}")
        except state_sync.StateSyncError as exc:
            print(f"erro ao enviar o estado (a alteração ficou só neste computador): {exc}")
            return 1
        print("estado enviado à branch `state`." if sent else "estado já estava em dia no GitHub.")
    refresh_positions(datetime.now(timezone.utc))  # atualiza as posições no painel com a base local, sem rede
    print(show())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

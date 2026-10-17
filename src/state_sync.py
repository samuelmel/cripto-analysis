"""Sincroniza `data/state/` com a branch `state` do repositório (posições, registro de sinais, histórico de estados, avisos).

Entrypoint de I/O (CLAUDE.md §1): só chama o `git`. A pasta `data/state/` é um worktree da branch `state`; assim as suas
posições ficam acessíveis ao GitHub Actions (que faz o checkout da mesma branch) e o `main` não recebe commits de dados.

Uso (da raiz do projeto):
    uv run python -m src.state_sync init        cria/ligar o worktree (cria a branch `state` vazia se ela não existir)
    uv run python -m src.state_sync pull        traz o que o GitHub Actions gravou
    uv run python -m src.state_sync push        envia o que mudou localmente

Nunca imprime URLs com credenciais nem variáveis de ambiente. O `push` só toca a branch `state`.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .loaders.state_store import STATE_DIR

BRANCH = "state"
REMOTE = "origin"
LEGACY_POSITIONS = Path("data/positions/positions.parquet")
_URL_CREDENTIALS = re.compile(r"://[^@/\s]+@")


class StateSyncError(RuntimeError):
    """Falha de git ao sincronizar o estado."""


def _clean(text: str) -> str:
    return _URL_CREDENTIALS.sub("://***@", text).strip()


def _git(args: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    if check and proc.returncode != 0:
        raise StateSyncError(f"git {' '.join(args[:2])} falhou: {_clean(proc.stderr or proc.stdout)}")
    return proc


def is_worktree(directory: Path = STATE_DIR) -> bool:
    return (directory / ".git").exists()


def init(directory: Path = STATE_DIR) -> str:
    """Garante o worktree da branch `state` em `directory`. Devolve o que foi feito (para mostrar ao usuário)."""
    if is_worktree(directory):
        return "worktree já existe"
    directory.parent.mkdir(parents=True, exist_ok=True)
    _git(["fetch", REMOTE, BRANCH], check=False)
    if _git(["rev-parse", "--verify", f"refs/remotes/{REMOTE}/{BRANCH}"], check=False).returncode == 0:
        _git(["worktree", "add", "-B", BRANCH, str(directory), f"{REMOTE}/{BRANCH}"])
        message = "worktree ligado à branch remota"
    else:
        _git(["worktree", "add", "--detach", str(directory)])
        _git(["checkout", "--orphan", BRANCH], cwd=directory)
        _git(["rm", "-rf", "--quiet", "."], cwd=directory, check=False)
        (directory / "README.md").write_text(
            "# Estado do crypto-analyzer\n\nBranch de dados (sem código): posições, registro imutável de sinais, histórico de "
            "estados e avisos enviados. Escrita pelo pipeline e por `python -m src.positions`. Não edite à mão.\n",
            encoding="utf-8",
        )
        _git(["add", "-A"], cwd=directory)
        _git(["commit", "-q", "-m", "estado: branch criada"], cwd=directory)
        message = "branch `state` criada (vazia)"
    if LEGACY_POSITIONS.is_file() and not (directory / "positions.parquet").exists():
        shutil.copy2(LEGACY_POSITIONS, directory / "positions.parquet")
        message += "; posições antigas de data/positions/ copiadas"
    return message


def pull(directory: Path = STATE_DIR) -> bool:
    """Traz as mudanças da branch `state`. False se não há worktree ou a branch ainda não existe no remoto."""
    if not is_worktree(directory):
        return False
    if _git(["ls-remote", "--exit-code", "--heads", REMOTE, BRANCH], check=False).returncode != 0:
        return False
    _git(["pull", "--ff-only", "-q", REMOTE, BRANCH], cwd=directory)
    return True


def push(message: str, directory: Path = STATE_DIR) -> bool:
    """Grava no commit e envia o que mudou em `directory`. False se não há worktree ou nada mudou."""
    if not is_worktree(directory):
        return False
    _git(["add", "-A"], cwd=directory)
    if _git(["diff", "--cached", "--quiet"], cwd=directory, check=False).returncode == 0:
        return False
    _git(["commit", "-q", "-m", message], cwd=directory)
    pushed = _git(["push", "-q", REMOTE, f"HEAD:{BRANCH}"], cwd=directory, check=False)
    if pushed.returncode != 0:
        _git(["pull", "--rebase", "-q", REMOTE, BRANCH], cwd=directory)
        _git(["push", "-q", REMOTE, f"HEAD:{BRANCH}"], cwd=directory)
    return True


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cmd", choices=("init", "pull", "push"))
    args = parser.parse_args(argv)
    try:
        if args.cmd == "init":
            print(init())
        elif args.cmd == "pull":
            print("atualizado" if pull() else "nada para trazer (sem worktree ou sem branch remota)")
        else:
            print("enviado" if push("estado: atualização manual") else "nada para enviar")
    except StateSyncError as exc:
        print(f"erro: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

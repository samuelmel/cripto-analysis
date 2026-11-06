"""Sincroniza `data/state/` com o repositório privado de estado (posições, registro de sinais, histórico de estados, avisos).

Entrypoint de I/O (CLAUDE.md §1): só chama o `git`. A pasta `data/state/` é um clone normal do repositório privado
`samuelmel/cripto-analysis-state` (branch `main`). Esse repositório é separado do código: o `main` deste projeto não
recebe commits de dados, e o GitHub Actions grava o estado nele usando uma deploy key SSH com escrita.

Os dois sentidos ficam separados:
- `init` cria o clone (ou migra o worktree antigo da branch `state` deste repositório, sem tocar no remoto);
- `pull` traz o que o GitHub Actions gravou; `push` envia o que mudou localmente.

Uso (da raiz do projeto):
    uv run python -m src.state_sync init        cria o clone (ou migra o worktree antigo)
    uv run python -m src.state_sync pull        traz o que o GitHub Actions gravou
    uv run python -m src.state_sync push        envia o que mudou localmente

Nunca imprime URLs com credenciais nem variáveis de ambiente. Toda mensagem de erro passa por `_clean`.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .loaders.state_store import STATE_DIR

STATE_REPO_URL = "https://github.com/samuelmel/cripto-analysis-state.git"
BRANCH = "main"
REMOTE = "origin"
LEGACY_BRANCH = "state"  # branch antiga deste repositório, usada até a migração para o repositório de estado
LEGACY_POSITIONS = Path("data/positions/positions.parquet")
BACKUP_DIR = Path("data/state_migracao_backup")
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


def is_checkout(directory: Path = STATE_DIR) -> bool:
    """True se `directory` é um clone normal (`.git` é uma pasta)."""
    return (directory / ".git").is_dir()


def is_legacy_worktree(directory: Path = STATE_DIR) -> bool:
    """True se `directory` é o worktree antigo da branch `state` (`.git` é um arquivo)."""
    return (directory / ".git").is_file()


def _check_remote(remote_url: str, directory: Path) -> None:
    """Confere que o clone aponta para o repositório de estado esperado (sem imprimir credenciais)."""
    current = _git(["remote", "get-url", REMOTE], cwd=directory, check=False).stdout.strip()
    if current != remote_url:
        raise StateSyncError(
            f"o clone em {directory} não aponta para o repositório de estado esperado "
            f"(origin atual: {_clean(current) or 'ausente'}). Ajuste o remoto ou apague a pasta e rode init de novo."
        )


def _remote_has_branch(directory: Path) -> bool:
    return _git(["ls-remote", "--exit-code", "--heads", REMOTE, BRANCH], cwd=directory, check=False).returncode == 0


def _clone(remote_url: str, directory: Path) -> str:
    directory.parent.mkdir(parents=True, exist_ok=True)
    _git(["clone", "-q", remote_url, str(directory)])
    if _git(["rev-parse", "--verify", "-q", f"refs/remotes/{REMOTE}/{BRANCH}"], cwd=directory, check=False).returncode == 0:
        # HEAD do remoto pode apontar para uma branch inexistente: o checkout explícito da `main` resolve isso.
        _git(["checkout", "-q", "-B", BRANCH, f"{REMOTE}/{BRANCH}"], cwd=directory)
        return "clone ligado ao repositório de estado"
    if _git(["for-each-ref", "--format=%(refname)", f"refs/remotes/{REMOTE}"], cwd=directory).stdout.strip():
        raise StateSyncError(f"o repositório de estado não tem a branch `{BRANCH}`; não vou criá-la por cima de outras branches.")
    # Remoto vazio: cria a branch `main` com o README e envia.
    _git(["symbolic-ref", "HEAD", f"refs/heads/{BRANCH}"], cwd=directory)
    (directory / "README.md").write_text(
        "# Estado do crypto-analyzer\n\nRepositório privado de dados (sem código): posições, registro imutável de sinais, "
        "histórico de estados e avisos enviados. Escrita pelo pipeline (GitHub Actions) e por `python -m src.positions`. "
        "Não edite à mão.\n",
        encoding="utf-8",
    )
    _git(["add", "-A"], cwd=directory)
    _git(["commit", "-q", "-m", "estado: repositório criado"], cwd=directory)
    _git(["push", "-q", "-u", REMOTE, f"HEAD:{BRANCH}"], cwd=directory)
    return "repositório de estado vazio: README criado e enviado"


def _migrate_worktree(remote_url: str, directory: Path) -> str:
    """Troca o worktree antigo da branch `state` por um clone do repositório de estado. Nunca apaga dado local."""
    if _git(["status", "--porcelain"], cwd=directory).stdout.strip():
        raise StateSyncError(
            f"{directory} tem mudanças não commitadas no worktree antigo (veja com `git -C {directory} status`). "
            "Faça commit ou salve o que importa em outro lugar e rode init de novo. Nada foi removido."
        )
    staging = Path(tempfile.mkdtemp(prefix="state_migracao_"))
    try:
        local_files = sorted(directory.glob("*.parquet"))
        for file in local_files:
            shutil.copy2(file, staging / file.name)
        _git(["worktree", "remove", str(directory)])
        _git(["branch", "-D", LEGACY_BRANCH], check=False)  # só local; o remoto não é tocado
        message = _clone(remote_url, directory)
        conflicts: list[str] = []
        for file in sorted(staging.glob("*.parquet")):
            target = directory / file.name
            if not target.exists():
                shutil.copy2(file, target)
            elif target.read_bytes() != file.read_bytes():
                BACKUP_DIR.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file, BACKUP_DIR / file.name)
                conflicts.append(file.name)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    message = f"worktree antigo migrado para clone; {message}"
    if conflicts:
        message += (
            f"; ATENÇÃO: {', '.join(conflicts)} diferem do repositório de estado e NÃO foram sobrescritos. "
            f"A cópia local está em {BACKUP_DIR}/ para você conferir."
        )
    return message


def init(remote_url: str = STATE_REPO_URL, directory: Path = STATE_DIR) -> str:
    """Garante o clone do repositório de estado em `directory`. Devolve o que foi feito (para mostrar ao usuário)."""
    if is_checkout(directory):
        _check_remote(remote_url, directory)
        message = "clone já existe"
    elif is_legacy_worktree(directory):
        message = _migrate_worktree(remote_url, directory)
    else:
        if directory.exists() and any(directory.iterdir()):
            raise StateSyncError(f"{directory} existe, não é um clone e não está vazia. Mova a pasta e rode init de novo.")
        message = _clone(remote_url, directory)
    if LEGACY_POSITIONS.is_file() and not (directory / "positions.parquet").exists():
        shutil.copy2(LEGACY_POSITIONS, directory / "positions.parquet")
        message += "; posições antigas de data/positions/ copiadas"
    return message


def pull(remote_url: str = STATE_REPO_URL, directory: Path = STATE_DIR) -> bool:
    """Traz as mudanças do repositório de estado. False se não há clone ou o remoto ainda não tem a branch."""
    if not is_checkout(directory):
        return False
    _check_remote(remote_url, directory)
    if not _remote_has_branch(directory):
        return False
    _git(["pull", "--ff-only", "-q", REMOTE, BRANCH], cwd=directory)
    return True


def push(message: str, remote_url: str = STATE_REPO_URL, directory: Path = STATE_DIR) -> bool:
    """Grava no commit e envia o que mudou em `directory`. False se não há clone ou nada mudou."""
    if not is_checkout(directory):
        return False
    _check_remote(remote_url, directory)
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
            print("atualizado" if pull() else "nada para trazer (sem clone ou sem branch remota)")
        else:
            print("enviado" if push("estado: atualização manual") else "nada para enviar")
    except StateSyncError as exc:
        print(f"erro: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

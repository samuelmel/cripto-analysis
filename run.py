"""Sobe a API e o painel localmente com um comando."""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from http.client import HTTPResponse
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT / "frontend"
DIST = FRONTEND / "dist" / "index.html"

DEFAULT_API_PORT = 8000
DEFAULT_WEB_PORT = 5173
API_HOST = "127.0.0.1"
WEB_HOST = "127.0.0.1"
CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


@dataclass(frozen=True)
class Options:
    prod: bool
    build: bool
    no_browser: bool
    api_port: int
    web_port: int


def parse_args() -> Options:
    parser = argparse.ArgumentParser(
        description="Inicia a API FastAPI e o painel React. Por padrão abre o modo de desenvolvimento.",
    )
    parser.add_argument("--prod", action="store_true", help="serve o build do frontend pela API, em uma porta só")
    parser.add_argument("--build", action="store_true", help="gera o build do frontend antes de iniciar")
    parser.add_argument("--no-browser", action="store_true", help="não abre o navegador")
    parser.add_argument("--api-port", type=int, default=DEFAULT_API_PORT, help="porta da API (padrão: 8000)")
    parser.add_argument("--web-port", type=int, default=DEFAULT_WEB_PORT, help="porta do Vite (padrão: 5173)")
    args = parser.parse_args()
    return Options(
        prod=bool(args.prod),
        build=bool(args.build),
        no_browser=bool(args.no_browser),
        api_port=int(args.api_port),
        web_port=int(args.web_port),
    )


def uv_command() -> str | None:
    return shutil.which("uv")


def npx_command() -> str:
    executable = shutil.which("npx")
    if executable is None:
        raise SystemExit("npx não encontrado. Instale o Node.js 20+ e tente de novo.")
    return executable


def pnpm_command(*args: str) -> list[str]:
    return [npx_command(), "--yes", "pnpm@10", *args]


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((API_HOST, port)) == 0


def api_ready(port: int) -> bool:
    url = f"http://{API_HOST}:{port}/api/v1/health"
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            return cast(HTTPResponse, response).status == 200
    except (urllib.error.URLError, OSError):
        return False


def start(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> subprocess.Popen[str]:
    print(f"> {' '.join(command)} (em {cwd})")
    return subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        text=True,
        creationflags=CREATE_NEW_PROCESS_GROUP,
    )


def stop(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def wait_for(
    label: str,
    check: Callable[[], bool],
    timeout: float,
    process: subprocess.Popen[str] | None = None,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        if process is not None and process.poll() is not None:
            return False
        time.sleep(0.4)
    print(f"Tempo esgotado esperando {label}.")
    return False


def ensure_dependencies() -> None:
    if (FRONTEND / "node_modules").is_dir():
        return
    print("Instalando dependências do frontend...")
    result = subprocess.run(pnpm_command("install"), cwd=FRONTEND, check=False)
    if result.returncode != 0:
        raise SystemExit("Falha ao instalar as dependências do frontend.")


def build_frontend() -> None:
    ensure_dependencies()
    print("Gerando o build do frontend...")
    result = subprocess.run(pnpm_command("build"), cwd=FRONTEND, check=False)
    if result.returncode != 0:
        raise SystemExit("Falha ao gerar o build do frontend.")


def start_api(port: int) -> subprocess.Popen[str] | None:
    if api_ready(port):
        print(f"API já está respondendo em http://{API_HOST}:{port}.")
        return None
    if port_open(port):
        raise SystemExit(f"A porta {port} está ocupada por outro processo. Use --api-port para escolher outra.")

    env = os.environ.copy()
    env["CRYPTO_ANALYZER_API_HOST"] = API_HOST
    env["CRYPTO_ANALYZER_API_PORT"] = str(port)
    uv = uv_command()
    command = [uv, "run", "python", "-m", "src.api"] if uv is not None else [sys.executable, "-m", "src.api"]
    print(f"Aguardando a API em http://{API_HOST}:{port}...")
    process = start(command, ROOT, env=env)
    if not wait_for("a API", lambda: api_ready(port), timeout=90, process=process):
        stop(process)
        raise SystemExit("A API não iniciou. Confira as mensagens acima.")
    return process


def start_web(port: int) -> subprocess.Popen[str]:
    if port_open(port):
        raise SystemExit(f"A porta {port} está ocupada por outro processo. Use --web-port para escolher outra.")
    ensure_dependencies()
    print(f"Aguardando o Vite em http://{WEB_HOST}:{port}...")
    process = start(
        pnpm_command("run", "dev", "--host", WEB_HOST, "--port", str(port)),
        FRONTEND,
    )
    if not wait_for("o Vite", lambda: port_open(port), timeout=90, process=process):
        stop(process)
        raise SystemExit("O frontend não iniciou. Confira as mensagens acima.")
    return process


def open_browser(url: str) -> None:
    print(f"Painel disponível em {url}")
    webbrowser.open(url)


def watch(processes: list[subprocess.Popen[str]]) -> int:
    try:
        while True:
            for process in processes:
                code = process.poll()
                if code is not None:
                    print(f"Um processo terminou com código {code}.")
                    return 1
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nEncerrando...")
        return 0
    finally:
        for process in reversed(processes):
            stop(process)


def run_dev(options: Options) -> int:
    processes: list[subprocess.Popen[str]] = []
    api = start_api(options.api_port)
    if api is not None:
        processes.append(api)
    web = start_web(options.web_port)
    processes.append(web)

    url = f"http://{WEB_HOST}:{options.web_port}"
    if not options.no_browser:
        open_browser(url)
    else:
        print(f"Painel disponível em {url}")
    return watch(processes)


def run_prod(options: Options) -> int:
    if options.build or not DIST.is_file():
        build_frontend()

    api = start_api(options.api_port)
    processes = [api] if api is not None else []
    url = f"http://{API_HOST}:{options.api_port}"
    if not options.no_browser:
        open_browser(url)
    else:
        print(f"Painel disponível em {url}")
    if not processes:
        print("A API já estava em execução; nada para encerrar.")
        return 0
    return watch(processes)


def main() -> int:
    options = parse_args()
    if options.prod:
        return run_prod(options)
    return run_dev(options)


if __name__ == "__main__":
    raise SystemExit(main())

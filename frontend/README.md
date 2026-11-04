# Painel do Crypto Analyzer

Frontend React + TypeScript do monitor quantitativo. Ele consome a API FastAPI somente leitura em `/api/v1`; não lê
Parquet no navegador, não calcula sinais e não envia ordens. A arquitetura completa está em
[`docs/frontend-architecture.md`](../docs/frontend-architecture.md).

## Desenvolvimento

Na raiz do projeto, o atalho sobe API, Vite e navegador:

```bash
uv run run.py
```

Para iniciar separadamente, rode `uv run python -m src.api` em um terminal e, em outro:

```bash
cd frontend
npx --yes pnpm@10 install
npx --yes pnpm@10 dev
```

O Vite roda em `http://localhost:5173` e encaminha `/api` para `http://127.0.0.1:8000`.

## Verificação

```bash
npx --yes pnpm@10 typecheck
npx --yes pnpm@10 test
npx --yes pnpm@10 build
npx --yes pnpm@10 e2e
```

O build fica em `dist/`. Em produção, `uv run python -m src.api` serve esse diretório na mesma origem da API.

## Dados ausentes

Algumas telas dependem de Parquets que podem não existir no worktree atual, como `sim_wallets.parquet` e
`sim_wallet_positions.parquet`. Nesses casos a interface mostra estado indisponível; ela não inventa patrimônio,
posições ou cotações.

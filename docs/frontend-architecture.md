# Frontend e API — arquitetura

Este documento descreve a camada de apresentação do Crypto Analyzer: uma API FastAPI **somente leitura** sobre os
Parquets publicados e um frontend React/TypeScript. Ele não altera o pipeline, o motor de backtest, as regras de
investimento nem a branch `state`.

## 1. Princípios

- A API lê artefatos; não calcula sinais, aportes, scores ou elegibilidade. Indicadores continuam em `src/transformers/`.
- Nenhum endpoint escreve arquivo, envia ordem ou acessa a branch `state`.
- Nenhum valor é inventado. Se um Parquet opcional não existe, a resposta traz estado indisponível.
- Toda resposta é tipada em Pydantic e espelhada em TypeScript com Zod na borda do navegador.
- A API não carrega o histórico inteiro para qualquer tela. Séries são limitadas por consulta; arquivos publicados são
  cacheados por `mtime` e invalidados quando o pipeline grava de novo.
- O frontend usa **dados reais da API**; não lê Parquet no navegador. A leitura antiga por `hyparquet` permanece apenas
  como contrato legado testado por `tests/test_frontend_contract.py`.

## 2. Fontes de dados

| Fonte | Caminho | Uso |
|---|---|---|
| Sinais diários | `frontend/public/daily_signals.parquet` | Visão geral, sinais, ativos e mercado. |
| Recomendação | `frontend/public/recommendation.parquet` | Resumo, regime, orçamento e decisão. |
| Desempenho | `frontend/public/performance.parquet` | Tendência × comprar e segurar. |
| Backtest da seleção | `frontend/public/selection_backtest.parquet` | Estratégias de seleção por período. |
| Regimes | `frontend/public/market_regimes.parquet` | Contexto causal de tendência e volatilidade. |
| Previsão | `frontend/public/forecast.parquet` | Faixas P10–P90 e veredito contra a referência. |
| Fontes | `frontend/public/sources.parquet` | Saúde e última coleta. |
| Laboratório | `frontend/public/strategy_lab.parquet` | Estratégias e DCA de referência. |
| Evidência por moeda | `frontend/public/signal_evidence.parquet` | Contagem de validação, sem recalcular. |
| Níveis de entrada | `frontend/public/entry_signal_levels.parquet` | Tabela do estudo de entradas. |
| Carteiras simuladas | `frontend/public/sim_wallets.parquet` | Resumo por carteira, quando existir. |
| Posições simuladas | `frontend/public/sim_wallet_positions.parquet` | Posições atuais, quando existir. |
| OHLCV point-in-time | `data/market/pit/ohlcv_1d/symbol=<SYMBOL>/data.parquet` | Candles para ativos e mercado. |

### Limitações atuais dos dados

- `sim_wallets.parquet`, `sim_wallet_positions.parquet`, `data/state/sim_decisions.parquet` e
  `data/state/model_predictions.parquet` não estão publicados neste worktree. A página de carteiras mostra estado
  indisponível para `PAINEL`, `IA`, `REVERSAO` e `SO_BTC`.
- O DCA fixo aparece como **referência do laboratório** (`strategy_lab.parquet`), não como carteira simulada em reais.
- `USDT/BRL` não está presente em `data/market/ohlcv_1d`. A API não converte valores sem cotação.
- A base point-in-time tem 683 pares. A elegibilidade histórica do universo **não** é recalculada pela API; isso exigiria
  reconstruir o universo dia a dia e não é uma leitura de apresentação.
- A data publicada é 2026-10-17. A API sinaliza defasagem em `/system/status` em vez de fingir atualidade.

## 3. API

Prefixo: `/api/v1`. Documentação interativa em `/docs`.

| Método | Rota | Retorno |
|---|---|---|
| GET | `/overview` | Recomendação, sinais, desempenho, seleção, previsão, regime e status. |
| GET | `/signals` | `daily_signals` + `recommendation` da mesma execução. |
| GET | `/market` | Resumo, ativos ranqueados, candles do BTC, regimes, previsões e fontes. |
| GET | `/assets?q=` | Busca nos 32 ativos analisados hoje. |
| GET | `/assets/{symbol}?days=` | Candles PIT, metadados e análise atual do ativo. |
| GET | `/research` | Catálogo editorial, laboratório, níveis de entrada e contagem de evidência. |
| GET | `/research/{study_id}` | Detalhe de um estudo. |
| GET | `/portfolios` | Catálogo das quatro carteiras + DCA, com estado explícito. |
| GET | `/portfolios/{portfolio_id}` | Resumo, posições e métricas quando disponíveis. |
| GET | `/system/status` | Artefatos, saúde das fontes, defasagem e nota de somente leitura. |
| GET | `/health` | Sonda simples. |

### Consistência

`overview` e `signals` recusam uma execução em que:

- `daily_signals` e `recommendation` têm `run_ts` diferente;
- a soma dos aportes passa do orçamento;
- o total do resumo difere da soma por moeda;
- existe aporte em moeda não selecionada.

Nesses casos a resposta é 503, nunca um painel silenciosamente errado.

### Cache

`src/api/cache.py` mantém um `DataFrame` por `(caminho, colunas)` e `mtime_ns`. Uma nova gravação do pipeline invalida a
entrada. O cache é de processo e não é persistido.

## 4. Frontend

### Estrutura

```
frontend/src/
  app/                 composição, rotas e providers
  components/layout/   shell, navegação e cabeçalho de página
  components/ui/       primitivas acessíveis
  components/charts/   gráficos ECharts
  components/data-display/
  features/overview/
  features/portfolios/
  features/research/
  features/market/
  features/methodology/
  lib/                 formato pt-BR, tons e funções puras
  services/            cliente HTTP e validação Zod
  schemas/             contratos TypeScript dos endpoints
  types/               contrato legado de `daily_signals` preservado
```

### Rotas

O app usa `HashRouter` para funcionar no build estático servido pelo FastAPI sem exigir fallback de servidor.

- `/` — Visão geral.
- `/carteiras` e `/carteiras/:portfolioId` — Carteiras.
- `/pesquisa` e `/pesquisa/:studyId` — Pesquisa quantitativa e detalhe do estudo.
- `/mercado` e `/mercado/:symbol` — Ativos e mercado.
- `/metodologia` — Metodologia e dados.

### Regras de UI

- Tema claro, cinza quente, grafite e teal. Verde/vermelho só para sinal e variação.
- IBM Plex Sans e IBM Plex Mono; números tabulares.
- Tabelas, tipografia e gráficos em vez de uma grade de cartões genéricos.
- Toda página tem estado de carregamento, erro e vazio.
- Nenhum componente faz `fetch`; o carregamento fica em `services/`.
- Formatação e cálculos de apresentação ficam em `lib/` e são funções puras.
- Acessibilidade: foco visível, contraste, navegação por teclado, `aria-*` nos controles, respeito a
  `prefers-reduced-motion`.
- Responsivo de 375 px a 1440 px; no celular a navegação vira uma barra inferior.

### Dependências

React, TypeScript estrito, Vite, Tailwind CSS 4, Radix UI, Lucide, ECharts, TanStack Query, Zod e React Router.
Componentes de UI seguem o padrão shadcn/ui (primitivas Radix + classes locais), sem biblioteca de tema pronta.

## 5. Execução

```bash
# API (mesma origem do build em produção)
uv run python -m src.api

# frontend em desenvolvimento, com proxy /api para 127.0.0.1:8000
cd frontend
npx --yes pnpm@10 install
npx --yes pnpm@10 dev

# testes e build
uv run pytest tests/api -q
uv run mypy --strict src/api
cd frontend
npx --yes pnpm@10 typecheck
npx --yes pnpm@10 test
npx --yes pnpm@10 build
npx --yes pnpm@10 e2e
```

Em produção, `uv run python -m src.api` serve `frontend/dist` na mesma origem depois do build. O acesso privado é feito
com Tailscale Serve, nunca Funnel. `vite preview` não é o servidor de produção.

## 6. Testes

- `tests/api/test_api.py`: contratos, consistência, estados vazios, ausência de rotas de escrita.
- `frontend/src/**/*.test.ts(x)`: funções puras e componentes.
- `frontend/e2e/`: Playwright contra API local e build.
- `tests/test_frontend_contract.py`: contrato legado entre `signals.ts`, `loadSignals.ts` e schemas Python.

## 7. Decisões e limites

- **Não alterar `state`**: a API só lê `data/state` para metadados; não chama loaders de escrita.
- **Não rodar o pipeline** para preencher telas. Dados ausentes são um estado de produto.
- **Não recalcular pesquisa**: o catálogo usa os números congelados nos documentos e os Parquets de evidência.
- **Não esconder resultados negativos**: estudos inconclusivos, rejeitados e compatíveis com sorte aparecem com o mesmo
  peso visual dos promissores.
- **Não mostrar `COMPRAR`**: a evidência atual não valida nenhuma moeda; a UI mostra observação, não recomendação.

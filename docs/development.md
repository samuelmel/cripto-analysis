# Desenvolvimento

Como testar, verificar tipos e mudar o projeto sem quebrar as regras que o sustentam.

## Regras do projeto

As regras completas estão em [CLAUDE.md](../CLAUDE.md). Código que viola uma delas não entra em commit. Em resumo:

1. **I/O separado da lógica.** Regras de negócio são funções puras em `src/transformers/`: não acessam rede, disco, relógio, variáveis de ambiente nem estado global. Rede fica em `extractors/` (só em `fetch`) e `notifiers/`, disco em `loaders/`, e o resto nos entrypoints. "Hoje" é sempre um parâmetro injetado.
2. **Tipagem estrita.** Python com anotações completas, `from __future__ import annotations` e aprovado em `mypy --strict`. `Any` só no payload bruto de `fetch`. TypeScript com `strict` e `noUncheckedIndexedAccess`, sem `any` nem `@ts-ignore`.
3. **Parquet em todas as camadas.** Nada de CSV ou JSON como armazenamento. A saída do painel usa compressão snappy, com escrita atômica (`.tmp` → `replace`) feita só por um loader. Se o pipeline falhar, o arquivo anterior fica intacto.
4. **Schema sincronizado.** Mudar uma coluna de `daily_signals.parquet` exige atualizar o tipo em `frontend/src/types/signals.ts` no mesmo commit.

## Comandos

```bash
uv sync --locked                       # dependências Python, incluindo as de desenvolvimento
uv run pytest -q                       # testes (sem rede)
uv run mypy --strict src/ mcp_server.py run.py  # tipagem estrita do Python
uv run run.py                          # API + Vite + navegador
uv run run.py --prod                   # build servido pela API em :8000
uv run python -m src.api               # somente a API

cd frontend
npx --yes pnpm@10 install              # dependências do painel
npx --yes pnpm@10 typecheck            # tipagem do app e das configs
npx --yes pnpm@10 test                 # testes unitários (Vitest)
npx --yes pnpm@10 build                # typecheck + build em frontend/dist
npx --yes pnpm@10 e2e                  # smoke Playwright (API + build)
```

O workflow `.github/workflows/ci.yml` roda `uv lock --check`, `uv sync --locked`, `mypy --strict`, `pytest` e, no
frontend, `pnpm install --frozen-lockfile`, `typecheck`, `test` e `build` a cada push na `main` e em pull requests. Os
testes de integração da API que dependem dos Parquets publicados são ignorados no CI, onde esses artefatos não são
versionados. O `daily.yml` continua sendo só o pipeline diário.

## Testes

- **Sem rede.** Um teste que tentar abrir conexão falha (`tests/conftest.py`).
- **O que cobrem:** a fronteira da SMA 200, o filtro do BTC, o STOP, posições encerradas, o pipeline `--offline`, API indisponível, timeout, resposta incompleta, dado desatualizado, a seleção (filtros, score, classificação e invariantes do aporte), a mensagem do Telegram (conteúdo, divisão, segredos), a previsão e o laboratório.

| Arquivo | Tema |
|---|---|
| `test_strategy.py` | Regra SMA 200, alertas e regras de venda |
| `test_selection.py` | Seleção, score, aporte e contrato da recomendação |
| `test_data_quality.py` | Auditoria dos candles, disponibilidade e universo |
| `test_extractors.py`, `test_http.py` | Adaptadores, hosts permitidos, timeout e retry |
| `test_notifications.py` | Formatação, validação e envio da mensagem |
| `test_forecast.py`, `test_lab.py` | Previsão walk-forward e laboratório de estratégias |
| `test_pipeline.py` | Pipeline de ponta a ponta, offline |
| `test_regimes.py` | Regimes de mercado: causalidade, dados ausentes, reprodutibilidade, integração e contrato com o frontend |
| `test_engine.py` | Motor de pesos: guarda de exposição, caixa parado, moedas sem preço |
| `test_loaders.py` | Escrita atômica, snappy, snapshots, upsert idempotente e consistência das duas definições do filtro do BTC |
| `test_frontend_contract.py` | Contrato do painel: todo campo dos tipos TypeScript existe no schema Python e o leitor só consome campos declarados |
| `test_regime_policy.py` | Fase 5 (pesquisa): políticas por regime, custos de transição, baselines, bootstrap, registro de experimentos e isolamento da produção |
| `tests/api/test_api.py` | API somente leitura: consistência da execução, ativos, pesquisa, carteiras indisponíveis, status e ausência de rotas de escrita. Ignorado quando os Parquets publicados não existem. |

## Mudanças comuns

### Ajustar um parâmetro

Todos ficam em `src/config.py`. A lista completa está em [strategies.md](strategies.md#4-parâmetros). Depois de mudar, recalcule sem baixar nada:

```bash
uv run python -m src.pipeline --offline
```

> [!WARNING]
> Pesos e limiares da seleção foram fixados **antes** do período de teste. Ajustá-los olhando para o resultado do teste invalida o teste. Use treino e validação (`research/selection_study.py`) para comparar alternativas.

### Incluir ou excluir uma moeda

- **Incluir:** acrescente o par em `UNIVERSE` (`"XYZ/USDT": "<id no CoinGecko>"`) e rode o pipeline online para baixar o histórico. Ela só é analisada depois de ter `MIN_HISTORY_DAYS` (365) candles.
- **Excluir da análise:** use `EXCLUDED_BASES`, com o motivo, ou tire o par de `UNIVERSE`.
- **Excluir só da compra:** use `BUY_BLOCKLIST`.

### Mudar uma coluna publicada

1. Altere o schema no transformer (`SELECTION_SCHEMA`, `ALLOCATION_SCHEMA` ou o contrato em `recommendation.py`).
2. Atualize o tipo em `frontend/src/types/signals.ts` e a validação em `frontend/src/data/loadSignals.ts`.
3. Rode `pytest`, `mypy --strict` e `typecheck` antes do commit.

## Frontend

- **Stack:** React 19, TypeScript estrito, Vite, Tailwind CSS 4, Radix UI, Lucide, ECharts, TanStack Query, Zod e React Router. O painel consome a API em `/api/v1`; `hyparquet` permanece apenas para o contrato legado de `loadSignals.ts`.
- **Organização:** componentes não fazem `fetch`. O carregamento fica em `frontend/src/services/` (cliente HTTP + hooks TanStack Query) e os contratos são validados com Zod em `frontend/src/schemas/api.ts`. Formatação e cálculos de apresentação são funções puras em `frontend/src/lib/`.
- **Rotas:** `HashRouter` com Visão geral, Carteiras, Pesquisa, Mercado e Metodologia. A API serve `frontend/dist` na mesma origem em produção.
- **Contrato com o backend:** todo campo que um tipo de `frontend/src/types/signals.ts` declara precisa existir no schema Python que gera o arquivo, e o leitor só consome campos declarados (`tests/test_frontend_contract.py`).
- **Design:** tokens, componentes e regras visuais estão em [frontend/DESIGN.md](../frontend/DESIGN.md); a arquitetura de dados e endpoints está em [frontend-architecture.md](frontend-architecture.md).

## Arquivos que não vão para o Git

Definidos em [`.gitignore`](../.gitignore) e [`frontend/.gitignore`](../frontend/.gitignore): `data/`, `logs/`, `frontend/public/*.parquet`, `frontend/node_modules/`, `frontend/dist/`, `frontend/test-results/`, `frontend/playwright-report/`, `frontend/package-lock.json`, `.venv/`, `.env` e `.env.*`, arquivos `*.tmp` e caches do Python. Nunca versione tokens nem chaves de API.

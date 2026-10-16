# Código e arquivos legados

O que sobrou da primeira arquitetura (scripts soltos na raiz) e o que fazer com cada item. Verificado no repositório em 16/10/2026. Nada aqui é usado pelo pipeline atual (`src/pipeline.py`).

## Scripts antigos apagados na árvore de trabalho (ainda rastreados no Git)

`extract_binance_vision.py`, `extract_historical.py`, `extract_market_context.py`, `feature_engineering.py`, `signal_analyzer.py`, `run_monthly.cmd` e o `architecture.md` da raiz (o atual está em `docs/architecture.md`) aparecem como **excluídos e não commitados** em `git status`. Foram removidos pelo usuário e **preservados no histórico do Git**: nenhuma operação desta auditoria os restaurou nem confirmou a exclusão. O que existia neles:

| Arquivo | Papel antigo | Substituído por |
|---|---|---|
| `extract_historical.py`, `extract_binance_vision.py` | Coleta histórica (REST e ZIPs mensais do Binance Vision) | `src/extractors/binance_adapter.py` + `src/loaders/market_store.py` |
| `extract_market_context.py` | Fear & Greed, funding rate, CoinGecko | `src/extractors/fng_adapter.py`, `coingecko_adapter.py` (o funding rate **não** foi migrado) |
| `feature_engineering.py`, `signal_analyzer.py` | Indicadores e sinais em CSV | `src/transformers/anomaly_detector.py`, `selection.py` |
| `run_monthly.cmd` | Agendamento mensal | `run_daily.cmd` e `.github/workflows/daily.yml` |

> [!NOTE]
> Os dados baixados por esses scripts continuam em `data/raw/` (`ohlcv_vision`, `funding_rate`, `fear_greed`, `coingecko`, fora do Git). **Nenhum módulo atual lê `data/raw/`**: a base usada é `data/market/`. Os arquivos de `data/raw/` não foram validados nesta auditoria e não entram em nenhum resultado.

## Módulos órfãos ainda rastreados na raiz

| Arquivo | Situação | Recomendação |
|---|---|---|
| `storage.py` | Só era importado pelos `extract_*.py` apagados; escrita Parquet zstd sem as garantias de `src/loaders/parquet_loader.py` | Remover junto com os scripts antigos |
| `market_metrics.py` | Referencia `signal_analyzer.load_closes` (apagado); sem uso | Remover, ou migrar para `src/` com testes se as métricas forem úteis |

Não foram removidos: a decisão de apagar código rastreado é do dono do repositório.

## Já removido nesta auditoria

- `requirements.txt`: listava `ccxt`, `pandas` e `pyarrow`, desatualizado em relação ao `pyproject.toml` (sem `mcp`) e não referenciado por nenhum script nem workflow. A instalação é `uv sync --locked`.
- Dependências `ccxt` e `aiohttp` do `pyproject.toml`: nenhuma linha do código as importa (os extratores usam `urllib`). `numpy`, que o código importa diretamente, passou a ser declarada. `uv.lock` regenerado: 68 para 50 pacotes.

## Motores e nomes duplicados

Há **dois motores de backtest** e um nome de estratégia que existe nos dois com simulações diferentes (`COMPRAR_E_SEGURAR`). Ver [AUDIT.md](AUDIT.md), item F2, e o catálogo em `src/transformers/strategy_catalog.py`.

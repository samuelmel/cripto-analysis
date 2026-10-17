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

---

## Inventário feito na Fase 0 do remoto (antes da remoção dos scripts)

> [!NOTE]
> Os scripts da raiz listados abaixo (`extract_*.py`, `feature_engineering.py`, `signal_analyzer.py`, `run_monthly.cmd`, `storage.py` aparece como órfão) foram **removidos** pelo dono do repositório (commit de remoção do legado), então `tests/test_legacy.py` e a verificação do `requirements.txt` no CI deixaram de existir. O inventário fica como registro do que eram.

# Inventário dos scripts legados da raiz

Levantado na Fase 0 do roadmap quantitativo (commit de referência `abcccd6`). Nenhum arquivo foi apagado: só foram
corrigidas as contradições com a regra atual e com o CLAUDE.md. Remoção fica para quando houver substituto
documentado e testado.

Consumidores verificados com `grep` em todo o repositório (Python, TypeScript, `.cmd`, workflows, Markdown).

| Arquivo | O que faz | Quem usa | Estado | Decisão (Fase 0) |
|---|---|---|---|---|
| `run_daily.cmd` | Agendador do Windows → `python -m src.pipeline` | usuário (Agendador de Tarefas), README | **vigente** | mantido |
| `run_monthly.cmd` | Agendador do Windows → `extract_historical.py` + `signal_analyzer.py` sobre `data/raw` | usuário (Agendador), nenhum código | legado | comentários corrigidos: o pânico é aviso, não compra; saída passou de CSV para Parquet (`data/signals/panic_YYYY-MM.parquet`) |
| `signal_analyzer.py` | Aplica a antiga regra de pânico (z < −2,5 e RSI < 30) à base `data/raw` | `run_monthly.cmd` | legado, **contradizia** a regra atual | agora é "alerta informativo, NÃO é recomendação de compra"; `find_signals` → `find_panic_alerts`; "Grau de Confiança" (nome enganoso) → `esticamento_sma200_pct`; `--out` só aceita `.parquet` (CLAUDE.md §3). Teste: `tests/test_legacy.py` |
| `feature_engineering.py` | Indicadores da base `data/raw` | `signal_analyzer.py` | legado | saída passou de CSV para Parquet (`data/features/features.parquet`); `--parquet` virou opção obsoleta e ignorada |
| `extract_historical.py` | Extração CCXT assíncrona para `data/raw/ohlcv` | `run_monthly.cmd`, `architecture.md` | legado | mantido; é o único usuário de `ccxt` |
| `extract_binance_vision.py` | ZIPs mensais do data.binance.vision (com SHA-256) para `data/raw/ohlcv_vision` | `architecture.md` | legado, **substituído para pesquisa na Fase 1** | mantido. O substituto é `src/extractors/binance_archive.py` + `python -m src.archive`: checksum obrigatório (o legado aceitava ZIP sem checksum), diários além dos mensais, manifesto, idempotência por ETag, testes. Candidato a remoção quando o usuário confirmar que não agenda o legado |
| `extract_market_context.py` | F&G, funding e CoinGecko para `data/raw` | `architecture.md` | legado | mantido; é o único usuário de `aiohttp` |
| `storage.py` | Escrita Parquet atômica + partição mensal para os `extract_*.py` | `extract_binance_vision.py`, `extract_market_context.py` | legado | mantido |
| `market_metrics.py` | Métricas por ativo (retorno do mês, 3 meses, 1 ano) | nenhum consumidor encontrado | legado, órfão | mantido; candidato a remoção quando houver decisão |
| `architecture.md` | Arquitetura da camada `data/raw` | README não o referencia | legado, **contradizia** a regra atual (dizia que COMPRAR = pânico) | marcado como documento histórico; trecho obsoleto substituído por remissão ao README |
| `requirements.txt` | Lista de dependências para pip | nenhum consumidor (o workflow usa `uv sync --locked`) | **divergia** do `pyproject.toml` (só ccxt, pandas, pyarrow) | agora é gerado do `uv.lock` (`uv export ... --no-hashes`); o CI falha se divergir |

## Dependências

| Pacote | Uso direto | Observação |
|---|---|---|
| pandas, pyarrow | `src/`, `research/`, scripts da raiz | núcleo da arquitetura |
| numpy | `src/transformers/*`, `research/`, testes | era usada sem estar declarada (vinha como dependência do pandas); declarada `numpy>=2.0` na Fase 0 |
| mcp | `mcp_server.py` | entrypoint opcional (Claude Desktop) |
| ccxt | só `extract_historical.py` (legado) | mantida enquanto o legado existir |
| aiohttp | só `extract_market_context.py` (legado) | mantida enquanto o legado existir |

`ccxt` e `aiohttp` só servem ao legado. Removê-las exige primeiro migrar ou aposentar esses scripts; não foi feito
na Fase 0 para não quebrar o `run_monthly.cmd` de quem o agenda.

## Motores de backtest legados (Fase 2)

O pipeline publica tudo pelo motor único (`src/transformers/backtest_engine.py`). Os motores antigos não foram
apagados porque (1) reproduzem os resultados anteriores à Fase 2, que continuam citados no README como históricos, e
(2) o laboratório de `research/` ainda depende deles. Cada um tem o docstring marcado como LEGADO.

| Função | Premissas antigas | Quem ainda usa | Teste que preserva o resultado antigo |
|---|---|---|---|
| `trade_simulator.run_portfolio`, `evaluate_portfolio`, `performance_summary` | execução ao fechamento do sinal; peso igual rebalanceado todo dia sem custo; só taxa; perde o movimento através de candle ausente | `research/lab.py`, `strategy_lab.py`, `strategy_comparison.py` | `tests/test_legacy_engines.py` (`performance`) |
| `trade_simulator.backtest` | entrada e saída ao fechamento do sinal, retorno sem custos | nenhum (o pipeline usa `portfolio_backtest.trend_trades`) | `tests/test_legacy_engines.py` (`backtest`) |
| `selection_backtest.run_weighted`, `evaluate_selection_legacy`, `metrics_row` | podia passar de 100% de exposição com a banda; ativo deslistado mantido pelo último preço | `research/selection_study.py` | `tests/test_legacy_engines.py` (`selection_backtest`) |

`trade_simulator.simulate` **não** é legado: aconselha as posições reais do usuário (o preço é o que ele pagou).
Remoção dos motores antigos: depois que os resultados antigos deixarem de ser citados.

**Fase 3.** As estratégias e grades do laboratório (`strategy_comparison.py`, `strategy_lab.py`/`lab.py`) foram
reavaliadas no motor único por `research/validation_study.py` (walk-forward, bootstrap em blocos, Holm). Os sinais
`bollinger_reversion`, `rsi_oversold` e `dip_in_uptrend` mudaram para `src/transformers/strategies.py` (o
laboratório e o estudo de comparação os reexportam com o mesmo nome; resultados idênticos). Os scripts antigos
continuam rodando no motor legado, como registro histórico: para decidir, vale a validação da Fase 3.
`selection_backtest.evidence` (comparação de Sharpe pontuais) continua disponível, mas o pipeline passou a usar
`evidence_with_uncertainty`.

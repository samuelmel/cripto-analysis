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

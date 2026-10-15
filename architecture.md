# crypto-analyzer — Arquitetura de Dados

## Objetivo
Extrair até 10 anos de OHLCV (open, high, low, close, volume) de criptomoedas via API pública gratuita e armazenar em formato analítico eficiente para backtests, features e dashboards.

## Fluxo
```
Binance (REST pública) ──CCXT async──▶ extract_historical.py ──▶ data/raw/ohlcv (Parquet, Hive)
                                                                   │
                                                                   ▼
                                              pandas / pyarrow / DuckDB / Polars (leitura com pruning)
```

## Decisão de armazenamento: Parquet, não JSON

| Critério | JSON | Parquet (zstd) |
|---|---|---|
| Layout | Linha, texto | Colunar, binário tipado |
| Tamanho por candle (estimativa) | ~110–130 B | ~15–25 B |
| Leitura parcial (só `close`) | Lê e parseia tudo | Lê só a coluna |
| Filtro por período | Varredura total | Partition pruning (`year`/`month`) + estatísticas min/max por row group |
| RAM | Arquivo inteiro em memória para parsear | Leitura em streaming por row group |
| Schema/tipos | Implícitos, strings | `timestamp[ms, UTC]`, `float64` garantidos |

JSON para 200 GB é anti-padrão: inflaria disco ~5–8×, exige parse completo em CPU e não permite projeção de colunas nem pruning.

## Viabilidade de volume (por símbolo, 10 anos)

| Timeframe | Linhas | Parquet zstd (est.) | JSON (est.) |
|---|---|---|---|
| 1d | ~3,7 mil | < 1 MB | < 1 MB |
| 1h | ~87,6 mil | ~2 MB | ~10 MB |
| 1m | ~5,26 mi | ~80–130 MB | ~600 MB |

- 200 GB em JSON (~350 pares em 1m) cabem em algo entre ~30 e 45 GB em Parquet.
- Na Binance, os pares spot mais antigos começam em 2017 (BTC/USDT: ago/2017). Na prática, "10 anos" retorna o que existe; o script avança automaticamente até a primeira vela disponível.
- Custo de requisições em 1m: ~5.300 chamadas/símbolo (1000 velas/chamada). Com o rate limiter do CCXT, levará horas por símbolo; rodar em lotes.

## Layout em disco (Hive partitioning)
```
data/raw/ohlcv/
  exchange=binance/
    timeframe=1h/
      symbol=BTC_USDT/
        year=2024/
          month=01/
            part-<first_ts>-<last_ts>.parquet
```
- Partição por `year/month` mantém arquivos entre ~1 e 10 MB em 1m (bom para pruning, evita "small files" excessivos).
- O nome do arquivo carrega o intervalo de timestamps: a retomada lê só os nomes, sem abrir Parquet.
- Escrita atômica (`.tmp` → rename): execução interrompida nunca deixa partição corrompida.

## Extração
- `ccxt.async_support` + `asyncio.Semaphore` (`--concurrency`) para paralelizar símbolos.
- `enableRateLimit` do CCXT controla o ritmo por exchange; backoff exponencial em `RateLimitExceeded`/`DDoSProtection`/erros de rede.
- Vela ainda aberta é descartada para não persistir dados incompletos.
- Idempotente: rodar de novo continua do último timestamp salvo.
- Logs em stdout e `logs/extract_historical.log`.

## Uso
Dependências gerenciadas com [uv](https://docs.astral.sh/uv/) (`pyproject.toml` + `uv.lock`):
```bash
uv sync
uv run extract_historical.py --symbols BTC/USDT ETH/USDT SOL/USDT --timeframe 1h --years 10
```
Adicionar dependência: `uv add <pacote>` (atualiza `pyproject.toml` e `uv.lock`).

Leitura:
```python
import pyarrow.dataset as ds
dset = ds.dataset("data/raw/ohlcv", partitioning="hive")
df = dset.to_table(
    columns=["timestamp", "close"],
    filter=(ds.field("symbol") == "BTC_USDT") & (ds.field("year") >= 2023),
).to_pandas()
```

## Fontes adicionais

| Script / subcomando | Fonte | Dados | Histórico | Chave |
|---|---|---|---|---|
| `extract_binance_vision.py` | data.binance.vision | Klines spot + `quote_volume`, `trades`, `taker_buy_*` (ZIP mensal, SHA-256 verificado) | Desde a listagem do par | Não |
| `extract_market_context.py fng` | api.alternative.me | Crypto Fear & Greed Index diário | Completo | Não |
| `extract_market_context.py funding` | fapi.binance.com | Funding rate de perpétuos USDⓈ-M (a cada 8h) + mark price | Desde 2019-09 | Não |
| `extract_market_context.py coingecko` | api.coingecko.com | Preço, market cap e volume total agregados | 365 dias (plano Demo) | Demo gratuita (`COINGECKO_API_KEY`) |

- O Binance Vision é a via preferida para backfill longo: 1 ZIP por mês em vez de milhares de requisições paginadas. A REST (`extract_historical.py`) cobre o mês corrente.
- Spot no Binance Vision usa timestamps em microssegundos a partir de 2025-01-01; o parser normaliza para ms.
- Open interest e long/short ratio da Binance só têm os últimos 30 dias na REST; ficaram fora.

```bash
uv run extract_binance_vision.py --symbols BTCUSDT ETHUSDT --timeframe 1h --years 10
uv run extract_market_context.py fng
uv run extract_market_context.py funding --symbols BTCUSDT ETHUSDT
COINGECKO_API_KEY=... uv run extract_market_context.py coingecko --coins bitcoin ethereum
```

Layout:
```
data/raw/ohlcv_vision/exchange=binance/timeframe=<tf>/symbol=<SYMBOL>/year=YYYY/month=MM/data.parquet
data/raw/fear_greed/data.parquet
data/raw/funding_rate/symbol=<SYMBOL>/year=YYYY/month=MM/data.parquet
data/raw/coingecko/coin_id=<id>/data.parquet
```

## Nova arquitetura ETL (em construção)
O dashboard Streamlit foi descartado. O pipeline diário passa a viver em `src/`, com frontend React + TypeScript em `frontend/`.
```
src/
  extractors/   E — um adaptador por fonte, todos com a mesma interface (padrão Adapter)
    base_extractor.py      BaseExtractor: extract(start, end) -> DataFrame padronizado
    binance_adapter.py     BinanceAdapter (OHLCV + volume)
    coingecko_adapter.py   CoinGeckoMarketAdapter (market cap) e CoinGeckoTrendingAdapter (tendências)
    fng_adapter.py         FearGreedAdapter (Fear & Greed Index)
  transformers/ T — limpeza, junção de fontes e indicadores
  loaders/      L — persistência para o frontend
frontend/       React + TypeScript
```
### Pipeline diário (`src/pipeline.py`, agendado por `run_daily.cmd` às 21:10 BRT)
1. Extrai 250 dias de candles 1d da Binance (universo em `src/config.py`), market cap atual do CoinGecko e o Fear & Greed.
2. `anomaly_detector.detect` classifica cada ativo: **COMPRAR** (z-score < -2.5, RSI < 30, F&G < 25), **PREPARAR** (radar: z-score < -1.5 e RSI < 40) ou **NEUTRO**.
3. `daily_alerts.compare_with_previous` compara com o último dia salvo e gera `COMPRAR AGORA`, `NO RADAR` ou `SAIU DO RADAR`.
4. Salva `data/signals/history/date=YYYY-MM-DD/signals.parquet` e publica `frontend/public/daily_signals.parquet`.

CoinGecko e F&G são opcionais: se falharem, o pipeline segue (sem F&G nenhum ativo vira COMPRAR). Falha da Binance aborta sem tocar no arquivo publicado.

Formato de saída de todo extrator: chaves `timestamp` (UTC), `source`, `symbol` (`MARKET` para séries globais) + as `value_columns` declaradas pelo adaptador. `BaseExtractor.standardize` garante tipos, unicidade de (timestamp, symbol) e ordenação. Os scripts `extract_*.py` da raiz são a referência de implementação até serem migrados para os adaptadores.

## Próximos passos
- Camada `silver`: validação de gaps, deduplicação e compactação mensal das partes.
- Consulta via DuckDB direto sobre os arquivos Parquet.

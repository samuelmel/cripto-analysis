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

## Próximos passos
- Camada `silver`: validação de gaps, deduplicação e compactação mensal das partes.
- Consulta via DuckDB direto sobre os arquivos Parquet.

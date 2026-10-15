# crypto-analyzer

Monitor diário de criptomoedas por **reversão à média**. Todo dia o pipeline baixa os candles da Binance, o market cap do CoinGecko e o Fear & Greed Index. Depois classifica cada moeda e publica o resultado num painel web.

| Estágio | Regra | Significado |
|---|---|---|
| **COMPRAR** | Z-Score 90d < -2.5 **e** RSI 14 < 30 **e** Fear & Greed < 25 | Sobrevenda extrema com pânico no mercado |
| **PREPARAR** | Z-Score 90d < -1.5 **e** RSI 14 < 40 | Radar: escorregando para a zona de compra |
| **NEUTRO** | demais casos | — |

O pipeline compara cada dia com o anterior e gera alertas de virada:

- `COMPRAR AGORA`: virou COMPRAR hoje.
- `NO RADAR`: entrou em PREPARAR hoje.
- `SAIU DO RADAR`: estava no radar ou em compra e voltou a NEUTRO.

> É uma regra estatística, não previsão nem recomendação de investimento. Um ativo sobrevendido pode continuar caindo.

---

## Requisitos

- [uv](https://docs.astral.sh/uv/), que gerencia Python 3.12 e as dependências
- [Node.js](https://nodejs.org/) 20 ou mais recente (testado com 24) e npm, para o painel
- Acesso à internet. As APIs usadas são públicas e gratuitas.

## Instalação

```bash
uv sync
```

```bash
npm --prefix frontend install
```

Chave do CoinGecko (opcional): sem ela o pipeline funciona com limite de requisições menor. Para usar a chave Demo gratuita, defina `COINGECKO_API_KEY` no ambiente.

## Uso

### 1. Rodar o pipeline

Da raiz do projeto:

```bash
uv run python -m src.pipeline
```

Leva cerca de 10 segundos. Saída no terminal:

```
Ciclo 2026-10-14 · 15 ativos · F&G 53
  estágios: {'NEUTRO': 15}
```

O pipeline grava dois arquivos:

| Arquivo | Conteúdo |
|---|---|
| `frontend/public/daily_signals.parquet` | Estado atual, lido pelo painel |
| `data/signals/history/date=YYYY-MM-DD/signals.parquet` | Histórico, um arquivo por dia |

Rodar de novo no mesmo dia sobrescreve o snapshot daquele dia. Os alertas comparam com o último dia **anterior** salvo, então a primeira execução não tem com o que comparar. Se a Binance falhar, o pipeline aborta e não altera o arquivo publicado.

### 2. Abrir o painel

```bash
npm --prefix frontend run dev
```

Acesse http://localhost:5173. O painel mostra:

- o ciclo, a quantidade de ativos e o Fear & Greed atual;
- uma faixa vermelha com o que disparou hoje;
- as tabelas COMPRAR e PREPARAR, com Ativo, Preço, Z-Score, RSI e F&G.

Se aparecer "sem dados ainda", rode o pipeline primeiro.

### 3. Agendar a execução diária (Windows)

O candle diário da Binance fecha às 00:00 UTC (21:00 em Brasília). Agende para 21:10 com um único comando:

```bash
schtasks /Create /TN "crypto-analyzer diario" /SC DAILY /ST 21:10 /TR "\"D:\Downloads\pastas codigo\projeto cripto\crypto-analyzer\run_daily.cmd\""
```

Ajuste o caminho se o projeto estiver em outra pasta. O log fica em `logs/pipeline.log`.

Para testar o agendamento sem esperar o horário:

```bash
schtasks /Run /TN "crypto-analyzer diario"
```

Para remover o agendamento:

```bash
schtasks /Delete /TN "crypto-analyzer diario" /F
```

### 4. Disparar pelo Claude Desktop (opcional)

O arquivo `mcp_server.py` expõe a tool `run_crypto_pipeline`. Adicione dentro de `mcpServers` no `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "crypto-analyzer": {
      "command": "C:\\Users\\Usuario\\.local\\bin\\uv.exe",
      "args": ["run", "--directory", "D:\\Downloads\\pastas codigo\\projeto cripto\\crypto-analyzer", "mcp_server.py"]
    }
  }
}
```

## Configuração

| O quê | Onde |
|---|---|
| Moedas monitoradas (par Binance → id CoinGecko) | `src/config.py` (`UNIVERSE`) |
| Limiares de COMPRAR e PREPARAR | `src/transformers/anomaly_detector.py` (`SignalRules`) |
| Janela de candles baixada | `src/pipeline.py` (`BINANCE_LOOKBACK`, padrão 250 dias) |

## Estrutura

```
src/
  pipeline.py            orquestra: extrai → detecta → compara com ontem → salva
  config.py              universo de moedas
  extractors/            E — um adaptador por fonte, saída padronizada
    base_extractor.py      contrato comum (timestamp UTC, source, symbol + colunas de valor)
    binance_adapter.py     candles 1d (/api/v3/klines)
    coingecko_adapter.py   market cap atual (/coins/markets)
    fng_adapter.py         Fear & Greed Index (alternative.me)
  transformers/          T — regras de negócio puras, sem I/O
    anomaly_detector.py    Z-Score, RSI e estágio por ativo (vetorizado)
    daily_alerts.py        alertas de virada contra o dia anterior
  loaders/               L — escrita Parquet atômica
    parquet_loader.py      publica frontend/public/daily_signals.parquet
    history_store.py       histórico diário em data/signals/history
frontend/                React + TypeScript + Tailwind
  src/data/loadSignals.ts  lê e valida o Parquet (único ponto de I/O)
  src/components/TerminalView.tsx
mcp_server.py            tool MCP run_crypto_pipeline
run_daily.cmd            script chamado pelo Agendador de Tarefas
```

Os scripts da raiz (`extract_historical.py`, `extract_binance_vision.py`, `extract_market_context.py`, `feature_engineering.py`, `signal_analyzer.py`, `run_monthly.cmd`) são da versão anterior. O pipeline diário não usa nenhum deles. Detalhes de armazenamento e fontes em [architecture.md](architecture.md).

## Desenvolvimento

Regras do projeto em [CLAUDE.md](CLAUDE.md), em resumo:

- I/O separado das regras de negócio;
- tipagem estrita em Python e TypeScript;
- Parquet como único formato de dados.

Checagem de tipos:

```bash
uv run mypy --strict src/
```

```bash
npm --prefix frontend run typecheck
```

Build de produção do painel:

```bash
npm --prefix frontend run build
```

## Problemas comuns

| Sintoma | Causa | Solução |
|---|---|---|
| Painel mostra "sem dados ainda" | `daily_signals.parquet` ainda não foi gerado | `uv run python -m src.pipeline` |
| Nenhum alerta no primeiro dia | Não há dia anterior salvo | Normal; os alertas aparecem a partir do segundo dia |
| Market cap vazio no painel | CoinGecko falhou ou limitou requisições | O pipeline segue sem ele; defina `COINGECKO_API_KEY` |
| Nenhum ativo em COMPRAR por semanas | O F&G precisa estar abaixo de 25 | Esperado: a regra só dispara em pânico de mercado |
| `HTTP 451` da Binance | Bloqueio regional da api.binance.com | Rodar de uma região onde a Binance global atende |

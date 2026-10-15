# crypto-analyzer

Monitor diário de criptomoedas por **reversão à média**. O projeto faz quatro coisas:

- **Base histórica:** guarda todos os candles diários desde 2017 e o Fear & Greed desde 2018.
- **Atualização diária:** todo dia baixa só o que falta e classifica cada moeda.
- **Posições:** acompanha as moedas que você comprou e diz quando vender.
- **Backtest:** testa as regras em todo o histórico para mostrar se elas funcionam.

> Isto é uma ferramenta estatística, não previsão nem recomendação de investimento. Leia a seção [O que o backtest mostra](#o-que-o-backtest-mostra) antes de usar os sinais para comprar.

## Como funciona

### Estágios de compra

| Estágio | Regra | Significado |
|---|---|---|
| **COMPRAR** | Z-Score 90d < -2.5 **e** RSI 14 < 30 **e** Fear & Greed < 25 | Sobrevenda extrema com pânico no mercado |
| **PREPARAR** | Z-Score 90d < -1.5 **e** RSI 14 < 40 | Radar: escorregando para a zona de compra |
| **NEUTRO** | demais casos | — |

Alertas de virada em relação ao dia anterior:

- `COMPRAR AGORA`: virou COMPRAR hoje.
- `NO RADAR`: entrou em PREPARAR hoje.
- `SAIU DO RADAR`: estava no radar e voltou a NEUTRO.

### Regras de venda

Valem para as suas posições e para o backtest. Quando mais de uma dispara no mesmo dia, vale a primeira da tabela:

| Motivo | Regra | Objetivo |
|---|---|---|
| **STOP** | Perda de 20% sobre o preço de compra | Cortar antes de cair mais |
| **PROTEGER LUCRO** | Subiu 15% ou mais e recuou 10% a partir do pico | Travar o lucro |
| **ALVO** | Comprou abaixo da média de 90 dias e o preço voltou a ela, com lucro | Reversão completa |
| **SOBRECOMPRADO** | RSI ≥ 70 com lucro | Realizar na euforia |
| **TEMPO** | 180 dias sem nenhuma das anteriores | Liberar o capital |

O painel mostra, para cada posição, SEGURAR ou VENDER com o motivo e a data em que a regra disparou. Também mostra os preços de referência: stop, trava de lucro e alvo.

## Requisitos

- [uv](https://docs.astral.sh/uv/), que gerencia Python 3.12 e as dependências
- [Node.js](https://nodejs.org/) 20 ou mais recente (testado com 24) e npm, para o painel
- Acesso à internet. As APIs (Binance, CoinGecko e alternative.me) são públicas e gratuitas.

## Instalação

```bash
uv sync
```

```bash
npm --prefix frontend install
```

Chave do CoinGecko (opcional): sem ela o pipeline funciona com limite de requisições menor. Para usar a chave Demo gratuita, defina `COINGECKO_API_KEY` no ambiente.

## Uso

### 1. Montar a base histórica e analisar

Da raiz do projeto:

```bash
uv run python -m src.pipeline
```

A primeira execução baixa todo o histórico, em cerca de 40 segundos para as 15 moedas. As seguintes baixam só os dias que faltam. Exemplo de saída:

```
Ciclo 2026-10-14 · 15 ativos · F&G 53
  estágios: {'NEUTRO': 15}
  backtest referência semanal: 5872 operações · acerto 69% · retorno médio +1.7% · mediana +5.1%
  backtest sinal COMPRAR: 86 operações · acerto 55% · retorno médio -5.1% · mediana +2.0%
```

| Modo | Comando |
|---|---|
| Normal: atualiza a base e analisa | `uv run python -m src.pipeline` |
| Só reanalisa a base local, sem internet | `uv run python -m src.pipeline --offline` |
| Baixa todo o histórico de novo | `uv run python -m src.pipeline --rebuild` |

Se a Binance falhar, o pipeline aborta e não altera o que já foi publicado.

### 2. Abrir o painel

```bash
npm --prefix frontend run dev
```

Acesse o endereço que aparece na linha `Local:` do terminal, normalmente http://localhost:5173. O painel só funciona enquanto esse comando estiver rodando. Ele mostra:

- **Hoje:** o que fazer, em uma frase, e o humor do mercado (Fear & Greed).
- **Suas posições:** uma ficha por compra com Segurar/Vender, o motivo em português simples, o resultado e os preços de limite de perda e de garantia de lucro.
- **Todas as moedas:** da mais barata em relação ao normal para a mais cara, com a distância da média de 90 dias. Clique numa para ver o gráfico.
- **Gráfico da moeda:** preço e média de 90 dias desde o início dos dados, sinais de compra passados, vendas simuladas com o resultado e as suas compras. Passe o mouse para ler o preço de cada dia.
- **A regra de compra funciona?:** a resposta direta e a comparação com comprar sem critério.
- **Como funciona:** as regras de compra e venda explicadas.

As decisões visuais (cores, tipografia, componentes) estão em [frontend/DESIGN.md](frontend/DESIGN.md).

Se aparecer "sem dados ainda", rode o pipeline primeiro.

### 3. Registrar suas compras e vendas

```bash
uv run python -m src.positions add BTC/USDT 83000 0.01
```

Esse comando registra a compra de 0,01 BTC a 83.000 USDT hoje. Para uma compra em outra data, use `--date 2026-10-01`.

```bash
uv run python -m src.positions list
```

```bash
uv run python -m src.positions close <id> 95000
```

```bash
uv run python -m src.positions remove <id>
```

`close` registra a venda e `remove` apaga um registro errado. Cada comando atualiza o painel na hora, sem internet; recarregue a página. As posições ficam em `data/positions/positions.parquet`. A moeda precisa estar em `src/config.py`.

### 4. Agendar a execução diária (Windows)

O candle diário da Binance fecha às 00:00 UTC (21:00 em Brasília). Agende para 21:10:

```bash
schtasks /Create /TN "crypto-analyzer diario" /SC DAILY /ST 21:10 /TR "\"D:\Downloads\pastas codigo\projeto cripto\crypto-analyzer\run_daily.cmd\""
```

Ajuste o caminho se o projeto estiver em outra pasta. O log fica em `logs/pipeline.log`.

Para testar sem esperar o horário:

```bash
schtasks /Run /TN "crypto-analyzer diario"
```

Para remover o agendamento:

```bash
schtasks /Delete /TN "crypto-analyzer diario" /F
```

### 5. Disparar pelo Claude Desktop (opcional)

O `mcp_server.py` expõe a tool `run_crypto_pipeline`. Adicione dentro de `mcpServers` no `claude_desktop_config.json`:

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

## O que o backtest mostra

O backtest simula cada sinal COMPRAR desde 2017 com as regras de venda acima. Para dizer se o sinal tem vantagem, compara com uma **referência**: comprar toda semana, em todas as moedas, sem critério, com as mesmas regras de venda.

Resultado com dados até 2026-10-14:

| | Operações | Acerto | Retorno médio | Mediana |
|---|---|---|---|---|
| Sinal COMPRAR | 86 | 55% | **-5,1%** | +2,0% |
| Referência semanal | 5.872 | 69% | **+1,7%** | +5,1% |

**O sinal de pânico rendeu menos do que comprar sem critério.**

- **Por quê:** 38 das 86 operações bateram no STOP de -20%, em média 3 semanas após a compra. Em mercados de baixa (2018, 2022), o pânico extremo costuma continuar por semanas: o sinal compra a "faca caindo".
- **Variações testadas:** esperar o repique, comprar só com o BTC acima da média de 200 dias e stops mais largos ou mais curtos. Escolhi a melhor no período 2017–2022 e conferi em 2023–2026, dados que a escolha não viu. Nenhuma ficou consistentemente positiva.
- **Onde vai melhor:** em BTC/ETH o sinal se sai melhor (-1,8% de média) do que nas altcoins (-6,2%).

Use COMPRAR como **alerta de pânico** para olhar o mercado com atenção, não como ordem automática de compra. O painel mostra essa comparação sempre atualizada. Se o mercado mudar e o sinal passar a superar a referência, o aviso muda sozinho.

## Configuração

| O quê | Onde |
|---|---|
| Moedas monitoradas (par Binance → id CoinGecko) | `src/config.py` (`UNIVERSE`) |
| Limiares de COMPRAR e PREPARAR | `src/transformers/anomaly_detector.py` (`SignalRules`) |
| Regras de venda | `src/transformers/trade_simulator.py` (`ExitRules`) |
| Janela entre episódios de COMPRAR | `src/transformers/trade_simulator.py` (`EntryRules.cooldown`, 14 dias) |

Depois de mudar uma regra, rode `uv run python -m src.pipeline --offline` para recalcular tudo sem baixar nada.

## Estrutura

```
src/
  pipeline.py              orquestra: atualiza base → analisa → compara com ontem → publica
  positions.py             CLI das suas posições
  config.py                universo de moedas
  extractors/              E — um adaptador por fonte, saída padronizada
    binance_adapter.py       candles 1d (/api/v3/klines)
    coingecko_adapter.py     market cap atual (/coins/markets)
    fng_adapter.py           Fear & Greed Index (alternative.me)
  transformers/            T — regras de negócio puras, sem I/O
    anomaly_detector.py      Z-Score, RSI e estágio de cada dia (vetorizado)
    daily_alerts.py          alertas de virada contra o dia anterior
    trade_simulator.py       regras de venda, backtest e referência
    position_advisor.py      SEGURAR / VENDER das suas posições
  loaders/                 L — Parquet com escrita atômica
    market_store.py          base histórica (data/market)
    history_store.py         snapshot diário (data/signals/history)
    positions_store.py       suas posições (data/positions)
    parquet_loader.py        publicação para o painel
frontend/                  React + TypeScript + Tailwind
  DESIGN.md                contrato visual: tokens, tipografia, componentes, o que evitar
  src/data/                leitura e validação do Parquet + cálculos e textos puros do painel
  src/components/          Dashboard, Sections, PriceChart (lightweight-charts), ui (primitivas)
mcp_server.py              tool MCP run_crypto_pipeline
run_daily.cmd              script chamado pelo Agendador de Tarefas
```

Arquivos publicados em `frontend/public/` (gerados, fora do Git):

| Arquivo | Conteúdo |
|---|---|
| `daily_signals.parquet` | Estágio e alertas do dia |
| `history.parquet` | Preço, indicadores e estágio de todos os dias |
| `backtest.parquet` | Cada operação simulada (sinal e referência) |
| `positions.parquet` | Suas posições com a recomendação |

## Desenvolvimento

Regras do projeto em [CLAUDE.md](CLAUDE.md), em resumo:

- I/O separado das regras de negócio;
- tipagem estrita em Python e TypeScript;
- Parquet como único formato de dados.

```bash
uv run mypy --strict src/
```

```bash
npm --prefix frontend run typecheck
```

```bash
npm --prefix frontend run build
```

## Problemas comuns

| Sintoma | Causa | Solução |
|---|---|---|
| Painel mostra "sem dados ainda" | O pipeline ainda não rodou | `uv run python -m src.pipeline` |
| localhost não abre ou mostra outra coisa | O painel não está rodando, ou subiu em outra porta | Rode `npm --prefix frontend run dev` e use o endereço da linha `Local:` |
| Posição nova não aparece | Página em cache | Recarregue a página |
| Nenhum alerta no primeiro dia | Não há dia anterior salvo | Normal; aparecem a partir do segundo dia |
| Nenhum ativo em COMPRAR por semanas | O F&G precisa estar abaixo de 25 | Esperado: a regra só dispara em pânico de mercado |
| `HTTP 451` da Binance | Bloqueio regional da api.binance.com | Rodar de uma região onde a Binance global atende |

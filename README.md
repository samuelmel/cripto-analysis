# crypto-analyzer

Monitor diário de criptomoedas que segue a **tendência** de Bitcoin e Ethereum. O projeto faz quatro coisas:

- **Base histórica:** guarda todos os candles diários desde 2017 e o Fear & Greed desde 2018.
- **Atualização diária:** todo dia baixa só o que falta e diz, para cada moeda, se está em tendência de alta.
- **Posições:** acompanha as moedas que você comprou e diz quando vender.
- **Backtest:** simula a regra em todo o histórico, em carteira, e compara com simplesmente comprar e segurar.

> Isto é uma ferramenta estatística, não previsão nem recomendação de investimento. Leia a seção [O que o backtest mostra](#o-que-o-backtest-mostra), incluindo as limitações, antes de usar os sinais para comprar.

## Como funciona

### Regra de compra e venda

Vale para **BTC e ETH** (configurável em `src/config.py`, `RECOMMENDED`). As outras 13 moedas continuam monitoradas, mas sem recomendação.

| Situação | Regra | O que fazer |
|---|---|---|
| **COMPRAR** | Fechamento acima da média de 200 dias (SMA 200) da moeda **e** o BTC também acima da SMA 200 dele | Comprar, ou segurar se já tem |
| **PREPARAR** | Fechamento até 3% abaixo da SMA 200 da moeda e subindo há 5 dias (e BTC em alta) | Radar: perto de cruzar |
| **NEUTRO** | Demais casos | Ficar de fora |

Alertas de virada em relação ao dia anterior:

- `COMPRAR AGORA`: virou COMPRAR hoje.
- `VENDER AGORA`: estava em COMPRAR e deixou de estar.
- `NO RADAR`: entrou em PREPARAR hoje.
- `SAIU DO RADAR`: estava em PREPARAR e voltou a NEUTRO.

**Pânico** (z-score de 90 dias < -2,5, RSI < 30 e Fear & Greed < 25) era a regra de compra anterior. Perdeu dinheiro no backtest e hoje é apenas um aviso (`panic` nos dados, "em pânico" no painel), sem recomendação de compra.

### Regras de venda

Valem para as suas posições e para o backtest. Quando mais de uma dispara no mesmo dia, vale a primeira da tabela:

| Motivo | Regra |
|---|---|
| **STOP** | Perda de 20% sobre o preço de compra (proteção extra) |
| **TENDENCIA** | A moeda fechou abaixo da SMA 200 dela |
| **MERCADO** | O BTC fechou abaixo da SMA 200 dele |

O painel mostra, para cada posição, SEGURAR ou VENDER com o motivo e a data em que a regra disparou. O preço de referência é "vender se fechar o dia abaixo de" = a SMA 200 atual.

**Sobre o STOP:** no backtest de carteira do BTC+ETH o resultado é idêntico com e sem ele (a SMA 200 sempre dispara antes ou no mesmo dia), e nas 15 moedas melhora um pouco (treino +383% contra +354%; teste +52% contra +50%). Como não piora, ficou como proteção extra para posições compradas bem acima da média. `ExitRules(stop_loss=None)` o desliga.

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
  estágios: {'NEUTRO': 13, 'COMPRAR': 2}
  operações da tendência (BTC/ETH): 61 fechadas · acerto 26% · retorno médio +25.0%
  carteira BTC+ETH treino · TENDENCIA: +293.7% (+31.5%/ano) · pior queda -59.1%
  carteira BTC+ETH teste · TENDENCIA: +209.5% (+34.7%/ano) · pior queda -29.3%
  carteira BTC+ETH treino · COMPRAR_E_SEGURAR: +67.4% (+10.8%/ano) · pior queda -83.1%
  carteira BTC+ETH teste · COMPRAR_E_SEGURAR: +235.0% (+37.6%/ano) · pior queda -59.9%
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
- **Suas posições:** uma ficha por compra com Segurar/Vender, o motivo em português simples, o resultado, o preço abaixo do qual vender e o limite de perda.
- **Todas as moedas:** a recomendação para BTC e ETH, e a distância da média de 200 dias de todas. Clique numa para ver o gráfico.
- **Gráfico da moeda:** preço, média de 90 dias e média de 200 dias desde o início dos dados, entradas e saídas da regra e as suas compras. Passe o mouse para ler o preço de cada dia.
- **A regra de compra funciona?:** a comparação de carteira com comprar e segurar (retorno, por ano, pior queda e tempo comprado), em treino e teste.
- **Como funciona:** as regras de compra e venda explicadas.

As decisões visuais (cores, tipografia, componentes) estão em [frontend/DESIGN.md](frontend/DESIGN.md).

Se aparecer "sem dados ainda", rode o pipeline primeiro.

### 3. Registrar suas compras e vendas

Pelo painel, em **Suas posições**:

- **Registrar uma compra:** escolha a moeda, confira o preço pago (vem preenchido com o último fechamento), informe a quantidade e a data.
- **Já vendi:** em cada ficha, informe o preço e a data da venda. Ela passa para "Vendas que você registrou", com o resultado.
- **Apagar registro:** só para corrigir um registro errado.

O painel grava por uma rota local do `npm run dev`, que chama o mesmo comando do terminal e só aceita pedidos da própria página. O build estático (`npm run build`) não tem essa rota.

Pelo terminal, o equivalente é:

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

O backtest é de **carteira**: peso igual entre as moedas que já têm dados, com taxa de 0,1% sobre cada mudança de posição. A posição decidida no fechamento do dia t vale para o retorno de t+1, e todas as estratégias só começam quando a SMA 200 da moeda existe. A regra foi escolhida no **treino (2018–2022)** e conferida no **teste (2023–2026)**, dados que a escolha não viu.

Resultado com dados até 2026-10-14:

**Só BTC + ETH**

| Estratégia | Período | Retorno total | Por ano | Pior queda | Sharpe | Tempo comprado |
|---|---|---|---|---|---|---|
| Tendência + BTC em alta (regra do painel) | treino | **+293,7%** | 31,5% | -59,1% | 0,8 | 41% |
| Comprar e segurar | treino | +67,4% | 10,8% | -83,1% | 0,5 | 100% |
| Regra antiga (pânico) | treino | -49,5% | -12,8% | -50,7% | -0,7 | 9% |
| Tendência + BTC em alta (regra do painel) | teste | +209,5% | 34,7% | **-29,3%** | 1,0 | 60% |
| Comprar e segurar | teste | +235,0% | 37,6% | -59,9% | 0,9 | 100% |
| Regra antiga (pânico) | teste | +22,0% | 5,4% | -22,8% | 0,4 | 18% |

**As 15 moedas** (tendência = fechamento acima da SMA 200 da própria moeda, sem filtro do BTC)

| Estratégia | Período | Retorno total | Pior queda |
|---|---|---|---|
| Tendência | treino | +375% | -60,8% |
| Comprar e segurar | treino | +132% | -81,7% |
| Regra antiga (pânico) | treino | -31,7% | -36,1% |
| Tendência | teste | +53,5% | -50,4% |
| Comprar e segurar | teste | +164,9% | -67,8% |
| Regra antiga (pânico) | teste | -3,8% | -20,8% |

O que isso quer dizer:

- **O pânico perdeu dinheiro.** Comprar no pânico rendeu -49,5% no treino com BTC+ETH, contra +67,4% de comprar e segurar. Por isso virou só um aviso.
- **A tendência rendeu mais no treino e menos no teste, com metade da queda.** No teste o BTC+ETH comprado e segurado rendeu um pouco mais (+235% contra +209,5%), mas passou por uma queda de -59,9% contra -29,3% da regra. A vantagem da regra está em ser mais fácil de suportar, não em render mais.
- **Nas 15 moedas a regra não compensa no teste** (+53,5% contra +164,9%), por isso a recomendação é só para BTC e ETH.
- **A regra erra muito e acerta pouco:** das 61 operações simuladas em BTC e ETH, 26% terminaram no lucro, com resultado médio de +25%. As perdas são pequenas (a regra sai cedo) e alguns ganhos são enormes (+318% no BTC em 2020–2021). Quem não aguenta ver várias pequenas perdas seguidas dificilmente segue a regra.

O painel mostra a comparação do pipeline do dia (`performance.parquet`). Ela usa a regra do painel (tendência + BTC em alta + STOP) também para as 15 moedas, então os números de "as 15 moedas" do painel diferem um pouco dos da tabela acima (treino +383%, teste +52% no painel): é o filtro do BTC e o STOP de -20%.

### Reproduzir a tabela

```bash
uv run python research/strategy_comparison.py
```

O script lê a base local, avalia sete estratégias (comprar e segurar, pânico, tendência, tendência + BTC, cruzamento de médias, momento de 90 dias e compra de queda dentro da alta) nos dois universos e períodos, e imprime as tabelas. É o mesmo código de carteira do pipeline (`trade_simulator.evaluate_portfolio`).

### Limitações

- **Viés de sobrevivência:** o universo são as moedas que existem hoje. Moedas que quebraram ou saíram do top 15 não estão na amostra, o que favorece qualquer estratégia de comprar moedas.
- **Uma única amostra histórica:** são poucos ciclos de mercado (dois grandes ciclos de alta e baixa do BTC). Uma regra que funcionou neles pode não funcionar no próximo.
- **O passado não garante o futuro.** O treino/teste reduz o risco de ajustar a regra aos dados, mas não o elimina.
- **Sem impostos** (ganho de capital, IR sobre vendas) e execução ideal: compra e venda exatamente no fechamento, sem diferença entre preço e execução (slippage), além da taxa de 0,1%.
- **A regra atrasa:** a média de 200 dias reage devagar; a regra compra depois da virada e vende depois do topo.

## Configuração

| O quê | Onde |
|---|---|
| Moedas monitoradas (par Binance → id CoinGecko) | `src/config.py` (`UNIVERSE`) |
| Moedas com recomendação de compra | `src/config.py` (`RECOMMENDED`; no painel, `RECOMMENDED_SYMBOLS` em `frontend/src/data/coins.ts`) |
| Moeda do filtro de mercado, períodos de treino/teste e taxa | `src/config.py` (`REGIME_SYMBOL`, `TRAIN_PERIOD`, `TEST_PERIOD`, `FEE_PER_SIDE`) |
| Janela da média, distância do radar e alerta de pânico | `src/transformers/anomaly_detector.py` (`SignalRules`) |
| Regras de venda (STOP) | `src/transformers/trade_simulator.py` (`ExitRules`) |

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
    anomaly_detector.py      SMA 200, tendência, estágio e alerta de pânico de cada dia (vetorizado)
    daily_alerts.py          alertas de virada contra o dia anterior
    trade_simulator.py       operações da tendência e backtest de carteira (treino/teste, taxa)
    panic_backtest.py        a regra antiga do pânico, congelada só para comparação
    position_advisor.py      SEGURAR / VENDER das suas posições
  loaders/                 L — Parquet com escrita atômica
    market_store.py          base histórica (data/market)
    history_store.py         snapshot diário (data/signals/history)
    positions_store.py       suas posições (data/positions)
    parquet_loader.py        publicação para o painel
research/
  strategy_comparison.py   reproduz a tabela de estratégias (treino x teste)
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
| `history.parquet` | Preço, indicadores (SMA 90 e 200, RSI, z-score) e estágio de todos os dias |
| `backtest.parquet` | Cada operação simulada da regra de tendência (BTC e ETH) |
| `performance.parquet` | Carteira: tendência x comprar e segurar x pânico, em treino e teste |
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
| BTC e ETH em NEUTRO por meses | O BTC está abaixo da média de 200 dias | Esperado: em mercado de baixa a regra manda ficar de fora |
| `HTTP 451` da Binance | Bloqueio regional da api.binance.com | Rodar de uma região onde a Binance global atende |

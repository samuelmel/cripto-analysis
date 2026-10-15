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

Se uma fonte falhar, o pipeline continua: a falha vai para o registro de fontes e a moeda sem dado novo fica **INDISPONÍVEL** na análise (veja [Fontes de dados e qualidade](#fontes-de-dados-e-qualidade)). Só uma base local vazia aborta a execução.

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

## Laboratório de estratégias

O sinal do painel (SMA 200) não muda com nada daqui. O laboratório existe para responder, com o mesmo motor de carteira do pipeline (taxa de 0,1% por lado, posição decidida em t vale para t+1, peso igual), se alguma outra ideia merece entrar.

```bash
uv run python research/strategy_lab.py
```

**Protocolo.** Treino 2018–2020 (olhar à vontade), **validação 2021–2022** (só aqui se escolhem os parâmetros: maior Sharpe de cada estratégia, com ao menos 3 operações) e **teste 2023 em diante**, que só mede, nunca escolhe. A grade completa de parâmetros fica em `data/research/strategy_lab_grid.parquet` e traz apenas treino e validação; os resultados, em `data/research/strategy_lab.parquet`.

**Estratégias.** As sete de `strategy_comparison.py` (comprar e segurar, pânico, tendência, tendência + BTC, cruzamento de médias, momento de 90 dias, queda dentro da alta), mais: DCA fixo (aporte semanal), rompimento de Donchian, reversão de Bollinger, RSI sobrevendido e rompimento com confirmação de volume. Cada uma é uma função pura `signal(market, **params) -> posições 0/1` (`research/lab.py`).

**Referência aleatória.** Para cada estratégia, 200 sorteios com sementes fixas (1000 a 1199): a mesma exposição e as mesmas durações de operação, mas em dias deslocados ao acaso (deslocamento circular por moeda). A coluna `beats_random_pct` diz em quantos sorteios a estratégia rendeu mais.

**Métricas.** Retorno total e ao ano, pior queda, Sharpe (média diária × 365 dividida pelo desvio × √365, coerente com candle diário de cripto, sem taxa livre de risco), tempo comprado, número de operações, acerto, fator de lucro, trocas de posição por ano, taxas pagas (% do capital) e `beats_random_pct`.

Resultado no **teste** (2023 até hoje), BTC + ETH, ordenado por Sharpe. Tudo aparece, inclusive o que perde:

| Estratégia | Parâmetros (da validação) | Total | Ao ano | Pior queda | Sharpe | Comprado | Operações | Acerto | Fator de lucro | Taxas | Bate o aleatório |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Tendência + BTC em alta (regra do painel) | fixa | +209,5% | 34,7% | -29,3% | 1,0 | 60% | 30 | 33% | 6,9 | 2,9% | 81,5% |
| Tendência (> SMA 200) | fixa | +197,7% | 33,4% | -29,3% | 1,0 | 61% | 30 | 37% | 7,0 | 2,9% | 79,5% |
| Momento 90 dias > 0 | fixa | +176,1% | 30,7% | -32,0% | 0,9 | 59% | 51 | 37% | 3,3 | 5,0% | 78,5% |
| Comprar e segurar | fixa | +235,0% | 37,6% | -59,9% | 0,9 | 100% | 2 | 100% | ∞ | 0% | não se aplica |
| Rompimento + volume | n=55, k=1,5 | +94,5% | 19,2% | -28,0% | 0,7 | 49% | 20 | 55% | 3,5 | 1,9% | 63,0% |
| Donchian | n=100 | +55,3% | 12,3% | -34,0% | 0,5 | 44% | 11 | 45% | 3,2 | 1,0% | 45,0% |
| Cruzamento SMA 50 > SMA 200 | fixa | +48,6% | 11,0% | -41,0% | 0,5 | 59% | 10 | 70% | 2,9 | 0,9% | 23,0% |
| Bollinger (reversão) | n=20, k=1,5 | +42,5% | 9,8% | -50,9% | 0,5 | 32% | 73 | 75% | 1,5 | 7,1% | 47,5% |
| DCA fixo | a cada 7 dias | +31,0% | 7,4% | -54,6% | 0,4 | 57% | 396 aportes | 58% | 4,7 | 0,1% | não se aplica |
| Regra antiga (pânico) | fixa | +22,0% | 5,4% | -22,8% | 0,4 | 18% | 10 | 80% | 2,6 | 1,0% | 37,0% |
| RSI sobrevendido | 25 / 50 | +14,3% | 3,6% | -21,2% | 0,3 | 9% | 10 | 50% | 2,1 | 1,0% | 54,5% |
| Queda dentro da alta | fixa | +4,9% | 1,3% | -21,3% | 0,2 | 6% | 11 | 36% | 1,3 | 1,1% | 42,0% |

Como ler:

- **Nada novo superou a regra do painel no teste.** Das cinco novas (DCA, Donchian, Bollinger, RSI e rompimento com volume), nenhuma passou de 0,7 de Sharpe, abaixo do 1,0 da tendência. Os parâmetros escolhidos na validação não se sustentaram: o Donchian (n=100) teve Sharpe 1,2 na validação e 0,5 no teste, com apenas 3 operações na validação.
- **Comprar e segurar rendeu mais** (+235,0% contra +209,5%), com quase o dobro da queda (-59,9% contra -29,3%). A vantagem da regra é suportar melhor, não render mais.
- **Contra o acaso, a vantagem não é esmagadora:** a regra do painel bateu 81,5% dos sorteios com a mesma exposição, ou seja, 18,5% dos sorteios fizeram o mesmo ou melhor. Com uma única história de mercado e poucas operações independentes, isso é compatível com sorte parcial. O cruzamento de médias (23%) rendeu menos que a maioria dos sorteios.
- **Nas 15 moedas** a história é pior para as estratégias de tendência (a regra do painel bate só 23% dos sorteios no teste) e o rompimento com volume (n=20, k=1,5) só empatou em Sharpe com comprar e segurar (0,7 dos dois), com +98,4% contra +164,9%.
- **Custos:** Bollinger fez 73 operações e pagou 7,1% do capital em taxas; o DCA semanal paga pouco por aporte, mas o DCA também perdeu na validação (-43%) e rendeu +31% no teste, abaixo do comprar e segurar.
- **Limitações específicas:** a validação tem só dois anos e, em BTC + ETH, de 3 a 7 operações nas estratégias de rompimento e RSI; os parâmetros escolhidos nela são ruidosos. O universo é de moedas que existem hoje (viés de sobrevivência) e os números não incluem impostos.

**Estratégias pendentes (não implementadas):** pairs trading (arbitragem estatística entre pares), rotação entre moedas (por exemplo, sempre comprar as de maior momento) e ensemble (combinar vários sinais).

## Previsão estatística

`src/transformers/forecast.py` (função pura: sem rede, disco nem relógio; só numpy e pandas; semente injetada, `FORECAST_SEED`). Para BTC e ETH, em 1, 7 e 30 dias, publica P10/P50/P90 do retorno, o retorno estimado (mediana), a volatilidade, o método, a janela e o número de observações em `frontend/public/forecast.parquet`. Se o dado de uma moeda estiver desatualizado, ela não recebe previsão.

**Métodos.** Passeio aleatório (baseline: sem tendência, volatilidade da janela × raiz do horizonte; é "o preço de hoje com ruído"), bootstrap de retornos em blocos e volatilidade EWMA (RiskMetrics). O modelo publicado é o melhor dos dois últimos na validação, então o EWMA só aparece quando os dados o justificam.

**Walk-forward.** Em cada origem a previsão usa só dados até aquele dia, e o realizado são os dias seguintes; as origens ficam a cada `h` dias para as janelas não se sobreporem, e o realizado tem de terminar dentro do próprio período (a validação nunca olha dentro do teste). Janela, bloco e lambda (e a janela do baseline) são escolhidos na **validação 2021–2022** pela perda de quantis (pinball); o **teste 2023 em diante é lido uma única vez**, com os parâmetros já escolhidos.

**Regra de veredito.** `beats_baseline` só é verdadeiro se o modelo vencer o baseline em perda de quantis, MAE e RMSE no teste. `coverage_ok` exige cobertura compatível com os 80% nominais da faixa P10–P90 (intervalo binomial de 95% para o número de janelas). Sem `beats_baseline`, a coluna `verdict` diz "sem vantagem demonstrada sobre o preço de hoje".

Resultado no teste (retornos logarítmicos, em pontos percentuais; cobertura nominal de 80%; erro direcional: o baseline conta como "sempre alta"):

| Ativo | Horizonte | Método (parâmetros) | Janelas | MAE modelo / baseline | RMSE modelo / baseline | Acerto direcional modelo / baseline | Cobertura modelo / baseline | Largura modelo / baseline | Vence o baseline |
|---|---|---|---|---|---|---|---|---|---|
| BTC | 1 dia | EWMA (janela 365, λ 0,94) | 1382 | 1,69 / 1,68 | 2,42 / 2,41 | 51,4% / 50,6% | 83,0% / 85,7% | 5,96 / 6,51 | não |
| BTC | 7 dias | EWMA (janela 365, λ 0,99) | 197 | 4,74 / 4,63 | 6,41 / 6,35 | 51,3% / 51,3% | 84,3% / 83,2% | 16,7 / 17,2 | não |
| BTC | 30 dias | Bootstrap (janela 365, bloco 10) | 46 | 10,97 / 10,03 | 14,28 / 13,86 | 47,8% / 50,0% | 69,6% / 80,4% | 34,7 / 35,8 | não |
| ETH | 1 dia | EWMA (janela 365, λ 0,94) | 1382 | 2,26 / 2,26 | 3,28 / 3,27 | 50,9% / 50,9% | 83,5% / 85,7% | 8,06 / 8,86 | não |
| ETH | 7 dias | Bootstrap (janela 180, bloco 5) | 197 | 6,59 / 6,27 | 8,76 / 8,49 | 48,7% / 50,3% | 75,1% / 83,2% | 20,5 / 22,5 | não |
| ETH | 30 dias | Bootstrap (janela 365, bloco 10) | 46 | 14,75 / 13,31 | 19,22 / 17,94 | 41,3% / 50,0% | 76,1% / 82,6% | 46,8 / 48,6 | não |

**Conclusão: nenhum modelo superou o baseline em nenhum dos seis casos.** O EWMA de 1 dia teve perda de quantis um pouco menor (a faixa é mais estreita e reage à volatilidade), mas MAE e RMSE iguais ou piores, e a cobertura das faixas de 1 dia fica acima do nominal (83% a 86% contra 80%) porque a normal não pega as caudas pesadas. Em 30 dias os modelos pioram de forma clara (acerto direcional de 41% a 48%). A previsão deve ser lida como **faixa de incerteza**, não como palpite de direção.

**Limitações.** Viés de sobrevivência (BTC e ETH são as sobreviventes mais fortes). Poucas janelas independentes no horizonte de 30 dias: 46 por ativo no teste, com erro-padrão da cobertura de cerca de 6 pontos percentuais, então diferenças pequenas não são conclusivas. Uma única história de mercado (dois ciclos). Não inclui impostos, taxas nem execução. O passado não garante o futuro, e nada disso é recomendação de investimento.

## Fontes de dados e qualidade

| Fonte | O que traz | Chamada | Persistência |
|---|---|---|---|
| Binance | Candles diários de preço e volume (a única fonte de preço) | `GET /api/v3/klines`, uma moeda por vez, até 1000 candles por página; a vela ainda aberta é descartada | `data/market/ohlcv_1d/symbol=…/data.parquet` (upsert por moeda e dia) |
| CoinGecko | Market cap e volume atuais, uma foto por execução | `GET /coins/markets`, uma chamada para todas; chave Demo opcional no header `x-cg-demo-api-key` (`COINGECKO_API_KEY`) | `data/market/coingecko/data.parquet` |
| alternative.me | Fear & Greed diário (só alimenta o aviso de pânico) | `GET /fng/` | `data/market/fng/data.parquet` |
| (registro) | Quando cada fonte foi atualizada, com status e erro | gravado a cada atualização | `data/market/source_log/data.parquet` |

Garantias:

- **Rede:** timeout de 30 s por tentativa, no máximo 5 tentativas com espera de 2, 4, 8 e 16 s, `Retry-After` respeitado em 429/418 (ban longo desiste na hora) e espaçamento mínimo entre chamadas por fonte (Binance 0,2 s, CoinGecko e alternative.me 1 s). O plano Demo do CoinGecko permite 100 chamadas por minuto e 10 mil por mês; o pipeline usa uma por dia.
- **Resposta incompleta ou fora do formato** (JSON inválido, campos faltando, candle curto) vira `ExtractorError`; nunca vira dado silenciosamente errado.
- **Fonte secundária** (CoinGecko, Fear & Greed) fora do ar não derruba o pipeline: market cap fica nulo e o aviso de pânico não dispara.
- **Fonte primária** (Binance) fora do ar para uma moeda: o erro é registrado e a análise segue com a base local; a moeda sem candle recente fica INDISPONÍVEL.
- **Fornecedores não se misturam:** se chegarem candles de outra fonte para uma moeda que já tem base, a gravação é recusada.
- **Auditoria dos candles** a cada execução (aparece no relatório): duplicados, fora de ordem, preço nulo/NaN/infinito/<= 0, fontes misturadas e lacunas de dias. Preço inválido e duplicados são descartados antes dos indicadores.
- **Dado desatualizado nunca gera sinal atual:** o último candle fechado esperado é o de ontem (UTC); com mais de `MAX_STALE_DAYS` de atraso, ou sem 200 dias de histórico, ou com o BTC (filtro de mercado) indisponível, o estágio vira `INDISPONÍVEL` com o motivo em `stage_reason`, sem alertas e sem pânico. Posições dessa moeda também ficam INDISPONÍVEIS, a menos que o STOP já tenha disparado.

### Universo de moedas

Tudo em `src/config.py`: `UNIVERSE` (candidatas), `RECOMMENDED` (BTC e ETH), `MAX_EXTRA_COINS`, `MIN_HISTORY_DAYS`, `MIN_AVG_QUOTE_VOLUME_USD` com `VOLUME_WINDOW_DAYS`, e `EXCLUDED_BASES` com o motivo de cada exclusão (stablecoins, duplicatas de BTC/ETH) mais `LEVERAGED_SUFFIXES` (tokens alavancados, como BTCUP). A seleção é feita por `src/transformers/universe.py`, e o relatório lista quem ficou de fora e por quê. As 15 moedas atuais passam em todos os filtros.

### Testes

```bash
uv run pytest
```

Sem chamadas reais de rede (um teste que tentar abrir conexão falha). Cobrem a fronteira da SMA 200, o filtro do BTC, o STOP, posições encerradas, o pipeline `--offline`, API indisponível, timeout, resposta incompleta e dado desatualizado.

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
| Filtros e exclusões do universo, atraso máximo dos dados | `src/config.py` (`MAX_EXTRA_COINS`, `MIN_HISTORY_DAYS`, `MIN_AVG_QUOTE_VOLUME_USD`, `EXCLUDED_BASES`, `MAX_STALE_DAYS`) |
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
    universe.py              seleção do universo (exclusões, histórico, volume)
    data_quality.py          auditoria dos candles e disponibilidade (INDISPONÍVEL)
    anomaly_detector.py      SMA 200, tendência, estágio e alerta de pânico de cada dia (vetorizado)
    daily_alerts.py          alertas de virada contra o dia anterior
    trade_simulator.py       operações da tendência e backtest de carteira (treino/teste, taxa)
    panic_backtest.py        a regra antiga do pânico, congelada só para comparação
    forecast.py              previsão P10/P50/P90 de BTC e ETH contra o baseline
    position_advisor.py      SEGURAR / VENDER das suas posições
  loaders/                 L — Parquet com escrita atômica
    market_store.py          base histórica (data/market)
    history_store.py         snapshot diário (data/signals/history)
    positions_store.py       suas posições (data/positions)
    source_log.py            registro da atualização de cada fonte
    parquet_loader.py        publicação para o painel
research/
  strategy_comparison.py   reproduz a tabela de estratégias (treino x teste)
  strategy_lab.py          laboratório: novas estratégias, validação, referência aleatória (data/research/)
  lab.py                   sinais puros, DCA, estatísticas de operações, sorteio
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
| `forecast.parquet` | Previsão de 1, 7 e 30 dias de BTC e ETH, com a avaliação contra o baseline |
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
| Moeda aparece como "Sem dados confiáveis" | Dado desatualizado ou histórico curto; o motivo aparece na tabela | Rode `uv run python -m src.pipeline`; veja `data/market/source_log` se a fonte falhou |
| `HTTP 451` da Binance | Bloqueio regional da api.binance.com | Rodar de uma região onde a Binance global atende |

# crypto-analyzer

Monitor diário de criptomoedas que avalia um universo de até 32 moedas, diz quais merecem ser consideradas para compra e **quanto de um orçamento configurado (padrão R$ 100)** seria razoável aportar em cada uma, preservando a regra de **tendência** (SMA 200) de Bitcoin e Ethereum como referência. O projeto faz cinco coisas:

- **Base histórica:** guarda todos os candles diários desde 2017 e o Fear & Greed desde 2018.
- **Atualização diária:** todo dia baixa só o que falta e diz, para cada moeda, se está em tendência de alta.
- **Seleção e aporte:** classifica as moedas elegíveis, explica por quê, e sugere de R$ 0 até o orçamento, nunca acima dele (veja [Seleção de oportunidades e aporte](#seleção-de-oportunidades-e-aporte)).
- **Posições:** acompanha as moedas que você comprou e diz quando vender.
- **Backtest:** simula a regra em todo o histórico, em carteira, e compara com simplesmente comprar e segurar.

> Isto é uma ferramenta estatística, não previsão nem recomendação de investimento. Leia a seção [O que o backtest mostra](#o-que-o-backtest-mostra), incluindo as limitações, antes de usar os sinais para comprar.

## Como funciona

### Regra de compra e venda

Vale para **BTC e ETH** (configurável em `src/config.py`, `RECOMMENDED`) e continua sendo a regra principal de referência e de venda. As demais moedas não recebem o estágio COMPRAR desta regra; elas são avaliadas pela [camada de seleção](#seleção-de-oportunidades-e-aporte), que também pode escolher BTC e ETH.

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

## Seleção de oportunidades e aporte

Calculada uma vez por execução no pipeline (`src/transformers/selection.py` e `allocation.py`) e publicada em `daily_signals.parquet` (uma linha por moeda) e `recommendation.parquet` (resumo), com o mesmo `run_ts`. O painel e o Telegram só leem esse resultado; não há cálculo de aporte no frontend nem no formatador da mensagem. Antes de publicar, `recommendation.validate_recommendation` confere que a soma dos aportes não passa do orçamento, que só moedas selecionadas e com dado confiável recebem valor e que os dois arquivos são da mesma execução; o painel repete a conferência ao ler.

### Universo

`UNIVERSE` em `src/config.py` tem 32 pares spot USDT (as 15 anteriores e mais 17). Entram na análise até `MAX_UNIVERSE_SIZE` moedas que passam nos filtros de `universe.py`: nada de stablecoins, duplicatas (WBTC, stETH), tokens alavancados, moedas com menos de `MIN_HISTORY_DAYS` (365) candles ou com volume médio abaixo de `MIN_AVG_QUOTE_VOLUME_USD`. Moeda listada há pouco (por exemplo SUI ou TON, conforme a base) fica fora e aparece em "fora da análise" com o motivo; o histórico nunca é presumido. Estar no universo **não autoriza compra**: para ser candidata a moeda ainda passa pelos filtros abaixo. Inclusão manual = acrescentar o par em `UNIVERSE`; exclusão total = `EXCLUDED_BASES`; exclusão só da compra = `BUY_BLOCKLIST`.

### Indicadores (um por tipo de informação)

| Critério | Indicador | Uso |
|---|---|---|
| Tendência | preço contra SMA 200 (e SMA 50) | filtro obrigatório e condição favorável |
| Momento | retorno de 30 e 90 dias ÷ volatilidade (7 dias só é exibido: ruído) | componente do score |
| Força relativa | percentil do momento entre as moedas do dia; diferença de 90 dias contra BTC e ETH | o percentil já é a força relativa; a diferença contra o BTC é mostrada, não somada de novo |
| Volatilidade | desvio dos retornos log de 90 dias, anualizado | componente de risco, filtro (> 150% ao ano), alerta (> 90%) e dimensionamento |
| Queda | pior queda em 180 dias, distância e dias desde o topo | componente de risco, filtro (> 60%) e alerta |
| Liquidez | volume médio de 30 dias (USDT); spread estimado por faixa de volume | componente do score, filtro (`MIN_BUY_VOLUME_USD`) e custo |
| Estabilidade | % dos últimos 50 dias acima da SMA 200; número de condições favoráveis | componente do score; mínimo de `MIN_CONDITIONS` condições |
| Valorização excessiva | distância acima da SMA 50 em unidades da oscilação de 50 dias; RSI 14 | preço esticado (> 1,5) ou RSI > 80 = aguardar |
| Qualidade dos dados | candle de ontem, histórico ≥ 250 dias, dias faltando no último ano | filtro obrigatório |
| Custos | taxa 0,1% + spread estimado + slippage 0,05%, ida e volta | aporte inviável vira zero; custo exibido |

Estratégias usadas como **condições favoráveis** (`ENABLED_SETUPS`, reaproveitando os sinais do laboratório em `src/transformers/strategies.py`): SMA 200, cruzamento de EMAs 20/50, rompimento de Donchian 55 e momento de 90 dias. Rompimento com volume e recuo dentro da alta (reversão à média com filtro de tendência) estão implementados mas desligados: perderam para a tendência no [laboratório](#laboratório-de-estratégias).

### Score e classificação

Score (0 a 100) = 0,35 × momento + 0,20 × persistência + 0,25 × risco + 0,20 × liquidez (`SCORE_WEIGHTS`), cada componente como percentil da moeda entre as pontuáveis do dia. Por quê: percentil põe tudo na mesma escala (nenhum indicador domina pelo tamanho dos números) e é robusto a valores extremos; um componente por tipo de informação evita contar o mesmo movimento várias vezes (retorno de 30 e 90 dias formam um só componente). O momento tem o maior peso porque é o fator mais documentado em cripto, mas abaixo da soma de risco e liquidez, que protegem contra comprar o que só subiu. Os pesos foram fixados por esse argumento, **antes** de qualquer teste, e não foram otimizados; `research/selection_study.py` mede a sensibilidade só em treino e validação. O score é relativo e **não é probabilidade de lucro**.

| Classificação | Quando |
|---|---|
| **Evitar entrada** | algum filtro obrigatório falhou: dado indisponível, histórico curto ou com lacunas, liquidez baixa, volatilidade ou queda excessiva, tendência de baixa, bloqueio manual |
| **Aguardar** | filtros ok, mas a entrada não se justifica: mercado defensivo, momento de 90 dias ≤ 0, menos de 3 condições, preço esticado, RSI > 80 ou score < 50 |
| **Oportunidade moderada** | passou em tudo, mas tem alerta de risco ou score entre 50 e 65 |
| **Boa oportunidade relativa** | score ≥ 65 e nenhum alerta de risco |

Nenhum indicador isolado (RSI baixo, alta recente, queda brusca, volume) leva a uma compra: é preciso passar por todos os filtros ao mesmo tempo. Cada moeda traz os motivos a favor, os riscos e o que impede a compra. As `MAX_CANDIDATES` (3) melhores são selecionadas.

**Filtro de regime (BTC).** `REGIME_FILTER = "bloquear"` (padrão): com o BTC abaixo da SMA 200, nenhuma compra nova em nenhuma moeda, por mais alto que seja o score. Alternativas: `"reduzir"` (metade dos alvos, classificação no máximo moderada) e `"desligado"` (só alerta). O padrão foi mantido igual à regra principal porque é o filtro de segurança já validado; `selection_study.py` compara as três variantes por período. Mudar o padrão só se o estudo, em treino e validação, mostrar vantagem consistente; o resultado do teste não deve decidir.

### Quanto aportar

1. Só as selecionadas recebem valor, até `MAX_POSITIONS` (3).
2. Fração-alvo = mín(`MAX_ALLOCATION_PCT` 40%, `TARGET_VOL_PER_POSITION` 30% ÷ volatilidade anual da moeda) × convicção (boa = 1; moderada = 0,5). Moeda que oscila o dobro recebe a metade; nada de martingale nem de aumentar aporte depois de perda.
3. Alocação teórica = orçamento × fração. Se a soma passa do orçamento, todas são reduzidas na mesma proporção e o resumo informa a exposição-alvo teórica; a sugestão prática nunca passa do orçamento.
4. Arredondamento **para baixo** em múltiplos de R$ 5 (`ROUND_TO_BRL`); abaixo de `MIN_ORDER_BRL` (R$ 10, confira na sua corretora) vira zero; custo estimado acima de 2% do aporte (`MAX_COST_PCT`, inclui `FIXED_COST_BRL`) vira zero. O motivo de cada zero aparece no painel e no Telegram.

Exemplos com R$ 100: uma moeda boa com volatilidade de 75% ao ano → 40% → R$ 40; uma moderada com 95% → 31,6% × 0,5 → R$ 15; três boas com 30% → alvo teórico R$ 120, reduzido para R$ 30 cada (R$ 90, sobra R$ 10 pelo arredondamento); nenhuma candidata → R$ 0. Os valores são **estimativas de dimensionamento do modelo, não garantia de retorno**.

**Orçamento.** `BUDGET_BRL = 100` é o total para novas posições na análise, não por moeda nem aporte obrigatório. Não há integração com saldo real: cada execução é uma **simulação** para o valor informado, e o sistema não presume que os R$ 100 voltam a estar disponíveis. Se você já aportou, rode com o saldo que resta: `uv run python -m src.pipeline --budget 55`.

### Validação

`selection_backtest.py` refaz a seleção e o aporte do pipeline (mesmas funções, mesmo orçamento, arredondamento e ordem mínima) a cada 7 dias e compara, com custos, com: seleção com valor igual por moeda, momento simples (as 3 que mais subiram em 90 dias), regra SMA 200 em todas as moedas, comprar e segurar todas e só BTC, em treino (2018–2020), validação (2021–2022) e teste (2023 em diante). Vai para `selection_backtest.parquet`, para a aba **Seleção** do painel e para a frase de evidência do Telegram. O estudo completo:

```bash
uv run python research/selection_study.py
```

acrescenta DCA fixo, referência aleatória (mesmo número de moedas, mesma exposição e mesmo giro, moedas sorteadas entre as elegíveis, 100 sementes fixas), as variantes do filtro de regime, resultado ano a ano (walk-forward), desempenho por regime de volatilidade do BTC (limiares medidos no treino), sensibilidade de pesos e limiares (só treino e validação), redundância entre componentes (Spearman) e viabilidade das quantias pequenas com R$ 100. Grava em `data/research/selection_study.parquet` sem tocar nos resultados anteriores (`strategy_lab.parquet`, tabelas abaixo).

**Resultados com dados reais: pendentes.** Esta mudança foi desenvolvida num ambiente sem acesso às APIs de mercado (Binance, CoinGecko e alternative.me bloqueadas pela rede), então o estudo só foi executado sobre preços sintéticos, para conferir o código; esses números não dizem nada sobre o mercado e não estão aqui. Rode o pipeline e o estudo com a base real antes de usar as sugestões. Desde a Fase 3, o campo `evidence` (painel e Telegram) compara a seleção com comprar e segurar **as mesmas moedas**, com as mesmas premissas, pela diferença de Sharpe com intervalo de 90% (bootstrap em blocos, semente fixa), e diz explicitamente que 2023 em diante é um período **já consultado** no desenvolvimento, não um teste intocado. Intervalo que inclui zero = "diferença compatível com sorte: a vantagem não está demonstrada". A avaliação completa, com todas as estratégias e correção para comparações múltiplas, está em [Validação estatística](#validação-estatística).

Desde a Fase 2 roda no [motor único](#motor-de-backtest): mesma execução (abertura do dia seguinte), mesmos custos e o mesmo universo point-in-time para a seleção e para cada referência. Limitações: as candidatas continuam sendo as moedas de `UNIVERSE` (moedas que quebraram, como LUNA e FTT, não estão na base do pipeline, o que favorece comprar altcoins; o universo histórico completo está só na base de pesquisa, `data/archive`); spread e slippage são hipóteses (`SPREAD_TIERS`, `SLIPPAGE`), não medidas; a abertura seguinte é uma aproximação do preço alcançável; uma única história de mercado; sem impostos. Não há execução de ordens: nenhuma chave de corretora, nenhuma API que movimente dinheiro.

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

A primeira execução baixa todo o histórico, em cerca de 40 segundos para 15 moedas (o universo atual tem 32: conte com o dobro). As seguintes baixam só os dias que faltam. Exemplo de saída:

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
| Envia o resumo pelo Telegram | `uv run python -m src.pipeline --notify` |
| Gera e valida a mensagem sem token e sem rede | `uv run python -m src.pipeline --dry-run` |
| Baixa todo o histórico de novo | `uv run python -m src.pipeline --rebuild` |

Se uma fonte falhar, o pipeline continua: a falha vai para o registro de fontes e a moeda sem dado novo fica **INDISPONÍVEL** na análise (veja [Fontes de dados e qualidade](#fontes-de-dados-e-qualidade)). Só uma base local vazia aborta a execução.

### 2. Abrir o painel

```bash
npm --prefix frontend run dev
```

Acesse o endereço que aparece na linha `Local:` do terminal, normalmente http://localhost:5173. O painel só funciona enquanto esse comando estiver rodando. Ele mostra:

O painel tem quatro abas:

- **Visão geral:** faixa de estado (mercado, atualização dos dados, data da análise), área de **avisos** separada das recomendações (pânico, dado desatualizado, falha de coleta), o que fazer hoje, os cartões de **Bitcoin e Ethereum** lado a lado (preço, sinal, variação em 24 horas e 30 dias, distância da média de 200 dias), a **previsão** de 1, 7 e 30 dias com a faixa P10 a P90, o gráfico principal e **suas posições**.
- **Histórico:** todas as moedas, o gráfico e as operações simuladas da moeda escolhida.
- **Previsões:** o gráfico com a faixa tracejada (rotulada como estimativa) e a tabela de avaliação contra o preço de hoje. Quando o modelo não vence a referência, o painel diz "sem vantagem demonstrada sobre o preço de hoje".
- **Pesquisa:** a comparação de carteira com comprar e segurar (incluindo a pior queda), o laboratório de estratégias (treino, validação e teste), como funciona e o glossário.

Termos como média de 200 dias, tendência, pior queda, volatilidade, faixa de previsão e Sharpe têm dica ao passar o mouse, focar com o teclado ou tocar (Esc fecha). O tooltip do gráfico mostra data, valor e fonte. Em telas estreitas tudo vira uma coluna, sem rolagem horizontal; as colunas secundárias das tabelas aparecem só no desktop.

Arquivos opcionais: `forecast.parquet`, `sources.parquet` e `strategy_lab.parquet` (este último vem de `uv run python research/strategy_lab.py`). Se faltarem, a aba mostra um estado vazio com o comando para gerá-los, em vez de erro.

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

O sinal do painel (SMA 200) não muda com nada daqui. O laboratório existe para responder se alguma outra ideia merece entrar. **Ele ainda usa o motor antigo** (`run_portfolio`: taxa de 0,1% por lado, posição decidida em t vale para t+1, rebalanceamento diário sem custo): seus números não são comparáveis com os do pipeline, que usa o [motor único](#motor-de-backtest). Na Fase 3, as mesmas estratégias e grades foram reavaliadas no motor único, com walk-forward e correção para comparações múltiplas, em [Validação estatística](#validação-estatística); para decidir, vale aquela avaliação. O laboratório antigo fica como registro histórico.

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

## Notificação no Telegram

O resumo do dia vai para o seu celular. Só envia mensagem: não há ordens, nem acesso a exchange, nem chave de corretora.

```bash
uv run python -m src.pipeline --notify      # roda o pipeline e envia o resumo
uv run python -m src.pipeline --dry-run     # gera e valida a mensagem, imprime, não envia nada e não pede token
```

| Variável | Para quê |
|---|---|
| `TELEGRAM_BOT_TOKEN` | token do seu bot (BotFather). Segredo: nunca vai em código, log, mensagem ou erro. |
| `TELEGRAM_CHAT_ID` | número do chat que recebe as mensagens |
| `COINGECKO_API_KEY` | opcional (chave Demo gratuita do CoinGecko) |

**O que a mensagem traz** (curta, para ler em um minuto): data e hora da análise (Fortaleza e UTC) e se os dados estão em dia, o orçamento da simulação, o estado do mercado (favorável, neutro ou defensivo, com uma frase de explicação), só as moedas selecionadas (no máximo `MAX_CANDIDATES`), cada uma com aporte sugerido, classificação e score, motivo e principal risco, o resumo do aporte (total, saldo não alocado, decisão e avisos como "exposição-alvo teórica acima do orçamento"), alertas essenciais (virada da regra SMA 200 de BTC ou ETH e pânico) e a evidência do backtest. Sem oportunidade, a mensagem é a frase fixa "Hoje não encontrei oportunidades suficientemente boas dentro dos critérios configurados. Aporte sugerido: R$ 0 de R$ 100. O orçamento permanece sem alocação." mais os motivos mais frequentes. Todos os números vêm de `recommendation.parquet`/`daily_signals.parquet` da mesma execução; os indicadores detalhados ficam no painel.

**Quando algo dá errado.** Dados parciais ou atrasados: a mensagem traz "Limitações desta análise" com a falha; moeda sem dado confiável nunca é recomendada, e sem dado do BTC nenhuma compra é sugerida. Se o pipeline falhar e o Telegram estiver configurado, chega um alerta curto de erro (sem segredos). Se o envio falhar, o pipeline termina com código 2, e o job do GitHub fica vermelho. Mensagens acima de 4096 caracteres são divididas em parágrafo ou linha; o envio tem timeout de 15 s, até 3 tentativas com espera de 2 e 4 s, respeita o `retry_after` do Telegram e não repete quando o token ou o chat estão errados.

### Criar o bot e descobrir o chat_id (você faz uma vez)

1. No Telegram, abra uma conversa com **@BotFather** (confira o selo azul de verificado) e envie `/newbot`. Escolha um nome e um usuário que termine em `bot`. O BotFather responde com o **token**, no formato `123456789:AA...`. Guarde-o: quem tem o token controla o bot.
2. Abra a conversa com o seu bot novo e envie qualquer mensagem (por exemplo, `oi`). Um bot não pode escrever primeiro.
3. Descubra o chat_id: no navegador, abra `https://api.telegram.org/bot<SEU_TOKEN>/getUpdates` (troque `<SEU_TOKEN>` pelo token) e procure `"chat":{"id":123456789`. Esse número é o `TELEGRAM_CHAT_ID`. Essa URL contém o token: não compartilhe a tela nem o link.
4. Teste no seu computador, no PowerShell, na pasta do projeto:

```powershell
$env:TELEGRAM_BOT_TOKEN = "cole-o-token"
$env:TELEGRAM_CHAT_ID = "cole-o-chat-id"
uv run python -m src.pipeline --offline --notify
```

Se a mensagem chegar no celular, está pronto. Fechar o PowerShell apaga as variáveis.

## Automação com GitHub Actions

O arquivo [.github/workflows/daily.yml](.github/workflows/daily.yml) roda o pipeline online todo dia e envia o resumo. Ele só funciona se o projeto estiver num repositório do GitHub (o workflow precisa estar na branch padrão).

**Horário.** O `cron` do GitHub usa UTC por padrão (a documentação atual também aceita uma chave `timezone`, mas não é necessária aqui). O gatilho é `10 0 * * *`: **00:10 UTC = 21:10 em Fortaleza** (UTC−3 o ano todo, sem horário de verão), logo depois do fechamento do candle diário da Binance (00:00 UTC). Usei UTC porque o evento que importa, o fechamento do candle, é em UTC. Para outro fuso, converta: horário local + 3 h = UTC em Fortaleza. O GitHub pode atrasar ou até descartar execuções agendadas em horário de pico (o começo de cada hora conta como pico, por isso 00:10 e não 00:00), e em repositório público desativa o agendamento depois de 60 dias sem atividade (reative em Actions).

**Por que uma vez por dia.** O sinal usa o fechamento diário: a vela do dia em andamento é descartada. Rodar a cada 5 horas devolve o mesmo sinal e só gera mensagens repetidas. Não há ganho.

**O que o workflow faz, nesta ordem:**

1. Testa `api.binance.com` e, se ela recusar o runner (**HTTP 451**, bloqueio regional) ou não responder 200, testa `data-api.binance.vision`, que serve os mesmos dados públicos de mercado. O primeiro que responder 200 vira a variável `BINANCE_API_HOST` do pipeline. Se nenhum responder, o job falha na hora com uma mensagem clara: a decisão é sua (outro lugar para rodar, ou outra fonte de preço). O pipeline só aceita esses dois hosts.
2. `actions/checkout` e `actions/setup-python` (as oficiais do GitHub, versão v7), instala o `uv` na mesma versão do projeto e faz `uv sync --locked`.
3. Roda `uv run python -m src.pipeline --notify`, sem `--offline`. Qualquer falha crítica (rede, análise, envio) deixa o job vermelho.

Segurança: `permissions: contents: read`, `concurrency` sem execuções simultâneas, e os segredos entram só como `secrets` do GitHub, só no passo do pipeline.

**Sobre o estado.** O runner começa sem a pasta `data/`: a cada execução o pipeline baixa o histórico inteiro de novo (cerca de 40 s na primeira carga) e recalcula tudo. A fonte de verdade dos preços é a própria Binance, não um cache. Ao final (mesmo se o pipeline falhar), o passo "Guardar o estado de auditoria" sobe como artefato privado do repositório, por 90 dias, o registro de fontes (com o histórico de falhas), as revisões de candles, o fingerprint dos dados usados e o snapshot dos sinais; nada de posições nem segredos. Falha nesse passo não deixa o job vermelho. O sinal de "ontem", usado nos alertas de virada, é recalculado a partir do histórico, sem estado guardado. **As suas posições (`data/positions`) não existem no runner**: a mensagem diária cobre os sinais de BTC e ETH, não as suas compras. Para ver o status das suas posições, use o painel no seu computador.

### O que você precisa fazer manualmente

1. Colocar o projeto num repositório do GitHub (eu não faço `push`) e deixar o workflow na branch padrão.
2. Em **Settings → Secrets and variables → Actions → New repository secret**, criar três segredos com estes nomes exatos: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` e (opcional) `COINGECKO_API_KEY`.
3. Em **Actions → Pipeline diário → Run workflow**, fazer um teste manual.
4. Confirmar o envio: o job termina verde, o log do último passo mostra `resumo enviado ao Telegram (1 mensagem(ns))` (o GitHub esconde os segredos no log) e a mensagem chega no celular. Se o primeiro passo ficar vermelho, a Binance (os dois hosts) recusou o runner e o pipeline não roda no GitHub sem outra solução.
5. Se usar o agendamento do Windows (seção abaixo) junto com o GitHub, você recebe duas mensagens por dia; desative um dos dois.

## Fontes de dados e qualidade

| Fonte | O que traz | Chamada | Persistência |
|---|---|---|---|
| Binance | Candles diários de preço e volume (a única fonte de preço) | `GET /api/v3/klines`, uma moeda por vez, até 1000 candles por página; a vela ainda aberta é descartada | `data/market/ohlcv_1d/symbol=…/data.parquet` (upsert por moeda e dia) |
| CoinGecko | Market cap e volume atuais, uma foto por execução | `GET /coins/markets`, uma chamada para todas; chave Demo opcional no header `x-cg-demo-api-key` (`COINGECKO_API_KEY`) | `data/market/coingecko/data.parquet` |
| alternative.me | Fear & Greed diário (só alimenta o aviso de pânico) | `GET /fng/` | `data/market/fng/data.parquet` |
| (registro) | Quando cada fonte foi atualizada, com status e erro | gravado a cada atualização | `data/market/source_log/data.parquet` (última de cada fonte) e `history.parquet` (todas, append-only) |
| (revisões) | Valor de candle já gravado que uma nova leitura alterou (valor antigo e novo) | a cada atualização | `data/market/revisions/data.parquet` |
| (dados usados) | Linhas, intervalo e SHA-256 dos candles de cada moeda usados em cada execução | a cada análise | `data/market/dataset_manifest/history.parquet`; o relatório mostra o hash combinado |
| Arquivo oficial da Binance (pesquisa) | Candles diários de todos os pares spot, **inclusive os deslistados** (LUNA, FTT, UST...), em ZIPs com SHA-256 | `python -m src.archive` (abaixo) | `data/archive/` (não é lida pelo pipeline diário) |

Garantias:

- **Rede:** timeout de 30 s por tentativa, no máximo 5 tentativas com espera de 2, 4, 8 e 16 s, `Retry-After` respeitado em 429/418 (ban longo desiste na hora) e espaçamento mínimo entre chamadas por fonte (Binance 0,2 s, CoinGecko e alternative.me 1 s). O plano Demo do CoinGecko permite 100 chamadas por minuto e 10 mil por mês; o pipeline usa uma por dia.
- **Resposta incompleta ou fora do formato** (JSON inválido, campos faltando, candle curto) vira `ExtractorError`; nunca vira dado silenciosamente errado.
- **Fonte secundária** (CoinGecko, Fear & Greed) fora do ar não derruba o pipeline: market cap fica nulo e o aviso de pânico não dispara.
- **Fonte primária** (Binance) fora do ar para uma moeda: o erro é registrado e a análise segue com a base local; a moeda sem candle recente fica INDISPONÍVEL.
- **Fornecedores não se misturam:** se chegarem candles de outra fonte para uma moeda que já tem base, a gravação é recusada.
- **Auditoria dos candles** a cada execução (aparece no relatório): duplicados, fora de ordem, preço nulo/NaN/infinito/<= 0, fontes misturadas, lacunas de dias, OHLC inconsistente (máxima abaixo do fechamento etc.), volume negativo, candle fora da meia-noite UTC e candle ainda não fechado no momento da leitura. Preço inválido e duplicados são descartados antes dos indicadores.
- **Dado desatualizado nunca gera sinal atual:** o último candle fechado esperado é o de ontem (UTC); com mais de `MAX_STALE_DAYS` de atraso, ou sem 200 dias de histórico, ou com o BTC (filtro de mercado) indisponível, o estágio vira `INDISPONÍVEL` com o motivo em `stage_reason`, sem alertas e sem pânico. Posições dessa moeda também ficam INDISPONÍVEIS, a menos que o STOP já tenha disparado.

### Base point-in-time do arquivo da Binance (pesquisa)

O universo do pipeline diário (`UNIVERSE`) são moedas que existem **hoje**: usá-lo para testar o passado tem viés de sobrevivência. Para a pesquisa há uma base separada, montada do arquivo público oficial da Binance (`data.binance.vision`, servido pelo bucket S3 `s3-ap-northeast-1.amazonaws.com/data.binance.vision`), que guarda também os pares que deixaram de negociar:

```bash
uv run python -m src.archive catalog        # todos os pares USDT do arquivo, vivos e deslistados
uv run python -m src.archive sync --core    # só as moedas de UNIVERSE
uv run python -m src.archive sync --all     # todos os candidatos (sem alavancados, stablecoins, fiat, ouro, embrulhados)
uv run python -m src.archive universe       # universo de cada dia, eventos de entrada e saída, resumo de sobrevivência
uv run python -m src.archive status         # tamanho da base, fingerprint e problemas de qualidade
```

- **Verificado:** cada ZIP é conferido contra o `.CHECKSUM` (SHA-256) publicado; sem checksum ou com divergência, nada é gravado. O manifesto (`data/archive/manifest`) guarda chave, ETag, SHA-256 e linhas de cada arquivo.
- **Incremental e idempotente:** o que já foi ingerido com o mesmo ETag não é baixado de novo; reexecutar não duplica candles; arquivo republicado pela Binance é baixado de novo e a mudança vai para `data/archive/revisions`. Falha num par vai para `data/archive/sync_log` e não toca nos outros.
- **Universo de cada dia** (`transformers/point_in_time.py`): no dia D só entram dados até o fechamento de D; histórico e volume médio são medidos até D; o limite de tamanho escolhe as de maior volume **em D**. Lacuna de mais de `EPISODE_GAP_DAYS` (7) dias encerra o episódio: o que voltar depois é outro ativo (caso real: `LUNAUSDT` ficou 18 dias parada em maio de 2022 e voltou como Terra 2.0).
- **Limites (o viés não está eliminado):** só enxerga pares listados na Binance spot; o fim de uma série é "sem candles depois de X" (deslistagem **inferida**, o arquivo não traz o anúncio); renomeações (MATIC → POL) aparecem como saída de um par e entrada de outro; as exclusões `NON_CRYPTO_BASES` são uma lista curada com o conhecimento de hoje; possíveis ações tokenizadas (sufixo B, 2025–2026) não são excluídas, só sinalizadas.

### Universo de moedas

Tudo em `src/config.py`: `UNIVERSE` (candidatas), `RECOMMENDED` (BTC e ETH), `MAX_EXTRA_COINS`, `MIN_HISTORY_DAYS`, `MIN_AVG_QUOTE_VOLUME_USD` com `VOLUME_WINDOW_DAYS`, e `EXCLUDED_BASES` com o motivo de cada exclusão (stablecoins, duplicatas de BTC/ETH) mais `LEVERAGED_SUFFIXES` (tokens alavancados, como BTCUP). A seleção é feita por `src/transformers/universe.py`, e o relatório lista quem ficou de fora e por quê. As moedas listadas há menos de um ano ficam de fora até completarem o histórico.

### Testes

```bash
uv run pytest
```

Sem chamadas reais de rede (um teste que tentar abrir conexão falha). Cobrem a fronteira da SMA 200, o filtro do BTC, o STOP, posições encerradas, o pipeline `--offline`, API indisponível, timeout, resposta incompleta e dado desatualizado.

`tests/test_golden_baseline.py` roda o pipeline inteiro sobre um mercado **sintético** fixo (`tests/synthetic_market.py`) e compara as saídas com `tests/golden/*.parquet`: uma refatoração que deveria ser só técnica não pode mudar esses números. Mudança intencional de regra é documentada em `docs/QUANT_ROADMAP_PROGRESS.md` antes de regenerar com `UPDATE_GOLDEN=1 uv run pytest tests/test_golden_baseline.py`. Os números sintéticos não dizem nada sobre o mercado.

O CI (`.github/workflows/ci.yml`) roda em todo pull request: `uv lock --check`, `requirements.txt` em sincronia com o `uv.lock`, nenhum Parquet/CSV/`.env` versionado, `mypy --strict src/ mcp_server.py`, `pytest` e o build do frontend. Não usa segredos nem acessa APIs de mercado. `requirements.txt` é gerado: `uv export --format requirements.txt --no-dev --locked --no-emit-project --no-hashes -o requirements.txt`.

## Motor de backtest

Desde a Fase 2 do roadmap há **um único motor de referência** (`src/transformers/backtest_engine.py`), usado por tudo que o pipeline publica: a carteira (`performance.parquet`), as operações da tendência (`backtest.parquet`) e a seleção contra as referências (`selection_backtest.parquet`). Todas as estratégias e referências de uma mesma tabela usam exatamente as mesmas premissas. Premissas versionadas em `src/config.py` (`EXECUTION_MODEL_VERSION = "next-open-v1"`):

| Premissa | Regra |
|---|---|
| Sinal | calculado com dados até o **fechamento** do candle diário de D |
| Execução | na **abertura do candle seguinte** (D+1), nunca ao fechamento de D que gerou o sinal. A abertura é uma aproximação do preço alcançável, não uma garantia |
| Sem preço válido | candle ausente: a ordem espera até `MAX_ORDER_DELAY_DAYS` (3) dias; depois expira, sem execução a preço inventado. Uma decisão nova substitui a pendente |
| Custos | compra a abertura × (1 + meio-spread + slippage), venda a abertura × (1 − meio-spread − slippage), taxa de 0,1% sobre o executado (`src/transformers/costs.py`, o mesmo modelo que a seleção usa para dizer se um aporte é viável). Meio-spread pela faixa de volume conhecida até a véspera |
| Caixa | vendas antes das compras; compras limitadas ao caixa (escaladas quando não cabem, com registro); sem alavancagem, sem venda a descoberto, caixa sem rendimento |
| Universo | em cada dia só ativos elegíveis no universo **point-in-time** daquele dia (`point_in_time.py`); ativo que sai do universo é vendido. BTC e ETH seguem a regra ao vivo e nunca saem por histórico ou volume |
| Deslistagem | ativo em carteira sem candle há mais de `EPISODE_GAP_DAYS` (7) é baixado com `DELIST_RECOVERY` (0 = perda total, conservador). Nenhum retorno atravessa uma lacuna entre episódios |
| Rebalanceamento | carteira de peso igual: todo dia, pagando o custo de cada ajuste; seleção e referências: a cada 7 dias, com banda de 5 pontos (`REBALANCE_BAND`) |
| Stop | é um sinal de fechamento, executado na abertura seguinte (o gap entra no resultado); não há stop intradiário |

Cada execução produz o livro de operações (preço de referência, preço executado, taxa, custo de spread e de slippage, caixa depois) e o livro de ordens (decisão, execução, atraso, status, fração executada). `reconcile` confere caixa = capital + fluxos, patrimônio = caixa + posições, retornos que reproduzem o patrimônio final, quantidades = compras − vendas − baixas, exposição ≤ 100%. Se não fechar, o pipeline não publica nada.

**Medido com dados reais** (arquivo oficial da Binance, 794.968 pares de candles consecutivos): a abertura de D+1 difere do fechamento de D em 0,033% na mediana (0,61% no percentil 99; máximo de 42,7%). Nas 32 moedas de `UNIVERSE`, 0,008% na mediana e 6,4% no máximo. A Binance negocia 24 horas: a mudança para a abertura seguinte quase não pesa no caso típico e tira o otimismo dos casos extremos.

**Os motores antigos** (`trade_simulator.run_portfolio`/`performance_summary`/`backtest` e `selection_backtest.run_weighted`/`evaluate_selection_legacy`) continuam no código só para reproduzir resultados antigos (`tests/test_legacy_engines.py`) e para o laboratório de `research/`, que ainda não migrou (Fase 3). Diferenças medidas, cada uma com teste em `tests/test_engine_reconciliation.py`: sem custos e com abertura = fechamento anterior, o motor único reproduz os dois exatamente; o `run_portfolio` rebalanceava para peso igual todo dia sem cobrar por isso e perdia o movimento de preço através de um candle ausente; o `run_weighted` podia passar de 100% de exposição com a banda (alavancagem implícita: até 116,7% no mercado sintético) e mantinha um ativo deslistado pelo último preço. A atribuição passo a passo, premissa por premissa, sai de `uv run python research/engine_reconciliation.py` (`--archive` para usar a base do arquivo oficial).

## Validação estatística

Fase 3 do roadmap. Responde se alguma estratégia do projeto tem evidência que vá além da sorte, sem escolher o melhor resultado histórico:

```bash
uv run python research/validation_study.py             # base do arquivo oficial (data/archive)
uv run python research/validation_study.py --base market
```

**Protocolo `wf-v1`** (fixado no código antes de rodar; detalhes em [docs/QUANT_ROADMAP_PROGRESS.md](docs/QUANT_ROADMAP_PROGRESS.md#fase-3--validação-estatística)):

| Item | Regra |
|---|---|
| Dados | todos os pares USDT do arquivo da Binance que estiveram no universo point-in-time em algum dia (271), inclusive os que pararam de negociar |
| Janelas | walk-forward anual: teste de 12 meses a partir de 2020-01-01; treino ancorado desde o primeiro candle; validação = 730 dias antes de cada escolha; embargo 0 (métricas diárias marcadas a mercado) |
| Status dos dados | **todo o histórico já foi explorado** no desenvolvimento das regras. O walk-forward impede que a escolha de parâmetros veja o teste, não que as regras tenham sido desenhadas olhando esses anos. Só dado posterior a 2026-10-15 será prospectivo |
| Família | 16 hipóteses: as 11 regras e grades já testadas em BTC+ETH e 5 estratégias do universo point-in-time. H0: Sharpe(estratégia) − Sharpe(referência) ≤ 0, unilateral, α = 5%, **Holm**. Teste impossível (pânico sem Fear & Greed) fica na família com p = 1 |
| Referência | comprar e segurar **as mesmas moedas**, mesmo motor, custos, banda e posição inicial (escolhida antes, por argumento); só BTC aparece como referência descritiva |
| Incerteza | bootstrap estacionário pareado e conjunto (Politis e Romano), bloco automático (Politis e White), 2.000 reamostras, semente 20261016, intervalo percentil de 90%; sensibilidade a blocos de 5, 20 e 60 dias; ajuste pelo máximo da estatística (Reality Check) além de Holm |
| Robustez | custo baixo e alto, atraso de 1 dia, cada janela começando em caixa, deslistagem com 100% de recuperação, 2% dos candles removidos, variações moderadas de parâmetro, regimes do BTC |
| Classificação | `INVALIDA`, `EVIDENCIA_INSUFICIENTE` (amostra ou diferença compatível com sorte), `NEGATIVA`, `PROMISSORA_NAO_CONFIRMADA`, `ROBUSTA_NO_PROTOCOLO` (exige todos os critérios de `src/transformers/evidence.py`) |

Tudo vai para `data/research/validation/` em modo append-only: registro de experimentos com id determinístico (estratégia, parâmetros, período, universo, referência, versão do motor, custos, fingerprint dos dados e da configuração), e uma execução nunca sobrescreve outra.

**Resultado com dados reais** (2020-01-01 a 2026-10-15, 2.480 dias, base com fingerprint `dc80de01535f89b9`, sem Fear & Greed neste ambiente). Diferença de Sharpe contra comprar e segurar as mesmas moedas, intervalo de 90%:

| Estratégia | Universo | Sharpe | ΔSharpe (IC 90%) | p | p Holm | Classificação |
|---|---|---|---|---|---|---|
| Seleção (aporte variável) | todas (PIT) | 1,13 | +0,71 (+0,08 a +1,23) | 0,017 | 0,27 | promissora, não confirmada |
| Seleção, peso igual | todas (PIT) | 0,92 | +0,51 (−0,11 a +1,00) | 0,047 | 0,71 | evidência insuficiente |
| Tendência (regra do painel) | BTC+ETH | 1,07 | +0,11 (−0,37 a +0,55) | 0,32 | 1 | evidência insuficiente |
| Tendência sem filtro do BTC | BTC+ETH | 1,04 | +0,07 (−0,36 a +0,49) | 0,34 | 1 | evidência insuficiente |
| Tendência + BTC, sem STOP | BTC+ETH | 1,07 | +0,11 (−0,37 a +0,55) | 0,32 | 1 | evidência insuficiente (idêntica à do painel: o STOP de −20% nunca disparou) |
| Rompimento + volume (grade) | BTC+ETH | 1,02 | +0,06 (−0,47 a +0,50) | 0,36 | 1 | evidência insuficiente |
| SMA 200 semanal | todas (PIT) | 0,53 | +0,11 (−0,46 a +0,63) | 0,32 | 1 | evidência insuficiente |
| Tendência diária | todas (PIT) | 0,41 | +0,12 (−0,37 a +0,57) | 0,29 | 1 | evidência insuficiente |
| Donchian (grade) | BTC+ETH | 0,90 | −0,07 (−0,62 a +0,36) | 0,52 | 1 | negativa |
| Cruzamento SMA 50/200 | BTC+ETH | 0,79 | −0,17 (−0,65 a +0,28) | 0,72 | 1 | negativa |
| Momento 90 dias | BTC+ETH | 0,76 | −0,21 (−0,81 a +0,29) | 0,72 | 1 | negativa |
| RSI sobrevendido (grade) | BTC+ETH | 0,28 | −0,69 (−1,46 a +0,05) | 0,93 | 1 | negativa |
| Momento simples | todas (PIT) | −0,37 | −0,78 (−1,31 a −0,35) | 0,99 | 1 | negativa (significativamente inferior) |
| Bollinger (grade) | BTC+ETH | −0,13 | −1,09 (−1,74 a −0,51) | 1,00 | 1 | negativa (significativamente inferior) |
| Queda dentro da alta | BTC+ETH | −0,28 | −1,24 (−2,15 a −0,33) | 0,99 | 1 | negativa (significativamente inferior) |
| Pânico | BTC+ETH | — | — | — | 1 | inválida: Fear & Greed ausente (não tratado como zero) |

Referências no mesmo período: comprar e segurar BTC+ETH Sharpe 0,96 (pior queda −76%); comprar e segurar todas (PIT, semanal) 0,42 (−96%); só BTC 0,90 (−77%).

Como ler, sem exagerar:

- **Nenhuma estratégia tem evidência robusta.** A única com intervalo acima de zero (a seleção) não sobrevive à correção para as 16 hipóteses (p ajustado 0,27; 0,17 pelo ajuste do máximo). Ela atende os demais critérios (estável em 5 de 7 janelas, positiva em todos os cenários de estresse e nas 4 variações de parâmetro), por isso é "promissora, não confirmada": a hipótese a acompanhar prospectivamente, não uma conclusão.
- **A regra do painel (tendência em BTC+ETH) não se distingue de comprar e segurar em retorno por risco** (+0,11, intervalo de −0,37 a +0,55). A vantagem dela é a pior queda menor (−60% contra −76%), que esta família de testes não usa como hipótese.
- **Seis estratégias perderam da referência**, três de forma significativa (momento simples, Bollinger, queda dentro da alta).
- Os números são de um histórico já explorado; deslistagens inferidas incluem renomeações (ver limitações) e spread/slippage são hipóteses. Um intervalo de confiança descreve a incerteza desta amostra, não garante retorno futuro.

## O que o backtest mostra

> **Resultados exploratórios e do MOTOR ANTIGO.** As tabelas desta seção, do laboratório e da previsão foram
> calculadas antes da Fase 2, com o motor antigo (execução ao fechamento do sinal, só taxa), com dados até
> 2026-10-14. Não são diretamente comparáveis com o que o pipeline publica agora (motor único, seção acima). O período
> "teste" (2023 em diante) já foi consultado várias vezes durante o desenvolvimento: não é um teste final intocado. Estão sujeitas a viés de sobrevivência, a um universo filtrado com o volume atual e à
> execução no fechamento do próprio candle do sinal. Ficam como referência histórica, não como validação. Detalhes
> e o plano de correção em [docs/QUANT_ROADMAP_PROGRESS.md](docs/QUANT_ROADMAP_PROGRESS.md).

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

**As 15 moedas** (universo anterior à ampliação, resultado preservado; tendência = fechamento acima da SMA 200 da própria moeda, sem filtro do BTC)

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
- **Nas 15 moedas a regra não compensa no teste** (+53,5% contra +164,9%), por isso o sinal de compra da regra SMA 200 vale só para BTC e ETH (as outras moedas passam pela seleção, com backtest próprio).
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
- **Sem impostos** (ganho de capital, IR sobre vendas). Nas tabelas desta seção (motor antigo), execução ideal: compra e venda exatamente no fechamento, sem spread nem slippage, só a taxa de 0,1%. O pipeline atual executa na abertura seguinte com taxa, spread e slippage ([motor único](#motor-de-backtest)).
- **A regra atrasa:** a média de 200 dias reage devagar; a regra compra depois da virada e vende depois do topo.

## Configuração

| O quê | Onde |
|---|---|
| Moedas monitoradas (par Binance → id CoinGecko) | `src/config.py` (`UNIVERSE`) |
| Filtros e exclusões do universo, atraso máximo dos dados | `src/config.py` (`MAX_EXTRA_COINS`, `MIN_HISTORY_DAYS`, `MIN_AVG_QUOTE_VOLUME_USD`, `EXCLUDED_BASES`, `MAX_STALE_DAYS`) |
| Moedas da regra principal SMA 200 | `src/config.py` (`RECOMMENDED`; no painel, `RECOMMENDED_SYMBOLS` em `frontend/src/data/coins.ts`) |
| Seleção: candidatas, liquidez, pesos, limiares, estratégias, filtro de regime | `src/config.py` (`MAX_CANDIDATES`, `BUY_BLOCKLIST`, `MIN_BUY_VOLUME_USD`, `MIN_SCORE_HISTORY_DAYS`, `SCORE_WEIGHTS`, `SCORE_STRONG`, `SCORE_MODERATE`, `MIN_CONDITIONS`, `ENABLED_SETUPS`, `SETUP_PARAMS`, `MAX_VOLATILITY`, `MAX_DRAWDOWN_180D`, `MAX_STRETCH`, `REGIME_FILTER`) |
| Orçamento e aporte | `src/config.py` (`BUDGET_BRL`, `MAX_POSITIONS`, `MAX_ALLOCATION_PCT`, `TARGET_VOL_PER_POSITION`, `CONVICTION`, `ROUND_TO_BRL`, `MIN_ORDER_BRL`, `FIXED_COST_BRL`, `MAX_COST_PCT`, `SPREAD_TIERS`, `SLIPPAGE`); por execução, `--budget` |
| Moeda do filtro de mercado, períodos de treino/teste e taxa | `src/config.py` (`REGIME_SYMBOL`, `TRAIN_PERIOD`, `TEST_PERIOD`, `FEE_PER_SIDE`) |
| Janela da média, distância do radar e alerta de pânico | `src/transformers/anomaly_detector.py` (`SignalRules`) |
| Regras de venda (STOP) | `src/transformers/trade_simulator.py` (`ExitRules`) |

Depois de mudar uma regra, rode `uv run python -m src.pipeline --offline` para recalcular tudo sem baixar nada.

## Estrutura

```
src/
  pipeline.py              orquestra: atualiza base → analisa → compara com ontem → publica
  positions.py             CLI das suas posições
  archive.py               CLI da base point-in-time do arquivo oficial da Binance (data/archive)
  config.py                universo de moedas
  extractors/              E — um adaptador por fonte, saída padronizada
    binance_adapter.py       candles 1d (/api/v3/klines)
    coingecko_adapter.py     market cap atual (/coins/markets)
    fng_adapter.py           Fear & Greed Index (alternative.me)
    binance_archive.py       arquivo oficial data.binance.vision (ZIPs com SHA-256, inclusive pares deslistados)
  transformers/            T — regras de negócio puras, sem I/O
    universe.py              seleção do universo de HOJE (exclusões, histórico, volume)
    point_in_time.py         universo de cada dia só com dados até aquele dia; episódios; eventos de entrada e saída
    dataset.py               fingerprint dos dados, manifesto por moeda, trilha de revisões de candles
    costs.py                 modelo de custos (taxa, meio-spread por faixa de volume, slippage)
    backtest_engine.py       motor único: execução na abertura seguinte, caixa, ordens, custos, reconciliação
    portfolio_backtest.py    tendência x comprar e segurar x pânico e operações da tendência, no motor único
    strategies.py            sinais de estratégia compartilhados (Donchian, EMAs, volume, Bollinger, RSI, recuo e queda na alta)
    selection.py             indicadores, score, classificação e motivos de cada moeda
    allocation.py            aporte por moeda dentro do orçamento (volatilidade, limites, arredondamento)
    recommendation.py        contrato daily_signals + recommendation e as suas invariantes
    selection_backtest.py    backtest da seleção contra referências, no motor único (e o legado run_weighted)
    metrics.py               métricas de uma série diária de retornos, com convenções e mínimos de amostra
    bootstrap.py             bootstrap estacionário em blocos: bloco automático, IC, p-valores, ajuste pelo máximo
    multiple_testing.py      Holm-Bonferroni sobre uma família declarada antes
    walk_forward.py          dobras de treino, validação e teste; escolha de parâmetros sem ver o teste
    strategy_catalog.py      todas as estratégias já testadas no projeto, como sinais 0/1 com variações
    validation.py            protocolo da Fase 3: cenários, dobras, bootstrap conjunto, Holm e classificação
    evidence.py              critérios pré-registrados e categorias de evidência
    experiments.py           registro de experimentos: id determinístico, fingerprints, bloqueio de mistura de motores
    data_quality.py          auditoria dos candles e disponibilidade (INDISPONÍVEL)
    anomaly_detector.py      SMA 200, tendência, estágio e alerta de pânico de cada dia (vetorizado)
    daily_alerts.py          alertas de virada contra o dia anterior
    trade_simulator.py       sinal de tendência e regras de saída; motores antigos (legado, só para reproduzir)
    panic_backtest.py        a regra antiga do pânico, congelada só para comparação
    notification.py          mensagem do Telegram (pura): relatório, divisão em 4096, validação
    forecast.py              previsão P10/P50/P90 de BTC e ETH contra o baseline
    position_advisor.py      SEGURAR / VENDER das suas posições
  loaders/                 L — Parquet com escrita atômica
    market_store.py          base histórica (data/market)
    history_store.py         snapshot diário (data/signals/history)
    positions_store.py       suas posições (data/positions)
    source_log.py            registro da atualização de cada fonte (última e histórico)
    archive_store.py         base do arquivo oficial (candles, manifesto, catálogo, sync_log, point-in-time)
    experiment_store.py      registro e tabelas da validação (data/research/validation), append-only
  notifiers/               envio (rede) de notificações
    telegram.py              sendMessage com timeout, retry e sem vazar o token
    parquet_loader.py        publicação para o painel
research/
  strategy_comparison.py   reproduz a tabela de estratégias (treino x teste)
  strategy_lab.py          laboratório: novas estratégias, validação, referência aleatória (data/research/)
  lab.py                   sinais puros, DCA, estatísticas de operações, sorteio
  selection_study.py       estudo da seleção e do aporte variável (data/research/selection_study.parquet)
  engine_reconciliation.py motor antigo x motor único, uma premissa por vez (data/research/engine_reconciliation.parquet)
  validation_study.py      validação estatística (Fase 3): família, walk-forward, bootstrap, Holm (data/research/validation/)
frontend/                  React + TypeScript + Tailwind
  DESIGN.md                contrato visual: tokens, tipografia, componentes, o que evitar
  src/data/                leitura e validação do Parquet + cálculos e textos puros do painel
  src/components/          Dashboard, Sections, PriceChart (lightweight-charts), ui (primitivas)
tests/                     pytest, sem chamadas de rede
.github/workflows/         pipeline diário no GitHub Actions
mcp_server.py              tool MCP run_crypto_pipeline
run_daily.cmd              script chamado pelo Agendador de Tarefas
```

Arquivos publicados em `frontend/public/` (gerados, fora do Git):

| Arquivo | Conteúdo |
|---|---|
| `daily_signals.parquet` | Estágio e alertas do dia, score, componentes, classificação, motivos, riscos e aporte de cada moeda |
| `recommendation.parquet` | Resumo da recomendação: orçamento, mercado, total sugerido, saldo, notas, evidência e estado dos dados |
| `selection_backtest.parquet` | Seleção contra as referências simples, com custos, em treino, validação e teste |
| `history.parquet` | Preço, indicadores (SMA 90 e 200, RSI, z-score) e estágio de todos os dias |
| `backtest.parquet` | Cada operação simulada da regra de tendência (BTC e ETH) |
| `performance.parquet` | Carteira: tendência x comprar e segurar x pânico, em treino e teste |
| `forecast.parquet` | Previsão de 1, 7 e 30 dias de BTC e ETH, com a avaliação contra o baseline |
| `sources.parquet` | Quando e como cada fonte foi atualizada (alerta de falha de coleta) |
| `strategy_lab.parquet` | Resultados do laboratório de estratégias (opcional, vem de `research/strategy_lab.py`) |
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
| `HTTP 451` da Binance | Bloqueio regional da api.binance.com | No GitHub Actions o workflow já tenta `data-api.binance.vision`; localmente, `BINANCE_API_HOST=https://data-api.binance.vision` ou rodar de uma região onde a Binance global atende |

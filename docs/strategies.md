# Estratégias, seleção e aporte

Este documento explica **como o Crypto Analyzer decide**. Há duas camadas, e uma não substitui a outra:

1. **Regra principal SMA 200**, só para Bitcoin e Ethereum. É a referência histórica do projeto e a regra de venda das suas posições.
2. **Camada de seleção e aporte**, para todas as moedas analisadas, inclusive BTC e ETH. É ela que escolhe as candidatas e sugere quanto aportar.

Todos os parâmetros citados ficam em [`src/config.py`](../src/config.py), salvo indicação diferente. Os resultados históricos estão em [backtesting.md](backtesting.md).

> [!NOTE]
> Nada aqui é recomendação de investimento. As regras foram fixadas antes do período de teste, e os testes não mostram vantagem demonstrada da seleção sobre estratégias simples.

---

## 1. Regra principal: SMA 200 (BTC e ETH)

**SMA 200** é a média simples dos últimos 200 fechamentos diários. Preço acima dela indica tendência de alta de longo prazo. Vale para as moedas de `RECOMMENDED` (BTC e ETH).

| Estágio | Regra | Leitura |
|---|---|---|
| **COMPRAR** | Fechamento acima da SMA 200 da moeda **e** BTC acima da SMA 200 dele | Comprar, ou segurar se já tem |
| **PREPARAR** | Fechamento até 3% abaixo da SMA 200, subindo há 5 dias, com o BTC em alta | Radar: perto de cruzar |
| **NEUTRO** | Demais casos | Ficar de fora |
| **INDISPONÍVEL** | Dado atrasado, menos de 200 dias de histórico ou BTC indisponível | Sem sinal (o motivo fica em `stage_reason`) |

Alertas de virada em relação ao dia anterior:

- `COMPRAR AGORA`: virou COMPRAR hoje.
- `VENDER AGORA`: estava em COMPRAR e deixou de estar.
- `NO RADAR`: entrou em PREPARAR hoje.
- `SAIU DO RADAR`: estava em PREPARAR e voltou a NEUTRO.

A janela da média, a distância do radar e os limites do pânico ficam em `SignalRules`, em [`src/transformers/anomaly_detector.py`](../src/transformers/anomaly_detector.py).

### Pânico: hoje só um aviso

O pânico (z-score de 90 dias < −2,5, RSI < 30 e Fear & Greed < 25) era a regra de compra anterior. Ele **perdeu dinheiro no backtest** (−49,5% no treino com BTC + ETH) e hoje é apenas um aviso: a coluna `panic` nos dados e o rótulo "em pânico" no painel. Não gera recomendação de compra.

### Regras de venda (suas posições e backtest)

Quando mais de uma regra dispara no mesmo dia, vale a primeira da tabela:

| Motivo | Regra |
|---|---|
| **STOP** | Perda de 20% sobre o preço de compra |
| **TENDENCIA** | A moeda fechou abaixo da SMA 200 dela |
| **MERCADO** | O BTC fechou abaixo da SMA 200 dele |

O painel mostra SEGURAR ou VENDER para cada posição, com o motivo e a data em que a regra disparou. O preço de referência ("vender se fechar o dia abaixo de") é a SMA 200 atual.

**Por que o STOP existe.** No backtest de carteira de BTC + ETH, o resultado é idêntico com e sem ele, porque a SMA 200 sempre dispara antes ou no mesmo dia. Nas 15 moedas do universo anterior, ele melhora um pouco: treino +383% contra +354%, teste +52% contra +50%. Como não piora, ficou como proteção extra para posições compradas bem acima da média. Para desligá-lo, use `ExitRules(stop_loss=None)` em [`src/transformers/trade_simulator.py`](../src/transformers/trade_simulator.py).

---

## 2. Seleção de oportunidades

A seleção roda **uma vez por execução** no pipeline ([`selection.py`](../src/transformers/selection.py) e [`allocation.py`](../src/transformers/allocation.py)). O resultado é publicado em `daily_signals.parquet` (uma linha por moeda) e `recommendation.parquet` (resumo), com o mesmo `run_ts`.

O painel e o Telegram só leem esse resultado. Não há cálculo de aporte no frontend nem no formatador da mensagem. Antes de publicar, `validate_recommendation` (em [`recommendation.py`](../src/transformers/recommendation.py)) confere três coisas:

- a soma dos aportes não passa do orçamento;
- só moedas selecionadas e com dado confiável recebem valor;
- os dois arquivos são da mesma execução.

O painel repete a conferência ao ler. A mesma função `assess` classifica o dia de hoje e cada dia do backtest da seleção, então o que aparece no painel é exatamente o que foi testado.

### 2.1 Universo: quem é analisado

`UNIVERSE` tem 32 pares spot em USDT: as 15 moedas originais e mais 17 da ampliação. Entram na análise até `MAX_UNIVERSE_SIZE` (32) moedas que passam nos filtros de [`universe.py`](../src/transformers/universe.py):

| Filtro | Parâmetro |
|---|---|
| Não é stablecoin nem duplicata (WBTC, WETH, stETH) | `EXCLUDED_BASES` |
| Não é token alavancado (sufixos UP, DOWN, BULL, BEAR) | `LEVERAGED_SUFFIXES` |
| Tem pelo menos 365 candles diários | `MIN_HISTORY_DAYS` |
| Volume médio de 30 dias de pelo menos US$ 1 milhão | `MIN_AVG_QUOTE_VOLUME_USD`, `VOLUME_WINDOW_DAYS` |

Uma moeda listada há pouco (por exemplo, SUI ou TON, conforme a base) fica de fora e aparece em "fora da análise" com o motivo. O histórico nunca é presumido.

**Estar no universo não autoriza compra.** Para virar candidata, a moeda ainda passa pelos filtros a seguir.

| Quero… | Faça |
|---|---|
| Incluir uma moeda | Acrescente o par em `UNIVERSE` |
| Excluir da análise inteira | `EXCLUDED_BASES`, ou tire de `UNIVERSE` |
| Excluir só da compra (continua no painel) | `BUY_BLOCKLIST`, por exemplo `{"DOGE/USDT": "não quero memecoins"}` |

### 2.2 Indicadores

Um indicador por tipo de informação, para não contar o mesmo movimento várias vezes:

| Critério | Indicador | Uso |
|---|---|---|
| Tendência | Preço contra SMA 200 e SMA 50 | Filtro obrigatório e condição favorável |
| Momento | Retornos de 30 e 90 dias ÷ volatilidade (o de 7 dias só é exibido, por ser ruído) | Componente do score |
| Força relativa | Percentil do momento entre as moedas do dia; diferença de 90 dias contra BTC e ETH | O percentil já é a força relativa; a diferença contra o BTC é exibida, não somada de novo |
| Volatilidade | Desvio dos retornos log de 90 dias, anualizado | Risco, filtro (> 150% ao ano), alerta (> 90%) e dimensionamento |
| Queda | Pior queda em 180 dias, distância e dias desde o topo | Risco, filtro (> 60%) e alerta |
| Liquidez | Volume médio de 30 dias (USDT); spread estimado por faixa de volume | Score, filtro (`MIN_BUY_VOLUME_USD`, US$ 20 milhões) e custo |
| Estabilidade | % dos últimos 50 dias acima da SMA 200; número de condições favoráveis | Score; mínimo de `MIN_CONDITIONS` (3) condições |
| Valorização excessiva | Distância acima da SMA 50 em unidades da oscilação de 50 dias; RSI de 14 dias | Esticado (> 1,5) ou RSI > 80 = aguardar |
| Qualidade dos dados | Candle de ontem, histórico ≥ 250 dias, no máximo 3 dias faltando no último ano | Filtro obrigatório |
| Custos | Taxa de 0,1% + spread estimado + slippage de 0,05%, ida e volta | Aporte inviável vira zero; custo exibido |

**Condições favoráveis** (`ENABLED_SETUPS`, sinais em [`strategies.py`](../src/transformers/strategies.py)): preço acima da SMA 200, cruzamento de EMAs 20/50, rompimento de Donchian 55 e momento de 90 dias positivo. Rompimento com volume e recuo dentro da alta estão implementados, mas **desligados**, porque perderam para a tendência no [laboratório](backtesting.md#laboratório-de-estratégias).

### 2.3 Score

```
score (0 a 100) = 0,35 × momento + 0,20 × persistência + 0,25 × risco + 0,20 × liquidez
```

Cada componente é o **percentil** da moeda entre as moedas pontuáveis do dia (`SCORE_WEIGHTS`). As razões:

- **Percentil** põe tudo na mesma escala, e nenhum indicador domina pelo tamanho dos números. Também é robusto a valores extremos.
- **Momento** tem o maior peso porque é o fator mais documentado em cripto. Ainda assim, fica abaixo da soma de risco e liquidez, que protegem contra comprar o que só subiu.
- Os pesos foram fixados por esse argumento, **antes** de qualquer teste, e não foram otimizados. `research/selection_study.py` mede a sensibilidade só em treino e validação.

O score é **relativo**: diz quem está melhor que as alternativas do dia. **Não é probabilidade de lucro.**

### 2.4 Classificação

A primeira regra que se aplica decide:

| Classificação | Quando |
|---|---|
| **Evitar entrada** | Algum filtro obrigatório falhou: dado indisponível, histórico curto ou com lacunas, liquidez baixa, volatilidade ou queda excessiva, preço abaixo da SMA 200, BTC sem dados confiáveis ou bloqueio manual |
| **Aguardar** | Filtros ok, mas a entrada não se justifica agora: mercado defensivo (com o filtro "bloquear"), momento de 90 dias ≤ 0, menos de 3 condições, preço esticado, RSI > 80 ou score < 50 |
| **Boa oportunidade relativa** | Score ≥ 65 (`SCORE_STRONG`) e nenhum alerta de risco |
| **Oportunidade moderada** | Passou em tudo, mas tem alerta de risco ou score entre 50 e 65 |

**Alertas de risco** impedem a classificação "boa": volatilidade acima de 90% ao ano, preço perto do limite de esticado, ainda mais de 15% abaixo do topo de 180 dias, queda forte recente, evidência limitada (exatamente 3 condições), liquidez apenas suficiente e mercado defensivo (quando o filtro não bloqueia).

Nenhum indicador isolado (RSI baixo, alta recente, queda brusca ou volume) leva a uma compra. A moeda precisa passar por todos os filtros ao mesmo tempo. Cada moeda traz os motivos a favor, os riscos e o que impede a compra.

**Ordem e corte:** as candidatas são ordenadas com as boas antes das moderadas e, depois, pelo score. As `MAX_CANDIDATES` (3) primeiras são selecionadas, e as demais recebem a nota "fora das 3 melhores desta análise".

### 2.5 Filtro de mercado (regime do BTC)

O estado do mercado vem do BTC:

| Estado | Condição |
|---|---|
| **Favorável** | BTC acima da SMA 200 e SMA 50 acima da SMA 200 |
| **Neutro** | BTC acima da SMA 200, mas SMA 50 abaixo da SMA 200 |
| **Defensivo** | BTC abaixo da SMA 200 |
| **Indisponível** | Sem dado confiável do BTC: nenhuma compra é sugerida |

`REGIME_FILTER` decide o que fazer no mercado defensivo:

- `"bloquear"` (padrão): nenhuma compra nova em nenhuma moeda, por mais alto que seja o score.
- `"reduzir"`: alvos cortados pela metade (`REGIME_REDUCE_FACTOR`), com classificação no máximo moderada.
- `"desligado"`: só alerta.

> [!NOTE]
> Este é o regime **que as regras de compra usam**. Existe também uma classificação de regimes mais rica (tendência × volatilidade, com confirmação), publicada só para análise em `market_regimes.parquet` e descrita em [regimes.md](regimes.md). Ela **não** altera este filtro.

O padrão é igual ao da regra principal, porque é o filtro de segurança já validado. `selection_study.py` compara as três variantes por período. Só mude o padrão se o estudo mostrar vantagem consistente em treino e validação. O resultado do teste não deve decidir.

---

## 3. Quanto aportar

O orçamento (`BUDGET_BRL`, padrão R$ 100) é o **total para novas posições na análise**. Não é um valor por moeda nem um aporte obrigatório.

1. **Quem recebe.** Só as moedas selecionadas recebem valor, até `MAX_POSITIONS` (3).
2. **Fração-alvo.** É o menor valor entre `MAX_ALLOCATION_PCT` (40%) e `TARGET_VOL_PER_POSITION` (30%) ÷ volatilidade anual da moeda. O resultado é multiplicado pela convicção (`CONVICTION`): 1 para boa, 0,5 para moderada. Uma moeda que oscila o dobro recebe a metade, e cada posição contribui com um risco parecido. Não há martingale, e o aporte nunca aumenta depois de uma perda.
3. **Limite do orçamento.** A alocação teórica é o orçamento × a fração. Se a soma passa do orçamento, todas as moedas são reduzidas na mesma proporção, e o resumo informa a exposição-alvo teórica. A sugestão prática nunca passa do orçamento.
4. **Arredondamento e mínimos.** O valor é arredondado **para baixo** em múltiplos de R$ 5 (`ROUND_TO_BRL`). Abaixo de `MIN_ORDER_BRL` (R$ 10), vira zero. Confira a ordem mínima da sua corretora. Custo estimado acima de 2% do aporte (`MAX_COST_PCT`, inclui `FIXED_COST_BRL`) também vira zero. O motivo de cada zero aparece no painel e no Telegram.
5. **Invariante.** 0 ≤ soma dos aportes ≤ orçamento. Se for violada, o pipeline levanta erro e não publica nada.

**Decisão resumida** (`decision` em `recommendation.parquet`): `NAO_INVESTIR` (R$ 0), `APORTE_PEQUENO` (até 30% do orçamento), `APORTE_PARCIAL` (até 60%) ou `APORTE_AMPLO` (acima de 60%).

### Exemplos com R$ 100 (ilustrativos)

| Situação | Cálculo | Sugestão |
|---|---|---|
| Uma moeda boa, volatilidade de 75% ao ano | 30% ÷ 75% = 40% (no limite) | R$ 40 |
| Uma moeda moderada, volatilidade de 95% | 30% ÷ 95% = 31,6% × 0,5 = 15,8% | R$ 15 |
| Três moedas boas, volatilidade de 30% | 3 × 40% = R$ 120 teóricos, reduzidos a R$ 33,33 cada | R$ 30 cada (R$ 90; sobram R$ 10 pelo arredondamento) |
| Nenhuma candidata | — | R$ 0 |

São estimativas de dimensionamento do modelo, não garantia de retorno.

### Orçamento e saldo real

Não há integração com a corretora. Cada execução é uma **simulação** para o valor informado, e o sistema não presume que os R$ 100 voltam a estar disponíveis. Se você já aportou, rode com o saldo que resta:

```bash
uv run python -m src.pipeline --budget 55
```

---

## 4. Parâmetros

Depois de mudar qualquer parâmetro, rode `uv run python -m src.pipeline --offline` para recalcular tudo sem baixar nada.

| O quê | Onde |
|---|---|
| Moedas monitoradas (par Binance → id CoinGecko) | `UNIVERSE` |
| Filtros do universo e atraso máximo dos dados | `MAX_UNIVERSE_SIZE`, `MIN_HISTORY_DAYS`, `MIN_AVG_QUOTE_VOLUME_USD`, `VOLUME_WINDOW_DAYS`, `EXCLUDED_BASES`, `LEVERAGED_SUFFIXES`, `MAX_STALE_DAYS` |
| Moedas da regra principal SMA 200 | `RECOMMENDED` (no painel, `RECOMMENDED_SYMBOLS` em `frontend/src/data/coins.ts`) |
| Seleção: candidatas, liquidez, pesos, limiares, estratégias, regime | `MAX_CANDIDATES`, `BUY_BLOCKLIST`, `MIN_BUY_VOLUME_USD`, `MIN_SCORE_HISTORY_DAYS`, `MAX_GAP_DAYS_365`, `SCORE_WEIGHTS`, `SCORE_STRONG`, `SCORE_MODERATE`, `MIN_CONDITIONS`, `ENABLED_SETUPS`, `SETUP_PARAMS`, `MAX_VOLATILITY`, `HIGH_VOLATILITY`, `MAX_DRAWDOWN_180D`, `MAX_STRETCH`, `MAX_RSI_ENTRY`, `REGIME_FILTER` |
| Orçamento e aporte | `BUDGET_BRL` (ou `--budget` por execução), `MAX_POSITIONS`, `MAX_ALLOCATION_PCT`, `TARGET_VOL_PER_POSITION`, `CONVICTION`, `REGIME_REDUCE_FACTOR`, `ROUND_TO_BRL`, `MIN_ORDER_BRL`, `FIXED_COST_BRL`, `MAX_COST_PCT`, `SPREAD_TIERS`, `SLIPPAGE` |
| Filtro de mercado, períodos e taxa | `REGIME_SYMBOL`, `TRAIN_PERIOD`, `VALIDATION_PERIOD`, `TEST_PERIOD`, `FEE_PER_SIDE` |
| Backtest da seleção | `SELECTION_REBALANCE_DAYS`, `REBALANCE_BAND` |
| Janela da média, radar e pânico | `SignalRules` em `src/transformers/anomaly_detector.py` |
| Regras de venda (STOP) | `ExitRules` em `src/transformers/trade_simulator.py` |

> [!WARNING]
> Os pesos e limiares foram fixados **antes** do teste. Se você os ajustar olhando para o resultado do período de teste, ele deixa de ser um teste independente.

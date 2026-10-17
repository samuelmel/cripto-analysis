# Backtests e pesquisa

Este documento reúne **como as regras foram testadas no passado, o que os testes mostraram e o que eles não conseguem mostrar**. Os resultados negativos estão incluídos.

> [!IMPORTANT]
> Resultado histórico não garante resultado futuro. Nenhum número aqui é promessa de rentabilidade nem recomendação de investimento.

**Resumo honesto:**

- A **regra SMA 200** em BTC + ETH rendeu um pouco menos que comprar e segurar no teste, com cerca de metade da queda máxima.
- **Nenhuma estratégia nova** do laboratório superou a regra SMA 200 no teste.
- A **seleção com aporte** ainda não demonstrou vantagem sobre as referências simples. O estudo completo está pendente.
- A **previsão de preço** não superou a referência ingênua em nenhum caso. Veja [forecast.md](forecast.md).

---

## Metodologia comum

Todos os backtests usam o mesmo motor de carteira (`trade_simulator.run_portfolio` e `summarize_returns`):

- **Carteira com peso igual** entre as moedas que já têm dados naquele dia.
- **Taxa de 0,1% por lado** (`FEE_PER_SIDE`) sobre cada mudança de posição.
- **Sem olhar para o futuro:** a posição decidida no fechamento do dia *t* vale para o retorno do dia *t + 1*.
- As estratégias só começam quando a SMA 200 da moeda existe.
- **Sharpe** = média diária × 365 ÷ (desvio diário × √365), coerente com candles diários de cripto, sem taxa livre de risco.

**Divisão no tempo.** A regra é escolhida em uma parte do histórico e conferida em outra, que a escolha não viu:

| Período | Datas | Uso |
|---|---|---|
| Treino | 2018–2020 (até 2022 no backtest original da regra) | Livre para explorar |
| Validação | 2021–2022 | Escolha de parâmetros, quando há |
| Teste | 2023 em diante | **Só mede, nunca escolhe** |

---

## Regra SMA 200 contra comprar e segurar

Base: candles diários da Binance até **2026-10-14**. Treino de 2018 a 2022 e teste de 2023 em diante (`TRAIN_PERIOD` e `TEST_PERIOD`).

### Só BTC + ETH

| Estratégia | Período | Retorno total | Por ano | Pior queda | Sharpe | Tempo comprado |
|---|---|---|---|---|---|---|
| Tendência + BTC em alta (regra do painel) | treino | **+293,7%** | 31,5% | −59,1% | 0,8 | 41% |
| Comprar e segurar | treino | +67,4% | 10,8% | −83,1% | 0,5 | 100% |
| Regra antiga (pânico) | treino | −49,5% | −12,8% | −50,7% | −0,7 | 9% |
| Tendência + BTC em alta (regra do painel) | teste | +209,5% | 34,7% | **−29,3%** | 1,0 | 60% |
| Comprar e segurar | teste | +235,0% | 37,6% | −59,9% | 0,9 | 100% |
| Regra antiga (pânico) | teste | +22,0% | 5,4% | −22,8% | 0,4 | 18% |

### As 15 moedas do universo anterior à ampliação

Nesta tabela, tendência = fechamento acima da SMA 200 da própria moeda, sem filtro do BTC.

| Estratégia | Período | Retorno total | Pior queda |
|---|---|---|---|
| Tendência | treino | +375% | −60,8% |
| Comprar e segurar | treino | +132% | −81,7% |
| Regra antiga (pânico) | treino | −31,7% | −36,1% |
| Tendência | teste | +53,5% | −50,4% |
| Comprar e segurar | teste | +164,9% | −67,8% |
| Regra antiga (pânico) | teste | −3,8% | −20,8% |

### Como ler

- **O pânico perdeu dinheiro.** Comprar no pânico rendeu −49,5% no treino com BTC + ETH, contra +67,4% de comprar e segurar. Por isso, virou só um aviso.
- **A tendência rendeu mais no treino e menos no teste, com metade da queda.** No teste, comprar e segurar BTC + ETH rendeu um pouco mais (+235% contra +209,5%), mas passou por uma queda de −59,9%, contra −29,3% da regra. A vantagem da regra está em ser mais fácil de suportar, não em render mais.
- **Nas 15 moedas, a regra não compensa no teste** (+53,5% contra +164,9%). Por isso, o sinal de compra da regra SMA 200 vale só para BTC e ETH. As outras moedas passam pela seleção, que tem backtest próprio.
- **A regra erra muito e acerta pouco.** Das 61 operações simuladas em BTC e ETH, 26% terminaram no lucro, com resultado médio de +25%. As perdas são pequenas, porque a regra sai cedo, e alguns ganhos são enormes (+318% no BTC em 2020–2021). Quem não aguenta ver várias pequenas perdas seguidas dificilmente segue a regra.

O painel mostra a comparação do pipeline do dia (`performance.parquet`). Ela usa a regra do painel (tendência + BTC em alta + STOP) também para as 15 moedas, então os números do painel diferem um pouco dos da tabela acima: treino +383% e teste +52%. A diferença vem do filtro do BTC e do STOP de −20%.

**Reproduzir:**

```bash
uv run python research/strategy_comparison.py
```

O script lê a base local e avalia sete estratégias nos dois universos e períodos: comprar e segurar, pânico, tendência, tendência + BTC, cruzamento de médias, momento de 90 dias e compra de queda dentro da alta. Em seguida, imprime as tabelas.

---

## Laboratório de estratégias

O laboratório responde se alguma outra ideia merece entrar. O sinal do painel não muda com nada daqui.

```bash
uv run python research/strategy_lab.py
```

**Protocolo.**

- Treino de 2018 a 2020: livre para olhar.
- **Validação de 2021 a 2022:** é só aqui que os parâmetros são escolhidos, pelo maior Sharpe de cada estratégia, com pelo menos 3 operações.
- **Teste de 2023 em diante:** só mede.

A grade completa de parâmetros (só treino e validação) fica em `data/research/strategy_lab_grid.parquet`. Os resultados ficam em `data/research/strategy_lab.parquet`, e uma cópia vai para o painel.

**Estratégias.** São as sete de `strategy_comparison.py` e mais cinco novas: DCA fixo (aporte semanal), rompimento de Donchian, reversão de Bollinger, RSI sobrevendido e rompimento com confirmação de volume. Cada uma é uma função pura `signal(market, **params) -> posições 0/1` em [`research/lab.py`](../research/lab.py).

**Referência aleatória.** Cada estratégia é comparada com 200 sorteios de sementes fixas (1000 a 1199). Os sorteios têm a mesma exposição e as mesmas durações de operação, mas em dias deslocados ao acaso (deslocamento circular por moeda). A coluna `beats_random_pct` mostra em quantos sorteios a estratégia rendeu mais.

### Resultado no teste (2023 em diante), BTC + ETH

Ordenado por Sharpe. Os parâmetros vêm da validação.

| Estratégia | Parâmetros | Total | Ao ano | Pior queda | Sharpe |
|---|---|---|---|---|---|
| Tendência + BTC em alta (regra do painel) | fixa | +209,5% | 34,7% | −29,3% | 1,0 |
| Tendência (> SMA 200) | fixa | +197,7% | 33,4% | −29,3% | 1,0 |
| Momento 90 dias > 0 | fixa | +176,1% | 30,7% | −32,0% | 0,9 |
| Comprar e segurar | fixa | +235,0% | 37,6% | −59,9% | 0,9 |
| Rompimento + volume | n=55, k=1,5 | +94,5% | 19,2% | −28,0% | 0,7 |
| Donchian | n=100 | +55,3% | 12,3% | −34,0% | 0,5 |
| Cruzamento SMA 50 > SMA 200 | fixa | +48,6% | 11,0% | −41,0% | 0,5 |
| Bollinger (reversão) | n=20, k=1,5 | +42,5% | 9,8% | −50,9% | 0,5 |
| DCA fixo | a cada 7 dias | +31,0% | 7,4% | −54,6% | 0,4 |
| Regra antiga (pânico) | fixa | +22,0% | 5,4% | −22,8% | 0,4 |
| RSI sobrevendido | 25 / 50 | +14,3% | 3,6% | −21,2% | 0,3 |
| Queda dentro da alta | fixa | +4,9% | 1,3% | −21,3% | 0,2 |

| Estratégia | Comprado | Operações | Acerto | Fator de lucro | Taxas | Bate o aleatório |
|---|---|---|---|---|---|---|
| Tendência + BTC em alta | 60% | 30 | 33% | 6,9 | 2,9% | 81,5% |
| Tendência (> SMA 200) | 61% | 30 | 37% | 7,0 | 2,9% | 79,5% |
| Momento 90 dias > 0 | 59% | 51 | 37% | 3,3 | 5,0% | 78,5% |
| Comprar e segurar | 100% | 2 | 100% | ∞ | 0% | não se aplica |
| Rompimento + volume | 49% | 20 | 55% | 3,5 | 1,9% | 63,0% |
| Donchian | 44% | 11 | 45% | 3,2 | 1,0% | 45,0% |
| Cruzamento SMA 50 > SMA 200 | 59% | 10 | 70% | 2,9 | 0,9% | 23,0% |
| Bollinger (reversão) | 32% | 73 | 75% | 1,5 | 7,1% | 47,5% |
| DCA fixo | 57% | 396 aportes | 58% | 4,7 | 0,1% | não se aplica |
| Regra antiga (pânico) | 18% | 10 | 80% | 2,6 | 1,0% | 37,0% |
| RSI sobrevendido | 9% | 10 | 50% | 2,1 | 1,0% | 54,5% |
| Queda dentro da alta | 6% | 11 | 36% | 1,3 | 1,1% | 42,0% |

"Taxas" = taxas pagas em % do capital.

### Como ler

- **Nada novo superou a regra do painel no teste.** Das cinco novas, nenhuma passou de 0,7 de Sharpe, abaixo do 1,0 da tendência. Os parâmetros da validação não se sustentaram: o Donchian (n=100) teve Sharpe de 1,2 na validação e 0,5 no teste, com apenas 3 operações na validação.
- **Comprar e segurar rendeu mais** (+235,0% contra +209,5%), com quase o dobro da queda (−59,9% contra −29,3%).
- **Contra o acaso, a vantagem não é esmagadora.** A regra do painel bateu 81,5% dos sorteios com a mesma exposição. Ou seja, 18,5% dos sorteios fizeram o mesmo ou melhor. Com uma única história de mercado e poucas operações independentes, isso é compatível com sorte parcial. O cruzamento de médias (23%) rendeu menos que a maioria dos sorteios.
- **Nas 15 moedas, o quadro é pior para as estratégias de tendência.** A regra do painel bate só 23% dos sorteios no teste. O rompimento com volume (n=20, k=1,5) só empatou em Sharpe com comprar e segurar (0,7 os dois), com +98,4% contra +164,9%.
- **Custos importam.** O Bollinger fez 73 operações e pagou 7,1% do capital em taxas. O DCA semanal paga pouco por aporte, mas perdeu na validação (−43%) e rendeu +31% no teste, abaixo de comprar e segurar.
- **Limitações específicas.** A validação tem só dois anos e, em BTC + ETH, de 3 a 7 operações nas estratégias de rompimento e RSI, então os parâmetros escolhidos nela são ruidosos.

**Não implementadas:** pairs trading (arbitragem estatística entre pares), rotação entre moedas (por exemplo, comprar sempre as de maior momento) e ensemble (combinar vários sinais).

---

## Validação da seleção com aporte

A seleção (veja [strategies.md](strategies.md#2-seleção-de-oportunidades)) tem dois níveis de validação.

### 1. Backtest dentro do pipeline

[`selection_backtest.py`](../src/transformers/selection_backtest.py) refaz a seleção e o aporte do pipeline com as mesmas funções, o mesmo orçamento, o mesmo arredondamento e a mesma ordem mínima. O rebalanceamento é a cada 7 dias (`SELECTION_REBALANCE_DAYS`), e uma moeda que continua na carteira só é reajustada se o peso-alvo mudar mais de 5 pontos percentuais (`REBALANCE_BAND`).

O resultado é comparado, já com custos (taxa, spread estimado e slippage), com estas referências:

| Referência | O que é |
|---|---|
| Seleção com peso igual | As mesmas moedas, com valor igual por moeda |
| Momento simples | As 3 que mais subiram em 90 dias |
| Regra SMA 200 | Em todas as moedas |
| Comprar e segurar | Todas as moedas |
| Só BTC | Comprar e segurar Bitcoin |

O resultado vai para `selection_backtest.parquet`, para a aba **Seleção** do painel e para a frase de evidência do Telegram (campo `evidence`). Essa frase diz automaticamente quando a vantagem não está demonstrada.

> [!IMPORTANT]
> **Correção metodológica de 16/10/2026 (motor `weights-2`).** A faixa de tolerância de 5 pontos percentuais do motor deixava a exposição bruta passar de 100% (até 118%) e o caixa das moedas que saíam parado (comprar e segurar ficava 57% investido). O motor agora vai direto aos alvos quando manter as posições ultrapassaria o alvo total ou deixaria mais que a faixa em caixa. **A seleção quase não muda; os baselines largos mudam.** Comparação antes e depois em [AUDIT.md](AUDIT.md#f2-backtesting-e-execução); teste de regressão em `tests/test_engine.py`. Os números abaixo já usam o motor corrigido; os da execução de 15/10/2026 (15 moedas, motor antigo) foram substituídos.

**Resultado com dados reais (execução de 16/10/2026, estudo completo).** Base local com **32 moedas**, dados até 2026-10-15. Períodos: treino 2018–2020, validação 2021–2022 e teste de 2023-01-01 a 2026-10-15.

| Estratégia | Sharpe treino | Sharpe validação | Sharpe teste | Ao ano (teste) | Pior queda (teste) | Investido (teste) | Custos (teste) |
|---|---|---|---|---|---|---|---|
| Seleção (aporte por volatilidade) | 0,74 | 1,24 | 0,70 | 16,0% | −26,1% | 42% | 10,5% |
| Seleção com peso igual | 0,29 | 1,23 | 0,35 | 6,0% | −44,3% | 57% | 15,4% |
| Momento simples | 0,58 | 0,65 | 0,98 | 59,6% | −81,6% | 99% | 22,0% |
| Regra SMA 200 em todas | 0,14 | 1,53 | 0,56 | 14,9% | −53,7% | 38% | 5,1% |
| Comprar e segurar todas | 0,48 | 0,70 | 0,66 | 24,1% | −77,7% | 100% | 1,0% |
| Só BTC | 0,90 | −0,24 | 1,13 | 51,9% | −53,0% | 100% | 0,2% |
| DCA fixo semanal (motor do laboratório, só taxa) | 0,82 | −0,37 | 0,26 | 2,5% | −65,6% | 53% | 0,1% |

**Como ler.** Pela regra definida antes do teste, **a vantagem da seleção não está demonstrada**: no teste ela não superou o momento simples (0,98) nem só BTC (1,13) em retorno por risco, depois dos custos. Superou comprar e segurar (0,66), a regra SMA 200 (0,56) e o DCA, mas essas comparações melhoraram com a correção do motor e não bastam sozinhas. Observações:

- A queda menor vem em boa parte de ficar fora do mercado: a seleção esteve comprada, em média, 10% do tempo no treino, 14% na validação e 42% no teste. Em 2018 e 2022 não comprou nada, e nesses anos comprar e segurar perdeu 71% e 74%.
- Nos anos fortes de alta (2020, 2021, 2023) ela ficou bem abaixo de comprar e segurar e de só BTC (por exemplo, 2023: −0,5% contra +144% e +151%).
- No teste a seleção pagou 10,5% do capital em custos estimados (114 entradas), contra 1,0% de comprar e segurar.
- O aporte por volatilidade foi igual ou melhor que o peso igual nos três períodos de retorno ajustado (0,74 contra 0,29, 1,24 contra 1,23, por pouco, e 0,70 contra 0,35).
- Todas as janelas pertencem a uma única história de mercado, e o período de teste **já foi consultado em fases anteriores**: o resultado é histórico e exploratório, não prospectivo.

### 2. Estudo completo (`research/selection_study.py`)

```bash
uv run python research/selection_study.py
```

Executado em 16/10/2026 sobre a base real (32 moedas); grava em `data/research/selection_study.parquet`. Leitura de cada seção (exploratória, sem intervalos de confiança nem correção de múltiplas comparações):

| Seção | Resultado |
|---|---|
| **Referência aleatória** (100 sorteios com a mesma exposição e giro, moedas sorteadas entre as elegíveis) | A seleção superou em Sharpe **96%** dos sorteios no treino, **60%** na validação e **92%** no teste. Com uma só história de mercado, isso é compatível com alguma habilidade e com sorte parcial; não é prova |
| **Filtro de regime do BTC** (bloquear é o padrão) | Teste: bloquear 0,70, reduzir 0,67, desligado 0,71. Validação: bloquear 1,24, reduzir 1,23, desligado 0,95. Nenhuma variante tem vantagem consistente em treino **e** validação sobre o padrão; o padrão `bloquear` fica |
| **Ano a ano** (walk-forward descritivo) | A seleção ficou sem posição em 2018 e 2022; positiva em 2020, 2021, 2024, 2025 e 2026; levemente negativa em 2019 (−2%) e 2023 (−0,5%). Nenhuma estratégia vence todos os anos. Anos civis são correlacionados e não contam como amostras independentes |
| **Regimes de volatilidade do BTC** (limiares de 30 dias medidos no treino) | Poucos dias em volatilidade alta no teste (45), então a leitura por regime não sustenta conclusão |
| **Sensibilidade de pesos e limiares** (só treino e validação) | Sharpe de treino entre 0,59 e 0,89 e de validação entre 0,95 e 1,31 nas oito variantes; sem mudança de ordem que justifique alterar o padrão. O alvo de volatilidade de 20% reduz muito a exposição (6,7% investido) |
| **Redundância dos componentes** | Correlações de Spearman na saída; a estabilidade ficou sem valor (`NaN`) no treino por falta de variação entre poucas moedas elegíveis. Não investigado |
| **Viabilidade com R$ 100** | 460 rebalanceamentos, 210 com aporte (46%), nenhum aporte zerado por ordem mínima ou custo, 3 com alvo teórico acima do orçamento; aporte médio de R$ 54,95 |

**Regra de leitura definida antes do teste:** se a seleção não superar, **no teste**, comprar e segurar e o momento simples em retorno por risco depois dos custos, a vantagem não está demonstrada. Resultado: superou o primeiro e **não** o segundo. **Não demonstrada.**

---

## Limitações de todos os backtests

- **Viés de sobrevivência.** O universo é formado por moedas que existem hoje. Moedas que quebraram (como LUNA e FTT) ou saíram do topo não estão na amostra, o que favorece qualquer estratégia de comprar moedas, principalmente altcoins.
- **Uma única história de mercado.** São poucos ciclos (dois grandes ciclos de alta e baixa do BTC). Uma regra que funcionou neles pode não funcionar no próximo.
- **Treino e teste reduzem o risco de ajustar a regra aos dados, mas não o eliminam.**
- **Execução ideal.** Compra e venda exatamente no fechamento, sem impostos (ganho de capital, IR sobre vendas).
- **Custos estimados.** Spread e slippage são hipóteses (`SPREAD_TIERS`, `SLIPPAGE`), não medidas, porque as fontes integradas não têm livro de ofertas.
- **A média de 200 dias reage devagar.** A regra compra depois da virada e vende depois do topo.

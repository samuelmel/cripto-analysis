# Carteiras simuladas em reais (dinheiro fictício)

Objetivo: acompanhar, todo dia pelo Telegram, quanto cada "robô" estaria ganhando ou perdendo se tivesse investido de
verdade. **Nada de dinheiro real:** o sistema não tem integração com corretora e nenhuma ordem é enviada. É contabilidade
de um caixa fictício de R$ 1.000,00 por carteira.

Este placar **não prova que nenhuma estratégia funciona**. Poucos meses de uma carteira não distinguem habilidade de sorte
(ver `docs/ml_study.md` e `docs/paper_portfolio.md`). Ele serve para acompanhar o que cada regra teria feito.

## As quatro carteiras (`src/transformers/sim_wallet.py`)

| Carteira | Regra |
|---|---|
| **PAINEL** | Segue a recomendação diária. Compra `allocation_brl` reais de cada moeda `selected` que a carteira ainda não tem (nem com ordem pendente). Vende a posição inteira quando `position_advisor.advise` (as mesmas regras de saída das posições reais, `docs/exit_rules.md`) devolve `VENDER`. |
| **IA** | Modelo `G_GBM` das previsões em sombra (`docs/ml_study.md`); no dia em que o Fear & Greed falta, `G_GBM_SEM_FNG`. Todo dia compra as 5 de maior probabilidade (`in_top_k`) com 1/30 do capital inicial dividido entre elas (≈ R$ 6,67 cada). Cada lote é vendido 30 dias depois. **A IA está em modo sombra: nenhum modelo foi validado.** |
| **REVERSAO** | **Estratégia experimental, sem estudo.** Só nos dias em que o BTC fecha acima da própria SMA 200 (`regime_up`), compra as 5 moedas do universo point-in-time do dia com o **pior** retorno de 90 dias, com o mesmo lote da IA. Cada lote é vendido 30 dias depois, em qualquer regime. Não há evidência de que funcione. |
| **SO_BTC** | No primeiro dia compra R$ 1.000,00 de BTC e segura. Nunca vende. Referência. |

As carteiras começam no primeiro dia em que o registro tem decisões: nada do passado entra no placar.

## Execução honesta

Como no motor do projeto (`backtest_engine`), a decisão sai do **fechamento do dia D** e a execução é na **abertura de D+1**
(a ordem fica `PENDENTE` até esse candle existir; a mensagem lista as pendentes):

- compra: abertura × (1 + meio-spread + slippage); venda: abertura × (1 − meio-spread − slippage);
- taxa de `costs.CostModel` sobre o valor negociado; o valor em R$ de uma compra **já inclui** a taxa;
- sem alavancagem e sem caixa negativo: compra que não cabe no caixa fica `NAO_EXECUTADA`, com o motivo
  (`caixa insuficiente`), e aparece na mensagem. Vendas executam antes das compras do mesmo dia;
- sem preço de abertura no dia (candle ausente), a ordem também fica `NAO_EXECUTADA`.

Consequência a conhecer: como o ciclo de compra e venda custa taxa e spread, o caixa da IA e da Reversão fecha o mês com um
pouco menos do que o lote seguinte pede, e parte das compras do 31º dia em diante pode ficar sem caixa (a menos que os
preços subam). Isso é o comportamento pedido (sem caixa negativo, sem compra parcial); o contador "ordem(ns) não
executada(s)" da mensagem mostra quantas foram.

## Moeda

Os preços são em USDT; os valores são mostrados em reais pela cotação do **USDT/BRL da própria Binance**
(`update_base` baixa o par e grava em `data/market`, fora de `UNIVERSE` e fora da análise).

- Compra e venda convertem R$ ↔ USDT pela cotação da **abertura** do dia da execução. O valor do dia usa o **fechamento**
  do último dia de dados: quantidade × fechamento × cotação.
- **Nunca se inventa cotação.** Sem cotação no dia da execução, a ordem não é executada. Sem cotação no dia da avaliação, a
  mensagem avisa "cotação do real indisponível" e mostra as posições em USDT (o caixa continua em R$). Como o replay é
  refeito a cada execução, uma cotação que chega depois corrige o histórico.
- **O custo de converter reais em USDT (spread e taxa da conversão) não é simulado.** Quem de fato comprasse USDT pagaria isso
  na entrada e na saída.

## Registro e replay

- Todo dia só as **decisões** de cada robô (carteira, dia, moeda, lote, COMPRA/VENDA, valor em R$) vão para
  `data/state/sim_decisions.parquet` (repositório de estado, `docs/state.md`). É append-only, **idempotente por chave** (carteira,
  dia, moeda, lado), com cadeia de hash igual à das previsões da IA (`model_shadow`), e só grava com `--record-state`.
  Reexecutar o mesmo dia não muda nada; alterar uma linha antiga quebra a cadeia e nada é gravado.
- Posições, caixa e valor **não são guardados**: a cada execução `sim_wallet.replay` refaz as carteiras do zero a partir das
  decisões e dos preços. Qualquer pessoa com os mesmos dados chega ao mesmo número.

## Segurança do pipeline

A simulação nunca derruba o pipeline: um erro vira nota no relatório (como `shadow_predictions` e `paper_outputs`). Ela não
altera sinais, aporte, recomendação nem a mensagem principal do Telegram; a mensagem das carteiras é separada e vem depois
do resumo do dia.

## Onde acompanhar

- Telegram: "💼 CARTEIRAS SIMULADAS (dinheiro fictício, sem ordens reais)", depois do resumo.
- Arquivos: `frontend/public/sim_wallets.parquet` (resumo por carteira) e `sim_wallet_positions.parquet` (posições por
  moeda). O painel ainda não os mostra.

## Limitações

- A abertura do dia seguinte é uma aproximação do preço alcançável; spread e slippage são estimados por faixa de volume, não
  medidos.
- Sem custo de conversão R$ ↔ USDT, sem impostos e sem limites de corretora.
- Moeda que para de negociar não é baixada nesta simulação: a posição fica avaliada no último fechamento conhecido.
- Dias sem execução do pipeline não geram decisões (a IA, por exemplo, não compra naquele dia).

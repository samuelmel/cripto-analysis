# Smart DCA x DCA fixo (BTC e ETH, instâncias independentes): protocolo `dca-v1`

Fixado em commit ANTES de qualquer execução. Dinheiro fictício; nenhuma ordem real. Código: `research/dca_study.py`.

## Pergunta
Com o mesmo fluxo de caixa e caixa finito, comprar lotes maiores em quedas (a partir da máxima histórica) entrega mais valor final por real aportado do que comprar um lote fixo toda semana?

## Regras
- **Ativos:** BTC (Bitstamp BTC/USD até 2017-08-16, emendado com Binance BTC/USDT) e ETH (Binance ETH/USDT, desde 2017-08-17). Cada um em simulação totalmente separada.
- **Aporte:** 1 unidade (C) no primeiro dia de cada mês, em caixa. Final da janela: o caixa que sobrou conta pelo valor de face.
- **Compra semanal (decisão no fechamento do domingo, execução na abertura seguinte), custo 0,25% sobre o valor comprado:**
  - Lote semanal do DCA fixo: `L = 12 C / 52` (gasta, no ano, o mesmo que entra). Compra `min(caixa, L)`.
  - Smart DCA: lote-base `b = f × L`, multiplicado por `m` conforme a queda `dd = fechamento / máxima histórica de fechamento até o dia − 1`:
    `dd > −20%` -> 1x; `−40% < dd <= −20%` -> 3x; `dd <= −40%` -> 5x. Compra `min(caixa, m × b)`. A diferença `L − b` fica de reserva.
  - **Principal: f = 0,5.** Sensibilidade (descritiva): f = 0,25 e f = 0,75. Os multiplicadores e limiares são os pedidos, sem otimização.
- **Janelas:** inícios semestrais (1º de janeiro e 1º de julho) com horizontes de 3 e 5 anos que cabem inteiros na base (BTC desde 2012-01; ETH desde 2018-01). Janelas sobrepostas: não são independentes.
- **Métrica de decisão:** valor final por real aportado = (unidades x último fechamento + caixa) / total aportado. Também: preço médio pago,
  fração do aporte efetivamente investida, caixa ocioso médio e pior queda da razão patrimônio / aportado acumulado.
- **Execução:** o motor `backtest_engine` não aceita aportes durante a simulação; esta pesquisa usa um simulador próprio mínimo com a mesma convenção
  (decisão no fechamento, execução na abertura do dia seguinte, custo de 0,25%). Sem alavancagem, sem venda.

## Critério (fixado agora)
O Smart DCA (f = 0,5) é promissor num ativo só se superar o DCA fixo em valor final por real aportado em **mais de 60% das janelas, nos dois horizontes**,
com diferença média positiva. Caso contrário, rejeitado nesse ativo. Mesmo promissor, não é validado: um único histórico por ativo, janelas sobrepostas, sem IC.

## Limitações
- Um único caminho de preços por ativo, quase todo em alta; vantagem de comprar mais nas quedas é em parte efeito dessa trajetória.
- ETH tem só ~8 anos de história: poucas janelas.
- A máxima histórica usa só a história disponível na base (BTC desde 2011, ETH desde 2017).

## Resultados
(preencher após a execução)

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
Execução de 2026-11-03, dados até 2026-11-01. Valor final por real aportado; "dif" = Smart DCA (f = 0,5) contra DCA fixo.

| Ativo | Horizonte | Janelas | Vitórias do Smart (f=0,5) | Diferença média | Mediana | Pior | Melhor |
|---|---|---|---|---|---|---|---|
| BTC | 3 anos | 24 | 7 (29%) | −2,58% | −0,88% | −17,98% | +4,09% |
| BTC | 5 anos | 20 | 5 (25%) | −3,16% | −1,62% | −16,59% | +1,96% |
| ETH | 3 anos | 12 | 9 (75%) | +1,02% | +0,92% | −0,86% | +4,20% |
| ETH | 5 anos | 8 | 5 (62%) | +0,90% | +1,06% | −0,86% | +3,47% |

Critério (> 60% de vitórias nos dois horizontes e diferença média > 0): **BTC REJEITADO; ETH PROMISSOR**.

Sensibilidade ao lote-base (descritiva): BTC f=0,25: 33% e 45% de vitórias, média −4,83% e −6,39%; f=0,75: 67% e 70%, média +0,34% e +0,18%.
ETH f=0,25: 83% e 100% de vitórias, média +3,64% e +3,42%; f=0,75: 50% e 75%, média +0,88% e +0,72%.

**Leitura:** as diferenças são pequenas (em geral entre −3% e +4% no valor final por real aportado) e o sinal depende do ativo e do lote-base
(no BTC, só f=0,75 empata ou ganha; no ETH, a vantagem é maior com f=0,25). No BTC, o Smart perde principalmente nas janelas que começam em 2012-2013 e 2017, em que
a reserva ficou parada durante a alta: é o custo de oportunidade esperado do caixa finito. O caixa quase sempre acaba investido (86% a 100% do aportado).
O "PROMISSOR" do ETH vem de poucas janelas sobrepostas (12 e 8, de um único caminho de 8 anos), então não é evidência de vantagem estrutural.
Conclusão: o Smart DCA não demonstra vantagem consistente sobre o DCA fixo; se entrar nas carteiras simuladas, só como robô experimental.
Sem IC nem correção para múltiplos testes; janelas sobrepostas.

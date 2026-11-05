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

## Apêndice: `research/dca_simulator.py` (aporte semanal, inícios anuais 2013-2022)

Variante pedida depois, com regras fixadas no cabeçalho do código antes da execução (aporte de R$ 100 por semana no fechamento do domingo, execução na
abertura seguinte, 0,25%, lote-base f = 0,5, multiplicadores 1x/3x/5x, janelas de 3 e 5 anos com início em 1º de janeiro). Execução de 2026-11-03.

| Ativo | Horizonte | Janelas | Vitórias do inteligente | Diferença média | Pior | Janelas fatais (perda > 5%) |
|---|---|---|---|---|---|---|
| BTC | 3 anos | 10 | 1 (10%) | −4,23% | −18,75% | 2013, 2016, 2017 |
| BTC | 5 anos | 9 | 1 (11%) | −4,35% | −17,48% | 2013, 2017 |
| ETH | 3 anos | 5 | 4 (80%) | +0,01% | −0,10% | nenhuma |
| ETH | 5 anos | 4 | 4 (100%) | +0,18% | 0,00% | nenhuma |

- **BTC REJEITADO**, e pior que no protocolo mensal acima. Nas janelas fatais o ativo subiu 6x a mais de 1.000x enquanto a reserva (3% a 8% do patrimônio em média)
  ficava parada e o preço médio saía 13% a 23% mais caro que o do fixo.
- **ETH "PROMISSOR" pelo critério, mas sem significado prático:** a diferença média é de +0,01% a +0,18%. O ETH ficou quase sempre mais de 20% abaixo da sua máxima,
  então o inteligente compra 3x ou 5x, esvazia o cofre rapidamente e passa a gastar só o aporte da semana, ou seja, se comporta como o DCA fixo.
  Poucas janelas (5 e 4) e sobrepostas. Não é evidência de vantagem.
- **Isolamento (caixa infinito, mesmo gasto total):** o preço médio cai em média 1,1% (3 anos) e 4,7% (5 anos) no BTC, e 10% a 11% no ETH, o que
  melhoraria o valor final em 5% a 13%. Mas isso exige caixa que o orçamento semanal não tem e a reescala usa o total da janela, conhecido só depois. É um teto teórico, não uma regra operável.
- Sensibilidade (descritiva): f = 0,75 reduz a perda no BTC (−1,3% de média) mas não vira vitória; f = 0,25 piora (−5,8% a −6,8%).

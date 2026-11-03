# Estudo de força relativa entre moedas (momentum x reversão): protocolo `xs-v1`

Fixado em commit ANTES de qualquer execução. Mudar qualquer item é um protocolo novo (`xs-v2`). Dinheiro fictício; nenhuma ordem real.
Código: `research/cross_sectional_study.py`. Resultados: seção final, preenchida só depois da execução.

## Pergunta
Entre as moedas do universo do dia, o mercado recompensa comprar as mais fortes (momentum) ou as mais fracas (reversão)?

## Protocolo
- **Universo:** `entry_signals.build_panel` (point-in-time: o conjunto de moedas elegíveis em cada dia, por volume medido
  até o dia, inclusive moedas que depois pararam de negociar). Só o arquivo oficial da Binance em USDT (`data/archive`),
  com `clean_candles` e `split_discontinuities` (continuidade-v1). Não é a lista das 7 moedas atuais (viés de sobrevivência).
  O ranking é feito só entre as moedas que são membros do universo no dia da decisão e têm candle.
- **Frequência:** candles diários. Rebalanceamento semanal: decisão no fechamento de cada domingo (UTC), execução na abertura seguinte.
- **Força:** retorno acumulado em `L` dias de calendário, `L` em {7, 14, 30, 90}.
- **Direção:** momentum (as `k` de maior retorno) ou reversão (as `k` de menor retorno).
- **Tamanho:** `k` em {1, 5, 10}, peso igual 1/k, 100% investido (cada posição 1/k; menos de k elegíveis deixa o resto em caixa).
- **Total: 4 x 2 x 3 = 24 configurações.**
- **Motor:** `backtest_engine` único (`next-open-v1`). Custo: 0,25% por lado (taxa 0,10% + meio-spread fixo 0,10% + slippage 0,05%),
  cobrado só sobre o valor efetivamente negociado (giro): moeda mantida na carteira não paga custo de entrada de novo;
  só se negocia a diferença entre o peso atual e o alvo. Sem alavancagem, sem venda a descoberto.
- **Moeda que desaparece:** se uma moeda em carteira fica mais de 7 dias sem candle (fim do episódio, `EPISODE_GAP_DAYS`), o motor
  baixa a posição com recuperação 0 (perda total do último preço marcado), sem custo de venda.
- **Divisão:** In-Sample do primeiro domingo com >= 10 membros com retorno de 90 dias até 2022-12-31; Out-of-Sample cego de
  2023-01-01 até o fim da base. Cada janela começa em caixa e é simulada separadamente.
- **Seleção (só com o In-Sample):** o maior Calmar (CAGR / |drawdown máximo|) do In-Sample, em dois escolhidos: o melhor
  de momentum e o melhor de reversão (o vencedor geral é um dos dois). Os escolhidos são avaliados UMA vez no Out-of-Sample.
  A tabela Out-of-Sample das 24 configurações é impressa só como descrição e não escolhe nada.
- **Referências (mesmo motor, custo e janelas):** MERCADO (todas as moedas membro, peso igual, rebalanceado semanal) e BTC (comprar e segurar).
- **Métricas:** CAGR, Calmar, Sharpe (diário, 365), drawdown máximo, giro anual e custo total.

## Regra de decisão (fixada agora)
Uma direção só é considerada promissora se o escolhido dela, no Out-of-Sample, superar o MERCADO em Calmar E em Sharpe.
Caso contrário, é rejeitada. Mesmo promissora, não é validada: faltam intervalo de confiança e correção para múltiplos testes
(24 configurações), que seriam o passo seguinte (`research/validation_study.py`).

## Limitações conhecidas
- O histórico já foi explorado no desenvolvimento do projeto (inclusive o IC de reversão em 90 dias): não é teste intocado.
- O universo é o das moedas do arquivo da Binance em USDT; moedas fora da Binance não aparecem.
- Meio-spread fixo (hipótese, não medido). Baixa por perda total é conservadora para moedas deslistadas.

## Resultados
Execução de 2026-11-03, dados até 2026-11-01, 273 séries que passaram pelo universo. IS 2019-06-02 a 2022-12-31; OOS 2023-01-01 a 2026-11-01.

**Protocolo xs-v1 (baixa com perda total).** Escolhidos no IS (maior Calmar): momentum = MOM L14 top10; reversão = REV L90 top10.

| Out-of-Sample | CAGR | Calmar | Sharpe | Drawdown máx. | Capital final (1 = início) |
|---|---|---|---|---|---|
| Momentum L14 top10 | −39,7% | −0,43 | −0,26 | −93% | 0,14 |
| Reversão L90 top10 | −21,5% | −0,24 | 0,07 | −88% | 0,40 |
| MERCADO (referência) | −31,9% | −0,35 | −0,16 | −92% | 0,23 |
| BTC (comprar e segurar) | +49,9% | 0,94 | 1,11 | −53% | 4,72 |

Regra de decisão: momentum REJEITADA; reversão PROMISSORA (supera o MERCADO em Calmar e Sharpe). Média das 12 configurações de cada
direção no OOS (descritivo): momentum CAGR −75% / Sharpe −0,57; reversão CAGR −62% / Sharpe −0,57.

**Sensibilidade pós-hoc (fora do protocolo; baixa com recuperação de 100% do último preço):** a seleção no IS muda
(momentum L30 top10, reversão L90 top5) e a reversão passa a ser REJEITADA (Calmar −0,25 vs −0,22 do MERCADO; Sharpe 0,09 vs 0,04).
Ou seja, o veredito "promissora" depende da hipótese de perda total nas moedas que somem.

**Leitura:** nenhuma configuração gerou retorno positivo ajustado ao risco; o universo de altcoins perdeu para o BTC no período
(MERCADO −32% ao ano contra BTC +50%). Reversão ficou menos ruim que momentum, mas o "vencedor" só vence uma referência que perde
dinheiro, e a vantagem não resiste à sensibilidade. Não vale levar a regra para os robôs. Sem IC nem correção para múltiplos testes.
Giro anual impresso corrige um erro de relatório da primeira execução (a coluna aparecia zerada; os retornos não mudaram).

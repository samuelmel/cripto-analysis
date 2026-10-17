# Regras de saída das posições: protocolo (fixado antes dos resultados)

Escrito antes de rodar o estudo (`research/exit_rules_study.py`). Nada abaixo muda depois de ver resultado; uma mudança
exige novo registro.

## Regras avaliadas

Todas decidem no **fechamento** do dia `d` (só com dados até `d`) e a venda é simulada no **fechamento seguinte**
(`d+1`), com custos de `config.py` (taxa + spread por faixa de volume + slippage, nos dois lados).

| Regra | Dispara quando |
|---|---|
| `STOP` | o fechamento está 20% (ou mais) abaixo do preço de entrada |
| `TENDENCIA` | o fechamento da moeda fica abaixo da própria SMA 200 |
| `MERCADO` | o fechamento do BTC fica abaixo da SMA 200 do BTC |
| `TRAILING` | o fechamento cai `x` abaixo do maior fechamento desde a entrada (a entrada conta como topo inicial) |

`x` (trailing) é avaliado na grade **{10%, 15%, 20%, 25%, 30%, 40%}**, declarada aqui. Nenhum valor é adotado por
intuição.

## Amostra de operações

Entradas = início de cada episódio de alta da regra SMA 200 (moeda e BTC acima da SMA 200), com a moeda no universo
point-in-time do dia, entrada simulada no fechamento seguinte ao sinal. É a mesma amostra de sinais do estudo de
validação (`docs/signal_validation.md`), em todas as moedas do universo, não só BTC e ETH. Sem retorno inventado: moeda
que para de negociar sai ao último preço; operação aberta no fim do período é encerrada no último fechamento e marcada
como aberta.

| Período | Entradas | Uso |
|---|---|---|
| Desenvolvimento | até 2024-12-31 (operação encerrada à força no último fechamento de 2024) | única base para escolher |
| Teste final | a partir de 2025-01-01 | não escolhe nada; avaliado uma vez |

## Critério de adoção do trailing

Referência: `STOP + TENDENCIA + MERCADO` (as regras já em uso). Para cada `x`, a regra combinada `referência + TRAILING(x)`
é comparada com a referência pela **diferença do retorno líquido por operação** (pareada, mesma operação nas duas).

1. IC e valor-p por bootstrap em blocos (blocos de `ceil(n^(1/3))` operações em ordem de entrada), 2000 reamostragens,
   semente fixa (`config.VALIDATION_SEED`, derivada por `x`); valor-p unilateral (o trailing melhora).
2. **Holm** sobre os 6 valores de `x`, α = 0,05.
3. Adota o `x` com menor valor-p ajustado **somente** se p ajustado < 0,05 e o limite inferior do IC de 95% > 0.
   Senão, **o trailing não é adotado** e a proteção de lucro fica como `ATENÇÃO` informativa (queda desde o topo), sem
   disparar VENDER.
4. Teste final: só pode **revogar**. Se adotado e, no teste final, houver pelo menos 20 operações e a diferença média for
   negativa, o trailing deixa de ser adotado. O teste final nunca promove.

## O que "quanto a regra funcionou" quer dizer

Para cada regra que dispara na referência, no desenvolvimento: nº de disparos, retorno médio e mediano das operações que
ela encerrou, e o **retorno de 30 dias depois da venda** (do preço de venda ao fechamento 30 dias depois). Retorno
posterior negativo = o preço continuou caindo (a venda evitou perda); positivo = a venda abriu mão de ganho. É descrição,
com a participação de disparos seguidos de queda; não é previsão.

## Estados da posição (fixados a priori)

- `VENDER`: alguma regra adotada disparou.
- `ATENÇÃO`: nenhuma disparou, mas alguma está a **metade do caminho**: perda desde a entrada ≥ 10% (metade do stop);
  fechamento até 3% acima da SMA 200 da moeda (`SignalRules.watch_distance`); BTC até 3% acima da SMA 200; queda desde o topo
  ≥ metade de `x` (informativa se o trailing não for adotado, usando `x = 20%`).
- `SEGURAR`: o resto.

O estado é uma recomendação por regra, não uma previsão. Nenhuma ordem real é executada.

## Resultado (desenvolvimento, execução de 2026-10-16)

950 operações em 126 moedas do universo point-in-time (entrada até 2024-12-31). Referência `STOP -20% + TENDENCIA + MERCADO`:

| Regra | Disparos | Retorno médio da operação | Mediana | Preço 30 dias depois da venda (média) | Disparos seguidos de queda |
|---|---|---|---|---|---|
| `TENDENCIA` | 642 | +1,0% | −4,0% | +4,7% | 53% |
| `MERCADO` | 225 | +59,1% | −4,1% | −5,9% | 66% |
| `STOP` (−20%) | 61 | −25,0% | −25,0% | +9,4% | 49% |
| ainda abertas no fim de 2024 | 22 | +53,2% | +39,0% | — | — |

Leitura: o `STOP` não evitou queda posterior na maioria dos casos (49% de quedas depois da venda, com rebote médio de +9,4%):
ele limita a perda por operação, não melhora o retorno. Já `TENDENCIA` e `MERCADO` saem antes de quedas em 53% e 66% dos casos.
O retorno médio por operação (+14,3%) vem de poucos ganhos enormes; a mediana é negativa.

**Trailing: nenhum valor da grade foi adotado.** Em todos os `x` a diferença média contra a referência foi negativa (de −14,0
pontos percentuais com `x = 10%` a −1,9 com `x = 40%`), com `p ajustado = 1,0`; só `x = 40%` tem IC que encosta em zero
(−7,1 a +1,1). O trailing corta justamente os ganhos grandes que sustentam a média. Como nenhum trailing foi adotado, o
teste final **não** foi avaliado nesta etapa. Consequência: a proteção de lucro fica só como `ATENÇÃO` informativa (queda de
10% desde o topo, metade de 20%), sem disparar `VENDER`.

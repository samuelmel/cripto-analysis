# Motor único de backtest: antes e depois

`src/transformers/backtest_engine.py` (`simulate_weights`) é o único núcleo de backtest de carteira. `run_weighted`
(seleção, pesquisa) e `run_portfolio` (posições 0/1 da tendência) são adaptadores sobre ele. Mudanças:

1. **Execução no fechamento seguinte ao sinal** (`EXECUTION_LAG = 1`). Antes, a ordem era executada no próprio
   fechamento do sinal, preço que o sinal já conhecia.
2. **Custos**: ambos os caminhos cobram o custo por lado da moeda (taxa, spread e slippage de `config.py`) sobre a
   mudança real de peso. `run_portfolio` antes cobrava só a taxa sobre a mudança de posição, sem deriva.
3. `ENGINE_VERSION = "engine-3"` (antes `weights-2`).

## Números (período de teste 2023-01-01 a hoje, mesma base local, só a execução muda)

`lag 0` = execução no fechamento do sinal (comportamento antigo, na mesma base); `lag 1` = novo padrão. Retorno
anual %, pior queda %, Sharpe.

| Motor | Estratégia | Anual (0 → 1) | Queda (0 → 1) | Sharpe (0 → 1) |
|---|---|---|---|---|
| pesos | BTC (comprar e segurar) | 51,88 → 51,60 | −52,97 → −52,97 | 1,13 → 1,13 |
| pesos | COMPRAR_E_SEGURAR (todas) | 24,08 → 25,61 | −77,72 → −77,43 | 0,66 → 0,68 |
| pesos | MOMENTO_SIMPLES | 59,60 → 33,93 | −81,58 → −85,79 | 0,98 → 0,76 |
| pesos | SELECAO | 15,99 → 17,69 | −26,06 → −26,10 | 0,70 → 0,77 |
| pesos | SELECAO_PESO_IGUAL | 6,03 → 5,10 | −44,32 → −45,59 | 0,35 → 0,32 |
| pesos | TENDENCIA_SMA200 (semanal) | 14,93 → 9,25 | −53,73 → −54,22 | 0,56 → 0,42 |
| posições | COMPRAR_E_SEGURAR (BTC+ETH) | 37,47 → 37,47 | −59,99 → −59,99 | 0,87 → 0,87 |
| posições | PANICO (BTC+ETH) | 5,31 → 8,11 | −22,87 → −21,32 | 0,36 → 0,48 |
| posições | **TENDENCIA SMA 200 (BTC+ETH, diária)** | **34,78 → 22,42** | −29,34 → −33,02 | **0,98 → 0,72** |

Antes da unificação, `run_portfolio` dava 34,98 %/ano para a tendência (BTC+ETH) no teste; o motor único com
`lag 0` dá 34,78 (a diferença de 0,2 ponto é só o custo da deriva do peso, que o motor antigo não cobrava).

Leitura: executar no fechamento seguinte tira cerca de 12 pontos percentuais por ano da regra principal e quase
metade do MOMENTO_SIMPLES. A conclusão "SMA 200 supera comprar e segurar" já não se sustenta nesses números
(22,4 contra 37,5 %/ano no teste, BTC+ETH). O período de teste continua sendo o 2023+ já consumido; isto descreve a
sensibilidade à execução, não uma validação.

Reprodução: `tests/test_backtest_engine.py` (execução em t+1, sem look-ahead, concordância dos dois adaptadores em
casos sintéticos, `lag 1` = `lag 0` com alvos deslocados) e o script de comparação descrito acima (mesmo
`evaluate_selection`/`performance_summary` com `execution_lag` 0 e 1).

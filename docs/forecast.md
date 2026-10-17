# Previsão estatística

O painel e o relatório mostram uma **faixa provável de preço** para BTC e ETH em 1, 7 e 30 dias. Este documento explica como ela é calculada e por que deve ser lida como **medida de incerteza, não como palpite de direção**.

> [!IMPORTANT]
> **Conclusão atual:** nenhum modelo superou a referência ingênua (passeio aleatório, que equivale a "o preço futuro é o de hoje, com ruído") em nenhum dos 6 casos testados. Quando isso acontece, o painel mostra "sem vantagem demonstrada sobre o preço de hoje".

## O que é publicado

[`src/transformers/forecast.py`](../src/transformers/forecast.py) é uma função pura: não usa rede, disco nem relógio, depende só de numpy e pandas e recebe a semente injetada (`FORECAST_SEED`). Para BTC e ETH, em 1, 7 e 30 dias, ela grava em `frontend/public/forecast.parquet`:

- os percentis P10, P50 e P90 do retorno e do preço. P10–P90 é a faixa em que o preço deveria cair em 80% das vezes;
- o retorno estimado (a mediana) e a volatilidade;
- o método, a janela e o número de observações;
- a avaliação no teste contra a referência, nas colunas `beats_baseline`, `coverage_ok` e `verdict`.

Se o dado de uma moeda estiver desatualizado, ela não recebe previsão. Uma previsão antiga nunca é apresentada como atual.

## Métodos

| Método | Ideia |
|---|---|
| **Passeio aleatório** (referência) | Sem tendência: volatilidade da janela × raiz do horizonte. É "o preço de hoje com ruído". |
| **Bootstrap em blocos** | Reamostra blocos de retornos históricos, preservando parte da dependência entre dias. |
| **Volatilidade EWMA** (RiskMetrics) | Dá mais peso aos dias recentes para estimar a volatilidade. |

O modelo publicado é o melhor entre bootstrap e EWMA na validação. Assim, o EWMA só aparece quando os dados o justificam.

## Validação walk-forward

- Em cada data de origem, a previsão usa **só dados até aquele dia**. O realizado são os dias seguintes.
- As origens ficam a cada *h* dias, para que as janelas não se sobreponham, e o realizado tem de terminar dentro do próprio período. A validação nunca olha dentro do teste.
- Janela, bloco e lambda (e também a janela da referência) são escolhidos na **validação, de 2021 a 2022**, pela perda de quantis (*pinball loss*).
- O **teste, de 2023 em diante, é lido uma única vez**, com os parâmetros já escolhidos.

**Regra de veredito.**

- `beats_baseline` só é verdadeiro se o modelo vencer a referência nas três medidas do teste: perda de quantis, MAE e RMSE.
- `coverage_ok` exige que a faixa P10–P90 acerte cerca de 80% das vezes, dentro do intervalo binomial de 95% para o número de janelas.

## Resultado no teste

Os valores são retornos logarítmicos em pontos percentuais e aparecem como "modelo / referência". Cobertura nominal: 80%. No acerto direcional, a referência conta como "sempre alta".

| Ativo | Horizonte | Método (parâmetros) | Janelas | MAE | RMSE |
|---|---|---|---|---|---|
| BTC | 1 dia | EWMA (janela 365, λ 0,94) | 1382 | 1,69 / 1,68 | 2,42 / 2,41 |
| BTC | 7 dias | EWMA (janela 365, λ 0,99) | 197 | 4,74 / 4,63 | 6,41 / 6,35 |
| BTC | 30 dias | Bootstrap (janela 365, bloco 10) | 46 | 10,97 / 10,03 | 14,28 / 13,86 |
| ETH | 1 dia | EWMA (janela 365, λ 0,94) | 1382 | 2,26 / 2,26 | 3,28 / 3,27 |
| ETH | 7 dias | Bootstrap (janela 180, bloco 5) | 197 | 6,59 / 6,27 | 8,76 / 8,49 |
| ETH | 30 dias | Bootstrap (janela 365, bloco 10) | 46 | 14,75 / 13,31 | 19,22 / 17,94 |

| Ativo | Horizonte | Acerto direcional | Cobertura | Largura da faixa | Vence a referência |
|---|---|---|---|---|---|
| BTC | 1 dia | 51,4% / 50,6% | 83,0% / 85,7% | 5,96 / 6,51 | não |
| BTC | 7 dias | 51,3% / 51,3% | 84,3% / 83,2% | 16,7 / 17,2 | não |
| BTC | 30 dias | 47,8% / 50,0% | 69,6% / 80,4% | 34,7 / 35,8 | não |
| ETH | 1 dia | 50,9% / 50,9% | 83,5% / 85,7% | 8,06 / 8,86 | não |
| ETH | 7 dias | 48,7% / 50,3% | 75,1% / 83,2% | 20,5 / 22,5 | não |
| ETH | 30 dias | 41,3% / 50,0% | 76,1% / 82,6% | 46,8 / 48,6 | não |

### Como ler

- **Nenhum modelo superou a referência em nenhum dos seis casos.**
- O EWMA de 1 dia teve perda de quantis um pouco menor, porque a faixa é mais estreita e reage à volatilidade. Mas o MAE e o RMSE ficaram iguais ou piores.
- A cobertura das faixas de 1 dia fica acima do nominal (83% a 86%, contra 80%), porque a distribuição normal não captura as caudas pesadas.
- Em 30 dias, os modelos pioram de forma clara, com acerto direcional de 41% a 48%.

## Limitações

- **Viés de sobrevivência:** BTC e ETH são as sobreviventes mais fortes do mercado.
- **Poucas janelas independentes em 30 dias:** são 46 por ativo no teste, com erro-padrão da cobertura de cerca de 6 pontos percentuais. Diferenças pequenas não são conclusivas.
- **Uma única história de mercado,** com dois ciclos.
- **Sem impostos, taxas nem execução.**
- O passado não garante o futuro, e nada disso é recomendação de investimento.

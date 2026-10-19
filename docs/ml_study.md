# Estudo da IA (modelos de machine learning): protocolo fixado antes dos resultados

Escrito e commitado **antes** de qualquer execução sobre dados reais (protocolo `ml-v1`). Mudar qualquer item depois de
ver resultado é um protocolo novo, com outro nome, e o resultado deste continua publicado.

## Pergunta

Um modelo de machine learning consegue escolher, entre as moedas do universo do dia, as que vão render mais nos 30
dias seguintes, **melhor que a média do universo** e **melhor que uma regra simples de momento**, fora da amostra e
líquido de custos?

Não se pergunta "o modelo acerta a direção do preço": a pergunta é de seleção relativa, que é o uso possível no
produto (ordenar candidatas).

## Dados

- Candles diários de todos os pares USDT do arquivo oficial da Binance (`data/archive`, inclusive os que pararam de
  negociar), com o filtro de continuidade `continuidade-v1` (`series_continuity.split_discontinuities`).
- Universo de cada dia: o point-in-time do estudo dos sinais de entrada (`entry_signals.build_panel`, `EntryRules`).
- Fear & Greed: `data/market/fng` ou, na falta, a cópia da branch `state` (`fng_history.parquet`). **Sem o índice, os
  dois modelos que o usam não são executados** (resultado NAO_EXECUTADO, p = 1 na família); nada é imputado.

## Modelos (`src/transformers/model_shadow.py`), hiperparâmetros fixos, sem nenhum ajuste

| Modelo | Tipo | Features |
|---|---|---|
| `F_LOGIT` | regressão logística L2, λ = 1 (o modelo F já existente) | as 11 do modelo F |
| `F_LOGIT_SEM_FNG` | a mesma | as 9 sem Fear & Greed |
| `G_GBM` | gradient boosting de árvores em NumPy (`gbm.py`): 200 rodadas, taxa 0,05, profundidade 3, 32 faixas por quantil do treino, mínimo de 200 linhas por folha, λ = 1 | as 11 |
| `G_GBM_SEM_FNG` | o mesmo | as 9 |

Features (todas só com dados até `t`): retorno de 30 e 90 dias, volatilidade de 30 e 90 dias, razão de volume 7/90,
distância às SMAs 50, 100 e 200, queda desde a máxima de 90 dias, Fear & Greed e sua variação de 7 dias. Alvo: a moeda
supera o BTC em 30 dias (retorno líquido, aberturas de `t+1` a `t+31`). Padronização (logística) e faixas (boosting)
vêm só das linhas de treino de cada dobra.

## Protocolo temporal

- Walk-forward anual, 2020 a 2026: a dobra `Y` treina com os dias até 31/12 de `Y−1` menos **31 dias de expurgo**
  (todo alvo de treino termina antes do corte) e prevê os dias de `Y`.
- **Desenvolvimento**: dias de 2020-01-01 a 2024-12-31. **Teste final**: de 2025-01-01 em diante, avaliado uma vez,
  para os quatro modelos (não se escolhe quem vai ao teste). O teste final já foi consultado por outros estudos do
  projeto (para outros sinais); para estes modelos, não.
- Todo o período é histórico já explorado no desenvolvimento das regras do projeto. A confirmação real é prospectiva:
  as previsões diárias ficam registradas em `model_predictions.parquet` (branch `state`) desde a implantação.

## Métricas

**Preditivas (descritivas)**, por modelo, no desenvolvimento e no teste final: AUC, log loss, Brier, e o ganho de log
loss sobre prever a taxa de positivos do treino (`skill = 1 − LL_modelo / LL_taxa`). Calibração por decis.

**Econômica (a usada nas hipóteses)**: em cada dia com pelo menos 10 moedas no universo, as **5** de maior
probabilidade (k = 5, o mesmo do modelo F). Excesso do dia = retorno líquido médio dessas 5 em 30 dias − retorno médio
do universo do dia no mesmo intervalo (`entry_signals.universe_reference`). Referência simples: as 5 de maior retorno de
90 dias no mesmo dia e universo (a combinação `A_90` do estudo dos sinais).

## Hipóteses, família e correção

Família de **8 hipóteses** (α = 5%, Holm), todas no período de desenvolvimento:

- `H_universo(M)`: excesso médio do modelo M contra o universo > 0 (4 hipóteses);
- `H_momento(M)`: excesso médio de M − excesso médio da referência de momento, dia a dia > 0 (4 hipóteses).

Inferência: média da série diária. As janelas de 30 dias se sobrepõem, então os dias vizinhos são dependentes:
bootstrap **estacionário** (`bootstrap.py`), 2.000 reamostras, semente 20261019, bloco médio = máximo entre o
automático (Politis e White) e 30 dias; IC de 95% (percentil); p unilateral pela distribuição centrada. Hipótese não
executável fica na família com p = 1.

## Classificação (`ml_study.classify_model`)

- **VALIDADO**: no desenvolvimento, p Holm < 0,05 e limite inferior do IC > 0 nas **duas** hipóteses do modelo, e no
  teste final os dois excessos médios > 0 (não contradito).
- **PROMISSOR**: não é VALIDADO; no desenvolvimento os dois excessos médios > 0; no teste final, os dois > 0.
- **SEM_EVIDENCIA**: o resto.
- **NAO_EXECUTADO**: features indisponíveis (Fear & Greed ausente).

## Consequência para o produto (fixada antes)

Nenhum modelo sai do modo sombra por este estudo, qualquer que seja o resultado. Um modelo VALIDADO só pode virar
candidato a "observação" (nunca COMPRAR automático) depois de 365 dias de previsões prospectivas registradas
confirmarem os dois excessos com o mesmo teste. PROMISSOR e SEM_EVIDENCIA continuam só registrando.

## Sensibilidade (descritiva, fora da família)

k = 3 e k = 10; execução no fechamento em vez da abertura; peso das moedas por posição no ranking não é testado.

## Limitações (escritas antes)

- Uma única história de mercado (cerca de 2 ciclos); o desenvolvimento tem ~1.800 dias, mas com janelas de 30 dias
  sobrepostas o número efetivo de observações independentes é da ordem de 60: só excessos de alguns pontos
  percentuais em 30 dias são detectáveis.
- Os quatro modelos e o momento se sobrepõem (usam retornos passados): Holm é válido mas conservador.
- Deslistagem: o retorno futuro de moeda que para de negociar usa o último preço (regra de `forward_returns`), que pode
  ser otimista; renomeações aparecem como saída de um par.
- Spread e slippage são hipóteses por faixa de volume.
- Base do arquivo oficial (S3), equivalente aos klines da REST, mas com fingerprint diferente da base usada no estudo
  dos sinais de entrada.

## Resultado da execução de 2026-10-19 (parcial: sem Fear & Greed)

Experimento `0498216a4d4223f0`, código `e97bbfc` (protocolo commitado antes da execução), dados do arquivo oficial com
`continuidade-v1` (691 séries, 795.659 candles, fingerprint `9e01bf713328…`), 82.192 linhas (dia, moeda) no universo
point-in-time. Saídas em `evidence/ml_study/`.

**O Fear & Greed estava indisponível neste ambiente** (o host é bloqueado): `F_LOGIT` e `G_GBM` não foram executados e
ficam com p = 1 na família de 8 hipóteses. A cópia diária do índice passa a ser guardada pelo GitHub Actions na branch
`state` (`fng_history.parquet`); com ela, os dois serão executados numa execução nova do mesmo protocolo
(`research/ml_study.py --fng ...`), registrada separadamente.

Métricas preditivas (o alvo é "supera o BTC em 30 dias"; taxa de positivos de ~35%):

| Modelo | Período | AUC | Log loss | Log loss da taxa | Ganho |
|---|---|---|---|---|---|
| F_LOGIT_SEM_FNG | desenvolvimento | 0,491 | 0,756 | 0,649 | −16,5% |
| F_LOGIT_SEM_FNG | teste final | 0,548 | 0,628 | 0,633 | +0,7% |
| G_GBM_SEM_FNG | desenvolvimento | 0,551 | 0,697 | 0,649 | −7,3% |
| G_GBM_SEM_FNG | teste final | 0,545 | 0,640 | 0,633 | −1,2% |

Excesso médio de 30 dias das 5 de maior probabilidade (desenvolvimento 2020–2024, 1.827 dias, IC de 95%, bloco ~65–72
dias; Holm sobre as 8 hipóteses):

| Modelo | Contra | Excesso | IC 95% | p | p Holm | Teste final (2025+) |
|---|---|---|---|---|---|---|
| F_LOGIT_SEM_FNG | universo | −2,7 pp | −5,4 a −0,2 | 0,97 | 1 | +4,3 pp |
| F_LOGIT_SEM_FNG | momento 90 dias | −0,1 pp | −4,1 a +3,8 | 0,53 | 1 | +9,0 pp |
| G_GBM_SEM_FNG | universo | +2,0 pp | −0,7 a +5,1 | 0,10 | 0,73 | +2,6 pp |
| G_GBM_SEM_FNG | momento 90 dias | +4,5 pp | +0,4 a +9,1 | 0,026 | 0,21 | +7,3 pp |
| (referência) momento 90 dias | universo | −2,6 pp | −5,7 a +0,5 | — | fora da família | −4,7 pp |

Níveis: **0 VALIDADO**; `G_GBM_SEM_FNG` **PROMISSOR** (excessos positivos no desenvolvimento e no teste final, sem
significância depois de Holm); `F_LOGIT_SEM_FNG` **SEM_EVIDENCIA**; `F_LOGIT` e `G_GBM` **NAO_EXECUTADO**.

Leitura, sem exagerar:

- **O PROMISSOR do boosting vem quase todo de 2021.** Excesso médio por ano contra o universo: 2020 −2,1 pp; **2021
  +12,0 pp**; 2022 +1,6 pp; 2023 −2,5 pp; 2024 +0,9 pp; 2025 +3,3 pp; 2026 +1,6 pp. Sem o ano de alta das altcoins, a
  vantagem no desenvolvimento some.
- **A vantagem sobre o momento é em boa parte o momento ser ruim**: as 5 de maior alta em 90 dias perderam do universo
  (−2,6 pp no desenvolvimento, −4,7 pp no teste final).
- **As probabilidades não são confiáveis como probabilidades.** As duas perdem da taxa de positivos em log loss no
  desenvolvimento. Só o decil mais alto do boosting diferencia: 52% de acertos contra ~33% nos outros decis. A
  regressão logística tem um formato em U (os decis extremos acertam mais que os do meio), que um modelo linear não
  representa; o boosting captura parte disso.
- **Sensibilidade:** com k = 3 o boosting sobe para +3,4 pp, com k = 10 cai para +1,1 pp, e executando no fechamento
  fica em +2,0 pp. O sinal concentra-se nas poucas moedas de maior probabilidade.

Consequência (fixada antes): nenhum modelo sai do modo sombra. Os quatro modelos já registram previsões diárias em
`model_predictions.parquet` (branch `state`); a avaliação prospectiva, com o mesmo teste, só depois de 365 dias.

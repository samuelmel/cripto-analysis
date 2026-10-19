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

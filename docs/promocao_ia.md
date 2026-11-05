# Trava de promoção da IA (`promotion-gate-v1`): critério fixado antes de qualquer avaliação

Os estudos do projeto (`docs/ml_study.md`, `docs/ml_study_v2.md`, `docs/regime_policy.md`) mostram que a IA ordena as
moedas um pouco melhor que o acaso, mas **não** superou a estratégia base de forma confiável quando se escolhem só as 5
primeiras. Ligá-la sem critério contradiria a evidência. Este documento define, **antes** de a trava ser calculada
sobre qualquer dado ao vivo, quando a IA deixa de só opinar e passa a influenciar o aporte **simulado**.

Nunca há ordem real: o projeto não tem integração com corretora, e a promoção só muda quais moedas aparecem no aporte
simulado (dinheiro fictício).

## O que "ativa" significa

1. **Visível (sempre):** a opinião da IA aparece na mensagem curta do Telegram e no painel, marcada como
   **"IA (em teste)"**, junto com o placar da carteira simulada dela contra "só segurar". O estado da trava aparece em
   uma linha.
2. **Influente (só com a trava aprovada):** a IA sugere as moedas do aporte simulado no lugar da regra atual.
3. **Se a trava reprovar ou não tiver dados suficientes,** a IA continua só opinando.

## O modelo avaliado

O mesmo da carteira simulada "IA": `G_GBM` (boosting com as 11 features) e, nos dias sem Fear & Greed, `G_GBM_SEM_FNG`.
Para cada dia vale o `G_GBM`; se ele não previu naquele dia, vale o `G_GBM_SEM_FNG`. Não se escolhe, depois de ver os
resultados, outro modelo.

## Os dados

- **Só previsões ao vivo** do registro `model_predictions.parquet` (gravadas no dia, com cadeia de hash). Nada do
  walk-forward do estudo entra: ele já foi olhado.
- **Só previsões maduras:** a janela de 30 dias da previsão já terminou e o resultado é conhecido.
- Retorno líquido de custos (taxa, spread e slippage do motor único), com entrada na abertura do dia seguinte.

## A estatística

Para cada dia `d` com previsão madura:

`excesso(d)` = média do retorno líquido de 30 dias das **5 moedas de maior probabilidade** em `d` − média do retorno de
30 dias do **universo** em `d` (o "acaso": comprar tudo igualmente).

A trava testa a média de `excesso(d)` por **bootstrap estacionário** (bloco médio de 30 dias, porque as janelas se
sobrepõem), 2.000 reamostras, semente 20261105, intervalo de confiança de **90%**.

## As condições (todas precisam valer)

| # | Condição | Valor fixo |
|---|---|---|
| 1 | O registro de previsões tem a cadeia de hash íntegra | `verify_chain` sem problemas |
| 2 | Dias de previsão ao vivo já maduros | **pelo menos 90** |
| 3 | Média do excesso das 5 escolhas, já líquida de custos | **> 0** |
| 4 | Limite inferior do IC de 90% do excesso | **> 0** |

Resultado: `APROVADA`, `REPROVADA`, `DADOS_INSUFICIENTES` (menos de 90 dias maduros) ou `CADEIA_INVALIDA`.
A trava é reavaliada todo dia e a aprovação **é revogada** no dia em que as condições deixarem de valer.

## Quando aprovada: como a IA influencia o aporte simulado

- As moedas do aporte passam a ser as de maior probabilidade da IA no dia, em vez da seleção por score da regra atual.
- Continuam valendo os filtros duros: moeda com dado indisponível, pouca liquidez, volatilidade ou queda excessiva,
  tendência de baixa ou excluída manualmente **nunca** entra, e o mercado defensivo continua bloqueando compras novas
  quando o filtro está ligado.
- O valor total e o dimensionamento por volatilidade seguem o código de alocação existente.
- A mensagem e o painel dizem que a escolha das moedas veio da IA.

## Limitações (antes de qualquer resultado)

- 90 dias com janelas de 30 dias sobrepostas equivalem a poucas observações independentes; o IC com bloco de 30 dias
  é otimista. **Aprovar não significa "validada"**: significa só que a IA passou nesta barra mínima e passa a
  influenciar uma carteira de dinheiro fictício, sob observação contínua.
- Uma única história de mercado recente; o resultado depende do regime do período.
- Excesso sobre a média do universo, não sobre comprar e segurar o BTC.
- Os estudos anteriores sugerem que parte do ganho da IA é efeito de reversão do momento, não "inteligência".

## Onde está no código

`promotion_gate` em `src/transformers/model_shadow.py` (função pura); aplicação ao aporte em
`apply_ai_selection`, no mesmo módulo; fiação no `src/pipeline.py`; testes em `tests/test_model_shadow.py`.

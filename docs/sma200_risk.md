# A regra SMA 200 reduz queda máxima e volatilidade contra comprar e segurar? Protocolo (fixado antes dos resultados)

Estudo à parte dos testes de sinal. Aqui a pergunta não é "o sinal dá retorno melhor", e sim se **estar posicionado só
quando a regra manda** reduz o risco em relação a manter a moeda o tempo todo. Escrito e commitado antes de calcular
qualquer métrica. Usa a base corrigida (`docs/data_continuity.md`, `continuidade-v1`).

## Estratégias comparadas (por moeda, mesmos dias)

- **SMA 200**: posicionada (long) no dia `d` se, no fechamento de `d-2`, a moeda e o BTC estavam acima das respectivas
  SMA 200; senão fica em caixa (retorno 0). O atraso de dois fechamentos reproduz "sinal no fechamento, entrada no
  fechamento seguinte". Cada mudança de posição paga o custo por lado de `config.py` (taxa + spread por faixa de volume +
  slippage).
- **Comprar e segurar (referência principal)**: posicionada todos os dias do mesmo conjunto, com o custo de entrar no
  primeiro dia e sair no último.
- **Mesma exposição (controle, só descritivo)**: a moeda multiplicada pela fração de dias em que a SMA 200 ficou
  posicionada. Serve para separar "reduziu o risco só por ficar menos tempo exposta" de "escolheu bem os dias".

Dias do conjunto: dias em que a moeda pertence ao universo point-in-time e tem SMA 200. Moeda sem pelo menos **365 dias**
nesse conjunto, no período, não entra (fixo agora, sem olhar resultado). Moeda que deixa de negociar sai ao último preço.

## Métricas (por moeda e período)

- **Queda máxima** = maior perda do pico ao vale da curva de patrimônio (positiva; menor é melhor).
- **Volatilidade** = desvio padrão dos retornos diários × √365, sobre todos os dias do conjunto (dia em caixa conta 0).
- Redução = métrica(comprar e segurar) − métrica(SMA 200). Positiva = a regra reduziu.

## Períodos

| Período | Intervalo | Uso |
|---|---|---|
| Desenvolvimento | até 2024-12-31 | decide o veredito |
| Teste final | 2025-01-01 em diante | avaliado uma vez, só pode contradizer |

## Inferência

Estatística: média, entre as moedas, da redução da queda máxima e da redução da volatilidade (cada moeda pesa igual).
Intervalo de 95% e valor-p unilateral por **bootstrap em blocos de calendário**: reamostram-se blocos de 60 dias do
calendário (os **mesmos dias para todas as moedas**, para preservar a correlação entre elas), 2000 reamostragens, semente
fixa derivada de `VALIDATION_SEED`; as duas estratégias são recalculadas no mesmo caminho reamostrado. Holm, α = 0,05,
sobre as 2 comparações (queda máxima e volatilidade).

## Critério

"A regra reduz o risco" = nas duas métricas, no desenvolvimento: p ajustado < 0,05 **e** limite inferior do IC de 95% > 0.
O teste final só contradiz: se, no teste final, a redução média de qualquer das duas for negativa, o resultado é
"não confirmado".

## Também será reportado (não decide nada)

- Fração de moedas em que a regra reduziu cada métrica; mediana por moeda.
- **O custo**: retorno total e anualizado médio da SMA 200 contra comprar e segurar. Reduzir risco ficando de fora também
  reduz o ganho; sem esse número a redução não diz nada.
- O controle de mesma exposição: a regra reduz mais do que simplesmente estar menos tempo na moeda?
- Resultado separado para BTC e ETH.

## Limitações (antes do resultado)

- Poucos ciclos de mercado (2017 a 2024); drawdown depende de poucos episódios e o bootstrap em blocos de 60 dias distorce
  o nível absoluto da queda máxima (o intervalo é da **diferença** pareada).
- Reduzir queda máxima de um ativo isolado não é reduzir o risco de uma carteira.
- A referência é comprar e segurar a mesma moeda, não o BTC nem uma carteira.

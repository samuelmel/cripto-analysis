# Teste agregado da regra SMA 200 (todas as moedas juntas): protocolo fixado antes dos resultados

Escrito e commitado **antes** de calcular qualquer retorno agregado. Nada abaixo muda depois de ver o resultado; uma
mudança exige novo registro. Complementa `docs/signal_validation.md` (teste por moeda) e reaproveita dele a regra do
sinal, o universo point-in-time, os custos, os sinais independentes e a referência aleatória.

## Pergunta

Juntando os eventos de todas as moedas do universo point-in-time (683 pares históricos, inclusive deslistados), a regra
SMA 200 (início de um episódio de alta com a moeda e o BTC acima da SMA 200) leva a retorno líquido maior do que entrar
em um dia qualquer **da mesma moeda**? Responde "a regra funciona de modo geral". **Não** valida moeda nenhuma: o resultado
não libera COMPRAR para ninguém. Quem aparece como COMPRAR continua decidido pelo teste por moeda.

Honestidade sobre a origem: este teste foi proposto **depois** de o teste por moeda não validar nenhuma moeda (poder
baixo, 12 a 30 sinais por moeda). É uma segunda olhada nos mesmos dados de desenvolvimento, motivada por esse resultado.
Por isso o critério abaixo é fixo e rigoroso, e o hold-out só entra se o desenvolvimento passar.

## Estatística

- Amostra: os **sinais independentes** de cada moeda (um sinal e pula-se qualquer outro a menos de `h` dias da mesma
  moeda), horizonte `h` em {7, 30}, período de desenvolvimento (entrada e saída até 2024-12-31), custos de `config.py`.
- **Excesso de um sinal** = retorno líquido do sinal − média do retorno líquido de entrar em qualquer dia elegível da
  **mesma moeda** (mesmo período e horizonte). Assim o ganho de moeda que só sobe não conta como mérito da regra.
- **Estatística principal** = média dos excessos de todos os sinais (cada sinal pesa igual).
- **Dependência entre moedas.** Na mesma semana muitas moedas dão sinal juntas (o BTC cruzando a SMA 200 liga várias de
  uma vez). Tratar os sinais como independentes subestimaria o erro. Por isso a inferência reamostra **janelas de
  calendário de 30 dias** (pela data de entrada), levando todos os sinais da janela juntos: bootstrap por cluster,
  `config.VALIDATION_BOOTSTRAP_RESAMPLES` reamostragens, semente fixa derivada de `VALIDATION_SEED` e do horizonte.
- **IC 95%** = percentis 2,5 e 97,5 da estatística reamostrada.
- **Valor-p** unilateral (a regra melhora) = fração de reamostragens centradas (estatística reamostrada − observada) com
  valor ≥ observado, com correção +1.
- **Estabilidade**: excesso médio > 0 na primeira e na segunda metade dos sinais, por data.
- **Holm**, α = 0,05, sobre a família de 2 testes (7 e 30 dias).

## Critério "a regra funciona de modo geral" (desenvolvimento)

Nos **dois** horizontes ao mesmo tempo: valor-p ajustado por Holm < 0,05, limite inferior do IC de 95% > 0 e excesso > 0
nas duas metades. Qualquer outra coisa = **não demonstrado**.

## Papel do hold-out

O teste final (a partir de 2025-01-01) é avaliado **somente se o desenvolvimento passar**, e só pode revogar: com pelo
menos 20 sinais independentes no horizonte e excesso médio negativo, o resultado vira `REVOGADO`. Se o desenvolvimento
não passar, o hold-out **não é calculado** (não se gasta o teste final para tentar reverter um resultado negativo).

## Apenas descritivo (não decide nada)

- Excesso médio com peso igual por moeda (média das médias por moeda) e mediana do excesso: mostram se a média é puxada
  por poucos ganhos enormes.
- Número de sinais, de moedas e de janelas de 30 dias que entraram; fração de moedas com excesso médio > 0.
- Sensibilidade: o mesmo teste sem BTC e ETH, e sem as 5 moedas com mais sinais.

## Limitações (valem antes do resultado)

- Moedas renomeadas ou migradas contam como pares distintos; a deslistada sai ao último preço.
- Retorno em horizonte fixo, sem stop; a regra de saída real é outra (ver `docs/exit_rules.md`).
- A referência inclui a deriva de alta da própria moeda; a comparação é com entrar em dia qualquer **da mesma moeda**,
  não com o BTC nem com a carteira.
- Mesmo agregado, o resultado vale para o período de desenvolvimento (2017 a 2024), que contém poucos ciclos de mercado;
  as janelas de 30 dias não eliminam a dependência de regime.
- Um resultado positivo diria que a regra tem vantagem **média** no conjunto, não que cada moeda a tenha.

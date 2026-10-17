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

## Resultado da execução de 2026-10-17

Experimento `e1c394add0e9d0ba` (dados 11fac7c853b7, código e7be451, semente 20261016; reproduzido em segunda execução com
resultado idêntico). 126 moedas, desenvolvimento, sinais independentes por moeda.

| Horizonte | Sinais | Janelas de 30 dias | Excesso médio | IC 95% | p ajustado (Holm) | Mediana | Moedas com excesso > 0 |
|---|---|---|---|---|---|---|---|
| 7 dias | 729 | 49 | +0,6 pp | −1,8 a +3,0 pp | 0,58 | −1,0 pp | 48% |
| 30 dias | 504 | 47 | **−97,8 pp (artefato, ver abaixo)** | −195 a −22 pp | 0,98 | −6,8 pp | 41% |

**Veredito: `NAO_DEMONSTRADO`.** Em 7 dias o excesso é indistinguível de zero (p ajustado 0,58). Como o critério exigia os
dois horizontes, o teste final **não foi calculado**. A mediana do excesso é negativa nos dois horizontes: a média, quando
positiva, vem de poucos ganhos grandes.

### Defeito de dados descoberto na leitura do resultado

O excesso de −97,8 pp em 30 dias **não é um resultado econômico**. Vem de um único par, `LUNA/USDT`: o par continua o
mesmo depois do colapso de maio de 2022, com o preço passando de centavos de milésimo para dólares. A média dos retornos de
30 dias de dias aleatórios desse par é de +12.339% (a referência), e os 4 sinais dele contribuem −123 pp cada, o que
sozinho explica quase toda a soma. É a limitação já escrita ("pares renomeados ou migrados contam como pares distintos"),
só que aqui ela quebra a estatística. A leitura correta do horizonte de 30 dias é a variante **posterior ao resultado**
(`SEM_LUNA_POSHOC`, criada depois de ver o número, só descritiva): excesso **+0,0 pp**, IC 95% de −7,1 a +7,6 pp, valor-p 0,49.

O veredito **não** foi alterado por isso: o protocolo foi aplicado como escrito, e o resultado oficial continua sendo o da
tabela. Mesmo sem LUNA o teste não passaria, porque o horizonte de 7 dias já falha.

### Leitura

- Juntando 126 moedas e 729 sinais (contra 12 a 30 por moeda no teste individual), **não aparece vantagem da regra SMA 200
  sobre entrar em um dia qualquer da mesma moeda**. O IC de 7 dias (−1,8 a +3,0 pp) exclui ganhos grandes, mas não
  descarta um efeito pequeno positivo ou negativo.
- Os sinais são menos numerosos do que parecem: 729 sinais caem em 49 janelas de calendário, porque muitas moedas ligam no
  mesmo mês. O erro padrão considera isso.
- Não demonstrado **não** é demonstrado que a regra falha. A regra tem outro papel (ficar fora em tendência de baixa, com o
  stop de 20%), que esse teste não mede.
- Sensibilidades (`evidence/pooled_signal_sensitivity.parquet`): sem BTC e ETH e sem as 5 moedas com mais sinais, o
  quadro de 7 dias não muda (+0,7 e +1,0 pp, ICs incluindo zero).

### Consequência e pendência

Nada muda no produto: continua sem moeda validada e sem COMPRAR. Pendência técnica, não tratada aqui por exigir mudança de
regra de dados: a limpeza (`clean_candles`) deveria descartar janelas de retorno que atravessam lacuna ou salto de preço
incompatível com mercado (caso LUNA), em vez de tratar o par como contínuo. Isso muda os dois testes (por moeda e agregado)
e precisa de novo registro.


## Refeito com a base corrigida (2026-10-17, `continuidade-v1`)

Experimento `c1bcc31eed147488` (dados fea05e374077). Mesmas regras; ver `docs/data_continuity.md`.

| Horizonte | Sinais | Excesso médio | IC 95% | p ajustado (Holm) |
|---|---|---|---|---|
| 7 dias | 726 | +0,6 pp | −1,8 a +2,9 pp | 0,59 |
| 30 dias | 503 | +0,1 pp | −7,0 a +7,7 pp | 0,59 |

**Veredito: `NAO_DEMONSTRADO`, igual ao anterior.** O −97,8 pp de 30 dias desapareceu (era a emenda do LUNA); o resultado oficial
agora coincide com a variante `SEM_LUNA_POSHOC` de antes. O teste final não foi calculado. O resultado anterior (`e1c394add0e9d0ba`)
continua no registro.

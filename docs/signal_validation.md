# Validação estatística do sinal COMPRAR, por moeda

Este documento fixa as regras **antes** de olhar qualquer resultado de retorno. Mudar uma regra depois de ver o
resultado invalida o estudo e exige novo registro (ver "Registro e reprodutibilidade").

## Pergunta

Para cada moeda, o sinal COMPRAR da regra atual (fechou acima da SMA 200 da própria moeda **e** o BTC acima da sua
SMA 200; evento = primeiro dia do episódio de alta) leva a retornos melhores do que entrar em um dia aleatório da
mesma moeda? Só moedas com evidência podem aparecer como COMPRAR (Telegram e painel). As demais continuam no
ranking, sem a palavra COMPRAR.

## Execução e custos

- O sinal é conhecido no fechamento do dia `t`. A entrada simulada é no **fechamento de `t+1`**; a saída, no
  fechamento de `t+1+h`, com `h` em {7, 30} dias.
- Custo por lado = `FEE_PER_SIDE` + meia-largura do spread (faixa pelo volume médio de 30 dias, `SPREAD_TIERS`) +
  `SLIPPAGE`, todos de `config.py`; paga-se dois lados.
- Moeda que para de negociar (deslistada) antes do fim da janela sai ao último fechamento disponível. Janela
  incompleta de moeda ainda ativa (dados recentes demais) é descartada.

## Universo point-in-time

O universo do dia `D` usa só dados até `D`: histórico mínimo, volume médio de 30 dias, candle recente e o limite de
`MAX_UNIVERSE_SIZE` moedas por volume. Candidatas = todos os pares `*USDT` que já existiram na Binance (inclusive
deslistados), não a lista de hoje. Um evento só conta se a moeda pertence ao universo no dia do sinal.

## Períodos

| Período | Intervalo | Uso |
|---|---|---|
| Desenvolvimento | até 2024-12-31 | única base para escolher qualquer coisa. O 2023+ antigo está aqui, já consumido |
| Teste final (hold-out) | 2025-01-01 em diante | **não** escolhe nada; avaliado uma vez |

Evento de desenvolvimento: entrada e saída (`t+1+h`) ambas até 2024-12-31 (expurgo: nenhuma janela de
desenvolvimento enxerga o hold-out).

## Estatística (por moeda e horizonte)

- **Sinais independentes**: dos eventos, mantém-se um e pula-se qualquer outro a menos de `h` dias dele.
- **Excesso** = média do retorno líquido dos sinais independentes − média do retorno líquido de entrar em qualquer dia
  elegível da mesma moeda (mesmo período, mesmo horizonte, mesmos custos).
- **Referência aleatória**: `B = 20000` sorteios de `n` dias de entrada da mesma moeda (semente fixa derivada de
  `VALIDATION_SEED`, moeda e horizonte). Valor-p unilateral = fração de sorteios com média ≥ a observada
  (com correção +1).
- **IC 95%** do excesso por bootstrap em blocos circulares (blocos de `ceil(n^(1/3))` nos sinais, de `h` dias na
  referência), 2000 reamostragens, semente fixa.
- **Estabilidade**: o excesso tem de ser > 0 também na primeira e na segunda metade (por data) dos sinais
  independentes.

## Comparações múltiplas

**Holm** (já em `policy_evaluation.holm_adjust`), α = 0,05, sobre a família de todas as combinações
(moeda, horizonte) com ao menos `N_MIN` sinais independentes. Combinações com menos sinais não entram na família
(não há como testar) e a moeda fica `SEM_EVIDENCIA`. O número de combinações candidatas e testadas fica no registro.

## Critério de moeda VALIDADA (desenvolvimento)

Nos **dois** horizontes (7 e 30 dias), simultaneamente:

1. pelo menos `N_MIN` sinais independentes;
2. valor-p ajustado por Holm < 0,05;
3. limite inferior do IC 95% do excesso > 0;
4. excesso > 0 nas duas metades.

Estados: `VALIDADA`, `NAO_VALIDADA` (sinais suficientes, critério não atendido), `SEM_EVIDENCIA` (menos de `N_MIN`
sinais em algum horizonte; nunca "boa"), `REVOGADA` (ver abaixo), `NAO_AVALIADA` (moeda sem dado no estudo).

## Papel do hold-out (regra escrita antes de ver o resultado)

O hold-out **só pode tirar** o status, nunca dá-lo. Moeda `VALIDADA` no desenvolvimento passa pelo teste final:

- Se tiver **pelo menos 5 sinais independentes** no hold-out em um horizonte e o excesso for **negativo** nesse
  horizonte (estimativa pontual, sem teste de significância: o poder é baixo), vira `REVOGADA` e **perde o COMPRAR**.
- Com menos de 5 sinais independentes no hold-out em ambos os horizontes, o teste não refuta nem confirma: o status
  `VALIDADA` permanece com `holdout = INSUFICIENTE` (não confirmada no teste final).
- Com 5 ou mais sinais em ambos os horizontes e excesso ≥ 0 em ambos: `holdout = CONFIRMADA`.
- Moeda que não passou no desenvolvimento **nunca** é promovida pelo hold-out, mesmo que vá bem nele.

O hold-out é avaliado **uma vez** por versão de regras. Reavaliar com regras diferentes exige o sinalizador explícito
`--allow-second-holdout`, e a segunda avaliação fica registrada.

## `N_MIN`

`N_MIN` (mínimo de sinais independentes) é fixado depois de ver **somente as contagens** de sinais independentes por
moeda e horizonte, sem calcular nenhum retorno, e antes de rodar qualquer estatística de retorno. O valor escolhido e
a data da escolha entram em `config.py` e neste documento em commit próprio, que precede o primeiro cálculo de
retorno.

### Valor fixado

`N_MIN = 12` (2026-10-16), escolhido vendo **somente** `evidence/independent_counts.parquet`, antes de qualquer retorno.
Moedas com sinais independentes no desenvolvimento (de 683 pares históricos, 126 tiveram algum sinal):

| Mínimo de sinais | 7 dias | 30 dias |
|---|---|---|
| >= 8 | 30 | 20 |
| >= 10 | 27 | 16 |
| **>= 12** | **20** | **11** |
| >= 15 | 15 | 7 |
| >= 20 | 8 | 1 |

Com menos de ~12 observações, o bootstrap em blocos (bloco 3) e o valor-p da referência aleatória deixam de ser
confiáveis; 12 mantém a família de Holm pequena sem deixar quase nenhuma moeda avaliável. No teste final, só 6 moedas
têm >= 8 sinais em 7 dias e 0 em 30 dias, por isso o mínimo do hold-out é 5 (`HOLDOUT_MIN_SIGNALS`).

## Registro e reprodutibilidade

- Cada execução grava no registro Parquet versionado `evidence/validation_registry.parquet`: combinações candidatas
  e testadas, sementes, versão do código e do motor, hash da configuração e do dado.
- Mesma semente, mesmos dados e mesma configuração dão o mesmo resultado (testado).
- Saída: `evidence/signal_evidence.parquet` (versionado, lido pelo pipeline diário) e cópia em
  `frontend/public/signal_evidence.parquet`.

## Limitações conhecidas

- Moedas renomeadas ou migradas (ex.: LUNA → LUNC) são pares diferentes na Binance; a continuidade não é tratada.
- Não há fonte oficial do motivo e da data de deslistagem; usa-se o último candle como fim da negociação.
- O stop de −20% e as saídas por tendência/mercado não entram: avalia-se o retorno em horizonte fixo.
- Em dias seguidos de alta, a moeda mostra COMPRAR enquanto durar o episódio; a evidência mede a entrada no
  primeiro dia.
- Os retornos de dias vizinhos são correlacionados; por isso blocos e sinais independentes.

## Resultado da execução de 2026-10-16

Experimento `c50af63e6e99f77f` (dados 11fac7c853b7, semente 20261016, `N_MIN = 12`, motor `engine-3`). Reproduzido em
dois processos com resultado idêntico (`research/signal_evidence_study.py run` devolve "reproduzido").

- Base: 683 pares `*USDT` da Binance (inclusive deslistados); 126 tiveram algum sinal; 252 combinações (moeda, horizonte)
  com pelo menos um sinal (candidatas); **31 testadas** (família de Holm, com `N_MIN` sinais independentes).
- **Nenhuma moeda foi validada.** 11 ficaram `NAO_VALIDADA` (sinais suficientes, sem efeito): ADA, BNB, BTC, ETC, ETH, LINK,
  LTC, SOL, TRX, VET e XRP. As outras 672 ficaram `SEM_EVIDENCIA` (poucos sinais). Todos os valores-p ajustados por Holm
  deram 1,0 e todos os limites inferiores do IC de 95% do excesso ficaram negativos (o maior: −0,02 ponto percentual).
- BTC e ETH, que eram as únicas moedas com COMPRAR, não passaram (excesso em 7 dias: +0,7 e −1,9 pontos percentuais;
  em 30 dias: −4,2 e −4,7 pontos percentuais, com IC incluindo zero). SOL teve o maior excesso pontual em 30 dias
  (+24 pontos percentuais), com IC de 95% de −18 a +67 pontos percentuais e valor-p bruto 0,033 (o menor da família de 31), que após Holm vira 1,0.
- O teste final só podia revogar moedas validadas; como não houve nenhuma, ele não decidiu nada.
- Consequência no produto: nenhuma moeda mostra COMPRAR no Telegram e no painel. O ranking de seleção continua igual.

Correção feita durante a execução: o primeiro ID de experimento dependia da ordem de um `frozenset` (varia entre
processos). Foi corrigido (lista ordenada) e o registro foi recriado; os resultados das duas execuções são idênticos
(comparação de quadro a quadro) e o teste final não foi reavaliado com regras diferentes.

Leitura honesta: a ausência de validação **não** prova que o sinal não funciona. Com 12 a 30 sinais independentes por
moeda e retornos de 30 dias muito dispersos em cripto, o estudo tem pouco poder para detectar vantagens modestas.
O que se pode afirmar é que não há evidência de que a regra SMA 200 supere entrar em dia aleatório, em nenhuma moeda.

## Registro de transparência

- **O teste final (hold-out) foi calculado duas vezes** com as mesmas regras, os mesmos dados e a mesma semente. A
  primeira execução gravou um ID de experimento instável (dependia da ordem de um `frozenset`, que varia entre
  processos); corrigido o ID, o registro foi recriado e o estudo rodou de novo. Os quadros de resultado das duas execuções
  foram comparados linha a linha e são **idênticos**. Nenhuma regra, limiar ou N_MIN mudou entre elas, e como nenhuma
  moeda foi validada o hold-out não decidiu nada. Ainda assim, ele não é mais "avaliado uma única vez" no sentido estrito.
- **Origem dos candles sem checksum.** O histórico dos 683 pares (inclusive deslistados) veio da API pública de klines
  (`data-api.binance.vision`), não dos ZIPs mensais do bucket `data.binance.vision`. Os ZIPs trazem um arquivo
  `.CHECKSUM` (SHA-256) que permitiria verificar a integridade; a API de klines **não** oferece checksum. Por isso não há
  verificação de integridade além da validação de formato e da limpeza de `clean_candles`. O `data_fingerprint` do
  experimento identifica os dados usados, mas não prova que a Binance os serviu corretamente.

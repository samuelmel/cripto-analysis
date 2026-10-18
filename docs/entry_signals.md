# Sinais de entrada candidatos: protocolo fixado antes dos resultados

Aprovado em 2026-10-17 e commitado antes de calcular qualquer retorno. Nada abaixo muda sem novo registro.
Contexto: a regra SMA 200 não demonstrou vantagem para escolher entrada (`docs/signal_validation.md`,
`docs/pooled_validation.md`, `docs/data_continuity.md`) e reduz risco só por menor exposição (`docs/sma200_risk.md`). Ela
deixa de ser gatilho de compra e fica como contexto (estado do mercado).

## Lista fechada de candidatos (5) e grade (11 combinações)

Todos operam sobre o universo point-in-time do dia (`docs/signal_validation.md`) com a base `continuidade-v1`. Usam só dados
até o fechamento do dia `t`.

**Evento = entrada na condição**, não cada dia em que ela continua valendo: há evento em `t` quando a condição é verdadeira
em `t` e falsa no dia anterior (dia anterior sem candle, fora do universo ou com o candidato incalculável conta como falso).
Isso vale para todos os candidatos, **inclusive B**: uma moeda que segue 15% abaixo da máxima por dez dias gera um evento,
no primeiro desses dias; só gera outro depois de sair da condição e voltar a ela. Em A, D, E e F, evento = entrar no top 5.

| Id | Hipótese (escrita antes) | Condição | Grade | Comb. |
|---|---|---|---|---|
| A | Momentum relativo: moedas no topo do ranking de retorno continuam acima das outras | retorno de `N` dias entre as 5 maiores do universo do dia | N ∈ {30, 60, 90} | 3 |
| B | Recuo em tendência de alta: comprar queda dentro de tendência recompensa | fechamento > SMA 100 da moeda **e** fechamento ≤ (1 − x) × máxima dos últimos 20 fechamentos | x ∈ {10%, 15%, 20%} | 3 |
| C | Rompimento: nova máxima de 55 dias com participação inicia movimento | fechamento > maior fechamento dos 55 dias anteriores **e** volume em USD do dia > média dos 20 dias anteriores | única | 1 |
| D | Força relativa contra o BTC: quem supera o BTC continua superando | retorno de `N` dias menos o do BTC entre os 5 maiores do universo **e** > 0 | N ∈ {30, 60, 90} | 3 |
| E | O score atual de seleção (`SCORE_WEIGHTS`) tem poder de escolha | moeda entre as 5 de maior score do dia (calculado só com dados até `t`) | única | 1 |

Nenhum parâmetro fora da grade é testado. A, D e E se sobrepõem (todos têm componente de momentum): isso deixa o Holm
conservador, não o invalida (Holm vale sob dependência arbitrária). Se o score E não puder ser reconstruído por data sem
olhar o futuro, E sai da lista e o motivo é registrado (não é substituído por outro candidato).

## Execução e custos

- Sinal conhecido no fechamento de `t`. **Entrada na abertura de `t+1`; saída na abertura de `t+1+h`**, `h` ∈ {7, 30} dias
  (saída na abertura para simetria com a entrada).
- Custo por lado = `FEE_PER_SIDE` + meia-largura do spread (faixa pelo volume) + `SLIPPAGE`, de `config.py`, nos dois lados.
- Moeda que para de negociar antes da saída sai ao último preço (regra do `continuidade-v1`); janela incompleta de moeda ativa
  é descartada.
- **Sensibilidade** (não entra no Holm, não decide): entrada no fechamento de `t+1` e saída no de `t+1+h`, com a referência
  calculada com a mesma execução.

## Método (o do teste agregado, `docs/pooled_validation.md`, com a referência abaixo)

- **Sinais independentes** por moeda e horizonte (pula-se evento a menos de `h` dias do anterior da mesma moeda).
- **Referência**, conforme o tipo de sinal (fixada antes dos resultados):
  - **A, D, E e F (seleção entre moedas)**: a pergunta é "escolher esta moeda hoje é melhor do que comprar o universo hoje".
    Referência = **média do universo point-in-time no mesmo dia `t`**, com peso igual entre as moedas, mesma execução
    (abertura `t+1` → abertura `t+1+h`), mesmo horizonte e os mesmos custos de `config.py` por moeda. Entram na média as
    moedas do universo em `t` com janela completa (a deslistada sai ao último preço, como no sinal). Isso tira do excesso o
    movimento do mercado no dia, que domina retornos de seleção.
  - **B e C (sinais de tempo, por moeda)**: referência = média do retorno líquido de entrar em qualquer dia elegível da
    **mesma moeda** (mesmo período, horizonte e execução), como no teste agregado. "Elegível" = a moeda está no universo e o
    candidato é calculável nesse dia.
- **Excesso do sinal** = retorno líquido do sinal − referência.
- **Estatística principal** = média dos excessos de todos os sinais (teste **agregado**), por combinação e horizonte.
- **Dependência entre moedas**: bootstrap por janelas de calendário de 30 dias (data de entrada), 2000 reamostragens, semente
  fixa derivada de `VALIDATION_SEED`, da combinação e do horizonte. IC 95% pelos percentis 2,5 e 97,5; valor-p unilateral
  (centrado) com correção +1; estabilidade = excesso > 0 nas duas metades dos sinais, por data.
- **Holm**, α = 0,05, sobre **todas** as hipóteses: 11 combinações × 2 horizontes = **22**, mais as do modelo (abaixo), total
  24. Cada combinação testada fica no `evidence/validation_registry.parquet`, com as não selecionadas também.
- Reportado sem decidir: excesso com peso igual por moeda, mediana, fração de moedas com excesso > 0, número de sinais, de
  moedas e de janelas de 30 dias.

## Períodos

| Período | Intervalo | Uso |
|---|---|---|
| Desenvolvimento | até 2024-12-31 (entrada e saída até essa data) | única base para classificar |
| Teste final | 2025-01-01 em diante | avaliado **uma vez**, depois de fixado o nível de cada sinal; só pode rebaixar |

Aviso: o teste final já foi consultado por outros estudos (SMA 200). Aqui ele é avaliado uma vez por este protocolo, mas não é
virgem em sentido estrito.

## Níveis (por combinação de sinal)

- **VALIDADO**: nos **dois** horizontes, no desenvolvimento, p ajustado (Holm) < 0,05, limite inferior do IC > 0 e excesso > 0
  nas duas metades; **e** não contradito no teste final: contradição = pelo menos 20 sinais no horizonte e excesso médio
  negativo em algum horizonte. Sem sinais suficientes no teste final, continua VALIDADO com a marca "não confirmado no teste final".
- **PROMISSOR**: não é VALIDADO, excesso médio > 0 nos dois horizontes (IC inclui zero) e não contradito no teste final pelo
  mesmo critério. Contradito = cai para SEM_EVIDENCIA.
- **SEM_EVIDENCIA**: o resto. Nunca significa "ruim".

Com 22 a 24 hipóteses e o poder já observado (~730 sinais agregados; IC de ±2,4 pp em 7 dias e ±7 pp em 30 dias), efeitos
abaixo de ~3 pp em 7 dias ou ~7 pp em 30 dias não serão detectáveis. É provável que nenhum sinal seja VALIDADO; PROMISSOR
com 11 combinações testadas tem alto risco de ser acaso (a melhor de várias), e a mensagem deve dizer isso.

## Modelo em modo sombra (regressão logística)

- **Alvo**: a moeda supera o BTC em 30 dias: retorno líquido da moeda (abertura `t+1` a abertura `t+31`, custos de
  `config.py`) maior que o retorno do BTC no mesmo intervalo.
- **Features** (todas calculadas só com dados até `t`): retorno de 30 e 90 dias, volatilidade de 30 e 90 dias, razão do volume
  em USD (média de 7 dias / média de 90 dias), distância à SMA 50, 100 e 200, queda desde a máxima de 90 dias, Fear & Greed
  (nível e variação de 7 dias) quando existir. Padronização com média e desvio do **treino** apenas.
- **Modelo**: regressão logística com regularização L2, λ fixo = 1,0 (sem ajuste), implementada em NumPy puro (Newton/IRLS,
  sem aleatoriedade: mesma entrada dá o mesmo resultado), sem scikit-learn. O intercepto não é penalizado.
- **Tudo vem só do treino de cada dobra**: média e desvio da padronização são calculados nas linhas de treino da dobra e
  aplicados, congelados, às linhas de teste; a penalidade L2 entra só no ajuste com as linhas de treino. Nenhum valor
  (padronização, λ, coeficiente, limiar) é escolhido ou recalculado olhando a dobra de teste.
- **Walk-forward anual**: para cada ano `Y` de 2020 a 2026, treina com dias até 31/12 de `Y-1` (menos 31 dias de expurgo,
  porque o alvo olha 30 dias à frente) e prevê `Y`. Dias de 2020 a 2024 = desenvolvimento; 2025+ = teste final.
- **Sem vazamento**: teste de truncagem (as features de `t` não mudam se os dados depois de `t` forem removidos) e teste de que
  nenhuma linha de treino tem alvo que termina depois do corte.
- **Sinal do modelo (F)**: moeda entre as 5 de maior probabilidade do dia (evento = entrada no top 5). É seleção entre
  moedas: referência = média do universo no mesmo dia, como A, D e E. Entra no Holm como 1 combinação (2 hipóteses).
- **Só vira candidato se superar a regra simples com IC**: referência fixa = **A com N = 90** (a regra de ranking mais simples,
  que usa a feature principal do modelo). Diferença entre o excesso de F e o de A em 30 dias, pareada por janela de
  calendário e restrita ao período em que F existe (2020 a 2024 no desenvolvimento), IC 95% pelo mesmo bootstrap; exige limite inferior > 0 **e** F ter nível PROMISSOR ou VALIDADO. Caso contrário
  o resultado negativo é publicado em `docs/` e o modelo fica só em sombra (previsões registradas na branch `state`, fora do Telegram).

## Consequência para o produto

- **COMPRAR passa a depender do sinal, não da moeda**: aparece para qualquer moeda que dispare, no dia, um sinal com nível
  VALIDADO neste teste agregado. O resultado por moeda (`docs/signal_validation.md`) vira informação extra na mensagem.
- PROMISSOR aparece como candidata em observação, nunca como COMPRAR, com o aviso de que pode ser só a melhor de várias.

## Limitações (escritas antes dos resultados)

- **O critério de contradição no teste final quase nunca vai disparar.** Ele exige pelo menos 20 sinais independentes num
  período de cerca de 21 meses e olha só o sinal da média, sem IC. Para sinais raros (C, B com x = 20%) os 20 sinais
  provavelmente não existem; quando existem, o ruído (IC de ±2,4 pp em 7 dias e ±7 pp em 30 dias) faz um excesso positivo
  no teste final não confirmar nada. O teste final é uma proteção fraca: só pega contradição grosseira. A contagem de sinais
  de cada combinação no teste final é reportada para que essa limitação fique visível.
- O teste final já foi consultado por estudos anteriores (SMA 200); não é virgem.
- A, D, E e F se sobrepõem (momentum). Holm segue válido, mas fica conservador; e um PROMISSOR entre 12 combinações tem alto
  risco de ser só a melhor de várias.
- Retorno em horizonte fixo, sem stop; a regra de saída real é outra (`docs/exit_rules.md`).
- Pares renomeados ou migrados contam como pares distintos; o `continuidade-v1` corta janelas em lacunas e saltos de preço.
- Poucos ciclos de mercado (2017 a 2024); as janelas de 30 dias do bootstrap não eliminam a dependência de regime.

## Plano de execução e entrega (um commit por etapa)

1. Este protocolo commitado (após aprovação).
2. Features e eventos puros (`src/transformers/`), com testes de truncagem, causalidade e contagem de eventos.
3. Estudo dos 5 candidatos + sensibilidade; resultados e níveis em `evidence/` e `docs/`.
4. Modelo sombra (NumPy), walk-forward e comparação com A-90; resultado publicado, qualquer que seja.
5. Níveis na evidência de produção, schema Parquet e tipo TypeScript no mesmo commit.
6. Mensagem diária do Telegram (candidatas, nível, excesso com IC, aporte, risco, regime, aviso).
7. Lista de observação e avisos só na mudança (candidata dispara ou se desfaz); ATENÇÃO sugere reduzir o tamanho.
8. Painel e relatório final.

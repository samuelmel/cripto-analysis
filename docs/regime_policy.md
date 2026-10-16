# Seleção de estratégias por regime (Fase 5): pesquisa

Estudo de pesquisa, **isolado da produção**: não altera sinais, aportes, recomendações, stops, painel nem Telegram, e não executa ordens. Código: [`regime_policy.py`](../src/transformers/regime_policy.py) (políticas), [`policy_experiment.py`](../src/transformers/policy_experiment.py) (cenário), [`policy_study.py`](../src/transformers/policy_study.py) (protocolo completo), [`policy_evaluation.py`](../src/transformers/policy_evaluation.py) (métricas, bootstrap, Holm, IDs), [`experiment_log.py`](../src/loaders/experiment_log.py) (registro) e [`research/regime_policy_study.py`](../research/regime_policy_study.py) (execução).

> [!IMPORTANT]
> **Resultado em uma frase:** a hipótese principal **não foi sustentada**. A diferença de Sharpe da política primária contra a regra de tendência fixa foi −0,06 (IC 95% de −0,18 a +0,05, com o motor corrigido na consolidação; −0,07 e [−0,20; +0,06] com o motor anterior), e nenhuma das 20 comparações da família é significativa, nem antes do ajuste. O resultado é **inconclusivo, com estimativa pontual nula ou negativa**, e é uma avaliação histórica exploratória (seção 8).
>
> As seções 1 a 7 (protocolo) foram escritas **antes** da primeira execução do estudo. As mudanças posteriores estão listadas, com data e motivo, na seção 9 ("Desvios do protocolo").

## 1. Hipótese e critério de decisão

**H1 (principal).** Uma política que escolhe a estratégia conforme o regime de mercado tem Sharpe líquido de custos maior que o da estratégia fixa de referência, no período de avaliação.

- **Métrica primária:** Sharpe anualizado dos retornos diários líquidos (média/desvio × √365, taxa livre de risco zero). Escolhida por ser a métrica já usada no projeto, com amostra diária de mais de 5 anos. Exige ao menos 252 dias; abaixo disso fica `NaN`.
- **Comparação primária (única, pré-registrada):** `P1_DEFENSIVA` contra `TENDENCIA_SMA200`, diferença de Sharpe, janela primária, custos centrais.
- **Critério de apoio à H1:** diferença > 0, intervalo de 95% por bootstrap em blocos que **exclui zero**, e diferença > 0 também com custo 2× e com atraso de 1 dia. Caso contrário, o resultado é **inconclusivo** ou **negativo**; nunca "comprovado".
- **Métricas secundárias:** retorno total e anualizado, volatilidade anualizada, Sortino (desvio abaixo de zero), drawdown máximo, tempo de recuperação, pior período submerso, turnover, custos, número de entradas, dias investidos e exposição média.

## 2. Dados, universo e tempo

- Base local do projeto (Binance, candles diários), universo = moedas de `UNIVERSE` aprovadas por `select_universe`, limpas por `clean_candles`. Elegibilidade por dia: tem candle e SMA 200 calculada. **Viés de sobrevivência permanece** (moedas de hoje) e vale igualmente para todas as políticas.
- Regime: `classify_market_regimes` (Fase 4, `regimes-1.0.0`) sobre o BTC. A linha de `D` só é conhecida em `known_at = D+1` (fechamento de `D`).
- **Decisão no fechamento de `D`, vale para o retorno de `D+1`** (convenção do motor existente, `selection_backtest.run_weighted`). O projeto **não** implementa execução na abertura de D+1; isso não foi presumido. O atraso de 1 dia é uma variante de robustez.
- Rebalanceamento a cada 7 dias (`SELECTION_REBALANCE_DAYS`), igual para todas as políticas. Entre rebalanceamentos os pesos flutuam com os preços.
- Janela primária: **2021-01-01 até o último dia da base**. Janelas secundárias: cada ano civil de 2021 em diante, `VALIDACAO` (2021–2022) e `TESTE` (2023 em diante), mais o período completo desde o início das candidatas.
- Todos começam em caixa. Anos civis são fatias da mesma simulação contínua (não reiniciam posições).

> [!WARNING]
> **Nenhum período é "fora da amostra" no sentido forte.** Toda a história até 2026-10 já foi inspecionada em fases anteriores (a Fase 4 descreveu regimes e desfechos posteriores sobre toda a série). Os resultados são **avaliação histórica exploratória**. Não existe teste prospectivo intocado.

## 3. Estratégias candidatas e baselines (as que existem no código)

| Nome | Origem | Definição |
|---|---|---|
| `COMPRAR_E_SEGURAR` | `selection_backtest.baseline_targets` | Peso igual em todas as moedas elegíveis |
| `TENDENCIA_SMA200` | idem | Peso igual nas moedas acima da SMA 200, com o BTC também acima |
| `MOMENTO_SIMPLES` | idem | As 3 de maior retorno em 90 dias, peso igual |
| `BTC` | idem | Só Bitcoin, comprado e segurado |
| `CAIXA` | nova, trivial | Nenhuma posição |
| `SELECAO` | `selection.assess` + `allocation.allocate` | Seleção de produção; só **referência descritiva** (dimensionamento e exposição diferentes; fora da família de testes) |

Não foram incluídas Donchian, Bollinger, RSI nem outras do laboratório: não estão no motor de pesos e não há ganho justificável em ampliar a família antes de saber se o regime carrega informação.

## 4. Políticas (tabelas definidas antes da avaliação)

Chave: regime de tendência (e volatilidade onde indicado). `MISTO`, `LATERAL`, `BAIXA`, `INDETERMINADO` e `INDISPONIVEL` **nunca** são tratados como `ALTA` ou `BAIXA`; qualquer estado não listado vai para `CAIXA`.

| Política | ALTA | MISTO | LATERAL | BAIXA | demais |
|---|---|---|---|---|---|
| `P1_DEFENSIVA` (**primária**) | `TENDENCIA_SMA200` | `CAIXA` | `CAIXA` | `CAIXA` | `CAIXA` |
| `P2_MOMENTO_NA_ALTA` | `MOMENTO_SIMPLES` | `TENDENCIA_SMA200` | `CAIXA` | `CAIXA` | `CAIXA` |
| `P3_VOL_FILTRADA` | `TENDENCIA_SMA200` se vol `NORMAL`, `CAIXA` se vol `ALTA` | `CAIXA` | `CAIXA` | `CAIXA` | `CAIXA` |
| `P4_ALTA_SEGURAR` | `COMPRAR_E_SEGURAR` | `CAIXA` | `CAIXA` | `CAIXA` | `CAIXA` |
| `P5_APRENDIDA_WF` | aprendida | aprendida | aprendida | aprendida | `CAIXA` |

`P5`: no início de cada ano civil, para cada estado de tendência, escolhe entre `COMPRAR_E_SEGURAR`, `TENDENCIA_SMA200` e `MOMENTO_SIMPLES` a candidata de maior Sharpe diário **usando só dias anteriores ao ano** (retorno do dia `t` associado ao regime conhecido em `t−1`, janela expansiva). Se o estado teve menos de 180 dias de treino, ou se o melhor Sharpe é ≤ 0, usa `CAIXA`. Parâmetros fixados a priori: 180 dias, critério Sharpe, reajuste anual. A tabela de cada ano é gravada.

Regras operacionais comuns:
- **Mudança de regime frequente:** nenhuma histerese adicional além da confirmação de 5 dias já existente no classificador (sem novos parâmetros); o número de trocas de estratégia é reportado.
- **Posição aberta numa troca:** nada é vendido fora do rebalanceamento. A nova estratégia só vale no próximo dia de rebalanceamento, quando a carteira vai ao novo alvo; o giro desse ajuste paga taxa + spread + slippage. A faixa de tolerância de 5 pontos percentuais do motor vale para todos igualmente.
- **Sem dados suficientes / nenhuma elegível:** a candidata devolve pesos zero (caixa).
- Determinística; versão `regime-policy-1.0.0`.

## 5. Custos e robustez (variantes declaradas antes, todas reportadas)

Custos por lado = taxa 0,1% + meia-largura de spread por faixa de volume + slippage 0,05% (o mesmo de `selection_backtest`), iguais para todas as políticas. Variantes (uma de cada vez, em torno da base): custo ×0,5 e ×2; atraso de execução de 1 dia; rebalanceamento a cada 14 dias; universo só `BTC` e `ETH`; classificador com média de 150 e 250 dias e com confirmação de 3 e 7 dias; 10% dos dias de regime tornados `INDISPONIVEL` (sorteio com semente fixa); **sem faixa de tolerância** (alvo exato a cada rebalanceamento; ver seção 9, item 1). Total: 12 variantes contando a base. Resultados desfavoráveis são apresentados com o mesmo destaque.

## 6. Inferência

- **Bootstrap em blocos circulares** dos retornos diários **pareados** (mesmos blocos para as duas séries): blocos de 20 dias, 2.000 reamostras, semente `20261016`; sensibilidade com blocos de 10 e 40 dias.
- Estimativa pontual, intervalo percentil de 95% e valor-p bilateral por bootstrap centrado.
- **Família de hipóteses:** 5 políticas × 4 baselines (`COMPRAR_E_SEGURAR`, `TENDENCIA_SMA200`, `MOMENTO_SIMPLES`, `BTC`) = 20 comparações de Sharpe. Correção de **Holm** sobre os 20 valores-p. A comparação primária é uma só (pré-registrada) e é reportada sem ajuste *e* dentro da família.
- Tamanho efetivo da amostra estimado pela autocorrelação da diferença (até 20 defasagens). Anos civis **não** são tratados como observações independentes; a contagem de anos em que a política vence é apenas descritiva.
- Número de políticas e de variantes avaliadas é registrado no experimento.

## 7. Registro e reprodutibilidade

Cada execução gera um registro **append-only** em `data/research/experiments.parquet`: ID determinístico (hash da configuração + fingerprint dos dados + classificador), estado do código (HEAD e se a árvore está suja), fingerprint dos dados, versão/hash do classificador e da política, universo, períodos, semente, parâmetros do bootstrap, custos, contagem de políticas e variantes, hash dos resultados, data da execução, status (`EXPLORATORIO`) e limitações. Uma segunda execução com as mesmas entradas deve reproduzir o hash dos resultados; se divergir, o registro é recusado e o conflito é mostrado. Resultados detalhados ficam em `data/research/regime_policy_<id>.parquet` (nunca sobrescritos).

Reproduzir:

```bash
uv run python research/regime_policy_study.py
```

## 8. Resultados (avaliação histórica exploratória)

> [!NOTE]
> As tabelas 8.1 a 8.5 são da **revisão 2, com o motor de pesos versão 1**, que tinha o defeito da faixa de tolerância (seção 9, item 1). O defeito foi corrigido na auditoria de consolidação (`ENGINE_VERSION = weights-2`) e o estudo foi refeito: ver **8.6**, que passa a ser a referência. A conclusão não mudou. As revisões 1 e 2 continuam no registro de experimentos.

Base local de 17/08/2017 a 15/10/2026, 32 moedas após `select_universe`. Janela primária: 01/01/2021 a 15/10/2026 (2.114 dias). Experimentos registrados em `data/research/experiments.parquet`: `30d753afd5555bba` (protocolo revisão 1) e `494685b03e2fdb68` (revisão 2, ver seção 9); dados `a6f4b2e2367b…`; código no HEAD `d45b976` com árvore de trabalho alterada; semente `20261016`; a revisão 2 foi executada duas vezes e a segunda confirmou **"reproduzido"** (mesmo hash de resultados `be18aba8…`).

### 8.1 Janela primária, cenário-base (custos centrais, faixa de tolerância do motor)

| Política / baseline | Retorno total | Anual | Volatilidade | Sharpe | Sortino | Pior queda | Exposição média | Custo total | Trocas |
|---|---|---|---|---|---|---|---|---|---|
| `BTC` | +108% | 13,5% | 56,6% | 0,51 | 0,74 | −76,6% | 99,7% | 0,2% | – |
| `COMPRAR_E_SEGURAR` | +416% | 32,8% | 51,6% | 0,81 | 1,16 | −65,2% | 57,0% (*) | 0,7% | – |
| `MOMENTO_SIMPLES` | +676% | 42,4% | 94,3% | 0,85 | 1,28 | −83,7% | 99,9% | 31,2% | – |
| `TENDENCIA_SMA200` (referência) | +733% | 44,2% | 49,4% | **0,99** | 1,45 | −56,8% | 37,7% | 6,0% | – |
| `P1_DEFENSIVA` (primária) | +557% | 38,4% | 47,5% | 0,93 | 1,35 | −56,4% | 34,4% | 5,5% | 23 |
| `P2_MOMENTO_NA_ALTA` | +1.364% | 58,9% | 73,8% | 0,99 | 1,56 | −55,9% | 51,2% | 17,5% | 39 |
| `P3_VOL_FILTRADA` | +225% | 22,6% | 43,2% | 0,69 | 0,98 | −56,4% | 32,2% | 5,8% | 27 |
| `P4_ALTA_SEGURAR` | +700% | 43,2% | 56,2% | 0,92 | 1,35 | −54,1% | 48,0% | 4,8% | 23 |
| `P5_APRENDIDA_WF` | +117% | 14,3% | 62,2% | 0,53 | 0,75 | −83,4% | 55,1% | 12,0% | 23 |
| `SELECAO` (produção; só referência) | +205% | 21,3% | 26,2% | 0,87 | 1,28 | −32,5% | 33,1% | 11,7% | – |

(*) A exposição de 57% de `COMPRAR_E_SEGURAR` é um achado sobre o motor, não um erro de leitura: ver seção 9, item 1. `SELECAO` tem dimensionamento e exposição próprios e está **fora da família de testes**.

Tempo de recuperação da pior queda: `P1`, `P3`, `P5` e `TENDENCIA_SMA200` ainda não tinham recuperado o topo anterior no fim da base; `P2` recuperou em 110 dias e `P4` em 246 (tabela completa no Parquet).

### 8.2 Comparação pareada de Sharpe (bootstrap em blocos de 20 dias, 2.000 reamostras)

**Primária pré-registrada: `P1_DEFENSIVA` − `TENDENCIA_SMA200` = −0,066; IC 95% [−0,203; +0,055]; p = 0,31.** Com blocos de 10 e 40 dias: [−0,210; +0,080] e [−0,210; +0,041]. O critério de apoio (diferença > 0 e IC fora do zero, também com custo 2× e atraso de 1 dia) **não foi atendido**: a diferença é negativa na base, com custo 2× (−0,065) e com atraso (−0,026).

Família de 20 hipóteses (5 políticas × 4 baselines), Holm:

| Política | vs `BTC` | vs `COMPRAR_E_SEGURAR` | vs `MOMENTO_SIMPLES` | vs `TENDENCIA_SMA200` |
|---|---|---|---|---|
| `P1_DEFENSIVA` | +0,42 [−0,53; 1,31] | +0,12 [−0,53; 0,74] | +0,08 [−0,65; 0,82] | −0,07 [−0,20; 0,06] |
| `P2_MOMENTO_NA_ALTA` | +0,49 [−0,42; 1,37] | +0,18 [−0,57; 0,89] | +0,15 [−0,42; 0,68] | +0,00 [−0,55; 0,47] |
| `P3_VOL_FILTRADA` | +0,19 [−0,82; 1,16] | −0,12 [−0,95; 0,63] | −0,15 [−0,94; 0,62] | −0,30 [−0,86; 0,06] |
| `P4_ALTA_SEGURAR` | +0,42 [−0,44; 1,27] | +0,11 [−0,52; 0,70] | +0,08 [−0,61; 0,78] | −0,07 [−0,38; 0,22] |
| `P5_APRENDIDA_WF` | +0,02 [−0,74; 0,79] | −0,28 [−0,77; 0,15] | −0,32 [−0,88; 0,26] | −0,46 [−0,98; 0,04] |

**Todos os intervalos contêm zero e todos os valores-p ajustados por Holm são 1,0.** O menor valor-p bruto é 0,08 (`P5` contra a tendência fixa, com sinal **negativo**). O tamanho efetivo de amostra da diferença diária fica entre cerca de 1.400 e 2.114 dias (a autocorrelação de curto prazo da diferença é pequena), mas isso **não** mede a incerteza que importa: os regimes duram semanas ou meses (mediana de `ALTA` = 97 dias), de modo que há poucas dezenas de episódios independentes, e os intervalos acima provavelmente subestimam a incerteza real.

### 8.3 Janelas temporais (Sharpe; cada janela é correlacionada com as demais)

| | 2021 | 2022 | 2023 | 2024 | 2025 | 2026* | VALIDACAO (2021–22) | TESTE (2023+) |
|---|---|---|---|---|---|---|---|---|
| `TENDENCIA_SMA200` | 2,18 | sem posição | 1,38 | 1,27 | −1,06 | 0,93 | 1,54 | 0,61 |
| `P1_DEFENSIVA` | 2,16 | sem posição | 1,00 | 1,34 | −1,00 | 0,60 | 1,52 | 0,50 |
| `P2_MOMENTO_NA_ALTA` | 1,67 | −0,57 | 1,57 | 1,14 | −0,14 | 1,12 | 1,14 | 0,91 |
| `P4_ALTA_SEGURAR` | 2,03 | −0,18 | 1,08 | 1,09 | −0,30 | 1,06 | 1,42 | 0,63 |
| `P5_APRENDIDA_WF` | 2,00 | −1,06 | 1,33 | 1,33 | −1,06 | 0,93 | 0,53 | 0,61 |
| `COMPRAR_E_SEGURAR` | 2,24 | −1,50 | 2,07 | 1,46 | −0,57 | −0,16 | 0,94 | 0,81 |

\* até 15/10/2026. "Sem posição" = a carteira ficou em caixa o ano todo (Sharpe indefinido): em 2022 o BTC ficou abaixo da SMA 200 e o regime foi `BAIXA` em 87% dos dias. Nenhuma política vence em todos os anos; a contagem de anos é só descritiva. Os períodos `VALIDACAO` e `TESTE` seguem os nomes do projeto, mas **não são fora da amostra**: foram inspecionados em fases anteriores.

### 8.4 Robustez (diferença de Sharpe de `P1` contra a tendência fixa, em cada variante)

IC e valor-p por variante (suplementares: fora da família de 20, **sem ajuste**, 12 variantes olhadas):

| Variante | Diferença | IC 95% | p |
|---|---|---|---|
| base | −0,066 | [−0,203; 0,055] | 0,31 |
| custo ×0,5 / ×2 | −0,067 / −0,065 | [−0,204; 0,055] / [−0,201; 0,055] | 0,31 / 0,32 |
| atraso de 1 dia | −0,026 | [−0,144; 0,098] | 0,65 |
| rebalanceamento a cada 14 dias | −0,125 | [−0,265; −0,011] | 0,05 |
| universo só BTC+ETH | −0,019 | [−0,216; 0,194] | 0,84 |
| classificador: média 150 / 250 | −0,017 / −0,024 | [−0,256; 0,193] / [−0,210; 0,178] | 0,87 / 0,80 |
| classificador: confirmação 3 / 7 | −0,057 / −0,097 | [−0,162; 0,044] / [−0,245; 0,024] | 0,30 / 0,16 |
| **regime `INDISPONIVEL` em 10% dos dias** | **−0,384** | **[−0,765; −0,080]** | 0,03 |
| sem faixa de tolerância (alvo exato) | −0,059 | [−0,184; 0,050] | 0,33 |

A diferença é **negativa em todas as 12 variantes** (de −0,02 a −0,38). A pior é a falha de dados: quando o regime some em 10% dos dias, a política vai para caixa, e a tendência fixa (que não depende do classificador) não sofre isso. Para as demais políticas, a diferença pontual contra a tendência fixa só fica positiva em casos isolados e pequenos (`P2` +0,03 a +0,05 com média 150/250, confirmação 3 e sem faixa; `P4` +0,06 com atraso de 1 dia), todos dentro do ruído.

**Custos:** a política primária paga menos custo que a tendência fixa (5,5% contra 6,0% do capital no período) e troca de estratégia 23 vezes. Custos ×0,5 e ×2 não mudam a leitura. `MOMENTO_SIMPLES` e `P2` pagam custos altos (31% e 18%) por rotatividade.

### 8.5 Política aprendida (`P5`)

Mapeamento escolhido por ano (só dados anteriores): em 2021, `ALTA` → `TENDENCIA_SMA200`, `BAIXA` → `MOMENTO_SIMPLES`, `MISTO` → `COMPRAR_E_SEGURAR`, `LATERAL` → `CAIXA`; a partir de 2023, quase tudo vira `TENDENCIA_SMA200` (que em `BAIXA` fica em caixa por construção). As escolhas de 2021–2022 vieram de poucos episódios (`BAIXA` com 383 dias de treino em 2021, concentrados em 2018–2020) e perderam dinheiro em 2022. Pior Sharpe da família contra a tendência fixa (−0,46). É um exemplo concreto de aprender o mapeamento a partir de poucos regimes.

### 8.6 Revisões 3 e 4: motor corrigido (`weights-2`)

Experimentos `18ef20f62a6d1b3b` (revisão 3) e `53aae5614341a57f` (revisão 4, que acrescenta a classificação de evidência); mesma semente, mesmos dados (`a6f4b2e2367b…`); a revisão 4 foi executada duas vezes e a segunda confirmou "reproduzido". Com o motor corrigido a exposição bruta nunca passa de 100% e `COMPRAR_E_SEGURAR` fica 99,7% investido (antes, 57%).

| | `BTC` | `COMPRAR_E_SEGURAR` | `MOMENTO_SIMPLES` | `TENDENCIA_SMA200` | `P1` | `P2` | `P3` | `P4` | `P5` | `SELECAO` |
|---|---|---|---|---|---|---|---|---|---|---|
| Sharpe (janela primária) | 0,51 | 0,68 | 0,84 | **0,98** | 0,92 | 0,99 | 0,65 | 0,88 | 0,53 | 0,88 |
| Exposição média | 99,7% | 99,7% | 99,1% | 35,3% | 32,6% | 50,8% | 30,0% | 49,7% | 53,5% | 32,3% |
| Revisão 2 (motor antigo): Sharpe | 0,51 | 0,81 | 0,85 | 0,99 | 0,93 | 0,99 | 0,69 | 0,92 | 0,53 | 0,87 |

- **Primária:** `P1` − `TENDENCIA_SMA200` = **−0,059**, IC 95% [−0,184; +0,051], p = 0,33. Não atende ao critério de apoio.
- **Família de 20:** nenhum p < 0,05 (menor: 0,096, `P5` contra a tendência fixa, **negativo**); todos os p de Holm = 1,0. Classificação de evidência (`classify_evidence`): **as 20 comparações são `SEM_EVIDENCIA`**.
- **Robustez:** a diferença de `P1` contra a tendência fixa é negativa nas 12 variantes (de −0,004 a −0,362); a pior, de novo, é o regime indisponível em 10% dos dias (−0,36; IC [−0,77; −0,08]). Custo ×0,5 e ×2 praticamente iguais (−0,060 e −0,057).
- A correção mexeu pouco em `P1`–`P3` (que ficam em caixa a maior parte do tempo) e muito nos baselines largos (`COMPRAR_E_SEGURAR` caiu de 0,81 para 0,68). O motor antigo favorecia ligeiramente os baselines nos dois sentidos, e a leitura da hipótese principal não depende disso.

## 9. Desvios do protocolo, achados e limitações

**Desvios (todos declarados):**

1. *Antes da primeira execução:* acrescentei a variante "sem faixa de tolerância" (`band=0`). Ao escrever os testes descobri que o motor existente (`run_weighted`) **retém** moedas cujo peso-alvo muda menos de 5 p.p.; com cerca de 30 moedas (peso ~3% cada) isso significa que as posições quase nunca são reajustadas e moedas que saem do universo elegível liberam caixa que não é reinvestido. O efeito: `COMPRAR_E_SEGURAR` fica só 57% investido no cenário-base, e outras carteiras chegam a ultrapassar 100% de exposição bruta em até 6% (`MOMENTO_SIMPLES`, 106%). Isso valia igual para todas as políticas. **Foi corrigido depois, na auditoria de consolidação** (motor `weights-2`, commit `0477f27`; ver 8.6 e `docs/AUDIT.md`). Com `band=0` o baseline fica 99,7% investido e seu Sharpe cai de 0,81 para 0,64; a conclusão sobre `P1` não muda (−0,059).
2. *Depois da primeira execução (revisão 2):* acrescentei a seção suplementar "IC da comparação primária em todas as variantes" (8.4), depois de ver que o cenário-base tinha esse artefato. É descritiva, não escolhe cenário nenhum e não entra na família; por isso o ID do experimento mudou (`30d753af…` → `494685b0…`). Os resultados da base são idênticos nas duas execuções; a primeira continua no registro.

**Limitações:**
- **Sem teste prospectivo.** Toda a história foi inspecionada. As tabelas de `P1`–`P4` foram fixadas antes de olhar o desempenho das candidatas por regime, mas a Fase 4 já tinha descrito retornos futuros por regime sobre a mesma série.
- Uma única história de mercado; poucos episódios por regime; as janelas anuais são correlacionadas.
- Viés de sobrevivência (moedas de hoje) e elegibilidade por SMA 200; spread e slippage estimados, não medidos.
- Execução no fechamento de `D` (o motor não tem convenção de abertura de D+1). O atraso de 1 dia é só uma variante.
- A Fase 3 não existe no repositório: o bootstrap em blocos, o Holm e o registro de experimentos implementados aqui são o mínimo para esta fase, **não** uma restauração dela. O bootstrap em blocos de 20 dias não captura a dependência de prazo mais longo dos regimes.
- Sharpe com taxa livre de risco zero e carteiras que ficam longos períodos em caixa: comparar Sharpe entre políticas com exposições muito diferentes favorece quem tem menos risco; por isso volatilidade, pior queda e exposição são mostradas ao lado.
- O que não foi testado: shorts, alavancagem, outros tamanhos de carteira, regras de saída alternativas, classificadores diferentes (clusterização, estados latentes), regime por moeda.

## 10. Conclusão

**Inconclusivo, sem evidência a favor da hipótese.** A seleção de estratégias por regime, nas quatro tabelas simples pré-definidas, não superou a regra de tendência fixa em Sharpe (estimativa pontual negativa ou nula, intervalos largos que incluem zero, nada significativo após Holm), e a variante aprendida piorou o resultado. Isso não prova que o regime seja inútil: a amostra tem poucos episódios e não permite concluir nem a favor nem contra. Não há justificativa, com estes dados, para integrar a política à produção.

## 11. Como reproduzir

```bash
uv run python research/regime_policy_study.py     # estudo completo (cerca de 30 s); registra e confere o experimento
uv run pytest tests/test_regime_policy.py         # 20 testes da Fase 5
```

Saídas em `data/research/` (fora do Git): `experiments.parquet`, `regime_policy_<id>.parquet`, `…_decisions.parquet` e `…_mappings.parquet`. A segunda execução com os mesmos dados imprime `(reproduzido)`; se algum resultado divergir, o registro é recusado (`ExperimentConflict`) e nada é sobrescrito.

# Roadmap quantitativo: progresso verificado

Este arquivo registra o que foi **verificado no código e nos testes deste repositório**, não o que foi planejado ou relatado em conversas anteriores. Última atualização: Fase 5, 16/10/2026.

> [!WARNING]
> O enunciado da Fase 4 descreve as Fases 0 a 3 (coleta point-in-time com checksums, motor único com execução em D+1, validação estatística com bootstrap temporal, controle de múltiplas comparações e registro de experimentos). Ao inspecionar este repositório (`crypto-analyzer`, branch `main`), **esses artefatos não foram encontrados**. Também não existiam `docs/QUANT_ROADMAP_PROGRESS.md` nem `docs/LEGACY.md` antes desta atualização. Nada abaixo presume que trabalho de outra sessão ou de outro repositório (`cripto-analysis`) esteja disponível aqui.

## Estado das fases anteriores (o que existe de fato)

| Fase | Pedido | O que foi encontrado | Situação |
|---|---|---|---|
| 0 | Testes, tipagem, CI, documentação | 151 testes passando antes da Fase 4, `mypy --strict` limpo, `uv.lock` consistente, documentação em `docs/`. O único workflow do GitHub (`daily.yml`) roda o pipeline diário; **não há workflow de CI** que rode testes e `mypy`. | Parcial |
| 1 | Coleta histórica oficial, checksums, universo point-in-time, auditoria de candles | Coleta pela API REST da Binance (`binance_adapter.py`), auditoria de candles (`data_quality.audit_candles`), universo estático de 32 moedas atuais (viés de sobrevivência). Sem verificação de checksum, sem universo point-in-time, sem as 676 moedas históricas. Os scripts antigos de coleta (`extract_*.py`) estão **apagados na árvore de trabalho** (não commitados). | Parcial / não encontrado |
| 2 | Motor único de backtest, sinal em D, execução na abertura de D+1, custos, reconciliação | `selection_backtest.run_weighted`: pesos decididos no fechamento de `t` valem no retorno de `t+1` (**execução no fechamento**, não na abertura de D+1), com taxa, spread estimado e slippage. `trade_simulator` tem um motor anterior (regra SMA 200). Dois motores coexistem; sem reconciliação contábil formal. | Parcial |
| 3 | Walk-forward, IC, bootstrap temporal, múltiplas comparações, robustez, registro de experimentos | Só: walk-forward **anual** descritivo e 100 sorteios aleatórios em `research/selection_study.py`; bootstrap em blocos apenas na previsão de preço (`forecast.py`). Sem IC para as estratégias, sem correção de múltiplas comparações, sem registro de experimentos. Os resultados reais do estudo de seleção seguem **pendentes** (ver `docs/backtesting.md`). | Não concluída |

## Fase 4: classificação de regimes de mercado

Metodologia, contrato, resultados e limitações: [regimes.md](regimes.md).

### Diagnóstico da implementação anterior

Regime só por SMA 200 e SMA 50 do BTC (`selection.regime_series`), causal mas sem volatilidade, sem confirmação (73 trocas em 9 anos), com definição duplicada em `anomaly_detector.regime_up` e sem versão ou parâmetros registrados. Detalhes na seção 1 de [regimes.md](regimes.md).

### Abordagem escolhida

Regras explícitas, duas dimensões independentes (tendência: distância à média de 200 dias e sua inclinação; volatilidade: percentil contra o passado do próprio ativo), zona morta, confirmação de 5 dias e histerese. Sem clusterização, sem estados latentes, sem probabilidades. Alternativas descartadas e motivos: seção 3 de [regimes.md](regimes.md).

### Definição temporal

`D` é a abertura do candle; a linha de `D` usa só candles fechados até `D`; `known_at = D + 1 dia`; `as_of` é injetado; a execução continua a do motor existente.

### Arquivos alterados ou criados

| Arquivo | Mudança |
|---|---|
| `src/transformers/regimes.py` (novo) | Classificador causal, contrato `REGIME_SCHEMA`, versão e fingerprints |
| `src/transformers/regime_evaluation.py` (novo) | Frequência, episódios, transições, trocas por ano, sensibilidade, walk-forward da volatilidade, desfechos exploratórios |
| `src/config.py` | Parâmetros `REGIME_*` (fixados a priori) |
| `src/pipeline.py` | Calcula e publica `market_regimes.parquet` (só leitura; não alimenta nenhuma regra de negociação) |
| `frontend/src/types/signals.ts`, `frontend/src/data/loadSignals.ts` | Tipo `MarketRegime` e leitor opcional; nenhuma tela alterada |
| `research/regime_study.py` (novo) | Estudo temporal, grava `data/research/regime_study.parquet` |
| `tests/test_regimes.py` (novo) | 32 testes |
| `docs/regimes.md` (novo), este arquivo (novo), `docs/architecture.md`, `docs/development.md`, `docs/strategies.md` | Documentação |

Não foram alterados: `selection.py`, `allocation.py`, `selection_backtest.py`, `anomaly_detector.py`, `recommendation.py`, `notification.py`, o regime antigo e seus consumidores, o orçamento, o dimensionamento, os limites de risco e a estratégia de referência.

### Verificações executadas (16/10/2026)

| Comando | Resultado |
|---|---|
| `uv run pytest` | 183 passaram (151 anteriores + 32 novos), 0 falhas |
| `uv run mypy --strict src/ mcp_server.py` | Sem erros (36 arquivos) |
| `uv lock --check` / `uv sync --locked --dry-run` | Consistente; sem mudanças |
| `npm run build` (em `frontend/`: `tsc --noEmit` estrito + `vite build`) | Passou |
| `uv run python research/regime_study.py` | Rodou sobre a base local real (BTC, 17/08/2017 a 15/10/2026) |
| Pipeline `--offline` sobre cópia da base real em pasta temporária | Publicou `market_regimes.parquet` (3.347 linhas); último dia `ALTA`/`NORMAL`, `OK`; `legacy_regime` = `recommendation.regime` = `FAVORAVEL` |
| Mutação (janela centrada; percentil sobre a série inteira) | Os testes de causalidade falharam nos dois casos, como esperado |

### Critérios de aceitação

| Critério | Situação |
|---|---|
| Classificação implementada e documentada | **Cumprido** |
| Causalidade temporal coberta por testes | **Cumprido** (truncamento do futuro, alteração e remoção de dados futuros, candle aberto, percentil só com o passado, verificação de mutação) |
| Parâmetros e features versionados | **Cumprido** (`CLASSIFIER_VERSION`, `params_hash`, `REGIME_*` em `config.py`) |
| Resultados reproduzíveis | **Cumprido** (tabela idêntica para os mesmos dados e parâmetros; `data_fingerprint` encadeado) |
| Dados ausentes e estados indeterminados tratados | **Cumprido** (`status` por dimensão, `INDETERMINADO`, `INDISPONIVEL`; nada preenchido com zero) |
| Avaliação de estabilidade temporal | **Parcialmente cumprido**: descritiva (por ano, por período, sensibilidade, walk-forward da volatilidade). Sem validação estatística formal, porque a Fase 3 não existe |
| Integração não altera regras de negociação | **Cumprido** (teste que troca os regimes e compara sinais, aportes, recomendação e backtest) |
| Limitações explicitadas | **Cumprido** (seção 8 de [regimes.md](regimes.md)) |
| Testes e verificações aplicáveis executados | **Cumprido** (tabela acima) |
| Documentação reflete o estado real | **Cumprido**, incluindo a ausência das Fases 0–3 como descritas |
| Dependência da Fase 3 | **Pendente**: nada que dependa de IC, bootstrap temporal ou correção de múltiplas comparações foi afirmado |

### Limitações remanescentes

Resumo; lista completa em [regimes.md](regimes.md): uma única série e uma única história de mercado; parâmetros não validados contra alternativas por método estatístico formal; forte dependência da janela da média (150 e 250 dias mudam ~17–20% dos rótulos); volatilidade relativa ao passado (quase nunca `ALTA` em 2023–2025); confirmação de 5 dias atrasa viradas; sem breadth nem volume; desfechos posteriores são exploratórios.

### Dependências para a Fase 5 (seleção adaptativa por regime)

1. Fase 3 de fato implementada: IC com bootstrap temporal, correção de múltiplas comparações, registro de experimentos.
2. Motor único de backtest com a execução definida (fechamento de `D` hoje; abertura de `D+1` se for o contrato desejado) e reconciliação contábil.
3. Universo point-in-time e uma decisão sobre as moedas históricas (676) antes de usar breadth.
4. Decisão explícita, com evidência fora da amostra, sobre a janela da média e a confirmação.
5. Autorização explícita para qualquer mudança na estratégia de referência ou nas regras de compra, venda e stop.

### Estado do Git (Fase 4)

A Fase 4 foi commitada localmente (`d45b976`, sem push) a pedido do usuário. As alterações antigas não commitadas (README, remoção dos scripts antigos, parte de `docs/`) foram preservadas fora desse commit.

## Fase 5: seleção de estratégias por regime (pesquisa)

Protocolo, resultados e limitações: [regime_policy.md](regime_policy.md). Estudo de pesquisa isolado da produção: **nada** em `pipeline.py`, seleção, alocação, recomendação, painel ou Telegram foi alterado, e um teste confere que a produção não importa os módulos novos.

### Auditoria inicial (o que existia)

Fase 4 presente, com os 32 testes passando; motor `selection_backtest.run_weighted` (execução no fechamento de `D`, sem convenção de abertura de D+1); baselines em `baseline_targets`. **Ausentes:** bootstrap e intervalos para estratégias, controle de múltiplas comparações, Sortino e tempo de recuperação, registro de experimentos. Foram implementados só os componentes mínimos para esta fase, sem declarar a Fase 3 restaurada.

### Resultado

**Hipótese principal não sustentada; resultado inconclusivo, com estimativa pontual nula ou negativa.** Primária (`P1_DEFENSIVA` contra `TENDENCIA_SMA200`): diferença de Sharpe −0,07, IC 95% [−0,20; +0,06], p = 0,31. Das 20 comparações da família, nenhuma tem p < 0,05 antes do ajuste (mínimo 0,08) e todos os p de Holm são 1,0. A diferença da primária é negativa nas 12 variantes de robustez. A política aprendida (`P5`) foi a pior da família. Não há base para integrar nada à produção.

### Achado sobre o motor existente

A faixa de tolerância de 5 p.p. de `run_weighted` deixa carteiras largas (cerca de 30 moedas) com exposição média de só 57% (`COMPRAR_E_SEGURAR`) e permite exposição bruta de até 106% (`MOMENTO_SIMPLES`). Vale igual para todas as políticas e não foi corrigido (mudaria o backtest de produção). Com faixa zero o baseline fica 99,7% investido (Sharpe 0,64) e a conclusão não muda. O `selection_backtest.parquet` publicado pelo pipeline carrega o mesmo artefato.

### Arquivos criados

| Arquivo | Papel |
|---|---|
| `src/transformers/regime_policy.py` | Tabelas de regime → estratégia (`regime-policy-1.0.0`), política aprendida só com o passado, guarda de `known_at` |
| `src/transformers/policy_experiment.py` | Cenário: baselines, candidatas e políticas sob as mesmas condições |
| `src/transformers/policy_study.py` | Protocolo completo, comparações, Holm, robustez |
| `src/transformers/policy_evaluation.py` | Métricas (Sharpe, Sortino, quedas), bootstrap em blocos, Holm, tamanho efetivo, fingerprints |
| `src/loaders/experiment_log.py` | Registro append-only de experimentos |
| `research/regime_policy_study.py` | Execução e gravação em `data/research/` |
| `tests/test_regime_policy.py` | 20 testes |
| `docs/regime_policy.md` | Protocolo (escrito antes da primeira execução), resultados e desvios |

### Verificações executadas (16/10/2026)

| Comando | Resultado |
|---|---|
| `uv run pytest` | 203 passaram (183 anteriores + 20 novos), 0 falhas |
| `uv run mypy --strict src/ mcp_server.py` | Sem erros (41 arquivos) |
| `uv lock --check` / `uv sync --locked --dry-run` | Consistente; sem mudanças |
| `npm run build` (em `frontend/`) | Passou (o frontend não foi alterado) |
| `uv run python research/regime_policy_study.py` | Executado duas vezes na revisão 2; a segunda confirmou "reproduzido" (mesmo hash de resultados) |
| Mutação (regime de outro dia na decisão; P5 treinando com o ano corrente) | Os testes de causalidade falharam nos dois casos |

### Critérios de conclusão

| Critério | Situação |
|---|---|
| Implementação real auditada | **Cumprido** |
| Política definida, versionada e testada | **Cumprido** (4 tabelas fixas + 1 aprendida) |
| Sem vazamento temporal conhecido | **Cumprido** (truncamento do futuro, alteração de preços futuros e treino de P5 testados; mutações detectadas) |
| Baselines sob condições equivalentes | **Cumprido, com ressalva**: mesmo motor, calendário, custos e capital inicial em caixa; o artefato da faixa de tolerância está documentado e há variante sem faixa |
| Avaliação temporal documentada | **Parcial**: anos civis, `VALIDACAO` e `TESTE`, mas **não há período prospectivo intocado**; tudo é exploratório |
| Custos de transição incluídos | **Cumprido** |
| Incerteza e múltiplas comparações | **Cumprido, com ressalva**: bootstrap em blocos e Holm implementados; blocos de 20 dias provavelmente subestimam a incerteza de regimes longos |
| Resultados negativos preservados | **Cumprido** (registro append-only, duas revisões, resultados completos em Parquet) |
| Testes e verificações executados | **Cumprido** (tabela acima) |
| Documentação permite reproduzir | **Cumprido** |
| Produção inalterada | **Cumprido** |

### O que ainda precisa ser verificado nas Fases 0–4

Fases 0–3 continuam como no quadro do início (parcial ou não encontrado). Fase 4: a sensibilidade à janela da média (150/250 dias mudam ~17–20% dos rótulos) e a ausência de evidência de que os regimes separem retornos futuros seguem sem resolução. Motor: decidir se a faixa de tolerância deve mudar (afeta o `selection_backtest.parquet` de produção) e se a execução deve passar à abertura de D+1. Validação: um período prospectivo só existirá com dados futuros.

### Estado do Git (Fase 5)

Nenhum commit, push, merge ou rebase da Fase 5. Todas as alterações estão no diretório de trabalho, junto com as pendências antigas, que foram preservadas.

## Auditoria de consolidação F0–F5 (16/10/2026)

Matriz completa, achados e pendências por prioridade: [AUDIT.md](AUDIT.md). O quadro "Estado das fases anteriores" acima é o retrato do momento da Fase 4; o estado atual está no AUDIT.md.

**Mudou nesta etapa (cada item com teste de regressão):**
- **Motor de pesos corrigido** (`ENGINE_VERSION = weights-2`): a faixa de tolerância permitia exposição de até 118% e deixava caixa parado (comprar e segurar com 57% de exposição). Sinais, aportes e recomendação não mudaram; os baselines largos ficaram mais fracos e a frase de evidência foi atualizada. A Fase 5 foi refeita com o motor novo e a conclusão se manteve.
- **Texto "fora da amostra"** retirado da frase de evidência (o período de teste já foi consultado).
- **Higiene:** workflow de CI (`ci.yml`, ainda não executado no GitHub), dependências mortas (`ccxt`, `aiohttp`) e `requirements.txt` removidos, `numpy` declarada, testes dos loaders.
- **Dados:** sinalização de possível deslistagem (sem presumir perda total) e contagem de dias sem preço.
- **Validação:** catálogo de estratégias (nenhuma confirmada como robusta, por teste) e classificação de qualidade da evidência.

**Continua aberto:** unificar os dois motores (o nome `COMPRAR_E_SEGURAR` existe nos dois com simulações diferentes); universo point-in-time (bloqueado por falta de fonte); convenção de execução; usar o bootstrap nos demais estudos; redesign do frontend (especificação não recebida).

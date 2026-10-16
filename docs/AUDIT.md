# Auditoria geral F0–F5 e consolidação

Auditoria de 16/10/2026 sobre a branch `main` (HEAD de partida `012a432`). Cada linha foi verificada **no código e nos testes deste repositório**; os relatórios das fases anteriores não foram aceitos como prova. Legenda do estado: **V** implementado e verificado · **I** implementado, insuficientemente validado · **P** parcial · **A** ausente · **B** bloqueado por falta de dados ou infraestrutura · **N/A** não se aplica.

Prioridades: **P0** crítico (resultado incorreto, vazamento, perda de dados, segredo exposto) · **P1** alto (metodologia, bugs que afetam resultados) · **P2** médio (incompleto, frágil, difícil de manter) · **P3** baixo (documentação e arrumação).

> [!IMPORTANT]
> **Nenhum P0 foi encontrado.** Não há segredo rastreado (varredura de padrões de token e chave em todos os arquivos versionados; `.env` existe só localmente e está no `.gitignore`; o conteúdo não foi lido), não há vazamento temporal no classificador de regimes nem nas políticas (testes de truncamento do futuro com mutação), e nenhuma perda de dados. Foram encontrados e **corrigidos dois P1** (motor de pesos; texto "fora da amostra") e vários P2. A conclusão histórica **"nenhuma estratégia foi confirmada como robusta" permanece** e agora está registrada em código (`strategy_catalog.confirmed_robust() == ()`).

## Estado do repositório na partida

Branch `main`, HEAD `012a432` (Fase 5), sem push. Alterações do usuário, preservadas e não tocadas: `README.md` e `frontend/README.md` modificados (o README ganhou uma única correção, ver P3), exclusão de `architecture.md` da raiz, `extract_*.py`, `feature_engineering.py`, `signal_analyzer.py` e `run_monthly.cmd`, e `docs/{backtesting,forecast,telegram,usage}.md` não rastreados. Pontos de partida: 203 testes passando, `mypy --strict` limpo, `uv lock --check` consistente, build do frontend ok.

## F0: higiene, confiabilidade e qualidade

| Requisito | Onde | Verificação | Estado / achado | Prio. | Ação / teste de regressão |
|---|---|---|---|---|---|
| Separação I/O × regra (CLAUDE.md §1) | `src/transformers/` | `grep` de `os`, `pathlib`, `aiohttp`, `ccxt`, `datetime.now`, leitura/escrita de Parquet e CSV em arquivo | **V**. Só `datetime.timedelta/timezone` (tipos) e um `to_csv` sem caminho (serialização em memória para hash) | – | – |
| Tipagem estática | `mypy --strict src/ mcp_server.py` | Executado | **V**: sem erros em 42 arquivos | – | CI |
| Testes | `tests/` | Executados | **V** (contagem na seção "Verificações") | – | – |
| Cobertura das áreas críticas | `parquet_loader`, `history_store`, `market_store` não tinham testes diretos | Mapeamento módulo × teste | **P** → **V**: escrita atômica (falha preserva o arquivo anterior), snappy do `daily_signals`, snapshots, upsert idempotente e retomada | P2 | `tests/test_loaders.py` (5 testes) |
| CI | `.github/workflows/` | Só existia `daily.yml` (pipeline diário) | **A** → **V (não executado)**: `ci.yml` roda `uv lock --check`, `uv sync --locked`, `mypy --strict`, `pytest` e o build do frontend. **Não foi executado no GitHub** (sem acesso); pode falhar na primeira rodada por diferenças Windows × Linux | P1 | Verificar a primeira execução do workflow |
| Dependências | `pyproject.toml`, `uv.lock`, `requirements.txt` | `grep` de imports | `ccxt` e `aiohttp` declaradas e **nunca importadas**; `numpy` importada e não declarada; `requirements.txt` desatualizado e sem referência | P2 | Removidas as duas dependências mortas, `numpy` declarada, `requirements.txt` removido, `uv.lock` regenerado (68 → 50 pacotes); testes e `mypy` repetidos |
| Segredos e `.gitignore` | `.gitignore`, `git ls-files` | Varredura de padrões; nenhum `.env`, `.pem`, `.key`, `*.pyc`, `node_modules`, `dist` rastreado | **V**. `data/`, `logs/`, `frontend/public/*.parquet`, `.env*` ignorados | – | – |
| Tratamento de exceções e logs | `pipeline.py`, `notifiers/telegram.py` | Leitura; testes de `redact` e de mensagem sem segredo | **V**: falha de fonte não derruba a análise; token nunca aparece em log, mensagem ou exceção (testado) | – | – |
| Módulos órfãos | `storage.py`, `market_metrics.py` | `grep`: nada os importa; apontam para scripts apagados | **I**: código morto | P3 | Documentado em [LEGACY.md](LEGACY.md); remoção é decisão do dono |
| Reprodutibilidade da instalação | `uv.lock`, `.python-version` (3.12) | `uv lock --check`, `uv sync --locked --dry-run` | **V**. `requires-python >=3.11` no `pyproject.toml` contra 3.12 no resto | P3 | – |

## F1: dados históricos e qualidade

| Requisito | Onde | Verificação | Estado / achado | Prio. | Ação / teste |
|---|---|---|---|---|---|
| Ingestão e candle aberto | `binance_adapter.py` | Leitura + testes de extrator | **V**: só candles fechados (`k[0] + step <= end`); hosts permitidos fixos | – | – |
| Integridade (duplicatas, lacunas, preço inválido) | `data_quality.py` | Testes existentes | **V**: auditoria e limpeza; duplicado fica o último | – | – |
| Idempotência e retomada | `market_store.py` | Leitura + novo teste | **V**: upsert por (moeda, dia), retomada a partir do último candle, a versão mais recente vence | P2 | `test_market_store_upsert_...` |
| Proveniência | coluna `source`, `source_log` | Leitura + teste de fonte misturada | **V** para fonte e momento da coleta. **A** no pipeline: fingerprint dos dados (só existe nos estudos, `policy_evaluation.data_fingerprint`) | P3 | Publicar o fingerprint junto com `sources.parquet` |
| Universo e viés de sobrevivência | `config.UNIVERSE`, `universe.py` | Leitura | **I**: 32 moedas escolhidas **hoje** (liquidez e histórico atuais); moedas deslistadas, renomeadas ou convertidas não estão na amostra. Vale para todos os backtests e favorece qualquer estratégia que compra altcoins | P1 | **B**: não há fonte de listagem point-in-time no ambiente; documentado em todos os estudos |
| Ativos que deixam de negociar | `availability`, `run_weighted` | Leitura + testes | **P**: o dia sem candle torna a moeda INDISPONÍVEL e ela sai da carteira no rebalanceamento; **o preço fica parado e não há perda por deslistagem**. A desatualização longa agora é sinalizada como "possível deslistagem, pausa ou conversão, causa não verificada", sem presumir perda total. O motor passou a contar `stale_weight_days` (peso × dias sem preço) | P2 | `test_long_gap_flags_...`, `test_held_coin_without_a_price_...` |
| Moedas históricas (676) | – | `data/raw/` não é lido por nenhum módulo | **B**: não integradas ao universo; `data/raw/` não foi validado | P2 | Ver LEGACY.md |
| Offline e fontes indisponíveis | `pipeline.py` | Testes de pipeline | **V**: `--offline`, fonte fora do ar e dado velho testados; Fear & Greed ausente não vira zero | – | – |
| `compute_features` e `bfill` | `selection.py` | Leitura | **I**: a decisão de repetir o preço em dia de lacuna usa a existência de candle futuro (`raw.bfill()`). Só afeta o valor de `close` em dias **sem candle**, que nenhum consumidor usa para decidir | P3 | Anotado; sem correção |

## F2: backtesting e execução

Há **dois motores**. Convenção real de ambos (verificada no código): o sinal é calculado no fechamento do dia `t` e vale para o retorno de `t+1`, isto é, **execução no fechamento de `t`**. **Não existe execução na abertura de D+1** em nenhum motor.

| | `trade_simulator.run_portfolio` (regra de tendência, painel) | `selection_backtest.run_weighted` (seleção e Fases 4–5) |
|---|---|---|
| Posição | 0/1 por moeda, decidida todo dia | Pesos-alvo, rebalanceamento a cada 7 dias |
| Carteira | Peso igual entre as moedas com dados (rebalanceada todo dia, implícito) | Pesos que flutuam com os preços; faixa de tolerância de 5 p.p. |
| Custos | Só taxa de 0,1% por lado | Taxa + spread estimado por faixa de volume + slippage |
| Caixa | Implícito (posição 0) | Explícito (sem rendimento) |
| Stops | `ExitRules`: STOP, SMA 200 e filtro do BTC, avaliados **no fechamento** (sem gap nem slippage de stop) | Não há stop por moeda |

| Requisito | Verificação | Estado / achado | Prio. | Ação / teste |
|---|---|---|---|---|
| Exposição acima de 100% e caixa parado | Reprodução com dados reais, motor antigo × novo | **Defeito confirmado (P1)**: com a faixa de 5 p.p. e ~30 moedas, as posições mantidas ficavam acima do alvo enquanto a nova entrava no alvo (exposição bruta de até **118%**) e o caixa das que saíam ficava parado (comprar e segurar com **57%** de exposição média). Afetava `selection_backtest.parquet` e a frase de evidência | **P1** | **Corrigido** (`ENGINE_VERSION = weights-2`, commit `0477f27`): o rebalanceamento vai direto aos alvos se manter as posições ultrapassar o alvo total ou deixar mais que a faixa em caixa. `guard_exposure=False` reproduz a versão 1. `tests/test_engine.py` (7 testes). Comparação abaixo |
| Mesmo nome, simulações diferentes | `COMPRAR_E_SEGURAR` existe nos dois motores | **Defeito de comparabilidade (P1)**: os números dos dois não são comparáveis (fee-only diário × pesos semanais com spread) | P1 | **Documentado** (catálogo e este quadro); **não unificado** (mudaria o painel). Pendente: decisão do dono sobre unificar os motores |
| Convenção de execução | Leitura dos dois motores | Fechamento de `t`, sem abertura de D+1. Atraso de 1 dia testado como variante (Fase 5) | P2 | Mudar a convenção é decisão metodológica do dono; não foi alterada |
| Tratamento de candles ausentes | `market_returns`, `run_weighted` | Retorno NaN → 0 (preço parado) | P2 | Agora contabilizado em `stale_weight_days` (valores pequenos: 0,0 a 0,7 peso-dia nas estratégias do teste) |
| Resultados publicados × reprodução | Pipeline `--offline` refeito; comparação com os arquivos de 15/10 | Sinais, aportes, decisão e regime **idênticos**; só `selection_backtest.parquet` e a frase de evidência mudaram | – | Artefatos regenerados |

**Efeito da correção no período de teste (2023-01-01 a 2026-10-15; 32 moedas).**

| Estratégia | Sharpe v1 → v2 | Retorno total v1 → v2 | Exposição média v1 → v2 | Exposição máxima v1 → v2 |
|---|---|---|---|---|
| `SELECAO` (produção) | 0,70 → 0,70 | +76,8% → +75,5% | 42,9% → 42,2% | 103% → 100% |
| `SELECAO_PESO_IGUAL` | 0,35 → 0,35 | +26,1% → +24,9% | 58,0% → 57,2% | 106% → 100% |
| `MOMENTO_SIMPLES` | 0,97 → 0,98 | +483% → +489% | 100,3% → 99,3% | 110% → 100% |
| `TENDENCIA_SMA200` | 0,61 → 0,56 | +87,1% → +69,5% | 42,2% → 38,3% | 111% → 100% |
| `COMPRAR_E_SEGURAR` | 0,77 → 0,66 | +176% → +127% | 81,6% → 99,6% | 101% → 100% |
| `BTC` | 1,13 → 1,13 | +388% → +388% | 99,6% → 99,6% | 100% → 100% |

A seleção de produção quase não muda; os baselines largos mudam mais (e ficam **mais fracos**, de modo que a seleção passa a superar `COMPRAR_E_SEGURAR` e `TENDENCIA_SMA200`, mas continua sem superar `MOMENTO_SIMPLES` nem `BTC`). A frase de evidência agora diz "não superou momento simples, só Bitcoin"; antes dizia também "comprar e segurar todas". **A conclusão ("vantagem não demonstrada") permanece.** Os períodos TREINO/VALIDAÇÃO também foram comparados (a seleção: 0,72 → 0,74 e 1,18 → 1,24 de Sharpe).

## F3: validação estatística

A F3 **não existia como descrita**. Estado do que há, verificado:

| Requisito | Onde | Estado | Prio. |
|---|---|---|---|
| Métricas com amostra mínima | `policy_evaluation.metrics` (252 dias) | **V** (Sharpe, Sortino, quedas e recuperação; `NaN` abaixo do mínimo, testado) | – |
| Bootstrap com dependência temporal, pareado | `paired_sharpe_bootstrap` (blocos circulares) | **V** na Fase 5. **Não** usado em `selection_study`, `strategy_lab` nem `selection_backtest` | P2 |
| Múltiplas hipóteses | `holm_adjust` | **V**, só na família da Fase 5 | P2 |
| Walk-forward e separação cronológica | `chronological_split`, `year_windows`; P5 anual; `selection_study` anual | **P**: descritivo; sem período prospectivo | P2 |
| Registro de experimentos e fingerprints | `loaders/experiment_log.py`, `data_fingerprint`, `experiment_id`, `results_digest` | **V** (append-only, conflito recusado, reprodução confirmada). **Só** a Fase 5 grava nele | P2 |
| Catálogo de estratégias | `transformers/strategy_catalog.py` | **A → V**: todo nome usado pelos motores está listado; teste falha se surgir um nome fora do catálogo | P2 |
| Classificação da qualidade da evidência | `policy_evaluation.classify_evidence` | **A → V**: `INSUFICIENTE`, `SEM_EVIDENCIA`, `INDICIO_EXPLORATORIO`, `CONFIRMADO_PROSPECTIVO` (este último exige período prospectivo, que não existe) | P2 |
| "Fora da amostra" | `evidence()` e `recommendation.py` chamavam o teste de 2023+ de "fora da amostra" | **Defeito de texto (P1)**: o período já foi consultado em várias fases | **P1** | **Corrigido**: "período de teste (…; já consultado antes, não é prospectivo)" |

Nada disso foi apresentado como restauração da F3.

## F4: regimes de mercado

| Requisito | Estado / evidência | Prio. |
|---|---|---|
| Classificador causal, `known_at`, versão, parâmetros e fingerprint | **V** (32 testes, truncamento do futuro, mutação detectada) | – |
| Estados indisponíveis e histórico insuficiente | **V** (`status`, `INDETERMINADO`, `INDISPONIVEL`) | – |
| Duas definições do filtro do BTC | **I** → **V**: `anomaly_detector.regime_up` e `selection.regime_series` concordam em todos os dias classificáveis (teste novo). Unificar o código é P3 | P3 |
| Sensibilidade à janela da média | **Limitação aberta, não resolvida**: 150 e 250 dias mudam ~17–20% dos rótulos | P2 |
| Regimes separam retornos futuros? | **Sem evidência** (Fase 4); mantido | – |
| Separação pesquisa × produção | **V**: `pipeline.py` só publica `market_regimes.parquet`; nenhuma regra o lê (teste) | – |

## F5: seleção adaptativa

| Requisito | Estado / evidência |
|---|---|
| Política versionada, candidatas reais, baselines comparáveis, custos de transição, `MISTO`/`INDISPONIVEL` | **V** (`regime-policy-1.0.0`; 23 testes) |
| Treino estritamente temporal, sem vazamento | **V** (truncamento do futuro; P5 treina só com dados anteriores ao ano; mutações detectadas) |
| Bootstrap, Holm, registro reproduzível, robustez, isolamento | **V** |
| Motor | **Refeito com o motor corrigido** (revisões 3 e 4); a conclusão não muda: primária −0,06 (IC 95% [−0,18; +0,05]), 20 de 20 comparações `SEM_EVIDENCIA`, política aprendida pior da família. **Não integrada à produção** |

## Pendências consolidadas

**P0:** nenhuma.

**P1 (corrigidas):** motor de pesos com exposição acima de 100% e caixa parado · texto "fora da amostra" · ausência de CI de testes (workflow criado, ainda não executado no GitHub).
**P1 (abertas):** (a) dois motores com resultados não comparáveis e o mesmo nome de estratégia: exige decisão sobre unificar; (b) viés de sobrevivência do universo: bloqueado por falta de fonte point-in-time.

**P2 (corrigidas):** estudo completo da seleção, que estava "pendente" na documentação, executado com dados reais (resultado em `docs/backtesting.md`: vantagem não demonstrada) · dependências mortas e `requirements.txt` · testes de loaders · sinalização de possível deslistagem · catálogo de estratégias · classificação de evidência · contagem de dias sem preço.
**P2 (abertas):** usar o bootstrap e a classificação de evidência também nos outros estudos (`strategy_lab`, `selection_study`) · sensibilidade do regime à janela da média · convenção de execução (fechamento × abertura de D+1) · `data/raw/` e funding rate não integrados · registrar fingerprint no pipeline.

**P3:** módulos órfãos (`storage.py`, `market_metrics.py`) · unificar as duas definições do filtro do BTC · `bfill` em `compute_features` · `requires-python` · stops avaliados no fechamento.

**Frontend:** o redesign pedido na mesma mensagem **não foi iniciado**: o texto recebido trazia o objetivo 1 e as Partes 1 a 3, sem a especificação do objetivo 2 (visual, telas, referências). Ver o fechamento do relatório.

> [!NOTE]
> Este arquivo reúne duas linhas de trabalho que evoluíram em paralelo e foram unidas no merge com `origin/main`: (1) **Fases 0 a 3 do remoto** (commit `2581890`: dados point-in-time com checksum, motor de referência, validação estatística) e (2) **a linha local** (Fases 4 e 5 e a validação do COMPRAR por moeda). O aviso da seção local de que as Fases 0 a 3 "não foram encontradas" vale para o estado local antes do merge; agora elas existem (primeira parte).

# Parte 1 — Fases 0 a 3 (origin/main)

# Roadmap quantitativo — progresso

Registro do trabalho do roadmap "Plataforma de Pesquisa Quantitativa Estatisticamente Rigorosa". Cada fase lista o
que mudou, o que foi executado (com o resultado real), o que falta e os riscos que continuam. Nada aqui é evidência
de lucratividade.

- Commit de referência: `abcccd6` (branch `main`, árvore limpa no início).
- Branch de trabalho: `feature/quantitative-research`. Sem commit e sem push até autorização.

## Acesso a dados no ambiente de desenvolvimento (testado em 2026-10-16)

Sessão em contêiner na nuvem (não é a máquina do usuário). Teste controlado, uma requisição por host:

| Host | Resultado | Uso |
|---|---|---|
| `api.binance.com` (REST) | bloqueado (HTTP 403 no proxy) | pipeline diário: só roda no GitHub Actions ou na máquina do usuário |
| `data-api.binance.vision` (REST espelho) | bloqueado | idem |
| `data.binance.vision` (CDN do arquivo) | bloqueado | — |
| `s3-ap-northeast-1.amazonaws.com/data.binance.vision` (bucket do arquivo oficial) | **acessível (HTTP 200)** | base point-in-time da Fase 1: candles diários de todos os pares spot, inclusive deslistados, com SHA-256 |
| `api.alternative.me` (Fear & Greed) | bloqueado | — |
| `api.coingecko.com` | bloqueado | — |
| `api.github.com` | acessível | consulta de releases, branches e execuções do Actions |

Consequências: dados reais de preço e volume da Binance agora podem ser coletados aqui pelo arquivo oficial (com
atraso de 1 a 3 dias nos arquivos diários). Fear & Greed e market cap continuam indisponíveis, e o pipeline diário
(REST) não pode ser executado de ponta a ponta neste ambiente. As tabelas de resultados reais do README seguem
como **exploratórias e já consumidas**; não foram recalculadas.

## Status por fase

| Fase | Tema | Status |
|---|---|---|
| 0 | Linha de base e higiene de engenharia | concluída (ver critérios) |
| 1 | Dados point-in-time e qualidade | concluída (ver critérios e limitações) |
| 2 | Motor de backtest único | concluída (ver critérios e limitações) |
| 3 | Validação estatística | concluída, com critérios parciais (ver critérios e limitações) |
| 4 | Classificação de regimes | pendente |
| 5 | Seleção adaptativa (modo sombra) | pendente |
| 6 | Gestão de risco da carteira | pendente |
| 7 | Registro prospectivo e monitoramento | pendente |
| 8 | Integração final e documentação | pendente |

---

## Fase 0 — linha de base e higiene de engenharia

### Linha de base medida no commit `abcccd6` (antes de qualquer alteração)

| Verificação | Comando | Resultado real |
|---|---|---|
| Testes Python | `uv run pytest -q` | **151 passed** (46,5 s) |
| Tipagem do pacote | `uv run mypy --strict src/` | **Success: no issues found in 33 source files** |
| Tipagem incluindo `mcp_server.py` | `uv run mypy --strict src/ mcp_server.py` | Success, 34 arquivos |
| Tipagem de `research/` e `tests/` | `uv run mypy --strict src/ research/ tests/ mcp_server.py` | **151 erros em 11 arquivos** (10 em `research/`, 141 em `tests/`; 107 só em `tests/test_selection.py`). Preexistente; o contrato documentado no README é `src/`. Não corrigido na Fase 0 |
| Frontend: tipagem | `npm --prefix frontend run typecheck` | ok |
| Frontend: build | `npm --prefix frontend run build` | ok (`dist/` gerado; aviso de chunk > 500 kB, não é erro) |
| Testes de frontend | — | **não existem**: não há framework de teste no `package.json`. Adicionar um (ex.: Vitest) é dependência nova; fica registrado como pendência, não feito |
| Dados reais | `curl` aos hosts de mercado | bloqueados (ver restrição acima) |

### Resultados históricos reais preservados (exploratórios, dados já consumidos)

As tabelas do README ("O que o backtest mostra", "Laboratório de estratégias", "Previsão estatística"), com dados
até 2026-10-14, são a única referência de resultados reais. Classificação metodológica:

- o período 2023–2026 ("teste") foi olhado repetidamente durante o desenvolvimento (inclusive pela frase de
  evidência do Telegram, recalculada todo dia sobre esse mesmo período) e pela auditoria; **não é um teste final
  intocado**;
- os números estão sujeitos aos vieses listados abaixo (sobrevivência, universo filtrado com dado atual, execução
  no fechamento do próprio candle do sinal, uma única história de mercado);
- não foram reproduzidos neste ambiente (sem acesso aos dados).

Ficam no README como **referência histórica exploratória**. A avaliação prospectiva nova começa na Fase 7, a partir
da data de implantação do registro imutável de sinais.

### Linha de base de regressão (sintética, reproduzível)

Como os artefatos reais não podem ser reproduzidos, a Fase 0 congela o comportamento do código, não do mercado:

- `tests/synthetic_market.py`: 6 moedas sintéticas (fator comum com ciclos de alta e baixa + ruído próprio,
  listagens escalonadas de 2017 a 2020) e um Fear & Greed sintético; datas fixas e semente fixa (`20261016`);
- `tests/test_golden_baseline.py`: roda `pipeline.analyze` completo numa pasta temporária e compara com
  `tests/golden/*.parquet` (tolerância relativa 1e-7): `performance`, `selection_backtest`, `backtest`, `forecast`,
  colunas escalares de `daily_signals` e `recommendation`, e um resumo por moeda de `history`;
- a referência foi gerada com `src/` **idêntico** ao commit `abcccd6` (`git diff --stat -- src/` vazio no momento
  da geração).

Qualquer mudança futura que altere esses números falha o teste. Mudança intencional de regra deve ser documentada
aqui antes de regenerar (`UPDATE_GOLDEN=1 uv run pytest tests/test_golden_baseline.py`). Os números sintéticos não
dizem nada sobre o mercado real.

### Mapa de consumidores das saídas

| Saída | Produtor | Consumidores |
|---|---|---|
| `frontend/public/daily_signals.parquet` | `pipeline.analyze` → `loaders.parquet_loader.write_daily_signals` (último arquivo gravado) | painel (`frontend/src/data/loadSignals.ts`, tipo em `frontend/src/types/signals.ts`), `mcp_server.py` (caminho de saída) |
| `frontend/public/recommendation.parquet` | `pipeline.analyze` | painel (obrigatório, exige 1 linha e o mesmo `run_ts`) |
| `history`, `backtest`, `performance`, `positions`, `closed_positions` `.parquet` | `pipeline.analyze` / `refresh_positions` | painel (obrigatórios) |
| `selection_backtest`, `forecast`, `sources` `.parquet` | `pipeline.analyze` | painel (opcionais) |
| `strategy_lab.parquet` | `research/strategy_lab.py` | painel, aba Pesquisa (opcional) |
| Mensagem do Telegram | `transformers.notification.format_report` sobre `signals` + `recommendation` em memória | `notifiers.telegram` |
| `data/market/**` (base) | `loaders.market_store`, `loaders.source_log` | `pipeline`, `research/*` |
| `data/signals/history/date=*/signals.parquet` | `loaders.history_store` | `pipeline` (fallback do dia anterior) |
| `data/positions/positions.parquet` | `src/positions.py` (CLI), `frontend/server/positionsApi.ts` (rota local do dev server) | `pipeline._publish_positions` |
| `data/research/*.parquet` | `research/*.py` | leitura manual |

### O que mudou na Fase 0

| Arquivo | Mudança |
|---|---|
| `pyproject.toml`, `uv.lock` | `numpy>=2.0` declarada (usada diretamente em `src/`); lock refeito com uv 0.13.0 (a versão do workflow): só 3 linhas novas no lock |
| `requirements.txt` | gerado do `uv.lock` (`uv export --format requirements.txt --no-dev --locked --no-emit-project --no-hashes`); antes divergia (3 pacotes, sem mcp, aiohttp, numpy) |
| `.github/workflows/ci.yml` | novo: em pull request e push na `main` — `uv lock --check`, requirements em sincronia, nenhum Parquet/CSV/.env versionado (exceto `tests/golden`), `uv sync --locked`, `mypy --strict src/ mcp_server.py`, `pytest`; e `npm ci` + `npm run build` (tsc strict + vite) no frontend. Sem segredos e sem rede de mercado |
| `signal_analyzer.py` | deixou de apresentar a regra de pânico como compra (alerta informativo, `find_panic_alerts`, coluna `esticamento_sma200_pct`); saída Parquet em vez de CSV |
| `feature_engineering.py` | saída Parquet em vez de CSV |
| `run_monthly.cmd` | comentários e caminho de saída coerentes com o acima |
| `architecture.md` | marcado como histórico; o trecho que dizia COMPRAR = pânico foi substituído |
| `docs/LEGACY.md` | novo: inventário dos scripts da raiz, consumidores e decisão |
| `tests/synthetic_market.py`, `tests/test_golden_baseline.py`, `tests/golden/*.parquet` | linha de base de regressão |
| `tests/test_legacy.py` | o legado não recomenda compra no pânico e recusa CSV |

Nenhum arquivo de `src/` foi alterado na Fase 0: nenhuma regra de estratégia, risco, orçamento ou formato de saída
mudou (confirmado pelo teste de regressão, que passa contra a referência gerada do `src/` original).

### Execução local dos passos do CI (resultado real)

| Passo | Resultado |
|---|---|
| `uv lock --check` (uv 0.13.0) | ok |
| `requirements.txt` regenerado e comparado | sem diferença |
| Parquet/CSV/.env versionados (fora de `tests/golden`) | nenhum |
| `uv sync --locked` | ok |
| `uv run mypy --strict src/ mcp_server.py` | Success: no issues found in 34 source files |
| `uv run pytest -q` | **162 passed** (62,5 s) |
| `npm ci && npm run build` (frontend) | ok |

### Pontos de falha silenciosa identificados (para as próximas fases)

Verificados lendo o código; nenhum foi corrigido na Fase 0 porque corrigir muda comportamento.

1. **Universo filtrado com dado atual.** `universe.select_universe` decide quem entra usando o volume dos últimos
   30 dias e o número de candles **de hoje**, e esse universo é aplicado a todo o histórico (backtest de carteira
   "TODAS" e seleção). Viés de sobrevivência e de seleção retroativa. → Fase 1.
2. **Universo = moedas vivas hoje.** `config.UNIVERSE` não contém moedas deslistadas (LUNA, FTT etc.). → Fase 1.
3. **Execução no fechamento do candle do sinal.** Nos dois motores (`trade_simulator.run_portfolio` e
   `selection_backtest.run_weighted`) a posição decidida no fechamento de t recebe o retorno fechamento(t) →
   fechamento(t+1): equivale a executar ao mesmo preço que gerou o sinal. As operações de `trend_entries` entram
   ao `close` do dia do sinal. → Fase 2 (execução a partir do candle seguinte).
4. **Retorno ausente vira zero.** `run_weighted` faz `returns.fillna(0.0)`: candle faltando é tratado como preço
   parado, sem marcação. `compute_features` repete o preço por até 5 dias de lacuna interna (`FILL_LIMIT`), sem
   coluna de imputação além de `has_candle`. → Fases 1 e 2.
5. **Rebalanceamento diário implícito.** `run_portfolio` faz a média simples dos retornos das moedas com dado em
   cada dia (peso igual recalculado todo dia, sem custo desse rebalanceamento); `run_weighted` deixa os pesos
   flutuarem. As duas metodologias não são comparáveis. → Fase 2.
6. **Spread e slippage só no motor de seleção.** `run_portfolio` cobra só a taxa (0,1%); `run_weighted` cobra
   taxa + spread estimado + slippage. → Fase 2.
7. **Upsert sem trilha.** `market_store._upsert` sobrescreve um candle revisado (keep="last") sem registro;
   `source_log` guarda só a última execução por (fonte, escopo). Não há hash nem versão dos dados usados. → Fase 1.
8. **Sem persistência no GitHub Actions.** Cada execução baixa tudo de novo; os snapshots de `data/signals/history`
   e o registro de fontes se perdem ao fim do job; as posições não existem no runner. → Fases 1 e 7.
9. **Falha de coleta não deixa o job vermelho.** Erro da Binance numa moeda (ou em todas) vira INDISPONÍVEL e o
   pipeline termina com código 0; sem `--notify`, o aviso fica só no log. Com BTC indisponível, nenhuma compra é
   sugerida (comportamento seguro), mas não há alerta de falha de coleta fora da mensagem. → Fase 7.
10. **Fonte secundária fora do ar desliga o pânico.** Sem Fear & Greed, `panic` nunca dispara e nada distingue
    "sem pânico" de "sem dado para avaliar" na saída. → Fase 7.
11. **Escrita não atômica no Windows.** `parquet_loader.write_parquet` copia por cima do arquivo quando o rename
    falha 25 vezes (arquivo aberto pelo dev server). Documentado no código; o painel valida ao ler.
12. **Evidência sem incerteza.** `selection_backtest.evidence` declara "superou" comparando Sharpe pontuais, sem
    intervalo nem correção para comparações múltiplas, sobre o período de teste reutilizado diariamente. → Fase 3.
13. **"Bate o aleatório" não é p-valor.** `beats_random_pct` do laboratório é a proporção de sorteios vencidos, sem
    hipótese nula declarada; a escolha de parâmetros (maior Sharpe na validação, mínimo de 3 operações) não
    registra quantas combinações foram testadas para correção. → Fase 3.
14. **Anualização em amostras curtas.** `summarize_returns` anualiza qualquer período (365 dias por ano) e calcula
    Sharpe sem tratar amostra pequena. → Fase 3.

### Critérios de aceitação da Fase 0

| Critério | Situação |
|---|---|
| Testes e tipagem passam | **ok**: 162 testes (151 originais + 8 da linha de base sintética + 3 do legado); `mypy --strict src/ mcp_server.py` sem erros. `research/` e `tests/` têm 151 erros de mypy preexistentes (pendência registrada) |
| CI configurado e executável | **configurado**; os passos foram executados localmente (ver "Execução local dos passos do CI"). A execução no GitHub só acontece quando houver push/PR, que depende de autorização |
| Frontend compila | **ok**; não há testes de frontend (pendência) |
| Resultados de referência registrados | **parcial**: reais não reproduzíveis aqui (preservados no README como exploratórios); referência de regressão sintética congelada |
| Nenhuma mudança de estratégia | **ok**: `src/` intocado; regressão passa |
| Scripts antigos não contradizem o comportamento atual | **ok**: `signal_analyzer.py`, `run_monthly.cmd`, `architecture.md` corrigidos; teste em `tests/test_legacy.py` |

### Riscos metodológicos remanescentes

Todos os itens 1–14 acima. Os mais graves para a validade de qualquer resultado: universo com viés de sobrevivência
e filtrado com dado atual (1, 2), execução ao preço do próprio sinal (3) e período de teste reutilizado sem
correção nem incerteza (12, 13).

### Próxima fase recomendada

Fase 1 (dados point-in-time). Sem acesso aos dados reais, a fase entrega a infraestrutura (histórico de
elegibilidade, metadados de coleta, hash dos conjuntos, validação, idempotência) com testes sintéticos e o
mecanismo para registrar deslistagens a partir de fontes verificáveis; não pode preencher o histórico real de
deslistagens.

---

## Fase 1 — dados point-in-time, qualidade e persistência

### Investigação inicial (resultados reais)

**Fontes.** Ver "Acesso a dados" no topo. O achado que muda a fase: o bucket S3 do arquivo oficial da Binance
responde. Nele há klines diários de **todos** os pares spot que a Binance já listou, com `.CHECKSUM` (SHA-256)
publicado por arquivo, inclusive os que deixaram de negociar. Verificação feita com dados reais:

- LUNA/USDT: o arquivo mostra o colapso (fechamento de US$ 82,35 em 05/05/2022, US$ 0,00005 em 13/05/2022), 18 dias
  sem candle e a volta em 31/05/2022 a US$ 8,87, que é a Terra 2.0 sob o mesmo símbolo. Isso exigiu a regra de
  episódios (`EPISODE_GAP_DAYS`): sem ela, a nova LUNA herdaria o histórico da antiga e um backtest calcularia um
  "retorno" de +17.739.900% atravessando a lacuna (US$ 0,00005 → US$ 8,87);
- catálogo real (listagem de 2026-10-16): **754 pares em USDT**; **249 sem arquivo recente** (pararam de negociar):
  2 com último mês em 2018, 3 em 2019, 18 em 2020, 20 em 2021, 38 em 2022, 24 em 2023, 46 em 2024, 51 em 2025 e 47 em
  2026; 9 pares têm meses faltando no meio da série (ex.: FTT, 9 meses);
- UST/USDT termina em 2022-05; SRM/USDT em 2022-11; WAVES/USDT em 2024-06; MATIC/USDT em 2024-09 (POL/USDT começa
  em 2024-09: renomeação); FTM/USDT em 2025-01.

**Persistência no GitHub Actions — mecanismos avaliados no repositório (privado):**

| Mecanismo | Existe hoje? | Avaliação |
|---|---|---|
| `actions/cache` | não usado | expira e é despejado (7 dias sem uso, limite de tamanho): só serve de acelerador, nunca de fonte de verdade |
| Artefatos (`actions/upload-artifact`) | não usado | privados num repositório privado, até 90 dias; funcionam com `contents: read`. Adequado para **auditoria** por execução |
| Releases | nenhuma release | duráveis, mas exigem `contents: write` no workflow: decisão de permissão que fica para a Fase 7 (registro prospectivo, o primeiro estado que não pode ser reconstruído) |
| Branch de dados | só existe `main` | versionaria dados diariamente no Git (o roadmap desaconselha) e exige `contents: write` |
| Execuções do workflow diário | 5 execuções; as 3 últimas com sucesso (2026-10-16) | cada uma baixa o histórico inteiro da Binance (~40 s) |

**Decisão (Fase 1).** Para preços e volumes a fonte de verdade é a própria Binance (REST no pipeline, arquivo
oficial com SHA-256 na pesquisa): tudo pode ser rebaixado e conferido, então nenhum cache vira fonte de verdade. O
que **não** se reconstrói (histórico de falhas de coleta, revisões de candles, fingerprint dos dados usados,
snapshot dos sinais) passa a ser guardado a cada execução como artefato privado de 90 dias, mesmo quando o
pipeline falha, num passo que não derruba o job. A persistência durável (Release ou branch de dados, com
`contents: write`) fica para a Fase 7, quando existir o registro imutável de sinais, e será proposta antes de
mudar permissões. Posições manuais não foram tocadas: continuam em `data/positions/` na máquina do usuário e não
existem no runner.

### O que mudou

| Arquivo | Mudança |
|---|---|
| `src/extractors/http.py` | `get_bytes` (mesmo timeout, backoff, Retry-After e mensagens sem cabeçalhos; `missing_ok` devolve None em 404); `get_json` passa a usá-lo, sem mudar comportamento (testes antigos inalterados); trava do espaçamento por host para uso com threads |
| `src/extractors/binance_archive.py` (novo) | adaptador do arquivo oficial: listagem paginada do S3, plano de download (mensais + diários sem mensal), SHA-256 obrigatório, parse (ms e µs, com e sem cabeçalho), só candles fechados, manifesto por ZIP, catálogo de pares, idempotência por ETag; hosts restritos a uma lista |
| `src/transformers/point_in_time.py` (novo) | universo de cada dia só com dados até D (histórico, volume da janela terminada em D, limite por volume em D), episódios separados por lacuna, eventos de entrada/saída **inferidos**, `merge_events` para anúncios oficiais futuros, resumo de sobrevivência, sinalização de possíveis ações tokenizadas |
| `src/transformers/dataset.py` (novo) | fingerprint SHA-256 canônico (independe da ordem), manifesto por moeda, hash combinado, trilha de revisões de candles |
| `src/transformers/data_quality.py` | `audit_candles` ganhou OHLC inconsistente, volume negativo, horário fora de 00:00 UTC e candle não fechado (`as_of` opcional); limpeza inalterada |
| `src/loaders/market_store.py` | `write_ohlcv(..., ingested_at=)` registra revisões em `revisions/`; manifesto dos dados usados por execução em `dataset_manifest/history.parquet` |
| `src/loaders/source_log.py` | histórico append-only (`history.parquet`) além da última de cada fonte; **bug preexistente corrigido**: execução em que todas as fontes falham quebrava a gravação (`NaT` sem fuso) |
| `src/loaders/archive_store.py` (novo) | base `data/archive/` (candles, manifesto, catálogo com histórico, sync_log, saídas point-in-time), separada da base do pipeline |
| `src/archive.py` (novo) | CLI: `catalog`, `sync --symbols/--core/--all`, `universe`, `status`; falha num par vai para o log e devolve código 1 sem tocar nos outros |
| `src/pipeline.py` | grava o manifesto dos dados usados e passa `ingested_at` e `as_of`; o relatório mostra o hash combinado. **Nenhuma regra de sinal, seleção, risco, orçamento ou saída do painel mudou** |
| `src/config.py` | `NON_CRYPTO_BASES` (lista curada: stablecoins, fiat, ouro, embrulhados) e `EPISODE_GAP_DAYS = 7`; só a pesquisa point-in-time usa |
| `.github/workflows/daily.yml` | passo "Guardar o estado de auditoria" (artefato privado de 90 dias, `if: always()`, `continue-on-error`) |
| `README.md`, `docs/LEGACY.md` | fontes novas, garantias, base point-in-time e seus limites; o legado `extract_binance_vision.py` tem substituto |
| testes | `tests/test_point_in_time.py`, `tests/test_archive.py`, `tests/test_dataset.py`, teste novo em `tests/test_pipeline.py` |

### Testes sintéticos exigidos pela fase

| Exigência | Teste |
|---|---|
| truncar os dados depois de D não muda o universo de D | `test_truncating_after_d_does_not_change_the_universe_up_to_d` (5 datas, inclusive a da deslistagem) |
| dados futuros não influenciam o passado | `test_future_prices_and_volumes_do_not_influence_past_eligibility` (preço ×50 e volume ×1000 depois de D) |
| deslistado permanece no histórico até a data de indisponibilidade | `test_delisted_pair_stays_in_history_until_its_last_candle_then_stops_trading`, `test_listing_events_mark_last_candle_as_inferred_delisting` |
| a segunda execução não duplica | `test_second_sync_downloads_nothing_and_does_not_duplicate`, `test_second_write_is_idempotent` |
| falha de coleta não corrompe o que existe | `test_failed_pair_is_logged_and_does_not_touch_existing_data`, `test_failed_write_leaves_the_previous_file_intact` |
| correção de dado gera evento auditável | `test_republished_file_is_reingested_and_the_change_is_audited`, `test_revised_candle_is_kept_in_the_audit_trail` |
| volume medido em D, não hoje | `test_volume_is_measured_up_to_d_not_today` |
| troca de ativo sob o mesmo símbolo | `test_long_gap_starts_a_new_episode_with_fresh_history` (cópia sintética do caso LUNA) |
| checksum | `test_checksum_mismatch_or_missing_fails_closed` |
| hash dos dados por execução | `test_each_run_records_the_fingerprint_of_the_data_it_used` |

### Coleta real

Executada neste ambiente em 2026-10-16 (todos os números abaixo foram medidos, não estimados):

| Etapa | Resultado |
|---|---|
| `sync --core` (32 moedas de `config.UNIVERSE`) | 2.987 ZIPs verificados por SHA-256, 76.767 candles (2017-08-17 a 2026-10-15), 0 falhas, ~10 min |
| `sync --core` de novo (idempotência) | **0 arquivos baixados**, fingerprint idêntico (`7ef60d20…`), 0 revisões, 45 s |
| `sync --all` interrompido de propósito (2 vezes, para trocar a otimização) | base preservada: fingerprint idêntico depois da interrupção; a retomada pulou o que já estava gravado |
| `sync --all` (676 candidatos: 754 pares USDT menos alavancados e `NON_CRYPTO_BASES`) | **676 pares, 0 falhas**; base final de **795.659 candles**, **33.594 ZIPs** no manifesto; ~20 min com 6 pares em paralelo |
| `sync --all` de novo (idempotência em escala) | **0 arquivos**, fingerprint idêntico (`4331555f21d6…f36a03`), 0 revisões |
| `universe` (universo point-in-time, limite de 32 por volume em D) | 676 pares × 3.347 dias em ~10 s |

Qualidade (auditoria da base inteira): 15 pares com lacunas internas (652 dias no total; maiores: FTT 310, CVC 153,
VEN 87); **BTT/USDT tem volume na moeda base negativo em 5 dias de 2019** no próprio arquivo da Binance (o volume
em USDT, que é o usado, é positivo): defeito da fonte, registrado, não corrigido. Nenhum OHLC inconsistente,
horário desalinhado ou candle não fechado.

Eventos inferidos: 684 inícios de episódio, 194 pares sem negociação no fim da série (deslistagem inferida) e 8
quebras de episódio por lacuna: FTT (15/11/2022, colapso da FTX), LUNA (13/05/2022), VEN (23/07/2018, migração
para VET), CVC, KEY, NBT, STRAX e VIDT.

**Viés de sobrevivência, medido** (pares distintos que estiveram entre as 32 elegíveis por volume em algum dia do
ano; quantos deles estão na lista de moedas de HOJE; quantos deixaram de negociar depois):

| Ano | Elegíveis por dia (média) | Distintos no ano | Na lista atual (`config.UNIVERSE`) | Pararam depois |
|---|---|---|---|---|
| 2017 | 2,0 | 2 | 2 | 0 |
| 2018 | 2,4 | 6 | 4 | 1 |
| 2019 | 10,6 | 17 | 10 | 3 |
| 2020 | 28,1 | 50 | 15 | 14 |
| 2021 | 32,0 | 89 | 22 | 26 |
| 2022 | 32,0 | 96 | 24 | 28 |
| 2023 | 32,0 | 110 | 27 | 35 |
| 2024 | 32,0 | 89 | 30 | 14 |
| 2025 | 32,0 | 85 | 28 | 11 |
| 2026 | 32,0 | 92 | 27 | 6 |

Leitura: em 2021, 67 dos 89 pares que um universo "top 32 por volume" teria contemplado não estão na lista atual,
e 26 deixaram de negociar. Os backtests do README, que só usam a lista atual, nunca viram esses casos. Em 2017 a
2019 há poucos elegíveis porque o filtro exige 365 candles próprios e o spot em USDT da Binance começa em 2017.

*Correção feita na Fase 2:* a primeira versão desta tabela aplicava o filtro de 365 dias também a BTC e ETH
(`always_include`), ao contrário da regra ao vivo (`universe.select_universe`, em que as moedas-núcleo nunca saem
por histórico ou volume). Corrigido em `point_in_time.universe_history`, com teste
(`test_core_coins_follow_the_live_rule_and_never_leave_for_history_or_volume`). A tabela acima já é a corrigida:
entrou a linha de 2017 e a média de 2018 caiu de 2,9 para 2,4 só porque os dias em que só BTC e ETH eram elegíveis
passaram a contar; o resto não mudou.

Conferências pontuais coerentes com a história: em 2022-05-12 (colapso) a LUNA estava no universo; em 2021-12-01
o universo incluía SAND, MANA, LRC, OMG, COCOS e CHR (onda "metaverso"); a FTT estava sem negociação em
2022-11-20; a MATIC sem negociação e a POL presente em 2026-10-15.

83 pares foram sinalizados como possíveis ações tokenizadas (AAPLB, AMZNB, ...): **não** foram excluídos.

Falha encontrada e corrigida durante a coleta: o `sync_log` era gravado a cada 25 pares; a interrupção proposital
deixou pares gravados sem linha no log (manifesto com 33.594 arquivos contra 33.313 no log). Os dados estavam
íntegros; agora o log é gravado a cada par, logo depois dos dados.

Os dados ficam em `data/archive/` (fora do Git, no disco deste contêiner): **não persistem** quando este contêiner
for reciclado. Para reconstruir em outra máquina: `uv run python -m src.archive sync --all` (o fingerprint permite
conferir se o resultado é o mesmo).

### Imputação de lacunas

Nada novo é imputado. O preenchimento que já existia (`selection.compute_features` repete o preço por até 5 dias
de lacuna interna, `FILL_LIMIT`) continua igual e sem marcação própria; a regressão sintética impede mudá-lo sem
documentar. O tratamento explícito de candle ausente na simulação (hoje `run_weighted` trata como retorno zero) é
escopo da Fase 2.

### Critérios de aceitação da Fase 1

| Critério | Situação |
|---|---|
| Histórico de elegibilidade de ativos | **ok**: `universe_history` (676 pares reais × 3.347 dias) |
| Disponibilidade histórica de pares | **ok**: catálogo (754 pares) e `days_since_candle` por dia |
| Registro de inclusão e exclusão | **ok, inferido**: `listing_events` (`inferred=True`); `merge_events` para eventos oficiais futuros |
| Deslistagens tratadas quando há evidência | **parcial**: evidência = fim da série no arquivo oficial; não há anúncio oficial integrado |
| Persistência incremental | **ok**: upsert por ETag, retomada após interrupção testada com dados reais |
| Atualização idempotente | **ok**: testes sintéticos e 2 reexecuções reais com 0 downloads e fingerprint idêntico |
| Validação de candles, timestamps, duplicatas, lacunas, desatualização | **ok**: `audit_candles` ampliada; desatualização já existia (`availability`) |
| Metadados de fonte e momento de coleta | **ok**: manifesto (chave, ETag, SHA-256, `fetched_at`), `ingested_at` nas revisões, histórico de fontes |
| Hash dos conjuntos de dados por experimento | **ok** para o pipeline (`dataset_manifest/history.parquet` por execução) e para a base do arquivo (`status`); o registro de experimentos que vai usá-lo é da Fase 3 |
| Testes de truncagem, futuro, deslistagem, duplicação e falha | **ok** (tabela acima); 202 testes passam; `mypy --strict src/ mcp_server.py` sem erros |
| Persistência no GitHub Actions sem cache como única fonte de verdade | **ok para auditoria** (artefato de 90 dias); durável **pendente** (Fase 7, exige decidir `contents: write`) |
| Nenhum dado ausente fabricado | **ok**: nada imputado; lacunas e defeitos da fonte só registrados |
| Viés de sobrevivência | **reduzido e medido, não resolvido** (ver limitações) |
| Pipeline diário e saídas do painel inalterados | **ok**: regressão sintética idêntica; schemas de `daily_signals`/`recommendation` sem mudança; build do frontend ok |

### Pontos de falha da Fase 0 tratados

| Item (Fase 0) | Situação após a Fase 1 |
|---|---|
| 1. Universo filtrado com dado atual | infraestrutura point-in-time pronta; o pipeline e os backtests ainda usam o universo atual (troca na Fase 2/3) |
| 2. Universo = moedas vivas hoje | base com 676 pares, inclusive os que pararam; viés medido |
| 7. Upsert sem trilha, sem hash | **resolvido**: revisões, histórico de fontes, manifesto e fingerprint por execução |
| 8. Sem persistência no Actions | **parcial**: artefato de auditoria de 90 dias; durável na Fase 7 |
| (novo) gravação do registro de fontes quebrava quando todas as fontes falhavam | **corrigido** (bug preexistente, teste de regressão) |

### Limitações e riscos remanescentes

- **Viés de sobrevivência reduzido, não eliminado.** O universo histórico agora inclui os pares que deixaram de
  negociar na Binance, mas só os da Binance spot em USDT. Moedas que nunca foram listadas na Binance, ou que só
  negociavam contra BTC/BUSD, não entram.
- **Deslistagem inferida.** O arquivo não traz o anúncio oficial: o evento é "sem candles depois de X". Uma
  suspensão longa e uma deslistagem parecem iguais até a série voltar. `merge_events` aceita eventos oficiais
  verificados no futuro; nenhum foi inventado.
- **Saída de posição numa deslistagem.** O último preço do arquivo não é necessariamente um preço executável
  (liquidez some antes); como simular essa saída é decisão da Fase 2.
- **Renomeações** (MATIC → POL, FTM → S) aparecem como saída de um par e entrada de outro, sem continuidade de preço.
- **Exclusões curadas com o conhecimento de hoje** (`NON_CRYPTO_BASES`): há algum viés retrospectivo nessa lista;
  ações tokenizadas suspeitas só são sinalizadas.
- **Sem market cap histórico e sem Fear & Greed neste ambiente.** O universo histórico usa volume negociado na
  Binance, que mede liquidez, não tamanho.
- **O pipeline diário ainda usa o universo atual** (`config.UNIVERSE` + `select_universe`) e as tabelas do README
  continuam com esse viés. A troca para o universo point-in-time nos backtests é da Fase 2/3, com a mudança de
  premissas documentada antes de publicar números novos.
- **Arquivos diários atrasam** 1 a 3 dias: o arquivo serve à pesquisa, não ao sinal de hoje.

### Próxima fase

Fase 2: motor de backtest único, com execução no candle seguinte, custos explícitos, candle ausente marcado e
saída forçada em deslistagem, rodando sobre o universo point-in-time.

---

## Fase 2 — motor de backtest único

### Contrato (`src/transformers/backtest_engine.py`, versão `next-open-v1`)

| Elemento | Definição |
|---|---|
| Sinal | `targets`: peso-alvo por ativo em cada dia de decisão D (fração do patrimônio, ≥ 0, soma ≤ 1), calculado com dados até o fechamento de D. Ativo ausente da linha = alvo 0 |
| Universo | `eligible` (mesmo formato), do universo point-in-time: alvo > 0 em ativo não elegível vira 0 e fica registrado (`FORA_DO_UNIVERSO`) |
| Ordem | decisão de D executada na abertura do primeiro candle depois de D; pendente por até `MAX_ORDER_DELAY_DAYS` (3) sem preço válido, depois `EXPIRADA`; decisão nova `SUBSTITUI` a pendente |
| Custos | `costs.CostModel`: compra a abertura × (1 + meio-spread + slippage), venda × (1 − meio-spread − slippage), taxa sobre o executado; meio-spread pela faixa de volume conhecida até a véspera; o mesmo modelo que a seleção usa para o aporte |
| Caixa e posições | quantidades e caixa explícitos; vendas antes das compras; compras limitadas ao caixa (`PARCIAL`, `fill_ratio`); sem alavancagem, sem venda a descoberto |
| Marcação e deslistagem | fechamento do dia, ou o último conhecido; sem candle há mais de `EPISODE_GAP_DAYS` (7) = baixa com `DELIST_RECOVERY` (0) |
| Saídas | patrimônio, caixa, retorno, exposição, quantidades e valores diários; livro de operações (preço de referência e executado, taxa, spread, slippage, caixa depois); livro de ordens (decisão, execução, atraso, status) |
| Métricas | `summarize`: retorno total e anual, pior queda, Sharpe (365 dias), exposição média, giro por ano, entradas, custos em % do capital (descritivas; incerteza é da Fase 3) |
| Reconciliação | `reconcile`: caixa = capital + fluxos do livro; patrimônio = caixa + posições; produto dos retornos = patrimônio final; quantidade final = compras − vendas − baixas; exposição ≤ 100%; caixa e quantidades ≥ 0. O pipeline não publica se falhar (`ReconciliationError`) |

### Decisões (com o motivo)

| Decisão | Motivo |
|---|---|
| Execução na abertura de D+1, não no fechamento de D | o fechamento de D é o preço que gerou o sinal; a abertura seguinte é o primeiro preço observável depois dele. É uma aproximação (não há livro de ofertas), documentada como tal |
| Posição inicial de cada período = última decisão anterior ao período | é conhecida no início do período (sem olhar para frente); o legado começava em caixa e esperava até 6 dias pelo primeiro rebalanceamento dentro do período |
| Peso-alvo inclui os custos | alvo de 100% gasta todo o patrimônio com taxa e spread; nunca cria caixa negativo |
| Carteira de peso igual (`performance.parquet`) rebalanceada todo dia, sem banda | é a definição da estratégia que o legado publicava; agora cada ajuste paga custo. Uma banda absoluta de 5 pontos com ~32 moedas (~3% cada) mudaria a estratégia para "deixar as vencedoras crescerem" (ver sensibilidade) |
| Seleção e referências (`selection_backtest.parquet`) a cada 7 dias com banda de 5 pontos | premissa que já existia, agora sem alavancagem implícita; mesma para a seleção e para cada referência |
| `DELIST_RECOVERY = 0` | o arquivo não diz se houve saída possível antes do fim da série; perda total é o limite conservador; a sensibilidade com 100% é publicada abaixo |
| Stop como sinal de fechamento, executado na abertura seguinte | é como uma regra diária pode ser seguida; o gap entra no resultado; não há stop intradiário |
| Universo point-in-time no pipeline | `universe_history` sobre todas as moedas da base (não só as que passam no filtro de hoje). BTC e ETH seguem a regra ao vivo (nunca saem por histórico ou volume) |
| Motores antigos mantidos como LEGADO | reproduzem os resultados anteriores (`tests/test_legacy_engines.py`) e o laboratório ainda depende deles; nada novo usa |

### Diferenças entre os motores (medidas, nenhuma escondida)

Testes em `tests/test_engine_reconciliation.py`, todos sintéticos:

- sem custos e com abertura(D+1) = fechamento(D), o motor único reproduz `run_portfolio` (dia a dia, 1e-12) e `run_weighted` sem banda (1e-12);
- `run_portfolio` cobrava taxa só quando a posição 0/1 mudava, mas rebalanceava para peso igual todo dia de graça: no motor único esse rebalanceamento paga custo;
- `run_portfolio` perdia o movimento de preço através de um candle ausente (`pct_change` sem preenchimento: +20% somem junto com o candle); o motor único marca o preço quando ele volta;
- `run_weighted` com banda **passava de 100% de exposição**: quando uma moeda sai da banda e volta ao alvo, as outras ficam com o peso que derivou para cima. No mercado sintético a exposição chegou a 116,7%, em centenas de dias. O motor único limita as compras ao caixa;
- `run_weighted` mantinha um ativo que parou de negociar pelo último preço (retorno zero) e o "vendia" a esse preço no rebalanceamento seguinte. Caso real: **TON/USDT parou de negociar no spot da Binance em 2026-06-30** (último candle com volume de US$ 0,47 mi contra US$ 3,9–7,9 mi nos cinco dias anteriores) e continua em `config.UNIVERSE`; o pipeline atual a marca como INDISPONÍVEL;
- o motor único reproduz o legado exatamente quando as premissas coincidem (ex.: BTC comprado e segurado no treino: −51,26% nos dois, no mercado sintético).

**Tempo de execução: abertura de D+1 contra fechamento de D, medido em dados reais** (base do arquivo oficial,
794.968 pares de candles consecutivos de 676 pares): mediana de 0,033%, percentil 99 de 0,61%, máximo de 42,7%
(SCR/USDT, 2024-10-22). Nas 32 moedas de `UNIVERSE`: mediana de 0,008%, percentil 99 de 0,29%, máximo de 6,4%; 40,5%
dos casos são exatamente iguais. A Binance negocia sem parar: a troca de premissa quase não pesa no caso típico e
retira o otimismo dos casos extremos. O motor antigo não tinha "look-ahead" no sentido de usar um preço futuro: ele
executava ao mesmo preço que gerou o sinal.

### Atribuição em dados reais (exploratória)

`uv run python research/engine_reconciliation.py --archive`: as 32 moedas de `config.UNIVERSE` na base do arquivo
oficial (dados até 2026-10-15), **sem Fear & Greed** (bloqueado neste ambiente, então o pânico fica de fora).
Retorno total (%) por passo; cada coluna acrescenta uma premissa à anterior (a ordem importa, os passos não são
comutativos). Conferência do legado: carteira BTC+ETH no treino dá +293,7% (tendência) e +67,4% (comprar e
segurar), **iguais às tabelas do README**, calculadas com a REST da Binance; no teste dá +211,9% e +237,6% contra
+209,5% e +235,0% do README, que parava um dia antes (2026-10-14).

Colunas: **L** legado; **1** motor único com as premissas do legado (começa em caixa, universo = ter SMA 200; na
carteira só taxa e rebalanceamento diário); **2** + posição inicial herdada; **3** + spread e slippage (carteira);
**4** + universo point-in-time = **publicado**; **B** sensibilidade com banda de 5 pontos (carteira); **D**
sensibilidade com deslistagem recuperando 100% do último preço.

| Carteira | Período | L | 1 | 2 | 3 | 4 | B | D |
|---|---|---|---|---|---|---|---|---|
| BTC+ETH tendência | treino | 293,7 | 285,3 | 285,3 | 277,5 | **277,5** | 296,5 | 277,5 |
| BTC+ETH tendência | teste | 211,9 | 207,7 | 207,7 | 202,4 | **202,4** | 202,6 | 202,4 |
| BTC+ETH comprar e segurar | treino | 67,4 | 63,3 | 63,3 | 61,8 | **61,8** | 69,4 | 61,8 |
| BTC+ETH comprar e segurar | teste | 237,6 | 233,4 | 234,8 | 233,1 | **233,1** | 236,0 | 233,1 |
| todas, tendência | treino | 255,8 | 232,5 | 232,5 | 222,8 | **311,6** | 405,1 | 311,6 |
| todas, tendência | teste | 55,9 | 45,8 | 45,8 | 42,0 | **32,1** | 48,9 | 32,1 |
| todas, comprar e segurar | treino | 74,3 | 60,5 | 60,5 | 57,2 | **129,9** | 203,0 | 129,9 |
| todas, comprar e segurar | teste | 131,3 | 112,3 | 114,5 | 111,8 | **97,5** | 138,4 | 103,9 |

*Nota da Fase 3: as colunas 4 e D desta tabela foram recalculadas depois da correção da elegibilidade das
referências (ver Fase 3, achado A3); a tabela abaixo é a da Fase 2, preservada.*

| Seleção (semanal) | Período | L | 1 | 2 | 4 | D |
|---|---|---|---|---|---|---|
| seleção | treino | 48,4 | 48,5 | 48,5 | **49,0** | 49,0 |
| seleção | validação | 72,6 | 72,6 | 130,1 | **130,1** | 130,1 |
| seleção | teste | 76,8 | 76,2 | 76,2 | **76,2** | 76,2 |
| seleção, peso igual | validação | 215,7 | 218,5 | 345,4 | **345,4** | 345,4 |
| momento simples | treino | 32,1 | 40,5 | 60,8 | **111,0** | 111,0 |
| momento simples | validação | 25,3 | 19,4 | 50,0 | **−6,0** | −6,0 |
| momento simples | teste | 483,3 | 299,7 | 323,7 | **106,3** | 196,6 |
| regra SMA 200 | treino | −7,1 | −0,8 | −0,8 | **15,7** | 15,7 |
| regra SMA 200 | teste | 87,1 | 83,5 | 83,5 | **57,3** | 57,3 |
| comprar e segurar todas | teste | 176,1 | 172,0 | 185,7 | **124,9** | 130,5 |
| só BTC | teste | 387,8 | 387,8 | 396,4 | **396,4** | 396,4 |

O que a tabela mostra (sem afirmar lucratividade de nada):

- em BTC+ETH, as premissas novas tiram de 6 a 16 pontos do resultado antigo (execução, custos de rebalanceamento,
  spread e slippage); o universo point-in-time não muda nada aqui (as duas sempre estão no universo);
- no "momento simples", o resultado antigo do teste (+483%) dependia de alavancagem implícita e de manter a TON pelo
  último preço: com as premissas do legado no motor único já cai para +300%, e com o universo point-in-time, para
  +106% (+197% se a TON tivesse sido vendida pelo último preço);
- a **posição inicial** pesa muito em janelas curtas: a validação da seleção vai de +72,6% para +130,1% só por
  começar investida em 2021-01-01 em vez de esperar o primeiro rebalanceamento da janela. Resultado tão sensível
  à convenção de início não é evidência robusta;
- com todas as moedas, o universo point-in-time muda o resultado nos dois sentidos (treino para cima, teste para
  baixo): no treino entram moedas que eram líquidas na época e que o filtro de hoje tira; no teste, a baixa da TON e
  as moedas que só ficam elegíveis com 365 dias de histórico;
- uma banda de 5 pontos na carteira de peso igual muda muito o resultado (coluna B): a escolha de rebalancear todo dia
  não é neutra e está documentada como premissa.

### Pipeline com dados reais (exploratório)

`pipeline.analyze` completo rodou sobre as 32 moedas da base do arquivo (cópia temporária, sem Fear & Greed e sem
CoinGecko) em **29,9 s**, com todos os livros reconciliados. Resultado publicado no motor único, carteira BTC+ETH:
tendência +277,5% no treino (pior queda −59,8%) e +202,4% no teste (−29,6%); comprar e segurar +61,8% (−83,3%) e
+233,1% (−60,0%). Operações da tendência: 63 (61 fechadas), 26% com lucro, retorno médio **líquido de custos** de
+24,6% (o legado mostrava +25,0% bruto, 61 operações). Frase de evidência da seleção: "não superou só Bitcoin em
retorno por risco, então a vantagem não está demonstrada" (comparação de Sharpe pontuais, sem incerteza: Fase 3).
O pânico aparece com 0% porque não há Fear & Greed neste ambiente, não porque a regra mudou.

### O que mudou

| Arquivo | Mudança |
|---|---|
| `src/transformers/backtest_engine.py` (novo) | o motor único: contrato, execução, caixa, ordens, custos, deslistagem, `reconcile`, `summarize`, `total_costs`, `panel_from_candles` |
| `src/transformers/costs.py` (novo) | modelo de custos único (taxa, meio-spread por faixa de volume, slippage); `selection.cost_per_side` passou a usá-lo (mesmo resultado: regressão idêntica) |
| `src/transformers/portfolio_backtest.py` (novo) | tendência, comprar e segurar e pânico como pesos-alvo no motor único; operações da tendência a partir do livro do motor (entrada e saída na abertura seguinte, retorno líquido) |
| `src/transformers/selection_backtest.py` | `evaluate_selection` no motor único (mesmas premissas para a seleção e as referências); o antigo virou `evaluate_selection_legacy`; `run_weighted` marcado como legado |
| `src/transformers/trade_simulator.py` | só docstrings: `backtest`, `run_portfolio`, `evaluate_portfolio`, `performance_summary` marcados como legado; `simulate` e `trend_positions` seguem vigentes |
| `src/transformers/point_in_time.py` | correção: BTC/ETH seguem a regra ao vivo (nunca saem por histórico, volume ou limite) |
| `src/config.py` | `EXECUTION_MODEL_VERSION`, `MAX_ORDER_DELAY_DAYS`, `DELIST_RECOVERY` |
| `src/pipeline.py` | `backtest_inputs` (histórico, indicadores, painel de preços e universo point-in-time de todas as moedas da base); carteira, operações e seleção no motor único |
| `frontend/src/types/signals.ts`, `icons.tsx`, `data/analytics.ts` | motivo de saída `DESLISTAGEM` no contrato das operações (só ocorre no backtest), com ícone e textos |
| `frontend/src/components/Sections.tsx`, `Recommendation.tsx` | textos de metodologia corrigidos: execução na abertura seguinte, taxa + spread + slippage, teste já consultado = exploratório |
| `research/engine_reconciliation.py` (novo) | atribuição legado → motor único, premissa por premissa, e sensibilidades |
| `research/lab.py`, `strategy_lab.py`, `strategy_comparison.py`, `selection_study.py` | aviso de que ainda usam o motor legado e não são comparáveis com o pipeline |
| `README.md`, `docs/LEGACY.md` | seção "Motor de backtest", tabelas antigas rotuladas como do motor antigo, estrutura |
| testes | `test_backtest_engine.py` (22), `test_engine_reconciliation.py` (5), `test_portfolio_backtest.py` (3), `test_legacy_engines.py` (3, parametrizado), `test_point_in_time.py` (+1), `test_selection.py` (contrato novo) |
| `tests/golden/` | `performance`, `selection_backtest` e `backtest` regenerados com o motor único; os anteriores preservados em `tests/golden/legacy_v1/` e reproduzidos pelas funções legadas |

### Critérios de aceitação da Fase 2

| # | Critério | Situação |
|---|---|---|
| 1 | Contrato único para sinais, posições, caixa, ordens, custos e métricas | **ok**: `backtest_engine.py` (tabela acima) |
| 2 | Eliminar a divergência sem ocultar diferenças | **ok**: um só motor publica; diferenças medidas e testadas; legados reproduzem o passado e estão marcados |
| 3 | Executar só depois que o sinal existe | **ok**: execução na abertura seguinte (`test_signal_at_close_d_executes_at_open_d_plus_1_not_at_close_d`, `test_prices_after_day_k_do_not_change_results_up_to_k`, `test_trend_trade_enters_and_exits_at_the_next_open_with_costs`) |
| 4 | Universo elegível em cada data, sem informação futura | **ok** no pipeline (universo point-in-time das moedas da base); **limitação**: as candidatas do pipeline ainda são a lista de hoje (a base completa de 676 pares está só na pesquisa) |
| 5 | Taxas, spread e slippage consistentes e configuráveis | **ok**: `costs.CostModel` único, custo zero quando não há operação, fórmula exata testada |
| 6 | Candle ausente, deslistagem, episódios, caixa insuficiente, ordem sem preço | **ok**, cada um com teste |
| 7 | Reconciliação contábil | **ok**: `reconcile` em toda execução do pipeline; teste de livro adulterado |
| 8 | Testes sintéticos de tempo, custos, deslistagem, lacunas, caixa, posições, look-ahead | **ok**: 34 testes novos do motor e da reconciliação |
| 9 | Estratégias e referências com as mesmas premissas; resultados antigos não comparáveis | **ok**: cada tabela publicada usa uma só configuração; README e painel rotulam os números antigos; laboratório marcado como legado |
| 10 | Documentação | **ok**: README, LEGACY, este arquivo |

Verificações executadas: `uv run pytest -q` = **236 passed**; `uv run mypy --strict src/ mcp_server.py` sem erros
(42 arquivos); `npm run build` do frontend ok (tsc estrito + vite).

### Limitações e riscos remanescentes

- **A abertura seguinte é uma aproximação**: não há livro de ofertas, profundidade nem impacto de mercado. Ordens
  pequenas (hipótese do projeto); spread e slippage continuam hipóteses por faixa de volume, não medidas.
- **Deslistagem**: 0% de recuperação é conservador e 100% é otimista; a verdade depende de anúncios (a Binance avisa
  com antecedência) que o sistema não lê. A sensibilidade está publicada; não há escolha "correta" com os dados atuais.
- **Candidatas do pipeline**: o universo point-in-time do pipeline é aplicado sobre as moedas de `config.UNIVERSE`
  (viés de sobrevivência da lista). O universo histórico completo (676 pares) existe em `data/archive`, mas os
  backtests publicados ainda não o usam (escopo da Fase 3, com o registro de experimentos).
- **Convenções de período**: a posição inicial muda bastante o resultado de janelas curtas (validação da seleção).
  Isso reforça que resultados por período, sem incerteza, não são evidência (Fase 3).
- **Laboratório e estudo da seleção** (`research/`) ainda usam o motor legado; seus números antigos não são
  comparáveis com o pipeline.
- **Métricas sem incerteza**: Sharpe e retornos são estimativas pontuais; a frase de evidência compara Sharpe
  pontuais. Intervalos, walk-forward e correção para comparações múltiplas são da Fase 3.
- **Fear & Greed indisponível neste ambiente**: a referência do pânico não pôde ser conferida com dados reais.
- **Custo do pipeline**: a análise ficou mais pesada (histórico e indicadores calculados também para todas as moedas
  da base, ~30 execuções do motor): 29,9 s com dados reais, dentro do limite de 20 min do workflow.

### Próxima fase

Fase 3: validação estatística (métricas com incerteza, walk-forward, bootstrap em blocos, registro de experimentos,
Holm), migrando o laboratório para o motor único e usando o universo point-in-time completo da base do arquivo.

---

## Fase 3 — validação estatística

Executada em 2026-10-16, no mesmo contêiner das Fases 1 e 2: a base `data/archive` (676 pares) estava disponível.
Fear & Greed e as APIs REST continuam bloqueados. Antes de qualquer mudança: branch `feature/quantitative-research`,
62 arquivos alterados das Fases 0–2 (sem commit), cópia de segurança e diff em `scratchpad/backup_pre_fase3.tgz` e
`pre_fase3.diff`. Nenhum reset, checkout, clean, commit ou push.

### Etapa 1 — auditoria metodológica (antes de implementar)

| # | Achado | Gravidade | Impacto | Evidência | Tratamento |
|---|---|---|---|---|---|
| A1 | A frase de evidência (painel, Telegram) chamava 2023 em diante de "teste fora da amostra", período recalculado todo dia e consultado no desenvolvimento | alta | apresenta evidência exploratória como confirmatória | `selection_backtest.evidence`, `recommendation.py` | **corrigido**: frase nova com intervalo e o rótulo "já consultado: não é um teste intocado" (`evidence_with_uncertainty`) |
| A2 | Comparações por Sharpe pontual, sem incerteza nem correção para múltiplas estratégias ("superou" = Sharpe maior; `beats_random_pct` sem hipótese nula) | alta | sorte vira "vantagem" | `evidence`, `strategy_lab.py` | **corrigido** na validação (bootstrap em blocos, Holm, ajuste pelo máximo); laboratório antigo mantido como registro |
| A3 | **Defeito (introduzido na Fase 2):** com o universo point-in-time, as referências da seleção escolhiam moedas fora do universo do dia; o motor zerava o alvo e a referência ficava parcialmente em caixa sem que isso fosse a regra | alta (tabela da seleção) | referências subinvestidas, comparação enviesada a favor da seleção | dados reais (32 moedas): MOMENTO_SIMPLES com 19,6% do alvo médio em moedas inelegíveis (196 de 460 rebalanceamentos), COMPRAR_E_SEGURAR 11,6% (290), TENDENCIA_SMA200 3,0% (118); a seleção, 1 dia | **corrigido** (`selection_targets`/`baseline_targets` recebem `eligible`, como `select_universe` ao vivo); teste `test_references_and_selection_only_use_coins_eligible_on_the_day`; regressão sintética regenerada (só referências da seleção mudaram) |
| A4 | Parâmetros do laboratório escolhidos numa validação fixa (2021–2022) e medidos num teste já explorado; 23 combinações sem correção; motor legado | média | escolha otimista, sem contagem de tentativas | `strategy_lab.py` | **substituído** por walk-forward anual no motor único (`walk_forward.py`), com todas as tentativas registradas |
| A5 | Períodos diferentes entre tabelas: `performance` usa treino 2018–2022 (contém a validação 2021–2022 da seleção e do laboratório) | baixa | "treino" de uma tabela é "validação" de outra | `pipeline.PERIODS` x `SELECTION_PERIODS` | documentado; formato do painel mantido |
| A6 | Anualização e Sharpe calculados em qualquer tamanho de amostra | média | Sharpe de poucos meses parece evidência | `summarize`, `summarize_returns` | `metrics.py`: anualizado só com 365+ dias, Sharpe/Sortino só com 180+; as tabelas publicadas continuam descritivas |
| A7 | Unidade das métricas: o motor único usa retornos diários do patrimônio (correto); o laboratório antigo mistura métricas por operação (acerto, fator de lucro) | baixa | por operação não serve para inferência | `lab.py` | validação usa só a série diária |
| A8 | Posição inicial muda muito janelas curtas (Fase 2) | média | resultado depende da convenção de início | Fase 2 (+72,6% → +130,1%) | cenário `INICIO_EM_CAIXA` em toda estratégia |
| A9 | **Deslistagem inferida inclui renomeações e trocas de token.** Baixas reais no universo point-in-time 2020–2026: ERD (→EGLD), NPXS (→PUNDIX), RNDR (→RENDER), MATIC (→POL), FTM (→S), EOS, COCOS, BNX, HNT, ALPACA, HIFI, LUNA (1º episódio), FTT, TON | média/alta (multi-moeda) | `DELIST_RECOVERY = 0` trata troca 1:1 como perda total: penaliza estratégias e referências multi-moeda | `trades` com `side = BAIXA` | **não corrigido** (sem fonte oficial de mapeamentos integrada; não se inventa conversão). Cenário `DESLISTAGEM_100` em toda estratégia. Os pares citados como renomeação são conhecimento público, **não verificados** pelo sistema |
| A10 | `compute_features` decide preencher uma lacuna olhando se há candle depois (`bfill`) | baixa | só altera indicadores dos próprios dias sem candle, que nunca são elegíveis (`has_candle` falso → EVITAR; fora das referências) | leitura do código; teste de truncagem passa | documentado, não alterado (mudaria a regressão sem efeito nas decisões) |
| A11 | O STOP de −20% da regra do painel nunca disparou em BTC/ETH de 2017 a 2026 (fechamento) | informativo | "tendência" e "tendência sem STOP" são a mesma série nesta amostra | `trend_signal` com e sem STOP: 0 dias diferentes (com −15%: 4 dias) | registrado; as duas seguem na família (pré-registradas) |
| A12 | Sem Fear & Greed, o pânico aparecia com 0% investido (Fase 2), indistinguível de "nunca disparou" | média | ausência lida como sinal | Fase 2 | validação marca INVALIDA (cobertura < 95%), p = 1 na família |
| A13 | Previsão (`forecast.py`) escolhe parâmetros na validação e diz ler o teste "uma única vez", mas o teste é recalculado todo dia | média | mesmo problema de A1, na previsão | docstring de `forecast.py` | documentado; fora do escopo de estratégias desta fase |
| A14 | Benchmarks e estratégias com as mesmas premissas dentro de cada tabela publicada | — | ok | Fase 2 | mantido; a validação recusa comparar com premissas diferentes |
| A15 | Candidatas do pipeline = lista de hoje (`config.UNIVERSE`) | alta (para conclusões) | viés de sobrevivência | Fase 1 | validação usa os 271 pares do arquivo que estiveram no universo point-in-time; pipeline inalterado |

Look-ahead: nenhum uso de preço futuro encontrado nos sinais (médias, retornos, canais com `shift(1)`, universo
point-in-time); agora há teste de truncagem para todos os sinais do catálogo, a seleção e as referências (A10 à
parte).

### Etapa 2 — protocolo temporal (`walk_forward.py`, versão `wf-v1`)

| Item | Regra | Por quê |
|---|---|---|
| Dobras | teste de 12 meses, de 2020-01-01 até o último dia da base (7 dobras: 2020…2026, a última até 2026-10-15) | um ano tem ~365 observações diárias e passa pelas estações do ciclo; não foi escolhido por resultado |
| Treino | ancorado no primeiro candle (2017-08-17), cresce a cada dobra; mínimo de 730 dias | inclui o aquecimento: SMA 200 (200 dias) e universo point-in-time (365 candles próprios) |
| Validação | os 730 dias antes de cada escolha | mesmo tamanho da validação 2021–2022 do laboratório antigo |
| Embargo | 0 dias | as métricas são diárias e marcadas a mercado; o treino nunca contém o retorno do 1º dia do teste; a ordem decidida no último dia do treino só executa no teste. Com rótulos de horizonte h, usar h − 1 (parâmetro existe) |
| Parâmetro no teste | a decisão de D usa o candidato escolhido na dobra mais recente com escolha <= D; antes da primeira escolha, caixa | nenhum parâmetro é usado antes de ser conhecido |
| Simulação | uma corrida contínua no motor único sobre todas as dobras de teste (sem zerar a carteira na fronteira) | evita o artefato de início em caixa; o início em caixa vira cenário |
| Status dos dados | `EXPLORADO_NO_DESENVOLVIMENTO` para todas as dobras | as regras foram desenhadas olhando 2018–2026; o walk-forward só protege a escolha de parâmetros da grade |
| Prospectivo | registrado em `registry.parquet` com status `AGUARDANDO_DADOS`: TENDENCIA e SELECAO, mesmas regras, configuração e testes, de 2026-10-16 a 2027-10-15 (mínimo de 365 dias novos) | único dado realmente inédito; avaliação na Fase 7 |

Não há período histórico intocado para reservar: tudo até 2026-10-15 já foi consultado.

### Etapa 3 — métricas e incerteza

Convenções (`metrics.py`): retorno simples diário do patrimônio, 365 dias por ano; taxa livre de risco 0 (o caixa do
motor não rende: Sharpe = excesso sobre ficar em caixa); dias em caixa entram com retorno 0; volatilidade com
ddof = 1; Sortino com desvio de baixa sobre todos os dias (alvo 0); série toda em caixa tem Sharpe 0; retorno
anualizado e Calmar só com 365+ dias, Sharpe/Sortino/volatilidade só com 180+ dias (abaixo disso: NaN, não
estimativa); pior queda e sua duração sobre o patrimônio; exposição média e tempo investido; giro, custos e
entradas do livro do motor. Retorno ausente é recusado (nunca vira zero).

Incerteza (`bootstrap.py`): bootstrap **estacionário** (Politis e Romano, 1994), blocos geométricos circulares,
comprimento médio automático por Politis e White (2004) com a correção de Patton, Politis e White (2009),
calculado sobre cada série, seus desvios absolutos (agrupamento de volatilidade) e as diferenças estratégia −
referência; usa-se o maior (conservador): **94,9 dias** nos dados reais. Reamostragem **conjunta** (os mesmos dias
para todas as séries), 2.000 reamostras, semente 20261016, intervalo percentil de 90%, p-valor unilateral pela
distribuição centrada. Sensibilidade a blocos fixos de 5, 20 e 60 dias publicada. Bootstrap IID não é usado como
evidência (o teste `test_block_bootstrap_ci_is_wider_than_iid_under_autocorrelation` mostra a diferença).

O que se separa no relatório: incerteza estatística (intervalos), variação entre janelas (dobras), sensibilidade às
premissas (cenários), sensibilidade a parâmetros (variações) e risco de overfitting por testar muitas estratégias
(Holm e ajuste pelo máximo).

### Etapa 4 — família e comparações múltiplas

- **Hipótese** de cada estratégia k: H0_k: Sharpe(k) − Sharpe(referência_k) <= 0 contra H1: > 0, sobre a série
  diária fora da amostra 2020-01-01 a 2026-10-15, no motor único `next-open-v1`.
- **Família** (`fase3-wf-v1`, 16 hipóteses, fixada antes de rodar): em BTC+ETH, as 7 regras fixas que o projeto já
  testou (TENDENCIA = regra do painel, TENDENCIA_SEM_FILTRO, TENDENCIA_BTC_SEM_STOP, CRUZAMENTO_50_200, MOMENTO_90D,
  QUEDA_NA_ALTA, PANICO) e as 4 grades do laboratório (DONCHIAN, BOLLINGER, RSI_SOBREVENDIDO, ROMPIMENTO_VOLUME, 23
  combinações escolhidas por walk-forward); no universo point-in-time, SELECAO, SELECAO_PESO_IGUAL, MOMENTO_SIMPLES,
  TENDENCIA_SMA200_SEMANAL e TENDENCIA_TODAS. DCA ficou de fora (é uma regra de aporte, não de sinal: não há hipótese
  de timing comparável).
- **Nível**: α = 5% para o erro familiar, **Holm** (vale sob qualquer dependência). Complemento: p ajustado pelo
  máximo da estatística centrada no bootstrap conjunto (passo único, no espírito do Reality Check de White), que usa a
  correlação entre as estratégias e responde "a melhor supera a sua referência?".
- **Testes ausentes ou inválidos** ficam na família com p = 1 (o tamanho m não muda depois de ver os dados).
- **Limites**: Holm é conservador com estratégias correlacionadas; o ajuste pelo máximo é de passo único, não
  studentizado (estatísticas de variância maior pesam mais); nenhum dos dois corrige o fato de as REGRAS terem sido
  desenhadas olhando o mesmo histórico, nem as variações já estudadas antes em `selection_study.py`.

### Etapa 5 — robustez

Cenários refeitos para a estratégia **e** a referência (mesma premissa nas duas): `CUSTO_BAIXO` (taxa 0,075%,
spread e slippage pela metade: otimista, não conta como estresse), `CUSTO_ALTO` (spread ×2, slippage 0,1%),
`ATRASO_1D` (decisão de D executada na abertura de D+2), `INICIO_EM_CAIXA` (cada dobra simulada sozinha, começando
em caixa), `DESLISTAGEM_100` (baixa recupera 100% do último preço), `DADOS_PARCIAIS` (2% dos candles removidos ao
acaso, semente 7: afeta execução e marcação; os sinais continuam calculados com os dados completos). Variações
moderadas de parâmetro, declaradas em `strategy_catalog.py` antes dos resultados (SMA 150/250, STOP −15/−25% ou
nenhum, cruzamentos 40/60/150/250, momento 60/120 dias, z ±0,25, score ±10 pontos, mínimo de condições 2/4, top 2/5,
rebalanceamento a cada 5/10 dias); para as grades, todos os candidatos. Regimes do BTC (FAVORAVEL/NEUTRO/DEFENSIVO
conhecido no fechamento anterior): descritivo.

### Etapa 6 — referências e critérios

Referência primária (escolhida por argumento, antes dos resultados): **comprar e segurar as mesmas moedas** com peso
igual, mesmo universo, execução, custos, banda e posição inicial: isola o valor do timing ou da seleção. BTC+ETH:
50/50 rebalanceado todo dia (banda 0, a mesma das estratégias diárias). Universo point-in-time: peso igual entre as
elegíveis, semanal com banda de 5 pontos (estratégias semanais) ou diário (tendência diária). Descritivas: só BTC; o
caixa é a referência implícita do Sharpe (rf = 0).

Critérios (`evidence.py`, todos exigidos para `ROBUSTA_NO_PROTOCOLO`): >= 730 dias fora da amostra e >= 10 entradas
(condição de elegibilidade, não de significância); p Holm < 5%; limite inferior do IC da ΔSharpe > 0; ΔSharpe > 0
em >= 2/3 das dobras; ΔSharpe > 0 em todos os cenários de estresse; ΔSharpe > 0 em >= 2/3 das variações (não
avaliado = não atendido); retorno anualizado > 0 e pior queda não mais funda que a da referência. Categorias:
INVALIDA; EVIDENCIA_INSUFICIENTE (amostra, ou ΔSharpe > 0 com IC incluindo zero = compatível com sorte); NEGATIVA
(ΔSharpe <= 0; "significativamente inferior" se o IC inteiro < 0); PROMISSORA_NAO_CONFIRMADA (IC > 0, mas algum
critério falhou); ROBUSTA_NO_PROTOCOLO (todos; ainda sobre histórico explorado).

### Etapa 7 — integração

- Pipeline: a frase `evidence` usa `evidence_with_uncertainty` (seleção x comprar e segurar as mesmas moedas, 2023
  em diante, ΔSharpe com IC de 90%, 1.000 reamostras, semente fixa, rótulo de período explorado). Schema de
  `recommendation.parquet` e de `daily_signals.parquet` inalterado (só o texto); nenhum sinal, aporte, risco ou
  orçamento mudou. Regressão sintética: só `recommendation.evidence` e as referências de `selection_backtest`
  mudaram; `daily_signals`, `performance`, `backtest`, `forecast` e `history` idênticos.
- Exploratório (README antigo, laboratório), validação histórica (`data/research/validation/`) e prospectivo
  (registro `AGUARDANDO_DADOS`) separados; o registro guarda a versão do motor e `assert_comparable` recusa misturar
  motores, protocolos, dados, períodos ou custos numa comparação.
- Frontend: nenhum arquivo alterado nesta fase (o painel já mostra `evidence` como texto).

### Experimentos executados (dados reais)

| Execução | Resultado |
|---|---|
| Auditoria A3 (32 moedas de `UNIVERSE`, base do arquivo) | números na tabela acima |
| `research/validation_study.py --n-boot 200 --no-save` (depuração) | completou em 219 s; serviu para achar A9, A11 e a convenção de Sharpe 0 em caixa (antes, dobras inteiras em caixa davam Sharpe NaN e contavam como falha de estabilidade). **Não gravado** |
| `research/validation_study.py` (2.000 reamostras), execução `20261016T195618Z-e9d2b86c` | 216 s; 118 linhas no registro; tabelas em `data/research/validation/` |
| Segunda execução idêntica, `20261016T200006Z-e9d2b86c` (reprodutibilidade) | 211 s; os mesmos 118 `experiment_id`, **118 de 118 com `reproduces = True`**; as duas execuções preservadas no registro |
| Frase de evidência nova do pipeline, sobre as 32 moedas de `UNIVERSE` na base do arquivo | "...a seleção teve Sharpe 0,7, retorno de 16,6% ao ano e pior queda de -25%. Diferença de Sharpe contra comprar e segurar as mesmas moedas: +0,07 (intervalo de 90%: -0,64 a +0,71; bootstrap em blocos de ~66 dias). Diferença compatível com sorte: a vantagem não está demonstrada." |
| `research/engine_reconciliation.py --archive` depois da correção A3 | atribuição da seleção recalculada (abaixo) |

Dados: 271 pares que estiveram no universo point-in-time em algum dia (de 676 na base), 476.048 candles,
fingerprint combinado `dc80de01535f89b9…` (o da base inteira continua `4331555f21d6…`); configuração `e9d2b86cfe5dee90`.
Sem Fear & Greed (bloqueado).

### Resultados (histórico explorado; nada aqui é promessa)

Diferença de Sharpe contra comprar e segurar as mesmas moedas, 2.480 dias (2020-01-01 a 2026-10-15), IC de 90%:

| Estratégia | Sharpe (IC 90%) | Ret. anual | Pior queda | ΔSharpe (IC 90%) | p | p Holm | p máx. | Dobras > 0 | Pior estresse | Variações > 0 | Classificação |
|---|---|---|---|---|---|---|---|---|---|---|---|
| SELECAO | 1,13 (0,31 a 1,92) | 38,4% | −33,4% | +0,71 (+0,08 a +1,23) | 0,017 | 0,27 | 0,17 | 5/7 | +0,62 (início em caixa) | 4/4 | PROMISSORA_NAO_CONFIRMADA |
| SELECAO_PESO_IGUAL | 0,92 (0,13 a 1,63) | 43,6% | −54,1% | +0,51 (−0,11 a +1,00) | 0,047 | 0,71 | 0,36 | 5/7 | +0,44 | 4/4 | EVIDENCIA_INSUFICIENTE |
| TENDENCIA (painel) | 1,07 (0,32 a 1,81) | 46,4% | −59,9% | +0,11 (−0,37 a +0,55) | 0,32 | 1 | 0,91 | 2/7 | +0,08 (atraso) | 5/5 | EVIDENCIA_INSUFICIENTE |
| TENDENCIA_BTC_SEM_STOP | idêntica à TENDENCIA (A11) | | | | | | | | | 2/2 | EVIDENCIA_INSUFICIENTE |
| TENDENCIA_SEM_FILTRO | 1,04 (0,29 a 1,78) | 46,0% | −48,4% | +0,07 (−0,36 a +0,49) | 0,34 | 1 | 0,93 | 1/7 | +0,07 | 1/2 | EVIDENCIA_INSUFICIENTE |
| ROMPIMENTO_VOLUME | 1,02 (0,29 a 1,69) | 38,7% | −44,4% | +0,06 (−0,47 a +0,50) | 0,36 | 1 | 0,94 | 4/7 | −0,02 (atraso) | 5/6 | EVIDENCIA_INSUFICIENTE |
| TENDENCIA_SMA200_SEMANAL | 0,53 (−0,26 a 1,33) | 14,0% | −67,7% | +0,11 (−0,46 a +0,63) | 0,32 | 1 | 0,90 | 3/7 | +0,07 | 2/2 | EVIDENCIA_INSUFICIENTE |
| TENDENCIA_TODAS | 0,41 (−0,36 a 1,15) | 7,7% | −81,8% | +0,12 (−0,37 a +0,57) | 0,29 | 1 | 0,90 | 2/7 | +0,10 | 3/3 | EVIDENCIA_INSUFICIENTE |
| DONCHIAN | 0,90 (0,06 a 1,64) | 32,7% | −50,9% | −0,07 (−0,62 a +0,36) | 0,52 | 1 | 0,98 | 3/7 | −0,16 | 1/3 | NEGATIVA |
| CRUZAMENTO_50_200 | 0,79 (0,05 a 1,56) | 31,1% | −57,5% | −0,17 (−0,65 a +0,28) | 0,72 | 1 | 1,00 | 1/7 | −0,20 | 0/4 | NEGATIVA |
| MOMENTO_90D | 0,76 (−0,09 a 1,57) | 27,9% | −63,6% | −0,21 (−0,81 a +0,29) | 0,72 | 1 | 1,00 | 2/7 | −0,22 | 2/2 | NEGATIVA |
| RSI_SOBREVENDIDO | 0,28 (−0,14 a 0,68) | 3,8% | −43,5% | −0,69 (−1,46 a +0,05) | 0,93 | 1 | 1,00 | 2/7 | −0,71 | 0/8 | NEGATIVA |
| MOMENTO_SIMPLES | −0,37 (−1,19 a 0,36) | −73,3% | −100,0% | −0,78 (−1,31 a −0,35) | 0,99 | 1 | 1,00 | 1/7 | −0,84 | 0/2 | NEGATIVA (significativa) |
| BOLLINGER | −0,13 (−0,63 a 0,42) | −9,8% | −71,4% | −1,09 (−1,74 a −0,51) | 1,00 | 1 | 1,00 | 1/7 | −1,12 | 0/6 | NEGATIVA (significativa) |
| QUEDA_NA_ALTA | −0,28 (−0,88 a 0,41) | −3,7% | −29,1% | −1,24 (−2,15 a −0,33) | 0,99 | 1 | 1,00 | 1/7 | −1,25 | 0/2 | NEGATIVA (significativa) |
| PANICO | — | — | — | — | — | 1 | — | — | — | — | INVALIDA (Fear & Greed ausente em 100% dos dias) |

Referências: HOLD_PRINCIPAIS (BTC+ETH) Sharpe 0,96 (0,28 a 1,70), 51,6% ao ano, pior queda −76,4%;
HOLD_TODAS_SEMANAL 0,42 (−0,29 a 1,18), 0,2% ao ano, −95,5%; HOLD_TODAS_DIARIO 0,29 (−0,42 a 1,05), −11,9% ao ano,
−98,3%; só BTC 0,90 (0,19 a 1,64), 43,1% ao ano, −76,6%.

ΔSharpe por dobra (contra a referência):

| Estratégia | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026* |
|---|---|---|---|---|---|---|---|
| SELECAO | −0,33 | +0,52 | +1,72 | −0,59 | +0,87 | +1,01 | +0,92 |
| SELECAO_PESO_IGUAL | −1,13 | +0,22 | +1,72 | −0,33 | +0,48 | +0,75 | +0,98 |
| TENDENCIA | −0,01 | −0,86 | +1,07 | −0,56 | −0,05 | −0,09 | +0,95 |
| TENDENCIA_SEM_FILTRO | −0,53 | −0,43 | −0,53 | −0,53 | −0,04 | −0,25 | +0,95 |
| ROMPIMENTO_VOLUME | −0,32 | +0,34 | +0,37 | −1,43 | +0,08 | −0,13 | +0,14 |
| TENDENCIA_SMA200_SEMANAL | −1,21 | +0,03 | +1,72 | −0,86 | −0,32 | −0,46 | +1,20 |
| TENDENCIA_TODAS | −0,85 | −0,44 | +1,87 | −0,85 | −0,28 | −0,28 | +1,53 |
| DONCHIAN | −0,32 | +0,34 | +0,14 | −1,58 | −0,24 | −0,54 | +0,14 |
| CRUZAMENTO_50_200 | −0,88 | −0,20 | −0,36 | −1,15 | −0,38 | −0,58 | +0,27 |
| MOMENTO_90D | −1,46 | −0,22 | −1,11 | −1,01 | +0,29 | +0,39 | −0,75 |
| MOMENTO_SIMPLES | −0,75 | −0,62 | −1,35 | −0,96 | −0,87 | +0,30 | −3,22 |
| RSI_SOBREVENDIDO | −1,09 | −1,68 | +1,76 | −1,91 | −1,35 | −0,25 | +0,25 |
| BOLLINGER | −1,37 | −2,24 | +0,23 | −0,38 | −1,13 | −0,87 | −1,09 |
| QUEDA_NA_ALTA | −2,35 | −3,02 | −0,27 | −0,69 | −0,69 | −0,98 | +0,04 |

\* 2026 vai até 2026-10-15 (288 dias). Em 2022 as estratégias de tendência ficaram quase todo o ano em caixa
(Sharpe 0) enquanto a referência caiu: a vantagem delas se concentra no ano de baixa.

Sensibilidade (ΔSharpe por cenário): nenhuma estratégia muda de sinal entre BASE e os estresses, exceto
ROMPIMENTO_VOLUME no atraso de 1 dia (+0,06 → −0,02). SELECAO: 0,62 a 0,75 em todos os cenários. Bloco: o IC da
SELECAO fica acima de zero com 5, 20, 60 e 94,9 dias (limite inferior de +0,08 a +0,20); o de SELECAO_PESO_IGUAL
encosta em zero (−0,11 a −0,00) em todos. Escolhas do walk-forward variaram de dobra para dobra em todas as grades
(ex.: Donchian n = 55, 20, 20, 100, 100, 20, 55): os parâmetros não são estáveis.

Leitura:

1. **Nenhuma estratégia atinge evidência robusta.** A seleção é a única com IC da diferença acima de zero e passa em
   todos os outros critérios (dobras, estresses, variações, retorno, queda), mas não sobrevive à correção para as 16
   hipóteses (p Holm 0,27; 0,17 pelo ajuste do máximo). Categoria: promissora, não confirmada. É a hipótese natural
   para o registro prospectivo, não uma conclusão.
2. **A regra do painel (tendência em BTC+ETH) não se distingue de comprar e segurar em retorno por risco** e só
   vence em 2/7 anos; a queda menor (−60% contra −76%) é real nesta amostra, mas não é a hipótese testada.
3. **Seis estratégias têm ΔSharpe negativo**; momento simples, Bollinger e queda dentro da alta, de forma
   significativa. O momento simples no universo completo perde 73% ao ano (colapsos de LUNA e FTT em 2022, baixas
   de 2025); com só as 32 moedas de hoje, a mesma regra rendia +596% na validação 2021–2022 (abaixo): viés de
   sobrevivência em escala.
4. Comprar e segurar o universo point-in-time inteiro perdeu quase tudo (−96% a −98% de pior queda), em parte pelas
   baixas de renomeações tratadas como perda total (A9).

Atribuição da seleção recalculada depois de A3 (`engine_reconciliation.py --archive`, 32 moedas de `UNIVERSE`, retorno
total %, colunas da Fase 2): coluna 4 (publicada) / D (deslistagem 100%):

| Estratégia | Treino | Validação | Teste |
|---|---|---|---|
| seleção | 48,7 / 48,7 | 134,9 / 134,9 | 79,3 / 79,3 |
| seleção, peso igual | 11,0 / 11,0 | 359,7 / 359,7 | 33,1 / 33,1 |
| momento simples | 8,8 / 8,8 | 596,1 / 596,1 | 196,7 / 326,7 |
| regra SMA 200 | 37,8 / 37,8 | 517,0 / 517,0 | 57,1 / 57,1 |
| comprar e segurar todas | 37,6 / 37,6 | 145,1 / 145,1 | 118,3 / 124,0 |
| só BTC | 211,5 / 211,5 | −42,9 / −42,9 | 396,4 / 396,4 |

### O que mudou

| Arquivo | Mudança |
|---|---|
| `src/transformers/metrics.py` (novo) | métricas da série diária com convenções e mínimos de amostra; versões vetorizadas para o bootstrap |
| `src/transformers/bootstrap.py` (novo) | bootstrap estacionário, bloco de Politis e White, IC percentil, p-valor unilateral, diferença pareada, ajuste pelo máximo |
| `src/transformers/multiple_testing.py` (novo) | Holm com hipóteses não testadas contadas como p = 1 |
| `src/transformers/walk_forward.py` (novo) | dobras, verificação de sobreposição (`HoldoutViolation`), escolha por dobra, costura dos alvos, atraso, status explorado/prospectivo |
| `src/transformers/strategy_catalog.py` (novo) | todas as estratégias já testadas, com variações declaradas; `trend_signal` reproduz a regra do painel |
| `src/transformers/validation.py` (novo) | protocolo: cenários, dobras, variações, regimes, bootstrap conjunto, Holm, ajuste pelo máximo, classificação |
| `src/transformers/evidence.py` (novo) | critérios e categorias |
| `src/transformers/experiments.py` (novo) | especificação, id determinístico, linhas do registro, `reproduces`, `assert_comparable` |
| `src/loaders/experiment_store.py` (novo) | registro e tabelas append-only (`DuplicateRunError`) |
| `research/validation_study.py` (novo) | entrypoint da validação com dados reais |
| `src/transformers/selection_backtest.py` | correção A3 (`eligible` em `selection_targets`, `baseline_targets`, `_all_targets`); `evaluate_selection_runs`; `evidence_with_uncertainty`; docstring atualizado |
| `src/transformers/strategies.py` | recebeu `bollinger_reversion`, `rsi_oversold` e `dip_in_uptrend` (antes em `research/`), sem mudança de lógica |
| `src/pipeline.py`, `src/config.py` | frase de evidência com incerteza; `VALIDATION_SEED`, `VALIDATION_BOOTSTRAP`; docstring dos períodos (2023+ explorado) |
| `src/transformers/recommendation.py` | só o comentário do campo `evidence` |
| `research/lab.py`, `strategy_comparison.py`, `engine_reconciliation.py` | reexportam os sinais movidos; a reconciliação passa `eligible` à seleção |
| `README.md`, `docs/LEGACY.md` | seção "Validação estatística", leitura da frase de evidência, estrutura, nota do laboratório |
| `tests/test_statistics.py` (novo, 14), `tests/test_validation_protocol.py` (novo, 18), `tests/test_selection.py` (+1) | ver abaixo |
| `tests/golden/recommendation.parquet`, `selection_backtest.parquet` | regenerados: só a frase de evidência e as referências da seleção (A3) mudaram |

### Testes e verificações executados

| Verificação | Resultado |
|---|---|
| `uv run pytest -q` | **269 passed** (236 da Fase 2 + 33 novos), 125 s |
| `uv run mypy --strict src/ mcp_server.py` | Success: no issues found in 51 source files |
| `uv lock --check` (uv 0.13.0) | ok |
| `requirements.txt` regenerado e comparado | sem diferença |
| Parquet/CSV/.env versionados fora de `tests/golden` | nenhum |
| `npm run build` (frontend, tsc estrito + vite) | ok (só o aviso de chunk > 500 kB, preexistente); nenhum arquivo do frontend mudou |
| Regressão sintética da Fase 2 | preservada: só `recommendation.evidence` e as referências de `selection_backtest` mudaram, conferido coluna a coluna contra a cópia de antes da fase |

Testes novos, por exigência da fase:

| Exigência | Testes |
|---|---|
| ausência de look-ahead | `test_truncating_after_d_changes_no_signal_or_selection_up_to_d` (todos os sinais do catálogo, seleção e referências, 3 datas de corte) |
| separação treino/validação/teste | `test_folds_are_annual_anchored_and_never_overlap_the_choice`, `test_embargo_and_prospective_status`, `test_overlapping_or_short_windows_are_rejected`, `test_decisions_use_only_parameters_chosen_before_them` |
| impossível otimizar com o teste | `test_grid_choice_ignores_prices_inside_the_test_window` (preços do teste ×3: escolha idêntica; o avaliador nunca recebe decisões do teste) |
| métricas | `test_metrics_match_hand_computed_values`, `test_drawdown_depth_duration_and_open_flag`, `test_vectorized_rows_match_the_scalar_definition` |
| bootstrap temporal | `test_stationary_indices_are_reproducible_circular_blocks_with_the_requested_mean_length`, `test_automatic_block_grows_with_serial_dependence`, `test_block_bootstrap_ci_is_wider_than_iid_under_autocorrelation`, `test_ci_coverage_of_the_mean_is_close_to_nominal_on_ar1` (cobertura em AR(1)), `test_paired_difference_detects_a_real_edge_and_not_a_fake_one` |
| comparações múltiplas | `test_holm_matches_the_textbook_example`, `test_untested_hypotheses_stay_in_the_family_with_p_one`, `test_max_stat_adjustment_is_never_below_the_raw_p_value` |
| reprodutibilidade | `test_family_evaluation_is_complete_reproducible_and_flags_invalid_tests`, `test_experiment_id_is_deterministic_and_covers_data_and_premises`, `test_registry_is_append_only_and_flags_reproduction` |
| configurações e fingerprints | `test_experiment_id_is_deterministic_and_covers_data_and_premises`, `test_registry_is_append_only_and_flags_reproduction` |
| dados ausentes | `test_all_cash_has_zero_sharpe_and_missing_returns_are_rejected`, `test_bootstrap_refuses_misaligned_or_missing_data`, feature ausente = INVALIDA em `test_family_evaluation...` |
| amostras pequenas | `test_small_samples_do_not_get_annualized_or_ratio_estimates`, `test_luck_small_samples_negative_and_invalid_are_separated` |
| sensibilidade às premissas | `test_family_evaluation...` (todos os cenários; custo alto < custo baixo) |
| sem mistura de motores | `test_mixing_engines_or_data_in_one_comparison_is_refused`, `test_strategy_and_benchmark_must_share_the_execution_premises` |
| classificação | `test_robust_requires_every_criterion`, `test_luck_small_samples_negative_and_invalid_are_separated` |
| defeito A3 | `test_references_and_selection_only_use_coins_eligible_on_the_day` |
| frase do pipeline | `test_pipeline_evidence_reports_uncertainty_and_never_calls_the_period_untouched` |
| catálogo = regra do painel | `test_catalog_trend_is_the_panel_rule` |

### Critérios da Fase 3

| Critério | Situação |
|---|---|
| Auditoria com gravidade, impacto e evidência | **cumprido** (A1–A15) |
| Protocolo walk-forward com janelas, aquecimento e embargo explícitos | **cumprido** |
| Parâmetros nunca escolhidos no período de avaliação | **cumprido** para as grades (walk-forward, teste dedicado); **não aplicável às regras fixas**, que foram desenhadas olhando o histórico inteiro (declarado como EXPLORADO) |
| 2023–2026 não apresentado como teste intocado | **cumprido** (pipeline, README, registro) |
| Protocolo prospectivo | **parcial**: registrado (`AGUARDANDO_DADOS`, 365 dias); a coleta e a avaliação são da Fase 7 |
| Métricas com convenções e mínimos de amostra | **cumprido** |
| Intervalos com dependência temporal | **cumprido** (bootstrap estacionário, bloco automático, sensibilidade ao bloco) |
| Registro de experimentos completo, sem sobrescrever | **cumprido** (append-only, id determinístico, fingerprints de dados e configuração, `reproduces`, status e limitações) |
| Correção para comparações múltiplas com família e nível definidos | **cumprido** (Holm, α = 5%, 16 hipóteses; ausentes com p = 1; ajuste pelo máximo como complemento) |
| Robustez e sensibilidade | **cumprido** para custos, atraso, posição inicial, deslistagem, dados parciais, parâmetros, janelas e regimes; **parcial** para dados parciais (os sinais não são recalculados com os candles removidos) |
| Referências definidas antes e com as mesmas premissas | **cumprido**; a validação recusa premissas diferentes |
| Classificação com todos os critérios para "robusta" | **cumprido** |
| Integração sem quebrar o pipeline nem mudar sinais | **cumprido** (só o texto `evidence` mudou) |
| Fear & Greed ausente sinalizado | **cumprido** (PANICO = INVALIDA) |
| Universo histórico completo nos backtests | **parcial**: na validação, sim (271 pares); no pipeline diário, as candidatas continuam sendo `config.UNIVERSE` |
| Laboratório migrado para o motor único | **cumprido para a avaliação** (todas as estratégias e grades reavaliadas no motor único); os scripts antigos continuam no motor legado como registro |
| Testes de frontend | **não cumprido** (não há framework; pendência da Fase 0) |

### Limitações remanescentes

- **Histórico explorado.** Toda a evidência desta fase é sobre dados já vistos no desenvolvimento das regras. A única
  confirmação possível é prospectiva (Fase 7).
- **Deslistagem x renomeação (A9).** A perda total em renomeações e trocas de token distorce as estratégias
  multi-moeda e suas referências (as duas sofrem, mas não necessariamente na mesma proporção). O cenário de 100% de
  recuperação não muda nenhuma classificação, mas o tratamento certo exige uma tabela de eventos oficiais verificados
  (`point_in_time.merge_events` já aceita), que não existe no sistema.
- **Uma só história de mercado**, com cerca de dois ciclos completos; 7 dobras anuais; o bloco automático (~95
  dias) deixa poucas reamostras independentes por série. Os intervalos são largos por isso, e não há como estreitá-los
  sem mais tempo de dados.
- **Intervalo percentil** sem correção de viés (não é BCa nem studentizado); Holm é conservador com estratégias
  correlacionadas; o ajuste pelo máximo é de passo único.
- **Hipótese única por estratégia** (Sharpe contra a referência). A redução de queda da regra do painel não foi
  testada como hipótese própria; testá-la agora, depois de ver os números, seria escolher a hipótese pelo resultado.
  Se for de interesse, deve entrar pré-registrada no protocolo prospectivo.
- **Variações já estudadas antes** (`selection_study.py`, laboratório antigo) não entram na contagem da família;
  a multiplicidade real é maior que 16.
- **Custos** continuam hipóteses por faixa de volume; os cenários cobrem metade e o dobro.
- **Fear & Greed indisponível**: o pânico não foi avaliado.
- **Regimes** são descritivos (o rótulo do BTC define-se pelo próprio BTC; não há teste por regime).
- **Pipeline diário** com candidatas de `config.UNIVERSE` (viés de sobrevivência): a frase de evidência é sobre esse
  universo, diferente do universo da validação.

### Próximos passos

**Fase 4 (regimes):** construir os rótulos de regime só com dados até D (tendência e volatilidade do BTC, dispersão
entre moedas, liquidez), com limiares estimados no treino de cada dobra; testar se a vantagem de alguma estratégia
depende do regime com o mesmo protocolo (walk-forward, bootstrap, família pré-registrada) e tratar a escolha do
regime como mais uma comparação múltipla. Integrar uma tabela verificada de renomeações e deslistagens (A9) antes de
qualquer conclusão sobre estratégias multi-moeda.

**Fase 5 (seleção adaptativa, modo sombra):** qualquer seletor (escolher estratégia ou peso por regime) é avaliado
como uma estratégia a mais da família, com a escolha feita só dentro do treino de cada dobra e registrada no
registro de experimentos; em produção, só em modo sombra (sem afetar a recomendação) até acumular dados prospectivos.
Candidata natural para acompanhamento: SELECAO (promissora, não confirmada), já registrada com status
`AGUARDANDO_DADOS`.


---

# Parte 2 — Fases 4 e 5 e validação do COMPRAR (linha local)

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

**Continua aberto:** unificar os dois motores (o nome `COMPRAR_E_SEGURAR` existe nos dois com simulações diferentes); universo point-in-time (bloqueado por falta de fonte); convenção de execução; usar o bootstrap nos demais estudos.

**Redesign do frontend (concluído):** painel horizontal com barra superior, indicadores e painéis em grade; a Visão geral caiu de 5.305 px para 1.341 px de altura no desktop (e de 10.037 para 2.513 no celular), sem rolagem horizontal; nova área de regimes (experimental). Detalhes, medições e limitações da validação visual em [AUDIT.md](AUDIT.md#redesign-do-frontend-16102026).

**Verificação final (16/10/2026):** `uv run pytest` 242 passaram; `mypy --strict` sem erros (42 arquivos); `uv lock --check` e `uv sync --locked --dry-run` consistentes; `npm run build` passou. O estado completo (fases F0 a F5, pendências e conclusão da seleção adaptativa) está em [AUDIT.md](AUDIT.md) e [regime_policy.md](regime_policy.md).


## Merge com origin/main (16/10/2026)

- Resolvido preservando as duas linhas. O núcleo de lag local foi revertido em favor do motor de referência do remoto; os motores legados seguem reproduzindo `tests/golden/legacy_v1` (`evaluate_selection_legacy` fixa `guard_exposure=False`, o motor v1).
- `strategy_catalog.py` do remoto (sinais da validação) e o catálogo local de evidência convivem: este virou `strategy_evidence_catalog.py`.
- Scripts legados da raiz, `requirements.txt` e `architecture.md` seguem removidos (decisão do dono do repositório); `tests/test_legacy.py` e a verificação do `requirements.txt` no CI foram retirados junto. O CI aceita `evidence/*.parquet` como único Parquet versionado além de `tests/golden`.
- Referência dourada `tests/golden/history_digest.parquet` regenerada de propósito: COMPRAR/PREPARAR agora exigem evidência estatística (`buy_days`/`watch_days` caem a zero sem `evidence/signal_evidence.parquet`). Nada mais mudou nas referências.

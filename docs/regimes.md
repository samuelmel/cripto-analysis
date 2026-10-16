# Regimes de mercado (Fase 4)

Classificação causal do estado do mercado de criptomoedas, publicada em `frontend/public/market_regimes.parquet`. É uma **descrição** para análise: não executa ordens, não altera regras de compra, venda, stop, orçamento ou risco, e não escolhe estratégias (isso é da Fase 5). Código: [`src/transformers/regimes.py`](../src/transformers/regimes.py) (classificador), [`src/transformers/regime_evaluation.py`](../src/transformers/regime_evaluation.py) (diagnóstico) e [`research/regime_study.py`](../research/regime_study.py) (estudo).

> [!IMPORTANT]
> Associação histórica não é causalidade, e um regime não é um sinal de compra. Os números de desempenho por regime mostrados aqui são **exploratórios**: uma única história de mercado (BTC, desde 2017), poucos episódios, sem teste de hipótese e sem correção de múltiplas comparações.

## 1. Diagnóstico da implementação anterior

| Item | Situação encontrada |
|---|---|
| Cálculo | `selection.regime_series`: BTC contra SMA 200 e SMA 50 → `FAVORAVEL`, `NEUTRO`, `DEFENSIVO`, `INDISPONIVEL`. |
| Causalidade | Janelas só para trás: causal. Ressalva: `compute_features` decide o `ffill` com `raw.bfill()` (depende de existir candle depois). Só afeta dias **sem candle**, que o regime antigo já marca `INDISPONIVEL`. |
| Dimensões | Só tendência. Nenhuma de volatilidade ou drawdown. |
| Estabilidade | Sem confirmação nem zona morta: cada cruzamento da SMA 200 troca o estado (73 trocas em 9 anos no BTC, 18 só em 2025). |
| Definições duplicadas | `anomaly_detector.regime_up` (estágio SMA 200) e `selection.regime_series` calculam a mesma ideia em dois lugares. |
| Consumidores | `allocation` (reduzir alvos), `selection_backtest`, `recommendation.parquet` (`regime`), Telegram (`REGIME_TEXT`) e frontend (`REGIMES`, `Recommendation.tsx`). |
| Estudo de volatilidade | `research/selection_study.py::btc_vol_regimes` mede os terços no treino inteiro, inclusive para os dias do próprio treino. |
| Contrato | Sem versão, parâmetros ou fingerprint associados ao regime. |

Decisão: **o regime antigo não muda** (nem valores, nem significado, nem consumidores). O novo classificador é aditivo e a saída traz `legacy_regime` ao lado, para comparação e migração futura.

## 2. Definição causal

O candle diário é rotulado pela hora de abertura (`D 00:00 UTC`) e fecha em `D+1 00:00 UTC`.

- A linha de `D` usa só candles fechados até `D`. Candles com `timestamp + 1 dia > as_of` (ainda abertos) e posteriores a `as_of` são descartados.
- `known_at = D + 1 dia`: primeiro instante em que a linha pode ser usada. Nunca é posterior a `as_of`.
- Mesmo contrato de `selection.compute_features` e de `selection_backtest.run_weighted`: decisão no fechamento de `D` usa a linha de `D` e vale a partir do retorno de `D+1`. A execução de qualquer ordem continua sendo a do motor existente, que **não** foi alterado.
- A data de referência (`as_of`) é parâmetro, injetado por `pipeline.analyze`. Nada lê o relógio.

## 3. Abordagem e justificativa

**Regras explícitas em duas dimensões independentes.** É a opção interpretável, testável e compatível com a infraestrutura (sem dependência nova).

| Dimensão | Feature | Finalidade |
|---|---|---|
| Tendência | `dist_ma_pct`: fechamento / média móvel de 200 dias − 1 | Onde o preço está em relação à tendência de longo prazo |
| Tendência | `slope_ma_pct`: variação dessa média em 30 dias | Separa "acima de uma média que sobe" de "acima de uma média que cai" (transição) |
| Volatilidade | `vol_ann_pct`: desvio dos retornos log de 30 dias, anualizado (365) | Nível de risco realizado |
| Volatilidade | `vol_rank_pct`: posição da volatilidade de hoje entre as do passado do próprio ativo | Torna "alta" relativa ao que o ativo já viveu, sem limiar fixo no código |

### Regras (parâmetros em `src/config.py`, fixados a priori)

| Estado de tendência | Condição (sinal bruto) |
|---|---|
| `ALTA` | `dist` > +5% e inclinação ≥ −2% |
| `BAIXA` | `dist` < −5% e inclinação ≤ +2% |
| `LATERAL` | |`dist`| ≤ 5% e |inclinação| ≤ 2% |
| `MISTO` | Todo o resto: sinais conflitantes ou transição |
| `INDETERMINADO` | Dados válidos, mas nenhum estado confirmado ainda |
| `INDISPONIVEL` | Sem dado confiável (ver `status`) |

**Confirmação:** um estado novo só vale depois de **5 dias seguidos** com o mesmo sinal bruto; até lá vale o anterior. Custo: atraso de até 4 dias nas viradas. Depois de um dia indisponível o estado recomeça `INDETERMINADO` (um estado velho não é arrastado por cima de um buraco).

**Volatilidade:** `ALTA` quando o percentil contra o passado **estrito** (só observações anteriores ao dia) passa de 80, com histerese (só volta a `NORMAL` abaixo de 70). `INDISPONIVEL` até haver 365 observações passadas. Como é relativa ao passado do próprio ativo, com ruído estacionário cerca de 20% dos dias seriam `ALTA` por construção; e, como 2018–2021 foram muito mais voláteis que 2023–2025, a volatilidade recente quase nunca é `ALTA` (ver seção 7).

### Alternativas não adotadas nesta fase

| Alternativa | Por que não agora |
|---|---|
| Clusterização (k-means, GMM) | Exigiria ajuste só no treino de cada janela e escolher k; os rótulos não teriam significado estável entre janelas. Sem ganho demonstrado sobre as regras. |
| Estados latentes (HMM) | Só valeria com inferência **filtrada** (nunca suavizada) e calibração; a complexidade não se justifica com uma única história de mercado. |
| Breadth do mercado | Exige universo historicamente válido. O universo é o de hoje (viés de sobrevivência) e não cobre as 676 moedas históricas. |
| Volume | Sem definição histórica estável nem teste de utilidade. |
| Fear & Greed | Fonte externa que pode faltar; o regime **não depende dela** (testado com a base sem F&G). |
| Probabilidade/confiança | As regras não são um modelo calibrado; não há porcentagem inventada. |

## 4. Contrato de saída (`market_regimes.parquet`)

Uma linha por **dia de calendário**, do primeiro candle ao último dia fechado em `as_of`. Dia sem candle aparece como `SEM_CANDLE`; nunca é pulado nem preenchido. Parquet snappy, escrita atômica por `write_parquet`. O schema é `regimes.REGIME_SCHEMA` e o espelho TypeScript é `MarketRegime` em [`signals.ts`](../frontend/src/types/signals.ts) (um teste confere que os dois têm as mesmas colunas, na mesma ordem).

| Coluna | Significado |
|---|---|
| `timestamp`, `known_at` | Dia `D` (abertura) e `D + 1 dia` (fechamento: primeiro uso permitido) |
| `symbol`, `close` | Ativo de referência (`REGIME_SYMBOL`) e fechamento observado (nulo se não há candle válido) |
| `dist_ma_pct`, `slope_ma_pct` | Features de tendência; nulas se `status` ≠ `OK` |
| `vol_ann_pct`, `vol_rank_pct` | Features de volatilidade; `vol_rank_pct` nulo antes do aquecimento do percentil |
| `trend_raw`, `trend_regime` | Sinal bruto do dia e regime confirmado |
| `vol_regime` | `NORMAL`, `ALTA` ou `INDISPONIVEL` |
| `status`, `vol_status` | Validade de cada dimensão: `OK`, `SEM_CANDLE`, `DADO_INVALIDO`, `HISTORICO_INSUFICIENTE`, `DADOS_INCOMPLETOS` |
| `legacy_regime` | Regime antigo (`FAVORAVEL`/`NEUTRO`/`DEFENSIVO`/`INDISPONIVEL`), só para comparação |
| `classifier_version`, `params_hash` | Versão do classificador e fingerprint dos parâmetros |
| `data_fingerprint` | Hash encadeado dos preços até `D`: o mesmo prefixo de dados dá o mesmo valor |

**Dados ausentes:** nada vira zero nem preço repetido. Cada janela tolera até 10% de dias sem candle (`REGIME_MIN_COVERAGE`); além disso o dia fica `DADOS_INCOMPLETOS`. A janela inteira de 200 dias precisa existir (aquecimento de 229 dias para a tendência; 30 + 365 para a volatilidade).

**Mudou um parâmetro ou a regra?** `params_hash` muda. Mudou o **significado** de um estado? Sobe `CLASSIFIER_VERSION`; nunca em silêncio.

**Reprodutibilidade:** mesmos dados e parâmetros → tabela idêntica (testado, inclusive com entrada embaralhada e duplicada).

## 5. Integração

`pipeline.analyze` calcula o regime com os candles já limpos do BTC e publica `market_regimes.parquet` **antes** do `daily_signals.parquet` (que continua sendo gravado por último). O resultado **não entra** em `assess`, `allocate`, `evaluate_selection`, recomendação nem Telegram; um teste troca todos os regimes por `BAIXA`/`ALTA` e confere que sinais, aportes, recomendação e backtest ficam idênticos. O frontend ganhou o tipo e o leitor (arquivo opcional; sem ele, lista vazia) e **nenhuma tela mudou**.

## 6. Testes

[`tests/test_regimes.py`](../tests/test_regimes.py): causalidade por truncamento do futuro em quatro pontos, por alteração e remoção de preços futuros, e `known_at`; candles abertos e futuros; histórico curto e aquecimento exato; candle ausente, preço inválido (0, negativo, ∞, NaN) e janela incompleta; confirmação e transições; reprodutibilidade e fingerprints; percentil só com o passado estrito; limiar ajustado só com dados de treino (nada do ano de teste nem depois); separação entre classificação operacional e desfecho posterior; pipeline com base sem Fear & Greed; base desatualizada; contrato com o frontend (colunas e listas de valores). Foi feita uma checagem de mutação: injetar janela centrada ou percentil sobre a série inteira faz os testes de causalidade falharem.

## 7. Resultados do estudo temporal (BTC, dados locais até 15/10/2026)

`uv run python research/regime_study.py` (classificador `regimes-1.0.0`, parâmetros `980544642a872dfa`). Descritivo e exploratório; sem inferência estatística.

| Leitura | Resultado |
|---|---|
| Dias classificados | 3.118 de 3.347 (tendência) e 2.952 (volatilidade); o resto é aquecimento (`HISTORICO_INSUFICIENTE`). Nenhum dia `DADOS_INCOMPLETOS` ou `SEM_CANDLE` no BTC. |
| Tendência | `ALTA` 46,0% (12 episódios, mediana 97 dias), `BAIXA` 31,4% (8; 67), `MISTO` 18,9% (17; 35), `LATERAL` 3,7% (5; 26). 4 dias `INDETERMINADO`. |
| Volatilidade | `ALTA` em 7,8% dos dias (6 episódios, mediana 39 dias). |
| Trocas de tendência | 41 no total contra 73 do regime antigo. Menos em 2018–2021 e 2023–2025 (2025: 4 contra 18), **mais** em 2022 (2 contra 0) e 2026 (4 contra 2): a melhora não é uniforme. |
| Estabilidade por ano | `ALTA` domina 2020, 2021, 2023–2025; `BAIXA` domina 2018 e 2022 e 2026 até agora. A volatilidade foi `ALTA` em 11% (2019), 10% (2020), 27% (2021), 7% (2022), **0% em 2023–2025**. |
| Sensibilidade | Banda ±20%, inclinação plana ±25% e confirmação 3/7 dias: 96–99% de concordância na tendência. **Janela da média 150/250 dias: só 80% e 83%** — a classificação depende de forma material da escolha da janela. Limiares de volatilidade 75/65 e 85/75: 97–98%. |
| Walk-forward da volatilidade | Limiar ajustado só com anos anteriores ao de teste concorda com o percentil online em 91,5% a 100% dos dias de cada ano. Em 2019 e 2022 o limiar congelado marca menos dias `ALTA` (2,7% e 1,6%) do que o online (11,2% e 6,6%). |
| Desfechos posteriores (exploratório) | Volatilidade realizada nos 30 dias seguintes: `ALTA` 74% contra 56% em `NORMAL` (coerente com persistência de volatilidade). Retorno médio de 30 dias seguintes: `ALTA` +3,9%, `BAIXA` −0,0%, `MISTO` +0,3%, `LATERAL` +12,5% (5 episódios). Sem intervalo de confiança nem correção: **não há evidência suficiente** para afirmar que o regime separa retornos futuros. |

## 8. Limitações

- Uma única série (BTC) e uma única história de mercado; poucos episódios por regime.
- Parâmetros fixados a priori, **não validados** contra alternativas por walk-forward estatístico (a Fase 3 não existe neste repositório). A sensibilidade só mede dependência; não escolhe nada.
- Forte dependência da janela da média (150/250 dias mudam ~17–20% dos rótulos).
- A volatilidade é relativa ao passado inteiro do ativo: o início do histórico (2018–2021) pesa muito, e a volatilidade recente é raramente `ALTA`. Ela também não distingue um regime de baixa volatilidade persistente de um nível absoluto aceitável.
- A confirmação de 5 dias atrasa as viradas (custo explícito de estabilidade).
- Sem breadth, volume ou dados on-chain/derivativos. Moedas fora do BTC não têm regime próprio.
- Estudo de desfechos usa janelas sobrepostas: o número de dias não é o tamanho da amostra.

## 9. Dependências para a Fase 5

A seleção de estratégias por regime **não deve começar** antes de:

1. Validação estatística (Fase 3): intervalos de confiança com bootstrap temporal, controle de múltiplas comparações e registro de experimentos. Hoje nada disso existe; só o walk-forward anual simples de `selection_study.py`.
2. Motor único de backtest com execução definida (hoje: execução no fechamento de `D`; o enunciado da Fase 2 menciona abertura de `D+1`, o que **não** está implementado aqui).
3. Universo historicamente válido (point-in-time) para breadth e para evitar viés de sobrevivência.
4. Decisão explícita sobre a janela da média e a política de confirmação, com evidência fora da amostra.

# Estudo da IA v2 (EXPLORATÓRIO): base ampliada e ranking de todas as moedas

Escrito e commitado antes de executar, mas **exploratório**: a v1 (`docs/ml_study.md`) já foi vista nos mesmos anos de
mercado, então nada aqui vale como teste independente. Serve para ver se o que a v1 mostrou se mantém com mais dados e
com uma métrica que usa todas as moedas. Não muda nível de nenhum modelo nem tira nada do modo sombra.

## O que muda em relação à v1

1. **Mais histórico real.** Além dos pares em USDT, os pares em BTC do arquivo oficial da Binance que começaram antes
   do par em USDT da mesma moeda, ou que nunca tiveram par em USDT (180 pares, 63 só em BTC), convertidos para dólar
   pelo BTCUSDT do mesmo dia e emendados antes do primeiro candle em USDT (`quote_conversion.py`). Mesmo filtro
   `continuidade-v1`, mesmo universo point-in-time.
2. **Todas as moedas do universo**, não só as 5 primeiras:
   - **IC de postos**: correlação de Spearman, a cada dia, entre a probabilidade do modelo e o retorno líquido de 30
     dias, sobre todas as moedas do universo;
   - **Spread entre quintos**: retorno médio do quinto de maior probabilidade − o do quinto de menor;
   - o **excesso do top-5** da v1, para comparação.
3. **Sem 2021**: cada métrica também sem o ano de 2021, porque a vantagem da v1 veio quase toda dele.

Mesmos modelos, hiperparâmetros, walk-forward, expurgo, períodos e bootstrap da v1 (`StudyRules`). Referência: o
momento de 90 dias com as mesmas métricas. Sem Fear & Greed, só os modelos SEM_FNG são executados.

## Como ler

- IC médio > 0 com IC de 95% acima de zero = o modelo ordena melhor que o acaso nessa amostra.
- Um resultado que só aparece com 2021 não é tratado como vantagem.
- Holm não é aplicado como critério (exploratório); os p-valores são mostrados como descrição.

## Limitações (escritas antes)

- Os pares em BTC convertidos aproximam máxima, mínima e volume em dólar; o custo usa o volume convertido.
- Mais moedas não são mais anos: as moedas andam juntas, o ganho de informação é pequeno.
- Exploratório sobre dados já vistos: qualquer achado precisa de confirmação prospectiva.

## Resultado da execução de 2026-10-19 (exploratório, sem Fear & Greed)

Código `678a55a` (protocolo commitado antes), dados `3ee90e90dbb3…`: 769 séries e 943.033 candles (com 179 moedas
ampliadas pelos pares em BTC convertidos, 321.214 candles), 92.269 linhas (dia, moeda) no universo (v1: 82.192).
Sem Fear & Greed: só os modelos SEM_FNG. Saída: `evidence/ml_study_v2/ranking.parquet`. IC de 95% por bootstrap
estacionário (bloco ≥ 30 dias).

| Modelo | Métrica | Desenvolvimento 2020–2024 | Sem 2021 | Teste final 2025+ |
|---|---|---|---|---|
| Boosting sem F&G | IC de postos | **+0,097** (+0,035 a +0,153) | **+0,081** (+0,016 a +0,145) | **+0,148** (+0,108 a +0,190) |
| Boosting sem F&G | quinto superior − inferior | +4,0 pp (+0,3 a +7,0) | +2,1 pp (−2,3 a +6,0) | +8,2 pp (+5,4 a +11,3) |
| Boosting sem F&G | top 5 − universo | +1,9 pp (−0,4 a +4,1) | +0,4 pp (−2,2 a +2,9) | +2,6 pp (+0,9 a +4,6) |
| Logística sem F&G | IC de postos | +0,050 (+0,013 a +0,088) | +0,067 (+0,026 a +0,104) | +0,149 (+0,071 a +0,225) |
| Logística sem F&G | quinto superior − inferior | −0,4 pp (−4,6 a +3,5) | +2,6 pp (+0,1 a +5,5) | +10,5 pp (+5,7 a +15,9) |
| Logística sem F&G | top 5 − universo | −2,9 pp (−6,2 a −0,0) | −1,3 pp (−3,4 a +1,0) | +4,1 pp (+1,8 a +6,8) |
| Momento 90 dias (referência) | IC de postos | **−0,102** (−0,147 a −0,059) | −0,099 | −0,097 |
| Momento 90 dias (referência) | top 5 − universo | −3,1 pp | −4,4 pp | −4,7 pp |

IC de postos do boosting por ano: 2020 −0,088; 2021 +0,159; 2022 +0,199; 2023 +0,110; 2024 +0,105; 2025 +0,146; 2026
+0,152. Positivo em 77% dos meses.

Leitura (exploratória, sobre dados já vistos):

- **Olhando todas as moedas, os dois modelos ordenam melhor que o acaso**, com intervalo acima de zero no
  desenvolvimento, sem 2021 e no teste final. É um achado mais consistente que o da v1, que olhava só as 5 primeiras:
  o IC do boosting é positivo em 6 de 7 anos.
- **O momento de 90 dias tem IC negativo e estável (−0,10):** nesta amostra, as moedas que mais subiram em 90 dias
  tenderam a render menos nos 30 dias seguintes (reversão). Boa parte do que os modelos aprenderam pode ser esse
  efeito de reversão. Isso explica por que "superar o momento" foi fácil na v1.
- **Em carteira só comprada, o ganho é menor:** o top 5 do boosting rende +1,9 pp contra o universo no
  desenvolvimento (intervalo inclui zero) e só +0,4 pp sem 2021. A ordenação ajuda mais a evitar as piores (quinto
  inferior) do que a escolher as 5 melhores. Vender a descoberto as piores não é algo que o projeto simula nem
  recomenda.
- **O teste final (2025+) é o mais forte**, mas tem só 622 dias e o bloco mínimo de 30 dias, então a precisão é
  otimista.
- Nada aqui muda o nível dos modelos nem os tira do modo sombra. A pergunta para os dados prospectivos fica mais
  precisa: **o IC de postos do boosting continua positivo nas previsões registradas?** As carteiras simuladas e o
  registro diário já respondem isso com dados novos.

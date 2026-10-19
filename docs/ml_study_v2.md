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

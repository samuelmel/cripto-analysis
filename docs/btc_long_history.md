# Regra SMA 200 no BTC com o histórico da Bitstamp (2011–2017): protocolo fixado antes dos dados

Escrito e commitado **antes** de os dados serem baixados (eles só chegam pelo GitHub Actions, workflow "Base de
pesquisa"). Protocolo `btc-longo-v1`.

## Por que este teste é diferente

Todo o resto do projeto usa dados da Binance, que começam em 2017-08-17, e esses anos já foram consultados muitas vezes
no desenvolvimento. **De 2011 a meados de 2017 nada foi olhado neste projeto.** A regra do painel (BTC acima da média de
200 dias, com STOP de −20% sobre o fechamento da entrada) foi fixada antes, então esse período é um teste fora da
amostra de verdade para ela. Ressalva honesta: a média de 200 dias é uma regra conhecida do mercado, estudada por
muita gente nesses anos; o que é inédito é o teste dela com o código, os custos e a execução deste projeto.

## Dados

- Bitstamp, BTC/USD diário (API pública oficial), de 2011-08-18 a 2017-08-16 (o dia antes do primeiro candle da
  Binance). Filtro `continuidade-v1`; dias sem candle e candles com volume zero são contados e publicados.
- A média de 200 dias exige 200 candles: o primeiro dia avaliável é o 200º candle da série.

## Regra e referência

- **Regra**: `strategy_catalog.trend_signal` com o BTC como a própria moeda e o próprio filtro de mercado: comprado
  quando o fechamento está acima da SMA 200, com o STOP de −20%. 100% em BTC quando comprado, caixa quando não.
- **Referência**: comprar e segurar BTC no mesmo período.
- **Execução**: motor único (`next-open-v1`): decisão no fechamento, execução na abertura seguinte; custos de
  `config.py` (taxa 0,1%, meio-spread pela faixa de volume, slippage 0,05%). Mesma configuração para as duas.

## Hipótese e teste

- **Uma hipótese, declarada agora**: H1: Sharpe(regra) − Sharpe(comprar e segurar) > 0 no período 2011–2017.
- Bootstrap estacionário pareado (`bootstrap.py`), bloco automático (Politis e White), 2.000 reamostras, semente
  20261019; IC de 90% (percentil); p unilateral. α = 5%.
- **Resultado**: CONFIRMADA se p < 0,05 e o limite inferior do IC > 0; COMPATIVEL_COM_SORTE se a diferença for > 0 sem
  isso; NEGATIVA se a diferença for <= 0.

## Descritivo (fora da hipótese)

- Retorno anualizado, pior queda, duração da pior queda e tempo investido das duas.
- Por ciclo: 2011–2013, 2014–2015, 2016–2017.
- Sensibilidade: SMA 150 e 250; sem STOP; taxa de 0,5% (tabela da Bitstamp em 2011–2014).
- Série completa 2012–2026 (Bitstamp até 2017-08-16, depois Binance), só descritiva: mistura período inédito e
  período explorado.

## Limitações (escritas antes)

- Um único ativo: os ciclos ficam mais longos, mas continuam poucos (3 grandes quedas).
- Liquidez de 2011–2013 muito menor que a de hoje: custos reais eram maiores (por isso a sensibilidade de taxa).
- O incidente da Mt. Gox (2014) afetou o mercado inteiro; a Bitstamp teve uma suspensão em janeiro de 2015 (hack):
  dias sem candle são tratados pelo motor (ordem pendente, preço marcado no último conhecido).

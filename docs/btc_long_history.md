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

## Resultado da execução de 2026-10-19 (única, conforme o protocolo)

Código `aa93d80` (protocolo commitado antes de os dados existirem), dados da Bitstamp baixados pelo workflow "Base de
pesquisa" (execução 39308972936): BTC/USD de 2011-08-18 a 2026-10-18, 5.541 candles, 0 dias faltando, 33 dias com volume
zero (2011–2012), fingerprint `b23c419cc145…`. Saídas em `evidence/btc_long_history/`.

**H1 (2012-03-05 a 2017-08-16, 1.991 dias, período nunca consultado no projeto):** ΔSharpe da regra contra comprar e
segurar = **+0,10** (IC 90%: −0,17 a +0,45; p = 0,29; bloco ~76 dias) → **COMPATIVEL_COM_SORTE**.

| | Regra SMA 200 | Comprar e segurar |
|---|---|---|
| Retorno total | +90.910% | +90.853% |
| Ao ano | 248,7% | 248,7% |
| Sharpe | 1,97 | 1,87 |
| Pior queda | **−71,2%** | −84,9% |
| Tempo investido | 76% | 100% |
| Entradas | 15 | 1 |

Por ciclo: 2011–2013, regra +11.376% contra +15.104% (a regra saiu e voltou durante a alta); **2014–2015 (a grande
queda depois da Mt. Gox), regra −22% contra −41%**; 2016–2017, idênticas (sempre acima da SMA 200). Sensibilidade:
ΔSharpe +0,03 (SMA 150), +0,08 (SMA 250), +0,10 (sem STOP; o STOP de −20% não mudou nada aqui) e +0,07 com taxa de 0,5%.
(`cost_pct` da regra, 402%, é a soma dos custos em % do capital INICIAL: com o patrimônio multiplicado por 900, os
custos somados passam o capital do começo.)

Leitura:

- **É o mesmo quadro do período da Binance (2018–2026), agora num período inédito:** a regra não rende mais que comprar e
  segurar em retorno por risco de forma demonstrável, mas corta a pior queda (−71% contra −85%; antes, −60% contra
  −76%). Dois períodos independentes contando a mesma história deixam esse achado mais confiável.
- A vantagem está nas quedas longas (2014–2015); nas altas fortes, a regra perde um pouco por sair e voltar.
- Nenhuma regra do painel muda: o texto do painel já diz que a vantagem da regra é suportar melhor as quedas, não
  render mais.

Coleta: só o BTC/USD veio nesta execução. ETH, LTC e XRP começaram na Bitstamp depois de 2011 e o coletor parava na
primeira página vazia; corrigido no commit seguinte (não afeta este teste, que usa só o BTC).

# Estudo UniRenko (exploratório, encerrado)

Dinheiro fictício, sem ordens reais. Código: `research/renko_chart.py`, `download_1h.py`, `unirenko_backtest.py`, `unirenko_atr_backtest.py`.
Dados: Binance 1d e 1h (7 moedas: BTC, ETH, BNB, SOL, XRP, ADA, DOGE; 2017-2020 a 2026-11-02). Execução na abertura do candle seguinte, 0,25% por operação.

| Variante | Testes | Bate comprar-e-segurar (Calmar / Sharpe) |
|---|---|---|
| Bloco fixo 10%, reversão 10/15/20%, lag 0/1, candles 1h | 42 | 29-43% / 0-14% (por configuração) |
| Bloco por ATR(14 ou 20), reversão 1,5x/2x ATR, lag 0, candles 1h | 28 | 21% / 21% |

Critério combinado antes da rodada ATR: parar se < 50% dos testes baterem comprar-e-segurar. Resultado: NÃO ATENDIDO, eixo encerrado.
Efeito consistente: ~50% de exposição e drawdown menor (−82% a −83% vs −91%), sem ganho de retorno ajustado ao risco.
Limites: ordem dentro do candle de 1h suposta; sem teste estatístico; poucos ativos.

# Momentum relativo ao BTC (filtro alfa): protocolo `xs-v2`

Fixado em commit ANTES de qualquer execução. Dinheiro fictício; nenhuma ordem real. Código: `research/relative_btc_study.py`.
Reaproveita o motor, o universo, o custo e as janelas do `xs-v1` (`docs/cross_sectional_study.md`).

## Regra
- Decisão no fechamento de cada domingo (UTC), execução na abertura de segunda; rebalanceamento semanal; candles diários.
- **Candidata:** moeda (exceto BTC) no universo point-in-time do dia, com candle, com retorno `r` de `L` dias > 0 (momentum positivo) E `r` maior
  que o retorno do BTC no mesmo horizonte. Ranking: maior `r` (mesma ordem do preço da moeda dividido pelo do BTC, que é monotônico).
- **Carteira:** as `k` primeiras candidatas, peso 1/k cada. Cada vaga não preenchida (menos de `k` candidatas) vai para o **fallback**: BTC ou caixa.
  Se nenhuma candidata, 100% no fallback.
- **Configurações (8):** `L` em {14, 30} x `k` em {1, 5} x fallback em {BTC, caixa}.
- **Motor e custo:** `backtest_engine` único, 0,25% por lado só sobre o giro; baixa por perda total (recuperação 0) após 7 dias sem candle.
- **Divisão:** IS do primeiro domingo com >= 10 membros com retorno de 90 dias (2019-06-02) a 2022-12-31; OOS cego de 2023-01-01 ao fim da base.
- **Seleção (só IS):** maior Calmar dentro de cada fallback (um escolhido com fallback BTC, um com fallback caixa); cada um é avaliado UMA vez no OOS.
  As 8 configurações no OOS são impressas só como descrição.
- **Referências:** BTC (comprar e segurar) e MERCADO (peso igual, todo o universo, semanal).

## Critério de sucesso (fixado agora)
Um escolhido só é considerado promissor se, no OOS, superar o **BTC comprado e segurado** em Calmar E em Sharpe.
Superar o MERCADO não conta. Mesmo promissor, não é validado (sem IC nem correção para múltiplos testes).
Se nenhum escolhido superar o BTC, o eixo de rotação de altcoins é encerrado.

## Limitações
Histórico já explorado antes no projeto; universo = moedas da Binance em USDT; meio-spread fixo; o OOS de 2023+ é um período de alta do BTC.

## Resultados
(preencher após a execução)

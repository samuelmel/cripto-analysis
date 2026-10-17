# Guia de uso

Tudo o que você precisa no dia a dia depois da [instalação](../README.md#instalação-e-primeiro-uso): rodar a análise, ler o painel, registrar compras e resolver problemas comuns.

- [Rodar a análise](#rodar-a-análise)
- [O painel](#o-painel)
- [Registrar compras e vendas](#registrar-compras-e-vendas)
- [Problemas comuns](#problemas-comuns)

---

## Rodar a análise

Sempre a partir da raiz do projeto:

| Modo | Comando | Usa a internet? |
|---|---|---|
| Normal: atualiza a base e analisa | `uv run python -m src.pipeline` | Sim |
| Só reanalisa a base local | `uv run python -m src.pipeline --offline` | Não |
| Baixa todo o histórico de novo | `uv run python -m src.pipeline --rebuild` | Sim |
| Analisa e envia o resumo pelo Telegram | `uv run python -m src.pipeline --notify` | Sim |
| Gera e valida a mensagem, sem enviar e sem token | `uv run python -m src.pipeline --dry-run` | Sim, para atualizar a base |
| Mensagem de teste totalmente local | `uv run python -m src.pipeline --offline --dry-run` | Não |
| Outro orçamento nesta execução | `uv run python -m src.pipeline --budget 55` | Conforme os outros flags |

`--offline` e `--rebuild` não podem ser usados juntos. `--budget` aceita qualquer valor ≥ 0, em reais.

**Primeira execução.** Baixa os candles diários de cada moeda desde a listagem na Binance (a partir de 2017) e o Fear & Greed desde 2018. Demora mais que as seguintes, que baixam só os dias que faltam. Uma moeda listada há menos de um ano entra na base, mas só é analisada quando completa o histórico mínimo.

**Se uma fonte falhar,** o pipeline continua. A falha vai para o registro de fontes, e a moeda sem dado novo fica **INDISPONÍVEL**. Só uma base local vazia aborta a execução. Detalhes em [architecture.md](architecture.md#garantias-de-qualidade).

### O resumo no terminal

No fim, o pipeline imprime um relatório com:

- moedas fora da análise e o motivo;
- moedas indisponíveis e problemas de qualidade dos dados;
- alertas de virada da regra SMA 200;
- estágios do dia;
- resultado das operações simuladas e da carteira em treino e teste;
- estado do mercado, candidatas e aporte sugerido;
- frase de evidência do backtest da seleção;
- quantas previsões superam a referência;
- status das suas posições.

Trecho real de uma execução `--offline` em 2026-10-15, com a base local de 15 moedas:

```
Ciclo 2026-10-14 · 15 ativos · F&G 53
  fora da análise NEAR/USDT: sem candles na base
  ...
  estágios: {'NEUTRO': 13, 'COMPRAR': 2}
  operações da tendência (BTC/ETH): 61 fechadas · acerto 26% · retorno médio +25.0%
  carteira BTC+ETH teste · TENDENCIA: +209.5% (+34.7%/ano) · pior queda -29.3%
  seleção: mercado FAVORAVEL · 6 candidata(s) · aporte sugerido R$ 60.00 de R$ 100.00 (não alocado R$ 40.00)
  ...
  previsão 1/7/30 dias: 0 de 6 superam o baseline no teste
```

Esse trecho mostra o formato. Não é uma recomendação atual.

---

## O painel

```bash
npm --prefix frontend run dev
```

Abra o endereço da linha `Local:` (normalmente <http://localhost:5173>). O painel lê os arquivos Parquet que o pipeline grava em `frontend/public/`. Depois de rodar o pipeline de novo, recarregue a página.

**Em toda tela.** A barra superior mostra as abas, o fechamento da análise (com o atraso, se houver), a hora da última coleta, o estado da última execução do pipeline e o botão **Recarregar** (relê os arquivos publicados; não roda o pipeline). Logo abaixo, uma faixa com oito indicadores: estado do mercado (regra de risco), regime do BTC (experimental), moedas analisadas, aporte sugerido, suas posições, regra principal (BTC e ETH), risco do BTC e humor do mercado. Avisos (pânico, dado desatualizado, falha de coleta) vêm numa faixa própria, separados das recomendações.

| Aba | O que mostra |
|---|---|
| **Visão geral** | À esquerda, o gráfico (com seletor de moeda e faixa de previsão) e a tabela de todas as moedas; clique numa moeda para ver o gráfico dela. À direita, a recomendação de aporte com as moedas selecionadas (o detalhe de cada uma abre ao clicar), a regra principal SMA 200 com BTC e ETH e um painel de apoio com três abas: **Posições** (registrar compra, "Já vendi", apagar), **Previsão** de 1, 7 e 30 dias e **Descartadas**. |
| **Seleção** | Ranking de todas as moedas analisadas (com rolagem interna), "A seleção funciona no passado?" (backtest contra as referências, por período) e como a seleção decide. |
| **Histórico** | Todas as moedas pela regra SMA 200, o gráfico desde o início da base e cada período em que a regra mandou comprar ou segurar a moeda escolhida. |
| **Previsões** | BTC e ETH lado a lado: gráfico com a faixa P10–P90 tracejada e rotulada como estimativa e a avaliação contra a referência. |
| **Pesquisa** | Um seletor escolhe o grupo: **Regra de tendência** (comparação de carteira com comprar e segurar), **Laboratório** de estratégias, **Regimes (experimental)**, **Como funciona** e **Glossário**. |

**Regimes (experimental).** Mostra o regime de tendência e de volatilidade do BTC, a faixa do tempo desde 2017, a frequência de cada regime e as limitações conhecidas. É só descrição: não gera sinal e não altera aporte, compra nem venda. Vem de `market_regimes.parquet` (arquivo opcional, gerado pelo pipeline).

**Acessibilidade.** As abas mudam com as setas do teclado. Termos como média de 200 dias, pior queda, volatilidade, faixa de previsão e Sharpe têm uma dica que abre com o mouse, com o foco do teclado ou com toque, e o Esc fecha. Em telas estreitas, tudo vira uma coluna, sem rolagem horizontal da página; tabelas longas rolam dentro do próprio painel e as colunas secundárias aparecem só no desktop. O texto de ajuda mais longo fica em seções recolhíveis ("Como ler").

**Arquivos opcionais.** `selection_backtest.parquet`, `forecast.parquet`, `sources.parquet`, `strategy_lab.parquet` e `market_regimes.parquet` podem faltar. Nesse caso, a área correspondente mostra um estado vazio com o comando para gerá-los. O `strategy_lab.parquet` vem de `uv run python research/strategy_lab.py`.

**Conferência.** Ao ler, o painel verifica se `daily_signals.parquet` e `recommendation.parquet` são da mesma execução e se a soma dos aportes cabe no orçamento. Se algo não bater, ele mostra um erro em vez de números inconsistentes.

As decisões visuais (cores, tipografia e componentes) estão em [frontend/DESIGN.md](../frontend/DESIGN.md).

---

## Registrar compras e vendas

O painel acompanha o que **você** comprou e diz, para cada posição, SEGURAR ou VENDER, com o motivo (STOP, TENDENCIA ou MERCADO; veja [strategies.md](strategies.md#regras-de-venda-suas-posições-e-backtest)).

### Pelo painel

Em **Visão geral → Suas posições**:

- **Registrar uma compra:** escolha a moeda, confira o preço pago (vem preenchido com o último fechamento) e informe a quantidade e a data.
- **Já vendi:** em cada ficha, informe o preço e a data da venda. A posição passa para "Vendas que você registrou", com o resultado.
- **Apagar registro:** só para corrigir um registro errado.

O painel grava por uma rota local do `npm run dev` (`frontend/server/positionsApi.ts`). Essa rota chama o mesmo comando do terminal e só aceita pedidos vindos da própria página. O build estático (`npm run build`) não tem essa rota.

### Pelo terminal

```bash
uv run python -m src.positions add BTC/USDT 83000 0.01                  # compra de 0,01 BTC a 83.000 USDT, hoje
uv run python -m src.positions add BTC/USDT 83000 0.01 --date 2026-10-01 # compra em outra data
uv run python -m src.positions list                                     # lista as posições
uv run python -m src.positions close <id> 95000                         # registra a venda (aceita --date)
uv run python -m src.positions remove <id>                              # apaga um registro errado
```

Os preços são em USDT, como os pares da Binance. Cada comando atualiza os arquivos do painel na hora, sem internet; recarregue a página. As posições ficam em `data/positions/positions.parquet`, só no seu computador. A moeda precisa estar em `UNIVERSE` (`src/config.py`).

---

## Problemas comuns

| Sintoma | Causa provável | Solução |
|---|---|---|
| Painel mostra "Ainda não há dados para mostrar" | O pipeline ainda não rodou, ou falta um arquivo obrigatório (por exemplo, `recommendation.parquet` de uma versão anterior) | `uv run python -m src.pipeline` e recarregue |
| Painel mostra erro de recomendação inconsistente | Arquivos em `frontend/public/` de execuções diferentes | Rode o pipeline de novo (pode ser `--offline`) e recarregue |
| O localhost não abre ou mostra outra coisa | O painel não está rodando ou subiu em outra porta | Rode `npm --prefix frontend run dev` e use o endereço da linha `Local:` |
| Posição nova não aparece | Página em cache | Recarregue a página |
| Nenhum alerta de virada | Não houve mudança de estágio em relação ao dia anterior | Normal. Os alertas só aparecem quando algo muda. |
| "Aporte sugerido: R$ 0" por muitos dias | Mercado defensivo (BTC abaixo da SMA 200) ou nenhuma moeda passa nos filtros | Esperado: a regra manda ficar de fora. Os motivos aparecem na aba Seleção. |
| Moeda "fora da análise" | Sem candles na base, histórico menor que um ano ou volume baixo | Rode o pipeline online. Moedas novas entram quando completam o histórico. |
| Moeda aparece como "Sem dados confiáveis" | Dado desatualizado ou histórico curto; o motivo aparece na tabela | Rode `uv run python -m src.pipeline`. Se a fonte falhou, veja `data/market/source_log`. |
| `HTTP 451` da Binance | Bloqueio regional da `api.binance.com` | Defina `BINANCE_API_HOST=https://data-api.binance.vision` ou rode de uma região atendida. No GitHub Actions, o workflow já tenta os dois hosts. |
| `--notify` termina com código 2 | Faltam `TELEGRAM_BOT_TOKEN` ou `TELEGRAM_CHAT_ID`, ou o envio falhou | Veja [telegram.md](telegram.md#criar-o-bot-e-testar) |

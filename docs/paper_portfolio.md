# Carteiras simuladas da IA (sem dinheiro real): regras fixadas antes do primeiro dia

Objetivo: acompanhar, com dados novos, o que os modelos de IA em sombra (`docs/ml_study.md`) fariam, sem dinheiro real e
sem afetar a recomendação. Nenhuma ordem é enviada a corretora; o sistema não tem integração com corretora.

## Como funciona (`src/transformers/paper_portfolio.py`)

- **Início:** no primeiro dia com previsão registrada em `model_predictions.parquet` (repositório de estado). Só dados
  posteriores à implantação: nada do passado entra no placar.
- **Compra simulada:** todo dia, cada modelo "compra" as 5 moedas de maior probabilidade com 1/30 do capital
  fictício (uma fatia por dia), dividido igualmente entre elas.
- **Venda simulada:** cada fatia fica 30 dias (o horizonte que o modelo prevê) e sai.
- **Execução:** motor único (`backtest_engine`): decisão no fechamento, execução na abertura seguinte, com taxa,
  spread e slippage; sem alavancagem; o que não está em fatia fica em caixa.
- **Referências, com a mesma regra de fatias:** MERCADO (todas as moedas do universo do dia) e MOMENTO 90d (as 5 de
  maior alta de 90 dias).
- **Dia sem previsão** de um modelo (ex.: sem Fear & Greed) não abre fatia; as fatias já abertas seguem.
- O placar é **recalculado a cada execução** a partir do registro imutável e dos preços: qualquer um reproduz o mesmo
  número.

## Aprender com os erros

- Os modelos são **retreinados todo dia** com tudo o que já tem resultado conhecido. Quando os 30 dias de uma
  previsão terminam, o resultado dela (acertou ou errou) passa a fazer parte do treino.
- O bloco do Telegram mostra o **acerto das previsões já maduras**: quantas das moedas compradas superaram o BTC e
  quanto renderam a mais que o universo.

## Regra de parada (fixada agora, antes de qualquer resultado)

- Status `INICIO` nos primeiros 30 dias e `EM_TESTE` até 182 dias.
- A partir de **182 dias**, se o retorno acumulado da carteira de um modelo ficar **mais de 15 pontos percentuais
  abaixo do MERCADO**, o modelo é marcado `DESCARTADO`. Ele continua registrando previsões, mas deixa de ser candidato.
- **Nenhum status libera compra.** Sair do modo sombra segue `docs/ml_study.md` (365 dias de previsões, mesmo teste) e,
  mesmo assim, só como "em observação".

## Onde acompanhar

- Telegram: mensagem "🧪 IA EM TESTE — SIMULAÇÃO (sem dinheiro real)" depois do resumo do dia.
- Arquivos: `frontend/public/paper_portfolio.parquet` (resumo) e `paper_equity.parquet` (patrimônio diário).

## Limitações

- A simulação usa a abertura do dia seguinte como preço; na prática o preço muda durante o dia.
- Spread e slippage são estimados por faixa de volume, não medidos.
- Meses de dados não provam vantagem: pela conta em `docs/ml_study.md`, uma vantagem de ~2 pp em 30 dias levaria
  muitos anos para ser demonstrada. O placar serve para acompanhar e descartar cedo o que for claramente ruim.

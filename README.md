
Crypto Analyzer

Sistema de análise quantitativa de criptomoedas desenvolvido em Python.
Coleta dados históricos, calcula sinais e indicadores, avalia
estratégias por backtesting e envia resumos pelo Telegram. Inclui um
painel web para consultar o histórico, os resultados e as posições
registradas manualmente.

    Aviso: projeto experimental e educacional. Não executa ordens em
    corretoras e não constitui recomendação financeira. Resultados
    históricos não garantem desempenho futuro.

Funcionalidades

    Dados de mercado: ingestão e armazenamento de candles diários da
    Binance em Parquet.
    Qualidade e rastreabilidade: validação dos dados, registro de
    falhas e identificação das entradas utilizadas em cada execução.
    Sinais e análise: indicadores técnicos, regras de tendência e
    classificação de oportunidades.
    Backtesting: simulação de estratégias com custos configuráveis e
    execução no candle seguinte.
    Gestão de risco simulada: orçamento configurável, limites de
    alocação e acompanhamento manual de posições.
    Notificações: resumo diário opcional pelo Telegram.
    Painel web: visualização de sinais, histórico, resultados de
    estratégias e posições.
    Pesquisa quantitativa: ferramentas para comparar estratégias e
    avaliar a robustez dos resultados.

Tecnologias

    Python 3.12+
    pandas, NumPy e PyArrow
    Parquet para armazenamento de dados
    React, TypeScript, Vite e Tailwind CSS
    pytest e mypy
    uv para gerenciamento do ambiente Python

Arquitetura
Fontes de mercado
      │
      ▼
Ingestão e validação
      │
      ▼
Dados históricos (Parquet)
      │
      ▼
Indicadores e sinais
      │
      ▼
Backtesting e análise de risco
      │
      ├──► Painel web
      └──► Resumo no Telegram

O pipeline Python concentra a coleta e a análise. O frontend consome os
arquivos de dados publicados pelo pipeline; não calcula as recomendações
de forma independente.
Requisitos

    Python 3.12+
    uv
    Node.js 20+ e npm para executar o painel
    Internet para atualizar os dados de mercado

Instalação

Na raiz do repositório:
uv sync
npm --prefix frontend install

Opcionalmente, configure COINGECKO_API_KEY para aumentar o limite de
acesso à API do CoinGecko.
Executar

Atualizar os dados e executar a análise:
uv run python -m src.pipeline

Recalcular usando somente os dados locais:
uv run python -m src.pipeline --offline

Validar a mensagem do Telegram sem enviar nada:
uv run python -m src.pipeline --dry-run

Executar o painel em desenvolvimento:
npm --prefix frontend run dev

Use o endereço local mostrado pelo Vite no terminal. Para gerar o build
de produção:
npm --prefix frontend run build
Telegram

Para habilitar notificações, configure estas variáveis de ambiente:

    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID

Nunca armazene tokens ou chaves diretamente no código, nos arquivos
versionados ou nos logs.
Testes e qualidade

Executar os testes Python:
uv run pytest

Verificar tipagem estrita:
uv run mypy --strict src/ mcp_server.py

Verificar o ambiente Python:
uv lock --check
Configuração

As principais configurações ficam em src/config.py, incluindo o
universo de moedas, filtros, parâmetros de tendência, orçamento simulado
e premissas de custo. Confira os valores atuais no código antes de
executar uma análise.
Limitações

    O mercado de criptomoedas é volátil; perdas substanciais são
    possíveis.
    Backtests dependem das premissas de execução, dos custos e da
    qualidade dos dados.
    Spread e slippage podem ser estimados, não necessariamente
    observados.
    A disponibilidade e a cobertura histórica das fontes variam; o
    universo histórico pode não representar todos os ativos que existiam
    em cada período.
    Resultados exploratórios não são prova de vantagem estatística nem
    garantia de rentabilidade.
    O projeto não envia ordens para corretoras.

Estrutura do projeto
src/
  extractors/       # Adaptadores das fontes de dados
  transformers/     # Indicadores, sinais, seleção e backtesting
  loaders/          # Persistência e leitura de dados
  pipeline.py       # Orquestração da execução
  config.py         # Configuração
research/            # Experimentos e estudos quantitativos
frontend/            # Painel React/TypeScript
tests/               # Testes automatizados
docs/                # Metodologia, arquitetura e progresso técnico

Consulte docs/ para detalhes metodológicos e decisões de
implementação. O README mantém apenas as informações necessárias para
entender, instalar e executar o projeto.

Pesquisa quantitativa (dados point-in-time, motor de backtest de referência, validação estatística e a validação do COMPRAR por moeda): [docs/pesquisa_quantitativa.md](docs/pesquisa_quantitativa.md) e [docs/signal_validation.md](docs/signal_validation.md).

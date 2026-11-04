
Crypto Analyzer

Sistema de análise quantitativa de criptomoedas desenvolvido em Python.
Coleta dados históricos, calcula sinais e indicadores, avalia
estratégias por backtesting e envia resumos pelo Telegram. Inclui um
painel web somente leitura para consultar sinais, carteiras simuladas,
pesquisa, mercado e metodologia.

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
    alocação e carteiras simuladas quando os Parquets existem.
    Notificações: resumo diário opcional pelo Telegram.
    Painel web: sinais, carteiras, mercado, pesquisa e metodologia,
    sempre somente leitura.
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
      ├──► API somente leitura ──► Painel web
      └──► Resumo no Telegram

O pipeline Python concentra a coleta e a análise. A API FastAPI lê os
Parquets publicados e o frontend React consome essa API; nenhum dos dois
calcula recomendações de forma independente nem envia ordens.
Requisitos

    Python 3.12+
    uv
    Node.js 20+ e pnpm 10 (via npx)
    Internet para atualizar os dados de mercado

Instalação

Na raiz do repositório (crypto-analyzer):
uv sync
cd frontend
npx --yes pnpm@10 install
cd ..

Opcionalmente, configure COINGECKO_API_KEY para aumentar o limite de
acesso à API do CoinGecko.
Executar

Atualizar os dados e executar a análise:
uv run python -m src.pipeline

Recalcular usando somente os dados locais:
uv run python -m src.pipeline --offline

Validar a mensagem do Telegram sem enviar nada:
uv run python -m src.pipeline --dry-run

Atalho: sobe API e painel juntos e abre o navegador:
uv run run.py

Variações:
uv run run.py --no-browser        # sem abrir o navegador
uv run run.py --prod              # usa o build e serve tudo em :8000
uv run run.py --prod --build      # gera o build antes de servir

O modo padrão usa Vite em http://localhost:5173 com proxy para a API em
:8000. O modo `--prod` gera o build quando necessário e a API serve
frontend/dist na mesma origem. Para executar manualmente, use
`uv run python -m src.api` e `npx --yes pnpm@10 dev` dentro de frontend/.
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
uv run mypy --strict src/ mcp_server.py run.py

Verificar o ambiente Python:
uv lock --check

Verificar o frontend:
cd frontend
npx --yes pnpm@10 typecheck
npx --yes pnpm@10 test
npx --yes pnpm@10 build
npx --yes pnpm@10 e2e
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
run.py               # Atalho para subir API e painel
src/
  api/              # API FastAPI somente leitura para o painel
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

Sinais de entrada (desde 2026-10-17 o COMPRAR depende do sinal, não da moeda): protocolo, resultado e uso no produto em [docs/entry_signals.md](docs/entry_signals.md). Resultado atual: nenhum sinal validado, então nenhuma moeda mostra COMPRAR; o score de seleção (E) fica em observação como promissor.

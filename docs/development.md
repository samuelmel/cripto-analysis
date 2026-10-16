# Desenvolvimento

Como testar, verificar tipos e mudar o projeto sem quebrar as regras que o sustentam.

## Regras do projeto

As regras completas estão em [CLAUDE.md](../CLAUDE.md). Código que viola uma delas não entra em commit. Em resumo:

1. **I/O separado da lógica.** Regras de negócio são funções puras em `src/transformers/`: não acessam rede, disco, relógio, variáveis de ambiente nem estado global. Rede fica em `extractors/` (só em `fetch`) e `notifiers/`, disco em `loaders/`, e o resto nos entrypoints. "Hoje" é sempre um parâmetro injetado.
2. **Tipagem estrita.** Python com anotações completas, `from __future__ import annotations` e aprovado em `mypy --strict`. `Any` só no payload bruto de `fetch`. TypeScript com `strict` e `noUncheckedIndexedAccess`, sem `any` nem `@ts-ignore`.
3. **Parquet em todas as camadas.** Nada de CSV ou JSON como armazenamento. A saída do painel usa compressão snappy, com escrita atômica (`.tmp` → `replace`) feita só por um loader. Se o pipeline falhar, o arquivo anterior fica intacto.
4. **Schema sincronizado.** Mudar uma coluna de `daily_signals.parquet` exige atualizar o tipo em `frontend/src/types/signals.ts` no mesmo commit.

## Comandos

```bash
uv sync                                # dependências Python, incluindo as de desenvolvimento
uv run pytest                          # testes
uv run mypy --strict src/              # tipagem estrita do Python
npm --prefix frontend install          # dependências do painel
npm --prefix frontend run typecheck    # tipagem do painel (app e config do Vite)
npm --prefix frontend run build        # typecheck + build de produção em frontend/dist
npm --prefix frontend run dev          # painel em modo de desenvolvimento
```

Em 2026-10-15, os quatro comandos de verificação passaram: 151 testes, `mypy --strict` sem erros em 33 arquivos e `tsc` sem erros.

Não existe um workflow de CI que rode esses testes a cada push. O único workflow, `daily.yml`, executa o pipeline diário.

## Testes

- **Sem rede.** Um teste que tentar abrir conexão falha (`tests/conftest.py`).
- **O que cobrem:** a fronteira da SMA 200, o filtro do BTC, o STOP, posições encerradas, o pipeline `--offline`, API indisponível, timeout, resposta incompleta, dado desatualizado, a seleção (filtros, score, classificação e invariantes do aporte), a mensagem do Telegram (conteúdo, divisão, segredos), a previsão e o laboratório.

| Arquivo | Tema |
|---|---|
| `test_strategy.py` | Regra SMA 200, alertas e regras de venda |
| `test_selection.py` | Seleção, score, aporte e contrato da recomendação |
| `test_data_quality.py` | Auditoria dos candles, disponibilidade e universo |
| `test_extractors.py`, `test_http.py` | Adaptadores, hosts permitidos, timeout e retry |
| `test_notifications.py` | Formatação, validação e envio da mensagem |
| `test_forecast.py`, `test_lab.py` | Previsão walk-forward e laboratório de estratégias |
| `test_pipeline.py` | Pipeline de ponta a ponta, offline |
| `test_regimes.py` | Regimes de mercado: causalidade, dados ausentes, reprodutibilidade, integração e contrato com o frontend |

## Mudanças comuns

### Ajustar um parâmetro

Todos ficam em `src/config.py`. A lista completa está em [strategies.md](strategies.md#4-parâmetros). Depois de mudar, recalcule sem baixar nada:

```bash
uv run python -m src.pipeline --offline
```

> [!WARNING]
> Pesos e limiares da seleção foram fixados **antes** do período de teste. Ajustá-los olhando para o resultado do teste invalida o teste. Use treino e validação (`research/selection_study.py`) para comparar alternativas.

### Incluir ou excluir uma moeda

- **Incluir:** acrescente o par em `UNIVERSE` (`"XYZ/USDT": "<id no CoinGecko>"`) e rode o pipeline online para baixar o histórico. Ela só é analisada depois de ter `MIN_HISTORY_DAYS` (365) candles.
- **Excluir da análise:** use `EXCLUDED_BASES`, com o motivo, ou tire o par de `UNIVERSE`.
- **Excluir só da compra:** use `BUY_BLOCKLIST`.

### Mudar uma coluna publicada

1. Altere o schema no transformer (`SELECTION_SCHEMA`, `ALLOCATION_SCHEMA` ou o contrato em `recommendation.py`).
2. Atualize o tipo em `frontend/src/types/signals.ts` e a validação em `frontend/src/data/loadSignals.ts`.
3. Rode `pytest`, `mypy --strict` e `typecheck` antes do commit.

## Frontend

- **Stack:** React 19, TypeScript, Vite, Tailwind CSS 4, `lightweight-charts` nos gráficos e `hyparquet` para ler Parquet no navegador.
- **Organização:** componentes em `frontend/src/components/` não fazem `fetch`. O carregamento fica em `frontend/src/data/loadSignals.ts`, e os cálculos e textos ficam em funções puras de `frontend/src/data/`.
- **Rota local de posições:** `frontend/server/positionsApi.ts` só existe no `npm run dev` e só aceita pedidos da própria página.
- **Design:** cores, tipografia e componentes estão em [frontend/DESIGN.md](../frontend/DESIGN.md).

## Arquivos que não vão para o Git

Definidos em [`.gitignore`](../.gitignore) e [`frontend/.gitignore`](../frontend/.gitignore): `data/`, `logs/`, `frontend/public/*.parquet`, `frontend/node_modules/`, `frontend/dist/`, `.venv/`, `.env` e `.env.*`, arquivos `*.tmp` e caches do Python. Nunca versione tokens nem chaves de API.

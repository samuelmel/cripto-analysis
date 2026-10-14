# crypto-analyzer — diretrizes inegociáveis

Valem para todo código novo ou alterado. Código que viola uma regra não entra em commit.

## 1. Separação estrita entre I/O e regras de negócio

- Regra de negócio (indicadores, filtros, scores, sinais, agregações) é função pura: recebe DataFrames/valores e devolve DataFrames/valores. Não acessa rede, disco, relógio (`datetime.now`), variáveis de ambiente nem estado global.
- I/O existe apenas na borda:
  - `src/extractors/` — somente em `fetch` (rede). `to_frame` e `standardize` são puros.
  - `src/loaders/` — escrita de arquivos.
  - Entrypoints (`src/pipeline.py`, `mcp_server.py`, CLIs) — orquestram e injetam parâmetros.
- `src/transformers/` não importa `aiohttp`, `ccxt`, `os`, `pathlib` nem funções de leitura/escrita de `pandas`/`pyarrow`.
- A data de referência ("hoje") é parâmetro, sempre injetado pelo entrypoint.
- Frontend: componentes React não fazem `fetch`. Carregamento fica em um módulo de dados; cálculos e formatação em funções puras testáveis.

## 2. Tipagem obrigatória

**Python**
- Anotações completas em todo parâmetro e retorno, inclusive `-> None`; `from __future__ import annotations` em todo módulo.
- `Any` só é permitido no payload bruto retornado por `fetch`. Regra de negócio nunca recebe nem devolve `Any`.
- Schemas de DataFrame são declarados (`value_columns`, `KEY_COLUMNS`), não implícitos.
- O código deve passar em `mypy --strict`.

**TypeScript**
- `tsconfig.json` com `"strict": true` e `"noUncheckedIndexedAccess": true`.
- Proibido `any`, `as any`, `@ts-ignore` e `@ts-expect-error`. Para dado externo, use `unknown` e valide.
- O tipo de uma linha de `daily_signals.parquet` é declarado em um único módulo e espelha o schema do Python.

## 3. Saída do pipeline: sempre Parquet

- Toda execução bem-sucedida do pipeline Python termina gravando o estado final em `frontend/public/daily_signals.parquet`.
- Formato sempre Parquet, em toda camada: dados brutos, intermediários e saída. Proibido CSV ou JSON como armazenamento ou como entrega ao frontend.
- A saída usa compressão `snappy` (lida no navegador sem codec extra).
- A escrita é atômica (`.tmp` → `replace`) e feita apenas por um loader em `src/loaders/`. Se o pipeline falhar, o arquivo anterior permanece intacto.
- Mudança de coluna em `daily_signals.parquet` atualiza o tipo TypeScript correspondente no mesmo commit.
- `daily_signals.parquet` é artefato gerado e não é versionado.

# Painel do Crypto Analyzer

Painel em React + TypeScript que lê os arquivos Parquet gravados pelo pipeline em `public/`.

```bash
npm install          # nesta pasta, ou npm --prefix frontend install na raiz
npm run dev          # painel em http://localhost:5173 (endereço exato na linha "Local:")
npm run typecheck    # tipagem estrita
npm run build        # typecheck + build de produção em dist/
```

Rode o pipeline antes (`uv run python -m src.pipeline`, na raiz). Sem os arquivos, o painel mostra "Ainda não há dados para mostrar".

- Uso das abas e registro de posições: [docs/usage.md](../docs/usage.md)
- Organização do código e regras: [docs/development.md](../docs/development.md#frontend)
- Contrato visual: [DESIGN.md](DESIGN.md)

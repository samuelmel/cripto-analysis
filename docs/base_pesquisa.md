# Base de pesquisa (branch `base-pesquisa`)

O histórico diário de todas as moedas que já negociaram na Binance desde 2017, inclusive as deslistadas, usado pelos
estudos (`research/`). O pipeline diário não depende dela: ele baixa só as moedas de `config.UNIVERSE`.

| Pasta | Conteúdo | Origem |
|---|---|---|
| `archive/` | 676 pares em USDT (vivos e deslistados), manifesto com SHA-256 de cada ZIP, catálogo, log de sincronização, universo point-in-time | `python -m src.archive sync --all` |
| `archive_bitstamp/` | candles diários da Bitstamp em USD: BTC desde 2011-08-18, ETH, LTC e XRP (API pública oficial) | `research/build_bitstamp.py` (só no Actions: a Bitstamp não é acessível do ambiente de desenvolvimento) |
| `archive_btc/` | os pares em BTC que começaram antes do par em USDT da mesma moeda (ou que nunca tiveram par em USDT) | `research/build_btc_pairs.py` |

## Onde fica e quanto custa

Na branch `base-pesquisa` do próprio repositório (privada como ele, sem custo). A branch tem **um único commit**,
substituído a cada atualização, então não acumula histórico: o tamanho é o da base atual (~75 MB em 2026-10). Ela
não vai para o seu PC a menos que você peça.

## Atualização

Automática, no dia 2 de cada mês (`.github/workflows/base-pesquisa.yml`), ou na hora pela aba Actions → "Base de
pesquisa" → Run workflow. É incremental: só baixa o que é novo. Se um par falhar, nada é publicado e a base anterior
continua lá.

## Restaurar (aqui, no PC ou em qualquer máquina)

```bash
git fetch origin base-pesquisa
git archive origin/base-pesquisa | tar -x -C data/
```

Cria `data/archive/`, `data/archive_btc/` e `data/archive_bitstamp/`. Para conferir: `uv run python -m src.archive status` mostra o fingerprint.

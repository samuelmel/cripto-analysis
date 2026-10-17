# Continuidade das séries de preço: critério de limpeza (fixado antes de refazer qualquer retorno)

Escrito e commitado antes de refazer os testes (`docs/signal_validation.md`, `docs/pooled_validation.md`) com a base
corrigida. A justificativa é **só qualidade de dado**; o efeito sobre o resultado dos testes não entra no critério.

## Problema

Um par da Binance pode mudar de ativo sem mudar de nome: relançamento depois de um colapso (`LUNA/USDT`, maio de 2022),
migração de contrato, redenominação. Os candles ficam em sequência, mas o preço antes e depois **não é do mesmo ativo**.
Calcular retorno, SMA 200 ou referência atravessando essa emenda inventa um ganho ou uma perda que ninguém teve. Foi o
que o teste agregado expôs (`LUNA/USDT`: média de +12.339% em 30 dias de "dia aleatório").

Honestidade sobre a origem: o defeito foi descoberto olhando o resultado de um teste. Para o critério não ser ajustado ao
resultado, os limiares abaixo foram escolhidos por argumento de mercado e fixados vendo apenas **a qualidade da série**
(lacunas entre candles e variação de um dia para o outro em toda a base de 683 pares), sem nenhum retorno de sinal.
Nessa inspeção: 14 pares têm lacuna (todas de 3 dias ou mais, de 3 a 311 dias) e 3 variações de dia único passam de 10×
para cima; as maiores quedas de dia único (até −99,97%) ocorrem sem lacuna.

## Critério (versão `continuidade-v1`)

Percorre-se cada par em ordem cronológica. Uma **quebra** ocorre entre o candle `i-1` e o candle `i` se:

1. **Lacuna**: há 2 ou mais candles diários ausentes seguidos (`i` está 3 dias ou mais depois de `i-1`).
   Razão: uma negociação suspensa por dias é, na prática, outro regime (halt, migração, relançamento); 1 candle ausente
   (2 dias) é tolerado como falha de coleta.
2. **Salto para cima**: o fechamento sobe mais de **10 vezes** (+900%) de um dia para o outro. Nenhum ativo líquido do
   universo faz isso organicamente; é troca de ativo ou erro de dado.

**Queda grande não é quebra.** Uma queda de 99,97% em um dia (`LUNA/USDT`, 12/05/2022) é perda real de quem tinha a
moeda; removê-la seria viés de sobrevivência. Variações de dia único abaixo do limiar (por exemplo +5×) também ficam: são
mercado.

## Tratamento

- Cada quebra **divide o par em segmentos**. O segmento seguinte é um instrumento novo (`SIMBOLO#2`, `#3`...), com
  histórico próprio: SMA 200, histórico mínimo do universo e média de volume recomeçam do zero nele. Nada atravessa a emenda.
- O segmento anterior termina no último candle antes da quebra e segue a regra que já existe para moeda que parou de
  negociar: sai ao último preço, sem inventar perda total nem ganho.
- Os arquivos brutos da base (`data/market/pit/`) **não são alterados**. A limpeza é uma etapa pura aplicada na leitura
  (`src/transformers/series_continuity.py`), para ser reversível e auditável. `clean_candles` e o pipeline diário não mudam.
- O relatório de quebras (par, dia, dias de lacuna, razão de preço, motivo) é gravado em
  `evidence/continuity_report.parquet`.

## Versão e registro

- Versão do critério: `CONTINUITY_VERSION = "continuidade-v1"` (em `config.py`), gravada na configuração de cada
  experimento; o `classifier_version` dos novos experimentos termina em `+continuidade-v1`. IDs novos, linhas novas
  no `evidence/validation_registry.parquet`; **as linhas anteriores permanecem**.
- Os testes refeitos são o por moeda (antes `c50af63e6e99f77f`) e o agregado (antes `e1c394add0e9d0ba`), ambos com ID novo.
- Nenhuma outra regra muda: horizontes, custos, α, `N_MIN = 12`, hold-out em 2025-01-01, sementes e critérios de
  validação são os mesmos. `N_MIN` **não** é refeito com as novas contagens.
- O teste final por moeda é avaliado uma terceira vez (as duas primeiras foram a mesma execução repetida), agora com
  `--allow-second-holdout`, porque o dado mudou; a regra de que ele só revoga continua. Fica registrado.
- Os arquivos de produção (`evidence/signal_evidence.parquet`, cópia no frontend) **não são sobrescritos** por esta
  etapa: os resultados refeitos vão para `evidence/continuidade_v1/`. Trocar a evidência usada pelo COMPRAR é decisão
  separada, depois de ver os resultados.

## O que será reportado

Número de pares com quebra, de quebras por motivo, de segmentos criados, de sinais (e sinais independentes) que antes
tinham a janela de retorno atravessando uma quebra e deixaram de existir ou mudaram, e se o veredito de cada teste mudou.


## Resultado da aplicação (2026-10-17, `continuidade-v1`)

Base: 683 pares → 697 instrumentos. O critério foi aplicado como escrito, sem ajuste depois de ver os resultados.

| | |
|---|---|
| Pares com quebra | 14 (um por par) |
| Por motivo | 11 só lacuna; 3 lacuna + salto para cima (LUNA, COCOS, DREP) |
| Segmentos novos | 14 |
| Janelas de referência (dias aleatórios) que atravessavam uma quebra | 4 em 7 dias e 19 em 30 dias (de 82 mil), agora separadas |
| Sinais cuja janela de retorno atravessava uma quebra | 0 nos dois horizontes |
| Sinais independentes de desenvolvimento | 7 dias: 729 → 726; 30 dias: 504 → 503 |
| Moedas com algum sinal | 126 → 126 |

Os 3 sinais de 7 dias e o 1 de 30 dias que sumiram são de moedas cujo segmento novo ainda não tem 200 dias de SMA. O defeito
estava na **referência aleatória** (dias de entrada de 19 janelas que atravessavam a emenda do LUNA e de outros pares),
não nos sinais. Lista completa das quebras: `evidence/continuity_report.parquet`.

### Os vereditos mudaram?

| Teste | Antes | Depois | Mudou? |
|---|---|---|---|
| Por moeda (`c50af63e6e99f77f` → `3fd73c32c408cd76`) | nenhuma validada; 11 `NAO_VALIDADA` | nenhuma validada; as mesmas 11 `NAO_VALIDADA` | **não** (0 moedas com status diferente) |
| Agregado (`e1c394add0e9d0ba` → `c1bcc31eed147488`) | `NAO_DEMONSTRADO` (30 dias: −97,8 pp, artefato) | `NAO_DEMONSTRADO` (7 dias: +0,6 pp, p Holm 0,59; 30 dias: +0,1 pp, IC −7,0 a +7,7 pp, p Holm 0,59) | **não**; o número de 30 dias passou a ser plausível |

O teste final por moeda foi calculado uma terceira vez (`--allow-second-holdout`); como nenhuma moeda foi validada, não
decidiu nada. As linhas antigas do registro foram mantidas. A evidência de produção (`evidence/signal_evidence.parquet`) **não foi
substituída**; os resultados refeitos estão em `evidence/continuidade_v1/`. Como o status de todas as moedas é o mesmo, trocar
não mudaria o que aparece no Telegram nem no painel.

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

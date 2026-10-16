---
version: alpha
name: crypto-analyzer
description: Painel diário que diz, em português simples, o que fazer com cada criptomoeda hoje — para quem não é do mercado e precisa decidir com calma.
colors:
  ground: "#f4f5f2"      # página
  surface: "#fcfcfb"     # blocos e gráfico
  ink: "#121417"         # 16.9:1 no ground
  muted: "#55544f"       # 6.9:1 no ground
  hairline: "#e1e0d9"
  signal: "#1c5cab"      # 6.1:1 — seleção, links, foco, botão principal
  signal-hover: "#184f95"
  signal-active: "#104281"
  series-price: "#2a78d6"
  series-average: "#eb6834"
  series-trend: "#4a3aa7"   # 3ª série (média de 200 dias)
  good: "#006300"        # texto de ganho / SEGURAR · marca #0ca30c
  good-bg: "#e3f1e3"
  critical: "#b42d2d"    # texto de perda / VENDER · marca #d03b3b
  critical-bg: "#f8e5e4"
  warning: "#7a4f00"     # texto de PREPARAR · marca #fab219
  warning-bg: "#fbf0d3"
typography:
  body: { family: "IBM Plex Sans", size: 15px, line-height: 1.55, weights: [400, 500, 600] }
  display: { family: "IBM Plex Sans", size: 28px, weight: 600, letter-spacing: -0.01em }
  figure: { family: "IBM Plex Sans", size: 32px, weight: 500, numeric: proportional }
  table-numbers: { numeric: tabular-nums }
rounded: { sm: 4px, md: 6px }
spacing: { xs: 4px, sm: 8px, md: 16px, lg: 24px, xl: 40px, xxl: 64px }
---

## Overview

Ferramenta pessoal de monitoramento de criptomoedas para uma pessoa que não domina análise técnica. O visual vem do material do próprio produto — tabelas de cotação, gráfico de preço, ficha de operação — na tradição suíça de informação: grade rígida, alinhamento à esquerda, uma família tipográfica em vários pesos, cor só onde carrega significado.

## Colors

- **ground / surface** — cinza-claro neutro (não creme) para a página e quase-branco para blocos; o contraste entre os dois separa áreas sem sombra.
- **ink / muted** — texto principal e secundário, ambos acima de 4.5:1.
- **signal** (azul profundo) — um único trabalho: indicar o que é interativo ou selecionado (moeda escolhida, foco, links).
- **series-price / series-average / series-trend** — azul, laranja e violeta da paleta categórica validada (`validate_palette.js --pairs all`: CVD ΔE ≥ 13, normal ≥ 16, contraste ≥ 3:1, todas as checagens passam). Usados só no gráfico, sempre com legenda e valor do dia ao lado.
- **good / critical / warning** — status. Sempre acompanhados de texto ("Vender", "Segurar", "Ficar de olho"); nunca a cor sozinha. Verde/vermelho também significam ganho/perda em números com sinal + ou −.

## Typography

IBM Plex Sans, self-hosted via @fontsource (400/500/600). Escala: 13 (rótulos de tabela), 15 (corpo), 18 (títulos de seção), 28 (título da página), 32 (números de destaque). Números de destaque em algarismos proporcionais; colunas de tabela em `tabular-nums`. O único lugar "alto" é a frase do bloco "Hoje".

## Layout

Largura máxima de 1120px, alinhada à esquerda, em cinco visões escolhidas por uma navegação em abas: **Visão geral**, **Seleção**, **Histórico**, **Previsões** e **Pesquisa**. Cada visão é uma grade de 12 colunas e espaçamento `lg` entre blocos.

- **Visão geral**, de cima para baixo: faixa da recomendação (5 fatos lado a lado: mercado, orçamento, sugerido, sem investir, dados) → área de avisos → bloco da recomendação de aporte (frase, barra do orçamento, notas, evidência) → cartões das moedas selecionadas (até 3 lado a lado) → tabela das descartadas → regra principal SMA 200 (faixa de estado, o que fazer hoje, cartões de BTC e ETH) → previsão → gráfico → suas posições.
- **Seleção**: ranking completo com componentes do score, backtest da seleção contra as referências e como a seleção decide.
- **Histórico**: todas as moedas e as operações simuladas da moeda escolhida.
- **Previsões**: gráfico com as faixas e a tabela de avaliação contra o preço de hoje.
- **Pesquisa**: comparação de estratégias, laboratório, como funciona e glossário.

Abaixo de 768px tudo vira uma coluna, na mesma ordem. A página nunca rola na horizontal: colunas secundárias das tabelas somem no celular (`hidden md:table-cell`) e a leitura completa fica no desktop. Tabelas ocupam a largura do bloco; números alinhados à direita.

## Elevation & Depth

Plano. Nenhuma sombra. Blocos se separam por fundo (surface sobre ground) e hairline de 1px.

## Shapes

`sm` 4px em etiquetas de status e botões de moeda; `md` 6px em blocos. Nada além disso.

## Components

- **Navegação** — abas em texto sobre uma linha `hairline`; a aba ativa tem sublinhado `signal` de 2px e `aria-selected`. Sem ícones, sem caixa alta.
- **Faixa de estado** — um bloco `surface` com três fatos (estado do mercado, atualização dos dados, data da análise): rótulo `muted` 13px em cima, valor 18px embaixo, divididos por `hairline`.
- **Área de avisos** — separada das recomendações por fundo tint de status (`warning-bg` para pânico e dado velho, `critical-bg` para falha de coleta), ícone Phosphor e título; diz sempre "não é recomendação". Sem avisos, vira uma linha `muted` com um ícone de confirmação.
- **Cartão de moeda** — logo, nome, etiqueta do sinal, preço em `figure`, variação de 24 horas e de 30 dias em `good`/`critical` com sinal, distância da média de 200 dias com a barra de distância e uma frase de razão. Dois lado a lado.
- **Faixa de previsão** — uma linha por horizonte: nome, trilho `ground` com o zero marcado, segmento tracejado de P10 a P90 (borda `series-price` tracejada, preenchimento `series-price` a 15%) e um traço no P50. Sempre rotulada "estimativa". Quando o modelo não vence a referência, vem junto uma etiqueta `warning`: "sem vantagem demonstrada sobre o preço de hoje".
- **Dica de glossário** — o termo com sublinhado pontilhado e um balão `surface` com borda `hairline`, sem sombra; abre ao passar o mouse, ao focar com o teclado e some com Esc; no celular vira uma faixa fixa na base da tela. O texto longo mora em `src/data/glossary.ts`, nunca no cartão.
- **Tooltip do gráfico** — balão `surface` com data, valor e fonte (Binance para preço, "calculada aqui" para médias, "modelo estatístico" para estimativas). Estimativas aparecem tracejadas, com a mesma cor do preço e transparência, e nunca se confundem com o histórico.

- **Recomendação** — o valor sugerido em `figure`, sempre com "Aporte sugerido" e a classificação ao lado; classificação usa `signal` (boa oportunidade relativa), neutro (moderada e evitar) e `warning` (aguardar). **Nunca** `good`/verde para oportunidade: verde sugeriria certeza de ganho. A barra do orçamento usa as cores de série (não de status) e sempre mostra o que fica sem investir.
- **Bloco** — surface, hairline, `md`, padding lg. Um nível só: bloco nunca contém bloco.
- **Etiqueta de status** — texto + fundo tint da cor de status, `sm`, peso 500.
- **Número de destaque** — rótulo em muted acima, valor em figure.
- **Tabela** — cabeçalho em muted 13px peso 500, linhas com hairline, linha selecionável com foco visível.
- **Botão** — principal: fundo signal, texto surface (hover/active escurecem); secundário: hairline; perigo: borda e texto critical; fantasma: só texto. Ícone de 18px à esquerda quando ajuda a reconhecer a ação.
- **Seletor de moeda** — logo + ticker, hairline; selecionado = borda signal e fundo signal-bg.
- **Ícones** — Phosphor, peso regular, sem moldura ou quadradinho; cada ícone tem um significado fixo (escudo = limite de perda, seta de queda = tendência acabou, moeda Bitcoin = mercado virou, olho = ficar de olho, mão com moedas = comprar ou segurar).
- **Logos das moedas** — SVG oficial (cryptocurrency-icons, CC0) em 20–36px, sempre ao lado do ticker.

## Do's and Don'ts

- Do: reutilizar tokens e componentes acima; adicionar token aqui antes de usá-lo.
- Do: escrever como se explica para um amigo: frases curtas, sem jargão sem explicação, sentence case.
- Do: foco visível em tudo que é clicável; respeitar `prefers-reduced-motion`.
- Don't use: fundo preto com verde neon, fonte mono decorativa, rótulos em caixa-alta, separadores "·", setas em botões, numeração 01/02/03, gradientes, glassmorphism, sombras grandes, cartões com faixa colorida na lateral, ícones em quadradinho, animação de contagem.
- Don't change: Parquet como fonte de dados; regras de negócio fora dos componentes (CLAUDE.md).

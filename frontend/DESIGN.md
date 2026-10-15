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

Coluna única de até 1120px, alinhada à esquerda, com seções na ordem das decisões do usuário: o que fazer hoje → suas posições → moedas → detalhe da moeda → a regra funciona? → como funciona. Tabelas ocupam a largura toda; números alinhados à direita.

## Elevation & Depth

Plano. Nenhuma sombra. Blocos se separam por fundo (surface sobre ground) e hairline de 1px.

## Shapes

`sm` 4px em etiquetas de status e botões de moeda; `md` 6px em blocos. Nada além disso.

## Components

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

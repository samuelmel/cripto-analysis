---
version: alpha
name: crypto-analyzer
description: Painel diário de análise quantitativa que diz, em português simples, o que fazer com cada criptomoeda hoje, com a informação essencial na primeira tela.
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
  neutral-mark: "#8a897f"   # faixa de regime lateral e marcas neutras (nunca texto)
typography:
  body: { family: "IBM Plex Sans", size: 14px, line-height: 1.45, weights: [400, 500, 600] }
  title: { family: "IBM Plex Sans", size: 15px, weight: 600, letter-spacing: -0.01em }
  figure: { family: "IBM Plex Sans", size: 22px, weight: 500, numeric: tabular }
  table-numbers: { numeric: tabular-nums }
rounded: { sm: 4px, md: 6px }
spacing: { xs: 4px, sm: 8px, md: 12px, lg: 16px, xl: 24px }
---

## Overview

Ferramenta pessoal de monitoramento e análise quantitativa de criptomoedas. O visual vem do material do próprio produto, as mesas de cotação e os terminais de análise: grade rígida, alta densidade com hierarquia clara, uma família tipográfica em vários pesos, cor só onde carrega significado. A informação que se consulta todo dia cabe na primeira tela de um desktop comum; o resto fica a uma aba, uma seção recolhível ou a uma rolagem interna de distância. A explicação para leigos continua presente, mas recolhida (dicas de glossário e textos "Como ler"), nunca no caminho do número.

## Colors

- **ground / surface** — cinza-claro neutro (não creme) para a página e quase-branco para painéis; o contraste entre os dois separa áreas sem sombra.
- **ink / muted** — texto principal e secundário, ambos acima de 4.5:1.
- **signal** (azul profundo) — um único trabalho: indicar o que é interativo ou selecionado (aba ativa, moeda escolhida, foco, links).
- **series-price / series-average / series-trend** — azul, laranja e violeta da paleta categórica validada (`validate_palette.js --pairs all`: CVD ΔE ≥ 13, normal ≥ 16, contraste ≥ 3:1). Usados no gráfico e na barra do orçamento, sempre com legenda.
- **good / critical / warning** — status. Sempre acompanhados de texto; nunca a cor sozinha. Verde/vermelho também significam ganho/perda em números com sinal + ou −.
- **marcas de regime** — a faixa do tempo dos regimes usa as marcas dos status (`good-mark` alta, `critical-mark` baixa, `warning-mark` misto ou volatilidade alta, `neutral-mark` lateral, `hairline` sem classificação) com legenda de texto ao lado. É descrição experimental: a cor nunca sugere compra ou venda.

## Typography

IBM Plex Sans, self-hosted via @fontsource (400/500/600). Escala: 11 (rótulos de indicador e notas), 12 (cabeçalhos de tabela, legendas, notas de painel), 13 (corpo de tabela e título de painel), 14 (corpo), 15 (título do app), 22 (número de destaque dentro de um painel). Algarismos tabulares (`num`) em tudo que se compara em coluna ou linha.

## Layout

Largura útil de até 1760px, alinhada à esquerda, em **grade de 12 colunas** com espaçamento `md` (12px) entre painéis. O painel nunca rola na horizontal; qualquer conteúdo largo (tabelas, abas) rola **dentro** do próprio painel.

- **Barra superior fixa** (uma linha, 44px): nome do app, as cinco visões como abas, e à direita o estado dos dados: fechamento da análise com o atraso, hora da última coleta, estado da última execução do pipeline e o botão de recarregar os arquivos publicados (não roda o pipeline).
- **Faixa de indicadores** (sempre visível, oito células em uma linha no desktop, quatro no tablet, duas no celular): mercado (regra de risco), regime do BTC (experimental), moedas analisadas, aporte sugerido, posições, regra principal (BTC e ETH), risco do BTC e humor do mercado. Cada célula sai de um campo que o pipeline publica; o que não existe aparece como "—".
- **Faixa de avisos**, logo abaixo; sem avisos, uma linha tranquila.
- **Visão geral** (desktop): coluna esquerda de 8 colunas (gráfico com seletor de moeda e a tabela de moedas com altura limitada) e coluna direita de 4 (recomendação de aporte, regra principal e um painel de apoio com abas: posições, previsão, descartadas). Em telas de 1024px a 1279px as colunas passam a 7 e 5; abaixo disso, uma coluna na mesma ordem.
- **Seleção**: ranking completo (altura limitada, cabeçalho fixo) e, abaixo, o backtest da seleção ao lado de "Como a seleção decide".
- **Histórico**: tabela de todas as moedas ao lado do gráfico e da lista de operações da moeda escolhida.
- **Previsões**: BTC e ETH lado a lado, cada um com gráfico e tabela de avaliação; colunas de detalhe só a partir de 1536px.
- **Pesquisa**: um seletor segmentado escolhe um grupo por vez: regra de tendência, laboratório, regimes (experimental), como funciona e glossário.

Abaixo de 768px tudo vira uma coluna, na mesma ordem. Colunas secundárias das tabelas somem no celular (`hidden md:table-cell`); nada deixa a página rolar na horizontal.

## Elevation & Depth

Plano. Nenhuma sombra. Painéis se separam por fundo (surface sobre ground) e hairline de 1px.

## Shapes

`sm` 4px em etiquetas de status, botões e controles; `md` 6px em painéis. Nada além disso.

## Components

- **Painel** — surface, hairline, `md`. Cabeçalho de uma linha (título 13px peso 600, nota `muted` 12px e ações à direita) separado do corpo por hairline; corpo com padding `md`, ou sem padding quando contém uma tabela. Um nível só: painel nunca contém painel nem cartão com borda própria.
- **Barra superior** — fixa no topo, surface com hairline embaixo. Abas em texto 13px: a ativa tem fundo `signal-bg`, texto `signal` e `aria-selected`; setas do teclado trocam de visão. No celular o conjunto quebra em linhas e as abas rolam dentro da própria faixa.
- **Faixa de indicadores** — células surface divididas por hairline de 1px: rótulo `muted` 11px, valor 13px peso 600 (tom de status quando carrega significado), nota `muted` 11px. Texto cortado mostra o completo no `title`.
- **Faixa de avisos** — uma caixa surface com uma linha por aviso (ícone Phosphor de 16px, título em `warning` ou `critical`, texto `muted`); diz que avisos não são recomendações. Sem avisos, uma linha `muted` com ícone de confirmação.
- **Tabela** — compacta (linhas de 28px, texto 13px), cabeçalho `muted` 12px peso 500 **fixo** durante a rolagem interna, `max-height` por painel, números à direita em tabulares, linha selecionável com foco visível. Colunas secundárias: `narrow: "hide"` (some no celular) e `narrow: "wide"` (só a partir de 1536px).
- **Regra principal** — tabela de BTC e ETH com etiqueta do sinal, preço, variação de 24 horas e 30 dias, distância da média de 200 dias (barra e número) e mini-gráfico de 90 dias; acima dela, a frase de veredito do dia com ícone Phosphor (nunca faixa colorida lateral) e os detalhes recolhidos.
- **Recomendação** — frase de decisão, barra do orçamento (cores de série, sempre mostrando o que fica sem investir) e uma linha por moeda selecionada (classificação, aporte, score e motivo principal); o detalhe (componentes do score, motivos, riscos, indicadores) abre sob demanda. Classificação usa `signal` (boa oportunidade relativa), neutro (moderada e evitar) e `warning` (aguardar). **Nunca** `good`/verde para oportunidade: verde sugeriria certeza de ganho.
- **Faixa de previsão** — uma linha por horizonte: nome, trilho `ground` com o zero marcado, segmento tracejado de P10 a P90 e um traço no P50. Sempre rotulada "estimativa". Quando o modelo não vence a referência, vem junto a etiqueta `warning` "sem vantagem demonstrada".
- **Regimes (experimental)** — células do estado de hoje, faixa do tempo da tendência e da volatilidade (largura proporcional aos dias, legenda de texto, eixo de anos), frequência por regime e as limitações conhecidas. Sempre rotulado experimental e descritivo: não gera sinal e não altera aporte, compra ou venda.
- **Seletor segmentado** — grupo de botões 12px com hairline; o selecionado tem fundo `signal-bg` e `aria-pressed`. Substitui grupos de botões grandes.
- **Recolhível** — `details` com resumo `muted` 13px: o texto longo de ajuda ("Como ler", validação, limitações) fica a um clique, sem ocupar altura.
- **Dica de glossário** — o termo com sublinhado pontilhado e um balão `surface` com borda `hairline`; abre ao passar o mouse, ao focar com o teclado e some com Esc; abre para a esquerda quando o termo está perto da borda direita; no celular vira uma faixa fixa na base da tela. O texto longo mora em `src/data/glossary.ts`.
- **Tooltip do gráfico** — balão `surface` com data, valor e fonte (Binance para preço, "calculada aqui" para médias, "modelo estatístico" para estimativas). Estimativas aparecem tracejadas e nunca se confundem com o histórico. Altura do gráfico controlada pelo painel (260 a 320px).
- **Estados** — carregando: mensagem e esqueleto estático (sem animação) com o formato da página; dados ausentes: painel com o comando do terminal que gera o arquivo; erro: painel com a mensagem; sem dado de uma moeda ou série: "—", nunca zero.
- **Etiqueta de status** — texto + fundo tint da cor de status, `sm`, 12px peso 500.
- **Botão** — principal: fundo signal, texto surface; secundário: hairline; perigo: borda e texto critical; fantasma: só texto. Ícone de 14 a 18px à esquerda quando ajuda a reconhecer a ação.
- **Ícones** — Phosphor, peso regular, sem moldura; cada ícone tem um significado fixo (escudo = limite de perda, seta de queda = tendência acabou, moeda Bitcoin = mercado virou, olho = ficar de olho, mão com moedas = comprar ou segurar).
- **Logos das moedas** — SVG oficial (cryptocurrency-icons, CC0) em 18 a 30px, sempre ao lado do ticker.

## Do's and Don'ts

- Do: reutilizar tokens e componentes acima; adicionar token aqui antes de usá-lo.
- Do: escrever como se explica para um amigo: frases curtas, sem jargão sem explicação, sentence case; o texto longo vai em recolhível ou glossário.
- Do: foco visível em tudo que é clicável; respeitar `prefers-reduced-motion`; altura limitada e rolagem interna em tabelas longas.
- Don't use: fundo preto com verde neon, fonte mono decorativa, rótulos em caixa-alta, separadores "·", setas em botões, numeração 01/02/03, gradientes, glassmorphism, sombras grandes, cartões com faixa colorida na lateral, ícones em quadradinho, animação de contagem.
- Don't change: Parquet como fonte de dados; regras de negócio fora dos componentes (CLAUDE.md).

# Crypto Analyzer — sistema visual

Painel quantitativo somente leitura. A interface existe para responder o que os dados publicados mostram, com que
confiança e o que continua indisponível. Nenhuma tela sugere ordem real, promessa de retorno ou certeza.

## Princípios

- **Decisão primeiro, densidade depois.** A Visão geral abre com a decisão publicada e o orçamento; tabelas e detalhes
  vêm abaixo.
- **Dados reais ou estado explícito.** Valor ausente vira "Indisponível", nunca zero, média ou estimativa inventada.
- **Terminal editorial, não dashboard genérico.** Tipografia, tabelas, hairlines e gráficos no lugar de uma grade de
  cartões coloridos.
- **Cor só quando carrega significado.** Teal marca ação e seleção; verde e vermelho marcam sinal e variação; âmbar
  marca atenção e defasagem.
- **Leitura confortável em qualquer largura.** Conteúdo ocupa a tela; abaixo de `lg` a navegação vira barra inferior.

## Tokens

Definidos em `src/index.css` (`@theme`) e usados como classes Tailwind.

| Token | Valor | Uso |
|---|---|---|
| `ground` | `#f3f2ed` | fundo da página |
| `surface` | `#fbfaf7` | painéis e barras |
| `raised` | `#ffffff` | controles e superfícies elevadas |
| `sunken` | `#ebe9e2` | hover, esqueletos e faixas |
| `ink` | `#151613` | texto principal |
| `muted` | `#5d5c55` | texto secundário |
| `faint` | `#8a887e` | rótulos e metadados |
| `hairline` | `#dcdad1` | bordas de 1px |
| `hairline-strong` | `#c7c4b8` | bordas de controles |
| `signal` | `#0d6b63` | links, seleção, ação principal |
| `signal-deep` | `#094d47` | hover e texto sobre lavagem |
| `signal-wash` | `#e2efec` | fundo selecionado |
| `good` / `good-wash` | `#176a3a` / `#e4f0e8` | ganho, estado positivo |
| `critical` / `critical-wash` | `#a43131` / `#f6e5e3` | perda, erro, risco |
| `warning` / `warning-wash` | `#7c5300` / `#f7eed6` | atenção, defasagem |
| `series-1..4` | teal, terracota, violeta, azul | séries de gráfico |

Raios: `sm` 4px, `md` 7px, `lg` 12px. A sombra `float` é reservada a sobreposições, não a painéis.

## Tipografia

IBM Plex Sans (400/500/600) para texto e títulos; IBM Plex Mono (400/500) para números, datas, tickers e valores
tabulares via `.num`. Títulos usam `.display` com `letter-spacing` negativo. Escala principal: 10–11px para rótulos,
12–13px para corpo e tabelas, 14–15px para títulos de seção, 22px para números de destaque e 24–40px para o hero.

## Layout

- **Desktop (`lg`+):** sidebar fixa de 236px, topbar sticky de 48px, conteúdo com padding lateral de 24–40px e largura
  total disponível. Sem coluna central estreita.
- **Mobile:** topbar compacta com marca e status; barra inferior fixa com cinco destinos; conteúdo em uma coluna.
- Grades usam `min-w-0` nos filhos para que gráficos e tabelas rolem dentro do painel, nunca na página.
- Tabelas longas têm rolagem interna e cabeçalho fixo; colunas secundárias desaparecem no celular.

## Componentes

- **Panel:** superfície `surface` com borda `hairline` e raio `md`. É o único nível de container; não aninha painéis.
- **SectionHeader:** eyebrow em teal, título `.display` e descrição curta; ações alinhadas à direita.
- **Badge:** texto + tom + ponto opcional. O ponto nunca substitui o texto.
- **Button:** primário teal, secundário com borda, fantasma sem borda. Altura de 36px e foco visível.
- **Stat:** rótulo em caixa alta, número mono de 22px e nota. Tom semântico apenas quando o dado justifica.
- **InlineNote:** faixa com borda esquerda de 2px para ressalvas, defasagem e limitações.
- **LoadingBlock / EmptyState / ErrorState:** estados explícitos, com rótulo acessível e ação de nova tentativa quando
  aplicável.
- **SegmentedTabs:** Radix Tabs; setas do teclado mudam a aba, estado ativo em `signal-wash`.
- **Hint:** Radix Tooltip para explicar termos sem esconder o número principal.
- **Gráficos ECharts:** linha de preço, performance, faixa P10–P90 e sparkline. Séries sempre legendadas; estimativas
  tracejadas e visualmente distintas do histórico.

## Acessibilidade

- Foco visível global de 2px em teal.
- Contraste mínimo de 4.5:1 para texto e 3:1 para elementos de interface.
- `aria-current`, `aria-selected`, `role="status"` e rótulos em ícones de navegação.
- `prefers-reduced-motion` desliga animações e transições.
- Navegação completa por teclado; tabelas mantêm cabeçalhos semânticos.

## Evitar

- Fundo preto com verde neon, gradientes, glassmorphism e sombras pesadas.
- Cartões com faixa colorida lateral, excesso de cards e números sem contexto.
- Verde para oportunidade ou previsão de alta; cor nunca promete retorno.
- Truncar valores sem indicar unidade, data ou fonte.
- Mostrar "R$ 0" quando a cotação ou o Parquet está ausente.

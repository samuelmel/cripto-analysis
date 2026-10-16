/** Termos do painel em português simples: o texto longo mora aqui, nos cartões só aparece o termo com dica. */
export type TermId =
  | "sma200" | "tendencia" | "drawdown" | "volatilidade" | "faixa" | "sharpe" | "baseline"
  | "score" | "momento" | "forca" | "persistencia" | "liquidez" | "regime" | "aporte" | "teorica" | "custo" | "classificacao";

export interface GlossaryEntry {
  readonly label: string;
  readonly text: string;
}

export const GLOSSARY: Readonly<Record<TermId, GlossaryEntry>> = {
  sma200: {
    label: "Média de 200 dias (SMA 200)",
    text: "Média dos últimos 200 fechamentos do preço. Se o preço está acima dela, a tendência é de alta.",
  },
  tendencia: {
    label: "Tendência",
    text: "Direção geral do preço no médio prazo. Aqui, está em alta quando o preço fecha acima da média de 200 dias.",
  },
  drawdown: {
    label: "Pior queda (drawdown)",
    text: "Quanto a carteira chegou a perder do topo até o fundo no período. Mostra o sufoco que você teria passado.",
  },
  volatilidade: {
    label: "Volatilidade",
    text: "O quanto o preço costuma balançar. Quanto maior, mais larga e mais incerta é a faixa de previsão.",
  },
  faixa: {
    label: "Faixa de previsão",
    text: "De P10 a P90: onde o retorno deve ficar em 8 de cada 10 vezes, segundo o modelo. É estimativa, não garantia. P50 é o valor do meio.",
  },
  sharpe: {
    label: "Sharpe",
    text: "Retorno por unidade de risco. Acima de 1 é bom, abaixo de 0,5 é fraco. Serve para comparar estratégias, não para prever.",
  },
  baseline: {
    label: "Preço de hoje (referência)",
    text: "A régua mínima: dizer que amanhã o preço será o de hoje, com ruído. Se o modelo não vence essa referência, ele não ensina nada.",
  },
  score: {
    label: "Score (nota relativa)",
    text: "Nota de 0 a 100 que compara a moeda com as outras analisadas no mesmo dia, somando momento, persistência, risco e liquidez com pesos fixos. Não é chance de lucro.",
  },
  momento: {
    label: "Momento (momentum)",
    text: "Quanto o preço subiu em 30 e 90 dias, descontada a oscilação normal da moeda. Subir não basta: moeda esticada demais fica em aguardar.",
  },
  forca: {
    label: "Força relativa",
    text: "Se a moeda subiu mais ou menos que o Bitcoin e que as outras moedas no mesmo período.",
  },
  persistencia: {
    label: "Persistência da tendência",
    text: "Em quantos dos últimos 50 dias o preço ficou acima da média de 200 dias. Tendência firme muda menos de ideia.",
  },
  liquidez: {
    label: "Liquidez",
    text: "Quanto dinheiro a moeda negocia por dia. Pouca liquidez = diferença maior entre preço de compra e de venda e preço mais fácil de manipular.",
  },
  regime: {
    label: "Estado do mercado",
    text: "Lido pelo Bitcoin. Defensivo (Bitcoin abaixo da média de 200 dias) bloqueia compras novas, por mais alto que seja o score de outra moeda.",
  },
  aporte: {
    label: "Aporte sugerido",
    text: "Quanto do orçamento o modelo colocaria na moeda. Moeda que oscila mais recebe menos. A soma nunca passa do orçamento, e pode ser zero.",
  },
  teorica: {
    label: "Alocação teórica",
    text: "Quanto o modelo colocaria sem o limite do seu orçamento. Quando passa do orçamento, todas as moedas são reduzidas na mesma proporção.",
  },
  custo: {
    label: "Custo estimado",
    text: "Taxa da corretora, diferença entre preço de compra e venda (spread) e escorregão de preço (slippage), na ida e na volta. É estimativa.",
  },
  classificacao: {
    label: "Classificação",
    text: "Boa oportunidade relativa, moderada, aguardar ou evitar entrada. Diz como a moeda está contra as alternativas e os filtros de risco; não é garantia.",
  },
};

export const GLOSSARY_ORDER: readonly TermId[] = [
  "aporte", "classificacao", "score", "regime", "momento", "forca", "persistencia", "liquidez", "teorica", "custo",
  "sma200", "tendencia", "drawdown", "volatilidade", "faixa", "sharpe", "baseline",
];

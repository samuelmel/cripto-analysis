/** Termos do painel em português simples: o texto longo mora aqui, nos cartões só aparece o termo com dica. */
export type TermId = "sma200" | "tendencia" | "drawdown" | "volatilidade" | "faixa" | "sharpe" | "baseline";

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
};

export const GLOSSARY_ORDER: readonly TermId[] = ["sma200", "tendencia", "drawdown", "volatilidade", "faixa", "sharpe", "baseline"];

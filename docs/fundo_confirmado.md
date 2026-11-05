# Comprar o "fundo confirmado por 2 candles" funciona? Protocolo (fixado antes dos resultados)

Em 05/11/2026 houve um teste exploratório informal desta ideia: comprar quando o fechamento é a mínima de 20 dias e
os 2 candles seguintes fecham em alta. O resultado informal (segurando 10 dias, 32 moedas) foi: **+8,3% por operação**
quando se compra no preço do fundo, **+0,3%** quando se compra só depois de a confirmação existir, e **+1,5%** comprando
num dia qualquer. Este documento transforma a ideia num estudo formal. Foi escrito e commitado **antes** de rodar o
código final; os números exploratórios acima não decidem nada.

## A regra

Por moeda, com candles diários (`open`, `close`), no dia `t`:

1. **Fundo**: `close[t]` é o menor fechamento dos últimos `N` dias (incluindo `t`).
2. **Confirmação**: `close[t+1] > close[t]` e `close[t+2] > close[t+1]` (dois fechamentos seguidos em alta).
3. A regra só fica conhecida **no fechamento de `t+2`**.

## Duas entradas lado a lado

| Entrada | Preço de compra | Comentário |
|---|---|---|
| **Honesta** | abertura de `t+3` | a primeira hora em que alguém poderia comprar sabendo da confirmação |
| **Com viés de olhar o futuro** | fechamento de `t` | exige saber, no dia do fundo, que os dois dias seguintes subiriam |

A segunda existe **só para mostrar o erro**: ela não é uma estratégia possível. Nas duas, a saída é no mesmo momento
(abertura de `t+3+H`), para que a única diferença seja o preço de entrada.

## Parâmetros (fixos agora)

- Janela do fundo `N` ∈ {10, 20, 50} dias.
- Prazo de segurar `H` ∈ {5, 10, 20} dias.
- Total: 9 configurações, 9 hipóteses (a honesta é a que decide).
- Custo: **0,2% ida e volta** descontado de toda operação (e do comparador).
- **Sem sobreposição**: por moeda, um novo sinal só vira operação se a entrada ocorrer depois da saída da operação anterior.
- Universo: as 32 moedas com candles diários em `data/market/ohlcv_1d` (`config.UNIVERSE`); moeda entra a partir do
  primeiro dia com `N` candles.

## Comparação com o acaso

Para cada operação, o comparador é o retorno médio de **entrar num dia qualquer da mesma moeda e segurar o mesmo prazo**
(abertura de `d` até a abertura de `d+H`, mesmo custo), calculado sobre todos os dias válidos da moeda **no mesmo
período** (desenvolvimento ou teste). O excesso da operação é `retorno − comparador`. Isso retira a deriva de alta da
própria moeda.

## Inferência

- Estatística: média do excesso por operação, juntando as moedas.
- Intervalo de 90% e p-valor unilateral (H0: média do excesso ≤ 0) por **bootstrap em blocos**: as operações são
  agrupadas por blocos de 30 dias do calendário (a data de entrada), reamostram-se blocos inteiros com reposição
  (as moedas andam juntas, então operações do mesmo mês não são independentes), 2.000 reamostras, semente 20261105.
- **Correção de Holm** sobre as 9 hipóteses da entrada honesta no desenvolvimento, α = 0,05.

## Períodos

| Período | Entradas entre | Uso |
|---|---|---|
| Desenvolvimento | 2017 a 2022 | decide o veredito |
| Teste final | 2023 a 2026 | só pode contradizer |

## Critério

Uma configuração é **`FUNCIONA`** apenas se, no desenvolvimento, a entrada honesta tiver: média do excesso > 0, limite
inferior do IC de 90% > 0, p ajustado de Holm < 0,05 e, no teste final, média do excesso > 0. Caso contrário é
**`NAO_DEMONSTRADO`**. Com menos de 30 operações num período, o resultado vira **`DADOS_INSUFICIENTES`**.
O estudo é considerado negativo se nenhuma das 9 configurações for `FUNCIONA`.

## Limitações (antes do resultado)

- Uma única história de mercado, poucos ciclos; as moedas andam juntas, o que reduz o número real de operações independentes.
- Universo atual de 32 moedas (inclui viés de sobrevivência: moedas que sumiram não estão aqui). Isso favorece a
  regra e o acaso por igual, mas não tem como ser medido.
- O "acaso" inclui a tendência de alta de cada moeda; o excesso é conservador de propósito.
- Custo fixo de 0,2%, sem modelar spread por liquidez.
- A ideia nasceu de um olhar exploratório nos mesmos dados; por isso o teste final de 2023+ **não é virgem**.

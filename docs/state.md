# Estado persistente: branch `state`

O que precisa sobreviver entre execuções (e ficar acessível ao GitHub Actions, para o aviso chegar com o PC desligado) vive na
branch `state` do repositório privado. É uma branch **só de dados** (sem código), separada da `main`.

| Arquivo (em `data/state/`) | Conteúdo | Quem escreve |
|---|---|---|
| `positions.parquet` | suas compras e vendas | `python -m src.positions` (no PC, ou o painel via dev server) |
| `signal_log.parquet` | registro **imutável** de sinais: um registro por moeda e dia, com cadeia de hash | pipeline do Actions (`--record-state`) |
| `position_states.parquet` | histórico diário do estado de cada posição aberta (SEGURAR, ATENÇÃO, VENDER) | pipeline do Actions |
| `notifications.parquet` | avisos de mudança de estado já enviados ao Telegram | pipeline do Actions |
| `model_predictions.parquet` | previsões diárias dos modelos de IA **em modo sombra** (probabilidade e posição por moeda e modelo, versão do modelo, fingerprint dos dados), com cadeia de hash; nunca entram na recomendação nem no Telegram | pipeline do Actions (`--record-state`) |
| `fng_history.parquet` | cópia do histórico do Fear & Greed visto em cada execução; um dia cujo valor muda na fonte entra de novo (revisão auditável). Se a fonte falhar, o pipeline usa esta cópia | pipeline do Actions (`--record-state`) |
| `sim_decisions.parquet` | decisões das **carteiras simuladas em reais** (dinheiro fictício; `docs/sim_wallets.md`): carteira, dia, moeda, lote, COMPRA/VENDA e valor em R$, com cadeia de hash; append-only e idempotente por (carteira, dia, moeda, lado). Posições e caixa não são guardados: são refeitos a cada execução a partir das decisões e dos preços | pipeline do Actions (`--record-state`) |

No PC, `data/state/` é um *worktree* git da branch `state` (a pasta `data/` é ignorada pela `main`). `python -m src.state_sync
init` cria o worktree (e a branch vazia na primeira vez, copiando as posições antigas de `data/positions/`).

## Fluxo

- **Registrar compra ou venda** (`python -m src.positions add|close|remove`): traz a branch (`pull`), altera, faz commit e `push`.
  Use `--no-sync` para trabalhar só local. Se o envio falhar, o comando diz que a alteração ficou só no seu computador.
- **Execução diária (Actions)**: faz o checkout da branch em `data/state`, roda `python -m src.pipeline --notify --record-state`
  e, se tudo deu certo, faz commit e push das mudanças na própria branch `state` (nunca na `main`).
- **Execução local do pipeline** (Agendador do Windows ou à mão): calcula e publica o painel, mas **não grava** o registro de
  sinais, o histórico nem os avisos (sem `--record-state`), para o PC e o Actions não divergirem.

## Registro imutável de sinais

Uma linha por moeda e dia de dados: estágio (já com a exigência de evidência), alerta, regra SMA 200 ativa, score, classificação,
seleção, a evidência estatística do COMPRAR (situação, excesso em 7 e 30 dias, p ajustado), versão da configuração
(`config_version`, hash dos parâmetros) e do código (commit). Cada linha traz o hash da anterior e o próprio.

- Um par (dia, moeda) que já existe **nunca** é reescrito; rodar de novo no mesmo dia não muda nada.
- Antes de acrescentar, o pipeline confere a cadeia. Se alguma linha foi alterada ou apagada, levanta `LogIntegrityError` e
  **nada** é gravado.
- Limitação: o git já guarda o histórico da branch `state`, e a cadeia de hash só prova que o arquivo não foi alterado
  silenciosamente; quem tem permissão de escrita na branch ainda poderia reescrever a cadeia inteira. É um registro de auditoria
  do próprio projeto, não uma prova perante terceiros.

## Estados das posições e aviso

`VENDER` quando alguma regra adotada dispara; `ATENÇÃO` quando alguma está a metade do caminho; `SEGURAR` no resto. As regras e a
evidência de cada uma estão em [exit_rules.md](exit_rules.md) (o trailing **não** foi adotado: aparece só como ATENÇÃO).
O Telegram avisa **só quando o estado muda**, uma vez, com a regra que disparou e o que ela fez no histórico. Uma mudança só é
marcada como avisada depois do envio; se o envio falhar, é reenviada na execução seguinte. Nenhuma ordem é executada.

## Privacidade

Suas posições ficam no histórico git do repositório privado. Se o repositório virar público, esses dados vazam; antes disso, mova
a branch `state` para outro repositório privado ou apague o histórico.

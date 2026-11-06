# Estado persistente: repositório privado de estado

O que precisa sobreviver entre execuções (e ficar acessível ao GitHub Actions, para o aviso chegar com o PC desligado) vive no
repositório privado **`samuelmel/cripto-analysis-state`** (branch `main`). É um repositório **só de dados** (sem código),
separado deste projeto: a `main` não recebe commits de dados.

| Arquivo (em `data/state/`) | Conteúdo | Quem escreve |
|---|---|---|
| `positions.parquet` | suas compras e vendas | `python -m src.positions` (no PC, ou o painel via dev server) |
| `signal_log.parquet` | registro **imutável** de sinais: um registro por moeda e dia, com cadeia de hash | pipeline do Actions (`--record-state`) |
| `position_states.parquet` | histórico diário do estado de cada posição aberta (SEGURAR, ATENÇÃO, VENDER) | pipeline do Actions |
| `notifications.parquet` | avisos de mudança de estado já enviados ao Telegram | pipeline do Actions |
| `model_predictions.parquet` | previsões diárias dos modelos de IA **em modo sombra** (probabilidade e posição por moeda e modelo, versão do modelo, fingerprint dos dados), com cadeia de hash; nunca entram na recomendação nem no Telegram | pipeline do Actions (`--record-state`) |
| `fng_history.parquet` | cópia do histórico do Fear & Greed visto em cada execução; um dia cujo valor muda na fonte entra de novo (revisão auditável). Se a fonte falhar, o pipeline usa esta cópia | pipeline do Actions (`--record-state`) |
| `sim_decisions.parquet` | decisões das **carteiras simuladas em reais** (dinheiro fictício; `docs/sim_wallets.md`): carteira, dia, moeda, lote, COMPRA/VENDA e valor em R$, com cadeia de hash; append-only e idempotente por (carteira, dia, moeda, lado). Posições e caixa não são guardados: são refeitos a cada execução a partir das decisões e dos preços | pipeline do Actions (`--record-state`) |

No PC, `data/state/` é um **clone normal** desse repositório (HTTPS, com as credenciais do seu Git; a pasta `data/` é ignorada
pelo projeto). `python -m src.state_sync init` cria o clone (ou, se for o worktree antigo da branch `state`, migra; ver abaixo).
Na primeira vez em um repositório de estado vazio, cria o README e envia. As posições antigas de `data/positions/` são copiadas
se ainda não existirem no clone.

No GitHub Actions, o acesso ao repositório de estado usa uma **deploy key SSH com escrita**, guardada no secret
`STATE_DEPLOY_KEY` do repositório do projeto. Sem esse secret, o pipeline diário falha logo no início com uma mensagem clara.

### Setup (uma vez)

1. Criar o repositório privado `samuelmel/cripto-analysis-state`, vazio (sem README, sem .gitignore, sem licença).
2. Gerar a chave: `ssh-keygen -t ed25519 -N "" -C "cripto-analysis actions" -f state_deploy_key`.
3. No repositório de estado: Settings → Deploy keys → Add, colar `state_deploy_key.pub` e marcar **Allow write access**.
4. No repositório do projeto: Settings → Secrets and variables → Actions → New secret `STATE_DEPLOY_KEY` com o conteúdo de
   `state_deploy_key` (a privada, inteira). Depois apague os dois arquivos da chave do seu computador.

### Migração do worktree antigo (PC)

Se `data/state/` ainda for o worktree da branch `state` deste repositório, `init` faz a troca: aborta (sem remover nada) se
houver mudança não commitada; senão copia os `.parquet`, remove o worktree, apaga a branch `state` **local** (o remoto não é
tocado), clona o repositório de estado e copia os dados. Se um arquivo local for diferente do que já está no repositório de
estado, ele **não** é sobrescrito: a cópia fica em `data/state_migracao_backup/` e o comando avisa.

## Fluxo

- **Registrar compra ou venda** (`python -m src.positions add|close|remove`): traz o repositório (`pull`), altera, faz commit e `push`.
  Use `--no-sync` para trabalhar só local. Se o envio falhar, o comando diz que a alteração ficou só no seu computador.
- **Execução diária (Actions)**: faz o checkout do repositório de estado em `data/state` (com a deploy key), roda
  `python -m src.pipeline --notify --record-state` e, se tudo deu certo, faz commit e push no repositório de estado.
  Este projeto não recebe escrita do workflow. Um último passo reativa os agendamentos (repositórios públicos sem atividade
  por 60 dias os desligam).
- **Execução local do pipeline** (Agendador do Windows ou à mão): calcula e publica o painel, mas **não grava** o registro de
  sinais, o histórico nem os avisos (sem `--record-state`), para o PC e o Actions não divergirem.

## Registro imutável de sinais

Uma linha por moeda e dia de dados: estágio (já com a exigência de evidência), alerta, regra SMA 200 ativa, score, classificação,
seleção, a evidência estatística do COMPRAR (situação, excesso em 7 e 30 dias, p ajustado), versão da configuração
(`config_version`, hash dos parâmetros) e do código (commit). Cada linha traz o hash da anterior e o próprio.

- Um par (dia, moeda) que já existe **nunca** é reescrito; rodar de novo no mesmo dia não muda nada.
- Antes de acrescentar, o pipeline confere a cadeia. Se alguma linha foi alterada ou apagada, levanta `LogIntegrityError` e
  **nada** é gravado.
- Limitação: o git já guarda o histórico do repositório de estado, e a cadeia de hash só prova que o arquivo não foi alterado
  silenciosamente; quem tem permissão de escrita na branch ainda poderia reescrever a cadeia inteira. É um registro de auditoria
  do próprio projeto, não uma prova perante terceiros.

## Estados das posições e aviso

`VENDER` quando alguma regra adotada dispara; `ATENÇÃO` quando alguma está a metade do caminho; `SEGURAR` no resto. As regras e a
evidência de cada uma estão em [exit_rules.md](exit_rules.md) (o trailing **não** foi adotado: aparece só como ATENÇÃO).
O Telegram avisa **só quando o estado muda**, uma vez, com a regra que disparou e o que ela fez no histórico. Uma mudança só é
marcada como avisada depois do envio; se o envio falhar, é reenviada na execução seguinte. Nenhuma ordem é executada.

## Privacidade

Suas posições ficam no histórico git do repositório de estado, que é **privado**. O repositório deste projeto pode ficar público
porque não guarda dados pessoais: nenhuma posição entrou no histórico da `main`, e o estado não passa por ele. Por isso o
estado **não** pode voltar para a branch `state` deste repositório (ela seria pública junto). Commits antigos da branch `state`
continuam acessíveis pelo hash até o GitHub limpar o repositório; a limpeza é feita por chamado ao GitHub Support
("sensitive data removal") antes de tornar o projeto público.

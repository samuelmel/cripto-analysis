# Telegram e automação

Como receber o resumo diário no celular e como fazer o pipeline rodar sozinho todo dia.

O envio é **só uma mensagem**. O projeto não executa ordens, não acessa nenhuma corretora e não usa chave de corretora.

- [O que a mensagem traz](#o-que-a-mensagem-traz)
- [Criar o bot e testar](#criar-o-bot-e-testar)
- [GitHub Actions](#github-actions)
- [Agendador de Tarefas do Windows](#agendador-de-tarefas-do-windows)
- [Claude Desktop (MCP)](#claude-desktop-mcp)

---

## O que a mensagem traz

Ela é curta, para ler em um minuto, e tem esta estrutura (os valores abaixo são ilustrativos):

```
📊 CRIPTO — ANÁLISE DO DIA
<data e hora em Fortaleza e em UTC>
Dados: fechamento diário de <dia> (UTC), <em dia | ATRASADO n dia(s)>.
Orçamento disponível na simulação: R$ 100
Mercado: <favorável | neutro | defensivo> — <explicação em uma frase>

Melhores oportunidades
1. <MOEDA> — Aporte sugerido: R$ <valor>
Classificação: <boa | moderada> (score <n> de 100)
Motivo: …
Atenção: <principal risco>

Resumo do aporte
Total sugerido: R$ <x> de R$ 100.
Saldo não alocado: R$ <y>.
Decisão: …

Validação histórica: <frase de evidência do backtest>
Importante: são estimativas quantitativas, não garantias de valorização. …
```

- Aparecem **só as moedas selecionadas**, no máximo `MAX_CANDIDATES` (3).
- Os alertas essenciais (virada da regra SMA 200 de BTC ou ETH e pânico) aparecem quando existem.
- Sem oportunidade, a mensagem usa uma frase fixa, seguida dos motivos mais frequentes: *"Hoje não encontrei oportunidades suficientemente boas dentro dos critérios configurados. Aporte sugerido: R$ 0 de R$ 100. O orçamento permanece sem alocação."*
- Todos os números vêm de `recommendation.parquet` e `daily_signals.parquet` da mesma execução. Os indicadores detalhados ficam no painel.

Para ver a mensagem real sem enviar nada e sem acessar a rede:

```bash
uv run python -m src.pipeline --offline --dry-run
```

### Quando algo dá errado

- **Dados parciais ou atrasados:** a mensagem traz a seção "Limitações desta análise". Uma moeda sem dado confiável nunca é recomendada, e, sem dado do BTC, nenhuma compra é sugerida.
- **O pipeline falhou:** se o Telegram estiver configurado, chega um alerta curto de erro, sem segredos.
- **O envio falhou:** o pipeline termina com código 2, e o job do GitHub fica vermelho.
- **Mensagem longa:** acima de 4096 caracteres, ela é dividida por parágrafo ou linha.
- **Rede:** o envio tem timeout de 15 s e até 3 tentativas, com espera de 2 e 4 s. Ele respeita o `retry_after` do Telegram e não repete quando o token ou o chat estão errados.
- **Código de saída** com `--notify`: 0 para ok, 1 para mensagem inválida e 2 para credenciais ausentes ou envio que falhou.

---

## Criar o bot e testar

Você faz isso uma vez.

1. No Telegram, abra uma conversa com **@BotFather**. Confira o selo azul de verificado. Envie `/newbot`, escolha um nome e um usuário que termine em `bot`. O BotFather responde com o **token**, no formato `123456789:AA...`. Guarde-o com cuidado: quem tem o token controla o bot.
2. Abra a conversa com o seu bot novo e envie qualquer mensagem, como `oi`. Um bot não pode escrever primeiro.
3. Descubra o `chat_id`. No navegador, abra `https://api.telegram.org/bot<SEU_TOKEN>/getUpdates`, trocando `<SEU_TOKEN>` pelo token, e procure `"chat":{"id":123456789`. Esse número é o `TELEGRAM_CHAT_ID`. **Essa URL contém o token**: não compartilhe a tela nem o link.
4. Teste no PowerShell, na pasta do projeto:

   ```powershell
   $env:TELEGRAM_BOT_TOKEN = "cole-o-token"
   $env:TELEGRAM_CHAT_ID = "cole-o-chat-id"
   uv run python -m src.pipeline --offline --notify
   ```

Se a mensagem chegar no celular, está pronto. Fechar o PowerShell apaga as variáveis. O projeto **não lê arquivos `.env`**: as variáveis precisam estar no ambiente do processo.

| Variável | Para quê |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token do bot. É segredo: nunca entra em código, log, mensagem ou erro. |
| `TELEGRAM_CHAT_ID` | Número do chat que recebe as mensagens |
| `COINGECKO_API_KEY` | Opcional: chave Demo gratuita do CoinGecko |
| `BINANCE_API_HOST` | Opcional: `https://data-api.binance.vision` quando a `api.binance.com` responde HTTP 451. Só esses dois hosts são aceitos. |

---

## GitHub Actions

O workflow [`.github/workflows/daily.yml`](../.github/workflows/daily.yml) roda o pipeline online todo dia e envia o resumo. Ele precisa estar na branch padrão do repositório no GitHub.

### O que você precisa fazer

1. Em **Settings → Secrets and variables → Actions → New repository secret**, crie os secrets com estes nomes exatos: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` e, se quiser, `COINGECKO_API_KEY`.
2. Em **Actions → Pipeline diário → Run workflow**, faça um teste manual.
3. Confirme o envio. O job deve terminar verde, o log do último passo deve mostrar `resumo enviado ao Telegram (1 mensagem(ns))` e a mensagem deve chegar no celular. O GitHub esconde os segredos no log.
4. Se também usar o Agendador do Windows, desative um dos dois, ou você receberá duas mensagens por dia.

### O que o workflow faz, nesta ordem

1. **Escolhe o host da Binance.** Testa a `api.binance.com` e, se ela recusar o runner (HTTP 451, bloqueio regional) ou não responder 200, testa a `data-api.binance.vision`, que serve os mesmos dados públicos. O primeiro que responder 200 vira a variável `BINANCE_API_HOST`. Se nenhum responder, o job falha na hora com uma mensagem clara. A saída, nesse caso, é rodar em outro lugar (por exemplo, um runner self-hosted) ou trocar de fonte de preço.
2. **Prepara o ambiente.** Usa `actions/checkout@v7` e `actions/setup-python@v7` com Python 3.12, instala o `uv` 0.13.0 e roda `uv sync --locked`.
3. **Roda o pipeline.** Executa `uv run python -m src.pipeline --notify`, sem `--offline`. Qualquer falha crítica (rede, análise ou envio) deixa o job vermelho.

**Segurança.** O workflow usa `permissions: contents: read`, `concurrency` sem execuções simultâneas, timeout de 20 minutos, e os segredos entram só como `secrets`, só no passo do pipeline.

### Horário

O gatilho é `cron: "10 0 * * *"`, ou seja, **00:10 UTC = 21:10 em Brasília e Fortaleza** (UTC−3, sem horário de verão). Esse horário fica logo depois do fechamento do candle diário da Binance (00:00 UTC). Para outro fuso, converta para UTC.

- O GitHub pode atrasar ou descartar execuções agendadas em horário de pico. O começo de cada hora é pico, por isso o gatilho é às 00:10 e não às 00:00.
- Em repositório público, o GitHub desativa o agendamento depois de 60 dias sem atividade. Para reativar, vá em **Actions**.

**Por que uma vez por dia.** O sinal usa o fechamento diário, e o candle do dia em andamento é descartado. Rodar com mais frequência devolve o mesmo sinal e só gera mensagens repetidas.

### O que não existe no runner

- **Base histórica:** o runner começa sem a pasta `data/`. A cada execução, o pipeline baixa o histórico inteiro de novo e recalcula tudo. O sinal de "ontem", usado nos alertas de virada, é recalculado a partir do histórico.
- **Suas posições:** ficam na branch `state` (ver [state.md](state.md)), acessível ao Actions. A mensagem diária continua cobrindo sinais e seleção; uma mensagem **separada** só aparece quando o estado de alguma posição muda (SEGURAR, ATENÇÃO, VENDER), com a regra e o histórico dela.

---

## Agendador de Tarefas do Windows

O [`run_daily.cmd`](../run_daily.cmd) roda `uv run python -m src.pipeline`, **sem** `--notify`, e grava o log em `logs/pipeline.log`. Para receber também o Telegram por aqui, acrescente `--notify` à linha do pipeline no arquivo e defina as variáveis do Telegram no ambiente do usuário do Windows.

Agende para 21:10, logo depois do fechamento do candle diário (00:00 UTC). Troque o caminho pelo da sua pasta:

```bat
schtasks /Create /TN "crypto-analyzer diario" /SC DAILY /ST 21:10 /TR "\"C:\caminho\para\cripto-analysis\run_daily.cmd\""
```

| Ação | Comando |
|---|---|
| Testar sem esperar o horário | `schtasks /Run /TN "crypto-analyzer diario"` |
| Remover o agendamento | `schtasks /Delete /TN "crypto-analyzer diario" /F` |

---

## Claude Desktop (MCP)

O [`mcp_server.py`](../mcp_server.py) expõe a tool `run_crypto_pipeline`, que roda o pipeline completo em subprocesso e devolve as últimas linhas do log. Adicione dentro de `mcpServers` no `claude_desktop_config.json`, trocando os caminhos pelos seus:

```json
{
  "mcpServers": {
    "crypto-analyzer": {
      "command": "C:\\caminho\\para\\uv.exe",
      "args": ["run", "--directory", "C:\\caminho\\para\\cripto-analysis", "mcp_server.py"]
    }
  }
}
```

## Sinais de entrada (desde 2026-10-17, `docs/entry_signals.md`)

- **Resumo diário**: seção "🎯 Sinais de entrada" com o estado do COMPRAR (só com sinal VALIDADO), as candidatas do dia com
  dado confiável (nível, combinação, desde quando, "novo hoje", aporte sugerido pela seleção e principal risco), o excesso com
  IC 95% em 7 e 30 dias e o teste final de cada sinal ativo, o regime do mercado e o aviso de que PROMISSOR pode ser só a melhor
  de várias combinações testadas. A validação por moeda aparece como informação; a regra SMA 200 aparece como contexto.
- **Aviso de mudança** ("👀 LISTA DE OBSERVAÇÃO — MUDANÇA"): mensagem separada, só quando uma candidata dispara (entra na
  condição de um sinal VALIDADO/PROMISSOR) ou se desfaz (sai dela) no dia. Moeda sem dado confiável não gera aviso. A mudança
  é calculada comparando hoje com ontem nas próprias condições (não depende de estado gravado); se o pipeline rodar duas vezes
  sobre o mesmo candle, o aviso se repete.
- **Posições**: quando uma posição muda para ATENÇÃO, o aviso traz "Sugestão: considere reduzir o tamanho da posição (não é
  ordem de venda; a regra ainda não disparou)".

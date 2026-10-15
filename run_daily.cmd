@echo off
:: Pipeline diario: extrai, detecta, compara com ontem, salva historico e publica para o frontend.
:: O candle diario da Binance fecha as 00:00 UTC (21:00 em Brasilia); agende para 21:10.
:: Registro no Agendador de Tarefas (rode uma vez num terminal):
::   schtasks /Create /TN "crypto-analyzer diario" /SC DAILY /ST 21:10 /TR "\"D:\Downloads\pastas codigo\projeto cripto\crypto-analyzer\run_daily.cmd\""

cd /d "%~dp0"
if not exist logs mkdir logs
uv run python -m src.pipeline >> logs\pipeline.log 2>&1
exit /b %ERRORLEVEL%

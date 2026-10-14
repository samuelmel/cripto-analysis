@echo off
setlocal enabledelayedexpansion

:: Atualização mensal: extração incremental -> features/sinais -> CSV do mês.
:: Agendador de Tarefas do Windows (Task Scheduler): Configurar para todo dia 1º às 02:00
:: Ação: Iniciar um programa -> Programa/script: cmd.exe 
:: Argumentos: /c "D:\Downloads\pastas codigo\projeto cripto\crypto-analyzer\run_monthly.cmd" >> logs\run_monthly.log 2>&1

set "PROJECT_DIR=D:\Downloads\pastas codigo\projeto cripto\crypto-analyzer"
cd /d "%PROJECT_DIR%"

:: Ativa o ambiente virtual (específico para Windows)
if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
) else (
    echo [.venv\Scripts\activate.bat] nao encontrado.
    exit /b 1
)

:: Configurações (em batch, listas separadas por espaço funcionam bem para argumentos)
set "SYMBOLS=BTC/USDT ETH/USDT SOL/USDT"
set "YEARS=4"

:: Extrai o mês (YYYY-MM) de forma segura ignorando as configurações regionais de data do Windows
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM'"') do set "MONTH=%%i"

set "SIGNALS_OUT=data\signals\signals_%MONTH%.csv"

:: Função inline para pegar a data/hora atual
for /f "delims=" %%i in ('powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"') do set "NOW=%%i"
echo [%NOW%] Inicio da atualizacao de %MONTH%

:: 1) Extração (retoma do último timestamp salvo; é idempotente)
uv run extract_historical.py --symbols %SYMBOLS% --timeframe 1d --years %YEARS%

:: 2) Features + sinais de compra, salvos em CSV do mês
uv run signal_analyzer.py --data data\raw\ohlcv --exchange binance --timeframe 1d --out "%SIGNALS_OUT%"

for /f "delims=" %%i in ('powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"') do set "NOW=%%i"
echo [%NOW%] Concluido: %SIGNALS_OUT%
@echo off

REM Se o sistema ja estiver rodando, apenas abre o navegador
netstat -ano | findstr ":8501" >nul 2>&1
if %ERRORLEVEL% equ 0 (
    start "" "http://localhost:8501"
    exit /b 0
)

REM Inicia o sistema em janela minimizada
start "Banco de Horas" /min cmd /k ""%~dp0_runner.bat""

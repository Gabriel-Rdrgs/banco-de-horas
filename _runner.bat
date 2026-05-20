@echo off
title Banco de Horas - Provida Centro Medico
cd /d "%~dp0"

echo.
echo  ============================================
echo   Banco de Horas - Provida Centro Medico
echo  ============================================
echo.
echo  Iniciando o sistema...
echo  O navegador abrira automaticamente em instantes.
echo.
echo  IMPORTANTE: Nao feche esta janela.
echo              Fechar aqui encerrara o sistema.
echo.

python -m streamlit run app.py

echo.
if %ERRORLEVEL% neq 0 (
    echo  ERRO ao iniciar. Verifique:
    echo   1. Python instalado e no PATH
    echo   2. Arquivo .env configurado com credenciais Azure
    echo   3. Dependencias instaladas: pip install -r requirements.txt
    echo.
)
echo  Sistema encerrado. Pressione qualquer tecla para fechar.
pause

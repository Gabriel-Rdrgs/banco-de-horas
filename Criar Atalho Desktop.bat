@echo off
set "DIR=%~dp0"
if "%DIR:~-1%"=="\" set "DIR=%DIR:~0,-1%"
set "ALVO=%DIR%\Iniciar Banco de Horas.bat"

echo Criando atalho na area de trabalho...

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { $WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\Banco de Horas.lnk'); $Shortcut.TargetPath = $env:ALVO; $Shortcut.WorkingDirectory = $env:DIR; $Shortcut.Description = 'Banco de Horas - Provida Centro Medico'; $Shortcut.IconLocation = $env:SystemRoot + '\System32\shell32.dll, 22'; $Shortcut.Save() }"

echo.
echo  Pronto! Atalho "Banco de Horas" criado na area de trabalho.
echo  A partir de agora, use o atalho para abrir o sistema.
echo.
pause

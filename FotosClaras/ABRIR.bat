@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Primero hace doble clic en INSTALAR.bat
  pause
  exit /b 1
)
start "Fotos Claras" ".venv\Scripts\pythonw.exe" "app.py"

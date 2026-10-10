@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Primero ejecuta INSTALAR.bat.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install pyinstaller
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --onedir --name "Fotos Claras" --hidden-import cv2 --collect-all cv2 app.py
if errorlevel 1 goto failed
echo Ejecutable creado en dist\Fotos Claras\Fotos Claras.exe
pause
exit /b 0
:failed
echo No se pudo crear el ejecutable.
pause
exit /b 1

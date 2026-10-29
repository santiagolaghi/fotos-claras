@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto failed
".venv\Scripts\python.exe" -m pip install pyinstaller==6.19.0
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --onedir --name FotosClaras --collect-all cv2 --collect-all pillow_heif app.py
if errorlevel 1 goto failed
echo Ejecutable: dist\FotosClaras\FotosClaras.exe
pause
exit /b 0
:failed
echo No se pudo compilar. Ejecuta INSTALAR.bat y revisa el diagnostico.
pause
exit /b 1

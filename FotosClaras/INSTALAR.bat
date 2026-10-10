@echo off
cd /d "%~dp0"
where py >nul 2>&1
if %errorlevel%==0 (
  py -3 -m venv .venv
) else (
  where python >nul 2>&1
  if not %errorlevel%==0 goto no_python
  python -m venv .venv
)
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo.
echo Instalacion terminada. Ahora hace doble clic en ABRIR.bat.
pause
exit /b 0
:no_python
echo Hace falta Python para Windows. Descargalo desde https://www.python.org/downloads/windows/
echo Durante la instalacion activa "Add python.exe to PATH" y despues volve a abrir este archivo.
pause
exit /b 1
:failed
echo No se pudo terminar la instalacion. Revisa tu conexion y volve a intentar.
pause
exit /b 1

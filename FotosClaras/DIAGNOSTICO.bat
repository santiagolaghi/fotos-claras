@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo Ejecuta INSTALAR.bat para diagnosticar la copia de codigo fuente.
 pause
 exit /b 1
)
".venv\Scripts\python.exe" -c "from fotosclaras import __version__; import PySide6, cv2, PIL; print('Fotos Claras', __version__); print('Qt', PySide6.__version__, 'OpenCV', cv2.__version__, 'Pillow', PIL.__version__)"
".venv\Scripts\python.exe" -m unittest discover -s tests_v1 -v
echo Diagnostico: %%LOCALAPPDATA%%\FotosClaras\diagnostico-v1.log
pause

# Fotos Claras

Aplicación de escritorio para Windows que encuentra fotos duplicadas, sugiere versiones similares, agrupa rostros y ayuda a organizar álbumes. Procesa las fotos en la PC; no las sube a GitHub.

## Instalar

Descargá `Fotos-Claras-Windows.zip` desde la [última versión](https://github.com/santiagolaghi/fotos-claras/releases/latest), descomprimilo y seguí las instrucciones de `FotosClaras/README.txt`. Necesita Python para Windows. La primera instalación se hace con `INSTALAR.bat`; después se abre con `ABRIR.bat`.

Desde la versión 0.7, la aplicación comprueba si hay actualizaciones al abrir y ofrece instalarlas. La instalación con el `.exe` opcional no incluye esa función.

## Desarrollo

Código en `FotosClaras/`. Pruebas: `PYTHONPATH=FotosClaras python -m unittest discover -s FotosClaras/tests -v`.

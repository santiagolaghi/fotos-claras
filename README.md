# Fotos Claras · Álbum Editorial

Organizador fotográfico local para Windows. Interfaz Qt, catálogo SQLite,
versiones para revisión, identidades corregibles, filtros combinados, álbumes
virtuales y movimientos recuperables. **0.9.0-beta.1**, no versión estable.

La reconstrucción se encuentra en la rama `reconstruccion/editorial-0.9`.
El workflow **Windows · pruebas e instalador beta** está configurado para
construir el instalador y verificar la aplicación instalada. Los primeros
intentos quedaron bloqueados antes de asignar un runner por una restricción
de cuenta: todavía no hay instalador Windows generado ni verificado.
El [PR #1](https://github.com/santiagolaghi/fotos-claras/pull/1) permanece en borrador.
No hay una release estable automática.

- [Auditoría del código previo](docs/AUDITORIA.md)
- [Arquitectura](docs/ARQUITECTURA.md)
- [Verificación y límites](docs/VERIFICACION.md)
- [Uso](FotosClaras/README.txt)

Desarrollo con Python 3.12:

```sh
python -m pip install -r FotosClaras/requirements.txt
python FotosClaras/app.py
```

Pruebas:

```sh
cd FotosClaras
python -m unittest discover -s tests_v1 -v
```

Desde la raíz: `python tools/verify_real.py` descarga fotografías públicas de
prueba y los modelos oficiales; `python tools/benchmark.py --files 10000`
genera un informe de rendimiento con sus limitaciones. Ninguna foto personal
se envía a servicios externos.

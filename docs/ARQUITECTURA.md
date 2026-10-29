# Arquitectura 0.9 beta

La implementación vigente es beta 3. Sus cambios en procesos, agrupamiento,
paginación y esquema v2 se detallan en [CAMBIOS-beta-3.md](CAMBIOS-beta-3.md).

- `fotosclaras/db.py`: esquema versionado, bibliotecas, fotos, rostros, personas,
  restricciones, álbumes virtuales, trabajos, operaciones y preferencias. Una
  conexión SQLite por hilo, WAL, claves externas y sincronización FULL.
- `imaging.py`: orientación EXIF, huella de bytes y píxeles RGBA con tamaño,
  formato, fecha, thumbnails en disco. Secuencias solo coinciden por archivo.
- `indexer.py`: descubrimiento controlado, huellas incrementales y cancelación.
  Solo un recorrido completo marca ausentes. Errores y progreso quedan guardados.
- `matching.py`: índice BK de huellas como preselección, comparación de detalle
  para versiones y agrupación exacta independiente. No hay borrado automático.
- `identity.py`: YuNet detecta; SFace representa rostros; agrupación incremental
  con margen frente a competidores, exclusión de dos caras de una misma foto,
  confirmaciones persistentes y veto tras separaciones. Nunca se entrena una red.
- `operations.py`: plan inmutable, preflight, copia exclusiva verificada y
  journal por archivo antes de retirar el origen. Recuperación de interrupciones,
  deshacer verificado y nunca sobrescribir. Álbum virtual no toca disco.
- `ui.py`, `widgets.py`: Qt model/view, miniaturas en pool acotado, worker para
  análisis y movimientos, visor con zoom, comparación, filtros y revisión.
- `updates.py`: Releases oficiales + digest de GitHub; instalación Windows en
  directorios versionados con lanzador, cambio de versión y vuelta a la anterior.
  Estado de usuario fuera de instalación. Sin release estable sin validación.

Los tamaños/mtime invalidan la caché. Si cambian los bytes pero no los píxeles,
se conservan rostros. Si cambia la fotografía se invalidan sus detecciones. La
importación de nombres antiguos conserva copias del estado anterior; no altera
la base previa. Cada operación está vinculada a IDs de fotografía, no al nombre.

La UI no ejecuta exploración de disco, hashes, modelos ni movimientos en el
hilo principal. El catálogo se puede abrir sin reanalizar. La pausa es cooperativa
entre archivos/pares y conserva el trabajo completado, no interrumpe la escritura
atómica de un archivo. Un análisis facial cancelado retoma solo los pendientes.

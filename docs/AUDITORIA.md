# Auditoría de Fotos Claras 0.8 beta

Se inspeccionaron todos los archivos Python, pruebas, scripts y README del ZIP
adjunto. Se contrastaron con `main` del repositorio el 27/10/2026: el ZIP contiene
cambios más recientes en app, core, faces, settings y pruebas; es la referencia
funcional para esta reconstrucción. No hay AGENTS.md en el proyecto.

## Hallazgos

|Prioridad|Evidencia|Consecuencia|
|---|---|---|
|Crítica|`core._move` registra el lote DESPUÉS de moverlo|Un cierre abrupto deja archivos movidos sin historial|
|Crítica|`undo_last` restaura sin verificar contenido y no registra cada paso|Puede devolver un archivo modificado y perder recuperación de lotes parciales|
|Alta|`FotosClaras.__init__` ejecuta `after(350, analyze)`|Análisis pesado al iniciar; no hay cancelación|
|Alta|`gallery._tile` y `app._show_preview` abren imágenes en el hilo UI|Congelamientos al desplazarse o seleccionar|
|Alta|`faces.split_group` conserva plantillas del grupo original|Una cara separada puede seguir sirviendo como referencia equivocada|
|Alta|`faces.cluster_faces` incorpora referencias sin confirmar y usa umbrales cercanos al de pares SFace|Deriva de identidad y contaminación entre personas; no hay rechazo persistente|
|Alta|IDs faciales son SHA de archivo + índice|Cambiar metadatos cambia identidad; copias idénticas comparten override accidentalmente|
|Alta|Catálogo, personas, preferencias e historial en almacenes independientes|No hay transacciones entre movimientos, rutas e identidades|
|Alta|Resultados de grupos y trabajos solo en memoria|Reagrupamiento al abrir; progreso y cancelación no persistentes|
|Alta|Actualizador solo reemplaza código Python, admite 100 MB y no actualiza dependencias|No sirve para distribuir Qt ni para actualizar EXE|
|Media|Hash de píxeles convierte todo a RGB y procesa primer frame|Transparencia y secuencias pueden clasificarse incorrectamente como idénticas|
|Media|Galería sin visor/zoom, ordenación y combinaciones excluir/solos|No cubre exploración familiar ni búsquedas del documento|
|Media|Álbumes solo son movimientos, sin vista persistente|No existe pertenencia virtual a varios álbumes|
|Media|Modelos se aceptan por tamaño; no checksum|Descarga incompleta o alterada no está autenticada por contenido|
|Media|Pruebas predominantemente dibujos y vectores artificiales|No demuestran rendimiento ni reconocimiento de fotografías reales en Windows|

## Decisiones

Interfaz Qt separada de servicios. SQLite WAL con migración, IDs estables,
operaciones persistidas ANTES de tocar archivos y verificadas por SHA-256,
reanudación por archivo, caché de miniaturas asíncrona. No se envían fotos a APIs.
YuNet/SFace locales con modelos fijados por SHA-256; referencias confirmadas y
restricciones persistentes después de separar personas. Las versiones visuales
son pares para revisión, nunca autorización para apartar archivos.

La entrega permanece beta hasta superar la matriz Windows y una evaluación
representativa de edad, perfiles, familias y biblioteca del usuario. Las métricas
de un ejemplo no se presentan como precisión general.

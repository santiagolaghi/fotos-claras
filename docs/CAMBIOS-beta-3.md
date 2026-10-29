# Beta 3 · reconocimiento, escala y combinaciones

Se corrigieron problemas concretos de la implementación anterior. No hay
evidencia suficiente para atribuir todos los fallos de Santi al modelo facial,
ni para prometer reconocimiento completo sobre su colección sin medirla.

## Cambios del motor

- La detección usa dos escalas globales y ventanas superpuestas en fotos grandes.
  Se suprimen detecciones repetidas antes de contar rostros. Los rostros pequeños
  o borrosos cuentan como posibles terceros, pero su calidad limita la asociación
  automática a una identidad.
- Se conservan YuNet/SFace y su espacio de representaciones compatible. El motor
  de agrupamiento es nuevo: compara identidades nombradas en lotes NumPy, con hasta
  48 referencias confirmadas diversas por persona, en lugar de los primeros doce
  UUIDs. Conserva diferencias de apariencia que el usuario haya confirmado.
- Para personas sin nombre se usa un índice LSH acotado de anclas fijas. Es una
  búsqueda aproximada: puede dejar grupos separados. Las identidades nombradas
  se comparan exhaustivamente; las aproximaciones no prueban una identidad.
- Una coincidencia dudosa genera hasta tres candidatos para revisión. Confirmar
  agrega una referencia; rechazar guarda un veto permanente. No se usan asociaciones
  automáticas como referencias. Renombrar tampoco las convierte en confirmaciones.
- Se puede confirmar una persona directamente desde los rostros de una foto,
  aunque esa foto no aparezca entre sus sugerencias. No entrena de nuevo la red.
- Una actualización del detector conserva los IDs, nombres, separaciones y vetos
  por correspondencia geométrica. Un rostro confirmado que el detector nuevo omite
  se mantiene, en lugar de borrar la corrección.

## Cambios de rendimiento

El análisis, agrupamiento e indexación usan un proceso independiente iniciado
con `spawn`, compatible con el mecanismo de Windows y `freeze_support` de
PyInstaller. El worker reduce su prioridad y limita los hilos numéricos. La UI
recibe mensajes pequeños de avance y puede seguir navegando.

La pausa conserva lotes completados. Si un worker no responde durante doce
segundos tras pedir pausa, se termina ese proceso y SQLite revierte su transacción
incompleta. Este mecanismo **no se utiliza para movimientos de fotografías**,
que siguen su journal y cancelación cooperativa.

Las asignaciones se guardan en lotes de 128; el progreso se persiste por intervalo,
no con una sincronización de disco por cada rostro. Las consultas de vistas se
hacen fuera de Qt, con resultados descartados si la vista ya cambió. Galería,
personas, grupos grandes de duplicados y fichas cargan páginas de 240 registros.
Los metadatos de las fotos se separan de los blobs de huellas visuales.

Las miniaturas tienen 48 MiB de presupuesto, cola acotada y reintento cuando se
libera capacidad. El visor no conserva una cola ilimitada de fotografías obsoletas.
El cierre espera de forma asíncrona, manteniendo el bucle de eventos disponible.
La vista previa de archivos es un modelo virtual, no miles de objetos por celda.

## Álbumes por personas

«Organizar por personas» permite elegir Santi y Dai y ver los recuentos de:

- Solo las personas elegidas.
- Las personas elegidas con terceros, identificados o desconocidos.
- Todas las fotos donde aparecen juntas.

Cada combinación permite ver fotos o crear un álbum inteligente. La regla se
evalúa sobre el catálogo actualizado, sin duplicar archivos. Incluir/excluir
personas y cantidad de rostros siguen disponibles en los filtros de la galería.
Una foto con error o análisis pendiente no prueba que falten otras personas.
Los filtros de composición utilizan solo detecciones completadas.

## Evidencia y límites

`validation/tests-linux.txt`: 54 pruebas de catálogo, correcciones, migración,
procesos, cancelación, selección y widgets Qt. `validation/ui-real-results.json`:
recorrido de 17 comprobaciones con fotografías y modelos reales, incluyendo
álbum inteligente y confirmación de un rostro desde su fotografía.

`validation/face-scale.json`: 20.000 representaciones simuladas, 200 identidades.
Mide coste de agrupamiento y latencia de eventos durante navegación concurrente.
Es una carga sintética: su número de asociaciones correctas **no es una medición
de precisión sobre fotografías familiares**. El informe registra los tiempos
concretos de esta máquina, que no predicen el equipo del usuario.

`validation/benchmark.json`: 10.000 archivos que repiten ocho fotografías reales
redimensionadas. Comprueba escala de archivos y caché, no diez mil escenas únicas.

La prueba de fotos reales sigue siendo pequeña. Faltan una colección familiar
etiquetada, cambios de edad amplios, perfiles extremos, oclusiones, gemelos,
exportaciones reales de WhatsApp y Windows físico/DPI. Una cara no detectada
puede alterar «solo Santi»: no se puede certificar ausencia de otras personas
mediante un detector facial. No se añadió un detector de cuerpos.

Windows dispone del workflow ampliado; la verificación real depende de que
GitHub asigne un runner. No se publica la beta como estable ni se declara un
instalador probado a partir de los resultados de Linux.

## Migración

El esquema local pasa de v1 a v2 con respaldo previo mediante SQLite backup.
Se conservan nombres, IDs, fotografías, álbumes e historial. El catálogo sigue
en `catalog-v1.sqlite3` para mantener su ubicación; el formato se determina por
`PRAGMA user_version`, no por el nombre del archivo. El respaldo se llama
`catalog-v1-before-v2.sqlite3`.

El código antiguo rechaza correctamente un esquema más reciente. Volver a una
beta anterior incompatible requiere revisar compatibilidad del catálogo; no se
restaura un respaldo automáticamente porque eso perdería correcciones nuevas.
La prueba de instaladores usa dos marcadores de versión del mismo build actual;
no demuestra compatibilidad con el ejecutable histórico de beta 2.

Referencias técnicas:

- OpenCV: https://docs.opencv.org/4.13.0/d0/dd4/tutorial_dnn_face.html
- Modelos: https://github.com/opencv/opencv_zoo/tree/main/models
- Procesos: https://docs.python.org/3.12/library/multiprocessing.html

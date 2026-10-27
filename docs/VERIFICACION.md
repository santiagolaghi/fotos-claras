# Verificación · beta 0.9

## Alcance

Se ejecutan pruebas de SQLite, cambios incrementales, cancelación, duplicados
con distintos metadatos, transparencia/secuencias, píxeles TIFF de 16 bits, archivos corruptos, filtros
ALL/ONLY/WITH OTHERS/EXCLUDE, rostros desconocidos, álbumes, nombres, separación,
veto persistente, unión, coocurrencia, ignorados, reinicio, vistas previas,
colisiones, destinos que aparecen después de planificar, contenido modificado,
recuperación tras copiar antes de retirar origen, pausa de lotes, deshacer y
respaldo. Qt se ejercita en ocho secciones, dos tamaños, selección y visor,
y con trabajo en segundo plano comprobando que el bucle de eventos responde.

`tools/verify_real.py` usa fotografías públicas de pruebas de OpenCV y
face_recognition. Descarga con SHA-256 fijado. Detecta 0/1/2 rostros; compara dos
exposiciones diferentes de una misma persona y una distinta; verifica su
agrupación con SFace real, combinaciones de dos personas y persistencia.

Dos fotogramas deportivos reales parecidos (basketball1/2 de OpenCV) también
se comprueban como tomas diferentes. Separar/unir se repite con embeddings
reales; mover/deshacer se repite con una fotografía real y su identidad.

La recomprensión se simula con redimensionamiento y JPEG; **no es una
exportación obtenida de WhatsApp**. No se dispone de la colección privada del
usuario, ni de una muestra extensa con infancia/edad/perfiles/gemelos.
No se garantiza precisión Google Fotos. Esos casos necesitan evaluación humana.

`tools/benchmark.py` mide archivos reales redimensionados repetidos con nombres
diferentes. Prueba escala del catálogo/caché y pasos de indexación, no representa
10.000 fotografías originales únicas de alta resolución ni reconocimiento de
10.000 personas. Los JSON de `validation` registran plataforma y cifras medidas.

## Windows

El entorno de desarrollo local es Linux. No se afirma una prueba local Windows.
El workflow Windows instala dependencias fijadas, corre las pruebas, descarga
modelos y fotos reales, produce capturas, construye EXE e instalador Inno Setup,
instala dos directorios de versión del mismo ejecutable, abre el EXE instalado
y prueba vuelta al directorio anterior. Es una prueba del empaquetado y el
lanzador, no de compatibilidad entre dos esquemas futuros distintos.
Genera evidencia en el artefacto Windows-evidencia y el instalador por separado.
El código se publicó en la rama `reconstruccion/editorial-0.9` y en el
[PR #1](https://github.com/santiagolaghi/fotos-claras/pull/1). Se intentó ejecutar
Windows en los runs 40594878187 y 40594951437, pero GitHub no asignó un runner
por una restricción de la cuenta. **Ningún paso Windows llegó a ejecutarse y
no se generó instalador.** Se requiere resolver esa restricción y repetir la
ejecución. Solo una ejecución exitosa acredita esos pasos. Las capturas son Qt offscreen;
no equivalen a validación interactiva física de DPI 125/150/200, touch o varios
monitores. Esa comprobación manual continúa pendiente.

## Pendientes que impiden llamar estable a esta versión

- Validación con la colección familiar y fotografías reales de WhatsApp.
- Cambios de edad, perfiles, gemelos y rostros muy pequeños u ocultos.
- Ensayo manual Windows en diferentes escalas y hardware modesto/disco USB.
- Firma Authenticode y política final de publicación de Releases.
- Historial de movimientos 0.8: se importan los lotes cuyo destino actual puede
  verificarse; los demás se conservan intactos y se reevalúan al deshacer los
  posteriores. El hash se toma al importar: el formato antiguo no registraba
  el contenido original, por lo que no acredita integridad anterior a la migración.
- Evaluar material completo de múltiples frames: exactitud solo por bytes para
  secuencias; miniatura/rostros usan el primer frame, versiones no las incluyen.
- Interrupción durante una copia parcial: el origen queda intacto; se informa
  conflicto y se conserva el destino parcial. No se elimina automáticamente.

Los archivos originales no se sobrescriben ni se borran automáticamente. Un
movimiento confirmado retira el origen tras verificar una copia durable. Copia
verificada + journal no sustituye backups físicos contra fallos de hardware.

## Resultados locales de esta entrega

- Linux, Python 3.12, Qt 6.10.2, OpenCV 4.13.
- 29 pruebas automatizadas nuevas aprobadas, con errores de callback Qt
  tratados como fallos de prueba.
- Las 14 pruebas de la versión anterior pasaban antes de la reconstrucción;
  esto confirmó que no bastaban para demostrar los requisitos nuevos.
- Fotografías y modelos reales: ver `validation/real-results.json`.
- 10.000 archivos reales redimensionados: ver `validation/benchmark.json`.
- La UI se capturó y revisó a 1000×700 y 1440×900 en Qt offscreen/Linux.
- No se generó ni ejecutó un EXE Windows en Linux.

Fuentes técnicas: [SFace/YuNet](https://docs.opencv.org/4.12.0/d0/dd4/tutorial_dnn_face.html),
[Qt model/view](https://doc.qt.io/qtforpython-6.10/PySide6/QtWidgets/QListView.html).
Los umbrales de agrupación son decisiones conservadoras de esta app, no una
garantía de precisión publicada por OpenCV.

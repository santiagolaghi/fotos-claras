FOTOS CLARAS PARA WINDOWS · versión 0.7
=======================================

INSTALACIÓN
1. Descomprimí el ZIP completo en una carpeta de tu PC.
2. Ejecutá INSTALAR.bat una vez. Necesita internet y Python para Windows.
   Si no lo tenés, el instalador te indica el enlace oficial.
3. Ejecutá ABRIR.bat. Elegí la carpeta principal de tus fotos.
   El selector de Windows muestra carpetas, aunque adentro haya miles de fotos.
4. Esperá a que el contador termine. Se recorren también las subcarpetas.
   La próxima vez, Fotos Claras recordará la última carpeta y retomará el
   análisis automáticamente. Podés cambiar de carpeta con "Elegir carpeta".

MEMORIA DE LA APP
Se guardan en el perfil local de Windows: el catálogo de fotos y rostros, los
nombres y correcciones de personas, el historial para deshacer movimientos,
la última carpeta, la sección abierta, la persona que estabas mirando y el
filtro de cantidad de rostros. Al abrir otra vez, se reconstruyen las listas
desde la carpeta y la caché. Si ya habías buscado rostros, también se retoma
esa búsqueda automáticamente.

ACTUALIZACIONES EN LÍNEA
Esta versión se instala una vez: si ya tenías Fotos Claras, descomprimí el ZIP
sobre la carpeta anterior, sin borrar .venv. Si es tu primera instalación,
seguí los pasos de INSTALACIÓN. Al abrir con ABRIR.bat, la app consulta si hay
una versión más reciente publicada en
https://github.com/santiagolaghi/fotos-claras/releases
También podés tocar "Buscar actualizaciones". Si aceptás, descarga el paquete,
comprueba su integridad, actualiza los archivos de la app y vuelve a abrirla.
Las fotos, los álbumes, los nombres guardados y .venv quedan en su lugar.
Si una futura versión requiere nuevas dependencias de Python, ejecutá
INSTALAR.bat para incorporarlas. La opción automática corresponde a la app
abierta con ABRIR.bat; el .exe opcional no dispone de este actualizador.

CÓMO USARLA · NAVEGACIÓN LATERAL
- Duplicados exactos: agrupa fotos cuyos píxeles completos coinciden, aunque
  cambien el nombre o el formato. La primera está sugerida para conservar.
  "Marcar copias para apartar" marca las demás. Revisá la selección y movelas
  a FotosClaras_ParaRevisar. La app no borra archivos.
- Versiones por revisar: candidatos muy próximos, como algunos JPG enviados
  por WhatsApp. Cambió la compresión, el tamaño o ambos: la app no los llama
  duplicados exactos. Puede haber una toma diferente o versiones que no
  aparezcan aquí. Elegí manualmente cuáles mover.
- Personas: tocá "Buscar rostros". Al primer uso se descargan dos modelos de
  OpenCV. Seleccioná un grupo de la lista. A la derecha se muestran el rostro
  recortado y la foto completa. El botón "¿Quién es esta persona?" está ARRIBA
  de la lista; también podés hacer doble clic sobre el grupo. Escribí
  "Dai" o "Santiago" una sola vez: la app busca coincidencias entre los demás
  grupos y reúne las fotos encontradas. Revisá que sean de la misma persona.
  Si hay fotos de otra persona en ese grupo, seleccionalas y tocá "Separar
  fotos marcadas" antes de nombrarlo. Podés unir grupos que queden separados.
  Los nombres y correcciones se conservan para futuros análisis.
- Por cantidad de rostros: filtrá 0, 1, 2 o 3 o más caras. Seleccioná varias
  personas con Ctrl + clic: aparecerán las fotos en las que están todas,
  incluso si salen otras personas. Podés elegir las fotos y moverlas a álbum.
- Sin rostros: seleccioná y mové las fotos deseadas a un álbum.
- Álbumes: al mover, podés elegir una carpeta existente o crear una nueva
  debajo de Álbumes en la carpeta principal. Si se repite un nombre, la app
  lo numera para no reemplazar archivos. Confirmá el destino antes de mover.
  "Deshacer último movimiento" devuelve el lote a sus carpetas anteriores.
  Si modificás a mano un archivo movido, quizá no pueda deshacerse.

Los álbumes son carpetas reales. Una foto puede aparecer al buscar dos
personas, pero físicamente solo está en una carpeta por vez. Los nombres de
personas no trasladan fotos hasta que elegís la acción de mover.

LÍMITES CONOCIDOS
El reconocimiento de caras es una sugerencia: puede separar a una misma
persona en varios grupos o confundir caras. Revisá el grupo antes de ponerle
nombre y usá las acciones de separar y unir para corregirlo. Una cara muy
pequeña, de perfil o tapada puede no detectarse.
El filtro "Sin rostros" significa que el detector no encontró ninguno, no
que la imagen no tenga personas. Las versiones WhatsApp muy recortadas o con
muchos cambios podrían no sugerirse. Revisá visualmente cada movimiento.

Se leen JPG/JPEG, PNG, WebP, BMP, TIFF y HEIC/HEIF. Los originales se
procesan localmente; las fotos no se suben a internet. El catálogo y los
nombres se guardan en el perfil local del usuario. El primer análisis de
miles de fotos puede tardar; las lecturas posteriores reutilizan una caché.

EJECUTABLE OPCIONAL
Tras INSTALAR.bat, ejecutá CREAR_EXE.bat en Windows. El resultado queda en
"dist\Fotos Claras\Fotos Claras.exe". Este ZIP incluye código y scripts;
el ejecutable de Windows debe construirse y probarse en una PC Windows.

Modelos OpenCV Zoo:
https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet
https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface

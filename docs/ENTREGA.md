# Fotos Claras 0.9.0-beta.1 · avance de reconstrucción

Se reemplazó Tkinter por Qt y se implementó el estilo Álbum Editorial: marfil,
verde oliva, títulos editoriales, mosaico con fotos propias, tarjetas y navegación
lateral. El inicio abre el catálogo y no dispara un análisis pesado.

Funciones implementadas: indexación incremental cancelable; duplicados exactos
con orientación, alfa, perfil de color y precisión original; versiones visuales
separadas para revisión; detección YuNet y reconocimiento SFace locales; nombres,
correcciones por rostro, unir/separar/ignorar; filtros incluir/excluir/solos/con
otros y 0/1/2/3+ rostros; galería virtual con selección, favoritos y visor con
zoom; álbumes virtuales; copiar/mover/apartar con plan por archivo, integridad,
historial y recuperación; importación de nombres e historial antiguo verificable;
actualizador por instaladores versionados y lanzador Windows con recuperación.

**Esto todavía es una beta de código fuente, no un instalador Windows probado.**
Las pruebas locales se realizaron en Linux. Los scripts Windows y el workflow
están preparados, pero su subida al repositorio fue rechazada por la revisión
automática al no encontrar autorización explícita para publicación remota.
No se volvió a intentar esa publicación por otro medio.

La autorización pendiente se limita a subir el código y configuración de pruebas
a `santiagolaghi/fotos-claras`, rama `reconstruccion/editorial-0.9`, para ejecutar
el workflow Windows. No requiere subir fotografías familiares ni el diseño
adjunto, ni publicar una release estable.

El ZIP incluye el código, scripts para Windows, auditoría, arquitectura, pruebas,
resultados locales y capturas Qt con fotografías públicas de prueba. Las fotos
de prueba y modelos se descargan por los scripts con SHA-256 fijado; no se
incluyen como una biblioteca del usuario.

Consultar VERIFICACION.md para los límites y pendientes: Windows/DPI/hardware,
colección familiar real, exportación auténtica WhatsApp, edad y perfiles.

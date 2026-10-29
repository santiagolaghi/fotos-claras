# Fotos Claras 0.9.0-beta.3 · avance de reconstrucción

La beta 3 reemplaza el agrupamiento, aísla análisis en otro proceso y agrega
revisión de coincidencias, confirmación desde una foto y álbumes por combinación.
Ver [cambios, pruebas y límites](CAMBIOS-beta-3.md). Para aplicar la detección
nueva a resultados antiguos, ejecutar «Buscar rostros» una vez.

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
Las pruebas locales se realizaron en Linux. El código y la configuración de
pruebas ya están publicados en la rama `reconstruccion/editorial-0.9` del
repositorio y en el [PR #1](https://github.com/santiagolaghi/fotos-claras/pull/1).

GitHub creó las ejecuciones de Windows, pero las detuvo antes de asignar un
runner por una restricción de cuenta. No se ejecutaron pruebas allí ni se
generó un EXE o instalador. El PR permanece en borrador hasta poder completar
esa verificación. La versión no se publicó como estable.

El ZIP incluye el código, scripts para Windows, auditoría, arquitectura, pruebas,
resultados locales y capturas Qt con fotografías públicas de prueba. Las fotos
de prueba y modelos se descargan por los scripts con SHA-256 fijado; no se
incluyen como una biblioteca del usuario.

Consultar VERIFICACION.md para los límites y pendientes: Windows/DPI/hardware,
colección familiar real, exportación auténtica WhatsApp, edad y perfiles.

## Beta 2: carpeta y recorrido completo

El selector permite Examinar o pegar una ruta. Los errores se muestran
sin cerrar el cuadro; no se cambia la biblioteca si la validación falla
o se cancela. El análisis sigue siendo una acción explícita.

También se corrigió un fallo reproducido del doble clic que impedía abrir
el visor y las fichas de personas. Pasaron 38 pruebas automatizadas y un
recorrido con 15 comprobaciones de la UI sobre fotografías y modelos reales.
El reintento de Windows siguió bloqueado antes de ejecutar pasos.

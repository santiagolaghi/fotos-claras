FOTOS CLARAS 0.9.0-beta.1 · ALBUM EDITORIAL

INSTALACION WINDOWS
Usa Fotos-Claras-Setup.exe, generado por el workflow Windows del repositorio.
Instala y abre Fotos Claras desde el acceso directo. No necesita Python.
Esta version es beta: consultar docs/VERIFICACION.md para evidencia y limites.

PRIMER USO
1. Elegi la carpeta principal con tus fotos. Cambiarla no inicia un analisis.
2. Toca Actualizar biblioteca. Podes pausar y continuar por archivo.
3. Busca rostros. Solo la primera vez descarga modelos locales verificados.
4. En Personas, doble clic en un grupo: revisa los rostros y guarda el nombre.
5. Galeria > Filtrar permite incluir/excluir personas y buscar solo ellas o con otras.
6. Selecciona fotografias (un clic marca, doble clic amplia) y toca Organizar.

Un album virtual conserva cada archivo en su ubicacion. Copiar conserva el
original y crea otro archivo. Mover cambia su carpeta real. La vista previa
muestra cada origen y destino; nada se mueve antes de confirmar.
Apartar mueve a FotosClaras_ParaRevisar. Configuracion > Historial permite
reanudar lotes interrumpidos y deshacer pasos completados. No sobrescribe.
Al deshacer una copia, se guarda en la carpeta de recuperacion de la app.

SEGURIDAD Y PERSISTENCIA
Catalogo, personas y operaciones: %LOCALAPPDATA%\FotosClaras\catalog-v1.sqlite3
Los nombres anteriores se importan de personas_v2.json o personas.json, que
se conservan intactos. El cambio de algoritmo requiere una primera indexacion
del catalogo nuevo; luego solo se recalculan fotos nuevas o modificadas.
Las detecciones, correcciones, filtros y albumes se conservan al cerrar.
El historial importa lotes antiguos cuyo destino actual se puede verificar;
los JSON originales se conservan. Su formato no acreditaba integridad previa
a esta migracion. El historial nuevo registra SHA-256 desde la planificacion. Ver docs/VERIFICACION.md.

Los rostros y versiones son sugerencias; las tomas parecidas no son exactas.
Sin rostros significa detector completado sin caras, no ausencia de personas.
Errores tecnicos se muestran por separado en Configuracion.

ACTUALIZACIONES
Configuracion > Buscar actualizaciones: consulta Releases oficiales y verifica
SHA-256 antes de ejecutar el instalador. Cada version se instala separadamente;
la anterior queda disponible en Inicio > Volver a la version anterior.
No se modifica la carpeta de fotografias ni la base local al instalar.
Los modelos y fotos se procesan localmente; no requiere una API GPT.

CODIGO FUENTE (alternativa para desarrollo)
Necesita Python 3.12 de 64 bits: ejecutar INSTALAR.bat, luego ABRIR.bat.
CREAR_EXE.bat construye una version portable; para la instalacion con rollback,
usar el workflow Windows y su instalador Inno Setup.

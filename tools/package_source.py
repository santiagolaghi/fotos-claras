"""Package reviewed source and local verification evidence; never include user photos/state."""
import hashlib
import json
import runpy
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
output=Path(sys.argv[1]).resolve();output.parent.mkdir(parents=True,exist_ok=True)
tracked=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
files=[ROOT/name for name in tracked if name and (ROOT/name).is_file()]
files+=sorted((ROOT/'validation/screenshots').glob('*.png'))
files=list(dict.fromkeys(files));manifest=[]
for path in files:
    rel=path.relative_to(ROOT).as_posix()
    if any(word in rel.split('/') for word in ('.git','upload','real','models','__pycache__')):raise ValueError('Ruta excluida: '+rel)
    if path.suffix in ('.sqlite3','.onnx','.exe'):raise ValueError('Estado/binario no permitido: '+rel)
    manifest.append(dict(path=rel,size=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
version=runpy.run_path(str(ROOT/'FotosClaras/fotosclaras/__init__.py'))['__version__']
base=f'Fotos-Claras-{version}/'
with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
    for path in files:z.write(path,base+path.relative_to(ROOT).as_posix())
    z.writestr(base+'MANIFEST.json',json.dumps(manifest,indent=2,ensure_ascii=False))
    z.writestr(base+'EMPEZAR.txt',
       f'FOTOS CLARAS {version} - CODIGO Y PRUEBAS\n\n'
       'No es un instalador EXE Windows ya verificado.\n'
       'Lee docs/ENTREGA.md y docs/VERIFICACION.md.\n'
       'Alternativa de desarrollo: FotosClaras/INSTALAR.bat, luego ABRIR.bat.\n'
       'El instalador completo se genera mediante el workflow Windows pendiente.\n')
print(json.dumps(dict(file=str(output),size=output.stat().st_size,files=len(files),sha256=hashlib.sha256(output.read_bytes()).hexdigest()),indent=2))

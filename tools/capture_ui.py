"""Capture all real Qt screens, using public fixtures only. Used on Windows CI too."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import shutil
import sys
import tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'FotosClaras'))
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from real_fixtures import download
from fotosclaras.db import Catalog
from fotosclaras.indexer import scan
from fotosclaras.identity import analyze
from fotosclaras.ui import MainWindow

fixtures=download(ROOT/'validation/real');out=ROOT/'validation/screenshots';out.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp);photos=root/'fotos';shutil.copytree(fixtures,photos)
    shutil.copy2(photos/'obama.jpg',photos/'copia.jpg')
    with Catalog(root/'data/catalog.sqlite3') as c:library=c.library(photos)['id'];path=c.path
    scan(path,library)
    shutil.copytree(ROOT/'validation/models',root/'data/models')
    analyze(path,library)
    app=QApplication.instance() or QApplication([]);w=MainWindow(path);w.show()
    for size in [(1440,900),(1000,700)]:
        w.resize(*size)
        for n in range(8):
            w.navigate(n);QTest.qWait(250);w.grab().save(str(out/f'{size[0]}-{n}.png'))
    w.close()
print(out)

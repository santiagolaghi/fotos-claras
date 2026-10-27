"""Windows desktop entry point (Qt). Run app.py --smoke for unattended UI check."""
import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from fotosclaras.db import data_dir


def main():
    log=logging.getLogger('fotosclaras');log.setLevel(logging.INFO)
    handler=RotatingFileHandler(data_dir()/'diagnostico-v1.log',maxBytes=2_000_000,backupCount=3,encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'));log.addHandler(handler)
    from PySide6.QtWidgets import QApplication,QMessageBox
    from PySide6.QtCore import QTimer,QLockFile
    from fotosclaras.ui import MainWindow
    app=QApplication(sys.argv);app.setApplicationName('Fotos Claras');app.setOrganizationName('FotosClaras')
    # Prevent two independent jobs from modifying the same local catalog/files.
    lock=QLockFile(str(data_dir()/'catalog-v1.lock'));lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None,'Fotos Claras','Fotos Claras ya está abierta con este catálogo.');return 1
    def uncaught(kind,error,tb):
        log.critical('Error de interfaz',exc_info=(kind,error,tb))
        QMessageBox.critical(None,'Fotos Claras',f'Ocurrió un error: {error}\nEl detalle quedó en el diagnóstico.')
    sys.excepthook=uncaught
    window=MainWindow();window.show()
    if '--smoke' in sys.argv:
        def finish():
            output=Path(os.environ.get('FOTOSCLARAS_SMOKE_DIR','.'));output.mkdir(parents=True,exist_ok=True)
            window.grab().save(str(output/'windows-home.png'));window.close()
        QTimer.singleShot(1500,finish)
    code=app.exec();lock.unlock();return code

if __name__=='__main__':sys.exit(main())

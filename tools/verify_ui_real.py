"""Drive the real Qt UI on public photographs, including the actual folder dialog."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'FotosClaras'))
from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import QApplication,QDialog,QMessageBox,QLineEdit,QPushButton,QListWidget,QComboBox,QInputDialog,QDialogButtonBox
from PySide6.QtTest import QTest
from PIL import Image
from fotosclaras.db import Catalog
from fotosclaras.ui import MainWindow
from fotosclaras.widgets import Viewer
from fotosclaras.identity import ensure_models
from real_fixtures import download

app=None
results=[];errors=[];watchers=[]
sys.excepthook=lambda *e:errors.append(str(e[1]))


def wait(predicate,timeout=20000):
    end=time.monotonic()+timeout/1000
    while not predicate() and not errors and time.monotonic()<end:QTest.qWait(20)
    if errors:raise AssertionError(errors)
    if not predicate():raise AssertionError('La UI no completó el paso antes del límite')


def check(name,condition):
    assert condition,name
    results.append(name);print('OK:',name,flush=True)


def click(parent,text):
    matches=[b for b in parent.findChildren(QPushButton) if b.text()==text and b.isVisible()]
    assert len(matches)==1,(text,[b.text() for b in parent.findChildren(QPushButton)])
    QTest.mouseClick(matches[0],Qt.LeftButton)


def arm(title,action,timeout=15000):
    """Act on a dialog while the real modal UI handler is on the stack."""
    timer=QTimer();start=time.monotonic();state={'done':False}
    def poll():
        modal=app.activeModalWidget()
        if modal is not None and (title is None or modal.windowTitle()==title):
            timer.stop()
            try:action(modal);state['done']=True
            except Exception as exc:
                errors.append(str(exc));modal.reject()
        elif time.monotonic()-start>timeout/1000:
            timer.stop();errors.append('No apareció el diálogo: '+str(title))
            if modal:modal.reject()
    timer.timeout.connect(poll);timer.start(20);watchers.append(timer)
    return state


def yes(dialog):
    assert isinstance(dialog,QMessageBox)
    QTest.mouseClick(dialog.button(QMessageBox.Yes),Qt.LeftButton)


def run():
    global app
    app=QApplication.instance() or QApplication([])
    fixtures=download(ROOT/'validation/real');ensure_models(ROOT/'validation/models')
    screenshots=ROOT/'validation/screenshots';screenshots.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);photos=root/'Fotos de familia – prueba';photos.mkdir()
        for name in ['obama.jpg','obama2.jpg','biden.jpg','two_people.jpg','scenery.jpg']:
            shutil.copy2(fixtures/name,photos/name)
        shutil.copy2(photos/'obama.jpg',photos/'obama (2).jpg')
        with Image.open(photos/'obama.jpg') as img:img.resize((455,568)).save(photos/'whatsapp.jpg',quality=68)
        path=root/'data/catalog.sqlite3';shutil.copytree(ROOT/'validation/models',path.parent/'models')
        w=MainWindow(path);w.show();QTest.qWait(150)
        QTest.mouseClick(w.library_button,Qt.LeftButton);wait(lambda:w._folder_picker is not None)
        picker=w._folder_picker;picker.grab().save(str(screenshots/'folder-picker.png'))
        picker.path_edit.setText(str(photos));QTest.mouseClick(picker.submit_button,Qt.LeftButton)
        wait(lambda:not w.busy)
        check('Elegir carpeta desde botón real',w.library is not None and w.library['path']==str(photos))
        check('Elegir no inicia análisis',w.catalog.one('SELECT COUNT(*) n FROM jobs')['n']==0)
        QTest.mouseClick(w.scan_button,Qt.LeftButton);wait(lambda:not w.busy)
        library=w.library['id'];check('Analizar desde botón real',len(w.catalog.photos(library))==7)
        QTest.mouseClick(w.nav[1],Qt.LeftButton);wait(lambda:w.current_grid is not None)
        check('Galería cargada después del análisis',len(w.current_grid.records())==7)
        def inspect_viewer(dialog):
            assert isinstance(dialog,Viewer)
            wait(lambda:len(dialog.left.scene().items())>0)
            QTest.keyClick(dialog,Qt.Key_Right)
            click(dialog,'Ajustar')
            QTest.keyClick(dialog,Qt.Key_F11);assert dialog.isFullScreen()
            QTest.keyClick(dialog,Qt.Key_F11);QTest.keyClick(dialog,Qt.Key_Escape)
        armed=arm('Fotos Claras · Visor',inspect_viewer)
        view=w.current_grid;QTest.mouseDClick(view.viewport(),Qt.LeftButton,Qt.NoModifier,view.visualRect(view.model().index(0)).center())
        wait(lambda:armed['done']);check('Visor real: imagen, navegación, ajuste, pantalla completa',True)
        # Quarantine only the duplicate, then undo using the actual history dialogs.
        QTest.mouseClick(w.nav[2],Qt.LeftButton);wait(lambda:w.current_grid is not None);click(w,'Seleccionar copias sugeridas')
        chosen=w.selected();check('Selección de una copia sugerida',len(chosen)==1)
        selected_path=Path(chosen[0]['path'])
        armed=arm('Revisá exactamente qué ocurrirá',lambda d:QTest.mouseClick(d.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok),Qt.LeftButton))
        click(w,'Apartar seleccionadas de la biblioteca');wait(lambda:armed['done'] and not w.busy)
        check('Apartar con vista previa y confirmación',not selected_path.exists() and len(w.catalog.photos(library))==6)
        def undo_dialog(dialog):
            listing=dialog.findChild(QListWidget);listing.setCurrentRow(0)
            arm('Deshacer operación',yes);click(dialog,'Deshacer seleccionada')
        armed=arm('Historial y recuperación',undo_dialog)
        w.history();wait(lambda:armed['done'] and not w.busy)
        check('Deshacer desde historial real',selected_path.exists() and len(w.catalog.photos(library))==7)
        # Detect real faces and name both groups through the actual person dialog.
        QTest.mouseClick(w.face_button,Qt.LeftButton);wait(lambda:not w.busy,60000)
        check('Modelos reales desde botón Buscar rostros',len(w.catalog.people(library))==2)
        def person_for(filename):
            return w.catalog.one('SELECT f.person_id FROM faces f JOIN photos p ON p.id=f.photo_id WHERE p.path=?',(str(photos/filename),))['person_id']
        a,b=person_for('obama.jpg'),person_for('biden.jpg')
        for person,name in [(a,'Persona A'),(b,'Persona B')]:
            QTest.mouseClick(w.nav[4],Qt.LeftButton);wait(lambda:w.current_grid is not None)
            view=w.current_grid;row=next(i for i,p in enumerate(view.records()) if p['id']==person)
            def identify(dialog,name=name):
                field=dialog.findChild(QLineEdit);field.setText(name)
                wait(lambda:dialog.save.isEnabled())
                click(dialog,'Guardar nombre y buscar más coincidencias')
            armed=arm('¿Quién es esta persona?',identify)
            QTest.mouseDClick(view.viewport(),Qt.LeftButton,Qt.NoModifier,view.visualRect(view.model().index(row)).center())
            wait(lambda:armed['done'] and not w.busy)
        check('Nombrar grupos desde Personas',w.catalog.one('SELECT COUNT(*) n FROM people WHERE name<>\'\'')['n']==2)
        QTest.mouseClick(w.nav[1],Qt.LeftButton);wait(lambda:w.current_grid is not None)
        def filter_pair(dialog):
            include=dialog.findChildren(QListWidget)[0]
            wait(lambda:include.count()==2)
            for i in range(include.count()):
                if include.item(i).data(Qt.UserRole) in (a,b):include.item(i).setCheckState(Qt.Checked)
            mode,count=dialog.findChildren(QComboBox);mode.setCurrentIndex(1);count.setCurrentIndex(3)
            click(dialog,'Ver fotografías')
        armed=arm('Encontrá a tus personas',filter_pair);click(w,'Filtrar personas y rostros');wait(lambda:armed['done'] and w.current_grid is not None)
        check('Filtro UI: ambas personas, solo ellas, exactamente 2 rostros',len(w.current_grid.records())==1 and Path(w.current_grid.records()[0]['path']).name=='two_people.jpg')
        w.grab().save(str(screenshots/'real-filter-pair.png'))
        w.current_grid.selectAll()
        def organize(dialog):
            def album_name(d):
                assert isinstance(d,QInputDialog);d.setTextValue('Álbum de prueba');d.accept()
            arm('Nuevo álbum',album_name)
            arm('Agregar a álbum',yes)
            click(dialog,'Continuar a vista previa')
        armed=arm('Organizar fotografías',organize);click(w,'Organizar selección');wait(lambda:armed['done'])
        album=w.catalog.one('SELECT id FROM albums WHERE name=?',('Álbum de prueba',))
        check('Crear álbum virtual y agregar desde diálogo real',bool(album) and len(w.catalog.photos(library,album=album['id']))==1)
        check('Álbum virtual conserva ubicación física',(photos/'two_people.jpg').is_file())
        # The person-composition dialog creates a live rule, without copying files.
        def composition(dialog):
            for i in range(dialog.list.count()):dialog.list.item(i).setCheckState(Qt.Checked)
            wait(lambda:dialog.rows['only'][1].isEnabled())
            assert '1 fotos' in dialog.rows['only'][0].text()
            def title(d):d.setTextValue('Pareja · inteligente');d.accept()
            arm('Álbum inteligente',title)
            QTest.mouseClick(dialog.rows['only'][2],Qt.LeftButton)
            wait(lambda:'creado' in dialog.message.text())
            dialog.grab().save(str(screenshots/'people-composition.png'))
            QTest.mouseClick(dialog.rows['only'][1],Qt.LeftButton)
        wait(lambda:w.current_grid is not None)
        armed=arm('Organizar por personas',composition);click(w,'Organizar por personas');wait(lambda:armed['done'] and w.current_grid is not None)
        smart=w.catalog.one('SELECT id,rule FROM albums WHERE name=?',('Pareja · inteligente',))
        check('Composición y álbum inteligente desde diálogo real',bool(smart['rule']) and w.catalog.photo_count(library,album=smart['id'])==1)
        w.current_grid.selectAll()
        def identify_photo(dialog):
            wait(lambda:len(dialog.grid.records())==2 and dialog.confirm.isEnabled())
            face=dialog.grid.records()[0];dialog.grid.selectionModel().select(dialog.grid.model().index(0),__import__('PySide6.QtCore',fromlist=['QItemSelectionModel']).QItemSelectionModel.Select)
            dialog.person.setCurrentText(face['name']);QTest.mouseClick(dialog.confirm,Qt.LeftButton)
        armed=arm('Identificar rostros de esta foto',identify_photo)
        click(w,'Identificar rostros de la foto seleccionada');wait(lambda:armed['done'] and not w.busy)
        check('Confirmar una identidad directamente desde la foto',True)
        QTest.mouseClick(w.nav[6],Qt.LeftButton);wait(lambda:w.current_grid is not None)
        check('Sin rostros en UI distingue análisis completado',len(w.current_grid.records())==1 and Path(w.current_grid.records()[0]['path']).name=='scenery.jpg')
        w.close();wait(lambda:w._closed);w=MainWindow(path);w.show();QTest.qWait(100)
        check('Reinicio conserva nombres, fotos y álbum',not w.busy and len(w.catalog.people(library))==2 and len(w.catalog.photos(library,album=album['id']))==1)
        w.close();wait(lambda:w._closed)
    assert not errors,errors
    report=dict(platform=sys.platform,status='passed',assertions=results,photos='Public face_recognition/OpenCV fixtures, not private family photos',mocked_file_picker=False,scope='Actual Qt dialogs/widgets driven in offscreen mode; not a physical Windows desktop test')
    (ROOT/'validation/ui-real-results.json').write_text(json.dumps(report,indent=2,ensure_ascii=False))
    print(json.dumps(report,indent=2,ensure_ascii=False))

if __name__=='__main__':
    try:run()
    except Exception:
        import traceback
        traceback.print_exc();print('Errores de callbacks:',errors,file=sys.stderr);sys.exit(1)

"""Exercise real buttons/dialogs/event loop, not a mocked file-picker return."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from PySide6.QtWidgets import QApplication,QPushButton,QLineEdit,QFileDialog,QDialogButtonBox
from PySide6.QtCore import Qt,QTimer
from PySide6.QtTest import QTest

from fotosclaras.db import Catalog
from fotosclaras.ui import MainWindow
from fotosclaras.dialogs import validate_directory

app=QApplication.instance() or QApplication([])


def until(predicate,timeout=6000):
    end=time.monotonic()+timeout/1000
    while not predicate() and time.monotonic()<end:QTest.qWait(15)
    if not predicate():raise AssertionError('El recorrido de interfaz no completó el paso esperado')


class FolderFlow(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.photos=self.root/'Fotos de familia – álbum';self.photos.mkdir()
        Image.new('RGB',(140,110),'#747f5c').save(self.photos/'foto.png')
        self.path=self.root/'state/catalog.sqlite3';self.w=MainWindow(self.path)
        self.errors=[];self.old_hook=sys.excepthook;sys.excepthook=lambda *exc:self.errors.append(exc)
        self.w.show();QTest.qWait(100)
    def tearDown(self):
        if self.w.busy:
            self.w.cancel_job();until(lambda:not self.w.busy)
        self.w.close();QTest.qWait(100);sys.excepthook=self.old_hook
        self.tmp.cleanup();self.assertFalse(self.errors,str(self.errors))
    def open_picker(self):
        QTest.mouseClick(self.w.library_button,Qt.LeftButton)
        until(lambda:self.w._folder_picker is not None and self.w._folder_picker.isVisible())
        return self.w._folder_picker
    def paste(self,field,text):
        app.clipboard().setText(text);field.setFocus();QTest.keyClick(field,Qt.Key_A,Qt.ControlModifier);QTest.keyClick(field,Qt.Key_V,Qt.ControlModifier)
    def use_path(self,path):
        picker=self.open_picker();self.paste(picker.path_edit,str(path));QTest.mouseClick(picker.submit_button,Qt.LeftButton)
        until(lambda:not self.w.busy)
        return picker
    def test_header_choose_real_dialog_paste_scan_gallery_and_restart(self):
        self.use_path(self.photos)
        self.assertIsNone(self.w._folder_picker);self.assertEqual(self.w.library['path'],str(self.photos.resolve()))
        self.assertEqual(self.w.catalog.one('SELECT COUNT(*) n FROM jobs')['n'],0)
        self.assertIn('Actualizar biblioteca',self.w.status.text())
        QTest.mouseClick(self.w.scan_button,Qt.LeftButton);until(lambda:not self.w.busy)
        self.assertEqual(len(self.w.catalog.photos(self.w.library['id'])),1)
        QTest.mouseClick(self.w.nav[1],Qt.LeftButton);QTest.qWait(100)
        self.assertEqual(len(self.w.current_grid.records()),1)
        self.w.close();self.w=MainWindow(self.path);self.w.show();QTest.qWait(100)
        self.assertFalse(self.w.busy);self.assertEqual(self.w.library['path'],str(self.photos.resolve()))
        self.assertEqual(len(self.w.catalog.photos(self.w.library['id'])),1)
    def test_welcome_button_opens_visible_picker(self):
        welcome=next(b for b in self.w.findChildren(QPushButton) if b.text()=='Elegir mi biblioteca' and b.isVisible())
        QTest.mouseClick(welcome,Qt.LeftButton);until(lambda:self.w._folder_picker is not None)
        picker=self.w._folder_picker;self.assertTrue(picker.isVisible());picker.reject()
        self.assertIsNone(self.w.library)
    def test_real_browser_selects_folder_and_timers_continue(self):
        picker=self.open_picker();self.paste(picker.path_edit,str(self.root))
        QTest.mouseClick(picker.browse_button,Qt.LeftButton)
        until(lambda:picker._browser is not None and picker._browser.isVisible())
        browser=picker._browser
        self.assertTrue(browser.testOption(QFileDialog.DontUseNativeDialog))
        ticks=[];timer=QTimer();timer.timeout.connect(lambda:ticks.append(1));timer.start(10)
        QTest.qWait(150);timer.stop();self.assertGreater(len(ticks),3)
        field=browser.findChild(QLineEdit,'fileNameEdit');self.assertIsNotNone(field)
        self.paste(field,str(self.photos));QTest.keyClick(field,Qt.Key_Return)
        until(lambda:self.w.library is not None)
        self.assertEqual(self.w.library['path'],str(self.photos.resolve()))
        self.assertIsNone(self.w._folder_picker)
    def test_invalid_and_file_path_stay_visible_then_retry(self):
        picker=self.use_path(self.root/'inexistente')
        self.assertTrue(picker.isVisible());self.assertIn('No encontramos',picker.feedback.text());self.assertIsNone(self.w.library)
        self.paste(picker.path_edit,str(self.photos/'foto.png'));QTest.mouseClick(picker.submit_button,Qt.LeftButton);until(lambda:not self.w.busy)
        self.assertIn('archivo',picker.feedback.text());self.assertIsNone(self.w.library)
        self.paste(picker.path_edit,str(self.photos));QTest.mouseClick(picker.submit_button,Qt.LeftButton);until(lambda:self.w.library is not None)
    def test_cancel_preserves_library_and_last_folder(self):
        self.use_path(self.photos);old=self.w.library['id'];picker=self.open_picker()
        self.paste(picker.path_edit,str(self.root));QTest.mouseClick(picker.buttons.button(QDialogButtonBox.Cancel),Qt.LeftButton)
        self.assertEqual(self.w.library['id'],old);self.assertEqual(self.w.catalog.pref('last_library'),old)
    def test_cancel_during_validation_does_not_apply_late_result(self):
        self.use_path(self.photos);old=self.w.library['id'];picker=self.open_picker();started=threading.Event();release=threading.Event()
        def slow(path,cancel):started.set();release.wait(3);return str(self.root)
        with patch('fotosclaras.ui.validate_directory',side_effect=slow):
            self.paste(picker.path_edit,str(self.root));QTest.mouseClick(picker.submit_button,Qt.LeftButton)
            until(started.is_set);QTest.mouseClick(picker.buttons.button(QDialogButtonBox.Cancel),Qt.LeftButton);release.set();until(lambda:not self.w.busy)
        self.assertEqual(self.w.library['id'],old);self.assertEqual(self.w.catalog.pref('last_library'),old)
    def test_permission_error_is_inline_not_silent(self):
        picker=self.open_picker();self.paste(picker.path_edit,str(self.photos))
        with patch('fotosclaras.dialogs.os.scandir',side_effect=PermissionError('denied')):
            QTest.mouseClick(picker.submit_button,Qt.LeftButton);until(lambda:not self.w.busy)
        self.assertIn('permiso',picker.feedback.text());self.assertTrue(picker.isVisible());self.assertIsNone(self.w.library)
    def test_quoted_and_empty_paths(self):
        self.assertEqual(validate_directory('"'+str(self.photos)+'"'),str(self.photos.resolve()))
        with self.assertRaisesRegex(ValueError,'Elegí'):validate_directory(' ')

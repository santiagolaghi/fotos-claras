import os
import sys
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile
import threading
import time
import unittest
from pathlib import Path
from PIL import Image
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt,QTimer
from PySide6.QtTest import QTest
from fotosclaras.db import Catalog
from fotosclaras.indexer import scan
from fotosclaras.ui import MainWindow

app=QApplication.instance() or QApplication([])

class QtFlow(unittest.TestCase):
    def setUp(self):
        self.uncaught=[];self.old_hook=sys.excepthook;sys.excepthook=lambda *exc:self.uncaught.append(exc)
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);photos=self.root/'fotos';photos.mkdir()
        for i in range(12):Image.new('RGB',(300,240),(i*20,100,80)).save(photos/f'foto-{i}.jpg')
        self.path=self.root/'data/catalog.sqlite3'
        with Catalog(self.path) as c:self.library=c.library(photos)['id']
        scan(self.path,self.library,compare=False)
        self.w=MainWindow(self.path);self.w.show();QTest.qWait(200)
    def tearDown(self):
        self.w.close();QTest.qWait(100);self.temp.cleanup();sys.excepthook=self.old_hook
        self.assertFalse(self.uncaught,str(self.uncaught))
    def test_all_sections_resize_persistence_no_auto_scan(self):
        self.assertFalse(self.w.busy)
        with Catalog(self.path) as c:before=c.one('SELECT COUNT(*) n FROM jobs')['n']
        for scale in [(1000,700),(1440,900)]:
            self.w.resize(*scale)
            for n in range(8):self.w.navigate(n);QTest.qWait(30)
        self.assertFalse(self.w.busy)
        with Catalog(self.path) as c:self.assertEqual(c.one('SELECT COUNT(*) n FROM jobs')['n'],before)
    def test_gallery_click_multiselect_and_viewer(self):
        self.w.navigate(1);QTest.qWait(150);view=self.w.current_grid
        for i in range(2):
            rect=view.visualRect(view.model().index(i));QTest.mouseClick(view.viewport(),Qt.LeftButton,Qt.NoModifier,rect.center())
        self.assertEqual(len(view.selected()),2)
        view.selectAll();self.assertEqual(len(view.selected()),12)
        from fotosclaras.widgets import Viewer
        viewer=Viewer(view.records(),0,self.w);viewer.show();QTest.qWait(300);viewer.step(1);viewer.fit();QTest.qWait(200);viewer.close()
    def test_background_job_keeps_event_loop_responsive(self):
        ticks=[];timer=QTimer();timer.timeout.connect(lambda:ticks.append(1));timer.start(10)
        def work(cancel,report):
            for i in range(40):
                if cancel.is_set():break
                time.sleep(.01);report('prueba',i,40)
        self.w.run(work);QTest.qWait(200);self.assertTrue(self.w.busy);self.w.cancel_job();QTest.qWait(200)
        self.assertFalse(self.w.busy);self.assertGreater(len(ticks),8);timer.stop()

    def test_gallery_double_click_and_enter_activate_exactly_once(self):
        from fotosclaras.widgets import PhotoView
        view=PhotoView(self.w.thumbs);view.set_records(self.w.catalog.photos(self.library));view.show();QTest.qWait(80)
        hits=[];view.doubleClicked.connect(lambda index:hits.append(index.row()))
        rect=view.visualRect(view.model().index(0))
        QTest.mouseClick(view.viewport(),Qt.LeftButton,Qt.NoModifier,rect.center())
        QTest.mouseDClick(view.viewport(),Qt.LeftButton,Qt.NoModifier,rect.center())
        self.assertEqual(hits,[0]);QTest.keyClick(view,Qt.Key_Return);self.assertEqual(hits,[0,0]);view.close()

import os
import sys
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from pathlib import Path
from PIL import Image
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt,QTimer
from PySide6.QtTest import QTest
from fotosclaras.db import Catalog
from fotosclaras.indexer import scan
from fotosclaras.ui import MainWindow

app=QApplication.instance() or QApplication([])

def until(predicate,timeout=8000):
    end=time.monotonic()+timeout/1000
    while not predicate() and time.monotonic()<end:QTest.qWait(15)
    if not predicate():raise AssertionError('No se completó la consulta de interfaz')

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
        self.w.close();until(lambda:self.w._closed);self.temp.cleanup();sys.excepthook=self.old_hook
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
        self.w.navigate(1);until(lambda:self.w.current_grid is not None);view=self.w.current_grid
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

    def test_real_spawned_analysis_keeps_navigation_responsive(self):
        ticks=[];timer=QTimer();timer.timeout.connect(lambda:ticks.append(time.monotonic()));timer.start(10)
        self.w.run_analysis('regroup');pid=self.w.task.process.pid
        self.assertNotEqual(pid,os.getpid());self.w.navigate(1)
        until(lambda:not self.w.busy and self.w.current_grid is not None)
        timer.stop();self.assertGreater(len(ticks),8);self.assertEqual(len(self.w.current_grid.records()),12)

    def test_slow_catalog_query_never_blocks_event_loop_or_replaces_new_page(self):
        from fotosclaras.library_view import load_page
        def slow(*args):time.sleep(.25);return load_page(*args)
        ticks=[];timer=QTimer();timer.timeout.connect(lambda:ticks.append(1));timer.start(10)
        with patch('fotosclaras.ui.load_page',side_effect=slow):
            self.w.navigate(1);QTest.qWait(50);self.w.navigate(6)
            until(lambda:self.w.current_grid is not None)
        timer.stop();self.assertGreater(len(ticks),10);self.assertEqual(self.w.section,6)
        self.assertEqual(len(self.w.current_grid.records()),0)

    def test_cancel_spawned_analysis_preserves_catalog(self):
        self.w.run_analysis('regroup');self.w.cancel_job();until(lambda:not self.w.busy)
        self.assertEqual(self.w.catalog.photo_count(self.library),12)
        self.assertIn('Pausado',self.w.status.text())

    def test_review_dialog_confirms_a_probable_face_through_real_widgets(self):
        import numpy as np
        from fotosclaras.people_ui import PersonDialog
        photos=self.w.catalog.photos(self.library)
        with self.w.catalog.db:
            self.w.catalog.db.execute("INSERT INTO people(id,name) VALUES ('s','Santi')")
            for key,photo,person,locked in [('reference',photos[0],'s',1),('candidate',photos[1],None,0)]:
                self.w.catalog.db.execute("INSERT INTO faces(id,photo_id,ordinal,person_id,vector,box,thumb,locked) VALUES (?,?,0,? ,?,'[0,0,1,1]',?,?)",
                    (key,photo['id'],person,np.array([1.,0.,0.],dtype=np.float32).tobytes(),photo['path'],locked))
                self.w.catalog.db.execute("UPDATE photos SET face_state='done' WHERE id=?",(photo['id'],))
            self.w.catalog.db.execute("INSERT INTO face_candidates VALUES ('candidate','s',.4)")
        dialog=PersonDialog(self.path,self.library,dict(id='s',name='Santi'),self.w.thumbs,self.w);dialog.show()
        requests=[];dialog.searchRequested.connect(lambda:requests.append(True));dialog.tabs.setCurrentIndex(1)
        until(lambda:len(dialog.views[1].records())==1);dialog.views[1].selectAll()
        from PySide6.QtWidgets import QPushButton
        confirm=next(b for b in dialog.findChildren(QPushButton) if b.text()=='Sí, es esta persona')
        QTest.mouseClick(confirm,Qt.LeftButton);until(lambda:dialog.completed)
        face=self.w.catalog.one("SELECT person_id,locked,match_state FROM faces WHERE id='candidate'")
        self.assertEqual(face,dict(person_id='s',locked=1,match_state='confirmed'));self.assertEqual(requests,[True]);dialog.deleteLater()

    def test_gallery_double_click_and_enter_activate_exactly_once(self):
        from fotosclaras.widgets import PhotoView
        view=PhotoView(self.w.thumbs);view.set_records(self.w.catalog.photos(self.library));view.show();QTest.qWait(80)
        hits=[];view.doubleClicked.connect(lambda index:hits.append(index.row()))
        rect=view.visualRect(view.model().index(0))
        QTest.mouseClick(view.viewport(),Qt.LeftButton,Qt.NoModifier,rect.center())
        QTest.mouseDClick(view.viewport(),Qt.LeftButton,Qt.NoModifier,rect.center())
        self.assertEqual(hits,[0]);QTest.keyClick(view,Qt.Key_Return);self.assertEqual(hits,[0,0]);view.close()

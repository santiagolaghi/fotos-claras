"""Scale/latency test with synthetic embeddings, not a face-accuracy benchmark."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ['OPENBLAS_NUM_THREADS']='1'
import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'FotosClaras'))
import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from fotosclaras.db import Catalog
from fotosclaras.identity import regroup
from fotosclaras.ui import MainWindow


def wait(predicate,timeout=120):
    end=time.monotonic()+timeout
    while not predicate() and time.monotonic()<end:QTest.qWait(10)
    assert predicate(),'El proceso no finalizó'


def run(n):
    rng=np.random.default_rng(73);identities=200;dimension=128
    centers=rng.standard_normal((identities,dimension)).astype(np.float32);centers/=np.linalg.norm(centers,axis=1,keepdims=True)
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);photos=root/'photos';photos.mkdir();path=root/'state/catalog.sqlite3'
        with Catalog(path) as c:
            library=c.library(photos)['id'];records=[];faces=[];expected={}
            for i in range(n):
                key=f'f{i:07}';confirmed=i<identities*3;known=confirmed or i%3!=0;person=i%identities
                v=centers[person]+rng.normal(0,.025,dimension) if known else rng.standard_normal(dimension)
                v=(v/np.linalg.norm(v)).astype(np.float32)
                if known and not confirmed:expected[key]=f'p{person:03}'
                records.append((key,library,str(photos/(key+'.jpg'))))
                faces.append((key,key,f'p{person:03}' if confirmed else None,v.tobytes(),int(confirmed)))
            with c.db:
                c.db.executemany('INSERT INTO people(id,name) VALUES (?,?)',[(f'p{i:03}',f'Persona {i}') for i in range(identities)])
                c.db.executemany("INSERT INTO photos(id,library_id,path,face_state) VALUES (?,?,?,'done')",records)
                c.db.executemany("INSERT INTO faces(id,photo_id,person_id,vector,locked,ordinal,box) VALUES (?,?,?,?,?,0,'[0,0,1,1]')",faces)
            started=time.perf_counter();assert regroup(c,library);elapsed=time.perf_counter()-started
            assignments={f['id']:f['person_id'] for f in c.rows('SELECT id,person_id FROM faces')}
            correct=sum(assignments[k]==p for k,p in expected.items());assert correct==len(expected),(correct,len(expected))
            started=time.perf_counter();page=c.photos(library,limit=240);page_seconds=time.perf_counter()-started;assert len(page)==240
        app=QApplication.instance() or QApplication([]);w=MainWindow(path);w.show();ticks=[]
        timer=QTimer();timer.timeout.connect(lambda:ticks.append(time.perf_counter()));timer.start(10)
        w.run_analysis('regroup');pid=w.task.process.pid;started=time.perf_counter()
        w.navigate(1);wait(lambda:w.current_grid is not None);gallery=time.perf_counter()-started
        w.navigate(4);wait(lambda:w.current_grid is not None and w.section==4)
        wait(lambda:not w.busy);timer.stop();wait(lambda:not w.findChildren(__import__('fotosclaras.jobs',fromlist=['ProcessTask']).ProcessTask))
        gaps=np.diff(ticks)*1000
        assert len(ticks)>10 and max(gaps)<1500,('Bloqueo de interfaz',max(gaps))
        w.close();wait(lambda:w._closed)
        report=dict(platform=sys.platform,faces=n,dimension=dimension,named_people=identities,
                    workload='Synthetic unit embeddings: noisy known identities plus independent unknowns; no measured family-photo recognition accuracy',
                    grouping_seconds=round(elapsed,3),known_assignments_correct=correct,known_assignments_total=len(expected),
                    page_size=240,page_query_seconds=round(page_seconds,4),
                    gallery_during_analysis_seconds=round(gallery,3),worker_separate_process=pid!=os.getpid(),
                    ui_timer_samples=len(ticks),ui_gap_max_ms=round(float(max(gaps)),2),ui_gap_p95_ms=round(float(np.percentile(gaps,95)),2))
        (ROOT/'validation/face-scale.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--faces',type=int,default=20000);run(p.parse_args().faces)

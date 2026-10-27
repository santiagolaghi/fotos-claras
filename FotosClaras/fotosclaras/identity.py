"""Local YuNet/SFace detection with durable face-level human corrections."""
from __future__ import annotations
import hashlib
import json
import threading
import urllib.request
from pathlib import Path
import numpy as np
from .db import Catalog,uid
from .imaging import open_rgb,sha256

MODEL_VERSION=3
MODELS={
 'face_detection_yunet_2023mar.onnx':('face_detection_yunet','8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4',232589),
 'face_recognition_sface_2021dec.onnx':('face_recognition_sface','0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79',38696353)}


def ensure_models(folder,cancel=None,report=lambda *a:None):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    cancel=cancel or threading.Event()
    for name,(directory,digest,size) in MODELS.items():
        target=folder/name
        if target.is_file() and sha256(target)==digest: continue
        tmp=target.with_suffix('.download')
        try:
            url=f'https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/{directory}/{name}'
            with urllib.request.urlopen(url,timeout=20) as stream,tmp.open('wb') as output:
                while block:=stream.read(256*1024):
                    if cancel.is_set(): raise InterruptedError('Preparación de modelos pausada')
                    output.write(block)
                    if output.tell()>size: raise ValueError('El modelo excede el tamaño esperado')
                    report('Descargando modelo facial',output.tell(),size)
            if tmp.stat().st_size!=size or sha256(tmp)!=digest: raise ValueError('El modelo no pasó la verificación SHA-256')
            tmp.replace(target)
        finally: tmp.unlink(missing_ok=True)
    return folder


class FaceEngine:
    def __init__(self,folder,cancel=None,report=lambda *a:None):
        import cv2
        cv2.setNumThreads(1)
        models=ensure_models(folder,cancel,report)
        self.detector=cv2.FaceDetectorYN.create(str(models/next(iter(MODELS))),'',(320,320),.7,.3,5000)
        self.recognizer=cv2.FaceRecognizerSF.create(str(models/'face_recognition_sface_2021dec.onnx'),'')
    def detect(self,path):
        rgb=np.asarray(open_rgb(path,1920));bgr=rgb[:,:,::-1].copy()
        self.detector.setInputSize((bgr.shape[1],bgr.shape[0]));_,boxes=self.detector.detect(bgr)
        found=[]
        for box in ([] if boxes is None else sorted(boxes,key=lambda b:(float(b[0]),float(b[1])))):
            vector=self.recognizer.feature(self.recognizer.alignCrop(bgr,box)).reshape(-1).astype(np.float32)
            norm=np.linalg.norm(vector)
            if not np.isfinite(norm) or norm<1e-8: raise ValueError('Representación facial inválida')
            x,y,w,h=map(float,box[:4]);ih,iw=rgb.shape[:2]
            crop=rgb[max(0,int(y)):min(ih,int(y+h)),max(0,int(x)):min(iw,int(x+w))]
            if not crop.size: raise ValueError('El detector devolvió un recorte vacío')
            found.append(dict(vector=vector/norm,box=[x/iw,y/ih,w/iw,h/ih],crop=crop))
        return found


def _vectors(c,library):
    return c.rows('''SELECT f.* FROM faces f JOIN photos p ON p.id=f.photo_id
      WHERE p.library_id=? AND p.state='active' AND p.error IS NULL AND p.face_state='done' ORDER BY f.locked DESC,f.id''',(library,))


def regroup(c,library,cancel=None,report=lambda *a:None):
    """Only unlocked faces can be reassigned; split vetoes and co-occurrence persist."""
    cancel=cancel or threading.Event();faces=_vectors(c,library)
    known={p['id']:p for p in c.rows('SELECT * FROM people')}
    blocked={}
    for b in c.rows('SELECT * FROM person_blocks'):
        blocked.setdefault(b['a'],set()).add(b['b']);blocked.setdefault(b['b'],set()).add(b['a'])
    veto={}
    for r in c.rows('SELECT * FROM face_rejections'): veto.setdefault(r['face_id'],set()).add(r['person_id'])
    refs={};occupied={};anchors={}
    for f in faces:
        if f['locked'] and f['person_id']:
            person=f['person_id'];v=np.frombuffer(f['vector'],dtype=np.float32)
            arr=refs.setdefault(person,[])
            if len(arr)<12 and (not arr or max(float(v@t) for t in arr)<.92): arr.append(v)
            occupied.setdefault(f['photo_id'],set()).add(person)
    # An unlocked group keeps a fixed anchor; expanding it cannot create a long similarity chain.
    for f in faces:
        if f['person_id'] and f['person_id'] not in refs:
            v=np.frombuffer(f['vector'],dtype=np.float32);refs[f['person_id']]=[v];anchors[f['person_id']]=v
    for i,f in enumerate(faces):
        if cancel.is_set(): return False
        if f['locked']: continue
        v=np.frombuffer(f['vector'],dtype=np.float32);old=f['person_id']
        rejected=veto.get(f['id'],set())|blocked.get(old,set())|occupied.get(f['photo_id'],set())
        scored=[]
        for person,templates in refs.items():
            if person in rejected: continue
            if person in anchors and float(v@anchors[person])<.55: continue
            score=max(float(v@t) for t in templates)
            if score>=.50: scored.append((score,person))
        scored.sort(reverse=True)
        confirmed=[s for s in scored if s[1] not in anchors]
        if confirmed: scored=confirmed
        person=None
        if scored and (len(scored)==1 or scored[0][0]-scored[1][0]>=.07): person=scored[0][1]
        if person is None:
            # Preserve the existing group unless it conflicts with another face in this photo.
            person=old if old and old not in rejected else uid()
            if person not in known:
                with c.db: c.db.execute('INSERT INTO people(id) VALUES (?)',(person,))
                known[person]={'id':person,'ignored':0,'name':''}
            if person not in refs: refs[person]=[v];anchors[person]=v
        with c.db: c.db.execute('UPDATE faces SET person_id=? WHERE id=?',(person,f['id']))
        occupied.setdefault(f['photo_id'],set()).add(person)
        report('Agrupando personas',i+1,len(faces))
    return True


def analyze(db_path,library,cancel=None,report=lambda *a:None,engine_factory=FaceEngine):
    cancel=cancel or threading.Event()
    with Catalog(db_path) as c:
        job=c.start_job(library,'faces');done=0;errors=0;total=0
        def progress(stage,n,t): c.progress(job,stage,n,t,errors);report(stage,n,t)
        try:
            pending=c.rows("SELECT * FROM photos WHERE library_id=? AND state='active' AND error IS NULL AND (face_state<>'done' OR face_version<>?)",(library,MODEL_VERSION))
            total=len(pending)
            if not pending:
                regroup(c,library,cancel,progress)
                c.progress(job,'Finalizado',0,0,0,'paused' if cancel.is_set() else 'done');return dict(done=0,errors=0)
            engine=engine_factory(c.path.parent/'models',cancel,progress)
            from PIL import Image
            folder=c.path.parent/'face-thumbnails';folder.mkdir(exist_ok=True)
            for p in pending:
                if cancel.is_set(): break
                try:
                    before=Path(p['path']).stat()
                    if (before.st_size,before.st_mtime_ns)!=(p['size'],p['mtime_ns']): raise ValueError('La foto cambió; actualizá la biblioteca antes de buscar rostros')
                    detections=engine.detect(p['path'])
                    after=Path(p['path']).stat()
                    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns): raise ValueError('La foto cambió durante el análisis')
                    with c.db:
                        # A changed model requires review; old data is backed up before upgrading.
                        c.db.execute('DELETE FROM faces WHERE photo_id=?',(p['id'],))
                        for ordinal,f in enumerate(detections):
                            key=uid();thumb=folder/(key+'.jpg')
                            image=Image.fromarray(f['crop']);image.thumbnail((180,180));image.save(thumb,quality=90)
                            from .legacy import restore_identity
                            person,locked=restore_identity(c,p,ordinal,f['vector'])
                            c.db.execute('INSERT INTO faces(id,photo_id,ordinal,vector,box,thumb,person_id,locked) VALUES (?,?,?,?,?,?,?,?)',
                              (key,p['id'],ordinal,f['vector'].astype(np.float32).tobytes(),json.dumps(f['box']),str(thumb),person,locked))
                        c.db.execute("UPDATE photos SET face_state='done',face_error=NULL,face_version=? WHERE id=?",(MODEL_VERSION,p['id']))
                except Exception as exc:
                    errors+=1
                    with c.db: c.db.execute("UPDATE photos SET face_state='error',face_error=? WHERE id=?",(str(exc),p['id']))
                    c.log('face_error',f"{p['path']}: {exc}")
                done+=1;progress('Buscando rostros',done,total)
            if not cancel.is_set(): regroup(c,library,cancel,progress)
            c.progress(job,'Pausado' if cancel.is_set() else 'Finalizado',done,total,errors,'paused' if cancel.is_set() else 'done')
            return dict(done=done,errors=errors)
        except InterruptedError:
            c.progress(job,'Pausado',done,total,errors,'paused');return dict(done=done,errors=errors)
        except Exception as exc:
            c.progress(job,'No se pudo analizar',done,total,errors+1,'error',str(exc));raise


def name_person(c,person,name):
    if not name.strip(): raise ValueError('Escribí un nombre')
    with c.db:
        c.db.execute('UPDATE people SET name=?,ignored=0 WHERE id=?',(name.strip(),person))
        c.db.execute('UPDATE faces SET locked=1 WHERE person_id=?',(person,))


def split(c,person,face_ids):
    if not face_ids: raise ValueError('Elegí los rostros que querés separar')
    all_faces={f['id'] for f in c.rows('SELECT id FROM faces WHERE person_id=?',(person,))}
    if not set(face_ids)<=all_faces: raise ValueError('Un rostro no pertenece a esta persona')
    target=uid()
    with c.db:
        c.db.execute('INSERT INTO people(id) VALUES (?)',(target,))
        c.db.execute('INSERT OR IGNORE INTO person_blocks VALUES (?,?)',tuple(sorted((person,target))))
        for f in face_ids:
            c.db.execute('INSERT OR IGNORE INTO face_rejections VALUES (?,?)',(f,person))
            c.db.execute('UPDATE faces SET person_id=?,locked=1 WHERE id=?',(target,f))
    return target


def merge(c,source,target):
    if source==target: raise ValueError('Elegí otra persona')
    if not c.one('SELECT id FROM people WHERE id=?',(target,)): raise ValueError('Persona de destino inexistente')
    # Co-occurrence is strong evidence that these are different people.
    overlap=c.one('SELECT 1 FROM faces a JOIN faces b ON a.photo_id=b.photo_id WHERE a.person_id=? AND b.person_id=? LIMIT 1',(source,target))
    if overlap: raise ValueError('Hay dos rostros diferentes en una misma foto. Corregí esos rostros antes de unir los grupos.')
    with c.db:
        c.db.execute('UPDATE faces SET person_id=?,locked=1 WHERE person_id=?',(target,source))
        # Explicit merge overrides only this pair of split vetoes; keep third-party constraints.
        for r in c.rows('SELECT * FROM face_rejections WHERE person_id=?',(source,)):
            c.db.execute('INSERT OR IGNORE INTO face_rejections VALUES (?,?)',(r['face_id'],target))
        c.db.execute('DELETE FROM face_rejections WHERE person_id=? AND face_id IN (SELECT id FROM faces WHERE person_id=?)',(target,target))
        for b in c.rows('SELECT * FROM person_blocks WHERE a=? OR b=?',(source,source)):
            other=b['b'] if b['a']==source else b['a']
            if other!=target: c.db.execute('INSERT OR IGNORE INTO person_blocks VALUES (?,?)',tuple(sorted((target,other))))
        c.db.execute('DELETE FROM people WHERE id=?',(source,))


def ignore(c,person,value=True):
    with c.db:
        c.db.execute('UPDATE people SET ignored=? WHERE id=?',(int(value),person))
        c.db.execute('UPDATE faces SET locked=1 WHERE person_id=?',(person,))

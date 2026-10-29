"""Local YuNet/SFace detection with durable face-level human corrections."""
from __future__ import annotations
import hashlib
import json
import threading
import urllib.request
from pathlib import Path
import numpy as np
from .db import Catalog,uid,PHOTO_FIELDS
from .imaging import open_rgb,sha256
from .face_matching import regroup,review_matches

MODEL_VERSION=4
MODELS={
 'face_detection_yunet_2023mar.onnx':('face_detection_yunet','8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4',232589),
 'face_recognition_sface_2021dec.onnx':('face_recognition_sface','0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79',38696353)}


def tile_positions(length,tile=1500):
    end=max(0,length-tile)
    return sorted(set(range(0,end+1,tile-300))|{end})


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
        self.cancel=cancel or threading.Event();self.report=report
        self.detector=cv2.FaceDetectorYN.create(str(models/next(iter(MODELS))),'',(320,320),.78,.3,5000)
        self.recognizer=cv2.FaceRecognizerSF.create(str(models/'face_recognition_sface_2021dec.onnx'),'')
    def detect(self,path):
        import cv2
        # Two global scales cover both large portraits and small group faces.
        # Overlapping tiles preserve detail instead of shrinking every face in
        # a large photograph into a few pixels. All work stays in the worker.
        rgb=np.asarray(open_rgb(path,3200));bgr=rgb[:,:,::-1].copy();ih,iw=rgb.shape[:2]
        candidates=[];passes=[]
        for side in (800,1600):
            scale=min(1.,side/max(iw,ih))
            if passes and scale==passes[-1][1]:continue
            image=cv2.resize(bgr,(max(32,round(iw*scale)),max(32,round(ih*scale))))
            passes.append((image,scale,0,0))
        if max(iw,ih)>1600:
            tile=1500
            xs=tile_positions(iw,tile);ys=tile_positions(ih,tile)
            passes.extend((bgr[y:y+tile,x:x+tile],1.,x,y) for y in ys for x in xs)
        for image,scale,dx,dy in passes:
            if self.cancel.is_set():raise InterruptedError('Búsqueda facial pausada')
            self.detector.setInputSize((image.shape[1],image.shape[0]));_,boxes=self.detector.detect(image)
            for box in ([] if boxes is None else boxes):
                mapped=box.copy();mapped[:14]/=scale
                mapped[[0,4,6,8,10,12]]+=dx;mapped[[1,5,7,9,11,13]]+=dy
                candidates.append(mapped)
        # Global NMS across scales/tiles; the same face counts exactly once.
        boxes=[]
        for box in sorted(candidates,key=lambda b:float(b[-1]),reverse=True):
            if not any(box_overlap(box[:4],other[:4])>.30 for other in boxes):boxes.append(box)
        found=[]
        for box in sorted(boxes,key=lambda b:(float(b[0]),float(b[1]))):
            if self.cancel.is_set():raise InterruptedError('Búsqueda facial pausada')
            vector=self.recognizer.feature(self.recognizer.alignCrop(bgr,box)).reshape(-1).astype(np.float32)
            norm=np.linalg.norm(vector)
            if not np.isfinite(norm) or norm<1e-8: raise ValueError('Representación facial inválida')
            x,y,w,h=map(float,box[:4]);ih,iw=rgb.shape[:2]
            crop=rgb[max(0,int(y)):min(ih,int(y+h)),max(0,int(x)):min(iw,int(x+w))]
            if not crop.size: raise ValueError('El detector devolvió un recorte vacío')
            # Size and local sharpness measure whether it is safe to identify
            # automatically. A poor-quality face is still counted as a third.
            gray=cv2.cvtColor(cv2.resize(crop,(112,112)),cv2.COLOR_RGB2GRAY)
            sharpness=float(cv2.Laplacian(gray,cv2.CV_32F).var())
            quality=min(1.,min(w,h)/80)*min(1.,max(.1,sharpness/80))
            found.append(dict(vector=vector/norm,box=[x/iw,y/ih,w/iw,h/ih],crop=crop,
                              quality=quality,detection_score=float(box[-1])))
        return found


def box_overlap(a,b):
    x=max(a[0],b[0]);y=max(a[1],b[1]);right=min(a[0]+a[2],b[0]+b[2]);bottom=min(a[1]+a[3],b[1]+b[3])
    intersection=max(0,right-x)*max(0,bottom-y)
    return intersection/max(1e-12,a[2]*a[3]+b[2]*b[3]-intersection)


def save_detections(c,photo,detections,folder):
    """Re-detection retains face IDs, rejections and confirmed names by geometry.

    A confirmed face unmatched by the new detector is retained. An upgrade must
    not silently erase the user's correction because one pass missed a face.
    """
    from PIL import Image
    old=c.rows('SELECT * FROM faces WHERE photo_id=? ORDER BY locked DESC',(photo['id'],))
    available={f['id']:f for f in old};matched=[]
    for f in detections:
        ranked=sorted(((box_overlap(f['box'],json.loads(o['box'])),o['id']) for o in available.values()),reverse=True)
        previous=available.pop(ranked[0][1]) if ranked and ranked[0][0]>=.35 else None
        matched.append((f,previous))
    leftovers=[o for o in available.values() if o['locked']]
    with c.db:
        # Temporarily move ordinals away from their unique values before reorder.
        c.db.execute('UPDATE faces SET ordinal=-ordinal-1000 WHERE photo_id=?',(photo['id'],))
        for key,o in available.items():
            if not o['locked']:c.db.execute('DELETE FROM faces WHERE id=?',(key,))
        for ordinal,(f,previous) in enumerate(matched):
            key=previous['id'] if previous else uid();thumb=folder/(key+'.jpg')
            image=Image.fromarray(f['crop']);image.thumbnail((180,180))
            temp=thumb.with_suffix('.tmp');image.save(temp,format='JPEG',quality=90);temp.replace(thumb)
            if previous:
                c.db.execute('UPDATE faces SET ordinal=?,vector=?,box=?,thumb=?,quality=?,detection_score=? WHERE id=?',
                  (ordinal,f['vector'].astype(np.float32).tobytes(),json.dumps(f['box']),str(thumb),f.get('quality',1),f.get('detection_score',1),key))
            else:
                from .legacy import restore_identity
                person,locked=restore_identity(c,photo,ordinal,f['vector'])
                c.db.execute('INSERT INTO faces(id,photo_id,ordinal,vector,box,thumb,person_id,locked,quality,detection_score,match_state) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                  (key,photo['id'],ordinal,f['vector'].astype(np.float32).tobytes(),json.dumps(f['box']),str(thumb),person,locked,f.get('quality',1),f.get('detection_score',1),'confirmed' if locked else 'unknown'))
        for ordinal,o in enumerate(leftovers,len(matched)):
            c.db.execute('UPDATE faces SET ordinal=? WHERE id=?',(ordinal,o['id']))
        c.db.execute("UPDATE photos SET face_state='done',face_error=NULL,face_version=? WHERE id=?",(MODEL_VERSION,photo['id']))


def analyze(db_path,library,cancel=None,report=lambda *a:None,engine_factory=FaceEngine):
    cancel=cancel or threading.Event()
    with Catalog(db_path) as c:
        job=c.start_job(library,'faces');done=0;errors=0;total=0
        import time
        last=0
        def progress(stage,n,t):
            nonlocal last
            now=time.monotonic()
            if now-last>=.5 or n==t:c.progress(job,stage,n,t,errors);last=now
            report(stage,n,t)
        try:
            pending=c.rows('SELECT '+','.join(PHOTO_FIELDS)+" FROM photos WHERE library_id=? AND state='active' AND error IS NULL AND (face_state<>'done' OR face_version<>?)",(library,MODEL_VERSION))
            total=len(pending)
            if not pending:
                regroup(c,library,cancel,progress)
                c.progress(job,'Finalizado',0,0,0,'paused' if cancel.is_set() else 'done');return dict(done=0,errors=0)
            engine=engine_factory(c.path.parent/'models',cancel,progress)
            folder=c.path.parent/'face-thumbnails';folder.mkdir(exist_ok=True)
            for p in pending:
                if cancel.is_set(): break
                try:
                    before=Path(p['path']).stat()
                    if (before.st_size,before.st_mtime_ns)!=(p['size'],p['mtime_ns']): raise ValueError('La foto cambió; actualizá la biblioteca antes de buscar rostros')
                    detections=engine.detect(p['path'])
                    after=Path(p['path']).stat()
                    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns): raise ValueError('La foto cambió durante el análisis')
                    save_detections(c,p,detections,folder)
                except InterruptedError:
                    break
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
    previous=c.one('SELECT name FROM people WHERE id=?',(person,))
    if not previous:raise ValueError('La persona ya no está disponible')
    with c.db:
        c.db.execute('UPDATE people SET name=?,ignored=0 WHERE id=?',(name.strip(),person))
        # Initial naming confirms the reviewed group. Renaming an established
        # person must not turn all subsequent automatic matches into training.
        if not previous['name']:
            c.db.execute("UPDATE faces SET locked=1,match_state='confirmed',match_score=1 WHERE person_id=?",(person,))
            c.db.execute('DELETE FROM face_candidates WHERE face_id IN (SELECT id FROM faces WHERE person_id=?)',(person,))


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
            c.db.execute("UPDATE faces SET person_id=?,locked=1,match_state='confirmed',match_score=1 WHERE id=?",(target,f))
            c.db.execute('DELETE FROM face_candidates WHERE face_id=?',(f,))
    return target


def merge(c,source,target):
    if source==target: raise ValueError('Elegí otra persona')
    if not c.one('SELECT id FROM people WHERE id=?',(target,)): raise ValueError('Persona de destino inexistente')
    # Co-occurrence is strong evidence that these are different people.
    overlap=c.one('SELECT 1 FROM faces a JOIN faces b ON a.photo_id=b.photo_id WHERE a.person_id=? AND b.person_id=? LIMIT 1',(source,target))
    if overlap: raise ValueError('Hay dos rostros diferentes en una misma foto. Corregí esos rostros antes de unir los grupos.')
    with c.db:
        c.db.execute('DELETE FROM face_candidates WHERE face_id IN (SELECT id FROM faces WHERE person_id=?)',(source,))
        c.db.execute("UPDATE faces SET person_id=?,locked=1,match_state='confirmed',match_score=1 WHERE person_id=?",(target,source))
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
        c.db.execute('DELETE FROM face_candidates WHERE face_id IN (SELECT id FROM faces WHERE person_id=?)',(person,))

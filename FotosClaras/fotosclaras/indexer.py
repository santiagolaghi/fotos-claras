"""Incremental, cancellable indexing. No heavy work is triggered on startup."""
import os
import threading
from pathlib import Path
from .db import Catalog,uid
from .imaging import EXTENSIONS,VERSION,fingerprint
from .matching import find_versions


def scan(db_path,library_id,cancel=None,report=lambda *a:None,compare=True):
    cancel=cancel or threading.Event()
    with Catalog(db_path) as c:
        library=c.one('SELECT * FROM libraries WHERE id=?',(library_id,))
        root=Path(library['path'])
        if not root.is_dir(): raise ValueError('La carpeta de esta biblioteca no está disponible')
        job=c.start_job(library_id,'index');paths=[];walk_errors=[]
        def progress(stage,done,total,errors=0):
            c.progress(job,stage,done,total,errors);report(stage,done,total)
        try:
            progress('Buscando fotografías',0,0)
            for base,dirs,files in os.walk(root,followlinks=False,onerror=walk_errors.append):
                dirs[:]=[d for d in dirs if not d.startswith('.') and d!='FotosClaras_ParaRevisar' and not (Path(base)/d).is_symlink() and (Path(base)/d).resolve()!=c.path.parent.resolve()]
                if cancel.is_set(): break
                paths.extend(Path(base)/n for n in files if Path(n).suffix.lower() in EXTENSIONS and not (Path(base)/n).is_symlink())
                report('Buscando fotografías',len(paths),0)
            errors=len(walk_errors);done=0
            for path in paths:
                if cancel.is_set(): break
                done+=1;path=path.resolve();old=c.one('SELECT * FROM photos WHERE path=? AND library_id=?',(str(path),library_id))
                try:
                    stat=path.stat()
                    if old and not old['error'] and old['fingerprint_version']==VERSION and (old['size'],old['mtime_ns'])==(stat.st_size,stat.st_mtime_ns):
                        with c.db: c.db.execute("UPDATE photos SET seen=?,state='active' WHERE id=?",(job,old['id']))
                    else:
                        item=fingerprint(path,c.path.parent/'thumbnails')
                        with c.db:
                            key=old['id'] if old else uid()
                            if not old: c.db.execute('INSERT INTO photos(id,library_id,path) VALUES (?,?,?)',(key,library_id,str(path)))
                            if old and old['raster']!=item['raster']:
                                c.db.execute('DELETE FROM faces WHERE photo_id=?',(key,))
                                c.db.execute("UPDATE photos SET face_state='pending',face_error=NULL,face_version=0 WHERE id=?",(key,))
                                c.db.execute('DELETE FROM pairs WHERE a=? OR b=?',(key,key))
                            c.db.execute('UPDATE photos SET '+','.join(k+'=?' for k in item)+",error=NULL,state='active',seen=? WHERE id=?",(*item.values(),job,key))
                except Exception as exc:
                    errors+=1
                    with c.db:
                        if not old: c.db.execute('INSERT INTO photos(id,library_id,path,error,seen) VALUES (?,?,?,?,?)',(uid(),library_id,str(path),str(exc),job))
                        else: c.db.execute("UPDATE photos SET error=?,seen=?,face_state='pending' WHERE id=?",(str(exc),job,old['id']))
                    c.log('index_error',f'{path}: {exc}')
                progress('Leyendo fotografías',done,len(paths),errors)
            if cancel.is_set():
                c.progress(job,'Pausado',done,len(paths),errors,'paused');return dict(state='paused',done=done,total=len(paths),errors=errors)
            # Never mark absent after a partial/unreadable directory traversal.
            if not walk_errors:
                with c.db: c.db.execute("UPDATE photos SET state='missing' WHERE library_id=? AND state='active' AND (seen IS NULL OR seen<>?)",(library_id,job))
            for exc in walk_errors: c.log('directory_error',str(exc))
            complete=not compare or find_versions(c,library_id,cancel,progress)
            state='done' if complete else 'paused'
            c.progress(job,'Finalizado' if complete else 'Pausado',done,len(paths),errors,state)
            return dict(state=state,done=done,total=len(paths),errors=errors)
        except Exception as exc:
            c.progress(job,'Interrumpido',0,len(paths),1,'error',str(exc));raise

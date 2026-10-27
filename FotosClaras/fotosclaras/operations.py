"""Durable file operations, exclusive writes, verified undo and crash recovery."""
from __future__ import annotations
import os
import shutil
import threading
import time
from pathlib import Path
from .db import uid
from .imaging import sha256


class OperationConflict(RuntimeError): pass


def plan(c,library,ids,destination,kind='move',preserve_tree=False,cancel=None,report=lambda *a:None):
    if kind not in ('move','copy','quarantine'): raise ValueError('Acción inválida')
    root=Path(c.one('SELECT path FROM libraries WHERE id=?',(library,))['path']).resolve()
    dest=Path(destination).resolve()
    # Keep application state and binaries outside photo operations.
    if dest==c.path.parent or c.path.parent in dest.parents: raise ValueError('Elegí una carpeta fuera de los datos de Fotos Claras')
    taken=set();items=[]
    for number,key in enumerate(dict.fromkeys(ids)):
        if cancel is not None and cancel.is_set(): raise InterruptedError('Preparación pausada')
        report('Preparando vista previa',number,len(ids))
        p=c.one('SELECT * FROM photos WHERE id=? AND library_id=?',(key,library))
        if not p: raise ValueError('La fotografía no pertenece a esta biblioteca')
        source=Path(p['path'])
        if source.is_symlink() or not source.is_file(): raise OperationConflict(f'No está disponible: {source}')
        if source.parent.resolve()==dest and not preserve_tree: raise OperationConflict('La foto ya está en la carpeta elegida')
        if not p['sha'] or sha256(source)!=p['sha']: raise OperationConflict(f'La foto cambió. Volvé a analizar: {source}')
        relative=source.relative_to(root) if preserve_tree and source.is_relative_to(root) else Path(source.name)
        target=dest/relative;original=target;n=2
        while target.exists() or str(target).casefold() in taken or c.one('SELECT id FROM photos WHERE library_id=? AND path=? AND id<>?',(library,str(target),key)):
            target=original.with_name(f'{original.stem} ({n}){original.suffix}');n+=1
        if target==source: raise OperationConflict('El origen y el destino coinciden')
        taken.add(str(target).casefold())
        items.append(dict(photo_id=key,source=str(source),target=str(target),digest=p['sha'],state='planned',
                          prior_state=p['state'],size=source.stat().st_size,mtime_ns=source.stat().st_mtime_ns))
    if not items: raise ValueError('Seleccioná fotografías primero')
    # No side effects during preview. Persist only when the user confirms it.
    return dict(id=uid(),library_id=library,kind=kind,items=items)


def save_plan(c,p):
    with c.db:
        c.db.execute('INSERT INTO operations VALUES (?,?,?,?,?,NULL)',(p['id'],p['library_id'],p['kind'],'planned',time.time()))
        for item in p['items']:
            fields=','.join(item)
            c.db.execute('INSERT INTO operation_items(operation_id,'+fields+') VALUES ('+','.join('?' for _ in range(len(item)+1))+')',(p['id'],*item.values()))
    return p['id']


def exclusive_copy(source,target,digest):
    """Never replace an existing pathname, including one created after preview."""
    source,target=Path(source),Path(target)
    target.parent.mkdir(parents=True,exist_ok=True)
    with source.open('rb') as src,target.open('xb') as dst:
        shutil.copyfileobj(src,dst,1024*1024);dst.flush();os.fsync(dst.fileno())
    if sha256(target)!=digest or sha256(source)!=digest:
        raise OperationConflict('El archivo cambió o la copia no pasó la comprobación; se conservó el origen')
    shutil.copystat(source,target)


def execute(c,key,cancel=None,report=lambda *a:None):
    cancel=cancel or threading.Event()
    op=c.one('SELECT * FROM operations WHERE id=?',(key,))
    if not op or op['state'] in ('undone','done'): return
    items=c.rows('SELECT * FROM operation_items WHERE operation_id=? ORDER BY id',(key,))
    with c.db: c.db.execute("UPDATE operations SET state='running',error=NULL WHERE id=?",(key,))
    try:
        for i,item in enumerate(items):
            if item['state']=='done': continue
            if cancel.is_set():
                with c.db: c.db.execute("UPDATE operations SET state='paused' WHERE id=?",(key,))
                return
            src,dst=Path(item['source']),Path(item['target'])
            if src.is_symlink() or dst.is_symlink(): raise OperationConflict('Una ruta fue reemplazada por un enlace')
            # Revalidate all meaningful state on resume. Never silently clobber a conflict.
            if src.exists() and sha256(src)!=item['digest']: raise OperationConflict(f'El origen cambió: {src}')
            if item['state']=='planned':
                if dst.exists(): raise OperationConflict(f'El destino apareció después de la vista previa: {dst}')
                with c.db: c.db.execute("UPDATE operation_items SET state='copying' WHERE id=?",(item['id'],))
                exclusive_copy(src,dst,item['digest'])
            elif not dst.exists() and src.is_file():
                exclusive_copy(src,dst,item['digest'])
            elif not dst.is_file() or sha256(dst)!=item['digest']:
                # A partial copy is retained for inspection; source stays safe.
                raise OperationConflict(f'Copia incompleta o destino modificado: {dst}. Conservamos el origen.')
            with c.db: c.db.execute("UPDATE operation_items SET state='copied' WHERE id=?",(item['id'],))
            if op['kind']!='copy' and src.exists():
                if sha256(src)!=item['digest']: raise OperationConflict(f'El origen cambió: {src}')
                src.unlink()  # Only after an exclusive, durable and verified copy.
            with c.db:
                if op['kind']!='copy':
                    state='quarantined' if op['kind']=='quarantine' else 'active'
                    c.db.execute('UPDATE photos SET path=?,state=?,mtime_ns=? WHERE id=?',
                                 (str(dst),state,dst.stat().st_mtime_ns,item['photo_id']))
                c.db.execute("UPDATE operation_items SET state='done' WHERE id=?",(item['id'],))
            report('Organizando fotografías',i+1,len(items))
        with c.db: c.db.execute("UPDATE operations SET state='done' WHERE id=?",(key,))
    except Exception as exc:
        with c.db: c.db.execute("UPDATE operations SET state='interrupted',error=? WHERE id=?",(str(exc),key))
        raise


def undo(c,key,report=lambda *a:None):
    op=c.one('SELECT * FROM operations WHERE id=?',(key,))
    if not op or op['state']=='undone': return 0
    items=c.rows("SELECT * FROM operation_items WHERE operation_id=? AND state IN ('done','undoing') ORDER BY id DESC",(key,))
    # Full preflight before starting a batch. Already restored items are recognized after a crash.
    for item in items:
        src,dst=Path(item['source']),Path(item['target'])
        if op['kind']=='copy':
            restore=c.path.parent/'recovered-copies'/key/dst.name
        else: restore=src
        if restore.exists() and item['state']!='undoing': raise OperationConflict(f'No se puede restaurar sin sobrescribir: {restore}')
        if restore.exists() and sha256(restore)!=item['digest']: raise OperationConflict(f'El origen fue modificado: {restore}')
        if dst.exists() and sha256(dst)!=item['digest']: raise OperationConflict(f'La foto movida fue modificada: {dst}')
        if not dst.exists() and not (item['state']=='undoing' and restore.exists()): raise OperationConflict(f'No se encontró: {dst}')
    with c.db: c.db.execute("UPDATE operations SET state='undoing' WHERE id=?",(key,))
    for i,item in enumerate(items):
        src,dst=Path(item['source']),Path(item['target'])
        restore=(c.path.parent/'recovered-copies'/key/dst.name) if op['kind']=='copy' else src
        with c.db: c.db.execute("UPDATE operation_items SET state='undoing' WHERE id=?",(item['id'],))
        if not restore.exists(): exclusive_copy(dst,restore,item['digest'])
        if dst.exists():
            if sha256(dst)!=item['digest']: raise OperationConflict(f'La foto cambió: {dst}')
            dst.unlink()
        with c.db:
            if op['kind']!='copy':
                if item['photo_id']:
                    c.db.execute('UPDATE photos SET path=?,state=?,mtime_ns=? WHERE id=?',(str(src),item['prior_state'],src.stat().st_mtime_ns,item['photo_id']))
                else:
                    c.db.execute('UPDATE photos SET path=?,state=?,mtime_ns=? WHERE library_id=? AND path=?',(str(src),item['prior_state'],src.stat().st_mtime_ns,op['library_id'],str(dst)))
            else:
                # If a later scan indexed the physical copy, keep its identity at its recovery path.
                c.db.execute("UPDATE photos SET path=?,state='quarantined' WHERE path=?",(str(restore),str(dst)))
            c.db.execute("UPDATE operation_items SET state='undone' WHERE id=?",(item['id'],))
        report('Deshaciendo movimiento',i+1,len(items))
    with c.db: c.db.execute("UPDATE operations SET state='undone' WHERE id=?",(key,))
    return len(items)

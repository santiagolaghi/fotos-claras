"""Read old identity/config state without modifying any legacy file."""
import json
from pathlib import Path
import numpy as np
from .db import uid


def import_state(c,folder=None):
    if c.pref('legacy_imported',False): return
    folder=Path(folder or c.path.parent)
    imported={'people':[],'overrides':{}}
    source=folder/'personas_v2.json'
    try:
        if source.exists(): imported=json.loads(source.read_text(encoding='utf-8'))
        elif (folder/'personas.json').exists():
            old=json.loads((folder/'personas.json').read_text(encoding='utf-8'))
            imported['people']=[dict(id=uid(),name=p['name'],templates=[p['vector']]) for p in old]
        with c.db:
            for person in imported.get('people',[]):
                c.db.execute('INSERT OR IGNORE INTO people(id,name) VALUES (?,?)',(person['id'],person.get('name','')))
        c.set_pref('legacy_people',imported)
        pref=folder/'preferencias.json'
        if pref.exists():
            prefs=json.loads(pref.read_text(encoding='utf-8'))
            if prefs.get('last_folder'): c.library(prefs['last_folder'])
        c.set_pref('legacy_imported',True)
    except (OSError,ValueError,TypeError,KeyError) as exc:
        c.log('legacy_import_error',str(exc))
        # Retry is possible; do not erase damaged legacy state.
        raise RuntimeError('No pudimos importar las identificaciones anteriores. Conservamos los archivos. '+str(exc)) from exc


def restore_identity(c,photo,ordinal,vector):
    old=c.pref('legacy_people',{})
    override=old.get('overrides',{}).get(f"{photo['sha']}:{ordinal}")
    if override and c.one('SELECT id FROM people WHERE id=?',(override,)):
        return override,1
    scores=[]
    for p in old.get('people',[]):
        if not p.get('name'): continue
        refs=[np.asarray(v,dtype=np.float32) for v in p.get('templates',[])]
        refs=[v/np.linalg.norm(v) for v in refs if v.shape==vector.shape and np.linalg.norm(v)>0]
        if refs: scores.append((max(float(v@vector) for v in refs),p['id']))
    scores.sort(reverse=True)
    if scores and scores[0][0]>=.60 and (len(scores)==1 or scores[0][0]-scores[1][0]>=.1): return scores[0][1],0
    return None,0


def import_history(c,library_id):
    """Import currently verifiable legacy batches; retain other JSON entries intact."""
    import hashlib
    import time
    from .imaging import sha256,EXTENSIONS
    from . import operations
    library=c.one('SELECT * FROM libraries WHERE id=?',(library_id,));root=Path(library['path']).resolve()
    key=hashlib.sha256(str(root).encode()).hexdigest()[:20]
    journal=c.path.parent/f'movimientos_{key}.jsonl'
    if not journal.exists():journal=root/'FotosClaras_ParaRevisar'/'movimientos.jsonl'
    if not journal.exists():return 0
    imported=0
    for line in reversed(journal.read_text(encoding='utf-8').splitlines()):
        token=hashlib.sha256((str(journal)+line).encode()).hexdigest()
        if c.pref('legacy_journal:'+token,False):continue
        try:
            entry=json.loads(line);items=[]
            for move in entry['moves']:
                source,target=Path(move['from']).resolve(),Path(move['to']).resolve()
                if not source.is_relative_to(root) or source.suffix.lower() not in EXTENSIONS:raise ValueError('Ruta antigua fuera de biblioteca')
                if source.exists() or not target.is_file():raise ValueError('Lote anterior aún no verificable')
                photo=c.one('SELECT id FROM photos WHERE library_id=? AND path=?',(library_id,str(target)))
                items.append(dict(photo_id=photo['id'] if photo else None,source=str(source),target=str(target),digest=sha256(target),state='done',prior_state='active',size=target.stat().st_size,mtime_ns=target.stat().st_mtime_ns))
            if not items:continue
            plan=dict(id='legacy-'+token[:32],library_id=library_id,kind='move',items=items)
            operations.save_plan(c,plan)
            with c.db:
                c.db.execute("UPDATE operations SET state='done',created=? WHERE id=?",(float(entry.get('time',time.time())),plan['id']))
            c.set_pref('legacy_journal:'+token,True);imported+=1
        except (OSError,ValueError,KeyError,TypeError):
            # Keep the original record and revisit after a later batch is undone.
            continue
    return imported

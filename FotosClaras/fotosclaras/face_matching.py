"""Bounded candidate search. Only human-confirmed faces train named identities."""
from __future__ import annotations
from collections import Counter
import threading
import numpy as np
from .db import uid

AUTO_THRESHOLD=.50
REVIEW_THRESHOLD=.30
AUTO_MARGIN=.07


def diverse_templates(vectors,quality,limit=48):
    """Cover confirmed ages/angles instead of taking the first random UUIDs."""
    if len(vectors)<=limit:return vectors
    chosen=[int(np.argmax(quality))]
    similarity=vectors@vectors[chosen[0]]
    for _ in range(limit-1):
        priority=(1-similarity)*(.35+.65*quality)
        priority[chosen]=-1
        index=int(np.argmax(priority))
        if similarity[index]>.97:break
        chosen.append(index);similarity=np.maximum(similarity,vectors@vectors[index])
    return vectors[chosen]


class AnchorIndex:
    """Deterministic multi-probe LSH for unnamed groups, never an identity proof.

    Named people are scored exhaustively in batches. Approximation is restricted
    to unknown groups, where a missed neighbour creates review work, not a false
    confirmed identity. Memory is linear; candidate comparisons are bounded.
    """
    def __init__(self,dimension):
        rng=np.random.default_rng(8427)
        self.planes=rng.standard_normal((80,dimension)).astype(np.float32)
        self.tables=[{} for _ in range(8)];self.vectors=[];self.people=[]
    def keys(self,vector):
        bits=(self.planes@vector>=0).reshape(8,10)
        return (bits*(1<<np.arange(10))).sum(axis=1)
    def add(self,person,vector):
        index=len(self.people);self.people.append(person);self.vectors.append(vector)
        for table,key in zip(self.tables,self.keys(vector)):
            table.setdefault(int(key),[]).append(index)
    def near(self,vector,exclude):
        if not self.people:return []
        if len(self.people)<=256:indices=range(len(self.people))
        else:
            votes=Counter()
            for table,key in zip(self.tables,self.keys(vector)):
                for code in [int(key)]+[int(key)^(1<<i) for i in range(10)]:
                    votes.update(table.get(code,())[:256])
            indices=[i for i,_ in votes.most_common(512)]
        eligible=[i for i in indices if self.people[i] not in exclude]
        if not eligible:return []
        scores=np.asarray([self.vectors[i] for i in eligible])@vector
        return sorted([(float(s),self.people[i]) for i,s in zip(eligible,scores) if s>=.55],reverse=True)


def regroup(c,library,cancel=None,report=lambda *a:None):
    cancel=cancel or threading.Event()
    faces=c.rows('''SELECT f.* FROM faces f JOIN photos p ON p.id=f.photo_id
      WHERE p.library_id=? AND p.state='active' AND p.error IS NULL AND p.face_state='done'
      ORDER BY f.locked DESC,f.quality DESC,f.id''',(library,))
    if not faces:return True
    # Embeddings are loaded once (128 floats each), not fetched during comparison.
    vectors=np.stack([np.frombuffer(f['vector'],dtype=np.float32) for f in faces])
    people={p['id']:p for p in c.rows('SELECT * FROM people')}
    veto={};blocked={};occupied={};references={};unknown=AnchorIndex(vectors.shape[1])
    for b in c.rows('SELECT * FROM person_blocks'):
        blocked.setdefault(b['a'],set()).add(b['b']);blocked.setdefault(b['b'],set()).add(b['a'])
    for r in c.rows('SELECT * FROM face_rejections'):
        veto.setdefault(r['face_id'],set()).add(r['person_id'])
    # Locked faces are the only references for an identified person. Automatic
    # assignments cannot progressively teach the engine its own mistakes.
    for i,f in enumerate(faces):
        person=f['person_id']
        if f['locked'] and person:
            occupied.setdefault(f['photo_id'],set()).add(person)
            if people[person]['name'] and not people[person]['ignored']:
                references.setdefault(person,[]).append((vectors[i],f['quality']))
    # Identities belong to the local catalog, not to one folder. A confirmed
    # person remains useful when the user opens another family library.
    for f in c.rows('''SELECT f.person_id,f.vector,f.quality FROM faces f JOIN people pe ON pe.id=f.person_id
        JOIN photos p ON p.id=f.photo_id WHERE p.library_id<>? AND p.state='active' AND p.error IS NULL
        AND p.face_state='done' AND f.locked=1 AND pe.name<>'' AND pe.ignored=0''',(library,)):
        v=np.frombuffer(f['vector'],dtype=np.float32)
        if v.shape==(vectors.shape[1],):references.setdefault(f['person_id'],[]).append((v,f['quality']))
    template_people=[];templates=[];starts=[]
    for person,samples in references.items():
        starts.append(len(templates));template_people.append(person)
        templates.extend(diverse_templates(np.stack([v for v,_ in samples]),np.array([q for _,q in samples])))
    matrix=np.stack(templates) if templates else np.empty((0,vectors.shape[1]),dtype=np.float32)
    anchored=set()
    for i,f in enumerate(faces):
        person=f['person_id']
        if person and not people[person]['name'] and person not in anchored:
            unknown.add(person,vectors[i]);anchored.add(person)
    pending=[i for i,f in enumerate(faces) if not f['locked']]
    total=len(pending);processed=0
    for base in range(0,total,128):
        if cancel.is_set():return False
        batch=pending[base:base+128]
        scores=np.maximum.reduceat(vectors[batch]@matrix.T,starts,axis=1) if len(matrix) else np.empty((len(batch),0))
        assignments=[];suggestions=[];created=[];cleared=[]
        for row,i in enumerate(batch):
            if cancel.is_set():break
            f=faces[i];v=vectors[i];old=f['person_id']
            rejected=veto.get(f['id'],set())|blocked.get(old,set())|occupied.get(f['photo_id'],set())
            ranked=sorted([(float(s),p) for p,s in zip(template_people,scores[row])
                           if p not in rejected and s>=REVIEW_THRESHOLD],reverse=True)
            person=None;score=None;state='unknown'
            if ranked:
                best,choice=ranked[0];gap=best-(ranked[1][0] if len(ranked)>1 else -1)
                if best>=AUTO_THRESHOLD and gap>=AUTO_MARGIN and f['quality']>=.35:
                    person=choice;score=best;state='automatic'
                else:
                    suggestions.extend((f['id'],p,s) for s,p in ranked[:3])
            if person is None:
                neighbours=unknown.near(v,rejected)
                if neighbours and (len(neighbours)==1 or neighbours[0][0]-neighbours[1][0]>=.04):
                    score,person=neighbours[0]
                if person is None:
                    person=old if old and not people[old]['name'] and old not in rejected else uid()
                    if person not in people:
                        people[person]=dict(id=person,name='',ignored=0);created.append((person,))
                    if person not in anchored:
                        unknown.add(person,v);anchored.add(person)
            occupied.setdefault(f['photo_id'],set()).add(person)
            assignments.append((person,state,score,f['id']));cleared.append((f['id'],));processed+=1
        # One durable transaction per batch, not two disk synchronizations/face.
        with c.db:
            c.db.executemany('INSERT INTO people(id) VALUES (?)',created)
            c.db.executemany('UPDATE faces SET person_id=?,match_state=?,match_score=? WHERE id=?',assignments)
            c.db.executemany('DELETE FROM face_candidates WHERE face_id=?',cleared)
            c.db.executemany('INSERT INTO face_candidates VALUES (?,?,?)',suggestions)
        report('Asociando personas y preparando coincidencias para revisar',processed,total)
    return not cancel.is_set()


def review_matches(c,person,face_ids,confirm=True):
    ids=list(dict.fromkeys(face_ids))
    if not ids:raise ValueError('Seleccioná rostros para revisar')
    if not c.one('SELECT id FROM people WHERE id=?',(person,)):raise ValueError('Persona inexistente')
    records=[];photos=set()
    for key in ids:
        f=c.one('SELECT * FROM faces WHERE id=?',(key,))
        if not f:raise ValueError('El rostro ya no está disponible')
        if confirm:
            if f['photo_id'] in photos:raise ValueError('Hay dos rostros seleccionados en una misma foto')
            if c.one('SELECT 1 FROM faces WHERE photo_id=? AND person_id=? AND id<>?',(f['photo_id'],person,key)):
                raise ValueError('Esta persona ya aparece en otro rostro de la fotografía')
            photos.add(f['photo_id'])
        records.append(f)
    with c.db:
        for f in records:
            if confirm:
                c.db.execute("UPDATE faces SET person_id=?,locked=1,match_state='confirmed',match_score=1 WHERE id=?",(person,f['id']))
                c.db.execute('DELETE FROM face_rejections WHERE face_id=? AND person_id=?',(f['id'],person))
                c.db.execute('DELETE FROM face_candidates WHERE face_id=?',(f['id'],))
            else:
                c.db.execute('INSERT OR IGNORE INTO face_rejections VALUES (?,?)',(f['id'],person))
                c.db.execute('DELETE FROM face_candidates WHERE face_id=? AND person_id=?',(f['id'],person))
    return len(records)

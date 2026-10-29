"""Hashes select candidates; detail comparisons only suggest manual review."""
import numpy as np
from .imaging import open_rgb,RESAMPLE
from .db import PHOTO_FIELDS

class BKTree:
    def __init__(self): self.root=None
    def add(self,key,value):
        if self.root is None: self.root=(key,[value],{});return
        node=self.root
        while True:
            d=(key^node[0]).bit_count()
            if not d: node[1].append(value);return
            if d not in node[2]: node[2][d]=(key,[value],{});return
            node=node[2][d]
    def near(self,key,radius):
        stack=[self.root] if self.root else [];result=[]
        while stack:
            node=stack.pop();d=(key^node[0]).bit_count()
            if d<=radius: result.extend(node[1])
            stack.extend(n for edge,n in node[2].items() if d-radius<=edge<=d+radius)
        return result


def version_score(a,b):
    if a['raster']==b['raster'] or a['frames']!=1 or b['frames']!=1: return None
    ra,rb=a['width']/a['height'],b['width']/b['height']
    if abs(ra-rb)/max(ra,rb)>.025: return None
    left=np.frombuffer(a['small'],dtype=np.uint8).astype(float)
    right=np.frombuffer(b['small'],dtype=np.uint8).astype(float)
    if np.abs(left-right).mean()>16 or min(left.std(),right.std())<8: return None
    # Larger spatial tiles retain local changes hidden by a tiny average hash.
    x=np.asarray(open_rgb(a['path'],800).resize((384,384),RESAMPLE),dtype=float)
    y=np.asarray(open_rgb(b['path'],800).resize((384,384),RESAMPLE),dtype=float)
    delta=np.abs(x-y).mean(axis=2)
    tile=delta.reshape(16,24,16,24).mean(axis=(1,3))
    # Even these thresholds do not prove that a burst is the same exposure.
    if delta.mean()>10 or np.percentile(delta,95)>35 or tile.max()>25: return None
    return round(1-float(delta.mean())/255,4)


def exact_groups(catalog,library):
    groups=catalog.rows('''SELECT raster,COUNT(*) n FROM photos WHERE library_id=?
        AND state='active' AND error IS NULL GROUP BY raster HAVING COUNT(*)>1 ORDER BY n DESC''',(library,))
    return [catalog.rows('SELECT '+','.join(PHOTO_FIELDS)+''' FROM photos WHERE library_id=? AND raster=?
        AND state='active' AND error IS NULL ORDER BY width*height DESC,size DESC,path''',(library,g['raster'])) for g in groups]


def find_versions(catalog,library,cancel,report):
    photos=catalog.photos(library,sort='name',features=True)
    # Keep one fixed representative per proven raster. No transitive union.
    unique={}
    for p in photos: unique.setdefault(p['raster'],p)
    tree=BKTree();items=list(unique.values());found=0
    for i,photo in enumerate(items):
        if cancel.is_set(): return False
        candidates=tree.near(int(photo['phash']),10)
        ranked=sorted(candidates,key=lambda j:(int(photo['dhash'])^int(items[j]['dhash'])).bit_count())
        # All neighbors are checked; no silent fixed cap that loses candidates.
        for j in ranked:
            if cancel.is_set(): return False
            other=items[j];a,b=sorted((photo['id'],other['id']))
            prior=catalog.one("SELECT decision FROM pairs WHERE a=? AND b=? AND kind='version'",(a,b))
            if prior: continue
            try: score=version_score(photo,other)
            except (OSError,ValueError): continue
            if score is not None:
                with catalog.db:
                    catalog.db.execute("INSERT INTO pairs VALUES (?,?,'version',?,?,'pending')",(a,b,score,'Compresión o tamaño diferente; requiere comparación visual'))
                found+=1
        tree.add(int(photo['phash']),i)
        report('Comparando versiones',i+1,len(items))
    return True

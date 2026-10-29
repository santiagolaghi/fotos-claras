"""Read-only page data, loaded outside the Qt event loop with bounded galleries."""
from pathlib import Path
from .db import Catalog,PHOTO_FIELDS
from . import matching

PAGE_SIZE=240


def load_page(path,library,section,filters,album,offset=0,group_index=0):
    with Catalog(path) as c:
        if section==0:
            exact=c.one("SELECT COUNT(*) n FROM (SELECT raster FROM photos WHERE library_id=? AND state='active' AND error IS NULL GROUP BY raster HAVING COUNT(*)>1)",(library,))['n']
            versions=c.one("SELECT COUNT(*) n FROM pairs a JOIN photos p ON p.id=a.a JOIN photos q ON q.id=a.b WHERE p.library_id=? AND p.state='active' AND q.state='active' AND a.decision='pending' AND p.error IS NULL AND q.error IS NULL",(library,))['n']
            return dict(records=c.photos(library,limit=6),stats=c.stats(library),exact=exact,versions=versions,
                        people=c.one("SELECT COUNT(DISTINCT f.person_id) n FROM faces f JOIN photos p ON p.id=f.photo_id WHERE p.library_id=? AND p.state='active' AND p.face_state='done' AND p.error IS NULL",(library,))['n'],
                        job=c.one('SELECT * FROM jobs WHERE library_id=? ORDER BY started DESC LIMIT 1',(library,)),
                        pending=c.one("SELECT COUNT(*) n FROM operations WHERE library_id=? AND state NOT IN ('done','undone')",(library,))['n'])
        if section in (1,6):
            query=dict(filters,album=album) if section==1 else dict(no_faces=True)
            total=c.photo_count(library,**query);offset=min(offset,max(0,(total-1)//PAGE_SIZE*PAGE_SIZE))
            return dict(records=c.photos(library,**query,limit=PAGE_SIZE,offset=offset),total=total,offset=offset,
                        stats=c.stats(library))
        if section==2:
            keys=c.rows("SELECT raster,COUNT(*) n FROM photos WHERE library_id=? AND state='active' AND error IS NULL GROUP BY raster HAVING COUNT(*)>1 ORDER BY n DESC,raster",(library,))
            if not keys:return dict(groups=[])
            group_index=min(group_index,len(keys)-1);key=keys[group_index];total=key['n']
            offset=min(offset,max(0,(total-1)//PAGE_SIZE*PAGE_SIZE))
            sql='SELECT '+','.join(PHOTO_FIELDS)+" FROM photos WHERE library_id=? AND raster=? AND state='active' AND error IS NULL ORDER BY width*height DESC,size DESC,path"
            args=(library,key['raster']);recommended=c.one(sql+' LIMIT 1',args)
            return dict(groups=[c.rows(sql+' LIMIT ? OFFSET ?',(*args,PAGE_SIZE,offset))],group_total=len(keys),
                        group_index=group_index,total=total,offset=offset,recommended=recommended)
        if section==3:
            where=""" FROM pairs JOIN photos p ON p.id=a JOIN photos q ON q.id=b
              WHERE p.library_id=? AND p.state='active' AND q.state='active' AND p.error IS NULL AND q.error IS NULL AND decision<>'rejected'"""
            total=c.one('SELECT COUNT(*) n'+where,(library,))['n'];group_index=min(group_index,max(0,total-1))
            rows=c.rows('SELECT a,b,score,reason,decision'+where+' ORDER BY score DESC,a,b LIMIT 1 OFFSET ?',(library,group_index))
            fields=','.join(PHOTO_FIELDS);groups=[]
            for pair in rows:
                group=[c.one('SELECT '+fields+' FROM photos WHERE id=?',(pair[k],)) for k in ('a','b')]
                groups.append(sorted(group,key=lambda p:(p['width']*p['height'],p['size']),reverse=True))
            return dict(groups=groups,pairs=rows,group_total=total,group_index=group_index)
        if section==4:
            total=c.one("SELECT COUNT(DISTINCT pe.id) n FROM people pe JOIN faces f ON f.person_id=pe.id JOIN photos p ON p.id=f.photo_id WHERE p.library_id=? AND p.state='active' AND p.face_state='done' AND p.error IS NULL AND pe.ignored=0",(library,))['n']
            offset=min(offset,max(0,(total-1)//PAGE_SIZE*PAGE_SIZE))
            return dict(records=c.people(library,limit=PAGE_SIZE,offset=offset),total=total,offset=offset)
        if section==5:
            albums=c.rows('SELECT a.*,COUNT(ap.photo_id) n FROM albums a LEFT JOIN album_photos ap ON ap.album_id=a.id WHERE library_id=? GROUP BY a.id ORDER BY a.name',(library,))
            for a in albums:
                if a['rule']:a['n']=c.photo_count(library,album=a['id'])
            # Only paths are read for folder grouping; never fingerprint blobs.
            parents={str(Path(p['path']).parent) for p in c.rows("SELECT path FROM photos WHERE library_id=? AND state='active' AND error IS NULL",(library,))}
            return dict(albums=albums,parents=sorted(parents))
        if section==7:
            return dict(libraries=c.rows('SELECT * FROM libraries ORDER BY created DESC'),
                        errors=c.rows("SELECT path,error,face_error FROM photos WHERE library_id=? AND (error IS NOT NULL OR face_error IS NOT NULL) LIMIT 500",(library,)))
        return {}

"""Transactional, versioned local catalog. Open one instance per worker."""
from __future__ import annotations
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path


def data_dir():
    path = Path(os.environ.get('FOTOSCLARAS_DATA') or
                Path(os.environ.get('LOCALAPPDATA', Path.home() / '.local/share')) / 'FotosClaras')
    path.mkdir(parents=True, exist_ok=True)
    return path


def uid():
    return uuid.uuid4().hex


SCHEMA = '''
CREATE TABLE libraries(id TEXT PRIMARY KEY, path TEXT UNIQUE NOT NULL, created REAL NOT NULL);
CREATE TABLE photos(
 id TEXT PRIMARY KEY, library_id TEXT NOT NULL REFERENCES libraries(id),
 path TEXT NOT NULL, size INTEGER, mtime_ns INTEGER, width INTEGER, height INTEGER,
 sha TEXT, raster TEXT, dhash TEXT, phash TEXT, small BLOB, captured TEXT, format TEXT,
 frames INTEGER DEFAULT 1, thumb TEXT, state TEXT NOT NULL DEFAULT 'active',
 error TEXT, face_state TEXT NOT NULL DEFAULT 'pending', face_error TEXT,
 face_version INTEGER DEFAULT 0, fingerprint_version INTEGER DEFAULT 0,
 seen TEXT, favorite INTEGER NOT NULL DEFAULT 0, UNIQUE(library_id,path));
CREATE INDEX photos_library ON photos(library_id,state);
CREATE INDEX photos_raster ON photos(library_id,raster);
CREATE INDEX photos_sha ON photos(sha);
CREATE TABLE people(id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', ignored INTEGER NOT NULL DEFAULT 0);
CREATE TABLE faces(id TEXT PRIMARY KEY, photo_id TEXT NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
 ordinal INTEGER NOT NULL, person_id TEXT REFERENCES people(id), vector BLOB NOT NULL,
 box TEXT NOT NULL, thumb TEXT, locked INTEGER NOT NULL DEFAULT 0,
 UNIQUE(photo_id,ordinal));
CREATE INDEX faces_person ON faces(person_id);
CREATE INDEX faces_photo ON faces(photo_id);
CREATE TABLE face_rejections(face_id TEXT REFERENCES faces(id) ON DELETE CASCADE,
 person_id TEXT REFERENCES people(id) ON DELETE CASCADE, PRIMARY KEY(face_id,person_id));
CREATE TABLE person_blocks(a TEXT REFERENCES people(id) ON DELETE CASCADE,
 b TEXT REFERENCES people(id) ON DELETE CASCADE, PRIMARY KEY(a,b));
CREATE TABLE pairs(a TEXT REFERENCES photos(id) ON DELETE CASCADE,b TEXT REFERENCES photos(id) ON DELETE CASCADE,
 kind TEXT NOT NULL, score REAL, reason TEXT, decision TEXT NOT NULL DEFAULT 'pending',
 PRIMARY KEY(a,b,kind));
CREATE TABLE albums(id TEXT PRIMARY KEY, library_id TEXT NOT NULL REFERENCES libraries(id),
 name TEXT NOT NULL, UNIQUE(library_id,name));
CREATE TABLE album_photos(album_id TEXT REFERENCES albums(id) ON DELETE CASCADE,
 photo_id TEXT REFERENCES photos(id) ON DELETE CASCADE, PRIMARY KEY(album_id,photo_id));
CREATE TABLE jobs(id TEXT PRIMARY KEY,library_id TEXT REFERENCES libraries(id),kind TEXT,state TEXT,
 stage TEXT,done INTEGER DEFAULT 0,total INTEGER DEFAULT 0,errors INTEGER DEFAULT 0,
 started REAL,updated REAL,message TEXT);
CREATE TABLE operations(id TEXT PRIMARY KEY,library_id TEXT REFERENCES libraries(id),kind TEXT,
 state TEXT NOT NULL,created REAL NOT NULL,error TEXT);
CREATE TABLE operation_items(id INTEGER PRIMARY KEY,operation_id TEXT NOT NULL REFERENCES operations(id),
 photo_id TEXT REFERENCES photos(id),source TEXT,target TEXT,digest TEXT,state TEXT,
 prior_state TEXT NOT NULL DEFAULT 'active',size INTEGER,mtime_ns INTEGER);
CREATE TABLE preferences(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE events(id INTEGER PRIMARY KEY,created REAL,kind TEXT,detail TEXT);
'''


class Catalog:
    def __init__(self, path=None):
        self.path = Path(path or data_dir() / 'catalog-v1.sqlite3')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        if version > 1:
            self.close()
            raise RuntimeError('Esta base requiere una versión más reciente de Fotos Claras')
        if not version:
            self.db.executescript('BEGIN IMMEDIATE;\n' + SCHEMA + '\nPRAGMA user_version=1;\nCOMMIT;')

    def __enter__(self): return self
    def __exit__(self, *args): self.close()
    def close(self): self.db.close()

    def rows(self, sql, args=()):
        return [dict(r) for r in self.db.execute(sql, args)]

    def one(self, sql, args=()):
        r = self.db.execute(sql, args).fetchone()
        return dict(r) if r else None

    def pref(self, key, default=None):
        row = self.one('SELECT value FROM preferences WHERE key=?', (key,))
        return json.loads(row['value']) if row else default

    def set_pref(self, key, value):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO preferences VALUES (?,?)', (key,json.dumps(value,ensure_ascii=False)))

    def library(self, path):
        path = str(Path(path).resolve())
        row = self.one('SELECT * FROM libraries WHERE path=?', (path,))
        if not row:
            with self.db:
                self.db.execute('INSERT INTO libraries VALUES (?,?,?)', (uid(),path,time.time()))
            row = self.one('SELECT * FROM libraries WHERE path=?', (path,))
        self.set_pref('last_library',row['id'])
        return row

    def start_job(self, library, kind):
        job = uid()
        with self.db:
            self.db.execute('INSERT INTO jobs(id,library_id,kind,state,started,updated) VALUES (?,?,?,?,?,?)',
                            (job,library,kind,'running',time.time(),time.time()))
        return job

    def progress(self, job, stage, done, total, errors=0, state='running', message=''):
        with self.db:
            self.db.execute('UPDATE jobs SET stage=?,done=?,total=?,errors=?,state=?,updated=?,message=? WHERE id=?',
                            (stage,done,total,errors,state,time.time(),message,job))

    def photos(self, library, include=(), exclude=(), mode='all', count=None,
               sort='date', no_faces=False, album=None, favorite=False, features=False):
        where, args = ["p.library_id=?", "p.state='active'", "p.error IS NULL"], [library]
        if include or exclude:where.append("p.face_state='done'")
        for person in include:
            where.append('EXISTS(SELECT 1 FROM faces f WHERE f.photo_id=p.id AND f.person_id=?)')
            args.append(person)
        for person in exclude:
            where.append('NOT EXISTS(SELECT 1 FROM faces f WHERE f.photo_id=p.id AND f.person_id=?)')
            args.append(person)
        if mode in ('only','others') and include:
            # Unknown/unidentified faces count as other people, too.
            marks=','.join('?' for _ in include)
            other=f'EXISTS(SELECT 1 FROM faces f WHERE f.photo_id=p.id AND (f.person_id IS NULL OR f.person_id NOT IN ({marks})))'
            where += ["p.face_state='done'", (('NOT ' if mode=='only' else '')+other)]
            args.extend(include)
        if count is not None or no_faces:
            where.append("p.face_state='done'")
            n=0 if no_faces else count
            where.append('(SELECT COUNT(*) FROM faces f WHERE f.photo_id=p.id)'+('>=?' if n==3 else '=?'))
            args.append(n)
        if album:
            where.append('EXISTS(SELECT 1 FROM album_photos a WHERE a.photo_id=p.id AND a.album_id=?)');args.append(album)
        if favorite: where.append('p.favorite=1')
        order={'date':'p.captured DESC,p.path','name':'p.path COLLATE NOCASE', 'size':'p.size DESC','resolution':'p.width*p.height DESC'}.get(sort,'p.path')
        fields='p.*' if features else ','.join('p.'+key for key in ('id','library_id','path','size','mtime_ns','width','height','sha','raster','captured','format','frames','thumb','state','error','face_state','face_error','favorite'))
        return self.rows('SELECT '+fields+',(SELECT COUNT(*) FROM faces f WHERE f.photo_id=p.id) AS face_count FROM photos p WHERE '+' AND '.join(where)+' ORDER BY '+order,args)

    def stats(self, library):
        return self.one('''SELECT COUNT(*) total,SUM(error IS NOT NULL) errors,
          SUM(face_state='error') face_errors,SUM(face_state='pending') pending,
          SUM(face_state='done' AND NOT EXISTS(SELECT 1 FROM faces f WHERE f.photo_id=photos.id)) no_faces
          FROM photos WHERE library_id=? AND state='active' ''',(library,))

    def people(self, library, ignored=False):
        return self.rows('''SELECT pe.*,COUNT(DISTINCT f.photo_id) photos,COUNT(f.id) faces,
          (SELECT f2.thumb FROM faces f2 JOIN photos p2 ON p2.id=f2.photo_id
           WHERE f2.person_id=pe.id AND p2.library_id=? AND p2.state='active' LIMIT 1) thumb
          FROM people pe JOIN faces f ON f.person_id=pe.id JOIN photos p ON p.id=f.photo_id
          WHERE p.library_id=? AND p.state='active' AND p.error IS NULL AND p.face_state='done' AND pe.ignored=?
          GROUP BY pe.id ORDER BY (pe.name=''),photos DESC''',(library,library,int(ignored)))

    def create_album(self, library, name):
        name=name.strip()
        if not name: raise ValueError('Escribí un nombre para el álbum')
        key=uid()
        with self.db: self.db.execute('INSERT INTO albums VALUES (?,?,?)',(key,library,name))
        return key

    def add_album(self, album, ids):
        with self.db:
            for photo in ids:
                if not self.one('SELECT 1 FROM albums a JOIN photos p ON p.library_id=a.library_id WHERE a.id=? AND p.id=?',(album,photo)):
                    raise ValueError('La foto y el álbum deben pertenecer a la misma biblioteca')
                self.db.execute('INSERT OR IGNORE INTO album_photos VALUES (?,?)',(album,photo))

    def log(self, kind, detail):
        with self.db: self.db.execute('INSERT INTO events(created,kind,detail) VALUES (?,?,?)',(time.time(),kind,str(detail)))

    def backup(self, path):
        with sqlite3.connect(path) as target: self.db.backup(target)

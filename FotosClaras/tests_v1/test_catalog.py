import json
import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image,PngImagePlugin
from fotosclaras.db import Catalog,uid
from fotosclaras import indexer,identity,operations,matching,imaging
from fotosclaras.legacy import import_state


class CatalogFlow(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.photos=self.root/'fotos';self.photos.mkdir()
        self.c=Catalog(self.root/'datos'/'catalog.sqlite3');self.library=self.c.library(self.photos)['id']
    def tearDown(self):self.c.close();self.tmp.cleanup()
    def image(self,name,color='red',size=(120,100)):
        path=self.photos/name;path.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',size,color).save(path);return path
    def scan(self,**kw):return indexer.scan(self.c.path,self.library,compare=False,**kw)
    def rows(self):return self.c.photos(self.library)
    def face(self,photo,vector,person=None,locked=0):
        key=uid();ordinal=self.c.one('SELECT COUNT(*) n FROM faces WHERE photo_id=?',(photo,))['n']
        v=np.asarray(vector,dtype=np.float32);v/=np.linalg.norm(v)
        with self.c.db:
            if person:self.c.db.execute('INSERT OR IGNORE INTO people(id) VALUES (?)',(person,))
            self.c.db.execute('INSERT INTO faces(id,photo_id,ordinal,person_id,vector,box,locked) VALUES (?,?,?,?,?,?,?)',(key,photo,ordinal,person,v.tobytes(),'[0,0,1,1]',locked))
            self.c.db.execute("UPDATE photos SET face_state='done',face_version=? WHERE id=?",(identity.MODEL_VERSION,photo))
        return key
    def test_exact_pixels_metadata_and_alpha_and_sequence(self):
        a=self.image('a.png');shutil.copy2(a,self.photos/'a (2).png')
        with Image.open(a) as im:
            meta=PngImagePlugin.PngInfo();meta.add_text('Description','Otra etiqueta');im.save(self.photos/'metadata.png',pnginfo=meta)
        self.scan();groups=matching.exact_groups(self.c,self.library);self.assertEqual([len(g) for g in groups],[3])
        for alpha,name in [(0,'transparent.png'),(255,'opaque.png')]:Image.new('RGBA',(12,12),(120,0,0,alpha)).save(self.photos/name)
        frames=[Image.new('RGB',(12,12),c) for c in ['red','blue']];frames[0].save(self.photos/'anim.webp',save_all=True,append_images=frames[1:])
        self.scan();self.assertNotEqual(self.c.one('SELECT raster FROM photos WHERE path=?',(str(self.photos/'transparent.png'),))['raster'],self.c.one('SELECT raster FROM photos WHERE path=?',(str(self.photos/'opaque.png'),))['raster'])
        self.assertEqual(self.c.one('SELECT frames FROM photos WHERE path=?',(str(self.photos/'anim.webp'),))['frames'],2)
    def test_16bit_samples_not_collapsed_by_rgb_conversion(self):
        a=np.full((12,12),300,dtype=np.uint16);b=a.copy();b[5,5]=301
        Image.fromarray(a).save(self.photos/'a16.tiff');Image.fromarray(b).save(self.photos/'b16.tiff')
        self.scan();self.assertEqual(matching.exact_groups(self.c,self.library),[])
    def test_incremental_and_restart(self):
        self.image('a.png');self.scan();key=self.rows()[0]['id']
        with patch('fotosclaras.indexer.fingerprint',side_effect=AssertionError('reprocesado')):self.scan()
        with Catalog(self.c.path) as other:self.assertEqual(other.photos(self.library)[0]['id'],key)
        self.image('b.png','blue')
        with patch('fotosclaras.indexer.fingerprint',wraps=imaging.fingerprint) as fn:self.scan();self.assertEqual(fn.call_count,1)
    def test_corrupt_is_error_not_zero_faces(self):
        self.image('a.png');(self.photos/'corrupt.jpg').write_bytes(b'bad');self.scan()
        self.assertEqual(self.c.stats(self.library)['errors'],1);self.assertEqual(len(self.c.photos(self.library,no_faces=True)),0)
    def test_pause_does_not_mark_unvisited_missing(self):
        for i in range(5):self.image(f'{i}.png')
        self.scan();cancel=threading.Event()
        def report(stage,n,t):
            if stage=='Leyendo fotografías' and n==2:cancel.set()
        self.scan(cancel=cancel,report=report);self.assertEqual(len(self.rows()),5)
        self.assertEqual(self.c.one('SELECT state FROM jobs ORDER BY started DESC LIMIT 1')['state'],'paused')
        self.scan();self.assertEqual(len(self.rows()),5)
    def test_face_errors_are_not_no_faces(self):
        self.image('good.png');self.image('bad.png','blue');self.scan()
        class Engine:
            def __init__(self,*a):pass
            def detect(self,path):
                if Path(path).name=='bad.png':raise ValueError('modelo falló')
                return []
        result=identity.analyze(self.c.path,self.library,engine_factory=Engine)
        self.assertEqual(result['errors'],1);self.assertEqual(len(self.c.photos(self.library,no_faces=True)),1)
        self.assertEqual(self.c.stats(self.library)['face_errors'],1)
    def test_boolean_filters_unknown_faces_and_album(self):
        for name in ['s','d','sd','sdo','do','none']:self.image(name+'.png')
        self.scan();photos={Path(p['path']).stem:p['id'] for p in self.rows()}
        for name in ['s','sd','sdo']:self.face(photos[name],[1,0,0],'s')
        for name in ['d','sd','sdo','do']:self.face(photos[name],[0,1,0],'d')
        self.face(photos['sdo'],[0,0,1]);self.face(photos['do'],[0,0,1])
        with self.c.db:self.c.db.execute("UPDATE photos SET face_state='done'")
        self.assertEqual(len(self.c.photos(self.library,include=['s'])),3)
        self.assertEqual(len(self.c.photos(self.library,include=['s','d'])),2)
        self.assertEqual(len(self.c.photos(self.library,include=['s','d'],mode='only')),1)
        self.assertEqual(len(self.c.photos(self.library,include=['s','d'],mode='others')),1)
        self.assertEqual(len(self.c.photos(self.library,include=['d'],exclude=['s'])),2)
        self.assertEqual(len(self.c.photos(self.library,count=0)),1)
        self.assertEqual(len(self.c.photos(self.library,count=1)),2)
        self.assertEqual(len(self.c.photos(self.library,count=2)),2)
        self.assertEqual(len(self.c.photos(self.library,count=3)),1)
        album=self.c.create_album(self.library,'Santi y Dai');self.c.add_album(album,[photos['sd'],photos['sdo']]);self.c.add_album(album,[photos['sd']])
        self.assertEqual(len(self.c.photos(self.library,album=album)),2)
        self.assertEqual(len(list(self.photos.iterdir())),6)
        with Catalog(self.c.path) as again:self.assertEqual(len(again.photos(self.library,album=album)),2)
    def test_cached_face_results_do_not_restart_models(self):
        self.image('none.png');self.scan();calls=[]
        class Engine:
            def __init__(self,*a):calls.append('engine')
            def detect(self,path):calls.append('detect');return []
        identity.analyze(self.c.path,self.library,engine_factory=Engine)
        with Catalog(self.c.path) as again:self.assertEqual(len(again.photos(self.library,no_faces=True)),1)
        result=identity.analyze(self.c.path,self.library,engine_factory=Engine)
        self.assertEqual(result['done'],0);self.assertEqual(calls,['engine','detect'])
    def test_name_split_veto_merge_ignore_restart(self):
        for i in range(4):self.image(f'{i}.png')
        self.scan();rows=self.rows()
        f1=self.face(rows[0]['id'],[1,0,0],'s');f2=self.face(rows[1]['id'],[.99,.02,0],'s')
        self.face(rows[2]['id'],[0,1,0],'d');f4=self.face(rows[3]['id'],[.8,.1,0],'fragment')
        identity.name_person(self.c,'s','Santiago');identity.regroup(self.c,self.library)
        self.assertEqual(self.c.one('SELECT person_id FROM faces WHERE id=?',(f4,))['person_id'],'s')
        new=identity.split(self.c,'s',[f2]);identity.regroup(self.c,self.library)
        self.assertEqual(self.c.one('SELECT person_id FROM faces WHERE id=?',(f2,))['person_id'],new)
        identity.merge(self.c,new,'s');identity.ignore(self.c,'s')
        with Catalog(self.c.path) as again:
            self.assertEqual(again.one('SELECT name FROM people WHERE id=?',('s',))['name'],'Santiago')
            self.assertEqual(len(again.people(self.library,True)),1)
            self.assertTrue(again.one('SELECT locked FROM faces WHERE id=?',(f1,))['locked'])
    def test_cannot_merge_cooccurring_people(self):
        self.image('pair.png');self.scan();p=self.rows()[0]['id'];self.face(p,[1,0],'a');self.face(p,[0,1],'b')
        with self.assertRaises(ValueError):identity.merge(self.c,'a','b')
    def test_move_preview_collision_undo_and_identity(self):
        self.image('a/x.png');self.image('b/x.png','blue');self.scan();rows=self.rows();self.face(rows[0]['id'],[1,0],'s',1)
        target=self.root/'destino';p=operations.plan(self.c,self.library,[r['id'] for r in rows],target)
        self.assertFalse(target.exists());self.assertEqual(len({i['target'] for i in p['items']}),2)
        key=operations.save_plan(self.c,p);operations.execute(self.c,key)
        self.assertTrue(all(Path(r['path']).exists() for r in self.rows()))
        self.assertEqual(self.c.one('SELECT person_id FROM faces')['person_id'],'s')
        self.assertEqual(operations.undo(self.c,key),2);self.assertTrue((self.photos/'a/x.png').exists());self.assertTrue((self.photos/'b/x.png').exists())
        self.assertEqual(self.c.one('SELECT state FROM operations WHERE id=?',(key,))['state'],'undone')
    def test_destination_appearing_after_plan_and_modified_undo(self):
        self.image('x.png');self.scan();p=operations.plan(self.c,self.library,[self.rows()[0]['id']],self.root/'dest')
        dst=Path(p['items'][0]['target']);dst.parent.mkdir();dst.write_bytes(b'do not overwrite')
        key=operations.save_plan(self.c,p)
        with self.assertRaises(operations.OperationConflict):operations.execute(self.c,key)
        self.assertEqual(dst.read_bytes(),b'do not overwrite');self.assertTrue((self.photos/'x.png').exists())
        dst.unlink();operations.execute(self.c,key);dst.write_bytes(b'edited')
        with self.assertRaises(operations.OperationConflict):operations.undo(self.c,key)
        self.assertEqual(dst.read_bytes(),b'edited')
    def test_crash_after_copy_before_delete_and_resume(self):
        self.image('x.png');self.scan();p=operations.plan(self.c,self.library,[self.rows()[0]['id']],self.root/'dest');key=operations.save_plan(self.c,p)
        item=self.c.one('SELECT * FROM operation_items WHERE operation_id=?',(key,))
        with self.c.db:self.c.db.execute("UPDATE operation_items SET state='copying' WHERE id=?",(item['id'],))
        operations.exclusive_copy(item['source'],item['target'],item['digest'])
        with Catalog(self.c.path) as after:operations.execute(after,key)
        self.assertFalse(Path(item['source']).exists());self.assertTrue(Path(item['target']).exists());self.assertEqual(operations.undo(self.c,key),1)
    def test_cancel_move_resume_and_no_photo_loss(self):
        for i in range(4):self.image(str(i)+'.png')
        self.scan();p=operations.plan(self.c,self.library,[r['id'] for r in self.rows()],self.root/'dest');key=operations.save_plan(self.c,p);cancel=threading.Event()
        operations.execute(self.c,key,cancel,lambda *a:cancel.set())
        self.assertEqual(self.c.one('SELECT state FROM operations WHERE id=?',(key,))['state'],'paused')
        self.assertEqual(len(self.rows()),4);operations.execute(self.c,key);self.assertEqual(operations.undo(self.c,key),4)
    def test_copy_undo_is_recoverable(self):
        path=self.image('x.png');self.scan();p=operations.plan(self.c,self.library,[self.rows()[0]['id']],self.root/'dest','copy');key=operations.save_plan(self.c,p);operations.execute(self.c,key)
        self.assertTrue(path.exists());operations.undo(self.c,key);self.assertTrue(path.exists());self.assertFalse(Path(p['items'][0]['target']).exists());self.assertTrue(any((self.c.path.parent/'recovered-copies'/key).iterdir()))
    def test_legacy_import_preserves_names_and_files(self):
        legacy=self.c.path.parent/'personas_v2.json';legacy.write_text(json.dumps({'people':[{'id':'old','name':'Daiana','templates':[[1,0]]}],'overrides':{'hash:0':'old'}}));before=legacy.read_bytes()
        import_state(self.c);self.assertEqual(self.c.one('SELECT name FROM people WHERE id=?',('old',))['name'],'Daiana');self.assertEqual(legacy.read_bytes(),before)
        self.assertEqual(self.c.pref('legacy_people')['overrides']['hash:0'],'old')
    def test_crash_after_intent_before_copy_retries_safely(self):
        self.image('x.png');self.scan();p=operations.plan(self.c,self.library,[self.rows()[0]['id']],self.root/'dest');key=operations.save_plan(self.c,p)
        with self.c.db:self.c.db.execute("UPDATE operation_items SET state='copying' WHERE operation_id=?",(key,))
        operations.execute(self.c,key);self.assertEqual(operations.undo(self.c,key),1)
    def test_import_legacy_move_history_and_undo(self):
        import hashlib
        path=self.image('original.png');self.scan();target=self.root/'old-album/renamed.png';target.parent.mkdir();shutil.move(str(path),target)
        key=hashlib.sha256(str(self.photos.resolve()).encode()).hexdigest()[:20]
        journal=self.c.path.parent/f'movimientos_{key}.jsonl'
        journal.write_text(json.dumps({'time':1,'moves':[{'from':str(path),'to':str(target)}]})+'\n')
        before=journal.read_bytes()
        from fotosclaras.legacy import import_history
        self.assertEqual(import_history(self.c,self.library),1);self.assertEqual(import_history(self.c,self.library),0)
        op=self.c.one('SELECT id FROM operations')['id'];operations.undo(self.c,op)
        self.assertTrue(path.exists());self.assertFalse(target.exists());self.assertEqual(journal.read_bytes(),before)
    def test_overlapping_libraries_keep_independent_catalogs(self):
        self.image('sub/foto.png');self.scan();other=self.c.library(self.photos/'sub')['id'];indexer.scan(self.c.path,other,compare=False)
        self.assertEqual(len(self.c.photos(self.library)),1);self.assertEqual(len(self.c.photos(other)),1)
    def test_quarantine_undo_excludes_without_disappearing_identity(self):
        self.image('x.png');self.scan();p=self.rows()[0];self.face(p['id'],[1,0],'s',1)
        plan=operations.plan(self.c,self.library,[p['id']],self.photos/'FotosClaras_ParaRevisar','quarantine');key=operations.save_plan(self.c,plan);operations.execute(self.c,key)
        self.assertFalse(self.rows());self.scan();self.assertFalse(self.rows());self.assertEqual(self.c.one('SELECT person_id FROM faces')['person_id'],'s')
        operations.undo(self.c,key);self.assertEqual(len(self.rows()),1)
    def test_backup_and_schema_version(self):
        self.image('x.png');self.scan();backup=self.root/'backup.sqlite3';self.c.backup(backup)
        with Catalog(backup) as c:self.assertEqual(len(c.photos(self.library)),1)

if __name__=='__main__':unittest.main()

"""Regression cases for missed identities, unsafe grouping and live combinations."""
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
import numpy as np
from fotosclaras.db import Catalog,SCHEMA,uid
from fotosclaras import identity
from fotosclaras.face_matching import diverse_templates


class IdentityFlow(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.c=Catalog(self.root/'state/catalog.sqlite3');self.library=self.c.library(self.root/'photos')['id']
    def tearDown(self):self.c.close();self.tmp.cleanup()
    def photo(self,library=None,state='done'):
        key=uid()
        with self.c.db:self.c.db.execute('INSERT INTO photos(id,library_id,path,face_state) VALUES (?,?,?,?)',(key,library or self.library,str(self.root/(key+'.jpg')),state))
        return key
    def face(self,vector,person=None,locked=0,photo=None,quality=1,box=(.1,.1,.3,.3)):
        photo=photo or self.photo();key=uid();v=np.asarray(vector,dtype=np.float32);v/=np.linalg.norm(v)
        with self.c.db:
            if person:self.c.db.execute('INSERT OR IGNORE INTO people(id) VALUES (?)',(person,))
            n=self.c.one('SELECT COUNT(*) n FROM faces WHERE photo_id=?',(photo,))['n']
            self.c.db.execute('INSERT INTO faces(id,photo_id,ordinal,person_id,vector,box,locked,quality) VALUES (?,?,?,?,?,?,?,?)',
                             (key,photo,n,person,v.tobytes(),json.dumps(box),locked,quality))
        return key
    def person(self,key):return self.c.one('SELECT person_id FROM faces WHERE id=?',(key,))['person_id']
    def test_probable_match_confirmation_teaches_remaining_faces(self):
        self.face([1,0,0],'s',1);identity.name_person(self.c,'s','Santi')
        candidate=self.face([.42,.9075,0]);other=self.face([.43,.902,.04])
        identity.regroup(self.c,self.library)
        self.assertNotEqual(self.person(candidate),'s')
        self.assertEqual(len(self.c.rows('SELECT * FROM face_candidates WHERE person_id=?',('s',))),2)
        identity.review_matches(self.c,'s',[candidate],True);identity.regroup(self.c,self.library)
        self.assertEqual(self.person(other),'s')
        self.assertEqual(self.c.one('SELECT match_state FROM faces WHERE id=?',(other,))['match_state'],'automatic')
        with Catalog(self.c.path) as again:
            self.assertEqual(again.one('SELECT locked FROM faces WHERE id=?',(candidate,))['locked'],1)
    def test_rejection_and_split_survive_search_and_restart(self):
        self.face([1,0,0],'s',1);identity.name_person(self.c,'s','Santi');candidate=self.face([.4,.9165,0])
        identity.regroup(self.c,self.library);identity.review_matches(self.c,'s',[candidate],False)
        with Catalog(self.c.path) as again:identity.regroup(again,self.library)
        self.assertFalse(self.c.one('SELECT 1 FROM face_candidates WHERE face_id=? AND person_id=?',(candidate,'s')))
        self.assertNotEqual(self.person(candidate),'s')
    def test_ambiguous_people_do_not_become_confident_identity(self):
        self.face([1,0,0],'s',1);self.face([.98,.2,0],'d',1)
        identity.name_person(self.c,'s','Santi');identity.name_person(self.c,'d','Dai')
        candidate=self.face([.99,.1,0]);identity.regroup(self.c,self.library)
        self.assertNotIn(self.person(candidate),('s','d'))
        self.assertEqual(len(self.c.rows('SELECT * FROM face_candidates WHERE face_id=?',(candidate,))),2)
    def test_low_quality_face_counts_as_third_without_auto_identity(self):
        self.face([1,0,0],'s',1);identity.name_person(self.c,'s','Santi')
        photo=self.photo();self.face([1,0,0],'s',1,photo);third=self.face([1,.03,0],photo=photo,quality=.1)
        identity.regroup(self.c,self.library)
        self.assertNotEqual(self.person(third),'s')
        self.assertEqual(len(self.c.photos(self.library,include=['s'],mode='others')),1)
        with self.assertRaises(ValueError):identity.review_matches(self.c,'s',[third],True)
    def test_diverse_references_include_late_confirmed_appearance(self):
        vectors=np.array([[1,.001*i,0] for i in range(80)]+[[0,1,0]],dtype=np.float32)
        vectors/=np.linalg.norm(vectors,axis=1,keepdims=True)
        selected=diverse_templates(vectors,np.ones(len(vectors)))
        self.assertTrue(any(v[1]>.99 for v in selected))
        for vector in vectors:self.face(vector,'s',1)
        identity.name_person(self.c,'s','Santi');candidate=self.face([.01,.99,0]);identity.regroup(self.c,self.library)
        self.assertEqual(self.person(candidate),'s')
    def test_confirmed_identity_is_available_in_other_library(self):
        self.face([1,0,0],'s',1);identity.name_person(self.c,'s','Santi')
        other=self.c.library(self.root/'other')['id'];candidate=self.face([1,.02,0],photo=self.photo(other))
        identity.regroup(self.c,other);self.assertEqual(self.person(candidate),'s')
    def test_renaming_does_not_promote_automatic_matches_to_references(self):
        self.face([1,0,0],'s',1);identity.name_person(self.c,'s','Santi')
        candidate=self.face([1,.01,0]);identity.regroup(self.c,self.library)
        identity.name_person(self.c,'s','Santiago')
        self.assertEqual(self.c.one('SELECT locked FROM faces WHERE id=?',(candidate,))['locked'],0)
    def test_large_portrait_tiles_leave_no_unexamined_middle(self):
        for length in (800,1600,2400,3200):
            covered=np.zeros(length,dtype=bool)
            for start in identity.tile_positions(length):covered[start:start+1500]=True
            self.assertTrue(covered.all(),length)
    def test_redetection_preserves_ids_names_and_negative_corrections(self):
        from PIL import Image
        photo=self.photo();key=self.face([1,0,0],'s',1,photo);identity.name_person(self.c,'s','Santi')
        self.c.db.execute('INSERT INTO people(id) VALUES (?)',('d',));self.c.db.commit()
        self.c.db.execute('INSERT INTO face_rejections VALUES (?,?)',(key,'d'));self.c.db.commit()
        folder=self.root/'faces';folder.mkdir();p=self.c.one('SELECT * FROM photos WHERE id=?',(photo,))
        detections=[dict(vector=np.array([1,0,0],dtype=np.float32),box=[.11,.1,.3,.3],crop=np.asarray(Image.new('RGB',(80,80))))]
        identity.save_detections(self.c,p,detections,folder)
        self.assertEqual(self.person(key),'s');self.assertEqual(self.c.one('SELECT locked FROM faces WHERE id=?',(key,))['locked'],1)
        self.assertTrue(self.c.one('SELECT 1 FROM face_rejections WHERE face_id=?',(key,)))
        identity.save_detections(self.c,p,[],folder)
        self.assertEqual(self.person(key),'s');self.assertEqual(len(self.c.rows('SELECT * FROM faces WHERE photo_id=?',(photo,))),1)
    def test_live_album_compositions_update_after_new_confirmations(self):
        solo=self.photo();pair=self.photo();group=self.photo();failed=self.photo(state='error')
        for p in (solo,pair,group,failed):self.face([1,0,0],'s',1,p)
        for p in (pair,group):self.face([0,1,0],'d',1,p)
        self.face([0,0,1],photo=group)
        identity.name_person(self.c,'s','Santi');identity.name_person(self.c,'d','Dai')
        self.assertEqual(self.c.composition(self.library,['s','d']),dict(all=2,only=1,others=1))
        album=self.c.create_album(self.library,'Santi y Dai',dict(include=['s','d'],mode='only'))
        self.assertEqual([p['id'] for p in self.c.photos(self.library,album=album)],[pair])
        fresh=self.photo();self.face([1,0,0],'s',1,fresh);self.face([0,1,0],'d',1,fresh)
        with Catalog(self.c.path) as again:self.assertEqual(again.photo_count(self.library,album=album),2)
        with self.assertRaises(ValueError):self.c.add_album(album,[solo])
    def test_paginated_query_has_stable_order_and_no_large_fingerprints(self):
        for _ in range(520):self.photo()
        first=self.c.photos(self.library,limit=240);second=self.c.photos(self.library,limit=240,offset=240)
        self.assertEqual(self.c.photo_count(self.library),520);self.assertFalse({p['id'] for p in first}&{p['id'] for p in second})
        self.assertNotIn('small',first[0]);self.assertEqual(len(self.c.photos(self.library,limit=240,offset=480)),40)
    def test_schema_upgrade_retains_old_data_and_backup(self):
        path=self.root/'old.sqlite3'
        with sqlite3.connect(path) as old:
            old.executescript(SCHEMA+'\nPRAGMA user_version=1;')
            old.execute('INSERT INTO people(id,name) VALUES (?,?)',('s','Santi'))
        with Catalog(path) as upgraded:
            self.assertEqual(upgraded.one('SELECT name FROM people')['name'],'Santi')
            self.assertEqual(upgraded.db.execute('PRAGMA user_version').fetchone()[0],2)
        backup=path.with_name('old-before-v2.sqlite3');self.assertTrue(backup.exists())
        with sqlite3.connect(backup) as old:self.assertEqual(old.execute('PRAGMA user_version').fetchone()[0],1)

if __name__=='__main__':unittest.main()

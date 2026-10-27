"""Actual photographs + actual models. Produces measured evidence, fails on mismatches."""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'FotosClaras'))
from real_fixtures import download
from fotosclaras.db import Catalog
from fotosclaras.imaging import fingerprint
from fotosclaras import indexer,identity,matching,operations
from PIL import Image,ImageEnhance


def run():
    fixtures=download(ROOT/'validation/real');models=ROOT/'validation/models'
    identity.ensure_models(models,report=lambda s,d,t:print(s,d,t,flush=True) if d==t else None)
    start=time.perf_counter();engine=identity.FaceEngine(models)
    vectors={};counts={}
    for name in ['obama.jpg','obama2.jpg','biden.jpg','two_people.jpg','scenery.jpg']:
        found=engine.detect(fixtures/name);counts[name]=len(found);vectors[name]=[f['vector'] for f in found]
    print('Rostros:',counts,flush=True)
    assert counts=={'obama.jpg':1,'obama2.jpg':1,'biden.jpg':1,'two_people.jpg':2,'scenery.jpg':0},counts
    same=float(vectors['obama.jpg'][0]@vectors['obama2.jpg'][0]);different=float(vectors['obama.jpg'][0]@vectors['biden.jpg'][0])
    print('Coseno misma persona / diferente:',same,different,flush=True)
    assert same>=.5 and different<.5,(same,different)
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp);photos=root/'photos';photos.mkdir();c=Catalog(root/'data/catalog.sqlite3');library=c.library(photos)['id']
        for name in ['obama.jpg','obama2.jpg','biden.jpg','two_people.jpg','scenery.jpg']:shutil.copy2(fixtures/name,photos/name)
        shutil.copy2(photos/'obama.jpg',photos/'obama (2).jpg')
        with Image.open(photos/'obama.jpg') as im:
            im.resize((455,568),Image.Resampling.LANCZOS).save(photos/'whatsapp.jpg',quality=68)
        result=indexer.scan(c.path,library);assert not result['errors']
        groups=matching.exact_groups(c,library);assert [len(g) for g in groups]==[2]
        recompressed=c.one('SELECT * FROM photos WHERE path=?',(str(photos/'whatsapp.jpg'),))
        original=c.one('SELECT * FROM photos WHERE path=?',(str(photos/'obama.jpg'),))
        assert matching.version_score(original,recompressed) is not None
        # Distinct real exposures of the same person cannot be proven duplicates.
        other=c.one('SELECT * FROM photos WHERE path=?',(str(photos/'obama2.jpg'),))
        assert original['raster']!=other['raster'];assert matching.version_score(original,other) is None
        burst=[fingerprint(fixtures/name,root/'thumbnails') for name in ['basketball1.png','basketball2.png']]
        for record,name in zip(burst,['basketball1.png','basketball2.png']):record['path']=str(fixtures/name)
        assert burst[0]['raster']!=burst[1]['raster'] and matching.version_score(*burst) is None
        models_data=c.path.parent/'models';shutil.copytree(models,models_data)
        result=identity.analyze(c.path,library);assert result['errors']==0,result
        people=c.people(library);print('Grupos reales:',[(p['photos'],p['name']) for p in people],flush=True)
        original_face=c.one('SELECT * FROM faces WHERE photo_id=?',(original['id'],));identity.name_person(c,original_face['person_id'],'Persona A');identity.regroup(c,library)
        only=c.photos(library,include=[original_face['person_id']]);paths={Path(p['path']).name for p in only}
        assert {'obama.jpg','obama2.jpg','whatsapp.jpg','obama (2).jpg','two_people.jpg'}<=paths,paths
        assert 'biden.jpg' not in paths
        pair=c.one('SELECT * FROM photos WHERE path=?',(str(photos/'two_people.jpg'),))
        pair_faces=c.rows('SELECT * FROM faces WHERE photo_id=?',(pair['id'],));assert len({f['person_id'] for f in pair_faces})==2
        b=c.one('SELECT person_id FROM faces WHERE photo_id=(SELECT id FROM photos WHERE path=?)',(str(photos/'biden.jpg'),))['person_id'];identity.name_person(c,b,'Persona B')
        assert len(c.photos(library,include=[original_face['person_id'],b]))==1
        assert len(c.photos(library,include=[original_face['person_id'],b],mode='only'))==1
        assert len(c.photos(library,no_faces=True))==1
        # Correct a real embedding, rerun grouping, and explicitly merge it back.
        split_face=c.one('SELECT id FROM faces WHERE photo_id=?',(other['id'],))['id']
        separated=identity.split(c,original_face['person_id'],[split_face]);identity.regroup(c,library)
        assert c.one('SELECT person_id FROM faces WHERE id=?',(split_face,))['person_id']==separated
        identity.merge(c,separated,original_face['person_id'])
        album=c.create_album(library,'Personas A y B');c.add_album(album,[pair['id']]);assert len(c.photos(library,album=album))==1
        operation=operations.plan(c,library,[other['id']],root/'album-real');key=operations.save_plan(c,operation);operations.execute(c,key)
        assert not Path(other['path']).exists();assert c.one('SELECT person_id FROM faces WHERE id=?',(split_face,))['person_id']==original_face['person_id']
        assert operations.undo(c,key)==1 and Path(other['path']).is_file()
        c.close()
        with Catalog(root/'data/catalog.sqlite3') as again:assert again.one('SELECT COUNT(*) n FROM people WHERE name<>\'\'')['n']==2
    report=dict(platform=sys.platform,real_photo_counts=counts,cosine_same_person=same,cosine_different_people=different,elapsed_seconds=round(time.perf_counter()-start,3),
        assertions=['exact copy','simulated WhatsApp compression (resize/JPEG, not actual WhatsApp export)','distinct real exposure rejected','similar sports frames rejected','real-embedding split/merge','real-file move/undo','virtual album','1/2/0 face detection','same-person grouping','two-person all/only filters','restart identities'],
        limitations=['Small public sample, not a family benchmark','No age/profile/twins coverage','Not real WhatsApp messaging export','Windows UI and installer require separate workflow evidence'])
    out=ROOT/'validation/real-results.json';out.write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))

if __name__=='__main__':run()

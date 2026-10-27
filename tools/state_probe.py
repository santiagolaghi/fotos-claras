"""Seed and verify actual catalog/identities/albums/history around Windows installers."""
import json
import os
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'FotosClaras'))
from fotosclaras.db import Catalog,data_dir

def snapshot(c):
    return {table:c.rows('SELECT * FROM '+table+' ORDER BY 1') for table in ['libraries','photos','people','albums','album_photos','preferences','operations','operation_items']}

folder=data_dir();expected=folder/'installer-probe.json'
with Catalog() as c:
    if sys.argv[1]=='seed':
        from fotosclaras.legacy import import_state
        import_state(c)
        library=c.library(folder.parent/'Familia (prueba de instalacion)')['id']
        with c.db:
            c.db.execute("INSERT INTO people(id,name) VALUES ('santi','Santiago')")
            c.db.execute("INSERT INTO people(id,name) VALUES ('dai','Daiana')")
            c.db.execute("INSERT INTO operations(id,library_id,kind,state,created) VALUES ('history',?,'move','undone',1)",(library,))
        c.set_pref('keep_this',dict(sort='date',include=['santi','dai'],mode='only'))
        album=c.create_album(library,'Santi y Dai')
        expected.write_text(json.dumps(snapshot(c),ensure_ascii=False),encoding='utf-8')
    else:
        assert snapshot(c)==json.loads(expected.read_text(encoding='utf-8')),'Installer changed local catalog state'
        print('Catalog/identities/preferences/albums/history survived.')

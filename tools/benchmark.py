"""Reproducible workload: real decoded images repeated as files, plus cached reopening."""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'FotosClaras'))
from real_fixtures import download
from fotosclaras.db import Catalog
from fotosclaras.indexer import scan
from PIL import Image

def run(n):
    fixtures=download(ROOT/'validation/real')
    with tempfile.TemporaryDirectory() as tmp:
        base=Path(tmp);photos=base/'photos';photos.mkdir();variants=[]
        for f in sorted(p for p in fixtures.iterdir() if p.suffix.lower() in ('.jpg','.png')):
            with Image.open(f) as image:
                image.thumbnail((400,400));target=base/(f.stem+'.jpg');image.convert('RGB').save(target,quality=80);variants.append(target)
        for i in range(n):shutil.copy2(variants[i%len(variants)],photos/f'{i:06}.jpg')
        with Catalog(base/'data/catalog.sqlite3') as c:library=c.library(photos)['id'];db_path=c.path
        start=time.perf_counter();result=scan(db_path,library);initial=time.perf_counter()-start
        start=time.perf_counter();cached=scan(db_path,library);incremental=time.perf_counter()-start
        start=time.perf_counter()
        with Catalog(db_path) as c:rows=c.photos(library);assert len(rows)==n
        reopening=time.perf_counter()-start
        assert not result['errors'] and not cached['errors']
        rss=None
        try:
            import resource
            rss=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,2)
        except ImportError:pass
        report=dict(platform=sys.platform,files=n,real_sources=len(variants),max_input_side=400,initial_seconds=round(initial,3),cached_seconds=round(incremental,3),catalog_open_seconds=round(reopening,3),peak_process_mib=rss,
          limitations='Repeated resized real photographs; measures file count/cache, not full-resolution unique-photo matching or 10,000-person clustering.')
        (ROOT/'validation').mkdir(exist_ok=True);(ROOT/'validation/benchmark.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--files',type=int,default=10000);run(p.parse_args().files)

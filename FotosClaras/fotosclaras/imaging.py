"""Bounded decoding, full pixel proof and disk thumbnail cache."""
from __future__ import annotations
import hashlib
import os
import warnings
from datetime import datetime
from pathlib import Path
import numpy as np
from PIL import Image, ImageOps
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError: pass

VERSION=3
EXTENSIONS={'.jpg','.jpeg','.png','.webp','.bmp','.tif','.tiff','.heic','.heif'}
Image.MAX_IMAGE_PIXELS=60_000_000
RESAMPLE=Image.Resampling.LANCZOS
x=np.arange(32)
DCT=np.cos(np.pi*(2*x[None,:]+1)*x[:,None]/64)
DCT[0]*=np.sqrt(1/32);DCT[1:]*=np.sqrt(2/32)


def sha256(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()


def open_rgb(path, max_side=None):
    with warnings.catch_warnings():
        warnings.simplefilter('error',Image.DecompressionBombWarning)
        with Image.open(path) as source:
            if max_side: source.draft('RGB',(max_side,max_side))
            ImageOps.exif_transpose(source,in_place=True)
            if max_side:source.thumbnail((max_side,max_side),RESAMPLE)
            if source.mode in ('RGBA','LA') or 'transparency' in source.info:
                rgba=source.convert('RGBA');image=Image.new('RGB',rgba.size,'white');image.paste(rgba,mask=rgba.getchannel('A'));return image
            return source.convert('RGB')


def fingerprint(path, cache):
    path=Path(path)
    before=path.stat()
    digest=sha256(path)
    with warnings.catch_warnings():
        warnings.simplefilter('error',Image.DecompressionBombWarning)
        with Image.open(path) as source:
            frames=getattr(source,'n_frames',1)
            exif=source.getexif()
            date=exif.get(36867) or exif.get(306)
            try: captured=datetime.strptime(str(date),'%Y:%m:%d %H:%M:%S').isoformat()
            except ValueError: captured=datetime.fromtimestamp(before.st_mtime).isoformat()
            fmt=source.format
            ImageOps.exif_transpose(source,in_place=True)
            oriented=source
            w,h=oriented.size
            # Do not prove 16-bit/float/CMYK equality with an 8-bit RGB conversion.
            canonical=oriented.mode in ('RGB','RGBA','L','LA','P','1')
            proof_mode='RGBA' if canonical else oriented.mode
            profile=source.info.get('icc_profile') or b''
            raster=hashlib.sha256(f'{proof_mode}:{w}x{h}:'.encode()+hashlib.sha256(profile).digest())
            for top in range(0,h,64):
                strip=oriented.crop((0,top,w,min(h,top+64)))
                if canonical:strip=strip.convert('RGBA')
                raster.update(strip.tobytes())
            # A single-frame fingerprint cannot prove equality of an animation.
            raster_digest=raster.hexdigest() if frames==1 else 'sequence:'+digest
            if int(source.info.get('bit_depth') or 8)>8 and oriented.mode in ('RGB','RGBA'):
                raster_digest='high-depth:'+digest
            if oriented.mode in ('RGB','L','CMYK','I','F','I;16','I;16B','1'):
                rgb=oriented if oriented.mode=='RGB' else oriented.convert('RGB')
            else:
                image=oriented.convert('RGBA')
                rgb=Image.new('RGB',image.size,'white');rgb.paste(image,mask=image.getchannel('A'))
            gray=np.asarray(rgb.resize((9,8),RESAMPLE).convert('L'))
            dhash=sum(1<<i for i,v in enumerate((gray[:,:-1]>gray[:,1:]).flat) if v)
            small=rgb.resize((64,64),RESAMPLE)
            frequencies=(DCT@np.asarray(rgb.resize((32,32),RESAMPLE).convert('L'),dtype=float)@DCT.T)[:8,:8]
            phash=sum(1<<i for i,v in enumerate(frequencies.flat) if v>np.median(frequencies.flat[1:]))
            thumb=thumbnail(path,cache,key=digest,image=rgb)
    after=path.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
        raise OSError('El archivo cambió durante la lectura; volvé a analizarlo')
    return dict(size=after.st_size,mtime_ns=after.st_mtime_ns,width=w,height=h,sha=digest,
                raster=raster_digest,dhash=str(dhash),phash=str(phash),small=small.tobytes(),
                captured=captured,format=fmt,frames=frames,thumb=str(thumb),fingerprint_version=VERSION)


def thumbnail(path,cache,key=None,image=None):
    cache=Path(cache);cache.mkdir(parents=True,exist_ok=True)
    if key is None:
        stat=Path(path).stat()
        key=hashlib.sha256(f'{path}:{stat.st_size}:{stat.st_mtime_ns}'.encode()).hexdigest()
    target=cache/(key+'.jpg')
    if not target.exists():
        import uuid
        preview=(ImageOps.contain(image,(640,480),RESAMPLE) if image else open_rgb(path,800))
        preview.thumbnail((640,480),RESAMPLE)
        temp=target.with_suffix('.'+uuid.uuid4().hex+'.tmp')
        try:
            preview.save(temp,format='JPEG',quality=85)
            os.replace(temp,target)
        finally: temp.unlink(missing_ok=True)
    return target

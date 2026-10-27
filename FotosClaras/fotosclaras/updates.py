"""Verified GitHub Windows installers; user state never lives in install paths."""
import hashlib
import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path
from . import __version__

REPOSITORY='santiagolaghi/fotos-claras'
ASSET='Fotos-Claras-Setup.exe'
MAX_SIZE=800*1024*1024

def number(tag):
    m=re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)(?:-beta\.(\d+))?',tag)
    if not m: raise ValueError('Número de versión inválido')
    a,b,c,beta=m.groups();return (int(a),int(b),int(c),int(beta) if beta else 1_000_000)

def check(include_beta=False):
    url=f'https://api.github.com/repos/{REPOSITORY}/releases'+('' if include_beta else '/latest')
    req=urllib.request.Request(url,headers={'User-Agent':'FotosClaras/'+__version__,'Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(req,timeout=15) as response: data=json.load(response)
    releases=data if isinstance(data,list) else [data]
    choices=[]
    for release in releases:
        if release.get('draft') or (release.get('prerelease') and not include_beta): continue
        try: newer=number(release['tag_name'])>number(__version__)
        except ValueError: continue
        if not newer: continue
        asset=next((x for x in release.get('assets',[]) if x['name']==ASSET),None)
        if not asset: continue
        digest=asset.get('digest','');url=asset.get('browser_download_url','')
        if not re.fullmatch('sha256:[0-9a-f]{64}',digest): raise ValueError('La versión publicada no tiene huella de integridad')
        if not url.startswith(f'https://github.com/{REPOSITORY}/releases/download/') or not url.endswith('/'+ASSET): raise ValueError('Origen de actualización inválido')
        choices.append(dict(version=release['tag_name'],url=url,sha256=digest[7:],size=asset.get('size',0)))
    return max(choices,key=lambda r:number(r['version'])) if choices else None


def download(release,folder,cancel,report=lambda *a:None):
    if not release['url'].startswith(f'https://github.com/{REPOSITORY}/releases/download/'):
        raise ValueError('Origen de actualización inválido')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    target=folder/ASSET;tmp=target.with_suffix('.part');h=hashlib.sha256();done=0
    try:
        with urllib.request.urlopen(release['url'],timeout=20) as src,tmp.open('wb') as dst:
            while block:=src.read(512*1024):
                if cancel.is_set(): raise InterruptedError('Descarga cancelada')
                done+=len(block)
                if done>MAX_SIZE: raise ValueError('Paquete demasiado grande')
                h.update(block);dst.write(block);report('Descargando actualización',done,release.get('size',0))
            dst.flush();os.fsync(dst.fileno())
        if h.hexdigest()!=release['sha256']: raise ValueError('La descarga no pasó la verificación SHA-256')
        tmp.replace(target)
    finally: tmp.unlink(missing_ok=True)
    return target


def install(path,install_root):
    if os.name!='nt': raise RuntimeError('El instalador solo se ejecuta en Windows')
    if not Path(path).is_file(): raise ValueError('No se encontró el instalador')
    # Installer writes an isolated version then switches the launcher pointer.
    subprocess.Popen([str(path),'/VERYSILENT','/NORESTART','/CURRENTUSER',f'/DIR={install_root}'])

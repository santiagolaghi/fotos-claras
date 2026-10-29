import hashlib
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from fotosclaras import updates

class Updates(unittest.TestCase):
    def release(self,data=b'MZ-installer'):
        return dict(version='v0.9.1',url='https://github.com/santiagolaghi/fotos-claras/releases/download/v0.9.1/'+updates.ASSET,sha256=hashlib.sha256(data).hexdigest(),size=len(data))
    def test_stable_vs_beta_order_and_missing_package(self):
        self.assertGreater(updates.number('v1.0.0'),updates.number('1.0.0-beta.90'))
        self.assertGreater(updates.number('1.0.0-beta.2'),updates.number('1.0.0-beta.1'))
        for bad in ['../../x','1.2','a','1.0.0+evil']:
            with self.assertRaises(ValueError):updates.number(bad)
    def test_release_selects_verified_asset(self):
        r=self.release();release=dict(tag_name=r['version'],assets=[dict(name=updates.ASSET,digest='sha256:'+r['sha256'],browser_download_url=r['url'],size=r['size'])])
        with patch('fotosclaras.updates.urllib.request.urlopen',return_value=io.BytesIO(json.dumps(release).encode())):
            self.assertEqual(updates.check()['sha256'],r['sha256'])
        release['assets'][0]['digest']=''
        with patch('fotosclaras.updates.urllib.request.urlopen',return_value=io.BytesIO(json.dumps(release).encode())):
            with self.assertRaises(ValueError):updates.check()
    def test_verified_download_corruption_and_cancel_cleanup(self):
        data=b'MZ-installer';r=self.release(data)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch('fotosclaras.updates.urllib.request.urlopen',return_value=io.BytesIO(data)):
                self.assertEqual(updates.download(r,root,threading.Event()).read_bytes(),data)
            r['sha256']='0'*64
            with patch('fotosclaras.updates.urllib.request.urlopen',return_value=io.BytesIO(data)):
                with self.assertRaises(ValueError):updates.download(r,root,threading.Event())
            self.assertFalse((root/'Fotos-Claras-Setup.part').exists())
            cancel=threading.Event();cancel.set()
            with patch('fotosclaras.updates.urllib.request.urlopen',return_value=io.BytesIO(data)):
                with self.assertRaises(InterruptedError):updates.download(self.release(data),root,cancel)
            self.assertEqual((root/updates.ASSET).read_bytes(),data)
    def test_model_checksum_and_cache(self):
        from fotosclaras import identity
        data=b'valid model bytes';digest=hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory() as tmp,patch.dict(identity.MODELS,{'test.onnx':('test',digest,len(data))},clear=True):
            with patch('fotosclaras.identity.urllib.request.urlopen',return_value=io.BytesIO(data)):
                identity.ensure_models(tmp)
            with patch('fotosclaras.identity.urllib.request.urlopen',side_effect=AssertionError('redownload')):
                identity.ensure_models(tmp)
            (Path(tmp)/'test.onnx').write_bytes(b'bad')
            with patch('fotosclaras.identity.urllib.request.urlopen',return_value=io.BytesIO(b'wrong bytes')):
                with self.assertRaises(ValueError):identity.ensure_models(tmp)
            self.assertFalse((Path(tmp)/'test.download').exists())
    def test_other_repository_rejected_before_network(self):
        r=self.release();r['url']='https://evil.example/installer.exe'
        with patch('fotosclaras.updates.urllib.request.urlopen',side_effect=AssertionError('network')):
            with self.assertRaises(ValueError):updates.download(r,'.',threading.Event())

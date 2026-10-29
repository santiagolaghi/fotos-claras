"""Download public photo fixtures, verify hashes. Never upload family photos."""
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

SAMPLES={
 'basketball1.png':('opencv/opencv/master/samples/data/basketball1.png','ba06f6701f7260998b430c39b6557f775497e6ce7b1a74f0b7ea6af371bf54a6'),
 'basketball2.png':('opencv/opencv/master/samples/data/basketball2.png','b3047772e0dc6c9d83c26f64894ca1a897f799f855c5574ac24b2ef934c2978e'),
 'obama.jpg':('ageitgey/face_recognition/master/examples/obama.jpg','0930e3aa8cae5920329c0c8cbc6a2ab70f47b0e67b432875beaa95cbf7e741f6'),
 'obama2.jpg':('ageitgey/face_recognition/master/examples/obama2.jpg','a7efcc907375274796f39646510704aa86672d59f6d5469d69af3c85590976a6'),
 'biden.jpg':('ageitgey/face_recognition/master/examples/biden.jpg','3c17508bb91554c637a2eabddfae790e5bb1caba93130814fc2ac50be9760c4c'),
 'two_people.jpg':('ageitgey/face_recognition/master/examples/two_people.jpg','536b29cd513fb618e4d5aa79d51a279948daa804ce359463449cce5f9dc68aa7'),
 'lena.jpg':('opencv/opencv/master/samples/data/lena.jpg','7de7ed51a1594fff247f4cae2301eceacf5313d6011e37b4a4c8733f7bb72c07'),
 'scenery.jpg':('opencv/opencv/master/samples/data/fruits.jpg','9c031d80a1c52da5eca790db896baffec6a7e52bf786cdb7bbfca5c7f880e6a1'),
}
def download(folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    for name,(url,digest) in SAMPLES.items():
        target=folder/name
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()==digest:continue
        data=urlopen('https://raw.githubusercontent.com/'+url,timeout=30).read()
        if hashlib.sha256(data).hexdigest()!=digest:raise ValueError('Fixture modificado: '+name)
        target.write_bytes(data)
    return folder
if __name__=='__main__':print(download(Path(__file__).resolve().parents[1]/'validation/real'))

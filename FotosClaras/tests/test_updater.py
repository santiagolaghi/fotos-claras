import hashlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import updater


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = self.temp.name
        self.install = Path(self.temp.name) / "installed"
        self.install.mkdir()
        (self.install / "app.py").write_text("old app", encoding="utf-8")
        (self.install / ".venv").mkdir()
        (self.install / ".venv" / "keep.txt").write_text("keep", encoding="utf-8")
        self.photos = Path(self.temp.name) / "photos"
        self.photos.mkdir()
        (self.photos / "a.jpg").write_bytes(b"original photo")

    def tearDown(self):
        if self.previous is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = self.previous
        self.temp.cleanup()

    @staticmethod
    def archive(extra=None):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as zip_file:
            zip_file.writestr("FotosClaras/app.py", "new app")
            zip_file.writestr("FotosClaras/updater.py", "new updater")
            if extra:
                zip_file.writestr(*extra)
        return data.getvalue()

    def test_detects_new_release_and_ignores_current(self):
        release = {"tag_name": "v0.8", "assets": [{"name": updater.ASSET_NAME,
                   "digest": "sha256:" + "a" * 64,
                   "browser_download_url": "https://github.com/santiagolaghi/fotos-claras/releases/download/v0.8/Fotos-Claras-Windows.zip"}]}
        with patch.object(updater, "_open", return_value=io.BytesIO(json.dumps(release).encode())):
            self.assertEqual(updater.check_for_update()["version"], "v0.8")
        release["tag_name"] = "v0.7"
        with patch.object(updater, "_open", return_value=io.BytesIO(json.dumps(release).encode())):
            self.assertIsNone(updater.check_for_update())

    def test_verified_update_preserves_venv_and_photos(self):
        contents = self.archive()
        release = {"version": "v0.8", "url": "https://github.com/santiagolaghi/fotos-claras/releases/download/v0.8/Fotos-Claras-Windows.zip",
                   "sha256": hashlib.sha256(contents).hexdigest()}
        with patch.object(updater, "_open", return_value=io.BytesIO(contents)):
            updater.stage_update(release, self.install)
        self.assertTrue(updater.apply_pending(relaunch=False))
        self.assertEqual((self.install / "app.py").read_text(), "new app")
        self.assertEqual((self.install / ".venv" / "keep.txt").read_text(), "keep")
        self.assertEqual((self.photos / "a.jpg").read_bytes(), b"original photo")
        self.assertFalse(updater.apply_pending(relaunch=False))

    def test_rejects_traversal_and_wrong_checksum(self):
        contents = self.archive(("FotosClaras/../outside.py", "malicious"))
        release = {"version": "v0.8", "url": "https://github.com/santiagolaghi/fotos-claras/releases/download/v0.8/Fotos-Claras-Windows.zip",
                   "sha256": hashlib.sha256(contents).hexdigest()}
        with patch.object(updater, "_open", return_value=io.BytesIO(contents)):
            with self.assertRaises(ValueError):
                updater.stage_update(release, self.install)
        self.assertEqual((self.install / "app.py").read_text(), "old app")
        release["sha256"] = "0" * 64
        with patch.object(updater, "_open", return_value=io.BytesIO(self.archive())):
            with self.assertRaises(ValueError):
                updater.stage_update(release, self.install)
        self.assertEqual((self.install / "app.py").read_text(), "old app")


if __name__ == "__main__":
    unittest.main()

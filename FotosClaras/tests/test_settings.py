import json
import os
import tempfile
import unittest
from pathlib import Path

from settings import load_settings, save_settings


class SettingsTests(unittest.TestCase):
    def test_remembers_folder_faces_and_place_in_app(self):
        with tempfile.TemporaryDirectory() as temp:
            previous = os.environ.get("LOCALAPPDATA")
            os.environ["LOCALAPPDATA"] = temp
            try:
                preferences = load_settings()
                self.assertFalse(preferences["faces_analyzed"])
                preferences.update(last_folder=r"C:\Fotos\Familia", faces_analyzed=True,
                                   last_tab=3, last_person_id="santiago", count_filter="2 rostros")
                save_settings(preferences)
                self.assertEqual(load_settings(), preferences)
                path = Path(temp) / "FotosClaras" / "preferencias.json"
                path.write_text(json.dumps({**preferences, "last_tab": 800, "count_filter": "incorrecto"}))
                recovered = load_settings()
                self.assertEqual(recovered["last_tab"], 2)
                self.assertEqual(recovered["count_filter"], "Todos")
            finally:
                if previous is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = previous


if __name__ == "__main__":
    unittest.main()

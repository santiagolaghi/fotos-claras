import tempfile
import unittest
import os
from pathlib import Path

from PIL import Image, ImageDraw

from core import fingerprint, group_duplicates, quarantine, move_to_album, scan, undo_last, visual_difference


class PhotoFlowTests(unittest.TestCase):
    def test_exact_recompressed_and_distinct(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            image = Image.new("RGB", (400, 300), "#225588")
            draw = ImageDraw.Draw(image)
            draw.ellipse((80, 40, 320, 260), fill="yellow")
            draw.rectangle((120, 110, 180, 180), fill="red")
            image.save(folder / "original.jpg", quality=97)
            (folder / "original (2).jpg").write_bytes((folder / "original.jpg").read_bytes())
            image.resize((280, 210)).save(folder / "whatsapp.jpg", quality=70)
            other = Image.new("RGB", (400, 300), "#225588")
            ImageDraw.Draw(other).rectangle((80, 40, 320, 260), fill="white")
            other.save(folder / "otra.jpg")
            previous = os.environ.get("LOCALAPPDATA")
            os.environ["LOCALAPPDATA"] = str(folder / "cache")
            try:
                photos, groups, versions, errors, extensions = scan(folder)
            finally:
                if previous is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = previous
            self.assertEqual(len(photos), 4)
            self.assertFalse(errors)
            self.assertEqual(extensions[".jpg"], 4)
            self.assertEqual([len(group) for group in groups], [2])
            self.assertEqual([len(group) for group in versions], [2])
            self.assertNotEqual(fingerprint(folder / "original.jpg").raster_digest, fingerprint(folder / "whatsapp.jpg").raster_digest)
            self.assertLess(visual_difference(fingerprint(folder / "original.jpg"), fingerprint(folder / "whatsapp.jpg")), .075)
            self.assertNotEqual(fingerprint(folder / "original.jpg").digest, fingerprint(folder / "whatsapp.jpg").digest)

    def test_move_undo_and_exclude_quarantine(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            previous = os.environ.get("LOCALAPPDATA")
            os.environ["LOCALAPPDATA"] = str(root / "cache")
            image = Image.new("RGB", (100, 100), "red")
            image.save(root / "x.jpg")
            image.save(root / "y.jpg")
            moved = quarantine([root / "y.jpg"], root)
            self.assertEqual(len(moved), 1)
            self.assertFalse((root / "y.jpg").exists())
            self.assertEqual(len(list(__import__("core").iter_photos(root))), 1)
            self.assertEqual(undo_last(root), 1)
            self.assertTrue((root / "y.jpg").exists())
            if previous is None:
                os.environ.pop("LOCALAPPDATA", None)
            else:
                os.environ["LOCALAPPDATA"] = previous

    def test_no_transitive_lookalike_chain(self):
        # Each item must match the fixed group representative; one near match
        # cannot indirectly pull a different photo into the same group.
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            a = Image.new("RGB", (64, 64), "black")
            b = Image.new("RGB", (64, 64), (18, 18, 18))
            c = Image.new("RGB", (64, 64), (38, 38, 38))
            for img, name in [(a, "a.png"), (b, "b.png"), (c, "c.png")]:
                img.save(folder / name)
            groups = group_duplicates([fingerprint(folder / n) for n in ("a.png", "b.png", "c.png")])
            self.assertEqual(groups, [])

    def test_album_collisions_and_undo(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "a").mkdir()
            (root / "b").mkdir()
            Image.new("RGB", (10, 10), "red").save(root / "a" / "x.jpg")
            Image.new("RGB", (10, 10), "blue").save(root / "b" / "x.jpg")
            previous = os.environ.get("LOCALAPPDATA")
            os.environ["LOCALAPPDATA"] = str(root / "cache")
            try:
                moved = move_to_album([root / "a" / "x.jpg", root / "b" / "x.jpg"], root, root / "Álbumes" / "Familia")
                self.assertEqual(len(moved), 2)
                self.assertEqual(sorted(p.name for p in (root / "Álbumes" / "Familia").iterdir()), ["x (2).jpg", "x.jpg"])
                self.assertEqual(undo_last(root), 2)
                self.assertTrue((root / "a" / "x.jpg").exists())
                self.assertTrue((root / "b" / "x.jpg").exists())
            finally:
                if previous is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = previous


if __name__ == "__main__":
    unittest.main()

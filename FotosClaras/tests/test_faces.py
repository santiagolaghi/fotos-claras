import os
import tempfile
import unittest
from pathlib import Path

from faces import cluster_faces, load_people, merge_groups, regroup_after_naming, save_name, split_group


class FaceGroupsTests(unittest.TestCase):
    def test_unnamed_group_keeps_identity_between_scans(self):
        face = {"id": "original:0", "path": "/photos/original.jpg", "number": 0,
                "vector": [1., 0.], "thumb": ""}
        empty = {"people": [], "overrides": {}}
        self.assertEqual(cluster_faces([face], empty)[0]["id"], cluster_faces([face], empty)[0]["id"])

    def test_naming_reclaims_old_fragments_and_keeps_two_faces_apart(self):
        with tempfile.TemporaryDirectory() as temp:
            previous = os.environ.get("LOCALAPPDATA")
            os.environ["LOCALAPPDATA"] = str(Path(temp) / "cache")
            try:
                first = {"id": "first", "path": "/photos/1.jpg", "number": 0,
                         "vector": [1., 0.], "thumb": ""}
                another = {"id": "other", "path": "/photos/2.jpg", "number": 0,
                           "vector": [.45, .893], "thumb": ""}
                # Similar-looking second face in the very same photograph.
                second = {"id": "second", "path": "/photos/1.jpg", "number": 1,
                          "vector": [.9, .435], "thumb": ""}
                old = [dict(id="s", name="", templates=[[1., 0.]], faces=[first],
                            photos=[first["path"]], thumb=""),
                       dict(id="d", name="", templates=[another["vector"]], faces=[another],
                            photos=[another["path"]], thumb=""),
                       dict(id="x", name="", templates=[second["vector"]], faces=[second],
                            photos=[second["path"]], thumb="")]
                save_name(old[0], "Santiago")
                groups = regroup_after_naming(old)
                santi = next(g for g in groups if g["name"] == "Santiago")
                self.assertIn(another["path"], santi["photos"])
                self.assertNotIn(second["id"], [f["id"] for f in santi["faces"]])
            finally:
                if previous is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = previous

    def test_one_name_per_group_persists_split_and_merge(self):
        with tempfile.TemporaryDirectory() as temp:
            previous = os.environ.get("LOCALAPPDATA")
            os.environ["LOCALAPPDATA"] = str(Path(temp) / "cache")
            try:
                faces = [{"id": f"image-{i}:0", "path": f"/photos/{i}.jpg", "number": 0,
                          "vector": v, "thumb": ""} for i, v in enumerate(([1, 0], [.99, .1], [0, 1]))]
                groups = cluster_faces(faces, {"people": [], "overrides": {}})
                self.assertEqual(sorted(len(g["photos"]) for g in groups), [1, 2])
                santi = next(g for g in groups if len(g["photos"]) == 2)
                save_name(santi, "Santiago")
                self.assertEqual(len(load_people()["people"]), 1)
                regrouped = cluster_faces(faces)
                named = next(g for g in regrouped if g["name"] == "Santiago")
                self.assertEqual(len(named["photos"]), 2)
                separated = split_group(named, ["/photos/1.jpg"])
                self.assertEqual(len(named["photos"]), 1)
                self.assertEqual(len(cluster_faces(faces)), 3)
                merge_groups(separated, named)
                self.assertEqual(len(next(g for g in cluster_faces(faces) if g["name"] == "Santiago")["photos"]), 2)
            finally:
                if previous is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = previous


if __name__ == "__main__":
    unittest.main()

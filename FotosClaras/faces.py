"""Local face detection and editable, persistent person groups."""
from __future__ import annotations

import hashlib
import json
import urllib.request
import uuid
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from core import Catalog, app_data

MODELS = {
    "face_detection_yunet_2023mar.onnx": "face_detection_yunet",
    "face_recognition_sface_2021dec.onnx": "face_recognition_sface",
}

# OpenCV's SFace pair threshold is .363. Keep a little margin for automatic
# grouping and use several varied examples so a change of angle doesn't
# create another identity solely because it differs from the first portrait.
GROUP_THRESHOLD = .38
NAMED_THRESHOLD = .39
MAX_TEMPLATES = 12


def ensure_models():
    folder = app_data() / "models"
    folder.mkdir(exist_ok=True)
    for filename, remote_dir in MODELS.items():
        target = folder / filename
        if target.exists() and target.stat().st_size > 100_000:
            continue
        address = f"https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/{remote_dir}/{filename}"
        temporary = folder / (filename + ".download")
        try:
            with urllib.request.urlopen(address, timeout=90) as response, temporary.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            if temporary.stat().st_size < 100_000 or temporary.open("rb").read(30).startswith(b"version https://git-lfs"):
                raise RuntimeError("El modelo descargado está incompleto")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    return folder


def face_thumbnail_path(path, index):
    key = hashlib.sha256(f"{path}|{Path(path).stat().st_mtime_ns}|{index}".encode()).hexdigest()
    folder = app_data() / "faces"
    folder.mkdir(exist_ok=True)
    return folder / f"{key}.jpg"


def load_people():
    path = app_data() / "personas_v2.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Prior releases saved names and representative vectors here.
        old = app_data() / "personas.json"
        try:
            entries = json.loads(old.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            entries = []
        return {"people": [{"id": uuid.uuid4().hex, "name": entry["name"], "templates": [entry["vector"]]}
                           for entry in entries], "overrides": {}}


def _save_people(data):
    path = app_data() / "personas_v2.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def face_id(photo, index):
    return f"{photo.digest}:{index}"


def cluster_faces(detected, saved=None):
    """detected: entries with id/path/index/vector/thumb. Keep edits by face ID."""
    saved = saved or load_people()
    groups = []
    by_id = {}
    index_by_id = {}
    vectors, owners = [], []
    paths_by_group = []
    for item in saved["people"]:
        group = {"id": item["id"], "name": item["name"], "templates": item["templates"][:MAX_TEMPLATES],
                 "faces": [], "photos": [], "thumb": ""}
        groups.append(group)
        by_id[item["id"]] = group
        index_by_id[item["id"]] = len(groups) - 1
        paths_by_group.append(set())
        for template in group["templates"]:
            vectors.append(np.asarray(template, dtype=np.float32))
            owners.append(len(groups) - 1)
    matrix = np.stack(vectors) if vectors else None
    owner_array = np.asarray(owners, dtype=np.int32)
    for face in detected:
        vector = np.asarray(face["vector"], dtype=np.float32)
        chosen = by_id.get(saved["overrides"].get(face["id"]))
        if chosen is None:
            if matrix is not None:
                scores = np.full(len(groups), -1.0, dtype=np.float32)
                np.maximum.at(scores, owner_array, matrix @ vector)
                # Two different faces in one photo cannot be the same person.
                for index, paths in enumerate(paths_by_group):
                    if face["path"] in paths:
                        scores[index] = -1.0
                best = int(np.argmax(scores))
                threshold = NAMED_THRESHOLD if groups[best]["name"] else GROUP_THRESHOLD
                if scores[best] >= threshold:
                    named_competitors = [scores[i] for i, group in enumerate(groups)
                                         if i != best and group["name"]]
                    runner_up = max(named_competitors, default=-1)
                    if not groups[best]["name"] or scores[best] - runner_up >= .04:
                        chosen = groups[best]
            if chosen is None:
                chosen = {"id": hashlib.sha256(face["id"].encode()).hexdigest()[:32],
                          "name": "", "templates": [face["vector"]],
                          "faces": [], "photos": [], "thumb": ""}
                groups.append(chosen)
                index_by_id[chosen["id"]] = len(groups) - 1
                paths_by_group.append(set())
                vectors.append(vector)
                owners.append(len(groups) - 1)
                matrix = np.vstack((matrix, vector)) if matrix is not None else vector[None, :]
                owner_array = np.asarray(owners, dtype=np.int32)
        index = index_by_id[chosen["id"]]
        chosen["faces"].append(face)
        if face["path"] not in chosen["photos"]:
            chosen["photos"].append(face["path"])
        paths_by_group[index].add(face["path"])
        if not chosen["thumb"]:
            chosen["thumb"] = face["thumb"]
        if len(chosen["templates"]) < MAX_TEMPLATES and all(
                float(np.dot(vector, np.asarray(t, dtype=np.float32))) < .72
                for t in chosen["templates"]):
            chosen["templates"].append(face["vector"])
            vectors.append(vector)
            owners.append(index)
            matrix = np.vstack((matrix, vector))
            owner_array = np.asarray(owners, dtype=np.int32)
    return sorted((g for g in groups if g["faces"]), key=lambda g: len(g["photos"]), reverse=True)


def regroup_after_naming(groups):
    """Apply a newly supplied name to the other unlabelled face groups."""
    faces = [face for group in groups for face in group["faces"]]
    return cluster_faces(faces)


def _record(group, data):
    item = next((p for p in data["people"] if p["id"] == group["id"]), None)
    if item is None:
        item = {"id": group["id"], "name": group["name"], "templates": group["templates"]}
        data["people"].append(item)
    else:
        item["name"], item["templates"] = group["name"], group["templates"]
    for face in group["faces"]:
        data["overrides"][face["id"]] = group["id"]


def save_name(group, name):
    name = name.strip()
    if not name:
        raise ValueError("Escribí un nombre")
    data = load_people()
    group["name"] = name
    _record(group, data)
    _save_people(data)


def split_group(group, paths):
    """Separate chosen photos' faces into a new unnamed group, persistently."""
    paths = set(paths)
    selected = [f for f in group["faces"] if f["path"] in paths]
    if not selected or len(selected) == len(group["faces"]):
        raise ValueError("Elegí algunas fotos del grupo, pero no todas")
    new = {"id": uuid.uuid4().hex, "name": "", "templates": [selected[0]["vector"]],
           "faces": selected, "photos": list(dict.fromkeys(f["path"] for f in selected)),
           "thumb": selected[0]["thumb"]}
    group["faces"] = [f for f in group["faces"] if f not in selected]
    group["photos"] = list(dict.fromkeys(f["path"] for f in group["faces"]))
    data = load_people()
    _record(group, data)
    _record(new, data)
    _save_people(data)
    return new


def merge_groups(source, target):
    if source["id"] == target["id"]:
        raise ValueError("Elegí otra persona")
    data = load_people()
    target["faces"].extend(source["faces"])
    target["photos"] = list(dict.fromkeys(target["photos"] + source["photos"]))
    target["templates"].extend(source["templates"])
    _record(target, data)
    data["people"] = [p for p in data["people"] if p["id"] != source["id"]]
    _save_people(data)


def scan_faces(photos, progress=lambda done, total: None):
    try:
        import cv2
    except ImportError as error:
        raise RuntimeError("Falta instalar el componente de rostros. Ejecutá INSTALAR.bat.") from error
    models = ensure_models()
    detector = cv2.FaceDetectorYN.create(str(models / "face_detection_yunet_2023mar.onnx"), "", (320, 320), .85, .3, 5000)
    recognizer = cv2.FaceRecognizerSF.create(str(models / "face_recognition_sface_2021dec.onnx"), "")
    catalog = Catalog()
    no_faces, detected, failures, counts = [], [], [], {}
    try:
        for i, photo in enumerate(photos, 1):
            try:
                cached = catalog.face_cache(photo.path)
                if cached is None:
                    with Image.open(photo.path) as original:
                        image = np.array(ImageOps.exif_transpose(original).convert("RGB"))
                    h, w = image.shape[:2]
                    if max(w, h) > 1920:
                        scale = 1920 / max(w, h)
                        image = cv2.resize(image, (round(w * scale), round(h * scale)))
                    bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
                    detector.setInputSize((bgr.shape[1], bgr.shape[0]))
                    _, boxes = detector.detect(bgr)
                    vectors = []
                    for box in [] if boxes is None else boxes:
                        aligned = recognizer.alignCrop(bgr, box)
                        vector = recognizer.feature(aligned).flatten().astype(float)
                        norm = np.linalg.norm(vector)
                        if norm:
                            x, y, width, height = (int(value) for value in box[:4])
                            crop = image[max(0, y):min(image.shape[0], y + height),
                                         max(0, x):min(image.shape[1], x + width)]
                            if crop.size:
                                thumbnail = Image.fromarray(crop)
                                thumbnail.thumbnail((96, 96))
                                thumbnail.save(face_thumbnail_path(photo.path, len(vectors)), quality=85)
                            vectors.append((vector / norm).tolist())
                    catalog.put_faces(photo.path, vectors)
                else:
                    vectors, _ = cached
                counts[photo.path] = len(vectors)
                if not vectors:
                    no_faces.append(photo.path)
                for number, vector in enumerate(vectors):
                    detected.append({"id": face_id(photo, number), "path": photo.path, "number": number,
                                     "vector": vector, "thumb": str(face_thumbnail_path(photo.path, number))})
            except Exception as error:
                failures.append((photo.path, str(error)))
            if i % 10 == 0 or i == len(photos):
                progress(i, len(photos))
    finally:
        catalog.close()
    return cluster_faces(detected), no_faces, counts, failures

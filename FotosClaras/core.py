"""Local photo indexing, conservative visual matching, and reversible moves."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
import numpy as np

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif"}
RESAMPLE = Image.Resampling.LANCZOS


@dataclass(frozen=True)
class Photo:
    path: str
    size: int
    width: int
    height: int
    digest: str
    raster_digest: str
    visual: int
    pixels: bytes

    @property
    def quality(self):
        # Pixels matter more than file size; an uncompressed PNG is not inherently sharper.
        return self.width * self.height, self.size


def app_data():
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    folder = Path(base) / "FotosClaras"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def iter_photos(folder):
    folder = Path(folder).resolve()
    if not folder.is_dir():
        raise ValueError("La carpeta no existe")
    for base, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "FotosClaras_ParaRevisar"]
        for filename in files:
            path = Path(base) / filename
            if path.suffix.lower() in EXTENSIONS:
                yield path


def fingerprint(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    with Image.open(path) as original:
        image = ImageOps.exif_transpose(original).convert("RGB")
        width, height = image.size
        small = image.resize((9, 8), RESAMPLE).convert("L")
        px = list(small.tobytes())
        visual = sum((1 << (row * 8 + col)) for row in range(8) for col in range(8)
                     if px[row * 9 + col] > px[row * 9 + col + 1])
        raster_digest = hashlib.sha256(f"{width}x{height}:".encode() + image.tobytes()).hexdigest()
        compare = image.resize((32, 32), RESAMPLE)
        pixels = compare.tobytes()
    return Photo(str(Path(path).resolve()), Path(path).stat().st_size, width, height,
                 digest.hexdigest(), raster_digest, visual, pixels)


class Catalog:
    def __init__(self, path=None):
        self.db = sqlite3.connect(path or app_data() / "catalog.sqlite3")
        self.db.execute("CREATE TABLE IF NOT EXISTS photos (path TEXT PRIMARY KEY, size INTEGER, mtime_ns INTEGER, width INTEGER, height INTEGER, digest TEXT, visual TEXT, pixels BLOB, raster_digest TEXT)")
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(photos)")}
        if "raster_digest" not in columns:
            self.db.execute("ALTER TABLE photos ADD COLUMN raster_digest TEXT")
        self.db.execute("CREATE TABLE IF NOT EXISTS faces (path TEXT PRIMARY KEY, size INTEGER, mtime_ns INTEGER, embeddings TEXT, count INTEGER)")
        self.db.commit()

    def get(self, path):
        stat = path.stat()
        row = self.db.execute("SELECT size, mtime_ns, width, height, digest, raster_digest, visual, pixels FROM photos WHERE path=?", (str(path.resolve()),)).fetchone()
        if row and row[5] and (row[0], row[1]) == (stat.st_size, stat.st_mtime_ns):
            return Photo(str(path.resolve()), row[0], row[2], row[3], row[4], row[5], int(row[6]), row[7])
        item = fingerprint(path)
        self.db.execute("INSERT OR REPLACE INTO photos (path,size,mtime_ns,width,height,digest,visual,pixels,raster_digest) VALUES (?,?,?,?,?,?,?,?,?)",
                        (item.path, stat.st_size, stat.st_mtime_ns, item.width, item.height,
                         item.digest, str(item.visual), item.pixels, item.raster_digest))
        self.db.commit()
        return item

    def face_cache(self, path):
        stat = Path(path).stat()
        row = self.db.execute("SELECT size, mtime_ns, embeddings, count FROM faces WHERE path=?", (str(path),)).fetchone()
        return (json.loads(row[2]), row[3]) if row and (row[0], row[1]) == (stat.st_size, stat.st_mtime_ns) else None

    def put_faces(self, path, embeddings):
        stat = Path(path).stat()
        self.db.execute("INSERT OR REPLACE INTO faces VALUES (?,?,?,?,?)",
                        (str(path), stat.st_size, stat.st_mtime_ns, json.dumps(embeddings), len(embeddings)))
        self.db.commit()

    def close(self):
        self.db.close()


class BKTree:
    def __init__(self):
        self.root = None

    def add(self, key, index):
        if self.root is None:
            self.root = (key, [index], {})
            return
        node = self.root
        while True:
            distance = (key ^ node[0]).bit_count()
            if distance == 0:
                node[1].append(index)
                return
            child = node[2].get(distance)
            if child is None:
                node[2][distance] = (key, [index], {})
                return
            node = child

    def near(self, key, radius):
        if self.root is None:
            return []
        found, stack = [], [self.root]
        while stack:
            node = stack.pop()
            distance = (key ^ node[0]).bit_count()
            if distance <= radius:
                found.extend(node[1])
            stack.extend(child for edge, child in node[2].items() if distance - radius <= edge <= distance + radius)
        return found


def visual_difference(a, b):
    # Mean RGB error on aligned thumbnails; also reject photos with different aspect ratios.
    ratio_a, ratio_b = a.width / a.height, b.width / b.height
    if abs(ratio_a - ratio_b) / max(ratio_a, ratio_b) > .035:
        return 1.0
    return sum(abs(x - y) for x, y in zip(a.pixels, b.pixels)) / (len(a.pixels) * 255)


def group_duplicates(photos):
    """Only byte-identical files or pixel-identical lossless re-encodings."""
    groups = {}
    for photo in photos:
        groups.setdefault(photo.raster_digest, []).append(photo)
    result = [sorted(group, key=lambda p: p.quality, reverse=True)
              for group in groups.values() if len(group) > 1]
    return sorted(result, key=lambda group: len(group), reverse=True)


@lru_cache(maxsize=96)
def comparison_pixels(path):
    with Image.open(path) as original:
        image = ImageOps.exif_transpose(original).convert("RGB")
        return np.asarray(image.resize((192, 192), RESAMPLE), dtype=np.int16)


def likely_same_photo(left, right):
    """Conservative candidates for a *review* queue; never an exact duplicate."""
    if left.raster_digest == right.raster_digest:
        return False
    ratio_a, ratio_b = left.width / left.height, right.width / right.height
    if abs(ratio_a - ratio_b) / max(ratio_a, ratio_b) > .008:
        return False
    if (left.visual ^ right.visual).bit_count() > 4 or visual_difference(left, right) > .035:
        return False
    try:
        delta = np.abs(comparison_pixels(left.path) - comparison_pixels(right.path))
    except OSError:
        return False
    gray = np.mean(delta, axis=2)
    # A small altered area in a burst matters, even if overall averages are low.
    tiles = gray.reshape(8, 24, 8, 24).mean(axis=(1, 3))
    return float(gray.mean()) <= 5.0 and float(np.percentile(gray, 99)) <= 24.0 and float(tiles.max()) <= 12.0


def find_versions(photos):
    """Possible WhatsApp re-encodings, kept separate from proven duplicates."""
    representatives = {}
    for photo in photos:
        representatives.setdefault(photo.raster_digest, photo)
    items = sorted(representatives.values(), key=lambda p: p.path)
    tree, groups = BKTree(), []
    for photo in items:
        match = None
        for index in sorted(set(tree.near(photo.visual, 4)))[:100]:
            if likely_same_photo(groups[index][0], photo):
                match = index
                break
        if match is None:
            match = len(groups)
            groups.append([photo])
            tree.add(photo.visual, match)
        else:
            groups[match].append(photo)
    return sorted((sorted(group, key=lambda p: p.quality, reverse=True)
                   for group in groups if len(group) > 1), key=len, reverse=True)


def scan(folder, progress=lambda done, total: None):
    paths = list(iter_photos(folder))
    extensions = dict(Counter(path.suffix.lower() for path in paths))
    catalog = Catalog()
    photos, errors = [], []
    try:
        for index, path in enumerate(paths, 1):
            try:
                photos.append(catalog.get(path))
            except (OSError, ValueError, UnidentifiedImageError) as error:
                errors.append((str(path), str(error)))
            if index % 20 == 0 or index == len(paths):
                progress(index, len(paths))
    finally:
        catalog.close()
    return photos, group_duplicates(photos), find_versions(photos), errors, extensions


def quarantine(paths, source_root):
    """Move chosen files to the review folder, keeping relative paths."""
    source_root = Path(source_root).resolve()
    destination = source_root / "FotosClaras_ParaRevisar"
    return _move(paths, source_root, destination, preserve_tree=True)


def move_to_album(paths, source_root, destination):
    """Move selected photos to an existing/new folder, with undo and no overwrites."""
    source_root, destination = Path(source_root).resolve(), Path(destination).resolve()
    if destination == source_root or destination == source_root / "FotosClaras_ParaRevisar":
        raise ValueError("Elegí un álbum diferente de la carpeta principal")
    return _move(paths, source_root, destination)


def _journal(source_root):
    key = hashlib.sha256(str(source_root).encode()).hexdigest()[:20]
    return app_data() / f"movimientos_{key}.jsonl"


def _move(paths, source_root, destination, preserve_tree=False):
    source_root, destination = Path(source_root).resolve(), Path(destination).resolve()
    chosen = list(dict.fromkeys(Path(raw).resolve() for raw in paths))
    if not chosen:
        return []
    for source in chosen:
        if not source.is_file() or not source.is_relative_to(source_root) or source.is_relative_to(destination):
            raise ValueError(f"Foto no disponible para mover: {source}")
    targets, reserved = [], set()
    for source in chosen:
        proposed = destination / (source.relative_to(source_root) if preserve_tree else source.name)
        target, number = proposed, 2
        while target.exists() or target in reserved or target in chosen:
            target = proposed.with_name(f"{proposed.stem} ({number}){proposed.suffix}")
            number += 1
        targets.append(target)
        reserved.add(target)
    moves = []
    try:
        for source, target in zip(chosen, targets):
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            moves.append({"from": str(source), "to": str(target)})
        with _journal(source_root).open("a", encoding="utf-8") as output:
            output.write(json.dumps({"time": time.time(), "moves": moves}, ensure_ascii=False) + "\n")
    except Exception:
        for move in reversed(moves):
            if Path(move["to"]).exists() and not Path(move["from"]).exists():
                shutil.move(move["to"], move["from"])
        raise
    return moves


def undo_last(source_root):
    journal = _journal(Path(source_root).resolve())
    if not journal.exists():
        # Restore movements recorded by versions older than 0.4 as well.
        journal = Path(source_root).resolve() / "FotosClaras_ParaRevisar" / "movimientos.jsonl"
    if not journal.exists():
        return 0
    entries = journal.read_text(encoding="utf-8").splitlines()
    if not entries:
        return 0
    moves = json.loads(entries[-1])["moves"]
    for move in reversed(moves):
        source, target = Path(move["to"]), Path(move["from"])
        if not source.exists() or target.exists():
            raise RuntimeError(f"No se puede restaurar sin sobrescribir: {target}")
    for move in reversed(moves):
        target = Path(move["from"])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(move["to"], move["from"])
    journal.write_text("\n".join(entries[:-1]) + ("\n" if len(entries) > 1 else ""), encoding="utf-8")
    return len(moves)

"""Signed-in-free GitHub Release updater for the source-based Windows install.

Only release ZIPs from the configured repository are accepted. The release
asset SHA-256 is checked before applying files. Photo folders and local state
are never part of an update.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

VERSION = "0.7"
REPOSITORY = "santiagolaghi/fotos-claras"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
ASSET_NAME = "Fotos-Claras-Windows.zip"
MAX_DOWNLOAD = 100 * 1024 * 1024
MAX_EXTRACTED = 200 * 1024 * 1024
ALLOWED_SUFFIXES = {".py", ".bat", ".txt", ".md", ".png", ".ico", ".json"}


def _app_data():
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    path = Path(base) / "FotosClaras"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _version_number(value):
    match = re.fullmatch(r"v?(\d+)\.(\d+)(?:\.(\d+))?", value)
    if not match:
        raise ValueError("La versión publicada no tiene un número válido")
    return tuple(int(number or 0) for number in match.groups())


def _open(address, timeout=12):
    request = urllib.request.Request(address, headers={"User-Agent": "FotosClaras-Updater/1", "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(request, timeout=timeout)


def check_for_update():
    """Return a verified release descriptor, or None if current is latest."""
    with _open(API_URL) as response:
        release = json.load(response)
    tag = release["tag_name"]
    if _version_number(tag) <= _version_number(VERSION):
        return None
    asset = next((a for a in release.get("assets", []) if a.get("name") == ASSET_NAME), None)
    if asset is None:
        raise ValueError("La versión nueva todavía no tiene paquete para Windows")
    digest = asset.get("digest") or ""
    url = asset.get("browser_download_url") or ""
    if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
        raise ValueError("La versión nueva no tiene una huella de integridad")
    if not url.startswith(f"https://github.com/{REPOSITORY}/releases/download/"):
        raise ValueError("El archivo no proviene del repositorio de Fotos Claras")
    return {"version": tag, "url": url, "sha256": digest[7:].lower()}


def _members(archive):
    members, total = [], 0
    for item in archive.infolist():
        if item.is_dir():
            continue
        path = PurePosixPath(item.filename)
        parts = path.parts
        if (len(parts) < 2 or parts[0] != "FotosClaras" or
                any(p in ("", ".", "..") or p.startswith(".") or ":" in p or "\\" in p for p in parts[1:]) or
                path.suffix.lower() not in ALLOWED_SUFFIXES or
                "__pycache__" in parts or ".venv" in parts or
                (item.external_attr >> 16) & 0o170000 == 0o120000):
            raise ValueError(f"El paquete contiene una ruta no permitida: {item.filename}")
        total += item.file_size
        if total > MAX_EXTRACTED:
            raise ValueError("El paquete excede el tamaño admitido")
        members.append((item, Path(*parts[1:])))
    if not any(relative == Path("app.py") for _, relative in members) or not any(
            relative == Path("updater.py") for _, relative in members):
        raise ValueError("Faltan archivos esenciales de la aplicación")
    if len({str(p).casefold() for _, p in members}) != len(members):
        raise ValueError("El paquete tiene nombres duplicados")
    return members


def stage_update(release, install_dir):
    """Download/verify the release and record a pending update atomically."""
    folder = _app_data() / "updates"
    folder.mkdir(exist_ok=True)
    archive_path = folder / "paquete.zip"
    partial = folder / "paquete.part"
    digest = hashlib.sha256()
    size = 0
    try:
        with _open(release["url"], timeout=45) as response, partial.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_DOWNLOAD:
                    raise ValueError("El paquete es demasiado grande")
                digest.update(chunk)
                output.write(chunk)
        if digest.hexdigest() != release["sha256"]:
            raise ValueError("La descarga no pasó la verificación de integridad")
        with zipfile.ZipFile(partial) as archive:
            _members(archive)
            if archive.testzip() is not None:
                raise ValueError("El paquete descargado está dañado")
        partial.replace(archive_path)
        pending = {"archive": str(archive_path), "sha256": release["sha256"],
                   "install_dir": str(Path(install_dir).resolve()), "version": release["version"],
                   "python": sys.executable}
        temporary = folder / "pendiente.tmp"
        temporary.write_text(json.dumps(pending), encoding="utf-8")
        temporary.replace(folder / "pendiente.json")
    finally:
        partial.unlink(missing_ok=True)


def _wait_for_pid(pid):
    if not pid:
        return
    if os.name == "nt":
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x00100000, False, int(pid))
        if handle:
            kernel.WaitForSingleObject(handle, 30000)
            kernel.CloseHandle(handle)
    else:
        for _ in range(300):
            try:
                os.kill(int(pid), 0)
            except ProcessLookupError:
                return
            time.sleep(.1)


def apply_pending(relaunch=True, wait_pid=None):
    """Apply staged source files with rollback; leave photos and .venv alone."""
    _wait_for_pid(wait_pid)
    folder = _app_data() / "updates"
    pending_path = folder / "pendiente.json"
    if not pending_path.exists():
        return False
    info = json.loads(pending_path.read_text(encoding="utf-8"))
    archive_path = Path(info["archive"])
    if archive_path.parent.resolve() != folder.resolve() or archive_path.name != "paquete.zip":
        raise ValueError("La actualización pendiente tiene una ruta inválida")
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    if digest != info["sha256"]:
        raise ValueError("La actualización pendiente no pasó la verificación")
    destination = Path(info["install_dir"]).resolve()
    if not (destination / "app.py").is_file():
        raise ValueError("No encontré la instalación anterior")
    staging = folder / "extraido"
    backup = folder / "respaldo"
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(backup, ignore_errors=True)
    staging.mkdir()
    backup.mkdir()
    touched = []
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = _members(archive)
            for item, relative in members:
                target = staging / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
        for _, relative in members:
            target = destination / relative
            if target.exists():
                saved = backup / relative
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging / relative, target)
            touched.append(relative)
    except Exception:
        for relative in reversed(touched):
            target, saved = destination / relative, backup / relative
            if saved.exists():
                shutil.copy2(saved, target)
            else:
                target.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    pending_path.unlink()
    archive_path.unlink(missing_ok=True)
    if relaunch:
        subprocess.Popen([info["python"], str(destination / "app.py")], cwd=destination,
                         creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    return True


def launch_installer(install_dir):
    """Run a copy outside the installation once the UI exits."""
    runner = _app_data() / "updates" / "instalador.py"
    shutil.copy2(Path(__file__).resolve(), runner)
    subprocess.Popen([sys.executable, str(runner), "--apply-pending", "--wait-pid", str(os.getpid())],
                     cwd=str(Path(install_dir).resolve()),
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))


if __name__ == "__main__":
    if "--apply-pending" in sys.argv:
        wait_pid = sys.argv[sys.argv.index("--wait-pid") + 1] if "--wait-pid" in sys.argv else None
        try:
            apply_pending(relaunch="--no-restart" not in sys.argv, wait_pid=wait_pid)
        except Exception as error:
            log = _app_data() / "actualizacion_error.txt"
            log.write_text(f"{type(error).__name__}: {error}\n", encoding="utf-8")
            raise

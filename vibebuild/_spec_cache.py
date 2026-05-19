"""
Persistent кеш разбора SRPM. Ключ — sha256 от файла + размер + версия vibebuild.

При повторном вызове `get_package_info_from_srpm(path)` на том же SRPM
парсинг (rpm2cpio + cpio + spec analysis) пропускается.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from vibebuild.analyzer import PackageInfo

from vibebuild import __version__ as _VIBEBUILD_VERSION

logger = logging.getLogger(__name__)

_CACHE_DIR = Path.home() / ".cache" / "vibebuild" / "spec-cache"
# Для определения «свежести» — sha256 первых N байт + полный размер.
# Полный sha256 на 100 MB SRPM — медленно (~500 ms), что съедает весь выигрыш.
_SAMPLE_BYTES = 4 * 1024 * 1024  # 4 MB


def _file_key(srpm_path: Path) -> str:
    """Сгенерировать стабильный ключ для SRPM-файла."""
    try:
        st = srpm_path.stat()
    except OSError:
        return ""
    h = hashlib.sha256()
    h.update(_VIBEBUILD_VERSION.encode())
    h.update(b"|")
    h.update(str(st.st_size).encode())
    h.update(b"|")
    try:
        with open(srpm_path, "rb") as f:
            chunk = f.read(_SAMPLE_BYTES)
            h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()[:32]


def _cache_path(key: str) -> Path:
    return _CACHE_DIR / f"{key}.json"


def get(srpm_path: str) -> Optional["PackageInfo"]:
    """Вернуть кешированный PackageInfo для SRPM, либо None."""
    from vibebuild.analyzer import BuildRequirement, PackageInfo

    key = _file_key(Path(srpm_path))
    if not key:
        return None
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.debug("Spec cache miss/corrupt %s: %s", path, e)
        return None
    build_requires = [
        BuildRequirement(
            name=br["name"],
            version=br.get("version"),
            operator=br.get("operator"),
        )
        for br in data.get("build_requires", [])
    ]
    return PackageInfo(
        name=data["name"],
        version=data["version"],
        release=data["release"],
        build_requires=build_requires,
        source_urls=data.get("source_urls", []),
    )


def put(srpm_path: str, info: "PackageInfo") -> None:
    """Сохранить PackageInfo в кеш."""
    key = _file_key(Path(srpm_path))
    if not key:
        return
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": info.name,
        "version": info.version,
        "release": info.release,
        "build_requires": [dataclasses.asdict(br) for br in info.build_requires],
        "source_urls": info.source_urls,
    }
    path = _cache_path(key)
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as e:
        logger.debug("Spec cache write failed for %s: %s", path, e)

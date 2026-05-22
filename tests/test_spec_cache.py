"""Тесты persistent кеша парсинга SRPM."""

from __future__ import annotations

import pytest

from vibebuild.analyzer import BuildRequirement, PackageInfo


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    """Изолированный кеш-каталог на тест."""
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr("vibebuild._spec_cache._CACHE_DIR", cache_dir)
    return cache_dir


@pytest.fixture
def sample_srpm(tmp_path):
    """Поддельный SRPM-файл (4MB-сэмпл для хеша)."""
    f = tmp_path / "x.src.rpm"
    f.write_bytes(b"FAKE SRPM CONTENT " * 1024)
    return f


@pytest.fixture
def sample_info():
    return PackageInfo(
        name="x",
        version="1.0",
        release="1",
        build_requires=[
            BuildRequirement(name="gcc"),
            BuildRequirement(name="cffi", version="1.12", operator=">="),
        ],
        source_urls=["http://example/x-1.0.tar.gz"],
    )


def test_put_then_get_roundtrip(isolated_cache, sample_srpm, sample_info):
    from vibebuild import _spec_cache

    assert _spec_cache.get(str(sample_srpm)) is None  # miss
    _spec_cache.put(str(sample_srpm), sample_info)
    got = _spec_cache.get(str(sample_srpm))
    assert got is not None
    assert got.name == "x"
    assert got.version == "1.0"
    assert len(got.build_requires) == 2
    assert got.build_requires[1].operator == ">="


def test_cache_miss_for_changed_file(isolated_cache, sample_srpm, sample_info):
    from vibebuild import _spec_cache

    _spec_cache.put(str(sample_srpm), sample_info)
    # меняем содержимое — sha256-сэмпл изменился
    sample_srpm.write_bytes(b"DIFFERENT CONTENT")
    assert _spec_cache.get(str(sample_srpm)) is None


def test_missing_file_returns_none(isolated_cache, tmp_path):
    from vibebuild import _spec_cache

    assert _spec_cache.get(str(tmp_path / "nope.src.rpm")) is None

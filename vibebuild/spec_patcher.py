"""Патчинг spec-файлов внутри SRPM перед отправкой в koji.

Применяется автоматически ко всем SRPM (целевому и зависимостям) до сабмита.
Две трансформации, согласованные с преподавателем:

1. Целиком вырезается секция `%check` — testsuite'ы апстримов часто требуют
   сети, специфичных лимитов pid/процессов и других вещей, которых в нашей
   sandbox-mock нет; вместо них опираемся на отдельный smoke install после
   тегирования. Делается всегда.
2. В начало spec'а опционально добавляется
   `%define _unpackaged_files_terminate_build 0`, чтобы оставшиеся в BUILDROOT
   нераспакованные файлы не валили сборку. Применяется условно — только при
   ретрае после сборки, упавшей с «Installed (but unpackaged) file(s) found»
   (см. логику ретрая в `vibebuild/builder.py`).

Оба механизма — штатные RPM/Fedora: макрос документирован в upstream
`/usr/lib/rpm/macros`, `%check` — обычная необязательная секция spec'а.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Optional

from vibebuild.exceptions import VibeBuildError

logger = logging.getLogger(__name__)

UNPACKAGED_MACRO = "%define _unpackaged_files_terminate_build 0"

# Имена RPM-секций. После `%check` парсинг возобновляется при появлении
# любой из них в начале строки.
_SECTION_NAMES = frozenset(
    {
        "package",
        "description",
        "prep",
        "generate_buildrequires",
        "conf",
        "build",
        "install",
        "check",
        "clean",
        "files",
        "changelog",
        "pre",
        "post",
        "preun",
        "postun",
        "pretrans",
        "posttrans",
        "trigger",
        "triggerin",
        "triggerun",
        "triggerpostun",
        "triggerprein",
        "verifyscript",
        "sepolicy",
        "filetriggerin",
        "filetriggerun",
        "filetriggerpostun",
        "transfiletriggerin",
        "transfiletriggerun",
        "transfiletriggerpostun",
    }
)


def _section_token(line: str) -> Optional[str]:
    """Вернуть имя секции, если строка её начинает, иначе None."""
    stripped = line.lstrip()
    if not stripped.startswith("%"):
        return None
    head = stripped.split(None, 1)[0]
    name = head[1:].split("(", 1)[0]
    return name if name in _SECTION_NAMES else None


def patch_spec_text(spec: str, add_unpackaged_macro: bool = False) -> str:
    """Применить правки к тексту spec'а. Идемпотентно.

    `%check` вырезается всегда. `UNPACKAGED_MACRO` добавляется только если
    `add_unpackaged_macro=True` — используется при ретрае после ошибки
    «Installed (but unpackaged) file(s) found».
    """
    out: list[str] = []
    in_check = False
    has_macro = UNPACKAGED_MACRO in spec
    for line in spec.splitlines(keepends=True):
        section = _section_token(line)
        if section == "check":
            in_check = True
            continue
        if in_check and section is not None:
            in_check = False
        if not in_check:
            out.append(line)
    body = "".join(out)
    if add_unpackaged_macro and not has_macro:
        body = UNPACKAGED_MACRO + "\n" + body
    return body


def _extract_srpm(srpm: Path, dest: Path, timeout: int) -> None:
    """Распаковать SRPM через rpm2cpio | cpio в dest. Без shell=True."""
    rpm2cpio = subprocess.Popen(
        ["rpm2cpio", str(srpm)], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        cpio = subprocess.Popen(
            ["cpio", "-idm", "--quiet"],
            stdin=rpm2cpio.stdout,
            cwd=str(dest),
            stderr=subprocess.PIPE,
        )
        if rpm2cpio.stdout is not None:
            rpm2cpio.stdout.close()
        try:
            _, cpio_err = cpio.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            cpio.kill()
            raise VibeBuildError(f"cpio timed out extracting {srpm.name}")
    finally:
        if rpm2cpio.poll() is None:
            rpm2cpio.kill()
    if cpio.returncode != 0:
        raise VibeBuildError(
            f"cpio failed extracting {srpm.name} (rc={cpio.returncode}): "
            f"{cpio_err.decode(errors='replace') if cpio_err else ''}"
        )


def patch_srpm(
    srpm_path: str,
    work_dir: Path,
    timeout: int = 600,
    add_unpackaged_macro: bool = False,
) -> str:
    """Распаковать SRPM, пропатчить spec, пересобрать новый SRPM рядом.

    Возвращает абсолютный путь к новому `.src.rpm`. NVR сохраняется, потому
    что Version/Release в spec'е не меняются. При любой ошибке поднимает
    `VibeBuildError` — вызывающий код может поймать и откатиться к исходному
    SRPM.

    Когда `add_unpackaged_macro=True`, в начало spec'а вставляется
    `%define _unpackaged_files_terminate_build 0`. По дефолту флаг выключен —
    builder поднимает его только при ретрае после соответствующей ошибки.
    """
    srpm = Path(srpm_path).resolve()
    if not srpm.exists():
        raise VibeBuildError(f"SRPM not found: {srpm}")

    suffix = "-patched-allow-unpackaged" if add_unpackaged_macro else "-patched"
    target = Path(work_dir) / f"{srpm.stem}{suffix}"
    sources_dir = target / "SOURCES"
    specs_dir = target / "SPECS"
    target.mkdir(parents=True, exist_ok=True)
    sources_dir.mkdir(exist_ok=True)
    specs_dir.mkdir(exist_ok=True)

    _extract_srpm(srpm, sources_dir, timeout)

    spec_files = sorted(sources_dir.glob("*.spec"))
    if not spec_files:
        raise VibeBuildError(f"No spec file found inside {srpm.name}")
    if len(spec_files) > 1:
        logger.warning("multiple specs in %s, picking %s", srpm.name, spec_files[0].name)

    spec_dst = specs_dir / spec_files[0].name
    spec_files[0].rename(spec_dst)
    spec_dst.write_text(
        patch_spec_text(spec_dst.read_text(), add_unpackaged_macro=add_unpackaged_macro)
    )

    result = subprocess.run(
        [
            "rpmbuild",
            "-bs",
            "--nodeps",
            "--define",
            f"_topdir {target}",
            "--define",
            f"_sourcedir {sources_dir}",
            "--define",
            f"_specdir {specs_dir}",
            "--define",
            f"_srcrpmdir {target}",
            "--define",
            f"_builddir {target}/BUILD",
            str(spec_dst),
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise VibeBuildError(
            f"rpmbuild -bs failed for {srpm.name}: {result.stderr.strip() or result.stdout.strip()}"
        )

    new_srpms = sorted(target.glob("*.src.rpm"))
    if not new_srpms:
        raise VibeBuildError(f"rpmbuild produced no SRPM for {srpm.name}")

    logger.info("patched spec inside %s -> %s", srpm.name, new_srpms[0].name)
    return str(new_srpms[0])

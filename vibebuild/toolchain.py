"""Классификация BuildRequires по используемым toolchain/языкам.

Чисто rule-based, без внешних зависимостей. Используется в CLI для
формирования секции "Languages / Toolchains detected" в саммари сборки.
"""

from __future__ import annotations

# name -> (exact_names, prefix_markers)
# Один BR может соответствовать нескольким toolchain (Python C-extension
# тянет и python3-devel, и gcc).
_TOOLCHAIN_MARKERS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "C/C++": (("gcc", "gcc-c++", "clang", "glibc-devel", "libstdc++-devel"), ()),
    "Go": (("golang", "golang-bin", "go-rpm-macros"), ("golang(",)),
    "Rust": (("rust", "cargo", "rust-packaging"), ("crate(",)),
    "Python": (
        ("python3-devel", "python3-setuptools", "python3-pip"),
        ("python3dist(", "python("),
    ),
    "Perl": (("perl", "perl-devel", "perl-generators"), ("perl(",)),
    "Ruby": (("ruby", "ruby-devel", "rubygems"), ("rubygem(",)),
    "Node.js": (("nodejs", "npm"), ("npm(", "nodejs-")),
    "Java": (("java-devel", "maven-local"), ("mvn(",)),
    "CMake": (("cmake",), ("cmake(",)),
    "Meson": (("meson", "ninja-build"), ()),
    "Autotools": (("autoconf", "automake", "libtool"), ()),
}


def detect_toolchains(build_requires: list[str]) -> list[str]:
    """Вернуть отсортированный список названий toolchain, найденных в BR.

    Имена BR проверяются на точное совпадение и на совпадение по префиксу
    для виртуальных provides (`python3dist(...)`, `golang(...)` и т.д.).
    Возвращается список без дубликатов в фиксированном порядке (как в
    `_TOOLCHAIN_MARKERS`).
    """
    found: set[str] = set()
    for req in build_requires:
        for tc_name, (exact, prefixes) in _TOOLCHAIN_MARKERS.items():
            if req in exact or any(req.startswith(p) for p in prefixes):
                found.add(tc_name)
    return [t for t in _TOOLCHAIN_MARKERS if t in found]

#!/usr/bin/env python3
"""
Benchmark: измерение времени и памяти ключевых операций vibebuild.

Запуск:
    python3 scripts/perf_bench.py [--output bench.json] [--scenarios scenario1,scenario2]
"""

from __future__ import annotations

import argparse
import gc
import json
import resource
import statistics
import sys
import time
from pathlib import Path
from typing import Callable


def _peak_rss_mb() -> float:
    """Пиковый RSS текущего процесса в МБ."""
    ru = resource.getrusage(resource.RUSAGE_SELF)
    # На Linux ru_maxrss в КБ, на macOS — в байтах. Здесь Linux-контейнер: КБ.
    return ru.ru_maxrss / 1024.0


def _time_op(fn: Callable, *, runs: int = 1) -> dict:
    """Прогнать fn() `runs` раз, вернуть статистику."""
    durations: list[float] = []
    rss_before = _peak_rss_mb()
    for _ in range(runs):
        gc.collect()
        t0 = time.monotonic()
        fn()
        durations.append(time.monotonic() - t0)
    rss_after = _peak_rss_mb()
    return {
        "runs": runs,
        "min_ms": round(min(durations) * 1000, 2),
        "median_ms": round(statistics.median(durations) * 1000, 2),
        "max_ms": round(max(durations) * 1000, 2),
        "mean_ms": round(statistics.mean(durations) * 1000, 2),
        "rss_delta_mb": round(rss_after - rss_before, 1),
    }


def scenario_ml_load() -> dict:
    """Сколько занимает import + MLPackageResolver() + ensure model loaded."""
    from vibebuild.ml_resolver import MLPackageResolver

    def _load():
        r = MLPackageResolver()
        # вынуждаем загрузку: пытаемся предсказать
        r.predict("python3dist(requests)")

    return _time_op(_load, runs=1)


def scenario_ml_predict_100(provides: list[str]) -> dict:
    """100 predict() запросов после первой загрузки."""
    from vibebuild.ml_resolver import MLPackageResolver

    r = MLPackageResolver()
    # прогреть
    r.predict(provides[0])

    def _predict_batch():
        for p in provides * 10:  # ~100
            r.predict(p)

    return _time_op(_predict_batch, runs=3)


def scenario_name_resolver_1000() -> dict:
    """1000 вызовов name_resolver.resolve() на разнообразных входах."""
    from vibebuild.name_resolver import PackageNameResolver

    inputs = [
        "python3dist(requests)", "python3dist(numpy)", "perl(File::Path)",
        "pkgconfig(glib-2.0)", "pkgconfig(openssl)", "rubygem(rake)",
        "cmake(spdlog)", "python3-devel", "gcc", "make",
    ] * 100

    r = PackageNameResolver()

    def _resolve_batch():
        for x in inputs:
            r.resolve(x)

    return _time_op(_resolve_batch, runs=3)


def scenario_analyze_srpm(srpm_path: str) -> dict:
    """Один analyze SRPM с холодным кешем."""
    from vibebuild.analyzer import get_package_info_from_srpm

    def _analyze():
        get_package_info_from_srpm(srpm_path)

    return _time_op(_analyze, runs=3)


def main() -> int:
    parser = argparse.ArgumentParser(description="vibebuild perf benchmark")
    parser.add_argument("--output", default="perf_bench.json")
    parser.add_argument("--scenarios", default="all", help="all|ml|resolver|analyzer")
    parser.add_argument(
        "--srpm",
        default="/tmp/vb-test/hello.src.rpm",
        help="SRPM для analyze-сценария (должен существовать)",
    )
    args = parser.parse_args()

    selected = set(args.scenarios.split(","))
    if "all" in selected:
        selected = {"ml", "resolver", "analyzer"}

    results: dict = {}

    if "ml" in selected:
        print("=== ML scenarios ===", file=sys.stderr)
        results["ml_load"] = scenario_ml_load()
        print(f"  ml_load: {results['ml_load']}", file=sys.stderr)

        provides = [
            "python3dist(setuptools-rust)", "pkgconfig(openssl3)", "perl(LWP::Simple)",
            "rust-packaging", "python3dist(numpy)", "cmake(spdlog)",
            "pkgconfig(glib-2.0)", "rubygem(rake)", "tex(stmaryrd.sty)", "crate(serde)",
        ]
        results["ml_predict_100"] = scenario_ml_predict_100(provides)
        print(f"  ml_predict_100: {results['ml_predict_100']}", file=sys.stderr)

    if "resolver" in selected:
        print("=== Name resolver ===", file=sys.stderr)
        results["name_resolver_1000"] = scenario_name_resolver_1000()
        print(f"  name_resolver_1000: {results['name_resolver_1000']}", file=sys.stderr)

    if "analyzer" in selected:
        print("=== Analyzer ===", file=sys.stderr)
        if Path(args.srpm).exists():
            results["analyze_srpm"] = scenario_analyze_srpm(args.srpm)
            print(f"  analyze_srpm: {results['analyze_srpm']}", file=sys.stderr)
        else:
            print(f"  пропуск analyze: {args.srpm} не существует", file=sys.stderr)

    Path(args.output).write_text(json.dumps(results, indent=2))
    print(f"\nОтчёт: {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

# Производительность vibebuild

Бенчмарки получены через `scripts/perf_bench.py` внутри контейнера
`vibebuild-dev` (Fedora 42, Python 3.13, x86_64 под Docker Desktop / arm64 host).
Цифры — медиана из 3 прогонов; разовые подъёмы (max) — холодные кеши.

## Сравнение «до / после» оптимизации (2026-05-21)

| Сценарий | Baseline | После | Δ |
|----------|----------|-------|---|
| `MLPackageResolver()` + первый `predict()` | 2958 ms / +1470 MB | lazy (0 ms на старте) | модель грузится только при первом обращении |
| `predict()` × 100 (хит кеша) | 0.17 ms median / 3363 ms max | **0.09 ms / 0.52 ms** | -47% median, -99% max |
| `name_resolver.resolve()` × 1000 | 0.07 ms | 0.06 ms | без изменений (уже быстро) |
| `analyze_srpm` (hello.src.rpm) | 44 ms median / 195 ms max | **3.6 ms / 100 ms** | **-92% median** (spec cache) |

## Что и где меняли

- **`vibebuild/ml_resolver.py:__init__`** — lazy-load. `is_available()`
  и первый `predict()` теперь тригерят загрузку модели; CLI-команды,
  не использующие ML, стартуют мгновенно.
- **`vibebuild/_spec_cache.py`** + хук в `analyzer.get_package_info_from_srpm` —
  persistent кеш `~/.cache/vibebuild/spec-cache/`. Ключ — sha256 от первых
  4 MB + размер + версия vibebuild.
- **`vibebuild/builder.py:_adaptive_poll_interval`** — adaptive polling:
  2 сек первые 30 сек, 10 сек до 3 минут, 30 сек далее. Короткие сборки
  реагируют быстрее, длинные — экономят запросы к Koji.
- **`vibebuild/resolver.py:build_dependency_graph`** — параллельная скачка
  SRPM зависимостей через `ThreadPoolExecutor(max_workers=5)`. Цепочка из
  N независимых deps скачивается за время одной (а не суммы).
- **`vibebuild/_retry.py`** + хук в `KojiClient._run_koji_command` —
  exponential backoff для transient ошибок (1s/2s/4s). Не triggers на
  программных ошибках.

## Воспроизведение

```bash
# baseline (откатить изменения и прогнать):
# git stash; python3 scripts/perf_bench.py --output baseline.json; git stash pop

# текущая версия:
docker compose -f dev/koji-server/docker-compose.yml exec vibebuild-dev bash -c '
  cd /workspace && python3 scripts/perf_bench.py --output /tmp/perf.json
'
```

## Дальнейшие направления (вне текущей итерации)

- **Approximate NN** (annoy/faiss) — для случаев, где кеш не помогает
  (уникальные provides). Сейчас brute-force даёт 100 ms на cache miss;
  annoy опустит до 1-5 ms.
- **Koji XML-RPC вместо subprocess** для read-only операций
  (`list-tagged`, `package_exists`). Экономия 100-300 ms на вызов.
- **Persistent кеш для name_resolver.resolve** — текущий in-memory жив
  только в рамках процесса.

# ML-резолвер: метрики

Все числа — фактические запуски `scripts/train_model.py` и
`scripts/prod_validation.py` внутри контейнера `vibebuild-dev` против
реального Fedora Koji (release rawhide / f42, x86_64).

## Сводный отчёт (2026-05-21)

### 1. Качество модели на held-out test-выборке

Параметры тренировки: TF-IDF char_wb (2-5), `max_features=20000`, KNN brute
cosine, top-K=10 с canonical-RPM выбором в predict, hybrid SRPM из top-1.

| Метрика | Значение |
|---------|----------|
| Train samples | 369 640 |
| Test samples (random) | 500 |
| Уникальных RPM | 55 498 |
| Уникальных SRPM | 22 959 |
| Размер модели | 288 MB (joblib compress=9) |
| Coverage | 96.4% |
| **SRPM accuracy (top-1)** | **74.9%** |
| **RPM accuracy (top-1)** | **43.6%** |
| Training time | 17 сек |
| Evaluation time | ~176 сек (brute-force cosine) |

### 2. Wide-scale прогон vibebuild на 108 реальных пакетах Fedora

Источник: `docs/PROD_VALIDATION.json` (полный JSON-отчёт).
Метод: для каждого пакета — `fetcher.download_srpm` + `analyzer.get_package_info_from_srpm`
+ `name_resolver.resolve` для каждой BR + ML fallback если правило молчит.

| Метрика | Значение |
|---------|----------|
| Пакетов прогнано | 108 |
| Успешных (analyze+resolve) | 95 (88.0%) |
| Упало на fetch (пакет не найден в rawhide) | 13 (12.0%) |
| **Упало на analyze** | **0** |
| **Упало на resolve** | **0** |
| Суммарно BuildRequires обработано | 1853 |
| Резолв через правила (`changed_by_rules`) | 541 (29.2%) |
| Резолв через ML (`changed_by_ml`) | 190 (10.3%) |
| Passthrough (имя уже валидное, как `gcc`, `make`) | 1122 (60.6%) |

### 3. Интерпретация

- **Analyzer стабилен**: 0 падений на 95 разнородных пакетах (от `hello` до
  `git`/`doxygen`/`texlive-base`/`systemd` со сборочными цепочками 50-82 BR).
- **ML добавляет реальную ценность**: 190 BR (10.3%) распознаны после ML,
  когда правила вернули пакет без изменений — это нетривиальные provides
  (`tex(...)`, `crate(...)`, `cmake(...)`, `pkgconfig(...)` с экзотическими
  именами).
- **13 fetch-failure — не баг vibebuild**: пакеты были retired/переименованы
  в rawhide (`python-pyyaml` → `python3-pyyaml`, `python-numpy` ->
  `python3-numpy`, и т.д.). На фиксированном релизе F42 успех был бы выше.

### 4. Пакеты с самыми тяжёлыми зависимостями (для прод-репликации)

| Пакет | BR | rule | ML | passthrough |
|-------|-----|------|-----|-------------|
| git | 82 | 24 | 8 | 50 |
| doxygen | 82 | 55 | 6 | 21 |
| systemd | 73 | 14 | 6 | 53 |
| graphviz | 64 | 0 | 5 | 59 |
| gcc | 54 | 0 | 8 | 46 |
| perl-DBI | 53 | 44 | 0 | 9 |
| perl-Test-Simple | 52 | 48 | 0 | 4 |
| texlive-base | 52 | 2 | 9 | 41 |

`perl-*` пакеты — отличный кейс для правил (`perl(Module::Name)` → `perl-Module-Name`).
`graphviz`/`systemd`/`gcc` — много passthrough (BR имена уже валидные).
`texlive-base` — типичная роль ML: `tex(...)` правилам неизвестно, модель
закрывает 9 BR из 52.

## Воспроизведение

### Тренировка
```bash
docker compose -f dev/koji-server/docker-compose.yml exec vibebuild-dev bash -c '
  cd /workspace
  vibebuild train --release 42 --eval-sample 500
'
```

### Wide-scale валидация
```bash
docker compose -f dev/koji-server/docker-compose.yml exec vibebuild-dev bash -c '
  cd /workspace
  python3 scripts/prod_validation.py --release rawhide --output /tmp/r.json
'
```

## Не достигнутое (честно)

- **Целевой RPM accuracy ≥ 60%** — фактический 43.6%. Принципиальный потолок
  brute-force KNN на pure-TF-IDF, где провайды повторяются в множестве
  RPM-подпакетов одного SRPM. Чтобы пробить — нужен подход уровня
  «обучаемый classifier на SRPM-классы» или approximate NN с
  weighted-features. Это отдельная задача.
- **Целевой размер ≤ 50 MB** — фактический 288 MB. Сжатие joblib=9 уже
  применено; дальше — переход на annoy/faiss с раздельным storage.

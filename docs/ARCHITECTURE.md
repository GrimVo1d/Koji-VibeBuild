# Архитектура VibeBuild

VibeBuild — расширение системы сборки [Koji](https://docs.pagure.org/koji/), которое автоматизирует разрешение зависимостей при сборке RPM-пакетов.

Стандартная команда `koji build` собирает один пакет и требует, чтобы все BuildRequires уже были доступны в репозитории Koji. Если зависимость отсутствует, сборка падает. VibeBuild решает эту проблему: анализирует SRPM, рекурсивно скачивает недостающие зависимости из Fedora, строит DAG зависимостей и собирает пакеты в правильном порядке.

## Содержание

- [Архитектура верхнего уровня](#архитектура-верхнего-уровня)
- [Слои приложения](#слои-приложения)
- [Поток данных](#поток-данных)
- [Разрешение имён пакетов](#разрешение-имён-пакетов)
- [Построение DAG и порядок сборки](#построение-dag-и-порядок-сборки)
- [Теги и таргеты Koji](#теги-и-таргеты-koji)
- [Иерархия исключений](#иерархия-исключений)
- [Конвенции и кеширование](#конвенции-и-кеширование)

---

## Архитектура верхнего уровня

```
┌─────────────────────────────────────────────────────────────┐
│                     Пользователь (CLI)                       │
└─────────────────────────────┬───────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      VibeBuild                               │
│  ┌──────────┐  ┌───────────────┐  ┌──────────┐  ┌────────┐ │
│  │ analyzer │  │ name_resolver │  │ resolver │  │ builder│ │
│  │          │  │ + ml_resolver │  │          │  │        │ │
│  └──────────┘  └───────────────┘  └──────────┘  └────────┘ │
│                ┌──────────┐                                  │
│                │ fetcher  │                                  │
│                └──────────┘                                  │
└─────────────────┬───────────────────────────────────────────┘
                  │
        ┌─────────┼──────────────┐
        ▼         ▼              ▼
  ┌─────────┐ ┌───────────┐ ┌──────────────────┐
  │Koji Hub │ │Fedora Koji│ │src.fedoraproject │
  │(локал.) │ │(внешний)  │ │(источник SRPM)   │
  └────┬────┘ └───────────┘ └──────────────────┘
       ▼
  ┌─────────┐
  │ kojid   │
  │ + mock  │
  └─────────┘
```

---

## Слои приложения

Пакет `vibebuild/` содержит восемь модулей. Точка входа — `cli.py:main` (console-script `vibebuild`).

### `analyzer.py` — анализ SRPM

Парсинг SRPM и spec-файлов, извлечение метаданных.

**Ключевые элементы:**

- `BuildRequirement` — dataclass: имя, версия, оператор сравнения
- `PackageInfo` — dataclass: name, version, release, build_requires, source_urls
- `SpecAnalyzer` — парсер spec-файлов
- `get_build_requires(srpm_path) -> list[str]` — извлекает только список BuildRequires через `rpm -qp --requires`
- `get_package_info_from_srpm(srpm_path) -> PackageInfo` — распаковывает SRPM через `rpm2cpio | cpio`, парсит .spec

**Алгоритм парсинга spec:**

1. Чтение файла построчно
2. Извлечение полей `Name:`, `Version:`, `Release:`, `BuildRequires:`, `Source:`
3. Раскрытие макросов RPM (`%{name}`, `%{version}`)
4. Парсинг BuildRequires с учётом операторов (`>=`, `<=`, `>`, `<`, `=`)

### `name_resolver.py` — rule-based разрешение имён

Spec-файлы часто содержат виртуальные имена зависимостей, не совпадающие с реальными RPM. `PackageNameResolver` реализует пайплайн:

```
Вход → Кеш → Раскрытие макросов → Паттерны provides → ML-фоллбэк → Результат
```

**Компоненты:**

- `SYSTEM_MACROS` — таблица из 18 системных макросов RPM (`%{python3_pkgversion}` → `3`, `%{_bindir}` → `/usr/bin` и т. д.)
- `PROVIDE_PATTERNS` — 9 скомпилированных regex-паттернов с функциями-трансформерами: `python(\d*)dist(X)` → `python{N}-{X}`, `pkgconfig(X)` → `{X}-devel`, `perl(X::Y)` → `perl-X-Y`, `rubygem`, `npm`, `cmake`, `tex`, `golang`, `mvn`
- `SUBPACKAGE_TO_SRPM` — захардкоженный маппинг (≈380 записей) подпакет → SRPM (`perl-File-Path` → `perl`, `python3-libs` → `python3.13`, `gcc-c++` → `gcc`)
- `resolve_srpm_name(rpm_name) -> list[str]` — генерирует варианты SRPM-имён для скачивания

### `ml_resolver.py` — ML-фоллбэк (опционально)

Срабатывает, если rule-based паттерны не справились с виртуальным provide.

**Архитектура модели:**

```
вход → TF-IDF (char n-grams 2-5, max 50k features)
     → KNN (cosine distance, k=5)
     → distance ≤ 0.3 → (rpm_name, srpm_name)
     → distance > 0.3 → None (низкая уверенность)
```

- `MLPackageResolver` — обёртка над scikit-learn моделью
- Гейтинг через флаг `HAS_SKLEARN`: при отсутствии `scikit-learn` модуль молча отключается
- Модель сохраняется в `vibebuild/data/model.joblib` (~5–15 МБ)
- Предсказания кешируются в `~/.cache/vibebuild/ml_name_cache.json`

Обучение — через `scripts/collect_training_data.py` (парсинг `primary.xml` из репозиториев Fedora) и `scripts/train_model.py`.

### `resolver.py` — построение DAG зависимостей

**Ключевые классы:**

- `KojiClient` — клиент Koji через CLI (`subprocess`). Методы: `list_packages(tag)`, `package_exists(pkg, tag)`, `list_tagged_builds(tag)`, `search_package(pattern)`
- `DependencyNode` — узел графа: `name`, `srpm_path`, `dependencies`, `is_available`, `build_order`
- `DependencyResolver` — основной класс:
  - `find_missing_deps(deps, tag)` — отфильтровывает зависимости, отсутствующие в Koji
  - `build_dependency_graph(pkg, srpm, srpm_resolver)` — рекурсивный обход
  - `topological_sort()` — алгоритм Кана; обнаруживает циклы
  - `get_build_chain()` — группировка узлов по уровням (`build_order`)

`find_missing_deps()` нормализует имена через `name_resolver.resolve()` перед проверкой в Koji.

**Алгоритм построения графа:**

1. Начало с корневого пакета
2. Для каждого пакета:
   - Если есть в Koji-теге → `is_available = True`
   - Иначе: извлечение BuildRequires, поиск недостающих, рекурсивная обработка
3. Топологическая сортировка
4. Группировка по уровням: пакеты без зависимостей — уровень 0; уровень пакета = max(уровень зависимостей) + 1; пакеты одного уровня собираются параллельно

### `fetcher.py` — скачивание SRPM

**Источники (по приоритету):**

| # | Источник | Метод |
|---|---|---|
| 1 | Fedora Koji (`koji.fedoraproject.org`) | `koji download-build --type=src` |
| 2 | `src.fedoraproject.org` | Скачивание spec + sources, локальная сборка через `rpmbuild -bs` |

**Ключевые классы:**

- `SRPMSource` — конфигурация источника (имя, URL, приоритет)
- `SRPMFetcher` — загрузчик с кешированием и опциональным отключением SSL-верификации

Если передан `name_resolver`, `download_srpm()` использует `resolve_srpm_name()` для перебора вариантов SRPM-имён: например, `python3-requests` пробуется и как `python-requests`, и как `python3-requests`.

### `builder.py` — оркестрация сборки

**Ключевые элементы:**

- `BuildStatus` — enum: `PENDING`, `BUILDING`, `COMPLETE`, `FAILED`, `CANCELED`
- `BuildTask` — задача сборки: `package_name`, `srpm_path`, `target`, `task_id`, `status`
- `BuildResult` — итог: `success`, `tasks`, `built_packages`, `failed_packages`, `total_time`
- `KojiBuilder` — оркестратор; содержит `KojiClient`, `DependencyResolver`, `SRPMFetcher`

**Метод `build_with_deps(srpm_path)` — главная функция:**

1. Парсинг SRPM (`get_package_info_from_srpm`)
2. Построение DAG (`build_dependency_graph`, рекурсивное скачивание недостающих)
3. Получение build-chain (`get_build_chain`)
4. Для каждого уровня:
   - `koji build --nowait` для всех пакетов уровня
   - Polling до завершения
   - `koji wait-repo` — ожидание регенерации репозитория
5. Сборка целевого пакета
6. Возврат `BuildResult`

Без ожидания `wait-repo` сборки следующего уровня упадут с «dependency not found».

### `cli.py` — CLI-интерфейс

Парсинг аргументов, каскадная загрузка конфигурации:

```
CLI-флаги (наивысший приоритет)
    ↓
~/.koji/config
    ↓
/etc/koji.conf (фоллбэк)
```

Создаёт `PackageNameResolver`, `SRPMFetcher`, `DependencyResolver`, `KojiBuilder`, диспетчирует в нужный режим (полная сборка, `--analyze-only`, `--download-only`, `--dry-run`, `--no-deps`, `--scratch`).

### `__main__.py`

Позволяет запуск через `python -m vibebuild`, делегирует в `cli.main`.

### `exceptions.py`

См. раздел [Иерархия исключений](#иерархия-исключений).

---

## Поток данных

```
SRPM-файл                                                          RPM-пакеты
    │                                                                   ▲
    ▼                                                                   │
analyzer ──► PackageInfo ──► name_resolver ──► нормализованные имена   │
                                  │                                     │
                                  ▼                                     │
                              resolver ◄── KojiClient (проверка тега)   │
                                  │                                     │
                                  ├─► find_missing ──► fetcher ──► SRPM │
                                  │                       │             │
                                  │           ◄───────────┘             │
                                  ▼                                     │
                              DAG → topological sort → build chain      │
                                  │                                     │
                                  ▼                                     │
                              builder ──► koji build (по уровням)──────┘
                                  │           │
                                  │           ▼
                                  └─► wait-repo между уровнями
```

---

## Разрешение имён пакетов

Примеры преобразований:

| В spec-файле | Реальное имя RPM | Имя SRPM |
|---|---|---|
| `python3dist(requests)` | `python3-requests` | `python-requests` |
| `python3dist(setuptools)` | `python3-setuptools` | `python-setuptools` |
| `%{python3_pkgversion}-devel` | `python3-devel` | `python3` |
| `pkgconfig(glib-2.0)` | `glib-2.0-devel` | `glib-2.0` |
| `perl(File::Path)` | `perl-File-Path` | `perl` |
| `cmake(Qt5Core)` | `cmake-qt5core` | — |
| `npm(typescript)` | `nodejs-typescript` | `nodejs-typescript` |
| `rubygem(bundler)` | `rubygem-bundler` | `rubygem-bundler` |
| `golang(github.com/foo/bar)` | `golang-github.com-foo-bar` | — |
| `mvn(org.apache:commons-lang)` | `commons-lang` | `commons-lang` |

**Точки интеграции `name_resolver`:**

- `analyzer` — лучшее раскрытие макросов через `SYSTEM_MACROS`
- `resolver` — нормализация имён перед проверкой в Koji
- `fetcher` — перебор вариантов SRPM через `resolve_srpm_name()`
- `builder` — создаёт и передаёт резолвер во все компоненты

ML-резолвер опционален (`pip install -e ".[ml]"`); без `scikit-learn` он молча деградирует.

---

## Построение DAG и порядок сборки

Пример: собираем `my-app`, зависящий от `lib-foo`, `lib-bar`, `lib-baz`. `lib-foo` зависит от `lib-base`, `lib-baz` — от `lib-core`. `lib-bar`, `lib-base`, `lib-core` уже есть в Koji.

```
       my-app
      /   |   \
  lib-foo lib-bar(ok) lib-baz
     │              │
  lib-base(ok)   lib-core(ok)
```

**Топологическая сортировка (алгоритм Кана):**

1. Вычисление in-degree для каждого узла
2. Узлы с in-degree = 0 → очередь
3. Извлечение узлов из очереди, уменьшение in-degree зависимых
4. Обнаружение циклов: если обработаны не все узлы → `CircularDependencyError`

**Группировка по уровням:**

- Уровень 0: `lib-foo`, `lib-baz` (параллельно)
- `koji wait-repo`
- Уровень 1: `my-app`

---

## Теги и таргеты Koji

```
fedora-target (Build Target)
    ├── build_tag: fedora-build  (BuildRoot, наследует от dest)
    └── dest_tag:  fedora-dest   (хранилище готовых пакетов)

fedora-build → внешние репозитории Fedora (base + updates)
```

**Процесс сборки:**

1. SRPM загружается в Koji
2. Mock создаёт chroot из пакетов `fedora-build`
3. Пакет собирается в изолированном окружении
4. Результат тегируется в `fedora-dest`
5. Репозиторий `fedora-build` регенерируется

---

## Иерархия исключений

Корень — `VibeBuildError`. Все исключения VibeBuild наследуются от него, поэтому ловятся одним `except`.

```
VibeBuildError
├── InvalidSRPMError          — невалидный SRPM
├── SpecParseError            — ошибка парсинга spec
├── DependencyResolutionError — ошибка разрешения зависимостей
│   └── CircularDependencyError
├── SRPMNotFoundError         — SRPM не найден ни в одном источнике
├── KojiBuildError            — ошибка сборки в Koji
├── KojiConnectionError       — ошибка подключения к Koji Hub
└── NameResolutionError       — ошибка разрешения имени пакета
```

---

## Конвенции и кеширование

**Python:**

- Минимальная версия — 3.9. Использовать `dict[]`/`list[]` (PEP 585), без walrus-оператора в коде, где важна совместимость с 3.9.
- Тесты используют мокинг `koji`/`subprocess`/`requests` — реальный Koji-сервер для unit-тестов не требуется.

**Конфигурация:**

- Загружается из `~/.koji/config` (основной), `/etc/koji.conf` (фоллбэк)
- CLI-флаги переопределяют конфиги

**Кеши:**

| Кеш | Где |
|---|---|
| Доступные пакеты в Koji-теге | Память, на сессию |
| Скачанные SRPM | `download_dir` фетчера |
| Граф зависимостей | Память, строится один раз |
| Разрешённые имена | Память, на сессию |
| ML-предсказания | `~/.cache/vibebuild/ml_name_cache.json` (персистентный) |

**Параллелизм:**

- Пакеты одного уровня DAG собираются параллельно (`koji build --nowait`)
- Скачивание SRPM может идти параллельно с анализом

**Безопасность:**

- SSL-клиентские сертификаты для аутентификации в Koji
- Проверка CA для HTTPS
- Все сборки изолированы в mock chroot

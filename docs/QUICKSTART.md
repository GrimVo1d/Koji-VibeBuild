# QuickStart — VibeBuild с нуля

Документ для тех, кто открыл проект и не понимает, что тут происходит. Объясняет с нуля: что такое RPM, SRPM, Koji, зачем нужен VibeBuild, как работает каждый модуль и как этим всем пользоваться. Никакого предыдущего опыта с RPM-пакетами не требуется.

## Содержание

1. [Базовые понятия](#1-базовые-понятия)
2. [Какую проблему решает VibeBuild](#2-какую-проблему-решает-vibebuild)
3. [Модули — что делает каждый](#3-модули--что-делает-каждый)
4. [Как всё работает вместе](#4-как-всё-работает-вместе)
5. [CLI — все команды с примерами](#5-cli--все-команды-с-примерами)
6. [Конфигурация](#6-конфигурация)
7. [Первая сборка: пошагово](#7-первая-сборка-пошагово)
8. [Глоссарий](#8-глоссарий)

---

## 1. Базовые понятия

### RPM

RPM (Red Hat Package Manager) — формат пакетов в Linux-дистрибутивах семейства Red Hat: Fedora, RHEL, CentOS, AlmaLinux, Rocky Linux.

Грубо: RPM — это `.rpm` файл, внутри которого скомпилированные программы, библиотеки и конфигурации. Команда `dnf install python3` ставит RPM-пакет.

```
python3-3.12.1-1.fc42.x86_64.rpm
  ^        ^     ^   ^      ^
 имя     версия  | fedora архитектура
              релиз
```

### SRPM

SRPM (Source RPM) — **исходный** RPM-пакет. Из него собирается бинарный RPM.

Внутри SRPM:

- **Spec-файл** — рецепт сборки (главное)
- **Исходный код** — архив с исходниками (tar.gz, zip)
- **Патчи** — если нужно что-то пропатчить

```
python3-3.12.1-1.fc42.src.rpm     <-- SRPM (обратите внимание на .src.)
python3-3.12.1-1.fc42.x86_64.rpm  <-- бинарный RPM (уже собранный)
```

Зачем нужен SRPM? Чтобы любой человек мог **пересобрать** пакет из исходников. Это основа всей пакетной инфраструктуры Fedora.

### Spec-файл

Рецепт сборки пакета. Текстовый файл с расширением `.spec`:

```spec
Name:    python-requests
Version: 2.31.0
Release: 1%{?dist}

# Зависимости для СБОРКИ (вот это самое важное для нас):
BuildRequires: python3-devel
BuildRequires: python3-setuptools
BuildRequires: python3dist(pytest)
BuildRequires: python3dist(urllib3)

# Зависимости для ЗАПУСКА (это другое):
Requires: python3-urllib3
Requires: python3-charset-normalizer

%description
HTTP-клиент для Python.

%build
%py3_build

%install
%py3_install
```

Ключевое отличие:

- **BuildRequires** — нужны только для СБОРКИ. Компиляторы, библиотеки разработки, тестовые фреймворки. Без них пакет не соберётся.
- **Requires** — нужны для ЗАПУСКА. То, что конечный пользователь получит как зависимости при установке.

VibeBuild работает именно с **BuildRequires**.

### Koji

Koji — централизованная система сборки RPM-пакетов. Аналог CI/CD, но специально для пакетов.

```
                    ┌─────────────┐
                    │  Koji Web   │  <-- веб-интерфейс
                    └──────┬──────┘
                           │
┌──────────┐        ┌──────┴──────┐        ┌──────────────┐
│ Клиент   │───────>│  Koji Hub   │───────>│ Koji Builder │
└──────────┘        └──────┬──────┘        └──────────────┘
                           │                  собирает пакеты
                    ┌──────┴──────┐
                    │ PostgreSQL  │
                    └─────────────┘
                    база: пакеты, сборки, теги, задачи
```

- **Koji Hub** — центральный сервер, принимает задачи на сборку
- **Koji Builder** — машина, которая реально собирает пакеты (в изолированном окружении mock)
- **Koji Web** — веб-морда для просмотра результатов
- **PostgreSQL** — база данных со всей информацией

Когда выполняется `koji build f42-candidate my-package.src.rpm`:

1. Hub принимает задачу
2. Builder скачивает SRPM
3. Builder создаёт чистое окружение (mock) с нужными зависимостями
4. Builder собирает пакет
5. Результат сохраняется и тегируется

### Теги и таргеты

Koji организует пакеты через **теги** (tags). Тег — метка, привязанная к набору пакетов.

```
f42-candidate      <-- кандидаты на включение в Fedora 42
  └─ f42-build     <-- тег для сборки, из него Builder берёт зависимости
```

**Таргет** (target) — пара «куда складывать результат» + «откуда брать зависимости»:

```
Таргет:    f42-candidate
  ├── destination tag: f42-candidate  (куда попадёт готовый пакет)
  └── build tag:       f42-build      (откуда берутся зависимости)
```

При сборке для `f42-candidate` Builder смотрит в `f42-build`: есть ли там все BuildRequires. Если нет — сборка падает.

### Virtual Provides

В spec-файлах зависимости часто пишутся НЕ как реальные имена пакетов:

```spec
BuildRequires: python3dist(requests)     # пакет называется python3-requests
BuildRequires: pkgconfig(glib-2.0)       # это glib2-devel
BuildRequires: perl(File::Path)          # это perl-File-Path
```

Это **виртуальные provides**. RPM позволяет пакету «предоставлять» произвольные имена. Пакет `python3-requests` предоставляет `python3dist(requests)`.

Проблема: чтобы **скачать** пакет, нужно знать настоящее имя, а не виртуальное. VibeBuild умеет конвертировать виртуальные имена в реальные (см. модуль `name_resolver.py`).

### DAG

DAG (Directed Acyclic Graph) — направленный ациклический граф.

Допустим, нужно собрать `my-app`. Ему нужны `lib-a` и `lib-b`. `lib-a` нужна `lib-d`. `lib-b` нужны `lib-d` и `lib-e`.

```
        my-app
       /   |   \
    lib-a  lib-b  lib-c
      |    / \
    lib-d  lib-e
```

Граф направленный (стрелки идут от зависящего к зависимости) и ациклический (нет циклов).

**Порядок сборки** определяется так:

- Сначала: `lib-c`, `lib-d`, `lib-e` (ни от кого не зависят) — Level 0
- Потом: `lib-a`, `lib-b` (зависят от Level 0) — Level 1
- В конце: `my-app` — Level 2

Внутри одного уровня пакеты можно собирать **параллельно**.

---

## 2. Какую проблему решает VibeBuild

### Стандартный koji build

```bash
$ koji build f42-candidate python-requests-2.31.0-1.fc42.src.rpm

# Builder начинает сборку...
# Создаёт mock-окружение...
# Пытается установить BuildRequires...

ERROR: No matching package to install: python3dist(urllib3)
ERROR: No matching package to install: python3dist(charset-normalizer)
ERROR: Not all dependencies satisfied
BUILD FAILED
```

Builder нашёл в spec-файле зависимости, но в `f42-build` таге этих пакетов нет.

### Без VibeBuild — руками

1. Понять, какие зависимости отсутствуют
2. Найти SRPM для каждой отсутствующей
3. Проверить, есть ли у НИХ отсутствующие зависимости
4. Рекурсивно повторять, пока не дойдёшь до «дна»
5. Определить правильный порядок сборки
6. Собрать всё по очереди, ожидая регенерацию репозитория между уровнями
7. Наконец собрать целевой пакет

Для одного пакета это может быть 5–20 зависимостей и несколько часов работы.

### С VibeBuild — одна команда

```bash
$ vibebuild f42-candidate python-requests-2.31.0-1.fc42.src.rpm

Analyzing python-requests-2.31.0-1.fc42.src.rpm...
Found 12 BuildRequires
Checking availability in f42-build...
Missing: 3 packages
  - python3-urllib3
  - python3-charset-normalizer
  - python3-idna

Downloading SRPMs from Fedora...
  Downloaded: python-urllib3-2.1.0-1.fc42.src.rpm
  Downloaded: python-charset-normalizer-3.3.0-1.fc42.src.rpm
  Downloaded: python-idna-3.6-1.fc42.src.rpm

Building dependency graph...
Build chain: 2 levels, 4 packages

Level 0: python-charset-normalizer, python-idna, python-urllib3
  [building...] [building...] [building...]
  [complete]    [complete]    [complete]

Waiting for repo regeneration...

Level 1 (target): python-requests
  [building...]
  [complete]

BUILD COMPLETE
  Built: 4 packages
  Failed: 0
  Time: 12m 34s
```

---

## 3. Модули — что делает каждый

```
vibebuild/
  ├── cli.py             -- точка входа, парсинг аргументов
  ├── __main__.py        -- запуск через `python -m vibebuild`
  ├── analyzer.py        -- парсинг SRPM, извлечение BuildRequires
  ├── name_resolver.py   -- конвертация виртуальных имён в реальные
  ├── ml_resolver.py     -- ML-фоллбэк для имён (опционально)
  ├── resolver.py        -- построение графа зависимостей
  ├── fetcher.py         -- скачивание SRPM из Fedora
  ├── builder.py         -- оркестрация сборки
  └── exceptions.py      -- кастомные исключения
```

### analyzer.py

Парсит SRPM и извлекает информацию о пакете, в первую очередь список BuildRequires.

**Шаги:**

1. На входе — `.src.rpm` файл
2. Извлечение spec-файла через `rpm2cpio | cpio`
3. Парсинг spec-файла построчно
4. Сбор макросов (`%global`, `%define`)
5. Раскрытие макросов в BuildRequires (`%{python3_pkgversion}` → `3`)
6. Возврат структурированных данных

**Ключевые классы:**

```python
@dataclass
class BuildRequirement:
    name: str                        # python3dist(requests)
    version: Optional[str] = None    # 2.28.0
    operator: Optional[str] = None   # >=

@dataclass
class PackageInfo:
    name: str                              # python-requests
    version: str                           # 2.31.0
    release: str                           # 1.fc42
    build_requires: list[BuildRequirement]
    source_urls: list[str]
```

**Использование:**

```python
from vibebuild.analyzer import get_build_requires, get_package_info_from_srpm

deps = get_build_requires("my-package.src.rpm")
# ["python3-devel", "python3dist(urllib3)", ...]

info = get_package_info_from_srpm("my-package.src.rpm")
# PackageInfo(name="python-requests", version="2.31.0", ...)
```

### name_resolver.py

Превращает виртуальные имена зависимостей в реальные имена RPM, а затем в имена SRPM.

**Цепочка преобразования:**

```
python3dist(requests)  -->  python3-requests  -->  python-requests (SRPM)
   виртуальное            реальный RPM          исходный пакет
```

**Pipeline:**

```
Входное имя
    │
    ├─> Кэш (уже разрешали?)
    │
    ├─> Раскрытие макросов (%{python3_pkgversion} → 3)
    │
    ├─> 9 regex-паттернов виртуальных provides:
    │      python3dist(X) → python3-X
    │      pkgconfig(X)   → X-devel
    │      perl(X::Y)     → perl-X-Y
    │      rubygem(X)     → rubygem-X
    │      npm(X)         → nodejs-X
    │      cmake(X)       → cmake-x
    │      tex(X)         → texlive-X
    │      golang(X/Y)    → golang-X-Y
    │      mvn(X:Y)       → Y
    │
    ├─> Обработка boolean deps: (python3dist(X) if ...)
    │
    └─> ML-фоллбэк (если правила не справились)
```

**Маппинг подпакетов (`resolve_srpm_name`):**

Когда RPM-пакет является **подпакетом** другого SRPM:

```
python3-libs      --> SRPM "python3.13" (не "python3-libs"!)
python3-devel     --> SRPM "python3.13"
gcc-c++           --> SRPM "gcc"
perl-File-Path    --> SRPM "perl"
glibc-devel       --> SRPM "glibc"
```

В `name_resolver.py` захардкожено ~380 таких маппингов в `SUBPACKAGE_TO_SRPM`.

### ml_resolver.py

ML-модель как фоллбэк, если правила из `name_resolver.py` не справились.

**Когда нужен:** для редких виртуальных provides, не покрытых regex-паттернами.

**Как работает:**

1. **TF-IDF** — превращает имя пакета в числовой вектор. Имя бьётся на char n-граммы 2–5 символов, считается их «важность».
2. **KNN** — ищет ближайших соседей по косинусному расстоянию.
3. Модель обучена на маппингах «виртуальное имя → RPM-пакет», собранных из Fedora.

ML-модель **опциональна**. Требует `scikit-learn`. Без него VibeBuild работает с одними правилами.

```python
from vibebuild.ml_resolver import MLPackageResolver

resolver = MLPackageResolver(model_path="model.joblib")
if resolver.is_available():
    result = resolver.predict("some-weird-provide")
    # {"rpm_name": "some-package", "srpm_name": "some-package"}
```

### resolver.py

Строит DAG, проверяет наличие пакетов в Koji, определяет порядок сборки.

**Шаги:**

1. Получает целевой SRPM и его BuildRequires от `analyzer`
2. Для каждого BuildRequires проверяет наличие в Koji (`koji list-tagged`)
3. Отсутствующие добавляет в граф как «нужно собрать»
4. Рекурсивно обрабатывает зависимости зависимостей
5. Топологическая сортировка
6. Группировка по уровням

**Ключевые классы:**

```python
@dataclass
class DependencyNode:
    name: str
    srpm_path: Optional[str] = None
    package_info: Optional[PackageInfo] = None
    dependencies: list[str] = []
    is_available: bool = False     # уже есть в Koji?
    build_order: int = -1

class KojiClient:
    """Обёртка над CLI-утилитой koji."""

class DependencyResolver:
    """Строит граф и вычисляет порядок сборки."""
```

**Пример:**

```
Вход: my-app.src.rpm (зависит от lib-a, lib-b, lib-c)
       lib-a зависит от lib-d
       lib-b зависит от lib-d, lib-e
       lib-c, lib-d, lib-e -- ни от кого не зависят

Граф:
    my-app --> lib-a --> lib-d
           --> lib-b --> lib-d
                     --> lib-e
           --> lib-c

Топологическая сортировка: lib-d, lib-e, lib-c, lib-a, lib-b, my-app

Уровни:
    Level 0: [lib-c, lib-d, lib-e]  -- параллельно
    Level 1: [lib-a, lib-b]         -- параллельно
    Level 2: [my-app]               -- target
```

### fetcher.py

Скачивает SRPM-файлы из Fedora для пакетов, которых нет в локальном Koji.

**Источники (по приоритету):**

1. **Fedora Koji** (`koji.fedoraproject.org`) через XML-RPC — ищет последний билд для нужной версии Fedora, скачивает SRPM с `kojipkgs.fedoraproject.org`
2. **src.fedoraproject.org** через HTTP — скачивает spec + sources, пересобирает SRPM локально через `rpmbuild -bs`

**Особенности:**

- Кэширование скачанных SRPM
- Автоопределение версии Fedora из имени тега (`f42-candidate` → fedora 42)
- Фоллбэк на предыдущие версии Fedora
- Маппинг имён через `name_resolver`

```python
fetcher = SRPMFetcher(
    download_dir="/tmp/srpms",
    fedora_release="42",
    name_resolver=resolver,
)
srpm_path = fetcher.download_srpm("python-requests")
# → "/tmp/srpms/python-requests-2.31.0-1.fc42.src.rpm"
```

### builder.py

Оркестрирует весь процесс сборки. Главный модуль, который собирает всё вместе.

**Полный цикл `build_with_deps`:**

```
1. wait-repo         -- убедиться, что репо готов
2. analyze SRPM      -- извлечь BuildRequires (analyzer)
3. resolve names     -- конвертация имён (name_resolver)
4. find missing      -- проверить наличие в Koji (resolver)
5. download missing  -- скачать недостающие SRPM (fetcher)
6. build DAG         -- построить граф (resolver)
7. get build chain   -- определить уровни

Для каждого уровня:
    8. submit builds  -- koji build --nowait для всех пакетов уровня
    9. poll builds    -- ждать завершения
    10. wait-repo     -- ждать регенерацию репозитория

11. build target     -- собрать целевой пакет
12. return result    -- BuildResult
```

**Repo regeneration:** когда пакет собран и протегирован, он НЕ сразу доступен. Koji нужно перегенерировать репозиторий (`createrepo`):

```
Level 0 собран → koji call newRepo f42-build
              → koji wait-repo f42-build --timeout=1800
              → Level 1 теперь видит пакеты из Level 0
```

Без ожидания repo regen сборки следующего уровня упадут с «dependency not found».

**Ключевые классы:**

```python
class BuildStatus(Enum):
    PENDING, BUILDING, COMPLETE, FAILED, CANCELED

@dataclass
class BuildTask:
    package_name: str
    srpm_path: str
    target: str
    task_id: Optional[int] = None
    status: BuildStatus = BuildStatus.PENDING

@dataclass
class BuildResult:
    success: bool
    tasks: list[BuildTask]
    failed_packages: list[str]
    built_packages: list[str]
    total_time: float

class KojiBuilder:
    def build_with_deps(self, srpm_path: str) -> BuildResult: ...
```

### cli.py

Точка входа. Парсит аргументы, загружает конфигурацию, запускает нужный режим.

**Режимы:**

| Режим | Флаг |
|-------|------|
| Полная сборка | (по умолчанию) |
| Только анализ | `--analyze-only` |
| Только скачивание | `--download-only` |
| Сухой прогон | `--dry-run` |
| Без зависимостей | `--no-deps` |
| Scratch | `--scratch` |

**Загрузка конфигурации (каскадно):**

```
CLI-флаги (наивысший приоритет)
    ↓
~/.koji/config
    ↓
/etc/koji.conf (фоллбэк)
```

### exceptions.py

```
VibeBuildError                  -- базовое исключение
  ├── InvalidSRPMError
  ├── SpecParseError
  ├── DependencyResolutionError
  │     └── CircularDependencyError
  ├── SRPMNotFoundError
  ├── KojiBuildError
  ├── KojiConnectionError
  └── NameResolutionError
```

Все ошибки ловятся одним `except`:

```python
try:
    result = builder.build_with_deps("my-package.src.rpm")
except VibeBuildError as e:
    print(f"Что-то пошло не так: {e}")
```

---

## 4. Как всё работает вместе

Пример: `vibebuild f42-candidate python-requests`

```
1. cli.py парсит аргументы
   → target = "f42-candidate"
   → package = "python-requests" (не файл, а имя)

2. cli.py: "python-requests" -- не файл, скачиваем
   → fetcher.download_srpm("python-requests")
   → /tmp/vibebuild/python-requests-2.31.0-1.fc42.src.rpm

3. analyzer.py парсит SRPM
   → BuildRequires:
     - python3-devel
     - python3-setuptools
     - python3dist(pytest)
     - python3dist(urllib3)
     - python3dist(charset-normalizer)
     - python3dist(idna)
     - python3dist(certifi)
     + ещё 5...

4. name_resolver.py конвертирует имена
   → python3dist(urllib3)            → python3-urllib3
   → python3dist(charset-normalizer) → python3-charset-normalizer
   → python3dist(idna)               → python3-idna
   → python3dist(certifi)            → python3-certifi
   → python3dist(pytest)             → python3-pytest

5. resolver.py проверяет Koji
   → python3-devel              ЕСТЬ
   → python3-setuptools         ЕСТЬ
   → python3-urllib3            НЕТ
   → python3-charset-normalizer НЕТ
   → python3-idna               НЕТ
   → python3-certifi            ЕСТЬ
   → python3-pytest             ЕСТЬ

   Отсутствуют: python3-urllib3, python3-charset-normalizer, python3-idna

6. name_resolver.py: resolve_srpm_name для скачивания
   → python3-urllib3             → SRPM: python-urllib3
   → python3-charset-normalizer  → SRPM: python-charset-normalizer
   → python3-idna                → SRPM: python-idna

7. fetcher.py скачивает 3 SRPM из Fedora

8. resolver.py строит DAG (рекурсивно проверяет зависимости скачанных)

   Граф:
     python-requests → [python-urllib3, python-charset-normalizer, python-idna]
     python-urllib3 → []
     python-charset-normalizer → []
     python-idna → []

   Уровни:
     Level 0: python-urllib3, python-charset-normalizer, python-idna
     Level 1: python-requests (target)

9. builder.py собирает Level 0 (3 параллельных koji build --nowait)
   → все три завершились: COMPLETE

10. builder.py ждёт repo regen
    → koji call newRepo f42-build
    → koji wait-repo f42-build --timeout=1800

11. builder.py собирает target
    → koji build f42-candidate python-requests-2.31.0-1.fc42.src.rpm
    → COMPLETE

12. cli.py выводит результат:
    BUILD SUMMARY
    Built:  4 packages
    Failed: 0
    Time:   8m 42s
```

---

## 5. CLI — все команды с примерами

### Синтаксис

```bash
# Формат 1: таргет из ~/.koji/config
vibebuild [OPTIONS] SRPM

# Формат 2: таргет явно
vibebuild [OPTIONS] TARGET SRPM

# SRPM может быть:
#   - путь к файлу:  ./my-package-1.0-1.fc42.src.rpm
#   - имя пакета:    python-requests (будет скачан из Fedora)
```

### Режимы работы

```bash
# Полная сборка
vibebuild f42-candidate python-requests

# Только анализ зависимостей
vibebuild --analyze-only python-requests.src.rpm

# Только скачать SRPM из Fedora
vibebuild --download-only python-requests

# Показать план сборки
vibebuild --dry-run f42-candidate python-requests
```

### Полезные флаги

```bash
# Scratch-сборка (не тегируется)
vibebuild --scratch f42-candidate python-requests

# Не ждать завершения сборки
vibebuild --nowait f42-candidate python-requests

# Пропустить разрешение зависимостей
vibebuild --no-deps f42-candidate my-package.src.rpm

# Подробный вывод
vibebuild --verbose f42-candidate python-requests

# Тихий режим
vibebuild --quiet f42-candidate python-requests
```

### Настройки подключения

```bash
# Свой Koji-сервер
vibebuild --server https://my-koji/kojihub f42-candidate pkg.src.rpm

# Клиентский сертификат
vibebuild --cert ~/.koji/client.pem f42-candidate pkg.src.rpm

# Указать build-тег явно
vibebuild --build-tag f42-build f42-candidate pkg.src.rpm

# Версия Fedora для скачивания SRPM
vibebuild --fedora-release 41 f42-candidate pkg.src.rpm
```

### ML-модель

```bash
# Использовать кастомную модель
vibebuild --ml-model ./my-model.joblib f42-candidate pkg.src.rpm

# Отключить ML (только rule-based)
vibebuild --no-ml f42-candidate pkg.src.rpm

# Отключить всё разрешение имён
vibebuild --no-name-resolution f42-candidate pkg.src.rpm
```

---

## 6. Конфигурация

### ~/.koji/config

Основной конфиг. Живёт в домашней директории пользователя.

```ini
[koji]
# Адрес Koji Hub (XML-RPC endpoint)
server = https://my-koji.example.com/kojihub

# Веб-интерфейс
weburl = https://my-koji.example.com/koji

# Клиентский SSL-сертификат
cert = ~/.koji/client.pem

# CA сертификат сервера
serverca = ~/.koji/serverca.crt

# Таргет по умолчанию
target = f42-candidate

# Build-тег
build_tag = f42-build
```

### Сертификаты

Koji использует SSL-клиентские сертификаты для аутентификации:

- **client.pem** — личный сертификат (выдаётся администратором Koji)
- **serverca.crt** — CA-сертификат сервера

```
~/.koji/
  ├── config          -- конфиг (текстовый)
  ├── client.pem      -- личный сертификат
  └── serverca.crt    -- CA сервера
```

### Приоритет настроек

```
CLI-флаги (--server, --cert, ...)   <-- наивысший приоритет
    ↓
~/.koji/config                       <-- пользовательский конфиг
    ↓
/etc/koji.conf                       <-- системный конфиг (фоллбэк)
```

---

## 7. Первая сборка: пошагово

Самый быстрый путь — поднять локальный Koji в Docker и собрать пакет.

### Шаг 1. Установка

```bash
# Склонируйте репозиторий проекта, затем:
pip install -e ".[dev,ml]"
```

Системные зависимости (Fedora/RHEL):

```bash
sudo dnf install -y koji rpm-build rpm2cpio
```

### Шаг 2. Локальный Koji

```bash
cd dev/koji-server
make setup
```

Через несколько минут:

- Hub: <https://localhost:8443/kojihub>
- Web: <https://localhost:8443/koji>
- `~/.koji/config` уже создан скриптом

Проверка:

```bash
koji list-tags
koji list-hosts
koji list-targets
```

Подробнее — см. `docs/DEPLOYMENT.md`, раздел «Локальная разработка».

### Шаг 3. Первая сборка

Простейший пример — пакет с минимумом зависимостей:

```bash
# Анализ зависимостей пакета (без сборки)
vibebuild --analyze-only python-six

# Показать план сборки
vibebuild --dry-run python-six

# Реальная сборка
vibebuild python-six
```

VibeBuild сам скачает SRPM из Fedora, посчитает недостающие зависимости и соберёт всё в правильном порядке.

### Шаг 4. Что смотреть в Web UI

Откройте <https://localhost:8443/koji>:

- **Tasks** — все задачи сборки
- **Builds** — успешно собранные пакеты
- **Tags** — список тегов и пакетов в каждом теге
- **Hosts** — статус builder'ов

Когда сборка завершится — пакеты появятся в `/mnt/koji/packages/` (внутри контейнера) и будут видны в Web UI.

### Шаг 5. Что делать, если упало

```bash
# Логи всех контейнеров
cd dev/koji-server && make logs

# Логи конкретного контейнера
docker compose logs koji-builder

# Полный сброс
make clean && make setup
```

Типичные проблемы и решения — в `docs/DEPLOYMENT.md`.

---

## 8. Глоссарий

| Термин | Что это |
|--------|--------|
| **RPM** | Red Hat Package Manager — формат пакетов в Fedora/RHEL/CentOS |
| **SRPM** | Source RPM — исходный пакет, из которого собирается бинарный RPM |
| **spec-файл** | Рецепт сборки пакета (.spec), содержит метаданные, зависимости, инструкции |
| **BuildRequires** | Зависимости для СБОРКИ пакета (не для запуска) |
| **Requires** | Зависимости для ЗАПУСКА пакета |
| **Koji** | Централизованная система сборки RPM-пакетов |
| **Koji Hub** | Центральный сервер Koji |
| **Koji Builder** | Машина, которая реально собирает пакеты |
| **Mock** | Инструмент для создания чистого окружения сборки (chroot) |
| **Tag** | Метка для группы пакетов в Koji (например, `f42-build`) |
| **Target** | Пара: destination tag + build tag |
| **Build tag** | Тег, из которого Builder берёт зависимости |
| **Destination tag** | Тег, куда попадает собранный пакет |
| **Virtual provide** | Виртуальное имя зависимости (`python3dist(X)`, `pkgconfig(X)`) |
| **DAG** | Directed Acyclic Graph — направленный ациклический граф зависимостей |
| **Topological sort** | Линейный порядок вершин DAG, учитывающий зависимости |
| **Repo regeneration** | Пересоздание YUM/DNF репозитория после добавления новых пакетов |
| **NVR** | Name-Version-Release — уникальный идентификатор сборки (`python-requests-2.31.0-1.fc42`) |
| **Scratch build** | Тестовая сборка, результат не тегируется |
| **TF-IDF** | Term Frequency — Inverse Document Frequency, метод превращения текста в вектор |
| **KNN** | K-Nearest Neighbors — алгоритм поиска ближайших соседей |
| **XML-RPC** | Протокол удалённого вызова процедур, используется Koji API |

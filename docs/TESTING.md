# Руководство по тестированию

Руководство по тестированию VibeBuild.

## Содержание

- [Запуск тестов](#запуск-тестов)
- [Структура тестов](#структура-тестов)
- [Написание тестов](#написание-тестов)
- [Мокирование](#мокирование)
- [Покрытие кода](#покрытие-кода)

---

## Запуск тестов

### Установка зависимостей

```bash
pip install -e ".[dev]"
```

### Запуск всех тестов

```bash
pytest
```

### Запуск с подробным выводом

```bash
pytest -v
```

### Запуск конкретного файла

```bash
pytest tests/test_analyzer.py
```

### Запуск конкретного теста

```bash
pytest tests/test_analyzer.py::test_get_build_requires
```

### Тесты разрешения имён

```bash
# Все тесты name resolver (49 тестов)
pytest tests/test_name_resolver.py -v

# Все тесты ML resolver (26 тестов, требуется scikit-learn)
pytest tests/test_ml_resolver.py -v

# Оба вместе
pytest tests/test_name_resolver.py tests/test_ml_resolver.py -v
```

### Запуск по маркерам

```bash
# Только юнит-тесты
pytest -m unit

# Только интеграционные тесты
pytest -m integration
```

### Ручная / E2E-проверка (опционально)

С `koji` CLI и доступом к Fedora Koji можно проверить полный цикл:

```bash
vibebuild --version
vibebuild --help
vibebuild --download-only python-requests
vibebuild --dry-run fedora-43 python-requests   # имя пакета: скачать, показать план сборки
```

Полный сценарий демонстрации (сборка одной командой по имени, анализ, dry-run, сборка) — см. [DEMO.md](../DEMO.md).

---

## Структура тестов

```
tests/
├── conftest.py              # Общие фикстуры
├── fixtures/                # Тестовые данные
│   ├── test-package.spec
│   └── test-package.src.rpm
├── test_analyzer.py         # Тесты анализатора
├── test_resolver.py         # Тесты резолвера
├── test_fetcher.py          # Тесты загрузчика
├── test_builder.py          # Тесты сборщика
├── test_cli.py              # Тесты CLI
├── test_name_resolver.py    # Тесты резолвера имён (49 тестов, 9 классов)
├── test_ml_resolver.py      # Тесты ML-резолвера (26 тестов, 7 классов)
└── integration/             # Интеграционные тесты
    └── test_e2e.py
```

### test_name_resolver.py (49 тестов)

Тесты для `PackageNameResolver` на основе правил:

| Класс | Кол-во | Что тестируется |
|---|---|---|
| `TestPackageNameResolverVirtualProvides` | 11 | Все 9 паттернов provides (python3dist, pkgconfig, perl, rubygem, npm, golang, tex, mvn, cmake) + крайние случаи |
| `TestPackageNameResolverMacros` | 6 | Раскрытие макросов: `%{python3_pkgversion}`, условные `%{?...}`, неизвестные макросы, множественные макросы |
| `TestPackageNameResolverPlainNames` | 3 | Прямая передача простых имён типа `gcc`, пустые строки |
| `TestPackageNameResolverSRPMNames` | 9 | Маппинг имён SRPM: python3-X, python2-X, -devel, -libs, perl-, rubygem-, nodejs-, golang- |
| `TestPackageNameResolverCaching` | 3 | Поведение кэша в памяти |
| `TestPackageNameResolverMLFallback` | 7 | Интеграция с ML: вызов для неразрешённых provides, пропуск при совпадении правил, обработка ошибок, плавная деградация |
| `TestSystemMacros` | 5 | Проверка записей SYSTEM_MACROS |
| `TestProvidePatterns` | 2 | Проверка структуры PROVIDE_PATTERNS |
| `TestResolveVirtualProvide` | 3 | Прямой вызов `resolve_virtual_provide()` |

### test_ml_resolver.py (26 тестов)

Тесты для ML-резолвера `MLPackageResolver`:

| Класс | Кол-во | Что тестируется |
|---|---|---|
| `TestMLPackageResolverInstantiation` | 2 | Конструктор с/без пути к модели |
| `TestMLPackageResolverTrain` | 3 | Обучение на примерных данных, ошибка при пустых данных, проверка словаря |
| `TestMLPackageResolverPredict` | 6 | Точные совпадения (python3dist, pkgconfig, perl), мусорный ввод возвращает None, недоступная модель |
| `TestMLPackageResolverSaveLoad` | 5 | Цикл сохранения/загрузки, создание каталога, обработка ошибок |
| `TestMLPackageResolverIsAvailable` | 3 | Доступность после обучения, без модели, после загрузки |
| `TestMLPackageResolverCache` | 5 | Кэширование предсказаний, сохранение на диск, обработка повреждённого файла |
| `TestMLPackageResolverWithoutSklearn` | 2 | Мок `HAS_SKLEARN=False`: ошибка обучения, проверка доступности |

---

## Написание тестов

### Стиль

Используйте паттерн AAA (Arrange-Act-Assert):

```python
def test_get_build_requires_extracts_packages():
    srpm_path = "tests/fixtures/test-package.src.rpm"

    result = get_build_requires(srpm_path)

    assert isinstance(result, list)
    assert "python3-devel" in result
```

### Соглашение по именованию

```python
def test_<что>_<условие>_<ожидаемый_результат>():
    # test_get_build_requires_with_valid_srpm_returns_list
    # test_analyze_spec_with_missing_name_raises_error
    pass
```

### Маркеры

```python
import pytest

@pytest.mark.unit
def test_unit_example():
    pass

@pytest.mark.integration
def test_integration_example():
    pass

@pytest.mark.slow
def test_slow_example():
    pass
```

---

## Фикстуры

### conftest.py

```python
import pytest
from pathlib import Path

@pytest.fixture
def fixtures_dir():
    return Path(__file__).parent / "fixtures"

@pytest.fixture
def sample_spec(fixtures_dir):
    return fixtures_dir / "test-package.spec"

@pytest.fixture
def sample_srpm(fixtures_dir):
    return fixtures_dir / "test-package.src.rpm"

@pytest.fixture
def mock_koji_client(mocker):
    """Мок KojiClient для тестов без реального Koji."""
    client = mocker.Mock()
    client.list_packages.return_value = ["python3", "gcc", "make"]
    client.package_exists.return_value = True
    return client
```

### Использование фикстур

```python
def test_analyzer_with_fixture(sample_spec):
    analyzer = SpecAnalyzer()

    result = analyzer.analyze_spec(str(sample_spec))

    assert result.name == "test-package"
```

---

## Мокирование

### Мок subprocess

```python
def test_koji_build_command(mocker):
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "Created task: 12345"

    builder = KojiBuilder()
    task = builder.build_package("test.src.rpm")

    assert task.task_id == 12345
    mock_run.assert_called_once()
```

### Мок requests

```python
def test_download_srpm_from_koji(mocker):
    mocker.patch("subprocess.run").return_value.returncode = 0

    fetcher = SRPMFetcher(download_dir="/tmp/test")

    # ... логика теста
```

### Мок ML-резолвера

```python
def test_resolve_with_ml_fallback(mocker):
    """Тест: ML-резолвер вызывается для неразрешённых виртуальных provides."""
    mock_ml = mocker.Mock()
    mock_ml.predict.return_value = "custom-package"

    resolver = PackageNameResolver(ml_resolver=mock_ml)
    result = resolver.resolve("unknown_provider(something)")

    mock_ml.predict.assert_called_once_with("unknown_provider(something)")
    assert result == "custom-package"


def test_resolve_ml_not_called_when_rules_match(mocker):
    """Тест: ML пропускается, когда правила успешно разрешают имя."""
    mock_ml = mocker.Mock()

    resolver = PackageNameResolver(ml_resolver=mock_ml)
    result = resolver.resolve("python3dist(requests)")

    mock_ml.predict.assert_not_called()
    assert result == "python3-requests"
```

### Мок файловой системы

```python
def test_analyze_spec_file_not_found(tmp_path):
    analyzer = SpecAnalyzer()

    with pytest.raises(FileNotFoundError):
        analyzer.analyze_spec(str(tmp_path / "nonexistent.spec"))
```

---

## Примеры тестов

### test_analyzer.py

```python
import pytest
from vibebuild.analyzer import SpecAnalyzer, get_build_requires
from vibebuild.exceptions import InvalidSRPMError, SpecParseError


class TestSpecAnalyzer:
    def test_analyze_spec_extracts_name(self, sample_spec):
        analyzer = SpecAnalyzer()

        result = analyzer.analyze_spec(str(sample_spec))

        assert result.name == "test-package"

    def test_analyze_spec_extracts_version(self, sample_spec):
        analyzer = SpecAnalyzer()

        result = analyzer.analyze_spec(str(sample_spec))

        assert result.version == "1.0"

    def test_analyze_spec_extracts_build_requires(self, sample_spec):
        analyzer = SpecAnalyzer()

        result = analyzer.analyze_spec(str(sample_spec))

        assert len(result.build_requires) > 0

    def test_analyze_spec_raises_on_missing_file(self):
        analyzer = SpecAnalyzer()

        with pytest.raises(FileNotFoundError):
            analyzer.analyze_spec("/nonexistent/path.spec")

    def test_analyze_spec_raises_on_invalid_spec(self, tmp_path):
        invalid_spec = tmp_path / "invalid.spec"
        invalid_spec.write_text("invalid content")
        analyzer = SpecAnalyzer()

        with pytest.raises(SpecParseError):
            analyzer.analyze_spec(str(invalid_spec))


class TestGetBuildRequires:
    def test_returns_list(self, sample_srpm):
        result = get_build_requires(str(sample_srpm))

        assert isinstance(result, list)

    def test_raises_on_invalid_srpm(self, tmp_path):
        invalid = tmp_path / "not-an-srpm.txt"
        invalid.write_text("not an srpm")

        with pytest.raises(InvalidSRPMError):
            get_build_requires(str(invalid))
```

### test_resolver.py

```python
import pytest
from vibebuild.resolver import DependencyResolver, KojiClient
from vibebuild.exceptions import CircularDependencyError


class TestDependencyResolver:
    def test_find_missing_deps_returns_missing(self, mock_koji_client):
        mock_koji_client.package_exists.side_effect = lambda p, t: p != "missing-pkg"
        resolver = DependencyResolver(koji_client=mock_koji_client)

        result = resolver.find_missing_deps(["existing-pkg", "missing-pkg"])

        assert "missing-pkg" in result
        assert "existing-pkg" not in result

    def test_topological_sort_detects_cycle(self, mock_koji_client):
        resolver = DependencyResolver(koji_client=mock_koji_client)
        resolver._dependency_graph = {
            "a": Mock(dependencies=["b"], is_available=False),
            "b": Mock(dependencies=["a"], is_available=False),
        }

        with pytest.raises(CircularDependencyError):
            resolver.topological_sort()
```

---

## Покрытие кода

### Запуск с покрытием

```bash
pytest --cov=vibebuild --cov-report=term-missing
```

### HTML-отчёт

```bash
pytest --cov=vibebuild --cov-report=html
open htmlcov/index.html
```

### Минимальное покрытие

```bash
pytest --cov=vibebuild --cov-fail-under=80
```

### Конфигурация в pyproject.toml

```toml
[tool.coverage.run]
source = ["vibebuild"]
branch = true

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "raise NotImplementedError",
    "if __name__ == .__main__.:",
]
```

---

## CI/CD

### GitHub Actions

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.9', '3.10', '3.11', '3.12']

    steps:
    - uses: actions/checkout@v4

    - name: Set up Python
      uses: actions/setup-python@v5
      with:
        python-version: ${{ matrix.python-version }}

    - name: Install dependencies
      run: |
        pip install -e ".[dev]"

    - name: Run tests
      run: |
        pytest --cov=vibebuild --cov-report=xml

    - name: Upload coverage
      uses: codecov/codecov-action@v3
```

---

## Интеграционные тесты

### Требования

Интеграционные тесты требуют:
- Доступ к тестовому серверу Koji
- Тестовые SRPM-файлы

### Пример

```python
# tests/integration/test_e2e.py

import pytest

@pytest.mark.integration
@pytest.mark.slow
class TestEndToEnd:
    @pytest.fixture
    def koji_server(self):
        return "https://test-koji.example.com/kojihub"

    def test_full_build_workflow(self, koji_server, sample_srpm):
        from vibebuild.builder import KojiBuilder

        builder = KojiBuilder(
            koji_server=koji_server,
            scratch=True,  # Scratch-сборка для тестов
        )

        result = builder.build_with_deps(str(sample_srpm))

        assert result.success
```

### Запуск интеграционных тестов

```bash
# Только юнит-тесты (по умолчанию)
pytest -m "not integration"

# Включая интеграционные тесты
pytest -m "integration"

# Все тесты
pytest
```

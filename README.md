# VibeBuild

**Расширение Koji для автоматического разрешения зависимостей и сборки**

[![CI](https://github.com/GrimVo1d/Koji-VibeBuild/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/GrimVo1d/Koji-VibeBuild/actions/workflows/test.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](https://www.python.org/downloads/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Conventional Commits](https://img.shields.io/badge/Conventional%20Commits-1.0.0-yellow.svg)](https://www.conventionalcommits.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

VibeBuild расширяет функциональность Koji, добавляя автоматическое разрешение зависимостей. При сборке пакета VibeBuild автоматически находит недостающие BuildRequires, скачивает их SRPM из Fedora и собирает всю цепочку зависимостей в правильном порядке.

## Возможности

- **Автоматический анализ зависимостей** — парсинг SRPM/spec-файлов для извлечения BuildRequires
- **Умное разрешение имён пакетов** — автоматическое преобразование виртуальных provides (`python3dist(requests)`, `pkgconfig(glib-2.0)`, `perl(File::Path)`) и RPM-макросов (`%{python3_pkgversion}`) в реальные имена пакетов
- **ML-разрешение имён** — опциональная модель scikit-learn (TF-IDF + KNN) как запасной вариант, когда правила не срабатывают
- **Скачивание SRPM** — автоматическое скачивание недостающих пакетов из Fedora Koji с умным маппингом имён SRPM (например, `python3-requests` -> `python-requests`)
- **Построение DAG** — определение порядка сборки на основе зависимостей
- **Оркестрация сборки** — последовательная сборка с ожиданием регенерации репозитория
- **CLI-интерфейс** — удобный инструмент командной строки с гибкими опциями

## Быстрый старт

### Установка

Склонируйте репозиторий и установите в editable-режиме:

```bash
cd vibebuild
pip install -e ".[dev,ml]"   # разработка + ML целиком
pip install -e ".[dev]"      # без ML
pip install -e ".[ml]"       # только ML, без dev-инструментов
pip install -e .             # минимум
```

### Использование

Базовая форма: `vibebuild [ОПЦИИ] SRPM` или `vibebuild [ОПЦИИ] TARGET SRPM`.
SRPM может быть путём к файлу `.src.rpm` или **именем пакета** (например, `python3`).
Если TARGET не указан, он берётся из ключа `target` в `~/.koji/config [koji]`.

```bash
# Одна команда: target из ~/.koji/config, скачать SRPM по имени и собрать
vibebuild python-requests
vibebuild python3

# Явное указание target (или если target не в конфиге)
vibebuild fedora-target python-requests
vibebuild fedora-target my-package-1.0-1.fc40.src.rpm

# Scratch-сборка (без тегирования)
vibebuild --scratch fedora-target my-package.src.rpm

# Сборка без разрешения зависимостей (только один пакет)
vibebuild --no-deps fedora-target my-package.src.rpm

# Анализ зависимостей без сборки (один аргумент: путь к SRPM)
vibebuild --analyze-only my-package.src.rpm

# Скачать SRPM из Fedora по имени пакета (требуется koji CLI)
vibebuild --download-only python-requests

# Пробный запуск — показать порядок сборки и что будет собрано
vibebuild --dry-run my-package.src.rpm

# Опции разрешения имён
vibebuild --no-ml fedora-target my-package.src.rpm              # только правила
vibebuild --no-name-resolution fedora-target my-package.src.rpm # сырые имена
vibebuild --ml-model /path/to/model.joblib fedora-target my-package.src.rpm
```

Пошаговая демонстрация (скачивание, анализ, dry-run, сборка) — см. раздел «Первая сборка: пошагово» в [QUICKSTART.md](docs/QUICKSTART.md#7-первая-сборка-пошагово).

### Проверка

После установки можно убедиться, что всё работает:

```bash
vibebuild --version
vibebuild --help          # краткий список основных опций
vibebuild --help-all      # полный список всех опций
```

Если установлен `[dev]`, запустите тесты из корня проекта:

```bash
pytest
```

Для проверки разрешения зависимостей на реальном пакете (требуется `koji` CLI и доступ к Fedora Koji):

```bash
vibebuild --download-only python-requests
vibebuild --analyze-only python-requests-*.src.rpm   # используем скачанный файл
vibebuild --dry-run python-requests          # target из ~/.koji/config
vibebuild --dry-run fedora-43 python-requests  # явный target
```

Без `koji` используйте любой имеющийся `.src.rpm` для `--analyze-only` и `--dry-run`. См. [TESTING.md](docs/TESTING.md) для запуска тестов.

### Использование со своим Koji-сервером

Если у вас уже есть Koji, `vibebuild` читает `~/.koji/config` (и `/etc/koji.conf`) для получения `server`, `weburl`, `cert` и `serverca`, поэтому часто достаточно передать `--server` для переопределения. Все опции: `vibebuild --help-all`.

```bash
# После настройки ~/.koji/config с target = my-target:
vibebuild my-package.src.rpm

vibebuild --server https://koji.example.com/kojihub my-target my-package.src.rpm
# или с явными сертификатами:
vibebuild --server https://koji.example.com/kojihub --cert ~/.koji/client.pem \
  --serverca ~/.koji/serverca.crt --build-tag my-build my-target my-package.src.rpm
```

## Локальный сервер (Docker)

В репозитории есть готовое Docker-окружение для локальной разработки и тестирования:

```bash
cd dev/koji-server
make setup    # Полная настройка: сертификаты, БД, Hub, Builder, клиент
```

После настройки Koji доступен по адресу https://localhost:8443/koji.


## Развёртывание Koji

В репозитории есть Ansible-плейбук для автоматического развёртывания Koji на Fedora:

```bash
cd ansible

# Настройте inventory (укажите YOUR_VPS_IP и ansible_user)
vim inventory/hosts.ini

# Настройте переменные (FQDN, пароли и т.д.)
vim group_vars/all.yml

# Запустите плейбук
ansible-playbook -i inventory/hosts.ini playbook.yml
```

Подробнее см. [DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Как это работает

```
┌─────────────────┐
│  vibebuild CLI  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ┌─────────────────┐
│   Анализатор    │────▶│  Парсинг SRPM   │
│                 │     │  Извлечение deps │
└────────┬────────┘     └─────────────────┘
         │
         ▼
┌─────────────────┐     ┌─────────────────┐
│   Резолвер имён │────▶│ Раскрытие макр. │
│ (правила + ML)  │     │ Разрешение имён │
└────────┬────────┘     └─────────────────┘
         │
         ▼
┌─────────────────┐     ┌─────────────────┐
│   Резолвер      │────▶│  Проверка Koji  │
│   зависимостей  │     │  Построение DAG │
└────────┬────────┘     └─────────────────┘
         │
         ▼
┌─────────────────┐     ┌─────────────────┐
│   Загрузчик     │────▶│  Скачивание     │
│                 │     │  SRPM из Fedora  │
└────────┬────────┘     └─────────────────┘
         │
         ▼
┌─────────────────┐     ┌─────────────────┐
│   Сборщик       │────▶│  koji build     │
│                 │     │  wait-repo      │
└─────────────────┘     └─────────────────┘
```

1. **Анализатор** — извлекает BuildRequires из SRPM/spec-файла, раскрывает RPM-макросы
2. **Резолвер имён** — преобразует виртуальные provides и имена на основе макросов в реальные имена RPM-пакетов (правила + опциональный ML)
3. **Резолвер зависимостей** — проверяет, какие зависимости отсутствуют в Koji, и строит граф зависимостей
4. **Загрузчик** — скачивает SRPM для недостающих пакетов из Fedora с умным маппингом имён
5. **Сборщик** — собирает пакеты в правильном порядке, ожидая регенерацию репозитория между сборками

## Обучение ML-модели (опционально)

VibeBuild включает скрипты для обучения ML-модели разрешения имён пакетов:

```bash
# 1. Сбор обучающих данных из репозиториев Fedora
python scripts/collect_training_data.py --output data/training_data.json

# 2. Обучение модели (алиасы из vibebuild/data/alias_training.json подмешиваются автоматически)
python scripts/train_model.py --input data/training_data.json --output vibebuild/data/model.joblib
```

Модель использует TF-IDF символьные n-граммы с K-Nearest Neighbors для предсказания реальных имён пакетов из строк виртуальных зависимостей. Обучение автоматически подмешивает алиасы из `vibebuild/data/alias_training.json` (например, `python3` → `python3.12`), чтобы команды вроде `vibebuild --download-only python3` работали при установленной модели. Используйте `--ml-model` для указания пользовательской модели. Подробнее см. [DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Требования

- **Python** 3.9+
- **koji** CLI — требуется для `--download-only` (скачивание SRPM из Fedora Koji) и для сборки. Без него эти функции недоступны. Установка: `sudo dnf install koji` (Fedora) или эквивалент для вашего дистрибутива.
- **rpm-build**, **rpm2cpio** (для распаковки и сборки SRPM; на Fedora: `dnf install rpm-build`)
- Доступ к серверу Koji (например, Fedora Koji для скачивания; собственный для сборки)

**Опционально (ML-разрешение имён):** `scikit-learn >= 1.3`, `joblib >= 1.3` — установка: `pip install -e ".[ml]"`.

## Документация

- [QUICKSTART.md](docs/QUICKSTART.md) — введение с нуля: понятия RPM/SRPM/Koji, модули, первая сборка пошагово
- [ARCHITECTURE.md](docs/ARCHITECTURE.md) — архитектура системы
- [DEPLOYMENT.md](docs/DEPLOYMENT.md) — руководство по развёртыванию
- [TESTING.md](docs/TESTING.md) — руководство по тестированию

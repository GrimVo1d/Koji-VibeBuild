# Production runbook

Этот документ — короткий чек-лист «как поднять и эксплуатировать vibebuild
в проде». Дополняет `ARCHITECTURE.md` (общая архитектура) и `DEPLOYMENT.md`
(локальный dev-стек).

## Требования

- Linux x86_64 (Fedora 40+ или RHEL/CentOS Stream/Alma 9+).
  **macOS только для разработки** — mock-сборка через Docker Desktop работает
  частично (см. `DEPLOYMENT.md`, секция «Известные ограничения»).
- Python 3.9–3.12
- `rpm`, `rpm-build`, `cpio` — для парсинга и распаковки SRPM
- `koji` CLI клиент — для submit-команд (`koji build`)
- Доступ к Koji-хабу (XML-RPC по HTTPS, обычно `:443`)
- Опционально для ML: `scikit-learn>=1.3`, `joblib>=1.3`

## Установка

```bash
git clone <repo>
cd koji-vibebuild
pip install -e ".[dev,ml]"          # для разработчиков
pip install ".[ml]"                  # для эксплуатации
```

## Первый запуск

```bash
vibebuild --version
vibebuild --analyze-only path/to/hello.src.rpm
```

## Аутентификация в Koji

vibebuild читает `~/.koji/config` (формат стандартный для koji-CLI). Минимум:

```
[koji]
server = https://koji.example.com/kojihub
weburl = https://koji.example.com/koji
topurl = https://koji.example.com/kojifiles
cert = /path/to/your.pem
serverca = /path/to/koji_ca.crt
authtype = ssl
target = fXX
```

## Ключевые CLI-флаги

| Флаг | Описание |
|------|----------|
| `--analyze-only` | Только разбор SRPM, без сборки |
| `--download-only` | Только скачать SRPM (и его зависимости) |
| `--dry-run` | Построить DAG и показать план, не submit'ить |
| `--scratch` | Scratch-сборка (без тегирования) |
| `--no-deps` | Пропустить рекурсивный resolve зависимостей |
| `--force` | Пересобрать, даже если идентичный NVR уже есть в теге |
| `--no-idempotency` | Отключить pre-check «уже собрано» |
| `--log-format=json` | JSON-логи для prod-парсеров (rsyslog/loki/elastic) |
| `--no-ml` | Не использовать ML-резолвер даже если модель доступна |
| `-v`, `-q` | Verbose / quiet логирование |

## Exit codes

| Code | Смысл |
|------|-------|
| 0 | Успех |
| 1 | Generic error (см. лог) |
| 2 | Неверные аргументы / конфиг |

(Расширение схемы exit codes — задача отдельного релиза. На текущем — `0`
успех, любой ненулевой = ошибка с подробностями в логах.)

## ML-резолвер

ML-резолвер заполняет пробелы rule-based-резолва для экзотических provides
(`tex(...)`, `crate(...)`, `cmake(...)` и т.п.). Модель хранится в
`vibebuild/data/model.joblib` (~290 MB) и **в репозиторий не коммитится**.

Обучение из реального Fedora-каталога:

```bash
vibebuild train --release 42 --output vibebuild/data/model.joblib
```

Метрики последнего прогона — в `docs/ML_METRICS.md`.

## Производственная конфигурация

### Логирование

```bash
vibebuild --log-format=json ... 2>> /var/log/vibebuild.log
```

Каждая строка — валидный JSON с полями `timestamp/level/module/message`.

### Idempotency

По умолчанию vibebuild **пропускает** сборки, если в target-теге уже есть
идентичный NVR. Это исключает повторное submit'ы при перезапуске cron-job
или ручного повтора. Пропуск выключается флагом `--no-idempotency` или
`--force`.

### Retry

vibebuild автоматически повторяет koji-команды и HTTP-загрузки SRPM при
transient-ошибках (connection reset, 503, timeout). Программные ошибки
(битый SRPM, отсутствие пакета в теге) — без retry, fail-fast.

### Производительность

- `vibebuild --analyze-only` без неизвестных provides — **не грузит ML-модель**
  (lazy load экономит ~3 сек startup + ~600 MB RAM).
- Spec cache: повторный analyze того же SRPM — `~3 ms` против `~45 ms` cold.
- Polling adaptive: короткие сборки реагируют за 2 сек, длинные — за 30 сек
  (баланс между latency и нагрузкой на Koji).
- SRPM-зависимости качаются параллельно (5 одновременных потоков).

Подробные числа — в `docs/PERF.md`.

## Что НЕ покрыто этой итерацией (известные ограничения)

1. **Реальная mock-сборка** в наш dev/koji-server на macOS+Docker Desktop
   уходит в `+waitrepo` из-за специфики Docker Desktop. На настоящем Linux-хосте
   submit→build→tagged-build проходит. **Перед prod-релизом — ручная проверка
   на Linux-VM**: `vibebuild --scratch <target> hello.src.rpm`, увидеть `.rpm`
   в `/mnt/koji/scratch`.
2. **Версионные constraints в resolver** реализованы только для `>=`, `>`,
   `=`, `<=`, `<`. Сложные выражения с `&&`, `||`, конъюнкциями BR — упрощаются
   до проверки имени.
3. **Resume после прерывания**: на текущем уровне vibebuild не ведёт persistent
   state-файла. Перезапуск идёт с нуля. Idempotency пропустит уже-собранные
   пакеты, но прогресс цепочки в середине не восстанавливается.

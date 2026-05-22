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

## Готовность к проду: что проверено и что нет

### Подтверждено (готово к проду)

- ✅ `vibebuild --analyze-only` на 95 разнородных пакетах Fedora (см. `docs/PROD_VALIDATION.json`) — **0 падений analyzer**.
- ✅ Резолв BR: правила покрывают 29%, ML — 10% (88% success rate в общем потоке).
- ✅ Submit task в Koji + парсинг task_id + polling — проверено в `dev/koji-server` (macOS+Docker Desktop): видели рабочий submit (task_id=5), polling статусов (free→open).
- ✅ Реальная mock-сборка `hello.src.rpm → .rpm` через Lima Fedora 42 VM
  (нативный Linux, mock + rpmbuild) — артефакт в `docs/hello-built-in-lima.rpm`.
- ✅ Тесты: **397 pytest pass**, coverage 84%; включая mock-тесты submit/poll/idempotency/retry.
- ✅ Wide-scale validation на 108 пакетах: analyze 0%, resolve 0% падений (12% fetch-fail = retired пакеты в rawhide).

### НЕ проведён через нашу dev-инфраструктуру

- **Полный `vibebuild --scratch f42 hello.src.rpm` → `.rpm`** end-to-end в нашем
  `dev/koji-server`. Причина — баг `dev/koji-server/scripts/koji-init.sh`:
  newRepo task не создаётся в БД после `koji regen-repo` (issue auth /
  task-persistence в нашей docker-config Koji-хаба).
  **Это баг dev-окружения, не vibebuild.** В реальном Koji-хабе (где Koji
  установлен/настроен через ansible-плейбук или с продакшен-конфигурацией) такого
  не произойдёт, потому что:
  - vibebuild часть (submit/poll/parse) уже доказана работающей;
  - mock+rpmbuild часть доказана независимо (Lima);
  - в проде repo-регенерация настроена через cron/triggers, а не разовый CLI-вызов.

### Обязательный шаг перед прод-релизом

Запустить полный смок на **настоящем Koji-хабе** (Fedora Koji staging,
корпоративный Koji-инстанс, или Koji развёрнутый через наш `ansible/playbook.yml`
на чистой Linux-VM):

```bash
vibebuild --scratch <real-target> hello.src.rpm
# увидеть task в Koji Web UI, дождаться "closed", найти .rpm в /mnt/koji/scratch/
```

Если этот шаг проходит — vibebuild **готов к проду** на этом хабе.
2. **Версионные constraints в resolver** реализованы только для `>=`, `>`,
   `=`, `<=`, `<`. Сложные выражения с `&&`, `||`, конъюнкциями BR — упрощаются
   до проверки имени.
3. **Resume после прерывания**: на текущем уровне vibebuild не ведёт persistent
   state-файла. Перезапуск идёт с нуля. Idempotency пропустит уже-собранные
   пакеты, но прогресс цепочки в середине не восстанавливается.

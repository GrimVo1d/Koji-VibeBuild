# Развёртывание и установка VibeBuild

Документ покрывает два сценария:

1. **Локальная разработка** — поднятие Koji-сервера в Docker через `dev/koji-server/`
2. **Деплой на VPS** — продакшен-установка через Ansible или вручную

## Содержание

- [Локальная разработка](#локальная-разработка)
  - [Требования](#требования-локально)
  - [Быстрый старт](#быстрый-старт-локально)
  - [Что происходит при setup](#что-происходит-при-setup)
  - [Управление сервером](#управление-сервером)
  - [Проверка работоспособности](#проверка-работоспособности-локально)
  - [Конфигурация контейнеров](#конфигурация-контейнеров)
  - [Устранение неполадок (локально)](#устранение-неполадок-локально)
- [Деплой на VPS](#деплой-на-vps)
  - [Требования к серверу](#требования-к-серверу)
  - [Выбор и заказ VPS](#выбор-и-заказ-vps)
  - [Первоначальная настройка](#первоначальная-настройка-сервера)
  - [Установка Koji через Ansible](#установка-koji-через-ansible-рекомендуется)
  - [Ручная установка Koji](#ручная-установка-koji)
  - [Настройка клиента VibeBuild](#настройка-клиента-vibebuild)
  - [Настройка ML-модели](#настройка-ml-модели-опционально)
  - [Проверка и мониторинг](#проверка-и-мониторинг)
  - [Устранение неполадок (VPS)](#устранение-неполадок-vps)
  - [Резервное копирование и обновление](#резервное-копирование-и-обновление)

---

## Локальная разработка

Для разработки и тестирования VibeBuild можно поднять полноценный Koji-сервер на локальной машине в Docker. Конфигурация лежит в `dev/koji-server/`.

### Требования (локально)

- **Docker** и **Docker Compose** (v2+)
- **koji CLI** — `sudo dnf install koji` (Fedora) или эквивалент
- **RAM:** минимум 4 ГБ (рекомендуется 8 ГБ)
- **Диск:** ~5 ГБ для контейнеров и данных
- **Сеть:** доступ к интернету (для скачивания образов и пакетов из Fedora-репозиториев)

### Быстрый старт (локально)

```bash
cd dev/koji-server
make setup
```

После завершения:

- Веб-интерфейс Koji: <https://localhost:8443/koji>
- API: <https://localhost:8443/kojihub>
- Проверка: `koji --noauth list-tags`

### Запуск vibebuild внутри Docker (рекомендация для macOS)

В `docker-compose.yml` поднимается сервис `vibebuild-dev` (Fedora 42 + `rpm`,
`koji`, `python3`, `scikit-learn`, vibebuild установлен в editable-режиме из
смонтированного `/workspace`). Это избавляет от установки rpm/koji на хост:

```bash
docker compose exec vibebuild-dev bash
# внутри:
vibebuild --analyze-only path/to/some.src.rpm
vibebuild --server https://koji-hub/kojihub --download-only f42 python-requests
vibebuild train --release 42       # обучить ML-резолвер
```

### Известные ограничения локального Koji-стека

- **На macOS / Docker Desktop scratch-сборка может зависнуть на `+waitrepo`**:
  initial repo для `f42-build` иногда не регенерируется автоматически после
  `koji-init.sh`. Если задача `waitrepo` зависла >5 минут — запустить вручную:
  `docker compose exec vibebuild-dev koji regen-repo f42-build` и подождать.
- Реальная mock-сборка отлажена под наш self-signed CA (см. `koji-builder/Dockerfile`,
  `ssl_extra_certs` в `/etc/mock/site-defaults.cfg`), но dnf-метаданные внутри
  chroot всё равно требуют рабочего интернета из koji-builder-контейнера для
  скачивания внешних пакетов F42.

### Что происходит при setup

#### 1. Генерация SSL-сертификатов (`make certs`)

Скрипт `scripts/generate-certs.sh` создаёт в каталоге `ssl/`:

- **CA** — корневой сертификат (`koji_ca_cert.crt`)
- **Hub** — серверный сертификат для Apache (`kojihub.pem`)
- **Web** — сертификат для Koji Web (`kojiweb.pem`)
- **Admin** — клиентский сертификат администратора (`kojiadmin.pem`)
- **Builder** — сертификат для демона сборки (`kojibuilder.pem`)

Все сертификаты выпускаются на 10 лет с SAN для `localhost` и `koji-hub`.

#### 2. Запуск БД и Hub

```bash
docker compose up -d --build db koji-hub
```

- **db** — PostgreSQL 16 (Alpine), хранит метаданные Koji
- **koji-hub** — Fedora 42 с Apache + mod_wsgi, Koji Hub и Koji Web

Hub-контейнер при первом запуске автоматически импортирует схему БД из `/usr/share/koji/schema.sql`.

#### 3. Инициализация Koji (`make init`)

Скрипт `scripts/koji-init.sh`:

- Ждёт готовности Hub (до 60 секунд)
- Создаёт пользователя `kojiadmin` с правами администратора
- Добавляет хост-сборщик `kojibuilder` (архитектура x86_64)
- Создаёт теги: `f42`, `f42-build`
- Создаёт цель сборки: `f42` (build_tag=`f42-build`, dest_tag=`f42`)
- Настраивает группы сборки (`build`, `srpm-build`) с базовыми пакетами (gcc, make, rpm-build и др.)
- Подключает внешние репозитории Fedora 42 (releases + updates)
- Запускает регенерацию репозитория

#### 4. Запуск Builder

```bash
docker compose up -d koji-builder
```

Контейнер `koji-builder` на Fedora 42 с mock, koji-builder и createrepo_c. Запускает демон `kojid`, который подключается к Hub и ждёт задач на сборку.

#### 5. Настройка клиента (`make client`)

Скрипт `scripts/setup-client.sh` создаёт `~/.koji/config`:

```ini
[koji]
server = https://localhost:8443/kojihub
weburl = https://localhost:8443/koji
topurl = https://localhost:8443/kojifiles
cert = <путь>/ssl/kojiadmin.pem
serverca = <путь>/ssl/koji_ca_cert.crt
authtype = ssl
target = f42
build_tag = f42-build
```

Если `~/.koji/config` уже существует, создаётся резервная копия.

### Управление сервером

Все команды запускаются из `dev/koji-server/`.

| Команда | Описание |
|---------|----------|
| `make setup` | Полная установка с нуля |
| `make stop` | Остановить все контейнеры |
| `make logs` | Показать логи всех контейнеров |
| `make clean` | Удалить контейнеры, тома и сертификаты |
| `make certs` | Перегенерировать SSL-сертификаты |
| `make init` | Повторная инициализация Koji |
| `make client` | Пересоздать конфигурацию клиента |

### Проверка работоспособности (локально)

```bash
# Список тегов (без аутентификации)
koji --noauth list-tags

# Список тегов (с аутентификацией)
koji list-tags

# Статус сборщика
koji list-hosts

# Информация о цели
koji list-targets
```

Веб-интерфейс: <https://localhost:8443/koji>. Браузер покажет предупреждение о самоподписанном сертификате — это нормально для локальной разработки.

**Установка VibeBuild и тестовая сборка:**

```bash
# Из корня репозитория
pip install -e ".[dev,ml]"

# Сборка пакета по имени (скачает SRPM из Fedora, разрешит зависимости, соберёт)
vibebuild python-requests

# Сборка локального SRPM
vibebuild my-package-1.0-1.fc42.src.rpm

# Анализ зависимостей (без сборки)
vibebuild --analyze-only my-package.src.rpm

# Показать план сборки (без реального запуска)
vibebuild --dry-run python-requests
```

Target (`f42`) и параметры подключения берутся из `~/.koji/config`, созданного при `make client`.

### Конфигурация контейнеров

**Переменные окружения** — `dev/koji-server/.env`:

| Переменная | По умолчанию | Описание |
|-----------|-------------|----------|
| `POSTGRES_USER` | `koji` | Пользователь PostgreSQL |
| `POSTGRES_PASSWORD` | `kojisecret` | Пароль PostgreSQL |
| `POSTGRES_DB` | `koji` | Имя БД |
| `KOJI_FQDN` | `localhost` | Доменное имя |
| `KOJI_HTTPS_PORT` | `8443` | HTTPS-порт Hub |
| `KOJI_TAG` | `f42` | Основной тег |
| `KOJI_BUILD_TAG` | `f42-build` | Тег сборки |
| `KOJI_TARGET` | `f42` | Цель сборки |

Изменение порта — отредактировать `KOJI_HTTPS_PORT` и пересоздать окружение:

```bash
make clean
make setup
```

**Контейнеры:**

| Контейнер | Образ | Описание |
|-----------|-------|----------|
| `db` | `postgres:16-alpine` | База данных |
| `koji-hub` | Fedora 42 (собирается) | Koji Hub + Web + Apache |
| `koji-builder` | Fedora 42 (собирается) | kojid + mock |

**Тома:**

| Том | Назначение |
|-----|-----------|
| `koji-db-data` | Данные PostgreSQL |
| `koji-data` | Пакеты и репозитории (`/mnt/koji`) |

### Устранение неполадок (локально)

**Hub не запускается:**

```bash
make logs
docker compose ps
ss -tlnp | grep 8443
```

**Builder в статусе offline:**

```bash
docker compose logs koji-builder
docker compose exec koji-builder curl -sk https://koji-hub/kojihub
docker compose restart koji-builder
```

**Ошибка сертификатов (SSL):**

```bash
make clean
make setup
```

**`koji list-tags` не работает:**

```bash
koji --noauth --server=https://localhost:8443/kojihub list-tags
cat ~/.koji/config
curl -sk https://localhost:8443/kojihub
```

**Сборка зависает:**

```bash
koji list-hosts
koji list-tags --build
koji regen-repo f42-build
```

**Полный сброс:**

```bash
cd dev/koji-server
make clean
make setup
```

---

## Деплой на VPS

Продакшен-установка Koji на отдельный сервер. Рекомендуется автоматизированный путь через Ansible; ручная установка приведена для понимания того, что происходит «под капотом».

### Требования к серверу

| Параметр | Минимум | Рекомендуется |
|---|---|---|
| **ОС** | Fedora 40+ | Fedora 41 Server |
| **RAM** | 4 ГБ | 8 ГБ+ |
| **CPU** | 2 ядра | 4 ядра+ |
| **Диск** | 50 ГБ SSD | 100 ГБ+ SSD |
| **Сеть** | Публичный IP | Публичный IP + домен |
| **Порты** | 80, 443 | 80, 443, 5432 |

**Почему Fedora?** Koji разрабатывается в рамках проекта Fedora и лучше всего поддерживается там. Все пакеты (`koji-hub`, `koji-builder`, `koji-web`) доступны в стандартных репозиториях.

**Требования к клиенту:**

- Python 3.9+
- `koji` CLI, `rpm-build`, `rpm2cpio`
- Сетевой доступ к серверу Koji
- Опционально (для ML-разрешения имён): `scikit-learn >= 1.3`, `joblib >= 1.3`

### Выбор и заказ VPS

Подойдёт любой провайдер, предоставляющий образы Fedora. При заказе:

1. Выбрать образ Fedora 40+ (Server Edition)
2. Тариф с минимум 4 ГБ RAM и 50 ГБ SSD
3. Регион, ближайший к пользователям
4. Настроить SSH-ключ для доступа
5. Записать IP-адрес сервера

### Первоначальная настройка сервера

**Подключение и обновление:**

```bash
ssh root@YOUR_VPS_IP
dnf update -y
dnf install -y vim wget curl git
```

**Hostname:**

```bash
hostnamectl set-hostname koji.example.com
echo "YOUR_VPS_IP koji.example.com koji" >> /etc/hosts
```

**Пользователь:**

```bash
useradd -m -G wheel kojiadmin
passwd kojiadmin
echo "kojiadmin ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/kojiadmin
```

**SSH:**

```bash
# На локальной машине
ssh-copy-id kojiadmin@YOUR_VPS_IP

# На сервере: отключить вход по паролю (опционально)
sed -i 's/^PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart sshd
```

**Firewall:**

```bash
systemctl enable --now firewalld
firewall-cmd --permanent --add-service=http
firewall-cmd --permanent --add-service=https
firewall-cmd --permanent --add-port=5432/tcp
firewall-cmd --reload
firewall-cmd --list-all
```

**SELinux:**

```bash
getenforce
setsebool -P httpd_can_network_connect 1
setsebool -P httpd_can_network_connect_db 1
```

### Установка Koji через Ansible (рекомендуется)

Автоматизированный путь использует Ansible-плейбук из `ansible/` репозитория проекта.

#### Установка Ansible (на локальной машине)

```bash
# Fedora / RHEL
sudo dnf install -y ansible-core

# macOS
brew install ansible

# Ubuntu / Debian
sudo apt install -y ansible

# Или через pip
pip install ansible
```

#### Клонирование репозитория и зависимости

Склонируйте репозиторий проекта и перейдите в каталог `ansible/`:

```bash
cd ansible
ansible-galaxy install -r requirements.yml
```

`requirements.yml` содержит коллекции `ansible.posix`, `community.postgresql`, `community.general`.

#### Инвентарь

Отредактируйте `inventory/hosts.ini`:

```ini
[koji_hub]
koji-server ansible_host=YOUR_VPS_IP ansible_user=root

[koji_builders]
koji-server

[koji_web]
koji-server

[koji:children]
koji_hub
koji_builders
koji_web
```

#### Переменные

`group_vars/all.yml` — основные настройки:

```yaml
# ОБЯЗАТЕЛЬНО изменить:
koji_hub_fqdn: "koji.example.com"
postgresql_password: "SecurePassword123"
koji_admin_user: "kojiadmin"

# SSL:
ssl_cert_country: "RU"
ssl_cert_state: "Moscow"
ssl_cert_city: "Moscow"
ssl_cert_org: "VibeBuild"
ssl_cert_ou: "Build System"

# Теги и таргеты:
koji_build_tag: "fedora-build"
koji_dest_tag: "fedora-dest"
koji_target: "fedora-target"

# Внешние репозитории:
external_repos:
  - name: "fedora-base"
    url: "https://mirrors.fedoraproject.org/mirrorlist?repo=fedora-$releasever&arch=$basearch"
  - name: "fedora-updates"
    url: "https://mirrors.fedoraproject.org/mirrorlist?repo=updates-released-f$releasever&arch=$basearch"

# Mock:
mock_chroot: "fedora-40-x86_64"

# Firewall:
firewall_ports:
  - 80/tcp
  - 443/tcp
  - 5432/tcp
```

#### Запуск плейбука

```bash
ansible all -i inventory/hosts.ini -m ping
ansible-playbook -i inventory/hosts.ini playbook.yml
```

**Порядок ролей:**

1. `postgresql` — установка БД, инициализация, создание пользователя `koji`, `pg_hba.conf`
2. `koji-hub` — установка `koji-hub`, генерация SSL (CA, сервер, admin), настройка Apache + mod_wsgi, `hub.conf`
3. `koji-builder` — установка `koji-builder`, `mock`, конфигурация `kojid.conf`, mock chroot
4. `koji-web` — установка `koji-web`, vhost Apache
5. `koji-init` — добавление admin, создание тегов (`fedora-dest`, `fedora-build`), таргета (`fedora-target`), подключение внешних репозиториев

Процесс занимает 5–15 минут. После завершения веб-интерфейс доступен по адресу `https://YOUR_VPS_IP/koji`.

### Ручная установка Koji

Альтернативный путь — для понимания шагов, выполняемых Ansible.

#### 1. Установка пакетов

```bash
dnf install -y \
    koji-hub koji-hub-plugins \
    koji-builder koji-web \
    postgresql-server \
    httpd mod_ssl mod_wsgi \
    python3-koji \
    mock rpm-build createrepo_c
```

#### 2. PostgreSQL

```bash
postgresql-setup --initdb
systemctl enable --now postgresql

cat >> /var/lib/pgsql/data/pg_hba.conf << 'EOF'
host    koji        koji        127.0.0.1/32    md5
host    koji        koji        ::1/128         md5
EOF

systemctl restart postgresql

sudo -u postgres psql << 'EOF'
CREATE USER koji WITH PASSWORD 'your_secure_password';
CREATE DATABASE koji OWNER koji;
EOF

sudo -u postgres psql koji < /usr/share/doc/koji*/docs/schema.sql
```

#### 3. SSL-сертификаты

```bash
mkdir -p /etc/pki/koji/{certs,private}

# CA
openssl req -new -x509 -days 3650 -nodes \
    -subj "/C=RU/ST=Moscow/L=Moscow/O=VibeBuild/OU=Build System/CN=Koji CA" \
    -keyout /etc/pki/koji/koji_ca_cert.key \
    -out /etc/pki/koji/koji_ca_cert.crt

# Серверный сертификат
openssl genrsa -out /etc/pki/koji/certs/server.key 2048
openssl req -new \
    -subj "/CN=koji.example.com" \
    -key /etc/pki/koji/certs/server.key \
    -out /etc/pki/koji/certs/server.csr
openssl x509 -req -days 3650 \
    -in /etc/pki/koji/certs/server.csr \
    -CA /etc/pki/koji/koji_ca_cert.crt \
    -CAkey /etc/pki/koji/koji_ca_cert.key \
    -CAcreateserial \
    -out /etc/pki/koji/certs/server.crt

# Admin
openssl genrsa -out /etc/pki/koji/certs/kojiadmin.key 2048
openssl req -new -subj "/CN=kojiadmin" \
    -key /etc/pki/koji/certs/kojiadmin.key \
    -out /etc/pki/koji/certs/kojiadmin.csr
openssl x509 -req -days 3650 \
    -in /etc/pki/koji/certs/kojiadmin.csr \
    -CA /etc/pki/koji/koji_ca_cert.crt \
    -CAkey /etc/pki/koji/koji_ca_cert.key \
    -out /etc/pki/koji/certs/kojiadmin.crt
cat /etc/pki/koji/certs/kojiadmin.crt /etc/pki/koji/certs/kojiadmin.key \
    > /etc/pki/koji/kojiadmin.pem

# Builder
openssl genrsa -out /etc/pki/koji/certs/kojibuilder.key 2048
openssl req -new -subj "/CN=$(hostname)" \
    -key /etc/pki/koji/certs/kojibuilder.key \
    -out /etc/pki/koji/certs/kojibuilder.csr
openssl x509 -req -days 3650 \
    -in /etc/pki/koji/certs/kojibuilder.csr \
    -CA /etc/pki/koji/koji_ca_cert.crt \
    -CAkey /etc/pki/koji/koji_ca_cert.key \
    -out /etc/pki/koji/certs/kojibuilder.crt
cat /etc/pki/koji/certs/kojibuilder.crt /etc/pki/koji/certs/kojibuilder.key \
    > /etc/pki/koji/kojibuilder.pem
```

#### 4. Директории Koji

```bash
mkdir -p /mnt/koji/{packages,repos,work,scratch}
chown -R apache:apache /mnt/koji
```

#### 5. Koji Hub

```bash
cat > /etc/koji-hub/hub.conf << 'EOF'
[hub]
DBName = koji
DBUser = koji
DBPass = your_secure_password
DBHost = 127.0.0.1
KojiDir = /mnt/koji
AuthPrincipal =
ProxyPrincipals =
LoginCreatesUser = On
KojiWebURL = https://koji.example.com/koji
DisableNotifications = True
EOF
```

#### 6. Apache

`/etc/httpd/conf.d/kojihub.conf`:

```apache
Alias /kojihub /usr/share/koji-hub/kojiapp.py

<Directory "/usr/share/koji-hub">
    Options ExecCGI
    SetHandler wsgi-script
    WSGIApplicationGroup %{GLOBAL}
    Require all granted
</Directory>

Alias /kojifiles /mnt/koji

<Directory "/mnt/koji">
    Options Indexes FollowSymLinks
    AllowOverride None
    Require all granted
</Directory>
```

В `/etc/httpd/conf.d/ssl.conf`:

```apache
SSLCertificateFile /etc/pki/koji/certs/server.crt
SSLCertificateKeyFile /etc/pki/koji/certs/server.key
SSLCACertificateFile /etc/pki/koji/koji_ca_cert.crt
SSLVerifyClient optional
SSLVerifyDepth 10
```

#### 7. Koji Builder

```bash
cat > /etc/kojid/kojid.conf << 'EOF'
[kojid]
server = https://koji.example.com/kojihub
topurl = https://koji.example.com/kojifiles
workdir = /tmp/koji
cert = /etc/pki/koji/kojibuilder.pem
serverca = /etc/pki/koji/koji_ca_cert.crt
allowed_scms = src.fedoraproject.org:/*:no:fedpkg,sources
mockdir = /var/lib/mock
mockuser = kojibuilder
mockhost = fedora-40-x86_64
EOF
```

#### 8. Koji Web

```bash
cat > /etc/kojiweb/web.conf << 'EOF'
[web]
SiteName = Koji
KojiHubURL = https://koji.example.com/kojihub
KojiFilesURL = https://koji.example.com/kojifiles
WebCert = /etc/pki/koji/kojiadmin.pem
ClientCA = /etc/pki/koji/koji_ca_cert.crt
KojiHubCA = /etc/pki/koji/koji_ca_cert.crt
LoginTimeout = 72
Secret = CHANGE_THIS_TO_RANDOM_STRING
EOF
```

#### 9. Запуск сервисов

```bash
systemctl enable --now httpd
systemctl enable --now kojid
```

#### 10. Инициализация

```bash
mkdir -p ~/.koji
cp /etc/pki/koji/kojiadmin.pem ~/.koji/client.pem
cp /etc/pki/koji/koji_ca_cert.crt ~/.koji/serverca.crt

cat > ~/.koji/config << 'EOF'
[koji]
server = https://koji.example.com/kojihub
weburl = https://koji.example.com/koji
topurl = https://koji.example.com/kojifiles
cert = ~/.koji/client.pem
serverca = ~/.koji/serverca.crt
EOF

koji add-user kojiadmin
koji grant-permission admin kojiadmin
koji add-host $(hostname) x86_64

koji add-tag fedora-dest
koji add-tag fedora-build --parent fedora-dest --arches x86_64
koji add-target fedora-target fedora-build fedora-dest

koji add-external-repo -t fedora-build fedora-base \
    "https://mirrors.fedoraproject.org/mirrorlist?repo=fedora-\$releasever&arch=\$basearch"
koji add-external-repo -t fedora-build fedora-updates \
    "https://mirrors.fedoraproject.org/mirrorlist?repo=updates-released-f\$releasever&arch=\$basearch"

koji add-group fedora-build build
koji add-group fedora-build srpm-build

for pkg in bash bzip2 coreutils cpio diffutils fedora-release findutils \
    gawk glibc-minimal-langpack grep gzip info make patch \
    redhat-rpm-config rpm-build sed shadow-utils tar unzip \
    util-linux which xz; do
    koji add-group-pkg fedora-build build $pkg
done

for pkg in bash fedora-release fedpkg-minimal gnupg2 \
    redhat-rpm-config rpm-build shadow-utils; do
    koji add-group-pkg fedora-build srpm-build $pkg
done

koji regen-repo fedora-build
```

Регенерация репозитория занимает 5–15 минут.

### Настройка клиента VibeBuild

Выполняется на **локальной машине** (не на сервере).

#### Сертификаты

```bash
mkdir -p ~/.koji
scp root@YOUR_VPS_IP:/etc/pki/koji/kojiadmin.pem ~/.koji/client.pem
scp root@YOUR_VPS_IP:/etc/pki/koji/koji_ca_cert.crt ~/.koji/serverca.crt
```

#### Koji CLI

```bash
cat > ~/.koji/config << 'EOF'
[koji]
server = https://YOUR_VPS_IP/kojihub
weburl = https://YOUR_VPS_IP/koji
topurl = https://YOUR_VPS_IP/kojifiles
cert = ~/.koji/client.pem
serverca = ~/.koji/serverca.crt
EOF
```

#### Установка VibeBuild

```bash
# Из исходников (склонируйте репозиторий проекта)
cd <путь к репозиторию>
pip install -e ".[dev,ml]"
```

`[ml]` ставит `scikit-learn` и `joblib` для ML-разрешения имён. Без них VibeBuild работает с rule-based разрешением.

#### Системные зависимости

```bash
# Fedora / RHEL
sudo dnf install -y koji rpm-build rpm2cpio

# macOS (через Homebrew)
brew install rpm

# Ubuntu / Debian
sudo apt install -y koji rpm rpm2cpio
```

#### Проверка подключения

```bash
koji hello
# olá, kojiadmin!
# You are using the hub at https://YOUR_VPS_IP/kojihub
```

#### Конфигурация через CLI или ENV

```bash
# Через флаги
vibebuild \
    --server https://koji.example.com/kojihub \
    --cert ~/.koji/client.pem \
    --serverca ~/.koji/serverca.crt \
    fedora-target my-package.src.rpm

# Через переменные окружения
export KOJI_SERVER=https://koji.example.com/kojihub
export KOJI_CERT=~/.koji/client.pem
export KOJI_SERVERCA=~/.koji/serverca.crt
vibebuild fedora-target my-package.src.rpm
```

### Настройка ML-модели (опционально)

VibeBuild включает ML-резолвер для сложных виртуальных RPM-зависимостей. ML-компонент полностью опционален.

#### 1. Установка ML-зависимостей

Уже выполнена через `pip install -e ".[dev,ml]"`. Без extras VibeBuild работает с rule-based разрешением имён (9 паттернов виртуальных provides + 18 системных макросов).

#### 2. Сбор обучающих данных

Скрипт скачивает и парсит метаданные репозиториев Fedora:

```bash
python scripts/collect_training_data.py \
    --output data/training_data.json \
    --release 40 \
    --arch x86_64
```

Скачивает `primary.xml.gz` с зеркал Fedora и извлекает виртуальные provides (python3dist, pkgconfig, perl и др.), привязанные к реальным именам пакетов. Результат — ~50 000–100 000 маппингов.

#### 3. Обучение

```bash
python scripts/train_model.py \
    --input data/training_data.json \
    --output vibebuild/data/model.joblib \
    --test-split 0.1
```

Скрипт обучает TF-IDF + KNN, оценивает на 10 % тестовой выборке (RPM accuracy, SRPM accuracy), сохраняет модель (~5–15 МБ).

#### 4. Использование

Модель автоматически загружается при запуске VibeBuild.

```bash
# Обычная работа (правила + ML как запасной вариант)
vibebuild fedora-target my-package.src.rpm

# Отключить ML, использовать только правила
vibebuild --no-ml fedora-target my-package.src.rpm

# Отключить всё разрешение имён
vibebuild --no-name-resolution fedora-target my-package.src.rpm

# Пользовательская модель
vibebuild --ml-model /path/to/model.joblib fedora-target my-package.src.rpm
```

Кэш ML-предсказаний — `~/.cache/vibebuild/ml_name_cache.json`. Очистите его при переобучении модели:

```bash
rm -f ~/.cache/vibebuild/ml_name_cache.json
```

### Проверка и мониторинг

#### Веб-интерфейс

Откройте `https://YOUR_VPS_IP/koji`.

#### Статус сервисов

```bash
# На сервере
systemctl status httpd          # Apache (Koji Hub + Web)
systemctl status kojid          # Koji Builder
systemctl status postgresql     # PostgreSQL

# С клиента
koji list-hosts
koji list-tags
koji list-targets
koji list-tasks
```

#### Тестовая сборка

```bash
vibebuild --download-only python-six
vibebuild --analyze-only python-six-*.src.rpm
vibebuild --dry-run fedora-target python-six-*.src.rpm
vibebuild fedora-target python-six-*.src.rpm
```

#### Метрики

Рекомендуется мониторить:

- Дисковое пространство на `/mnt/koji`
- Очередь задач Koji
- Статус builder
- Время отклика Hub

### Устранение неполадок (VPS)

**Не могу подключиться к серверу:**

```bash
sudo systemctl status httpd
sudo ss -tlnp | grep -E ':(80|443)'
sudo firewall-cmd --list-all
openssl s_client -connect YOUR_VPS_IP:443 < /dev/null

# Если самоподписанный сертификат
vibebuild --no-ssl-verify --server https://YOUR_VPS_IP/kojihub ...
```

**SSL certificate verify failed:**

```bash
ls -la ~/.koji/serverca.crt
openssl x509 -in ~/.koji/client.pem -noout -subject
openssl rsa -in ~/.koji/client.pem -noout -check
```

**Database connection failed:**

```bash
sudo systemctl status postgresql
psql -h 127.0.0.1 -U koji -d koji
sudo cat /var/lib/pgsql/data/pg_hba.conf | grep koji
sudo systemctl restart postgresql
```

**Builder offline:**

```bash
sudo systemctl status kojid
sudo journalctl -u kojid -f
ls -la /etc/pki/koji/kojibuilder.pem
koji list-hosts
sudo systemctl restart kojid
```

**Сборка падает с createrepo error:**

```bash
koji regen-repo fedora-build
sudo chown -R apache:apache /mnt/koji
df -h /mnt/koji
```

**Логи:**

```bash
sudo tail -f /var/log/httpd/error_log
sudo journalctl -u kojid -f
sudo tail -f /var/lib/pgsql/data/log/postgresql-*.log
sudo ls /var/lib/mock/*/result/
```

### Резервное копирование и обновление

**Backup:**

```bash
# Дамп БД
pg_dump -U koji koji > /backup/koji_db_$(date +%Y%m%d).sql

# Сертификаты
tar -czf /backup/koji_certs_$(date +%Y%m%d).tar.gz /etc/pki/koji/

# Конфигурация
tar -czf /backup/koji_config_$(date +%Y%m%d).tar.gz \
    /etc/koji-hub/ /etc/kojid/ /etc/kojiweb/
```

**Обновление Koji:**

```bash
sudo dnf update koji-hub koji-builder koji-web
sudo systemctl restart httpd kojid
```

**Обновление VibeBuild:**

```bash
cd <путь к репозиторию>
git pull
pip install -e ".[dev,ml]"
```

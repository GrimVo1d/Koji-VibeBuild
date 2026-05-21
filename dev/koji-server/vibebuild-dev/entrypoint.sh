#!/usr/bin/env bash
set -euo pipefail

# Настраиваем koji-клиент внутри контейнера, чтобы он смотрел на koji-hub
# по docker-сети (а не на localhost).
mkdir -p /root/.koji
cat > /root/.koji/config <<EOF
[koji]
server = https://koji-hub/kojihub
weburl = https://koji-hub/koji
topurl = https://koji-hub/kojifiles
cert = /etc/pki/koji/kojiadmin.pem
serverca = /etc/pki/koji/koji_ca_cert.crt
authtype = ssl
target = f42
build_tag = f42-build
EOF

# Доверяем CA для curl/wget/requests
cp /etc/pki/koji/koji_ca_cert.crt /etc/pki/ca-trust/source/anchors/koji_ca_cert.crt
update-ca-trust extract

# Устанавливаем vibebuild в editable-режиме из смонтированного /workspace.
# Делаем --no-deps на ml (sklearn/joblib уже стоят системно) — остальные через pip.
if [ -f /workspace/pyproject.toml ]; then
    cd /workspace
    pip install --quiet --no-build-isolation -e ".[dev]" \
        || pip install --no-build-isolation -e ".[dev]"
    echo "vibebuild установлен в /workspace"
else
    echo "WARNING: /workspace/pyproject.toml не найден — vibebuild не установлен"
fi

# Не падаем: держим контейнер живым, чтобы docker compose exec работал
echo ""
echo "=== vibebuild-dev готов ==="
echo "Вход: docker compose exec vibebuild-dev bash"
echo "Конфиг koji: /root/.koji/config (server = https://koji-hub/kojihub)"
echo ""
exec sleep infinity

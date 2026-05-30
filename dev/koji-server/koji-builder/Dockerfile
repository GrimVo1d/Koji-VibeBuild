FROM fedora:42

RUN dnf install -y \
    koji-builder \
    mock createrepo_c \
    rpm-build \
    && dnf clean all

RUN useradd -r kojibuilder 2>/dev/null || true && \
    usermod -aG mock kojibuilder

# Доверяем нашему self-signed CA *внутри* mock-чрутов: подкладываем его в
# ssl_extra_certs через site-defaults, чтобы dnf внутри chroot мог скачать
# repomd.xml с koji-hub без SSL-ошибок.
RUN printf "%s\n" \
    "import os" \
    "_ca = '/etc/pki/koji/koji_ca_cert.crt'" \
    "if os.path.exists(_ca):" \
    "    config_opts['ssl_extra_certs'] = _ca" \
    >> /etc/mock/site-defaults.cfg

# Совместимость kojid (передаёт `-r koji/<name>`) с mock 6.7+, который такую
# форму больше не понимает и падает с IsADirectoryError на '/'.
# /usr/bin/mock — это consolehelper-симлинк, ломать его нельзя
# (kojibuilder из группы mock получает root-привилегии через PAM именно
# через consolehelper). Поэтому патчим сам Python-скрипт mock'а в самом
# начале, чтобы он переписывал `-r koji/<name>` в современный
# `--configdir /etc/mock/koji -r <name>`.
RUN python3 -c "import sys, pathlib; p = pathlib.Path('/usr/libexec/mock/mock'); \
src = p.read_text(); \
shim = '''\n\
# --- KOJI COMPAT SHIM (added in Dockerfile) ---------------------------------\n\
# mock 6.7+ больше не понимает '-r koji/<name>' (бьёт IsADirectoryError на '/').\n\
# kojid по-прежнему так зовёт. Транслируем в '--configdir /etc/mock/koji -r <name>'.\n\
import sys as _sys, os as _os\n\
_a = _sys.argv\n\
_i = 1\n\
while _i < len(_a) - 1:\n\
    if _a[_i] == '-r' and _a[_i+1].startswith('koji/'):\n\
        _short = _a[_i+1].split('/', 1)[1]\n\
        _a[_i:_i+2] = ['--configdir', '/etc/mock/koji', '-r', _short]\n\
        break\n\
    _i += 1\n\
del _a, _i\n\
# --- end KOJI COMPAT SHIM ---------------------------------------------------\n\
'''; \
marker = 'import sys'; \
idx = src.index(marker); \
p.write_text(src[:idx] + shim + src[idx:])"

COPY kojid.conf /etc/kojid/kojid.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]

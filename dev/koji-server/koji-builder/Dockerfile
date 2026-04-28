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

COPY kojid.conf /etc/kojid/kojid.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]

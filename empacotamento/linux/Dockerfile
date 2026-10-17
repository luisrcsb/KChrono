# KChrono — ambiente de build do Linux (AppImage x86_64).
#
# Ubuntu 22.04 de propósito: glibc 2.35 = piso de compatibilidade.
# O AppImage gerado aqui roda em Debian 12+, Ubuntu 22.04+, Linux Mint 21+.
# Python 3.12 (deadsnakes) para ficar perto do 3.14 usado no Windows.
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg software-properties-common \
        patchelf file xz-utils build-essential \
 && add-apt-repository -y ppa:deadsnakes/ppa \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv python3.12-dev \
 && rm -rf /var/lib/apt/lists/*

# venv isolado com PyInstaller + dependências do app
RUN python3.12 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir -U pip \
 && /opt/venv/bin/pip install --no-cache-dir pyinstaller==6.22.3
ENV PATH=/opt/venv/bin:$PATH

# requirements fora da imagem só pra rebuild desta camada quando mudar
COPY requirements.txt /tmp/requirements.txt
RUN /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt

# appimagetool extraído (dispensa FUSE dentro do container)
RUN mkdir -p /opt/appimagetool \
 && curl -fsSL -o /tmp/appimagetool.AppImage \
        https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage \
 && chmod +x /tmp/appimagetool.AppImage \
 && (cd /opt/appimagetool && /tmp/appimagetool.AppImage --appimage-extract >/dev/null) \
 && rm /tmp/appimagetool.AppImage

WORKDIR /app

#!/usr/bin/env bash
# KChrono — monta a ISO da live (Debian + Xfce + Firefox + KChrono pronto).
#
#   sudo bash iso/montar_iso.sh
#
# Requer o AppImage já copiado para:
#   iso/config/includes.live/opt/kchrono/KChrono.AppImage
# (a CI copia automaticamente; localmente:
#    cp publicacao/linux/*.AppImage iso/config/includes.live/opt/kchrono/KChrono.AppImage)
#
# Saída: iso/build/KChrono-live-*.iso
set -euo pipefail

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
APP="$RAIZ/iso/config/includes.live/opt/kchrono/KChrono.AppImage"

[ -f "$APP" ] || {
    echo "ERRO: falta o AppImage em $APP"
    exit 1
}
chmod +x "$APP"

# live-build precisa de root (chroot, mksquashfs, xorriso)
if [ "$(id -u)" != "0" ]; then
    exec sudo bash "$0" "$@"
fi

if ! command -v lb >/dev/null 2>&1; then
    echo "== instalando ferramentas do live-build"
    apt-get update
    apt-get install -y live-build debootstrap squashfs-tools xorriso \
        dosfstools mtools systemd-container
fi

cd "$RAIZ/iso"
lb clean --all >/dev/null 2>&1 || true

echo "== lb config (Debian bookworm + Xfce + instalador gráfico)"
lb config \
    --distribution bookworm \
    --architectures amd64 \
    --binary-images iso-hybrid \
    --image-name "KChrono-live" \
    --iso-application "KChrono" \
    --iso-publisher "KChrono" \
    --iso-volume "KChrono" \
    --archive-areas "main contrib non-free non-free-firmware" \
    --debian-installer live \
    --debian-installer-gui true \
    --bootloaders "syslinux,grub-efi" \
    --bootappend-live "boot=live components hostname=kchrono" \
    --compression xz \
    --memtest none \
    --zsync false

echo "== lb build (15 a 25 min)"
lb build

echo "== ISO gerada:"
ls -lh "$RAIZ"/iso/build/*.iso

#!/usr/bin/env bash
# KChrono — monta o AppImage do Linux (roda DENTRO do container Dockerfile).
#
#   docker build -t kchrono-linux -f empacotamento/linux/Dockerfile .
#   docker run --rm -v "$PWD:/app" -w /app kchrono-linux \
#        bash empacotamento/linux/build_appimage.sh
#
# Saída: publicacao/linux/KChrono-<versao>-x86_64.AppImage
set -euo pipefail

RAIZ="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$RAIZ"

echo "== Python: $(python3 --version)"
python3 empacotamento/build.py          # gera empacotamento/dist/KChrono-<versao> (onedir)

VER=$(python3 -c "import json; print(json.load(open('empacotamento/versao.json'))['versao'])")
APP="empacotamento/dist/KChrono-${VER}"
test -x "$APP/KChrono-${VER}" || { echo "ERRO: PyInstaller não gerou $APP/KChrono-${VER}"; exit 1; }

# ---- AppDir (formato que o appimagetool transforma em AppImage) ----
DIR=build/appdir
rm -rf "$DIR"
mkdir -p "$DIR/usr/bin/KChrono"
cp -a "$APP/." "$DIR/usr/bin/KChrono/"
# nome estável do executável dentro do AppImage (sem a versão)
mv "$DIR/usr/bin/KChrono/KChrono-${VER}" "$DIR/usr/bin/KChrono/KChrono"

cat > "$DIR/KChrono.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=KChrono
GenericName=Cronometragem RC
Comment=Cronometragem de corridas RC com voz neural offline
Exec=KChrono
Icon=kchrono
Terminal=false
Categories=Utility;AudioVideo;Sports;
EOF

cp imagens/KCHRONO-LOGO.png "$DIR/kchrono.png"

cat > "$DIR/AppRun" <<'EOF'
#!/bin/sh
# Entry point do AppImage — mantém o CWD do usuário (graváveis em ~/.local/share)
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/KChrono/KChrono" "$@"
EOF

chmod +x "$DIR/AppRun" "$DIR/KChrono.desktop"

# ---- AppImage ----
mkdir -p publicacao/linux
cp empacotamento/linux/LEIA-ME.txt publicacao/linux/
AIT="${APPIMAGETOOL:-/opt/appimagetool/squashfs-root/AppRun}"
ARCH=x86_64 "$AIT" "$DIR" "publicacao/linux/KChrono-${VER}-x86_64.AppImage"

echo "== AppImage gerado:"
ls -lh publicacao/linux/

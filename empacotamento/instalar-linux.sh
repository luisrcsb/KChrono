#!/usr/bin/env bash
# ============================================================
#  KChrono - instalador Linux (usuário, sem root)
#  Instala em ~/.local/share/KChrono e cria o comando `kchrono`.
#  Requer: WebKitGTK 4.1 (libwebkit2gtk-4.1-0) para pywebview.
#  Rode a partir de qualquer lugar dentro do projeto:
#      bash empacotamento/instalar-linux.sh
# ============================================================
set -euo pipefail

AQUI="$(cd "$(dirname "$0")" && pwd)"
SRC="$(cd "$AQUI/.." && pwd)"
DEST="${KCHRONO_DEST:-$HOME/.local/share/KChrono}"
BIN="${KCHRONO_BIN:-$HOME/.local/bin}"

echo "KChrono — instalando (Linux + pywebview/WebKitGTK)"
echo "  origem : $SRC"
echo "  destino: $DEST"

# Verifica dependência de sistema (WebKitGTK para pywebview)
if ! pkg-config --exists webkit2gtk-4.1 2>/dev/null; then
    echo "AVISO: webkit2gtk-4.1 não encontrado."
    echo "  Ubuntu/Debian: sudo apt install libwebkit2gtk-4.1-0"
    echo "  Fedora:        sudo dnf install webkit2gtk4.1"
    echo "  Arch:          sudo pacman -S webkit2gtk-4.1"
    echo "  Sem isso, a janela nativa não abrirá (fallback para navegador)."
fi

mkdir -p "$DEST" "$BIN"

echo "[1/4] copiando arquivos do projeto…"
for item in cli.py caminhos.py requirements.txt nucleo servidor drivers sync interface imagens; do
  if [ -e "$SRC/$item" ]; then
    cp -r "$SRC/$item" "$DEST/"
  fi
done

echo "[2/4] criando ambiente virtual e instalando dependências…"
python3 -m venv "$DEST/venv"
"$DEST/venv/bin/pip" install --upgrade pip >/dev/null
"$DEST/venv/bin/pip" install -r "$DEST/requirements.txt"

echo "[3/4] criando o comando 'kchrono'…"
cat > "$BIN/kchrono" <<EOF
#!/usr/bin/env bash
cd "$DEST"
exec "$DEST/venv/bin/python" cli.py servidor "\$@"
EOF
chmod +x "$BIN/kchrono"

# Wrapper para o app nativo (pywebview)
cat > "$BIN/kchrono-app" <<EOF
#!/usr/bin/env bash
cd "$DEST"
exec "$DEST/venv/bin/python" empacotamento/kchrono_launcher.py "\$@"
EOF
chmod +x "$BIN/kchrono-app"

echo "[4/4] instalando atalho no menu…"
mkdir -p "$HOME/.local/share/applications"
sed "s|__EXEC__|$BIN/kchrono-app|g" "$AQUI/kchrono.desktop" \
  > "$HOME/.local/share/applications/kchrono.desktop"

echo
echo "Pronto! Dois comandos disponíveis:"
echo "  kchrono        → servidor headless (para systemd/serviço)"
echo "  kchrono-app    → app nativo com janela (WebView2/GTK)"
echo "  (se '$BIN' não estiver no PATH, adicione:  export PATH=\"$BIN:\$PATH\")"
echo "  Telão:  kchrono-app --telao --fullscreen"
echo "  Gerente: kchrono-app --gerente"

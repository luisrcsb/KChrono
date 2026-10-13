#!/usr/bin/env bash
# ============================================================
#  KChrono - instalador Linux (usuário, sem root)
#  Instala em ~/.local/share/KChrono e cria o comando `kchrono`.
#  Rode a partir de qualquer lugar dentro do projeto:
#      bash empacotamento/instalar-linux.sh
# ============================================================
set -euo pipefail

AQUI="$(cd "$(dirname "$0")" && pwd)"
SRC="$(cd "$AQUI/.." && pwd)"
DEST="${KCHRONO_DEST:-$HOME/.local/share/KChrono}"
BIN="${KCHRONO_BIN:-$HOME/.local/bin}"

echo "KChrono — instalando"
echo "  origem : $SRC"
echo "  destino: $DEST"

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

echo "[4/4] instalando atalho no menu…"
mkdir -p "$HOME/.local/share/applications"
sed "s|__EXEC__|$BIN/kchrono|g" "$AQUI/kchrono.desktop" \
  > "$HOME/.local/share/applications/kchrono.desktop"

echo
echo "Pronto! Inicie com:  kchrono"
echo "  (se '$BIN' não estiver no PATH, adicione:  export PATH=\"$BIN:\$PATH\")"
echo "  Telão:  http://localhost:8780/telao"

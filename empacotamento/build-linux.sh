#!/usr/bin/env bash
# ============================================================
#  KChrono - build Linux (gera tar.gz para distribuição)
#  Rode a partir da pasta empacotamento:
#      bash build-linux.sh
# ============================================================
set -euo pipefail

cd "$(dirname "$0")"
VERSAO="1.0.0"
DIST="kchrono-linux-${VERSAO}"
STAGE="stage/${DIST}"

echo "=== KChrono Linux build v${VERSAO} ==="

# Limpa stage anterior
rm -rf stage
mkdir -p "${STAGE}"

echo "[1/4] Copiando arquivos do projeto..."
SRC="$(cd .. && pwd)"
for item in cli.py caminhos.py requirements.txt atualizador.py nucleo servidor drivers sync interface imagens; do
  if [ -e "$SRC/$item" ]; then
    cp -r "$SRC/$item" "${STAGE}/"
  fi
done

# Copia arquivos de empacotamento necessários
cp kchrono.service "${STAGE}/"
cp kchrono.desktop "${STAGE}/"
cp instalar-linux.sh "${STAGE}/"
cp versao.json "${STAGE}/"
cp LEIA-ME.md "${STAGE}/"

echo "[2/4] Criando script de entrada kchrono..."
cat > "${STAGE}/kchrono" <<'EOF'
#!/usr/bin/env bash
# Launcher do KChrono — detecta se está instalado ou rodando do pacote
set -euo pipefail

# Se KCHRONO_HOME não está setado, tenta descobrir
if [ -z "${KCHRONO_HOME:-}" ]; then
    # Se estamos no pacote extraído
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    if [ -f "$SCRIPT_DIR/cli.py" ]; then
        export KCHRONO_HOME="$SCRIPT_DIR"
    elif [ -d "$HOME/.local/share/KChrono" ]; then
        export KCHRONO_HOME="$HOME/.local/share/KChrono"
    else
        echo "Erro: KCHRONO_HOME não definido e instalação não encontrada."
        echo "  Rode: bash instalar-linux.sh"
        exit 1
    fi
fi

cd "$KCHRONO_HOME"

# Se não existe venv, cria
if [ ! -d "venv" ]; then
    echo "Criando ambiente virtual..."
    python3 -m venv venv
    ./venv/bin/pip install --upgrade pip >/dev/null
    ./venv/bin/pip install -r requirements.txt
fi

exec ./venv/bin/python cli.py "$@"
EOF
chmod +x "${STAGE}/kchrono"

echo "[3/4] Criando launcher do app nativo (kchrono-app)..."
cat > "${STAGE}/kchrono-app" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

if [ -z "${KCHRONO_HOME:-}" ]; then
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    if [ -f "$SCRIPT_DIR/cli.py" ]; then
        export KCHRONO_HOME="$SCRIPT_DIR"
    elif [ -d "$HOME/.local/share/KChrono" ]; then
        export KCHRONO_HOME="$HOME/.local/share/KChrono"
    else
        echo "Erro: instalação não encontrada. Rode: bash instalar-linux.sh"
        exit 1
    fi
fi

cd "$KCHRONO_HOME"

if [ ! -d "venv" ]; then
    echo "Criando ambiente virtual..."
    python3 -m venv venv
    ./venv/bin/pip install --upgrade pip >/dev/null
    ./venv/bin/pip install -r requirements.txt
fi

exec ./venv/bin/python empacotamento/kchrono_launcher.py "$@"
EOF
chmod +x "${STAGE}/kchrono-app"

echo "[4/4] Criando tar.gz..."
tar -czf "${DIST}.tar.gz" -C stage "${DIST}"

echo
echo "✅ Pronto: ${DIST}.tar.gz"
echo "   Teste: tar -xzf ${DIST}.tar.gz && cd ${DIST} && ./kchrono-app"
echo "   Instalação: cd ${DIST} && bash instalar-linux.sh"
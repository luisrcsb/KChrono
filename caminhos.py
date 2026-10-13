"""KChrono — resolução de caminhos.

Funciona tanto rodando do código-fonte quanto empacotado com PyInstaller.

· ``dir_recursos()`` — arquivos somente-leitura que acompanham o app
  (interface/, imagens/); no modo empacotado ficam em ``sys._MEIPASS``.
· ``dir_dados()`` — arquivos graváveis (banco SQLite, config.json, uploads);
  ficam sempre **ao lado do executável** / da pasta do projeto, para não se
  perderem quando o app é atualizado.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def empacotado() -> bool:
    """True quando roda de dentro de um executável PyInstaller."""
    return bool(getattr(sys, "frozen", False))


def dir_recursos() -> Path:
    if empacotado():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def dir_dados() -> Path:
    """Pasta gravável (banco, config, uploads).

    · código-fonte → pasta do projeto;
    · empacotado    → %APPDATA%\\KChrono (Windows) ou ~/.local/share/KChrono,
      para funcionar mesmo instalado em Program Files (somente leitura).
    """
    if empacotado():
        if sys.platform == "win32":
            base = os.environ.get("APPDATA") or str(Path.home())
        else:
            base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        pasta = Path(base) / "KChrono"
        pasta.mkdir(parents=True, exist_ok=True)
        return pasta
    return Path(__file__).resolve().parent

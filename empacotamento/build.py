"""Empacota o KChrono com PyInstaller (Windows e Linux).

· Sobe o processo do PyInstaller dentro do próprio interpreter (truque
  ``_pyi_isolated_subprocess``): no Python 3.14 + numpy do Windows o
  subprocesso isolado do PyInstaller morre com ACCESS_VIOLATION ao importar
  ``numpy.typing``.
· Sincroniza o ``!define VERSAO`` do instalador NSIS (empacotamento/instalador.nsi)
  com a fonte única da versão: empacotamento/versao.json.

Uso (qualquer plataforma):
    python empacotamento/build.py
"""
import json
import os
import re
import sys

# Faz PyInstaller.isolated.Python virar no-op (executa tudo em processo).
sys._pyi_isolated_subprocess = True

AQUI = os.path.dirname(os.path.abspath(__file__))


def _sincronizar_versao_nsis():
    """Espelha versao.json nos !define VERSAO e VERSAO_ARQ do instalador NSIS."""
    vfile = os.path.join(AQUI, "versao.json")
    nsi = os.path.join(AQUI, "instalador.nsi")
    try:
        with open(vfile, encoding="utf-8") as f:
            versao = json.load(f)["versao"]
        # surrogateescape preserva byte a byte o arquivo (NSIS lê em ACP)
        with open(nsi, encoding="utf-8", errors="surrogateescape") as f:
            txt = f.read()
        novo, n = re.subn(r'(!define VERSAO ")[^"]*(")',
                          lambda m: m.group(1) + versao + m.group(2),
                          txt, count=1)
        # VERSAO_ARQ = versão com hífens → nome do arquivo do instalador
        novo, n2 = re.subn(r'(!define VERSAO_ARQ ")[^"]*(")',
                           lambda m: m.group(1) + versao.replace(".", "-")
                           + m.group(2), novo, count=1)
        if (n or n2) and novo != txt:
            with open(nsi, "w", encoding="utf-8",
                      errors="surrogateescape", newline="") as f:
                f.write(novo)
            print(f"[build] instalador.nsi VERSAO = {versao}"
                  f" (arquivo: KChrono-Setup-{versao.replace('.', '-')}.exe)")
    except Exception as e:
        print(f"[build] aviso: não sincronizei a versão do NSIS ({e})")


def main() -> int:
    _sincronizar_versao_nsis()
    os.chdir(AQUI)
    from PyInstaller.__main__ import run
    run(["--clean", "--noconfirm", "KChrono.spec"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Empacota o KChrono com PyInstaller (Windows e Linux).

· Sobe o processo do PyInstaller dentro do próprio interpreter (truque
  ``_pyi_isolated_subprocess``): no Python 3.14 + numpy do Windows o
  subprocesso isolado do PyInstaller morre com ACCESS_VIOLATION ao importar
  ``numpy.typing``.
· **Confere a versão antes de empacotar** (regra do projeto: toda alteração
  entregue sobe a versão). Se algum espelho estiver fora de sincronia com
  ``empacotamento/versao.json`` o build é recusado — assim não sai pacote
  com versão errada. Use ``python tools/versao.py bump --notas "..."``.
· Sincroniza o ``!define VERSAO`` do instalador NSIS (empacotamento/instalador.nsi)
  com a fonte única da versão: empacotamento/versao.json.

Uso (qualquer plataforma):
    python empacotamento/build.py
"""
import os
import sys

# Faz PyInstaller.isolated.Python virar no-op (executa tudo em processo).
sys._pyi_isolated_subprocess = True

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)


def _carregar_ferramenta_versao():
    """Importa tools/versao.py (fonte única da versão)."""
    if RAIZ not in sys.path:
        sys.path.insert(0, RAIZ)
    if os.path.join(RAIZ, "tools") not in sys.path:
        sys.path.insert(0, os.path.join(RAIZ, "tools"))
    import versao  # noqa: E402
    return versao


def _checar_versao() -> bool:
    """True se a versão está em sincronia (senão o build é recusado)."""
    try:
        v = _carregar_ferramenta_versao()
    except Exception as e:
        print(f"[build] aviso: não consegui checar a versão ({e})")
        return True
    problemas = v.verificar()
    if problemas:
        print("[build] ERRO: a versão está fora de sincronia:")
        for p in problemas:
            print(f"   - {p}")
        print('[build] rode: python tools/versao.py bump --notas "o que mudou"')
        return False
    print(f"[build] versão ok (v{v.versao_atual()})")
    return True


def _sincronizar_versao_nsis():
    """Espelha versao.json nos !define VERSAO e VERSAO_ARQ do instalador NSIS."""
    try:
        v = _carregar_ferramenta_versao()
        v.sincronizar()
    except Exception as e:
        print(f"[build] aviso: não sincronizei a versão do NSIS ({e})")


def main() -> int:
    if not _checar_versao():
        return 1
    _sincronizar_versao_nsis()
    os.chdir(AQUI)
    from PyInstaller.__main__ import run
    run(["--clean", "--noconfirm", "KChrono.spec"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

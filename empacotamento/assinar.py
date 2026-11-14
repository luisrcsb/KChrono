"""Assinatura de código (signtool) do KChrono — Windows.

Assinar o executável e o instalador é a forma correta e recomendada de
reduzir falso positivo de antivírus: um binário com assinatura válida e
timestamp é reconhecido como software legítimo de um autor identificado.

Nada aqui é obrigatório: **sem certificado configurado o script não faz
nada** (no-op) e o build segue normal. A senha nunca fica no código — vem
da variável de ambiente ``KCHRONO_SIGN_PASSWORD``.

Variáveis de ambiente reconhecidas
----------------------------------
    KCHRONO_SIGN_PFX        caminho do certificado .pfx/.p12 (recomendado)
    KCHRONO_SIGN_PASSWORD   senha do .pfx (nunca no código)
    KCHRONO_SIGN_SUBJECT    (alternativa) nome do certificado no repositório
                            do Windows; assina pelo ``/n`` do signtool
    KCHRONO_SIGN_SHA1       (alternativa) thumbprint do certificado; ``/sha1``
    KCHRONO_SIGNTOOL        caminho do signtool.exe (opcional — se ausente o
                            script procura no PATH e nos SDKs do Windows)
    KCHRONO_TIMESTAMP_URL   servidor de timestamp RFC 3161
                            (padrão: http://timestamp.digicert.com)

Uso:
    python empacotamento/assinar.py <arquivo.exe> [<arquivo2.exe> ...]
    python empacotamento/assinar.py --verificar <arquivo.exe>

Saída: código 0 = ok (ou nada a fazer); 1 = falha de assinatura.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

TIMESTAMP_PADRAO = "http://timestamp.digicert.com"

# Locais usuais do signtool.exe (Windows SDK / Visual Studio).
_CAMINHOS_SIGNTOOL = [
    r"C:\Program Files (x86)\Windows Kits\10\bin",
    r"C:\Program Files\Windows Kits\10\bin",
]


def _encontrar_signtool() -> str | None:
    """Devolve o caminho do signtool.exe ou None se não encontrado."""
    env = os.environ.get("KCHRONO_SIGNTOOL")
    if env:
        return env if Path(env).is_file() else None

    no_path = shutil.which("signtool") or shutil.which("signtool.exe")
    if no_path:
        return no_path

    # Procura a versão mais recente do SDK instalada.
    for raiz in _CAMINHOS_SIGNTOOL:
        base = Path(raiz)
        if not base.is_dir():
            continue
        for sub in sorted(base.glob("*/x64/signtool.exe"), reverse=True):
            return str(sub)
    return None


def _montar_comando(signtool: str, arquivo: str) -> list[str] | None:
    """Monta a linha de comando de assinatura, ou None se não configurado."""
    pfx = os.environ.get("KCHRONO_SIGN_PFX")
    senha = os.environ.get("KCHRONO_SIGN_PASSWORD", "")
    subject = os.environ.get("KCHRONO_SIGN_SUBJECT")
    sha1 = os.environ.get("KCHRONO_SIGN_SHA1")
    timestamp = os.environ.get("KCHRONO_TIMESTAMP_URL") or TIMESTAMP_PADRAO

    cmd = [signtool, "sign", "/fd", "sha256",
           "/tr", timestamp, "/td", "sha256",
           "/d", "KChrono - Cronometragem de Kart"]

    if pfx:
        cmd += ["/f", pfx]
        if senha:
            cmd += ["/p", senha]
    elif subject:
        cmd += ["/n", subject]
    elif sha1:
        cmd += ["/sha1", sha1]
    else:
        return None  # nada configurado → no-op

    cmd.append(arquivo)
    return cmd


def _configurado() -> bool:
    return bool(os.environ.get("KCHRONO_SIGN_PFX")
                or os.environ.get("KCHRONO_SIGN_SUBJECT")
                or os.environ.get("KCHRONO_SIGN_SHA1"))


def assinar(arquivos: list[str], silencioso: bool = False) -> bool:
    """Assina os arquivos informados. Sem certificado, não faz nada."""
    if not _configurado():
        if not silencioso:
            print("[assinar] nenhum certificado configurado — assinatura ignorada "
                  "(defina KCHRONO_SIGN_PFX + KCHRONO_SIGN_PASSWORD para assinar).")
        return True

    signtool = _encontrar_signtool()
    if not signtool:
        print("[assinar] signtool.exe não encontrado — defina KCHRONO_SIGNTOOL "
              "com o caminho do signtool.")
        return False

    ok = True
    for arq in arquivos:
        if not Path(arq).is_file():
            print(f"[assinar] arquivo não encontrado: {arq}")
            ok = False
            continue
        cmd = _montar_comando(signtool, arq)
        if cmd is None:
            return True
        if not silencioso:
            print(f"[assinar] {Path(arq).name}")
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            print(f"[assinar] falhou em {Path(arq).name}:\n{proc.stdout}\n{proc.stderr}")
            ok = False
        elif not silencioso:
            print("[assinar] ok")
    return ok


def verificar(arquivo: str) -> bool:
    """Confere a assinatura de um arquivo (signtool verify /pa)."""
    signtool = _encontrar_signtool()
    if not signtool:
        print("[assinar] signtool.exe não encontrado.")
        return False
    proc = subprocess.run([signtool, "verify", "/pa", "/v", arquivo],
                          capture_output=True, text=True)
    print(proc.stdout or proc.stderr)
    return proc.returncode == 0


def main(argv: list[str]) -> int:
    # console do Windows costuma ser cp1252 — nunca quebrar por um acento
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if not argv:
        print(__doc__)
        return 2
    if argv[0] == "--verificar":
        return 0 if verificar(argv[1]) else 1
    return 0 if assinar(argv) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

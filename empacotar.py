"""KChrono — empacotador unificado: sempre gera publicacao/windows e
publicacao/linux.

    python empacotar.py

· Windows: PyInstaller (onefile) + NSIS → publicacao/windows/
· Linux:   Docker (se instalado) → publicacao/linux/; sem Docker, o AppImage
   é gerado pela CI do GitHub Actions (.github/workflows/release.yml) na
   publicação da tag — deixe a pasta linux preenchida por ela.
· No final escreve publicacao/VERSAO.txt (versão, data, commit).

Uma tag (`git tag v1.0.5 && git push origin v1.0.5`) publica a release
com os três pacotes: Setup (Windows), AppImage (Linux) e ISO da live.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
PUB = RAIZ / "publicacao"


def _versao() -> str:
    vfile = RAIZ / "empacotamento" / "versao.json"
    try:
        return json.loads(vfile.read_text(encoding="utf-8"))["versao"]
    except Exception:
        return "?"


def _makensis():
    candidatos = [
        Path(r"C:\Program Files (x86)\NSIS\makensis.exe"),
        Path(r"C:\Program Files\NSIS\makensis.exe"),
    ]
    for c in candidatos:
        if c.exists():
            return str(c)
    return shutil.which("makensis")


def build_windows() -> None:
    if sys.platform != "win32":
        print("[windows] pulando: só é possível buildar o Windows no Windows "
              "(a CI cuida disso na tag).")
        return

    print("== [windows] PyInstaller (onefile)")
    subprocess.run([sys.executable, str(RAIZ / "empacotamento" / "build.py")],
                   check=True, cwd=RAIZ)
    exe = RAIZ / "empacotamento" / "dist" / "KChrono.exe"
    if not exe.exists():
        sys.exit("ERRO: empacotamento/dist/KChrono.exe não foi gerado")

    alvo = PUB / "windows"
    alvo.mkdir(parents=True, exist_ok=True)
    shutil.copy2(exe, alvo / "KChrono.exe")

    makensis = _makensis()
    if not makensis:
        print("[windows] AVISO: makensis não encontrado (instale o NSIS) — "
              "só o exe solto foi copiado.")
        return

    print("== [windows] NSIS (instalador)")
    subprocess.run([makensis, "instalador.nsi"], check=True,
                   cwd=RAIZ / "empacotamento")
    setup = RAIZ / "empacotamento" / "KChrono-Setup.exe"
    if not setup.exists():
        sys.exit("ERRO: KChrono-Setup.exe não foi gerado")
    shutil.copy2(setup, alvo / "KChrono-Setup.exe")
    print(f"OK [windows] publicacao/windows/ (v{_versao()})")


def build_linux() -> None:
    alvo = PUB / "linux"
    alvo.mkdir(parents=True, exist_ok=True)
    leia_me = RAIZ / "empacotamento" / "linux" / "LEIA-ME.txt"
    if leia_me.exists():
        shutil.copy2(leia_me, alvo / "LEIA-ME.txt")

    if shutil.which("docker"):
        print("== [linux] Docker → AppImage (Ubuntu 22.04, glibc 2.35)")
        subprocess.run(["docker", "build", "-t", "kchrono-linux",
                        "-f", "empacotamento/linux/Dockerfile", "."],
                       check=True, cwd=RAIZ)
        subprocess.run(["docker", "run", "--rm",
                        "-v", str(RAIZ).replace("\\", "/") + ":/app",
                        "-w", "/app", "kchrono-linux",
                        "bash", "empacotamento/linux/build_appimage.sh"],
                       check=True, cwd=RAIZ)
        print("OK [linux] publicacao/linux/")
        return

    existentes = sorted(alvo.glob("*.AppImage"))
    if existentes:
        print(f"== [linux] Docker ausente — usando AppImage já baixado: "
              f"{existentes[-1].name}")
    else:
        print("[linux] Docker ausente: o AppImage será gerado pela CI "
              "na publicação da tag (.github/workflows/release.yml). "
              "Baixe o artefato 'publicacao-linux' da run e copie para "
              "publicacao/linux/.")


def escrever_versao_txt() -> None:
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                capture_output=True, text=True,
                                cwd=RAIZ).stdout.strip() or "?"
    except Exception:
        commit = "?"
    texto = (f"KChrono {_versao()}\n"
             f"Data: {time.strftime('%d/%m/%Y %H:%M')}\n"
             f"Commit: {commit}\n")
    (PUB / "VERSAO.txt").write_text(texto, encoding="utf-8")
    print(f"OK publicacao/VERSAO.txt ({_versao()}, commit {commit})")


def main() -> int:
    build_windows()
    build_linux()
    escrever_versao_txt()
    print("\n== publicacao/ ==")
    for p in sorted(PUB.rglob("*")):
        if p.is_file():
            print(f"  {p.relative_to(PUB)}  ({p.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

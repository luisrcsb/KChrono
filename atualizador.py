"""KChrono — verificação, download e instalação de atualizações.

Canal principal: **GitHub Releases** do repositório configurado em
``config.json → atualizacao_repo`` (formato ``usuario/repositorio``,
público). A tag da release é a versão (ex.: ``v1.0.4``) e o asset
``KChrono-Setup.exe`` é o instalador do Windows.

Canal alternativo: uma pasta web qualquer publicando ``versao.json`` com
``"url_base"`` preenchido (formato antigo), para quem hospeda sem GitHub.

Fluxo "Instalar agora": baixa o instalador para
``%APPDATA%\\KChrono\\atualizacoes``, agenda o instalador em silêncio
(NSIS ``/S`` — o NSIS reinstala no diretório gravado no registro) e
encerra o app. Reabrir já é a versão nova; os dados (banco, config,
vozes) ficam em %APPDATA% e não são tocados.

Publicação (uma vez por versão):
    1. crie uma release no GitHub com tag ``v1.0.4`` e anexe o
       ``KChrono-Setup.exe`` como asset;
    2. no Admin → Sobre → Atualizações, informe ``usuario/repo``.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, Optional

from caminhos import dir_dados, dir_recursos

log = logging.getLogger("kchrono.atualizador")

#: o GitHub exige User-Agent em toda requisição
UA = "KChrono-Updater"


def _versao_atual() -> str:
    """Versão embutida no app (empacotamento/versao.json vai dentro do .exe)."""
    for base in (dir_recursos(), Path(__file__).resolve().parent):
        vfile = base / "empacotamento" / "versao.json"
        try:
            if vfile.exists():
                return str(json.loads(vfile.read_text(encoding="utf-8"))
                           .get("versao", "1.0.0"))
        except Exception:
            pass
    return "1.0.0"


VERSAO_ATUAL = _versao_atual()


def _maior(a: str, b: str) -> bool:
    """True se a versão ``a`` for mais nova que ``b`` (ex.: 1.2.0 > 1.1.9)."""
    def t(v: str):
        return [int(x) for x in (v or "0").replace("-", ".").split(".") if x.isdigit()]
    try:
        return t(a) > t(b)
    except Exception:
        return False


def _repo() -> str:
    """Repositório GitHub configurado (usuario/repo) — lido do config.json."""
    try:
        with open(dir_dados() / "config.json", encoding="utf-8-sig") as f:
            return str((json.load(f) or {}).get("atualizacao_repo") or "").strip().strip("/")
    except Exception:
        return ""


def manifesto_local() -> Dict:
    """versao.json embutido (canal 'pasta web' — define o url_base)."""
    caminhos = [dir_recursos() / "empacotamento" / "versao.json"]
    for c in caminhos:
        if c.exists():
            try:
                return json.loads(c.read_text(encoding="utf-8"))
            except Exception as e:
                log.debug("versao.json inválido (%s): %s", c, e)
    return {"versao": VERSAO_ATUAL, "url_base": "", "arquivos": {}}


# ------------------------------------------------------------------ verificação
def verificar() -> Dict:
    """Consulta o canal configurado e diz se há versão nova."""
    repo = _repo()
    if repo:
        return _verificar_github(repo)
    url = (manifesto_local().get("url_base") or "").strip().rstrip("/")
    if url:
        return _verificar_pasta(url)
    return {"versao_atual": VERSAO_ATUAL, "disponivel": False,
            "motivo": "sem canal de atualização — informe o repositório"
                      " (usuario/repo) no Admin → Sobre"}


def _verificar_github(repo: str) -> Dict:
    """Última release do GitHub: a tag é a versão, o .exe é o instalador."""
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            rel = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"versao_atual": VERSAO_ATUAL, "disponivel": False, "erro":
                    f"'{repo}' não tem releases — crie uma release anexando"
                    " o KChrono-Setup.exe"}
        return {"versao_atual": VERSAO_ATUAL, "disponivel": False,
                "erro": f"GitHub respondeu HTTP {e.code}"}
    except Exception as e:
        return {"versao_atual": VERSAO_ATUAL, "disponivel": False, "erro": str(e)}

    nova = str(rel.get("tag_name") or "").lstrip("vV")
    assets = {str(a.get("name") or ""): a for a in (rel.get("assets") or [])}
    return {"versao_atual": VERSAO_ATUAL,
            "versao_remota": nova,
            "disponivel": _maior(nova, VERSAO_ATUAL),
            "repo": repo,
            "canal": f"github · {repo}",
            "notas": (rel.get("body") or "").strip()[:2000],
            "arquivos": _mapa_pacotes(assets)}


def _mapa_pacotes(assets: Dict[str, Dict]) -> Dict:
    """chave de plataforma -> {"url", "nome", "tamanho"} (melhor asset)."""
    mapa: Dict[str, Dict] = {}
    for nome, a in sorted(assets.items()):
        low = nome.lower()
        url = a.get("browser_download_url")
        item = {"url": url, "nome": nome, "tamanho": a.get("size")}
        if low.endswith(".exe") and not mapa.get("windows"):
            mapa["windows"] = item
        elif low.endswith((".tar.gz", ".appimage")) and not mapa.get("linux"):
            mapa["linux"] = item
    return mapa


def _verificar_pasta(url_base: str) -> Dict:
    """Canal legado: pasta web com versao.json + pacotes."""
    try:
        with urllib.request.urlopen(
                urllib.request.Request(f"{url_base}/versao.json",
                                       headers={"User-Agent": UA}), timeout=8) as r:
            remoto = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"versao_atual": VERSAO_ATUAL, "disponivel": False,
                "erro": f"{url_base}: {e}", "url_base": url_base}
    nova = str(remoto.get("versao", ""))
    return {"versao_atual": VERSAO_ATUAL,
            "versao_remota": nova,
            "disponivel": _maior(nova, VERSAO_ATUAL),
            "canal": f"pasta web · {url_base}",
            "url_base": url_base,
            "notas": remoto.get("notas", ""),
            "arquivos": remoto.get("arquivos", {})}


# ---------------------------------------------------------------------- download
def _resolver_pacote(ver: Dict, chave: str) -> Optional[Dict]:
    """Pacote da plataforma: {"url", "nome"} — GitHub (dict) ou pasta web (str)."""
    item = (ver.get("arquivos") or {}).get(chave)
    if isinstance(item, dict) and item.get("url"):
        return item
    if isinstance(item, str) and ver.get("url_base"):
        return {"url": f"{ver['url_base'].rstrip('/')}/{item}", "nome": item}
    return None


def baixar(chave: str = "windows", destino: Optional[str] = None) -> Dict:
    """Baixa o instalador da versão nova para ``%APPDATA%\\KChrono\\atualizacoes``."""
    import requests

    ver = verificar()
    pac = _resolver_pacote(ver, chave)
    if not pac:
        return {"ok": False,
                "erro": ver.get("erro") or ver.get("motivo")
                        or f"não há pacote para '{chave}' nesta versão"}
    pasta = dir_dados() / "atualizacoes"
    pasta.mkdir(parents=True, exist_ok=True)
    destino = destino or str(pasta / pac["nome"])
    try:
        with requests.get(pac["url"], stream=True, timeout=120,
                          headers={"User-Agent": UA}) as r:
            r.raise_for_status()
            with open(destino, "wb") as f:
                for bloco in r.iter_content(chunk_size=1 << 20):
                    f.write(bloco)
    except Exception as e:
        return {"ok": False, "erro": str(e)}
    tamanho = os.path.getsize(destino)
    log.info("atualização baixada: %s (%.1f MB)", destino, tamanho / 1e6)
    return {"ok": True, "arquivo": destino, "versao": ver.get("versao_remota"),
            "tamanho_mb": round(tamanho / 1e6, 1)}


# ----------------------------------------------------------------------- instalar
def instalar(chave: str = "windows", destino: Optional[str] = None) -> Dict:
    """Baixa (se preciso) e executa o instalador em silêncio; fecha o app.

    O instalador precisa dos arquivos liberados: ele é agendado com um
    pequeno atraso e o app se encerra em seguida. O NSIS reinstala no
    diretório anterior (gravado no registro pelo próprio instalador) e os
    dados em %APPDATA% permanecem intactos.
    """
    if sys.platform != "win32":
        return {"ok": False, "erro": "instalação automática disponível apenas no Windows"}
    import subprocess

    ver = verificar()
    if not ver.get("disponivel"):
        return {"ok": False, "erro": ver.get("erro") or "não há versão nova para instalar"}
    b = baixar(chave, destino)
    if not b.get("ok"):
        return b
    caminho = b["arquivo"]
    if not os.path.exists(caminho):
        return {"ok": False, "erro": f"instalador não encontrado em {caminho}"}

    def _rodar_instalador():
        try:
            # NSIS /S = silencioso; o registro guia o diretório de instalação
            subprocess.Popen(
                [caminho, "/S"],
                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0x00000008))
            log.info("instalador executado em silêncio: %s", caminho)
        except Exception:
            log.exception("falha ao executar o instalador %s", caminho)

    threading.Timer(6.0, _rodar_instalador).start()   # espera o app liberar os arquivos
    threading.Timer(2.0, _encerrar_app).start()
    log.info("atualização: v%s agendada (%s)", b.get("versao"), caminho)
    return {"ok": True, "arquivo": caminho, "versao": b.get("versao"),
            "acao": "instalador_agendado"}


def _encerrar_app():
    """Fecha a janela nativa (pywebview) e garante o fim do processo."""
    try:
        import webview
        for janela in (getattr(webview, "windows", None) or []):
            try:
                janela.destroy()
            except Exception:
                pass
    except Exception:
        pass
    threading.Timer(3.0, lambda: os._exit(0)).start()

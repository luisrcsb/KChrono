"""KChrono — verificação e download de atualizações (Fase 7).

O app consulta um ``versao.json`` remoto (o mesmo formato de
``empacotamento/versao.json``) e informa se há versão nova. O download
é feito sob demanda (botão no painel Admin); a aplicação da atualização
é responsabilidade do instalador.

Para habilitar: preencha ``"url_base"`` em versao.json com o endereço
onde o arquivo ``versao.json`` e os pacotes ficam publicados.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from pathlib import Path
from typing import Dict, Optional

from caminhos import dir_recursos

VERSAO_ATUAL = "1.0.0"
log = logging.getLogger("kchrono.atualizador")


def _maior(a: str, b: str) -> bool:
    """True se a versão ``a`` for mais nova que ``b`` (ex.: 1.2.0 > 1.1.9)."""
    def t(v: str):
        return [int(x) for x in (v or "0").replace("-", ".").split(".") if x.isdigit()]
    try:
        return t(a) > t(b)
    except Exception:
        return False


def manifesto_local() -> Dict:
    caminhos = [dir_recursos() / "empacotamento" / "versao.json"]
    for c in caminhos:
        if c.exists():
            try:
                return json.loads(c.read_text(encoding="utf-8"))
            except Exception as e:
                log.debug("versao.json inválido (%s): %s", c, e)
    return {"versao": VERSAO_ATUAL, "url_base": "", "arquivos": {}}


def verificar() -> Dict:
    """Consulta o servidor de atualização e retorna se há versão nova."""
    local = manifesto_local()
    url = (local.get("url_base") or "").strip().rstrip("/")
    if not url:
        return {"versao_atual": VERSAO_ATUAL, "disponivel": False,
                "motivo": "servidor de atualização não configurado"}
    try:
        with urllib.request.urlopen(f"{url}/versao.json", timeout=8) as r:
            remoto = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"versao_atual": VERSAO_ATUAL, "disponivel": False, "erro": str(e)}
    nova = str(remoto.get("versao", ""))
    return {"versao_atual": VERSAO_ATUAL,
            "versao_remota": nova,
            "disponivel": _maior(nova, VERSAO_ATUAL),
            "url_base": url,
            "notas": remoto.get("notas", ""),
            "arquivos": remoto.get("arquivos", {})}


def baixar(chave: str = "windows", destino: Optional[str] = None) -> Dict:
    """Baixa o pacote de atualização indicado (windows|linux) para ``destino``."""
    import os
    import sys

    ver = verificar()
    if not ver.get("url_base"):
        return {"ok": False, "erro": ver.get("motivo", "sem servidor de atualização")}
    arquivo = (ver.get("arquivos") or {}).get(chave)
    if not arquivo:
        return {"ok": False, "erro": f"não há pacote para '{chave}'"}
    url = f"{ver['url_base']}/{arquivo}"
    destino = destino or os.path.join(os.path.expanduser("~"), "Downloads", arquivo)
    try:
        urllib.request.urlretrieve(url, destino)
    except Exception as e:
        return {"ok": False, "erro": str(e)}
    return {"ok": True, "arquivo": destino, "versao": ver.get("versao_remota")}

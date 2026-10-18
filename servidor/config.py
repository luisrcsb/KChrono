"""KChrono — configuração do servidor local (Fase 3)."""
from __future__ import annotations

import json
from typing import Dict

from caminhos import dir_dados

DIR_PROJETO = dir_dados()
CONFIG_PATH = DIR_PROJETO / "config.json"

#: Modelo gravado no primeiro uso (credenciais do projeto KChrono no Firebase)
CONFIG_MODELO = {
    "firebase": {
        "apiKey": "AIzaSyAQMfIgj8t1YpemLgx-xxvftVKco5ML7JU",
        "databaseURL": "https://kchrono-default-rtdb.firebaseio.com",
        "storageBucket": "kchrono.firebasestorage.app",
    },
    "email": "",
    "password": "",
    "pistaId": "krathus",
    "auto_upload": True,          # envia ao finalizar a sessão
    "tempo_minimo_volta_s": 3,
    # driver de cronometragem (Fase 6)
    "decoder_tipo": "p3",         # p3 | easylap | lapwiz
    "decoder_host": "192.168.0.50",
    "decoder_porta": 5403,
    "decoder_auto": True,         # tenta conectar em loop ao abrir o app
    # simulador de corridas (testes/desenvolvimento — nunca resultados oficiais)
    "sim_sistema": "p3",            # fonte simulada: p3 | easylap | lapwiz
    "sim_velocidade": 1.0,          # velocidade da reprodução (0.5 = meio-tempo)
    "telao_tela": 1,                # monitor do telão 2ª tela (0 = principal)
    "voz_contagem": True,           # voz na contagem regressiva/largada
    "contador_s": 10,               # segundos da contagem antes da largada
    # canal de atualização: repositório GitHub (usuario/repo) com releases
    "atualizacao_repo": "",
}


def carregar_config() -> Dict:
    try:
        with open(CONFIG_PATH, encoding="utf-8-sig") as f:
            cfg = json.load(f)
    except (FileNotFoundError, ValueError):
        return dict(CONFIG_MODELO)
    base = dict(CONFIG_MODELO)
    base.update({k: v for k, v in (cfg or {}).items() if v is not None})
    return base


def salvar_config(cfg: Dict):
    tmp = CONFIG_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    tmp.replace(CONFIG_PATH)

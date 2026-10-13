"""KChrono — módulo Gerente de Pista: credenciais e sessões de acesso.

O Gerente de Pista é um controle externo (celular/tablet na rede local) com
login próprio, separado do operador. As credenciais ficam em ``config.json``
(senha com *salt* + PBKDF2-SHA256) e as sessões são tokens opacos em memória.

Nunca há senha em texto puro no arquivo nem no front-end: o cliente envia a
senha uma vez, recebe um token e o usa nas requisições seguintes.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from typing import Dict, List, Optional

from .config import carregar_config, salvar_config

log = logging.getLogger("kchrono.gerente")

#: custo do PBKDF2 (iterações) — equilibra segurança e tempo de login local
ITERACOES = 200_000
#: validade do token de sessão (segundos) — 12 h
TTL_PADRAO_S = 12 * 3600
#: validade do convite do QR Code (segundos) — 30 dias
TTL_CONVITE_S = 30 * 24 * 3600
#: tamanho mínimo da senha do gerente
SENHA_MINIMA = 4


class GerenciadorAcesso:
    """Credenciais do gerente (config.json) + tokens de sessão.

    Os tokens (sessões de senha e convites do QR) são espelhados em
    ``config.json`` (``gerente_tokens``) para **sobreviver a reinícios** do
    servidor — sem isso, todo restart derrubava os celulares conectados e o
    QR de 30 dias morria no primeiro reboot. Expirados são podados na carga.
    """

    def __init__(self, ttl_s: int = TTL_PADRAO_S,
                 ttl_convite_s: int = TTL_CONVITE_S):
        self.ttl_s = ttl_s
        self.ttl_convite_s = ttl_convite_s
        self._tokens: Dict[str, Dict] = {}
        self._carregar_tokens()

    # ---------------------------------------------------------------- credenciais
    def _bloco(self) -> Dict:
        return carregar_config().get("gerente") or {}

    def configurado(self) -> bool:
        b = self._bloco()
        return bool(b.get("usuario") and b.get("senha_hash") and b.get("salt"))

    def usuario(self) -> Optional[str]:
        usuario = self._bloco().get("usuario")
        return str(usuario) if usuario else None

    @staticmethod
    def _hash(senha: str, salt_hex: str) -> str:
        return hashlib.pbkdf2_hmac(
            "sha256", str(senha).encode("utf-8"),
            bytes.fromhex(salt_hex), ITERACOES).hex()

    def definir_credenciais(self, usuario: str, senha: str,
                            trocar: bool = False) -> Dict:
        """Cria (ou troca) as credenciais do gerente. Invalida tokens ativos."""
        usuario = (usuario or "").strip()
        if not usuario:
            raise ValueError("informe o usuário")
        if not senha or len(senha) < SENHA_MINIMA:
            raise ValueError(f"a senha deve ter ao menos {SENHA_MINIMA} caracteres")
        salt = secrets.token_hex(16)
        cfg = carregar_config()
        cfg["gerente"] = {
            "usuario": usuario,
            "salt": salt,
            "senha_hash": self._hash(senha, salt),
            "criado_em": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        salvar_config(cfg)
        self._tokens.clear()
        self._salvar_tokens()
        log.info("credenciais do gerente de pista definidas (usuário %s)", usuario)
        return {"usuario": usuario, "trocou": bool(trocar)}

    def conferir(self, usuario: str, senha: str) -> bool:
        b = self._bloco()
        if not b or not b.get("usuario") or not b.get("salt"):
            return False
        if not hmac.compare_digest(str(b.get("usuario")), str(usuario or "")):
            # compara mesmo assim (evita vazar o usuário pelo tempo de resposta)
            self._hash(senha or "", b.get("salt"))
            return False
        calculado = self._hash(senha or "", b["salt"])
        return hmac.compare_digest(str(b.get("senha_hash") or ""), calculado)

    # ----- tokens de sessão -----
    def _carregar_tokens(self) -> None:
        """Restaura os tokens salvos (sobrevivem a reinícios)."""
        try:
            salvos = carregar_config().get("gerente_tokens") or {}
        except Exception:
            salvos = {}
        agora = time.time()
        self._tokens = {
            t: {"usuario": s.get("usuario"), "convite": bool(s.get("convite")),
                "criado_em": s.get("criado_em", agora),
                "expira": float(s.get("expira", 0))}
            for t, s in salvos.items()
            if isinstance(s, dict) and float(s.get("expira", 0)) > agora
        }

    def _salvar_tokens(self) -> None:
        """Espelha os tokens em config.json (para sobreviver a reinícios)."""
        try:
            cfg = carregar_config()
            cfg["gerente_tokens"] = {
                t: {"usuario": s.get("usuario"),
                    "convite": bool(s.get("convite")),
                    "criado_em": s.get("criado_em"),
                    "expira": s.get("expira")}
                for t, s in self._tokens.items()
            }
            salvar_config(cfg)
        except Exception as e:
            log.warning("não foi possível persistir tokens do gerente: %s", e)

    def criar_token(self, usuario: Optional[str] = None) -> str:
        usuario = usuario or self.usuario() or "gerente"
        token = secrets.token_urlsafe(32)
        self._tokens[token] = {"usuario": usuario, "expira": time.time() + self.ttl_s}
        self.limpar_expirados()
        self._salvar_tokens()
        return token

    def validar(self, token: Optional[str]) -> Optional[Dict]:
        if not token:
            return None
        sessao = self._tokens.get(token)
        if not sessao:
            return None
        if sessao["expira"] < time.time():
            self._tokens.pop(token, None)
            self._salvar_tokens()
            return None
        return {"usuario": sessao["usuario"]}

    def revogar(self, token: Optional[str]) -> bool:
        if not token:
            return False
        saiu = self._tokens.pop(token, None) is not None
        if saiu:
            self._salvar_tokens()
        return saiu

    # ----- convites (QR Code) -----
    def criar_convite(self, ttl_s: Optional[int] = None,
                      rotulo: str = "qrcode",
                      preservar: Optional[str] = None) -> Dict:
        """Emite um novo token pelo QR Code — **rotaciona** os antigos.

        Cada QR substitui o anterior: quem estava usando o QR velho perde o
        acesso no próximo comando. Assim o convite vive pouco e não fica
        circulando em print de tela por semanas.

        ``preservar`` mantém vivo o token de quem pediu (quando ele próprio
        entrou por QR), para não derrubar a própria sessão.
        """
        ttl = int(ttl_s or self.ttl_convite_s)
        substituidos = self.revogar_convites(preservar=preservar)
        token = secrets.token_urlsafe(24)
        self._tokens[token] = {
            "usuario": rotulo,
            "convite": True,
            "criado_em": time.time(),
            "expira": time.time() + ttl,
        }
        self.limpar_expirados()
        self._salvar_tokens()
        log.info("convite (QR) criado — válido por %ss, %s substituído(s)",
                 ttl, substituidos)
        return {"token": token, "expira_em": time.time() + ttl,
                "ttl_s": ttl, "substituidos": substituidos}

    def convites(self) -> List[Dict]:
        """Convites ainda válidos (para a tela poder revogar)."""
        self.limpar_expirados()
        agora = time.time()
        return [{"token": t, "rotulo": s.get("usuario"),
                 "expira_em": s.get("expira"),
                 "restante_s": int(max(0, s.get("expira", 0) - agora))}
                for t, s in self._tokens.items() if s.get("convite")]

    def revogar_convites(self, preservar: Optional[str] = None) -> int:
        """Invalida os QR Codes emitidos (a senha continua valendo).

        Com ``preservar`` informado, esse token sobrevive — usado para não
        derrubar a sessão de quem acabou de gerar o QR.
        """
        self.limpar_expirados()
        alvos = [t for t, s in self._tokens.items()
                 if s.get("convite") and t != preservar]
        for t in alvos:
            self._tokens.pop(t, None)
        if alvos:
            log.info("%s convite(s) de acesso (QR) revogado(s)", len(alvos))
            self._salvar_tokens()
        return len(alvos)

    def limpar_expirados(self) -> int:
        agora = time.time()
        vencidos = [t for t, s in self._tokens.items() if s["expira"] < agora]
        for t in vencidos:
            self._tokens.pop(t, None)
        if vencidos:
            self._salvar_tokens()
        return len(vencidos)


#: instância única usada pela API
acesso = GerenciadorAcesso()

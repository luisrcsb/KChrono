"""KChrono — sincronização com o CTAD (Fase 3)."""
from .ctad_client import CtadClient, ErroAuth, ErroBanco
from .sincronizador import Sincronizador, gerar_resumo

__all__ = ["CtadClient", "ErroAuth", "ErroBanco", "Sincronizador", "gerar_resumo"]

"""KChrono — infraestrutura i18n (gettext) para Python."""
from __future__ import annotations
import gettext
from pathlib import Path
from threading import local

_thread_local = local()

# Caminho base dos arquivos .mo compilados
LOCALE_DIR = Path(__file__).resolve().parent.parent / "i18n"

# Guarda a instância de tradução ativa
_tradução_ativa = None

# Idioma ativo por thread (padrão pt_BR)
def get_idioma() -> str:
    return getattr(_thread_local, "idioma", "pt_BR")

def set_idioma(lang: str):
    """Define o idioma para a thread atual."""
    _thread_local.idioma = lang
    _instalar(lang)

def _instalar(lang: str):
    """Instala a tradução gettext globalmente."""
    global _tradução_ativa
    try:
        _tradução_ativa = gettext.translation("kchrono", localedir=str(LOCALE_DIR), languages=[lang], fallback=True)
        _tradução_ativa.install()
    except FileNotFoundError:
        _tradução_ativa = gettext.NullTranslations()
        _tradução_ativa.install()

# Inicializa com pt_BR
_instalar("pt_BR")

def _(texto: str) -> str:
    """Função de tradução ativa na thread."""
    if _tradução_ativa:
        return _tradução_ativa.gettext(texto)
    return gettext.gettext(texto)

def n_(singular: str, plural: str, n: int) -> str:
    """Tradução com plural."""
    if _tradução_ativa:
        return _tradução_ativa.ngettext(singular, plural, n)
    return gettext.ngettext(singular, plural, n)

# Conveniência
def idiomas_disponiveis() -> list[str]:
    return ["pt_BR", "en_US"]

def nome_idioma(codigo: str) -> str:
    return {"pt_BR": "Português (Brasil)", "en_US": "English (US)"}.get(codigo, codigo)
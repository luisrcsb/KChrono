"""KChrono — QR Code da área do Gerente de Pista.

Gera o QR em PNG (via ``segno``, puro Python, sem dependências) e devolve
como *data URI*, para o front-end só precisar colocar em um ``<img>``.
PNG foi escolhido de propósito: renderiza em qualquer navegador ou WebView,
enquanto o SVG em data URI falha em alguns (o QR chegava mas não exibia).
Nada de arquivo em disco nem cache.
"""
from __future__ import annotations

import base64
import io
import socket
from typing import Optional

try:
    import segno
except ImportError:                                  # pragma: no cover
    segno = None


def disponivel() -> bool:
    return segno is not None


def ip_lan() -> Optional[str]:
    """IP da máquina na rede local (para o QR abrir no celular).

    Truque do socket UDP: descobre o IP da rota padrão sem enviar nada.
    Se falhar, devolve ``None`` e quem chama decide o fallback.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            return ip if ip and not ip.startswith("127.") else None
        finally:
            s.close()
    except Exception:
        return None


def base_url_para_qr(hospedeiro: Optional[str], porta: Optional[int]) -> str:
    """Base do endereço embutido no QR.

    REGRA DE OURO: nunca ``localhost`` — no celular, localhost é o próprio
    celular (não conecta e cai na tela de login). Se o pedido veio de
    localhost, troca pelo IP da LAN; se já veio pela rede, mantém o host.
    """
    porta = porta or 8780
    if not hospedeiro or hospedeiro in ("127.0.0.1", "localhost", "::1"):
        return f"http://{ip_lan() or 'localhost'}:{porta}"
    if "://" in hospedeiro:
        return hospedeiro.rstrip("/")
    return f"http://{hospedeiro}:{porta}"


def data_uri(texto: str, escala: int = 8, cor: str = "#000000",
             fundo: str = "#ffffff") -> str:
    """QR como ``data:image/png;base64,...`` pronto para ``<img src>``.

    ``escala`` é o tamanho de cada módulo (quadradinho) do QR em pixels.
    """
    if segno is None:
        raise RuntimeError("biblioteca 'segno' não instalada "
                           "(pip install segno)")
    texto = str(texto or "")
    if not texto:
        raise ValueError("texto do QR vazio")
    # erro 'm' (~15% de correção): aguenta um QR meio sujo/riscado na tela
    qr = segno.make(texto, error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="png", scale=escala, dark=cor, light=fundo)
    return ("data:image/png;base64,"
            + base64.b64encode(buf.getvalue()).decode("ascii"))


def tamanho_modulos(texto: str) -> int:
    """Quantidade de módulos do QR (para calcular o tamanho na tela)."""
    if segno is None:
        return 0
    return len(getattr(segno.make(str(texto or "")), "matrix", []) or [])

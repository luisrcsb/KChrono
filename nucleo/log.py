"""KChrono — logging com severidades em PT-BR (Fase 1.5).

Codificação por severidade (requisito do console do operador):
  · INFO  (branco/cinza) — tráfego normal;
  · AVISO (amarelo)      — ghost lap, tempo mínimo violado, avisos de hardware;
  · ERRO  (vermelho)     — falhas críticas, transponder não cadastrado.

Cores ANSI quando o terminal suporta (habilitado automaticamente no Windows).
Projetado para não quebrar em terminais sem cor/cp1252.
"""
from __future__ import annotations

import logging
import sys

_LEVEL_PT = {logging.INFO: "INFO", logging.WARNING: "AVISO", logging.ERROR: "ERRO",
             logging.DEBUG: "DEBUG", logging.CRITICAL: "CRITICO"}

_CORES = {logging.WARNING: "\033[93m",   # amarelo
          logging.ERROR: "\033[91m",     # vermelho
          logging.CRITICAL: "\033[91m"}
_RESET = "\033[0m"


def habilitar_ansi_windows() -> bool:
    """Ativa sequências ANSI no console do Windows (Win10+)."""
    if sys.platform != "win32":
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        modo = ctypes.c_uint32(0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        return bool(kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), modo) or True)
    except Exception:
        return False


class _Formatador(logging.Formatter):
    def __init__(self, com_cor: bool):
        super().__init__(datefmt="%H:%M:%S")
        self.com_cor = com_cor

    def format(self, record):
        nivel = _LEVEL_PT.get(record.levelno, record.levelname)
        msg = record.getMessage()
        linha = f"{self.formatTime(record, self.datefmt)} {nivel:<7} {msg}"
        if self.com_cor and record.levelno in _CORES:
            return f"{_CORES[record.levelno]}{linha}{_RESET}"
        return linha


def configurar_log(nivel: int = logging.INFO) -> logging.Logger:
    raiz = logging.getLogger("kchrono")
    raiz.setLevel(nivel)
    if not raiz.handlers:
        try:
            # UTF-8 com replace: acentos/emoji nunca derrubam o log
            # (stdout redirecionado no Windows é cp1252 por padrão)
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_Formatador(com_cor=habilitar_ansi_windows()))
        raiz.addHandler(handler)
        raiz.propagate = False
    return raiz

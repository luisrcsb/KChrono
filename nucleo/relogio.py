"""KChrono — relógio de alta precisão e monitor de drift (Fase 1.5).

- Windows: QueryPerformanceCounter (API nativa, resolução sub-microsegundo);
- Linux/macOS: clock_gettime(CLOCK_MONOTONIC);
- MonitorDrift: compara o RTC do decoder com o relógio local do PC e avisa
  quando a diferença passar do limite (evita voltas com tempo "furado").
"""
from __future__ import annotations

import ctypes
import sys
import time
from typing import Optional

_US_POR_SEGUNDO = 1_000_000


# ---------------------------------------------------------------- relógio local
if sys.platform == "win32":
    _kernel32 = ctypes.windll.kernel32
    _freq = ctypes.c_longlong(0)
    if not _kernel32.QueryPerformanceFrequency(ctypes.byref(_freq)):
        raise OSError("QueryPerformanceFrequency falhou")
    _FREQ = _freq.value

    def agora_monotonic_us() -> int:
        """Microssegundos desde um ponto arbitrário (monotônico, não sofre NTP)."""
        contador = ctypes.c_longlong(0)
        _kernel32.QueryPerformanceCounter(ctypes.byref(contador))
        return contador.value * _US_POR_SEGUNDO // _FREQ
else:
    def agora_monotonic_us() -> int:
        return time.clock_gettime(time.CLOCK_MONOTONIC)


def agora_epoch_us() -> int:
    """Microssegundos desde epoch Unix (para comparar com o RTC dos decoders)."""
    return time.time_ns() // 1000


# ---------------------------------------------------------------- monitor de drift
class MonitorDrift:
    """Observa a diferença entre o RTC do decoder e o relógio local.

    Uso: a cada STATUS/heartbeat do driver, chamar observar(rtc_decoder_us).
    Se a diferença absoluta passar do limite, devolve o drift (µs) para alerta.
    """

    def __init__(self, limite_us: int = 500_000):
        self.limite_us = limite_us
        self.ultimo_drift_us: Optional[int] = None

    def observar(self, rtc_decoder_us: Optional[int]) -> Optional[int]:
        if not rtc_decoder_us:
            return None
        drift = int(rtc_decoder_us - agora_epoch_us())
        self.ultimo_drift_us = drift
        if abs(drift) > self.limite_us:
            return drift
        return None

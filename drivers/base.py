"""KChrono — interfaces comuns aos drivers de cronometragem.

Cada driver traduz o protocolo de um sistema de cronometragem para os
eventos definidos aqui (Passing, Status) — o núcleo do KChrono só fala
essa língua, independente do hardware usado na pista.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Dict, Optional


@dataclass
class Passing:
    """Uma passagem (volta) capturada por um decodificador."""
    transponder: Optional[int] = None
    rtc_time: Optional[int] = None          # tempo do decoder em microssegundos
    passing_number: Optional[int] = None
    strength: Optional[int] = None          # força do sinal
    hits: Optional[int] = None              # acertos do sinal
    decoder_id: Optional[int] = None
    brutos: Dict[str, Any] = field(default_factory=dict)  # campos não catalogados
    recebido_em: datetime = field(default_factory=datetime.now)

    @property
    def timestamp_ms(self) -> Optional[Decimal]:
        """RTC_TIME do decoder convertido para milissegundos."""
        if self.rtc_time is None:
            return None
        return Decimal(self.rtc_time) / 1000


@dataclass
class Status:
    """Estado do hardware (ruído, temperatura, tensão...)."""
    temperatura: Optional[int] = None
    tensao: Optional[Decimal] = None        # volts
    ruido: Optional[int] = None
    gps: Optional[int] = None
    satelites: Optional[int] = None
    decoder_id: Optional[int] = None
    brutos: Dict[str, Any] = field(default_factory=dict)
    recebido_em: datetime = field(default_factory=datetime.now)


#: Assinatura dos callbacks: (evento, pacote_cru) -> None
Callback = Callable[[Any, Any], None]


class Decoder(ABC):
    """Interface que todo driver de cronometragem implementa."""

    @abstractmethod
    async def connect(self) -> None:
        """Abre a conexão com o decodificador."""

    @abstractmethod
    async def read_loop(self,
                        on_passing: Optional[Callback] = None,
                        on_status: Optional[Callback] = None,
                        on_desconhecido: Optional[Callback] = None) -> None:
        """Lê o stream até a conexão fechar, chamando os callbacks por evento.

        `on_desconhecido` recebe o pacote cru (dict) de tipos ainda não catalogados.
        """

    @abstractmethod
    async def close(self) -> None:
        """Fecha a conexão."""

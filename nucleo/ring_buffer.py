"""KChrono — ring buffer thread-safe com descarte seguro (Fase 1.5).

Protege a ingestão em picos de tráfego (ex.: largada com muitos carros
passando quase juntos): pacotes novos nunca travem o produtor; itens mais
antigos são descartados com contabilidade quando aenche — anomalias ficam
registradas em vez de travar a thread.
"""
from __future__ import annotations

import threading
from collections import deque
from typing import Deque, Generic, List, Optional, TypeVar

T = TypeVar("T")


class RingBuffer(Generic[T]):
    """Buffer circular limitado com estatísticas de descarte."""

    def __init__(self, capacidade: int):
        if capacidade < 1:
            raise ValueError("capacidade deve ser >= 1")
        self.capacidade = capacidade
        self._itens: Deque[T] = deque(maxlen=capacidade)
        self._lock = threading.Lock()
        self.recebidos = 0
        self.descartados = 0

    def push(self, item: T) -> bool:
        """Insere um item. False se descartou o item mais antigo (buffer cheio)."""
        with self._lock:
            cheio = len(self._itens) == self.capacidade
            if cheio:
                self.descartados += 1
            self._itens.append(item)  # deque(maxlen) descarta o mais antigo
            self.recebidos += 1
            return not cheio

    def pop(self) -> Optional[T]:
        with self._lock:
            return self._itens.popleft() if self._itens else None

    def pop_tudo(self) -> List[T]:
        with self._lock:
            itens = list(self._itens)
            self._itens.clear()
            return itens

    @property
    def tamanho(self) -> int:
        with self._lock:
            return len(self._itens)

    def stats(self) -> dict:
        with self._lock:
            return {"capacidade": self.capacidade, "tamanho": len(self._itens),
                    "recebidos": self.recebidos, "descartados": self.descartados}

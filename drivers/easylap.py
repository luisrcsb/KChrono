"""KChrono — driver EASYLAP-USB (Fase 6).

O EASYLAP-USB é compatível com o protocolo **Robitronic serial**, documentado
publicamente (Flip Side Racing — flipsideracing.org, wiki RobitronicSerial):

  · 38400 baud, 8N1 (porta COM virtual via USB)
  · init: ``03 B9 01`` → decoder responde ``00`` e passa a transmitir
  · pacote de carro detectado:
      [len][checksum][0x84][UID 2B LE][00 00][tempo ms 4B LE][hits][strength]
  · pacote de timestamp (~1/s):
      [len][checksum][0x83][tempo 4B LE][14 D0 01 02]
  · sem delimitador: o 1º byte é o tamanho total do pacote

Uso:
    from drivers.easylap import EasyLap
    driver = EasyLap(porta="COM3")        # ou porta=None p/ auto-detectar
    await driver.connect()
    await driver.read_loop(on_passing=tratar_volta)
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, List, Optional

from .base import Callback, Decoder, Passing

log = logging.getLogger("kchrono.driver.easylap")

INIT = bytes([0x03, 0xB9, 0x01])   # inicializa a comunicação
TIPO_CARRO = 0x84
TIPO_TIMESTAMP = 0x83
#: faixa plausível do byte de comprimento (o protocolo usa pacotes de ~8-14 B);
#: fora disso = byte de lixo/dessincronismo -> ressincroniza
TAM_MIN, TAM_MAX = 4, 64


class EasyLap(Decoder):
    """Cliente do EASYLAP-USB (serial 38400 8N1, protocolo Robitronic)."""

    def __init__(self, porta: Optional[str] = None, baud: int = 38400,
                 timeout: float = 1.0):
        self.porta = porta
        self.baud = baud
        self.timeout = timeout
        self._serial = None
        self.conectado = False
        self._buffer = b""
        self._sequencia = 0
        self._ultimo_tempo_ms = None
        self.porta_usada: Optional[str] = None
        self.stats = {"pacotes": 0, "ressincronizacoes": 0, "erros_leitura": 0}

    # ----- portas disponíveis -----
    @staticmethod
    def listar_portas() -> List[str]:
        try:
            import serial.tools.list_ports
            return [p.device for p in serial.tools.list_ports.comports()]
        except Exception:
            return []

    def _abrir_serial(self):
        import serial
        candidatas = [self.porta] if self.porta else self.listar_portas() or \
            [f"COM{i}" for i in range(1, 17)]
        for porta in candidatas:
            try:
                ser = serial.Serial(porta, self.baud, bytesize=8, parity="N",
                                    stopbits=1, timeout=self.timeout)
                ser.reset_input_buffer()
                ser.write(INIT)
                ser.flush()
                self._serial = ser
                self.porta_usada = porta
                log.info("EASYLAP conectado em %s (%d baud)", porta, self.baud)
                return
            except Exception as e:
                log.debug("porta %s indisponível: %s", porta, e)
        raise OSError("nenhuma porta serial do EASYLAP encontrada "
                      "(conecte o USB e instale o driver)")

    async def connect(self) -> None:
        if self.conectado:
            return
        self._abrir_serial()
        self.conectado = True

    async def read_loop(self,
                        on_passing: Optional[Callback] = None,
                        on_status: Optional[Callback] = None,
                        on_desconhecido: Optional[Callback] = None) -> None:
        if not self.conectado:
            raise RuntimeError("chame connect() antes de read_loop()")
        loop = asyncio.get_running_loop()
        while self.conectado:
            # leitura bloqueante em executor (não trave o event loop)
            dados = await loop.run_in_executor(None, self._ler_com_timeout)
            if dados:
                self._buffer += dados
                for pacote in self._extrair_pacotes():
                    self._processar(pacote, on_passing, on_status, on_desconhecido)

    def _ler_com_timeout(self, tamanho: int = 512) -> bytes:
        try:
            return self._serial.read(tamanho)   # devolve o que tiver (timeout 1s)
        except Exception as e:
            log.warning("erro lendo serial: %s", e)
            self.stats["erros_leitura"] += 1
            self.conectado = False
            return b""

    def _extrair_pacotes(self) -> List[bytes]:
        """Extrai pacotes validados do buffer (1º byte = tamanho total).

        Robustez v1.0.7: comprimento improvável (0, gigante) ou tipo sem o
        bit alto = dessincronismo -> descarta 1 byte e ressincroniza. Antes,
        um comprimento 0 travava o buffer em loop infinito.
        """
        pacotes = []
        while self._buffer:
            tam = self._buffer[0]
            if tam < TAM_MIN or tam > TAM_MAX:
                self._buffer = self._buffer[1:]
                self.stats["ressincronizacoes"] += 1
                continue
            if len(self._buffer) < tam:
                break
            pacote = self._buffer[:tam]
            if not (pacote[2] & 0x80):      # tipos conhecidos: 0x83/0x84
                self._buffer = self._buffer[1:]
                self.stats["ressincronizacoes"] += 1
                continue
            self._buffer = self._buffer[tam:]
            pacotes.append(pacote)
        return pacotes

    def _processar(self, pacote: bytes, on_passing, on_status, on_desconhecido):
        if len(pacote) < 4:
            return
        tipo = pacote[2]
        if tipo == TIPO_CARRO and len(pacote) >= 13:
            self.stats["pacotes"] += 1
            uid = pacote[3] | (pacote[4] << 8)
            tempo_ms = (pacote[8] | (pacote[9] << 8)
                        | (pacote[10] << 16) | (pacote[11] << 24))
            hits = pacote[12]
            strength = pacote[13] if len(pacote) > 13 else None
            self._sequencia += 1
            passing = Passing(
                transponder=uid,
                rtc_time=int(time.time() * 1_000_000),   # relógio local (µs)
                passing_number=self._sequencia,
                strength=strength, hits=hits)
            if on_passing:
                on_passing(passing, {"raw": pacote.hex()})
        elif tipo == TIPO_TIMESTAMP:
            self._ultimo_tempo_ms = int.from_bytes(pacote[3:7], "little") \
                if len(pacote) >= 7 else None
            if on_desconhecido:
                on_desconhecido({"tor": "timestamp", "tempo_ms": self._ultimo_tempo_ms,
                                 "raw": pacote.hex()})
        else:
            if on_desconhecido:
                on_desconhecido({"tipo": tipo, "raw": pacote.hex()})

    async def close(self) -> None:
        self.conectado = False
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
        log.info("EASYLAP desconectado")

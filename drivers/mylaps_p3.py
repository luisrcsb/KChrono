"""Driver MyLaps/AMB P3 — TCP 5403, protocolo binário.

Especificação completa (com amostras reais capturadas do decoder da pista):
docs/PROTOCOLO-P3.md

Uso típico:
    decoder = MyLapsP3("192.168.0.50")
    await decoder.connect()
    await decoder.read_loop(on_passing=tratar_volta)
"""
from __future__ import annotations

import asyncio
import logging
import struct
from decimal import Decimal
from typing import Callable, Dict, Optional, Tuple

from .base import Callback, Decoder, Passing, Status

log = logging.getLogger("kchrono.driver.p3")

# --- constantes do framing ---
START, END, ESCAPE = 0x8E, 0x8F, 0x8D
ESCAPE_OFFSET = 0x20

# --- tipos de mensagem (TOR) ---
TOR_PASSING = 0x01
TOR_STATUS = 0x02

# --- ids de campos TLV ---
F_DECODER_ID = 0x81
F_PASSING_NUMBER = 0x01
F_TRANSPONDER = 0x03
F_RTC_TIME = 0x04
F_STRENGTH = 0x05
F_HITS = 0x06
F_RUIDO = 0x01
F_GPS = 0x06
F_TEMPERATURA = 0x07
F_SATELITES = 0x0A
F_TENSAO = 0x0C

_FMT_POR_TAMANHO = {1: "<B", 2: "<H", 4: "<I", 8: "<Q"}


def unescape(dados: bytes) -> bytes:
    """Desfaz o byte-stuffing do P3: 8D xx -> (xx + 0x20).

    Nota: o parser de referência open-source subtrai 0x20; a direção +0x20
    é a logicamente consistente com o encoding. Fica validado contra uma
    passagem real que contenha 0x8E/0x8F/0x8D no payload.
    """
    saida = bytearray()
    i = 0
    while i < len(dados):
        if dados[i] == ESCAPE and i + 1 < len(dados):
            saida.append((dados[i + 1] + ESCAPE_OFFSET) & 0xFF)
            i += 2
        else:
            saida.append(dados[i])
            i += 1
    return bytes(saida)


def extrair_frames(buffer: bytes) -> Tuple[list, bytes]:
    """Extrai frames completos (8E..8F) do buffer.

    Retorna (lista_de_frames, resto_do_buffer).
    """
    frames = []
    pos = 0
    while True:
        inicio = buffer.find(b"\x8e", pos)
        if inicio == -1:
            break
        fim = buffer.find(b"\x8f", inicio + 1)
        if fim == -1:
            break
        frames.append(buffer[inicio:fim + 1])
        pos = fim + 1
    return frames, buffer[pos:]


def parse_frame(frame: bytes) -> Dict:
    """Decodifica um frame P3.

    Retorna dict com header (versao/tamanho/crc/flags/tor) e campos TLV
    mapeados id -> valor inteiro (ou hex para tamanhos não-inteiros).
    """
    if len(frame) < 12 or frame[0] != START or frame[-1] != END:
        raise ValueError(f"frame inválido ({len(frame)} bytes)")
    versao, tamanho, crc, flags, tor = struct.unpack("<BHHHH", frame[1:10])

    dados = unescape(frame)
    campos: Dict[int, object] = {}
    pos = 10
    while pos < len(dados) - 1:
        campo, tam = dados[pos], dados[pos + 1]
        valor_raw = dados[pos + 2:pos + 2 + tam]
        fmt = _FMT_POR_TAMANHO.get(tam)
        if fmt is not None and len(valor_raw) == tam:
            valor = struct.unpack(fmt, valor_raw)[0]
        else:
            valor = valor_raw.hex()  # campo não-inteiro ou tamanho inesperado
        campos[campo] = valor
        pos += 2 + tam

    return {"versao": versao, "tamanho": tamanho, "crc": crc, "flags": flags,
            "tor": tor, "campos": campos, "brutos_hex": dados[10:-1].hex()}


def evento_do_pacote(pacote: Dict):
    """Converte um pacote parseado em Passing/Status, ou None se desconhecido."""
    tor, campos = pacote["tor"], pacote["campos"]
    if tor == TOR_PASSING:
        return Passing(
            transponder=campos.get(F_TRANSPONDER),
            rtc_time=campos.get(F_RTC_TIME),
            passing_number=campos.get(F_PASSING_NUMBER),
            strength=campos.get(F_STRENGTH),
            hits=campos.get(F_HITS),
            decoder_id=campos.get(F_DECODER_ID),
            brutos={f"0x{k:02x}": v for k, v in campos.items()},
        )
    if tor == TOR_STATUS:
        tensao_raw = campos.get(F_TENSAO)
        return Status(
            temperatura=campos.get(F_TEMPERATURA),
            ruido=campos.get(F_RUIDO),
            gps=campos.get(F_GPS),
            satelites=campos.get(F_SATELITES),
            tensao=Decimal(tensao_raw) / 10 if tensao_raw is not None else None,
            decoder_id=campos.get(F_DECODER_ID),
            brutos={f"0x{k:02x}": v for k, v in campos.items()},
        )
    return None


class MyLapsP3(Decoder):
    """Cliente do decodificador MyLaps/AMB P3.

    Read-only por design: conecta e apenas escuta o stream (status + passings),
    sem enviar comandos que alterem estado do decoder.
    """

    def __init__(self, host: str, porta: int = 5403, timeout: float = 5.0):
        self.host = host
        self.porta = porta
        self.timeout = timeout
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._buffer = b""
        self.conectado = False

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.porta), self.timeout)
        self.conectado = True
        log.info("conectado em %s:%d", self.host, self.porta)

    async def read_loop(self,
                        on_passing: Optional[Callback] = None,
                        on_status: Optional[Callback] = None,
                        on_desconhecido: Optional[Callback] = None) -> None:
        if not self.conectado:
            raise RuntimeError("chame connect() antes de read_loop()")
        while True:
            dados = await self._reader.read(4096)
            if not dados:
                log.warning("conexão encerrada pelo decoder")
                break
            self._buffer += dados
            frames, self._buffer = extrair_frames(self._buffer)
            for frame in frames:
                try:
                    pacote = parse_frame(frame)
                except ValueError as e:
                    log.warning("frame descartado: %s", e)
                    continue
                evento = evento_do_pacote(pacote)
                if isinstance(evento, Passing) and on_passing:
                    on_passing(evento, pacote)
                elif isinstance(evento, Status) and on_status:
                    on_status(evento, pacote)
                elif on_desconhecido:
                    on_desconhecido(pacote)

    async def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
        self.conectado = False
        log.info("conexão fechada")

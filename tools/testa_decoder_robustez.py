"""Testes de robustez da leitura do decoder (sem hardware real).

Rode: python tools/testa_decoder_robustez.py

Cobre:
  1) P3: validacao de header/TLV (frame corrompido descartado, nao vira volta);
  2) P3: ressincronismo do buffer (lixo sem start byte nao trava a leitura);
  3) P3: canais redundantes (2 conexoes TCP) + dedup de passings;
  4) P3: reabertura automatica de canal morto (self-heal com backoff);
  5) P3: timeout de silencio (conexao zumbi detectada -> RuntimeError);
  6) EASYLAP: comprimento 0 nao trava mais o buffer + ressincronismo de lixo.
"""
from __future__ import annotations

import asyncio
import logging
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from drivers.easylap import EasyLap                       # noqa: E402
from drivers.mylaps_p3 import MyLapsP3, parse_frame       # noqa: E402

logging.basicConfig(level=logging.CRITICAL)

# status real capturado do decoder (docs/PROTOCOLO-P3.md sec. 4, amostra B)
STATUS_HEX = "8E021F00CCB50000020001023900070223000C01790601008104221604008F"

FALHAS: list = []


def check(cond: bool, msg: str) -> None:
    if cond:
        print(f"  OK    {msg}")
    else:
        print(f"  FALHA {msg}")
        FALHAS.append(msg)


def frame_passing(num: int, transponder: int = 9000001) -> bytes:
    """Monta um frame P3 de passing valido (sem bytes que exijam escaping)."""
    campos = b"".join([
        bytes([0x01, 2]) + struct.pack("<H", num % 0xFFFF),
        bytes([0x03, 4]) + struct.pack("<I", transponder),
        bytes([0x04, 8]) + struct.pack("<Q", 0x0101010101010100 + (num & 0x3F)),
        bytes([0x81, 4]) + struct.pack("<I", 0x12345678),
    ])
    corpo = struct.pack("<BHHHH", 2, 11 + len(campos), 0, 0, 0x0001) + campos
    frame = b"\x8e" + corpo + b"\x8f"
    assert len(frame) == 11 + len(campos)
    return frame


# ----------------------------------------------------------------- P3 puro
def teste_parse_validacao() -> None:
    print("[1] P3: validacao de header/TLV")
    a = parse_frame(bytes.fromhex(
        "8E021B0009C400001C00010897497E7C3DBABD248104221604008F"))
    check(a["tor"] == 0x1C, "amostra real A (tor 0x1C) decodificada")
    b = parse_frame(bytes.fromhex(STATUS_HEX))
    check(b["tor"] == 0x02 and b["campos"][0x0C] == 121,
          "amostra real B (status, tensao 12.1V) decodificada")

    try:   # tamanho declarado 0 != 12 do frame
        parse_frame(b"\x8e\x02\x00\x00" + b"\x00" * 7 + b"\x01\x02\x03\x8f")
        check(False, "tamanho inconsistente rejeitado")
    except ValueError:
        check(True, "tamanho inconsistente rejeitado")

    try:   # campo TLV pede 143 B e estoura o frame de 12
        parse_frame(b"\x8e\x02\x0c\x00" + b"\x00" * 6 + b"\x03" + b"\x8f")
        check(False, "TLV estourando o frame rejeitado")
    except ValueError:
        check(True, "TLV estourando o frame rejeitado")


def teste_ressincronismo() -> None:
    print("[2] P3: ressincronismo do buffer")
    d = MyLapsP3("x")
    eventos = []
    d._processar_dados(0, b"\x41" * 8192,
                       lambda p, pac: eventos.append(p), None, None)
    check(d.stats["ressincronizacoes"] >= 1 and d._buffers.get(0, b"") == b"",
          "lixo de 8 KB sem start byte descartado (sem crescimento infinito)")
    d._processar_dados(0, frame_passing(1),
                       lambda p, pac: eventos.append(p), None, None)
    check(len(eventos) == 1 and d.stats["frames"] == 1,
          "frame valido apos o lixo ainda decodificado")
    d._processar_dados(0, b"\x8e\x02\x00\x00" + b"\x00" * 17 + b"\x8f",
                       lambda p, pac: eventos.append(p), None, None)
    check(d.stats["descartados"] >= 1 and len(eventos) == 1,
          "frame corrompido descartado (nao virou passing)")


# --------------------------------------------------- decoder fake p/ rede
class ServidorFake:
    """Decoder P3 de mentira: status ao conectar + broadcast de passings."""

    def __init__(self, modo: str = "broadcast"):
        self.modo = modo                     # broadcast | mudo_apos_status
        self.conexoes: list = []
        self.total_conexoes = 0
        self._num = 0
        self._tarefa = None
        self._server = None

    async def abrir(self) -> int:
        self._server = await asyncio.start_server(self._aceitar,
                                                  "127.0.0.1", 0)
        return self._server.sockets[0].getsockname()[1]

    async def _aceitar(self, leitor, escritor):
        self.total_conexoes += 1
        self.conexoes.append([leitor, escritor])
        escritor.write(bytes.fromhex(STATUS_HEX))
        await escritor.drain()
        if self.modo == "broadcast" and self._tarefa is None:
            self._tarefa = asyncio.create_task(self._transmitir())

    async def _transmitir(self):
        while True:
            self._num += 1
            frame = frame_passing(self._num)
            vivos = []
            for par in self.conexoes:
                try:
                    par[1].write(frame)
                    await par[1].drain()
                    vivos.append(par)
                except Exception:
                    pass
            self.conexoes = vivos
            await asyncio.sleep(0.15)

    async def matar_mais_antigo(self) -> None:
        if self.conexoes:
            _, escritor = self.conexoes.pop(0)
            try:
                escritor.close()
            except Exception:
                pass

    async def fechar(self) -> None:
        if self._tarefa:
            self._tarefa.cancel()
        if self._server:
            self._server.close()
        for _, escritor in self.conexoes:
            try:
                escritor.close()
            except Exception:
                pass


async def teste_canais_redundantes() -> None:
    print("[3+4] P3: canais redundantes + dedup + reabertura de canal")
    srv = ServidorFake("broadcast")
    porta = await srv.abrir()
    recebidos: list = []
    d = MyLapsP3("127.0.0.1", porta, timeout=2, redundante=True,
                 timeout_leitura=10)
    await d.connect()
    check(d.canais_ativos == 2, "connect redundante abre 2 canais TCP")
    task = asyncio.create_task(
        d.read_loop(on_passing=lambda p, pac: recebidos.append(
            (p.transponder, p.rtc_time, p.passing_number))))

    await asyncio.sleep(1.2)
    fase_a = len(recebidos)
    check(fase_a > 3, f"passings recebidos na fase A ({fase_a})")
    check(d.stats["duplicados"] > 0, "dedup entre canais ativo (duplicados > 0)")
    check(len(recebidos) == len(set(recebidos)),
          "nenhum passing entregue em duplicidade")

    await srv.matar_mais_antigo()           # mata o canal primario
    await asyncio.sleep(1.0)
    check(len(recebidos) > fase_a,
          "canal secundario seguiu recebendo apos a queda do primario")

    await asyncio.sleep(5.6)                # supervisor reabre apos 5 s
    check(srv.total_conexoes >= 3,
          f"canal morto reaberto sozinho ({srv.total_conexoes} conexoes)")
    check(d.canais_ativos == 2, "2 canais ativos apos o self-heal")
    check(not task.done(), "read_loop segue vivo apos queda de canal")

    await d.close()
    await srv.fechar()
    try:
        await asyncio.wait_for(task, 3)
    except Exception:
        pass
    check(task.done(), "close() encerra o read_loop limpo")


async def teste_timeout_zumbi() -> None:
    print("[5] P3: timeout de silencio (conexao zumbi)")
    srv = ServidorFake("mudo_apos_status")
    porta = await srv.abrir()
    d = MyLapsP3("127.0.0.1", porta, timeout=2, redundante=False,
                 timeout_leitura=0.8)
    leitor, escritor = await d._abrir_canal()
    d._canais = [(leitor, escritor)]
    d._buffers = {0: b""}
    d.conectado = True
    t0 = time.monotonic()
    erro = None
    try:
        await asyncio.wait_for(d._ler_canal(0, leitor, (None, None, None)), 5)
    except RuntimeError as e:
        erro = str(e)
    dur = time.monotonic() - t0
    check(erro is not None and "sem dados" in erro and 0.8 <= dur <= 3,
          f"silencio detectado como erro em {dur:.1f}s")
    await d.close()
    await srv.fechar()


# ------------------------------------------------------------- EASYLAP
def teste_easylap() -> None:
    print("[6] EASYLAP: comprimento 0 + ressincronismo")
    e = EasyLap(porta="COM99")
    pacote = (bytes([0x0E, 0x00, 0x84]) + struct.pack("<H", 1234)
              + b"\x00\x00\x00" + struct.pack("<I", 5000) + bytes([10, 99]))
    e._buffer = b"\x00\x01\x02abc"          # comprimento 0 = loop infinito antes
    check(e._extrair_pacotes() == [] and e.stats["ressincronizacoes"] >= 5,
          "comprimento 0 nao trava o buffer (lixeira ressincroniza)")
    e._buffer = b"\xff\xff" + pacote
    check(e._extrair_pacotes() == [pacote],
          "pacote valido recuperado apos 2 bytes de lixo")
    e._buffer = b"\x0e\x00\x41" + b"\xff\x01\x7f\x00" * 8
    check(e._extrair_pacotes() == [] and e.stats["ressincronizacoes"] > 0,
          "tipo invalido (sem bit alto) ressincroniza")
    passings = []
    e._processar(pacote, lambda p, raw: passings.append(p), None, None)
    check(bool(passings) and passings[0].transponder == 1234
          and passings[0].hits == 10 and passings[0].strength == 99,
          "pacote de carro valido vira Passing")


async def main() -> None:
    teste_parse_validacao()
    teste_ressincronismo()
    await teste_canais_redundantes()
    await teste_timeout_zumbi()
    teste_easylap()
    print()
    if FALHAS:
        print(f"FALHAS: {len(FALHAS)}")
        for f in FALHAS:
            print(f"  - {f}")
        sys.exit(1)
    print("TODOS OS TESTES PASSARAM")


if __name__ == "__main__":
    asyncio.run(main())

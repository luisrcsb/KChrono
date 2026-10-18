"""Driver MyLaps/AMB P3 — TCP 5403, protocolo binário.

Especificação completa (com amostras reais capturadas do decoder da pista):
docs/PROTOCOLO-P3.md

Robustez de leitura/v1.0.7:
  · validação do header (campo `tamanho`) e dos campos TLV — frame corrompido
    é descartado antes de virar um passing falso;
  · ressincronismo do buffer por canal (lixo sem start byte ou frame gigante
    incompleto não trava mais a leitura);
  · timeout de silêncio por canal — conexão zumbi (TCP vivo mas mudo) é
    detectada e reaberta automaticamente;
  · TCP keepalive no socket (metade morta detectada pelo próprio SO);
  · canais redundantes: 2 conexões TCP simultâneas ao mesmo decoder (o P3
    aceita até 4) — se um canal cair, o outro segue recebendo e o canal morto
    é reaberto sozinho; passings vindos dos dois canais são deduplicados;
  · estatísticas de recepção (bytes/frames/descartados/duplicados/ressinc).

Uso típico:
    decoder = MyLapsP3("192.168.0.50")
    await decoder.connect()
    await decoder.read_loop(on_passing=tratar_volta)
"""
from __future__ import annotations

import asyncio
import logging
import socket
import struct
import time
from decimal import Decimal
from typing import Callable, Dict, List, Optional, Tuple

from .base import Callback, Decoder, Passing, Status

log = logging.getLogger("kchrono.driver.p3")

# --- constantes do framing ---
START, END, ESCAPE = 0x8E, 0x8F, 0x8D
ESCAPE_OFFSET = 0x20

#: buffer de um canal acima disso sem frame completo = lixo no fio
TAM_MAX_FRAME = 4096
#: janela de deduplicação de passings entre canais (s)
JANELA_DEDUP_S = 10.0
#: reaberturas seguidas sem receber um byte sequer antes de desistir do canal
ABERTURAS_SEM_DADOS_MAX = 3
#: tentativas de reabertura de um canal (5 s de espera entre cada)
REABERTURAS_MAX = 6

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
    """Decodifica um frame P3 com validação de integridade.

    Validações (frame corrompido levanta ValueError = descartado):
      · `tamanho` do header bate com o comprimento real (só quando não há
        byte-stuffing — com escaping o comprimento no fio difere);
      · campos TLV cabem dentro do frame.

    Retorna dict com header (versao/tamanho/crc/flags/tor) e campos TLV
    mapeados id -> valor inteiro (ou hex para tamanhos não-inteiros).
    """
    if len(frame) < 12 or frame[0] != START or frame[-1] != END:
        raise ValueError(f"frame inválido ({len(frame)} bytes)")
    versao, tamanho, crc, flags, tor = struct.unpack("<BHHHH", frame[1:10])
    if ESCAPE not in frame and tamanho != len(frame):
        raise ValueError(f"tamanho declarado {tamanho} != {len(frame)} do frame")

    dados = unescape(frame)
    campos: Dict[int, object] = {}
    pos = 10
    while pos < len(dados) - 1:
        campo, tam = dados[pos], dados[pos + 1]
        if pos + 2 + tam > len(dados) - 1:
            raise ValueError(f"campo 0x{campo:02x} ({tam} B) estoura o frame")
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

    Robustez:
      · `redundante=True` mantém 2 conexões TCP (o P3 aceita até 4) — se um
        canal cair, o outro segue e o canal morto é reaberto com backoff;
      · `timeout_leitura` (45 s) detecta conexão zumbi (TCP vivo, dados mortos)
        e força a reabertura do canal;
      · frames corrompidos são validados (header + TLV) e contabilizados.
    """

    def __init__(self, host: str, porta: int = 5403, timeout: float = 5.0,
                 redundante: bool = True, timeout_leitura: float = 45.0):
        self.host = host
        self.porta = porta
        self.timeout = timeout
        self.redundante = bool(redundante)
        self.timeout_leitura = float(timeout_leitura)
        self._canais: List[Tuple[asyncio.StreamReader, asyncio.StreamWriter]] = []
        self._buffers: Dict[int, bytes] = {}
        self._tarefas: List[asyncio.Task] = []
        self._vistos: Dict[tuple, float] = {}
        self._fechando = False
        self.conectado = False
        #: estatísticas de recepção (expostas no snapshot do servidor)
        self.stats = {"bytes": 0, "frames": 0, "descartados": 0,
                      "duplicados": 0, "ressincronizacoes": 0}

    @property
    def canais_ativos(self) -> int:
        """Canais TCP vivos (supervisores ainda rodando, ou abertos)."""
        if self._tarefas:
            return sum(1 for t in self._tarefas if not t.done())
        return len(self._canais)

    # ------------------------------------------------------------- conexão
    async def _abrir_canal(self) -> Tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """Abre um canal TCP e liga o keepalive (detecta metade morta)."""
        leitor, escritor = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.porta), self.timeout)
        sock = escritor.get_extra_info("socket")
        if sock is not None:
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                for nome, valor in (("TCP_KEEPIDLE", 20), ("TCP_KEEPINTVL", 10),
                                    ("TCP_KEEPCNT", 4)):
                    const = getattr(socket, nome, None)
                    if const is not None:
                        sock.setsockopt(socket.IPPROTO_TCP, const, valor)
            except OSError:
                pass  # best-effort: keepalive é camada extra, não obrigatória
        return leitor, escritor

    async def _fechar_canais(self) -> None:
        canais, self._canais = self._canais, []
        self._buffers = {}
        for _, escritor in canais:
            try:
                escritor.close()
            except Exception:
                pass
        for _, escritor in canais:
            try:
                await escritor.wait_closed()
            except Exception:
                pass

    async def connect(self) -> None:
        await self._fechar_canais()
        self._fechando = False
        canal = await self._abrir_canal()          # primário (falha = erro)
        self._canais = [canal]
        self._buffers = {0: b""}
        self.conectado = True
        if self.redundante:
            try:
                self._canais.append(await self._abrir_canal())
                self._buffers[1] = b""
                log.info("conectado em %s:%d · 2 canais (redundante)",
                         self.host, self.porta)
            except (OSError, asyncio.TimeoutError) as e:
                log.info("canal redundante indisponível (%s) — seguindo com "
                         "1 canal", e)
        else:
            log.info("conectado em %s:%d", self.host, self.porta)

    # -------------------------------------------------------------- leitura
    async def read_loop(self,
                        on_passing: Optional[Callback] = None,
                        on_status: Optional[Callback] = None,
                        on_desconhecido: Optional[Callback] = None) -> None:
        if not self.conectado or not self._canais:
            raise RuntimeError("chame connect() antes de read_loop()")
        cb = (on_passing, on_status, on_desconhecido)
        self._tarefas = [asyncio.create_task(self._supervisionar(i, canal, cb))
                         for i, canal in enumerate(self._canais)]
        resultados = await asyncio.gather(*self._tarefas,
                                          return_exceptions=True)
        self._tarefas = []
        for r in resultados:
            if isinstance(r, Exception):
                log.warning("supervisor de canal terminou com erro: %s", r)
        if self.conectado and not self._fechando:
            log.warning("todos os canais do decoder desistiram")

    async def _supervisionar(self, indice: int, canal, cb) -> None:
        """Mantém um canal vivo: lê até falhar; reabre com backoff; desiste
        (e deixa o servidor reconectar tudo) após N falhas ou N aberturas
        sem receber um único byte."""
        leitor, escritor = canal
        aberturas_mudas = 0
        try:
            while self.conectado and not self._fechando:
                antes = self.stats["bytes"]
                erro = None
                try:
                    await self._ler_canal(indice, leitor, cb)
                    erro = "decoder encerrou o canal"
                except Exception as e:
                    erro = str(e)
                try:
                    escritor.close()
                except Exception:
                    pass
                if not (self.conectado and not self._fechando):
                    break
                if self.stats["bytes"] > antes:
                    aberturas_mudas = 0
                else:
                    aberturas_mudas += 1
                    if aberturas_mudas >= ABERTURAS_SEM_DADOS_MAX:
                        log.warning("canal %d mudo em %d aberturas seguidas "
                                    "— desistindo do canal", indice,
                                    aberturas_mudas)
                        break
                log.warning("canal %d caiu (%s) — reabrindo em 5s...", indice, erro)
                novo = None
                for tent in range(REABERTURAS_MAX):
                    await asyncio.sleep(5)
                    if not (self.conectado and not self._fechando):
                        break
                    try:
                        novo = await self._abrir_canal()
                        break
                    except (OSError, asyncio.TimeoutError) as e:
                        log.debug("canal %d: reabertura %d/%d falhou: %s",
                                  indice, tent + 1, REABERTURAS_MAX, e)
                if novo is None:
                    if self.conectado and not self._fechando:
                        log.warning("canal %d: %d reaberturas falhadas "
                                    "— desistindo do canal", indice,
                                    REABERTURAS_MAX)
                    break
                leitor, escritor = novo
                self._buffers[indice] = b""
        finally:
            try:
                escritor.close()
            except Exception:
                pass

    async def _ler_canal(self, indice: int, leitor: asyncio.StreamReader,
                         cb: tuple) -> None:
        """Loop de leitura de um canal. Levanta em timeout de silêncio (conexão
        zumbi) ou quando o decoder fecha a conexão."""
        on_passing, on_status, on_desconhecido = cb
        while self.conectado and not self._fechando:
            try:
                dados = await asyncio.wait_for(leitor.read(4096),
                                               self.timeout_leitura)
            except asyncio.TimeoutError:
                raise RuntimeError(f"sem dados do decoder há "
                                   f"{self.timeout_leitura:.0f}s")
            if not dados:
                raise ConnectionError("conexão encerrada pelo decoder")
            self.stats["bytes"] += len(dados)
            self._processar_dados(indice, dados, on_passing, on_status,
                                  on_desconhecido)

    # ------------------------------------------------------------ parsing
    def _processar_dados(self, indice: int, dados: bytes,
                         on_passing, on_status, on_desconhecido) -> None:
        """Framing + parse + dedup de um bloco recebido em um canal."""
        buffer = self._buffers.get(indice, b"") + dados
        frames, resto = extrair_frames(buffer)
        if len(resto) > TAM_MAX_FRAME:
            # nunca chegou frame completo até aqui = lixo/dessincronismo:
            # ressincroniza a partir do último start byte (ou zera)
            self.stats["ressincronizacoes"] += 1
            idx = resto.rfind(b"\x8e")
            resto = resto[idx:] if idx != -1 else b""
            if len(resto) > TAM_MAX_FRAME:
                resto = b""       # start gigante sem fim: descarta de vez
        self._buffers[indice] = resto
        for frame in frames:
            try:
                pacote = parse_frame(frame)
            except ValueError as e:
                self.stats["descartados"] += 1
                log.warning("frame descartado: %s", e)
                continue
            self.stats["frames"] += 1
            evento = evento_do_pacote(pacote)
            if isinstance(evento, Passing):
                if self._passing_duplicado(evento):
                    self.stats["duplicados"] += 1
                    continue
                if on_passing:
                    on_passing(evento, pacote)
            elif isinstance(evento, Status):
                if on_status:
                    on_status(evento, pacote)
            elif on_desconhecido:
                on_desconhecido(pacote)

    def _passing_duplicado(self, passing: Passing) -> bool:
        """Mesmo passing chegou pelo outro canal (ou retransmissão).

        Chave = (transponder, rtc_time em µs, passing_number): eventos
        distintos nunca repetem os três campos.
        """
        chave = (passing.transponder, passing.rtc_time, passing.passing_number)
        agora = time.monotonic()
        if len(self._vistos) > 512:
            corta = agora - JANELA_DEDUP_S
            self._vistos = {k: t for k, t in self._vistos.items() if t > corta}
        visto = self._vistos.get(chave)
        self._vistos[chave] = agora
        return visto is not None and (agora - visto) <= JANELA_DEDUP_S

    # ------------------------------------------------------------- fechamento
    async def close(self) -> None:
        self._fechando = True
        self.conectado = False
        tarefas, self._tarefas = self._tarefas, []
        for tarefa in tarefas:
            if not tarefa.done():
                tarefa.cancel()
        if tarefas:
            await asyncio.gather(*tarefas, return_exceptions=True)
        await self._fechar_canais()
        log.info("conexão fechada · %s", self.stats)

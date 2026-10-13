"""KChrono — driver SKYRC LapWiz RT004 (Fase 6) — Bluetooth BLE.

O LapWiz se comunica por **Bluetooth** (o USB-C é só para carga) e o protocolo
do app SkyRC não é público. Este driver prepara o terreno:

  1. scan BLE por dispositivos LapWiz;
  2. conexão + descoberta de serviços/características (GATT);
  3. subscrição em todas as características notificáveis;
  4. log estruturado (hex) de cada notificação — material para decodificar o
     protocolo em uma sessão de engenharia reversa ao vivo (igual fizemos com
     o MyLaps P3).

Quando o formato for decodificado, basta implementar `_decodificar()` — o
restante da estrutura já está pronto.
"""
from __future__ import annotations

import logging
from typing import Callable, List, Optional

from .base import Callback, Decoder, Passing

log = logging.getLogger("kchrono.driver.lapwiz")

NOMES_LAPWIZ = ("lapwiz", "skyrc", "rt004")
TEMPO_ESPERA_SCAN_S = 8.0


class LapWiz(Decoder):
    """Cliente BLE do SKYRC LapWiz (descoberta + captura passiva)."""

    def __init__(self, endereco: Optional[str] = None, tempo_scan: float = TEMPO_ESPERA_SCAN_S):
        self.endereco = endereco          # None = descobrir por nome
        self.tempo_scan = tempo_scan
        self._client = None
        self.conectado = False
        self._caracteristicas: List = []

    # ----- descoberta -----
    async def descobrir(self) -> List[dict]:
        try:
            from bleak import BleakScanner
        except ImportError:
            raise OSError("bleak não instalado (pip install bleak)")
        achados = []
        dispositivos = await BleakScanner.discover(timeout=self.tempo_scan)
        for d in dispositivos:
            nome = (d.name or "").lower()
            if any(p in nome for p in NOMES_LAPWIZ) or self.endereco == d.address:
                achados.append({"nome": d.name, "endereco": d.address})
                log.info("LapWiz encontrado: %s (%s)", d.name, d.address)
        return achados

    async def connect(self) -> None:
        if self.conectado:
            return
        try:
            from bleak import BleakClient
        except ImportError:
            raise OSError("bleak não instalado (pip install bleak)")

        if not self.endereco:
            achados = await self.descobrir()
            if not achados:
                raise OSError("nenhum LapWiz encontrado no scan BLE "
                              "(ligue o timing unit e aproxime)")
            self.endereco = achados[0]["endereco"]

        client = BleakClient(self.endereco)
        await client.connect()
        self._client = client
        self.conectado = True
        log.info("LapWiz conectado: %s", self.endereco)

        # descobre serviços e características
        self._caracteristicas = []
        for servico in client.services:
            for car in servico.characteristics:
                self._caracteristicas.append(car)
                log.info("GATT %s %s — props: %s", car.uuid, str(car.description),
                         list(car.properties))
        self._notificacoes = 0

    async def read_loop(self,
                        on_passing: Optional[Callback] = None,
                        on_status: Optional[Callback] = None,
                        on_desconhecido: Optional[Callback] = None) -> None:
        if not self.conectado:
            raise RuntimeError("chame connect() antes de read_loop()")

        def _cb(caracteristica, dados: bytearray):
            self._notificacoes += 1
            hexa = dados.hex()
            log.info("[LapWiz notify #%d] %s = %s", self._notificacoes,
                     caracteristica.uuid, hexa)
            if on_desconhecido:
                on_desconhecido({"servico": "lapwiz",
                                 "caracteristica": str(caracteristica.uuid),
                                 "hex": hexa})
            evento = self._decodificar(bytes(dados))
            if evento and on_passing:
                on_passing(evento, {"raw": hexa})

        # subscreve em tudo que aceita notificação
        for car in self._caracteristicas:
            if "notify" in car.properties or "indicate" in car.properties:
                try:
                    await self._client.start_notify(car.uuid, _cb)
                except Exception as e:
                    log.debug("não foi possível subscrever %s: %s", car.uuid, e)

        log.info("LapWiz: %d característica(s) monitorada(s) — capturando…",
                 len([c for c in self._caracteristicas
                      if "notify" in c.properties or "indicate" in c.properties]))
        while self.conectado:
            await asyncio.sleep(1)
            if self._client and not self._client.is_connected:
                log.warning("LapWiz desconectou")
                break

    def _decodificar(self, dados: bytes) -> Optional[Passing]:
        """PROTOCOLO AINDA NÃO DECODIFICADO — decodifique aqui após a RE ao vivo.

        Quando descoberto (ex.: byte de tipo + UID + tempo), retorne:
            Passing(transponder=uid, rtc_time=..., strength=..., hits=...)
        """
        return None

    async def close(self) -> None:
        self.conectado = False
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:
                pass
        log.info("LapWiz desconectado")

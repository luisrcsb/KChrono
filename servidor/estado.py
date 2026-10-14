"""KChrono — estado global da aplicação (servidor local).

Ponte entre o driver (hardware), o motor de corrida e a interface web:
uma task asyncio lê o decoder, alimenta o motor e publica eventos para
todos os clientes conectados (WebSocket).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Dict, List, Optional

from drivers.base import Passing, Status
from drivers.mylaps_p3 import MyLapsP3
from nucleo import Banco, MotorCorrida, TipoSessao
from nucleo.campeonatos import (PADRAO_PILOTOS_POR_CHAVE, PilotoCamp, Regulamento,
                                calcular_pontos, gerar_heats, montar_grids_campeonato,
                                ranking_geral, validar_espectro)
from nucleo.relogio import MonitorDrift, agora_epoch_us, agora_monotonic_us
from nucleo.ring_buffer import RingBuffer
from sync import CtadClient, ErroAuth, Sincronizador
from caminhos import dir_dados
from .config import carregar_config, salvar_config
from .som import OPCOES_SOM_PADRAO, ModuloSom

log = logging.getLogger("kchrono.estado")

TRANS_PONDER_DEMO = 7096340   # último transponder validado em pista
PILOTO_DEMO = "Krathus (demo)"

#: transponder -> piloto (Fase 2: cadastro manual; Fase 3: espelho do CTAD)
CADASTRO_TRANSPONDERS = {TRANS_PONDER_DEMO: 1}


class EstadoApp:
    """Singleton do servidor — uma instância por processo."""

    def __init__(self, host_decoder: str = "192.168.0.50", porta_decoder: int = 5403):
        # banco persistente em dados/kchrono.db (histórico de voltas)
        pasta_dados = dir_dados() / "dados"
        pasta_dados.mkdir(exist_ok=True)
        self.banco = Banco(str(pasta_dados / "kchrono.db"))
        self.driver = MyLapsP3(host_decoder, porta_decoder)
        self.motor: Optional[MotorCorrida] = None
        self.sessao_id: Optional[str] = None
        self.conectado = False
        self.pausado = False
        self.drift = MonitorDrift()
        self.ring = RingBuffer(1000)       # picos da largada
        self.eventos: List[Dict] = []      # log Recente p/ interface (máx 200)
        self._filas: List[asyncio.Queue] = []
        self._task_decoder: Optional[asyncio.Task] = None
        self._task_vigia: Optional[asyncio.Task] = None
        #: loop de auto-conexão do boot (conectar em loop até conseguir)
        self._task_auto_conectar: Optional[asyncio.Task] = None
        self._ultimo_status: Optional[Dict] = None
        #: o operador quer conexão (liga no conectar, desliga no desconectar —
        #: base do auto-reconnect e do watchdog de silêncio)
        self._quer_decoder = False
        #: último frame recebido do decoder (qualquer tipo) — watchdog
        self._ultimo_rx_us: Optional[int] = None
        self._aviso_silencio_em: float = 0.0
        self.contadores = {"passings_validos": 0, "ghost_laps": 0, "gaps": 0,
                           "sem_piloto": 0}
        self.inicio_sessao_us: Optional[int] = None
        #: cronômetro da sessão: tempo congelado ao finalizar + pausas acumuladas
        self._tempo_final_s: Optional[float] = None
        self._pausa_inicio_us: Optional[int] = None
        self._pausado_total_us: int = 0
        self.parametros: Dict = {"duracao": 10, "criterio": "tempo",
                                 "tempo_minimo_volta_s": 3}
        self.som = ModuloSom(ativo=True)
        # recordes para locução (carregados a cada sessão) e tarefa de posições
        self._recorde_pista_us: Optional[int] = None
        self._recorde_pessoal: Dict[int, int] = {}
        self._ultima_leitura_voltas = 0
        self._task_posicoes: Optional[asyncio.Task] = None

        # --- Gerente de pista: estado da pista + check-in dos pilotos ---
        #: bandeira atual: verde | amarela | vermelha | fechada
        self.bandeira = "verde"
        self.bandeira_motivo = ""
        #: pilotos confirmados (check-in) — só eles entram na próxima sessão
        self.presentes: set = set()

        # --- Campeonato (tipo de sessão em etapas, avanço manual) ---
        #: {"plano": {...}, "indice": int} enquanto um campeonato está em andamento
        self.campeonato_ativo: Optional[Dict] = None

        # --- Fase 3: sincronização com o CTAD ---
        self.config = carregar_config()
        self.sincronizador = Sincronizador(
            banco=self.banco,
            pista_id=self.config.get("pistaId", "krathus"))

        # driver inicial conforme a config (p3 | easylap | lapwiz)
        try:
            self.driver = self._criar_driver(
                self.config.get("decoder_tipo", "p3"),
                self.config.get("decoder_host"))
        except ValueError as e:
            log.warning("config de decoder inválida (%s) — usando MyLaps P3", e)

        # Fase 4: aplica as preferências de voz/som salvas em config.json
        self._aplicar_config_som()

        # Gerente de pista: restaura o check-in salvo em config.json
        self._carregar_checkin()

        # piloto de demonstração — só semeia em banco vazio, para não duplicar
        # nem "roubar" o transponder quando o usuário renomeia o piloto demo.
        if not self.banco.listar_pilotos():
            self._piloto_demo_id = self.banco.criar_piloto(PILOTO_DEMO, "demo")
            self.banco.vincular_transponder(TRANS_PONDER_DEMO, self._piloto_demo_id)
        else:
            demo = self.banco.piloto_do_transponder(TRANS_PONDER_DEMO)
            self._piloto_demo_id = demo.id if demo else None

    # ---------------------------------------------------------------- websocket
    def assinar(self) -> asyncio.Queue:
        fila: asyncio.Queue = asyncio.Queue()
        self._filas.append(fila)
        return fila

    def cancelar(self, fila: asyncio.Queue):
        if fila in self._filas:
            self._filas.remove(fila)

    def publicar(self, tipo: str, dados: Dict):
        # "tipo"/"ts" são o canal e o carimbo do evento — dados nunca os
        # sobrescrevem (ex.: iniciar sessão manda "tipo": "treino" nos dados,
        # que antes apagava o "tipo": "sessao" e o frontend descartava o evento).
        limpos = {k: v for k, v in (dados or {}).items() if k not in ("tipo", "ts")}
        evento = {"tipo": tipo, "ts": time.strftime("%H:%M:%S"), **limpos}
        self.eventos.append(evento)
        del self.eventos[:-200]
        for fila in list(self._filas):
            try:
                fila.put_nowait(evento)
            except asyncio.QueueFull:
                pass

    # ---------------------------------------------------------------- decoder
    def _on_rejeicao(self, transponder: int, tempo_us: int, passing_number):
        """Callback de ghost lap — registra e publica para a interface."""
        self.contadores["ghost_laps"] += 1
        self.publicar("ghost_lap", {"transponder": transponder})
        self.som.ghost_lap()
        log.info("ghost lap rejeitado: transponder %s, delta %.3fs < tempo mínimo",
                 transponder, tempo_us / 1e6)

    def _criar_driver(self, tipo: str, alvo: Optional[str] = None):
        """Fábrica de drivers — p3 (MyLaps) | easylap (serial) | lapwiz (BLE)."""
        if tipo == "p3":
            return MyLapsP3(alvo or self.config.get("decoder_host", "192.168.0.50"),
                            int(self.config.get("decoder_porta", 5403)))
        if tipo == "easylap":
            from drivers.easylap import EasyLap
            return EasyLap(porta=alvo)
        if tipo == "lapwiz":
            from drivers.lapwiz import LapWiz
            return LapWiz(endereco=alvo)
        raise ValueError(f"driver desconhecido: {tipo}")

    async def desconectar_decoder(self) -> None:
        """Encerra o driver atual e a tarefa de leitura, se houver."""
        self._quer_decoder = False
        self.parar_auto_conectar()
        if self._task_decoder and not self._task_decoder.done():
            self._task_decoder.cancel()
            try:
                await self._task_decoder
            except (asyncio.CancelledError, Exception):
                pass
        self._task_decoder = None
        if self._task_vigia and not self._task_vigia.done():
            self._task_vigia.cancel()
            try:
                await self._task_vigia
            except (asyncio.CancelledError, Exception):
                pass
        self._task_vigia = None
        if self.driver is not None:
            try:
                await self.driver.close()
            except Exception as e:
                log.debug("erro fechando driver: %s", e)
        self.conectado = False

    def _garantir_vigia(self):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._task_vigia is None or self._task_vigia.done():
            self._task_vigia = asyncio.create_task(self._vigiar_decoder())

    # ------------------------------------------------- auto-conexão (boot)
    def decoder_auto_ativo(self) -> bool:
        """Checkbox 'Conectar ao abrir' (padrão ligado)."""
        return bool(self.config.get("decoder_auto", True))

    def definir_decoder_auto(self, ativo: bool) -> Dict:
        cfg = carregar_config()
        cfg["decoder_auto"] = bool(ativo)
        salvar_config(cfg)
        self.config = cfg
        if ativo:
            self.iniciar_auto_conectar()
        else:
            self.parar_auto_conectar()
        return {"ok": True, "ativo": bool(ativo)}

    def telao_tela(self) -> Dict:
        """Monitor escolhido para o telão (Configurações → Telão)."""
        try:
            indice = max(0, int(self.config.get("telao_tela", 1)))
        except (TypeError, ValueError):
            indice = 1
        return {"indice": indice}

    def definir_telao_tela(self, indice: int) -> Dict:
        try:
            indice = max(0, int(indice))
        except (TypeError, ValueError):
            raise ValueError("tela inválida")
        cfg = carregar_config()
        cfg["telao_tela"] = indice
        salvar_config(cfg)
        self.config = cfg
        return {"ok": True, "indice": indice}

    def iniciar_auto_conectar(self):
        """Dispara o loop de conexão do boot (se ligado e ainda desconectado)."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        if not self.decoder_auto_ativo() or self.conectado:
            return
        if self._task_auto_conectar is None or self._task_auto_conectar.done():
            self._task_auto_conectar = asyncio.create_task(self._loop_auto_conectar())

    def parar_auto_conectar(self):
        if self._task_auto_conectar and not self._task_auto_conectar.done():
            self._task_auto_conectar.cancel()
        self._task_auto_conectar = None

    def _apos_conectar(self, tipo: str, como: str = "conectado"):
        """Estado comum após (re)conexão bem-sucedida."""
        self._quer_decoder = True
        self.conectado = True
        self._ultimo_rx_us = agora_monotonic_us()
        self.config["decoder_tipo"] = tipo
        self.publicar("sistema", {"msg": f"decoder {tipo} {como}"
                                         + (f" ({getattr(self.driver, 'porta_usada', '')})"
                                            if getattr(self.driver, "porta_usada", None)
                                            else "")})
        self._task_decoder = asyncio.create_task(self._ler_decoder())
        self._garantir_vigia()

    async def _loop_auto_conectar(self):
        """Tenta conectar em loop até conseguir (ou até desligarem a chave)."""
        try:
            tentativa = 0
            while self.decoder_auto_ativo() and not self.conectado:
                tentativa += 1
                tipo = self.config.get("decoder_tipo", "p3")
                if tentativa == 1:
                    log.info("auto-conexão do decoder (%s) em loop...", tipo)
                try:
                    self.driver = self._criar_driver(tipo, None)
                    await self.driver.connect()
                except (OSError, asyncio.TimeoutError, ValueError) as e:
                    if tentativa == 1:
                        self.publicar("erro", {"msg": f"auto-conexão: {e}"
                                                        " — tentando em loop..."})
                    log.debug("auto-conexão tentativa %d falhou: %s", tentativa, e)
                    await asyncio.sleep(5)
                    continue
                self._apos_conectar(tipo, "conectado (auto-conexão)")
                break
        except asyncio.CancelledError:
            pass

    async def _vigiar_decoder(self):
        """Watchdog: conectado mas sem frames há >20 s = algo errado na rede."""
        try:
            while self._quer_decoder:
                await asyncio.sleep(5)
                if not (self._quer_decoder and self.conectado and self._ultimo_rx_us):
                    continue
                gap = (agora_monotonic_us() - self._ultimo_rx_us) / 1e6
                if gap > 20 and time.monotonic() - self._aviso_silencio_em > 60:
                    self._aviso_silencio_em = time.monotonic()
                    log.warning("decoder silencioso há %.0fs", gap)
                    self.publicar("aviso", {"msg":
                        f"decoder conectado mas sem enviar dados há {gap:.0f}s — "
                        "verifique rede/cabo/loop (o P3 aceita no máx 4 conexões)"})
        except asyncio.CancelledError:
            pass

    async def _tentar_reconectar(self):
        """Loop de auto-reconnect após queda (para no desconectar manual)."""
        try:
            while self._quer_decoder and not self.conectado:
                await asyncio.sleep(5)
                if not self._quer_decoder or self.conectado:
                    break
                tipo = self.config.get("decoder_tipo", "p3")
                log.info("tentando reconectar o decoder (%s)...", tipo)
                try:
                    self.driver = self._criar_driver(tipo, None)
                    await self.driver.connect()
                except (OSError, asyncio.TimeoutError, ValueError) as e:
                    log.warning("reconexão ao decoder falhou: %s", e)
                    continue
                self._apos_conectar(tipo, "reconectado")
                break
        except asyncio.CancelledError:
            pass

    async def conectar_decoder(self, tipo: Optional[str] = None,
                               alvo: Optional[str] = None) -> bool:
        """Conecta o driver selecionado: p3 (MyLaps) | easylap | lapwiz."""
        tipo = tipo or self.config.get("decoder_tipo", "p3")
        if self.conectado and self.driver:
            if tipo == self.config.get("decoder_tipo", "p3"):
                return True                      # já conectado no mesmo driver
            await self.desconectar_decoder()      # trocar de driver
        # encerra tarefa anterior (loop de reconexão pendente, se houver)
        if self._task_decoder and not self._task_decoder.done():
            self._task_decoder.cancel()
            try:
                await self._task_decoder
            except (asyncio.CancelledError, Exception):
                pass
            self._task_decoder = None
        try:
            self.driver = self._criar_driver(tipo, alvo)
            await self.driver.connect()
        except (OSError, asyncio.TimeoutError, ValueError) as e:
            self.publicar("erro", {"msg": f"falha ao conectar ({tipo}): {e}"})
            if self.decoder_auto_ativo():
                self.iniciar_auto_conectar()
            return False
        self._apos_conectar(tipo)
        return True

    async def _ler_decoder(self):
        try:
            await self.driver.read_loop(
                on_passing=self._on_passing,
                on_status=self._on_status,
                on_desconhecido=self._on_desconhecido)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("leitura do decoder interrompida: %s", e)
            self.conectado = False
            try:
                await self.driver.close()
            except Exception:
                pass
            if self._quer_decoder:
                self.publicar("erro", {"msg": f"conexão com o decoder caiu ({e})"
                                                  " — tentando reconectar..."})
                self._task_decoder = asyncio.create_task(self._tentar_reconectar())
            else:
                self.publicar("erro", {"msg": f"conexão com o decoder caiu ({e})"})
        else:
            # read_loop terminou sem erro = decoder fechou a conexão
            if self._quer_decoder:
                self.conectado = False
                try:
                    await self.driver.close()
                except Exception:
                    pass
                self.publicar("erro", {"msg": "decoder encerrou a conexão"
                                              " — tentando reconectar..."})
                self._task_decoder = asyncio.create_task(self._tentar_reconectar())

    def _on_status(self, status: Status, pacote):
        self._ultimo_rx_us = agora_monotonic_us()
        drift = self.drift.observar(status.rtc_time if hasattr(status, "rtc_time") else None)
        self._ultimo_status = {
            "temperatura": status.temperatura, "tensao": str(status.tensao or "?"),
            "ruido": status.ruido, "gps": status.gps,
            "decoder_id": status.decoder_id, "drift_us": drift}
        if drift:
            self.publicar("aviso", {"msg": f"drift do decoder: {drift/1e6:.1f}s"})
        self.publicar("status", self._ultimo_status)

    def _on_desconhecido(self, pacote):
        self._ultimo_rx_us = agora_monotonic_us()
        # mensagens cruas ainda não catalogadas (tor=0x1C no P3, notify no LapWiz…)
        if isinstance(pacote, dict) and "tor" in pacote:
            msg = f"mensagem tor=0x{pacote['tor']:04X}"
        else:
            msg = f"mensagem crua: {pacote}"
        self.publicar("decoder", {"msg": msg[:300]})

    def _on_passing(self, passing: Passing, pacote):
        self._ultimo_rx_us = agora_monotonic_us()
        if not self.motor or self.pausado:
            return
        # proteção: pico de tráfego na largada (ring buffer + contagem)
        if not self.ring.push(passing):
            log.warning("ring buffer cheio — passing mais antigo descartado")

        # rejeições (ghost lap) são tratadas pelo callback on_rejeicao
        volta = self.motor.processar_passing(passing)
        if volta:
            self.contadores["passings_validos"] += 1
            self.publicar("volta", {
                "piloto_id": volta.piloto_id, "nome": self._piloto_nome(volta.piloto_id),
                "numero": volta.numero, "tempo": volta.tempo_s})
            self.publicar("classificacao", {"linhas": self._classificacao()})
            self.publicar("voltas", self.dados_voltas())
            self._anunciar_volta(volta)

    def _piloto_nome(self, piloto_id: int) -> str:
        piloto = self.banco.buscar_piloto(piloto_id)
        return piloto.nome if piloto else str(piloto_id)

    def _nome_falado(self, piloto_id: int) -> str:
        """Nome para o TTS: a fonia cadastrada, ou o nome se não houver."""
        piloto = self.banco.buscar_piloto(piloto_id)
        if not piloto:
            return str(piloto_id)
        return (piloto.fonia or "").strip() or piloto.nome

    @staticmethod
    def _tempo_falado(tempo_us: Optional[int]) -> str:
        """Tempo em segundos para o TTS, ex.: '9,12' ou '1 minuto e 3,50'."""
        if not tempo_us:
            return "0"
        s = tempo_us / 1_000_000
        if s < 60:
            return f"{s:.2f}".replace(".", ",")
        minutos = int(s // 60)
        resto = s - minutos * 60
        return f"{minutos} minuto{'s' if minutos > 1 else ''} e {resto:05.2f}".replace(".", ",")

    def _cfg_som(self) -> Dict:
        return {**OPCOES_SOM_PADRAO, **(self.config.get("som") or {})}

    def _anunciar_volta(self, volta):
        """Locução de cada volta: leitura da volta, recordes e posições a cada N voltas."""
        cfg = self._cfg_som()
        nome = self._nome_falado(volta.piloto_id)
        tempo = self._tempo_falado(volta.tempo_us)

        if cfg.get("anunciar_volta"):
            self.som.falar("volta", numero=volta.numero, nome=nome, tempo=tempo)

        # recorde da pista (mais forte) tem prioridade sobre o recorde pessoal
        if self._recorde_pista_us is None or volta.tempo_us < self._recorde_pista_us:
            self._recorde_pista_us = volta.tempo_us
            self._recorde_pessoal[volta.piloto_id] = volta.tempo_us
            if cfg.get("anunciar_recorde_pista"):
                self.som.falar("recorde_pista", nome=nome, tempo=tempo)
                self.publicar("volta", {"piloto_id": volta.piloto_id,
                                        "recorde": "pista", "tempo": tempo})
        else:
            anterior = self._recorde_pessoal.get(volta.piloto_id)
            if anterior is None or volta.tempo_us < anterior:
                self._recorde_pessoal[volta.piloto_id] = volta.tempo_us
                if cfg.get("anunciar_recorde_pessoal"):
                    self.som.falar("recorde_pessoal", nome=nome, tempo=tempo)
                    self.publicar("volta", {"piloto_id": volta.piloto_id,
                                            "recorde": "pessoal", "tempo": tempo})

        # leitura de posições a cada N voltas do líder (ex.: a cada 10 voltas)
        cada = int(cfg.get("anunciar_a_cada_voltas") or 0)
        if cada > 0 and self.motor:
            lider = max((l.voltas for l in self.motor.classificacao()), default=0)
            if lider and lider % cada == 0 and lider != self._ultima_leitura_voltas:
                self._ultima_leitura_voltas = lider
                self._anunciar_posicoes()

    def dados_voltas(self) -> Dict:
        """Voltas volta a volta da sessão atual (para gráficos)."""
        if not self.motor or not self.sessao_id:
            return {"pilotos": [], "parametros": self.parametros}
        voltas = self.banco.voltas_da_sessao(self.sessao_id)
        por: Dict[str, list] = {}
        for v in voltas:
            nome = self._piloto_nome(v.piloto_id)
            por.setdefault(nome, []).append(
                {"numero": v.numero, "tempo": round(v.tempo_us / 1e6, 3),
                 "melhor": bool(v.melhor)})
        pilotos = sorted(por.items(), key=lambda kv: -len(kv[1]))
        return {"pilotos": [{"nome": n, "voltas": vs} for n, vs in pilotos],
                "parametros": self.parametros}

    def _classificacao(self):
        return [{"posicao": l.posicao, "nome": l.nome, "voltas": l.voltas,
                 "tempo": formatar(l.tempo_total_us), "melhor": formatar(l.melhor_volta_us),
                 "melhor_us": l.melhor_volta_us, "ultima": formatar(l.ultima_volta_us),
                 "gap": l.gap, "abreviado": l.abreviado, "numero": l.numero,
                 "intervalo": formatar(l.intervalo_us) if l.intervalo_us else "",
                 "media": formatar(int(l.media_us)) if l.media_us else "-",
                 "desvio": formatar(int(l.desvio_us)) if l.desvio_us else "-",
                 "consistencia": f"{l.consistencia_pct:.1f}%" if l.consistencia_pct else "-",
                 "transponder": l.transponder, "suspeita": l.suspeita,
                 "piloto_id": l.piloto_id}
                for l in self.motor.classificacao()]

    # ---------------------------------------------------------------- sessão
    def iniciar_sessao(self, tipo: str, tempo_minimo_s: float = 0,
                       duracao: float = 10, criterio: str = "tempo") -> bool:
        if self.motor and self.motor.estado.value not in ("parado", "finalizado"):
            return False
        self.sessao_id = self.banco.abrir_sessao(pista_id=None, tipo=TipoSessao(tipo))
        self.parametros = {"duracao": duracao, "criterio": criterio,
                           "tempo_minimo_volta_s": tempo_minimo_s}
        self.motor = MotorCorrida(
            banco=self.banco, sessao_id=self.sessao_id,
            tempo_minimo_volta_us=int(tempo_minimo_s * 1_000_000),
            on_rejeicao=self._on_rejeicao,
            resolver_piloto=self._resolver_transponder)
        # vínculos transponder -> piloto (todos os cadastrados no Admin)
        vinculos = [(int(t["codigo"]), int(t["piloto_id"]))
                    for t in self.banco.listar_transponders()]
        if not vinculos:
            vinculos = list(CADASTRO_TRANSPONDERS.items())
        # check-in do gerente: se houver pilotos confirmados, só eles entram
        if self.presentes:
            vinculos = [(c, p) for c, p in vinculos if p in self.presentes]
        for codigo, piloto_id in vinculos:
            self.motor.registrar_transponder(codigo, piloto_id)
        for piloto_id in {pid for _, pid in vinculos}:
            self.motor.vincular_piloto(piloto_id, self._piloto_nome(piloto_id))
        log.info("sessão %s (%s): %d vínculo(s) transponder->piloto, %d piloto(s) no motor",
                 self.sessao_id[:8], tipo, len(vinculos), len(self.motor._pilotos))
        self.motor.iniciar(TipoSessao(tipo))
        self.som.iniciada(tipo)
        if tipo == "corrida":
            self.som.anunciar_largada()
        self.contadores = {"passings_validos": 0, "ghost_laps": 0, "gaps": 0,
                           "sem_piloto": 0}
        # cronômetro da sessão: começa no "Iniciar sessão" para TODO tipo
        # (treino/classificação/corrida) — a largada só redefine na corrida.
        self.inicio_sessao_us = agora_monotonic_us()
        self._tempo_final_s = None
        self._pausa_inicio_us = None
        self._pausado_total_us = 0
        self.pausado = False
        # recordes para a locução (base = histórico já gravado) e anúncio periódico
        self._recorde_pista_us = self.banco.melhor_volta_pista_us()
        self._recorde_pessoal = self.banco.melhores_por_piloto()
        self._ultima_leitura_voltas = 0
        self._iniciar_anuncios()
        self.publicar("sessao", {"estado": "iniciada", "tipo": tipo})
        return True

    def _resolver_transponder(self, transponder: int):
        """Resolve transponder -> (piloto_id, nome) para o motor da sessão."""
        piloto = self.banco.piloto_do_transponder(transponder) if self.banco else None
        return (piloto.id, piloto.nome) if piloto else None

    def _iniciar_anuncios(self):
        """(Re)inicia a tarefa que lê as posições em intervalos configurados."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._task_posicoes is None or self._task_posicoes.done():
            self._task_posicoes = asyncio.create_task(self._loop_posicoes())

    async def _loop_posicoes(self):
        proximo = None
        try:
            while self.motor and self.motor.estado.value not in ("parado", "finalizado"):
                intervalo = float(self._cfg_som().get("intervalo_posicoes") or 0)
                if intervalo <= 0:
                    proximo = None
                    await asyncio.sleep(2)
                    continue
                if proximo is None:
                    proximo = time.monotonic() + intervalo
                await asyncio.sleep(1)
                if self.pausado:
                    proximo = time.monotonic() + intervalo
                    continue
                if time.monotonic() >= proximo:
                    self._anunciar_posicoes()
                    proximo = time.monotonic() + intervalo
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.warning("loop de anúncios de posição encerrado: %s", e)

    def _anunciar_posicoes(self) -> int:
        if not self.motor:
            return 0
        linhas = [l for l in self.motor.classificacao() if l.voltas > 0]
        if not linhas:
            return 0
        topo = max(1, int(self._cfg_som().get("posicoes_topo") or 3))
        partes = [f"{l.posicao}º {self._nome_falado(l.piloto_id)}"
                  for l in linhas[:topo]]
        self.som.falar("posicoes", lista=", ".join(partes))
        return len(partes)

    def anunciar_posicoes(self) -> Dict:
        """Leitura de posição sob demanda (botão do Admin)."""
        if not self.motor:
            return {"ok": False, "erro": "nenhuma sessão ativa"}
        n = self._anunciar_posicoes()
        if not n:
            return {"ok": False, "erro": "ainda não há voltas para anunciar"}
        return {"ok": True, "pilotadas": n}

    def largada(self) -> bool:
        if not self.motor:
            return False
        try:
            self.motor.largada()
            self.inicio_sessao_us = agora_monotonic_us()
            self._tempo_final_s = None
            self._pausa_inicio_us = None
            self._pausado_total_us = 0
            self.pausado = False
            self.publicar("sessao", {"estado": "correndo"})
            return True
        except RuntimeError:
            return False

    def marcar_gato(self, piloto_id: int, numero_volta=None) -> bool:
        if not self.motor:
            return False
        ok = self.motor.marcar_suspeita(piloto_id, numero_volta)
        if ok:
            self.publicar("admin", {"msg": "volta marcada como suspeita ('gato')"})
            self.som.gato()
            self.publicar("classificacao", {"linhas": self._classificacao()})
        return ok

    def desmarcar_gato(self, piloto_id: int, numero_volta=None) -> bool:
        if not self.motor:
            return False
        ok = self.motor.desmarcar_suspeita(piloto_id, numero_volta)
        if ok:
            self.publicar("classificacao", {"linhas": self._classificacao()})
        return ok

    def apagar_volta(self, piloto_id: int, numero_volta=None) -> bool:
        if not self.motor:
            return False
        ok = self.motor.apagar_volta(piloto_id, numero_volta)
        if ok:
            self.publicar("admin", {"msg": "volta apagada (ação administrativa)"})
            self.publicar("classificacao", {"linhas": self._classificacao()})
        return ok

    def pausar(self, pausar: bool) -> bool:
        if not self.motor:
            return False
        # congela/retoma o cronômetro da sessão junto com a pausa
        agora = agora_monotonic_us()
        if pausar and not self.pausado:
            self._pausa_inicio_us = agora
        elif not pausar and self.pausado and self._pausa_inicio_us is not None:
            self._pausado_total_us += agora - self._pausa_inicio_us
            self._pausa_inicio_us = None
        self.pausado = pausar
        if pausar:
            self.som.pausada()
        else:
            self.som.retomada()
        self.publicar("sessao", {"estado": "pausada" if pausar else "retomada"})
        return True

    def tempo_sessao_s(self) -> Optional[float]:
        """Cronômetro da sessão em segundos (desconta pausas; congela ao fim)."""
        if self._tempo_final_s is not None:
            return self._tempo_final_s
        if not self.inicio_sessao_us:
            return None
        fim = self._pausa_inicio_us if self.pausado and self._pausa_inicio_us else agora_monotonic_us()
        return max(0.0, (fim - self.inicio_sessao_us - self._pausado_total_us) / 1e6)

    def finalizar(self) -> bool:
        if not self.motor:
            return False
        self.motor.finalizar()
        self.pausado = False
        # congela o cronômetro no tempo final da sessão
        self._tempo_final_s = self.tempo_sessao_s()
        self._pausa_inicio_us = None
        if self._task_posicoes and not self._task_posicoes.done():
            self._task_posicoes.cancel()
        self._task_posicoes = None
        self.som.finalizada()
        # auto-upload (Fase 3): enfileira a sessão completa para o CTAD
        if self.config.get("auto_upload") and self.sincronizador.configurado:
            try:
                payload = self.sincronizador.sessao_para_upload(
                    self.sessao_id, f"sessao_{self.sessao_id[:8]}")
                self.sincronizador.enfileirar(payload)
                self.publicar("sync", {"msg": "sessão enfileirada para o CTAD (auto-upload)"})
            except Exception as e:
                log.warning("auto-upload falhou: %s", e)
        self.publicar("sessao", {"estado": "finalizada",
                                 "classificacao": self._classificacao()})
        return True

    # ---------------------------------------------------------------- gerente de pista
    #: valores de estado da pista aceitos pelo gerente
    BANDEIRAS = ("verde", "amarela", "vermelha", "fechada")

    def estado_pista(self) -> Dict:
        return {"bandeira": self.bandeira, "motivo": self.bandeira_motivo}

    def definir_bandeira(self, cor: str, motivo: str = "") -> Dict:
        """Define a bandeira/estado da pista (controle do gerente)."""
        cor = (cor or "").strip().lower()
        if cor not in self.BANDEIRAS:
            raise ValueError("bandeira inválida — use verde, amarela, vermelha ou fechada")
        self.bandeira = cor
        self.bandeira_motivo = (motivo or "").strip()
        self.publicar("bandeira", self.estado_pista())
        if cor == "vermelha":
            self.publicar("aviso", {"msg": "bandeira vermelha — pista fechada pelo gerente"})
        elif cor == "fechada":
            self.publicar("aviso", {"msg": "pista fechada pelo gerente"})
        return {"ok": True, **self.estado_pista()}

    # ----- check-in dos pilotos -----
    def _carregar_checkin(self):
        try:
            ids = self.config.get("checkin") or []
            self.presentes = {int(i) for i in ids}
        except (TypeError, ValueError):
            self.presentes = set()

    def _salvar_checkin(self):
        cfg = carregar_config()
        cfg["checkin"] = sorted(self.presentes)
        salvar_config(cfg)
        self.config = cfg

    def listar_presentes(self) -> List[int]:
        return sorted(self.presentes)

    def definir_presente(self, piloto_id: int, presente: bool) -> Dict:
        try:
            piloto_id = int(piloto_id)
        except (TypeError, ValueError):
            raise ValueError("piloto inválido")
        if presente:
            self.presentes.add(piloto_id)
        else:
            self.presentes.discard(piloto_id)
        self._salvar_checkin()
        self.publicar("checkin", {"presentes": self.listar_presentes()})
        return {"ok": True, "presentes": self.listar_presentes()}

    def definir_presentes(self, ids) -> Dict:
        try:
            self.presentes = {int(i) for i in (ids or [])}
        except (TypeError, ValueError):
            raise ValueError("lista de presentes inválida")
        self._salvar_checkin()
        self.publicar("checkin", {"presentes": self.listar_presentes()})
        return {"ok": True, "presentes": self.listar_presentes()}

    # ----- anúncios do gerente -----
    def anunciar_texto(self, texto: Optional[str] = None,
                       chave: Optional[str] = None) -> Dict:
        """Fala um texto livre (ou uma frase cadastrada) pela locução."""
        if (not texto or not str(texto).strip()) and chave:
            texto = self.som.texto(chave)
        texto = (texto or "").strip()
        if not texto:
            raise ValueError("informe o texto do anúncio")
        falou = False
        if self.som.ativo and self.som.locutor:
            self.som.locutor.falar(texto)
            falou = True
        self.publicar("anuncio", {"texto": texto})
        return {"ok": True, "texto": texto, "falado": falou}

    # ----- volta manual (correção pelo gerente) -----
    def adicionar_volta(self, piloto_id: int, tempo_s: float) -> bool:
        if not self.motor:
            log.warning("volta manual recusada: sem motor de sessão ativo")
            return False
        try:
            tempo_us = int(round(float(tempo_s) * 1_000_000))
        except (TypeError, ValueError):
            return False
        if tempo_us <= 0:
            return False
        ok = self.motor.adicionar_volta(piloto_id, tempo_us)
        if ok:
            self.publicar("admin", {"msg": "volta adicionada manualmente"})
            self.publicar("classificacao", {"linhas": self._classificacao()})
            self.publicar("voltas", self.dados_voltas())
        return ok

    def painel_gerente(self) -> Dict:
        """Pacote completo do gerente: sessão + classificação + pilotos + pista."""
        return {"snapshot": self.snapshot(),
                "pilotos": self.listar_pilotos(),
                "presentes": self.listar_presentes(),
                **self.estado_pista()}

    # ---------------------------------------------------------------- sync (Fase 3)
    def configurar_sync(self, email: str, password: str, pista_id: Optional[str] = None) -> Dict:
        """Configura e testa a conta do CTAD (login real, como o site)."""
        cfg = dict(self.config)
        cfg["email"] = email
        if password:
            cfg["password"] = password
        if pista_id:
            cfg["pistaId"] = pista_id
        cliente = CtadClient(cfg)
        info = cliente.testar_conexao()   # levanta ErroAuth se recusado
        # login ok — persiste e liga o sincronizador
        self.config = cfg
        salvar_config(cfg)
        self.sincronizador.cliente = cliente
        self.sincronizador.pista_id = cfg.get("pistaId", "krathus")
        self.publicar("sync", {"msg": f"conectado ao CTAD ({info['nivel']})"})
        return info

    def _nome_sessao_para(self, sessao_id: str) -> str:
        try:
            for s in self.banco.listar_sessoes():
                if s["id"] == sessao_id:
                    tipo = (s["tipo"] or "sessão").capitalize()
                    ini = (s["inicio"] or "")[:16].replace("T", " ")
                    return f"{tipo} {ini}".strip()
        except Exception:
            pass
        return f"sessão {sessao_id[:8]}"

    def previa_sessao(self, sessao_id: str, nome_sessao: Optional[str] = None) -> Dict:
        """Monta o payload de upload SEM enviar (para conferência)."""
        if not sessao_id:
            raise RuntimeError("informe a sessão")
        nome = nome_sessao or self._nome_sessao_para(sessao_id)
        return self.sincronizador.sessao_para_upload(sessao_id, nome)

    def enviar_sessao(self, nome_sessao: Optional[str] = None,
                      sessao_id: Optional[str] = None) -> Dict:
        if not self.sincronizador.configurado:
            raise ErroAuth("sync não configurado — informe e-mail/senha do CTAD")
        alvo = sessao_id or self.sessao_id
        if not alvo:
            raise RuntimeError("nenhuma sessão ativa para enviar")
        nome = nome_sessao or self._nome_sessao_para(alvo)
        payload = self.sincronizador.sessao_para_upload(alvo, nome)
        self.sincronizador.enfileirar(payload)
        resultado = self.sincronizador.processar()
        self.publicar("sync", {"msg": f"sessão '{nome}' processada: {resultado}"})
        return {"batKey": payload["bateriaKey"], "sessao_id": alvo, **resultado}

    def sync_processar(self) -> Dict:
        if not self.sincronizador.configurado:
            raise ErroAuth("sync não configurado — informe e-mail/senha do CTAD")
        resultado = self.sincronizador.processar()
        self.publicar("sync", {"msg": f"fila processada: {resultado}"})
        return resultado

    def limpar_fila_sync(self) -> int:
        """Remove itens pendentes/com erro da fila (mantém histórico dos enviados)."""
        if not self.banco:
            return 0
        with self.banco.conn:
            cur = self.banco.conn.execute(
                "DELETE FROM fila_sync WHERE estado IN ('pendente', 'erro')")
        return cur.rowcount

    # ---------------------------------------------------------------- voz / som (Admin)
    def _aplicar_ajustes_som(self, ajustes: Dict):
        loc = self.som.locutor
        if not loc:
            return
        if ajustes.get("volume") is not None:
            loc.set_volume(ajustes["volume"])
        if ajustes.get("velocidade") is not None:
            loc.set_velocidade(ajustes["velocidade"])
        if ajustes.get("voz"):
            loc.definir_voz(ajustes["voz"])

    def _aplicar_config_som(self):
        """Carrega frases/voz/volume/áudios salvos em config.json para o ModuloSom."""
        cfg = self.config.get("som") or {}
        self.som.definir_frases(cfg.get("frases"))
        self.som.definir_audios(self._mapa_audios())
        self.som.definir_habilitados(cfg.get("habilitados"))
        self._aplicar_ajustes_som(cfg)

    def som_info(self) -> Dict:
        loc = self.som.locutor
        base = loc.status() if loc else {
            "tts_ativo": False, "volume": 0.9, "velocidade": 180,
            "voz_id": None, "vozes": [], "edge_disponivel": False}
        return {"ativo": self.som.ativo, "frases": self.som.frases_publicas(),
                "audios": self.som.audios_publicos(),
                "opcoes": self._cfg_som(), **base}

    # ----- áudios gravados por frase (substituem a locução TTS) -----
    _EXTS_AUDIO = (".wav", ".mp3", ".ogg", ".m4a", ".wma", ".aac", ".flac")

    def _dir_audios(self) -> str:
        d = os.path.join(str(dir_dados()), "audios")
        os.makedirs(d, exist_ok=True)
        return d

    def _mapa_audios(self, cfg: Optional[Dict] = None) -> Dict[str, str]:
        cfg = cfg or self.config
        som_cfg = cfg.get("som") or {}
        d = self._dir_audios()
        mapa: Dict[str, str] = {}
        for chave, arquivo in (som_cfg.get("audios") or {}).items():
            p = os.path.join(d, str(arquivo))
            if os.path.isfile(p):
                mapa[chave] = p
        return mapa

    def _remover_arquivo_audio(self, chave: str):
        d = self._dir_audios()
        for ext in self._EXTS_AUDIO:
            p = os.path.join(d, chave + ext)
            if os.path.isfile(p):
                try:
                    os.remove(p)
                except OSError:
                    pass

    def salvar_audio(self, chave: str, nome: str, dados: bytes) -> Dict:
        from .som import FRASES_TTS
        if chave not in FRASES_TTS:
            raise ValueError("frase desconhecida")
        if not dados:
            raise ValueError("arquivo vazio")
        ext = os.path.splitext(nome or "")[1].lower() or ".wav"
        if ext not in self._EXTS_AUDIO:
            raise ValueError(f"formato não suportado ({ext}) — use WAV ou MP3")
        self._remover_arquivo_audio(chave)
        destino = os.path.join(self._dir_audios(), chave + ext)
        with open(destino, "wb") as fh:
            fh.write(dados)
        cfg = carregar_config()
        som_cfg = cfg.get("som") or {}
        audios = dict(som_cfg.get("audios") or {})
        audios[chave] = os.path.basename(destino)
        som_cfg["audios"] = audios
        cfg["som"] = som_cfg
        salvar_config(cfg)
        self.config = cfg
        self.som.definir_audios(self._mapa_audios(cfg))
        self.publicar("som", {"msg": f"áudio definido para {chave}"})
        return {"ok": True, "chave": chave, "arquivo": os.path.basename(destino)}

    def remover_audio(self, chave: str) -> Dict:
        self._remover_arquivo_audio(chave)
        cfg = carregar_config()
        som_cfg = cfg.get("som") or {}
        audios = dict(som_cfg.get("audios") or {})
        audios.pop(chave, None)
        som_cfg["audios"] = audios
        cfg["som"] = som_cfg
        salvar_config(cfg)
        self.config = cfg
        self.som.definir_audios(self._mapa_audios(cfg))
        self.publicar("som", {"msg": f"áudio removido de {chave}"})
        return {"ok": True}

    def caminho_audio(self, chave: str) -> Optional[str]:
        return self.som.audios.get(chave)

    def ouvir_som(self, texto: Optional[str] = None, chave: Optional[str] = None,
                  **ajustes) -> Dict:
        """Pré-escuta de uma frase (Admin) — não altera a configuração salva."""
        if not texto and chave:
            texto = self.som.texto(chave)
        if not texto or not str(texto).strip():
            raise ValueError("frase vazia — escreva o texto antes de ouvir")
        texto = self.som.com_exemplo(str(texto))
        self._aplicar_ajustes_som(ajustes)
        falou = self.som.ouvir(texto, chave=chave)
        return {"ok": True, "texto": texto, "falado": falou,
                "tts_ativo": bool(self.som.locutor and self.som.locutor.tts_ativo)}

    def salvar_som(self, frases: Optional[Dict] = None, volume=None,
                   velocidade=None, voz=None, intervalo_posicoes=None,
                   posicoes_topo=None, anunciar_volta=None,
                   anunciar_a_cada_voltas=None,
                   anunciar_recorde_pessoal=None,
                   anunciar_recorde_pista=None,
                   habilitados: Optional[Dict] = None) -> Dict:
        if frases:
            self.som.definir_frases(frases)
        if habilitados is not None:
            self.som.definir_habilitados(habilitados)
        self._aplicar_ajustes_som({"volume": volume, "velocidade": velocidade,
                                   "voz": voz})
        cfg = carregar_config()
        som_cfg = cfg.get("som") or {}
        if frases:
            som_cfg["frases"] = {**(som_cfg.get("frases") or {}), **frases}
        if habilitados is not None:
            som_cfg["habilitados"] = {**(som_cfg.get("habilitados") or {}),
                                      **{k: bool(v) for k, v in habilitados.items()}}
        if volume is not None:
            som_cfg["volume"] = float(volume)
        if velocidade is not None:
            som_cfg["velocidade"] = int(velocidade)
        if voz:
            som_cfg["voz"] = voz
        # anúncios automáticos (posições em intervalo + recordes)
        if intervalo_posicoes is not None:
            som_cfg["intervalo_posicoes"] = max(0.0, float(intervalo_posicoes))
        if posicoes_topo is not None:
            som_cfg["posicoes_topo"] = max(1, int(posicoes_topo))
        if anunciar_volta is not None:
            som_cfg["anunciar_volta"] = bool(anunciar_volta)
        if anunciar_a_cada_voltas is not None:
            som_cfg["anunciar_a_cada_voltas"] = max(0, int(anunciar_a_cada_voltas))
        if anunciar_recorde_pessoal is not None:
            som_cfg["anunciar_recorde_pessoal"] = bool(anunciar_recorde_pessoal)
        if anunciar_recorde_pista is not None:
            som_cfg["anunciar_recorde_pista"] = bool(anunciar_recorde_pista)
        cfg["som"] = som_cfg
        salvar_config(cfg)
        self.config = cfg
        self.publicar("som", {"msg": "preferências de voz/som salvas"})
        return {"ok": True, "salvo": True}

    # ---------------------------------------------------------------- pilotos (Admin)
    #: funções extra opcionais que um piloto pode acumular
    FUNCOES_PILOTO = ("superuser", "admin", "gestor")

    @staticmethod
    def _parse_transponders(valor) -> List[int]:
        if valor is None or valor == "":
            return []
        brutos = valor if isinstance(valor, (list, tuple)) else \
            str(valor).replace(";", ",").split(",")
        codigos = []
        for b in brutos:
            b = str(b).strip()
            if not b:
                continue
            try:
                codigos.append(int(b))
            except ValueError:
                raise ValueError(f"transponder inválido: {b}")
        return list(dict.fromkeys(codigos))    # remove repetidos mantendo a ordem

    @staticmethod
    def _normaliza_telefone(valor) -> str:
        """Telefone vira a chave natural: guarda só os dígitos."""
        if valor is None:
            return ""
        return "".join(c for c in str(valor) if c.isdigit())

    @classmethod
    def _parse_funcoes(cls, valor) -> str:
        """Normaliza a lista de funções extra (admite CSV, lista ou vazio)."""
        if valor is None or valor == "":
            return ""
        brutos = valor if isinstance(valor, (list, tuple)) else \
            str(valor).replace(";", ",").split(",")
        funcs = []
        for f in brutos:
            f = str(f).strip().lower()
            if not f:
                continue
            if f not in cls.FUNCOES_PILOTO:
                raise ValueError(f"função inválida: {f}")
            if f not in funcs:
                funcs.append(f)
        return ",".join(funcs)

    def listar_pilotos(self) -> List[Dict]:
        saida = []
        for p in self.banco.pilotos_detalhado():
            trad = [int(x) for x in (p["transponders"] or "").split(",") if x.strip()]
            funcoes = [f for f in (p["funcoes"] or "").split(",") if f]
            saida.append({"id": p["id"], "nome": p["nome"], "apelido": p["apelido"],
                          "fonia": p["fonia"] or "", "ativo": bool(p["ativo"]),
                          "telefone": p["telefone"] or "", "funcoes": funcoes,
                          "transponders": sorted(trad)})
        return saida

    def _validar_telefone(self, telefone: str, ignorar_id: Optional[int] = None) -> str:
        telefone = self._normaliza_telefone(telefone)
        if not telefone:
            return ""
        if self.banco.piloto_com_telefone(telefone, ignorar_id):
            raise ValueError("telefone já cadastrado para outro piloto")
        return telefone

    def criar_piloto(self, nome: str, apelido: str = "", fonia: str = "",
                     transponders=None, telefone: str = "", funcoes=None) -> Dict:
        nome = (nome or "").strip()
        if not nome:
            raise ValueError("informe o nome do piloto")
        tel = self._validar_telefone(telefone)
        funcs = self._parse_funcoes(funcoes)
        pid = self.banco.criar_piloto(nome, (apelido or "").strip(),
                                      (fonia or "").strip(), tel, funcs)
        codigos = self._parse_transponders(transponders)
        if codigos:
            self.banco.definir_transponders(pid, codigos)
        self.publicar("pilotos", {"msg": f"piloto cadastrado: {nome}"})
        return {"id": pid, "nome": nome, "telefone": tel,
                "funcoes": funcs.split(",") if funcs else [], "transponders": codigos}

    def editar_piloto(self, piloto_id: int, nome: str, apelido: str = "",
                      fonia: str = "", ativo: bool = True, transponders=None,
                      telefone: str = "", funcoes=None) -> Dict:
        if not self.banco.buscar_piloto(piloto_id):
            raise ValueError("piloto não encontrado")
        nome = (nome or "").strip()
        if not nome:
            raise ValueError("informe o nome do piloto")
        tel = self._validar_telefone(telefone, ignorar_id=piloto_id)
        funcs = self._parse_funcoes(funcoes)
        self.banco.atualizar_piloto(piloto_id, nome, (apelido or "").strip(),
                                    (fonia or "").strip(), bool(ativo), tel, funcs)
        if transponders is not None:
            self.banco.definir_transponders(piloto_id, self._parse_transponders(transponders))
        self.publicar("pilotos", {"msg": f"piloto atualizado: {nome}"})
        return {"id": piloto_id, "nome": nome, "telefone": tel,
                "funcoes": funcs.split(",") if funcs else []}

    def excluir_piloto(self, piloto_id: int) -> Dict:
        resultado = self.banco.excluir_piloto(piloto_id)
        self.publicar("pilotos", {"msg": f"piloto {piloto_id}: {resultado['msg']}"})
        return resultado

    # ---------------------------------------------------------------- busca global
    def buscar(self, termo: str, limite: int = 8) -> Dict:
        """Busca unificada: pilotos, sessões, campeonatos, baterias."""
        termo = (termo or "").strip()
        if not termo:
            return {"termo": termo, "pilotos": [], "sessoes": [],
                    "campeonatos": [], "baterias": []}
        alvo = termo.lower()

        def casa(*vals) -> bool:
            return any(alvo in str(v or "").lower() for v in vals)

        pilotos = []
        for p in self.listar_pilotos():
            tr = " ".join(str(t) for t in p.get("transponders", []))
            if casa(p.get("nome"), p.get("apelido"), p.get("fonia"),
                    p.get("telefone"), tr):
                pilotos.append(p)
                if len(pilotos) >= limite:
                    break

        sessoes = []
        for s in self.banco.listar_sessoes():
            inicio = (s["inicio"] or "")
            if casa(s["tipo"], s["estado"], inicio[:16].replace("T", " ")):
                sessoes.append({
                    "id": s["id"], "tipo": s["tipo"], "estado": s["estado"],
                    "inicio": s["inicio"], "voltas": s["n_voltas"],
                    "pilotos": s["n_pilotos"], "melhor": formatar(s["melhor_us"]),
                    "rotulo": f"{(s['tipo'] or '').capitalize()} "
                              f"{inicio[:16].replace('T', ' ')}".strip(),
                })
                if len(sessoes) >= limite:
                    break

        campeonatos = []
        for c in self.banco.listar_campeonatos():
            if casa(c["nome"]):
                campeonatos.append({"id": c["id"], "nome": c["nome"],
                                    "provas": c["numero_provas"]})
                if len(campeonatos) >= limite:
                    break

        baterias = [{"bateria_id": b["bateria_id"], "nome": b["bateria"],
                     "fase": b["fase"], "etapa": b["etapa"],
                     "campeonato_id": b["campeonato_id"],
                     "campeonato": b["campeonato"]}
                    for b in self.banco.buscar_baterias(termo, limite)]

        return {"termo": termo, "pilotos": pilotos, "sessoes": sessoes,
                "campeonatos": campeonatos, "baterias": baterias}

    # ---------------------------------------------------------------- relatórios
    def relatorio_resumo(self) -> Dict:
        return self.banco.relatorio_contagens()

    def relatorio_pilotos(self) -> List[Dict]:
        saida = []
        for p in self.banco.relatorio_pilotos():
            saida.append({
                "id": p["id"], "nome": p["nome"], "apelido": p["apelido"] or "",
                "telefone": p["telefone"] or "", "ativo": bool(p["ativo"]),
                "funcoes": [f for f in (p["funcoes"] or "").split(",") if f],
                "voltas": int(p["voltas"] or 0), "sessoes": int(p["sessoes"] or 0),
                "melhor": formatar(p["melhor_us"]), "melhor_us": p["melhor_us"],
                "ultima_sessao": p["ultima_sessao"],
            })
        return saida

    def relatorio_sessoes(self, tipo: Optional[str] = None,
                          de: Optional[str] = None, ate: Optional[str] = None) -> List[Dict]:
        saida = []
        for s in self.banco.listar_sessoes():
            inicio = s["inicio"] or ""
            if tipo and s["tipo"] != tipo:
                continue
            if de and inicio[:10] < de:
                continue
            if ate and inicio[:10] > ate:
                continue
            saida.append({
                "id": s["id"], "tipo": s["tipo"], "estado": s["estado"],
                "inicio": inicio, "fim": s["fim"],
                "voltas": int(s["n_voltas"] or 0), "pilotos": int(s["n_pilotos"] or 0),
                "melhor": formatar(s["melhor_us"]), "melhor_us": s["melhor_us"],
                "rotulo": f"{(s['tipo'] or '').capitalize()} " +
                          (s["inicio"] or "")[:16].replace("T", " "),
            })
        return saida

    def relatorio_sessao(self, sessao_id: str) -> Dict:
        return self.historico_sessao(sessao_id)

    def relatorio_csv(self, tipo: str, termo: str = "") -> str:
        """Gera CSV (;) de um relatório para download."""
        import csv
        import io
        buffer = io.StringIO()
        w = csv.writer(buffer, delimiter=";", lineterminator="\n")
        if tipo == "pilotos":
            w.writerow(["ID", "Nome", "Apelido", "Telefone", "Funções", "Ativo",
                        "Voltas", "Sessões", "Melhor volta"])
            for p in self.relatorio_pilotos():
                w.writerow([p["id"], p["nome"], p["apelido"], p["telefone"],
                            " ".join(p["funcoes"]), "sim" if p["ativo"] else "não",
                            p["voltas"], p["sessoes"], p["melhor"]])
        else:
            w.writerow(["ID", "Tipo", "Estado", "Início", "Fim", "Pilotos",
                        "Voltas", "Melhor volta"])
            for s in self.relatorio_sessoes():
                w.writerow([s["id"], s["tipo"], s["estado"], s["inicio"], s["fim"],
                            s["pilotos"], s["voltas"], s["melhor"]])
        return buffer.getvalue()

    # ---------------------------------------------------------------- notificações (Admin)
    PADRAO_NOTIFICACOES = {
        "decoder_offline": True, "ghost_lap": True, "fila_upload": True,
        "recorde": True, "navegador": False, "som_alerta": True,
    }

    def notificacoes(self) -> Dict:
        base = dict(self.PADRAO_NOTIFICACOES)
        base.update({k: v for k, v in (self.config.get("notificacoes") or {}).items()
                     if k in base})
        return base

    def salvar_notificacoes(self, valores: Dict) -> Dict:
        atuais = self.notificacoes()
        for k, v in (valores or {}).items():
            if k in atuais:
                atuais[k] = bool(v)
        cfg = carregar_config()
        cfg["notificacoes"] = atuais
        salvar_config(cfg)
        self.config = cfg
        self.publicar("notificacoes", {"msg": "preferências de notificação salvas"})
        return {"ok": True, "notificacoes": atuais}

    # ---------------------------------------------------------------- banner do dashboard (carrossel)
    #: slides padrão do carrossel. "aviso" é editável; "decoder" e "campeonato"
    #: são painéis ao vivo montados pelo front-end.
    PADRAO_BANNER = [
        {"tipo": "aviso", "tag": "PRÓXIMA SESSÃO", "titulo": "Treino Livre",
         "sub": "hoje 14:00",
         "texto": "Krathus Arena · 29 pilotos inscritos · regulamento e grid do "
                  "campeonato definidos no CTAD (fonte única).",
         "botao": "Abrir painel do operador", "acao": "operador"},
        {"tipo": "decoder"},
        {"tipo": "campeonato"},
    ]

    def banner(self) -> Dict:
        """Slides do carrossel do dashboard (configuráveis no Admin).

        O texto de um slide ``aviso`` pode conter ``{pilotos}``, que é
        substituído pelo nº de inscritos do campeonato mais recente.
        """
        slides = self.config.get("banner") or self.PADRAO_BANNER
        n_pilotos = None
        try:
            camps = self.banco.listar_campeonatos() if self.banco else []
            if camps:
                n_pilotos = len(self.banco.listar_inscricoes(camps[0]["id"]))
        except Exception:
            n_pilotos = None
        saida = []
        for s in slides:
            s = dict(s)
            if s.get("tipo") == "aviso" and "{pilotos}" in (s.get("texto") or ""):
                s["texto"] = s["texto"].replace(
                    "{pilotos}", str(n_pilotos) if n_pilotos is not None else "—")
            saida.append(s)
        return {"slides": saida}

    def salvar_banner(self, slides) -> Dict:
        """Grava os slides do carrossel (Admin → Carrossel)."""
        if not isinstance(slides, list) or not slides:
            raise ValueError("banner inválido — informe ao menos um slide")
        limpo = []
        for s in slides:
            tipo = str(s.get("tipo") or "aviso")
            if tipo == "aviso":
                limpo.append({
                    "tipo": "aviso",
                    "tag": str(s.get("tag") or ""),
                    "titulo": str(s.get("titulo") or ""),
                    "sub": str(s.get("sub") or ""),
                    "texto": str(s.get("texto") or ""),
                    "botao": str(s.get("botao") or ""),
                    "acao": str(s.get("acao") or "operador"),
                })
            elif tipo in ("decoder", "campeonato"):
                limpo.append({"tipo": tipo})
            else:
                raise ValueError(f"tipo de slide desconhecido: {tipo}")
        cfg = carregar_config()
        cfg["banner"] = limpo
        salvar_config(cfg)
        self.config = cfg
        self.publicar("sistema", {"msg": "banner do dashboard atualizado"})
        return {"ok": True, "slides": limpo}

    # ---------------------------------------------------------------- campeonato (plano de etapas)
    #: sequência padrão do tipo de sessão "Campeonato"
    PADRAO_CAMPEONATO = [
        {"etapa": "treino", "rotulo": "Treino", "duracao": 10},
        {"etapa": "intervalo", "rotulo": "Intervalo", "duracao": 5},
        {"etapa": "classificacao", "rotulo": "Classificação", "duracao": 10},
        {"etapa": "intervalo", "rotulo": "Intervalo", "duracao": 5},
        {"etapa": "corrida", "rotulo": "Corrida", "duracao": 20},
    ]

    def campeonato_plano(self) -> Dict:
        """Plano do campeonato (etapas) e a duração total exata."""
        cfg = self.config.get("campeonato_plano") or {}
        etapas = cfg.get("etapas") or self.PADRAO_CAMPEONATO
        etapas = [{"etapa": e.get("etapa") or "etapa",
                   "rotulo": e.get("rotulo") or e.get("etapa") or "Etapa",
                   "duracao": max(0, int(e.get("duracao") or 0))} for e in etapas]
        total = sum(e["duracao"] for e in etapas)
        if total >= 60:
            exata = f"{total // 60}h{total % 60:02d}min"
        else:
            exata = f"{total} min"
        return {"etapas": etapas, "total_min": total, "duracao_exata": exata}

    def salvar_campeonato_plano(self, etapas) -> Dict:
        if not isinstance(etapas, list) or not etapas:
            raise ValueError("plano do campeonato inválido")
        limpo = [{"etapa": str(e.get("etapa") or "etapa"),
                  "rotulo": str(e.get("rotulo") or e.get("etapa") or "Etapa"),
                  "duracao": max(0, int(e.get("duracao") or 0))} for e in etapas]
        cfg = carregar_config()
        cfg["campeonato_plano"] = {"etapas": limpo}
        salvar_config(cfg)
        self.config = cfg
        self.publicar("campeonato", {"msg": "plano do campeonato salvo"})
        return {"ok": True, **self.campeonato_plano()}

    def iniciar_campeonato(self, tempo_minimo_s: float = 0) -> Dict:
        """Inicia a sequência do campeonato pela primeira etapa (Treino)."""
        plano = self.campeonato_plano()
        etapas = plano["etapas"]
        indice = next((i for i, e in enumerate(etapas) if e["etapa"] != "intervalo"), 0)
        primeira = etapas[indice]
        tipo = primeira["etapa"] if primeira["etapa"] in ("treino", "classificacao", "corrida") \
            else "corrida"
        if not self.iniciar_sessao(tipo, tempo_minimo_s=tempo_minimo_s,
                                   duracao=primeira["duracao"], criterio="tempo"):
            raise ValueError("já existe uma sessão em andamento")
        self.campeonato_ativo = {"plano": plano, "indice": indice,
                                 "tempo_minimo_s": tempo_minimo_s}
        self.publicar("campeonato", {"msg": f"campeonato iniciado — {primeira['rotulo']}",
                                     "estado": self.campeonato_estado()})
        return {"ok": True, "etapa": primeira, "plano": plano, **self.campeonato_estado()}

    def campeonato_estado(self) -> Dict:
        """Situação do campeonato em andamento (etapa atual e próxima)."""
        if not self.campeonato_ativo:
            return {"ativo": False, "plano": self.campeonato_plano()}
        ativo = self.campeonato_ativo
        etapas = ativo["plano"]["etapas"]
        i = ativo["indice"]
        return {"ativo": True, "indice": i, "etapa": etapas[i],
                "numero": i + 1, "total": len(etapas),
                "proxima": etapas[i + 1] if i + 1 < len(etapas) else None,
                "plano": ativo["plano"]}

    def campeonato_proxima(self) -> Dict:
        """Avança para a próxima etapa — avanço MANUAL, disparado pelo operador."""
        if not self.campeonato_ativo:
            raise ValueError("nenhum campeonato em andamento")
        ativo = self.campeonato_ativo
        etapas = ativo["plano"]["etapas"]
        prox_i = ativo["indice"] + 1
        if prox_i >= len(etapas):
            if self.motor and self.motor.estado.value not in ("parado", "finalizado"):
                self.finalizar()
            self.campeonato_ativo = None
            self.publicar("campeonato", {"msg": "campeonato concluído",
                                         "estado": self.campeonato_estado()})
            return {"ok": True, "concluido": True, **self.campeonato_estado()}
        etapa = etapas[prox_i]
        # encerra a etapa atual antes de mudar (intervalo não tem sessão própria)
        if self.motor and self.motor.estado.value not in ("parado", "finalizado"):
            self.finalizar()
        if etapa["etapa"] in ("treino", "classificacao", "corrida"):
            self.iniciar_sessao(etapa["etapa"],
                                tempo_minimo_s=ativo.get("tempo_minimo_s", 0),
                                duracao=etapa["duracao"], criterio="tempo")
        ativo["indice"] = prox_i
        self.publicar("campeonato", {"msg": f"etapa {etapa['rotulo']}",
                                     "estado": self.campeonato_estado()})
        return {"ok": True, **self.campeonato_estado()}

    def campeonato_encerrar(self) -> Dict:
        """Encerra o campeonato em andamento."""
        if self.motor and self.motor.estado.value not in ("parado", "finalizado"):
            self.finalizar()
        self.campeonato_ativo = None
        self.publicar("campeonato", {"msg": "campeonato encerrado pelo operador",
                                     "estado": self.campeonato_estado()})
        return {"ok": True, "ativo": False}

    # ---------------------------------------------------------------- campeonatos (Fase 5)
    def _regulamento(self, camp) -> "Regulamento":
        return Regulamento(
            tabela=json.loads(camp["pontuacao_tabela"]),
            drop_rounds=int(camp["drop_rounds"]),
            bonus_pole=int(camp["bonus_pole"]),
            bonus_melhor_volta=int(camp["bonus_melhor_volta"]),
            numero_provas=int(camp["numero_provas"]),
            pilotos_por_prova=int(camp["pilotos_por_prova"]),
            pilotos_por_chave=int(self._max_por_chave(camp)))

    @staticmethod
    def _max_por_chave(camp) -> int:
        """Teto de pilotos por chave — com fallback para ``pilotos_por_prova`` (CTAD)."""
        try:
            valor = camp["pilotos_por_chave"]
        except (IndexError, KeyError):
            valor = None
        return int(valor or camp["pilotos_por_prova"] or PADRAO_PILOTOS_POR_CHAVE)

    def criar_campeonato(self, nome: str, numero_provas: int = 4,
                         pilotos_por_prova: int = 10, drop_rounds: int = 0,
                         bonus_pole: int = 0, bonus_melhor_volta: int = 0,
                         tabela=None, pilotos_por_chave: int = 10,
                         inverter_bateria: int = 0) -> int:
        if not nome or not nome.strip():
            raise ValueError("nome do campeonato é obrigatório")
        cid = self.banco.criar_campeonato(
            nome.strip(), numero_provas, pilotos_por_prova, tabela,
            drop_rounds, bonus_pole, bonus_melhor_volta,
            pilotos_por_chave=pilotos_por_chave,
            inverter_bateria=inverter_bateria)
        self.publicar("campeonato", {"msg": f"campeonato '{nome.strip()}' criado"})
        return cid

    def campeonatos_resumo(self) -> List[Dict]:
        return [{"id": c["id"], "nome": c["nome"],
                 "numero_provas": c["numero_provas"],
                 "pilotos_por_prova": c["pilotos_por_prova"],
                 "pilotos_por_chave": self._max_por_chave(c),
                 "inverter_bateria": bool(c["inverter_bateria"]),
                 "drop_rounds": c["drop_rounds"],
                 "inscritos": len(self.banco.listar_inscricoes(c["id"]))}
                for c in self.banco.listar_campeonatos()]

    # ---------------------------------------------------------------- sistema de chaves
    def campeonato_definir_chaves(self, campeonato_id: int, max_por_chave=None,
                                  inverter_bateria=None) -> Dict:
        """Ajusta o teto de pilotos por chave e a inversão da bateria seguinte."""
        camp = self.banco.campeonato(campeonato_id)
        if not camp:
            raise ValueError("campeonato não encontrado")
        self.banco.definir_chaves(campeonato_id, max_por_chave, inverter_bateria)
        self.publicar("campeonato", {"msg": "sistema de chaves atualizado"})
        return self.campeonato_grids(campeonato_id)

    def campeonato_grids(self, campeonato_id: int) -> Dict:
        """Grades por prova, cada uma dividida em Chave A/B/C… (diretiva do CTAD)."""
        camp = self.banco.campeonato(campeonato_id)
        if not camp:
            raise ValueError("campeonato não encontrado")
        insc = self.banco.listar_inscricoes(campeonato_id)
        inscritos = [PilotoCamp(piloto_id=r["piloto_id"], nome=r["nome"],
                                transponder=r["transponder"],
                                frequencia=r["frequencia"],
                                pontos_ranking=r["pontos_ranking"] or 0)
                     for r in insc]
        maxc = self._max_por_chave(camp)
        inverter = bool(camp["inverter_bateria"])

        # prova 1: ordem do treino (última sessão de treino finalizada), se houver
        treino_voltas = None
        sess = self.banco.ultima_sessao("treino")
        if sess:
            ids = {p.piloto_id for p in inscritos}
            vpp = {pid: v for pid, v in self.banco.voltas_por_piloto(sess["id"]).items()
                   if pid in ids}
            if vpp:
                treino_voltas = vpp

        # provas seguintes: classificação das etapas já lançadas (posição importada)
        resultados_por_prova = []
        for etapa in self.banco.listar_etapas(campeonato_id):
            linhas = self.banco.classificacao_etapa(etapa["id"])
            if linhas:
                resultados_por_prova.append([
                    {"piloto_id": l["piloto_id"], "posicao": l["posicao"],
                     "melhor_volta_s": (l["melhor_volta_us"] / 1_000_000
                                        if l["melhor_volta_us"] else None)}
                    for l in linhas])

        grids = montar_grids_campeonato(
            inscritos, self._max_por_chave(camp),
            resultados_por_prova=resultados_por_prova or None,
            treino_voltas=treino_voltas, inverter_seguinte=inverter,
            n_provas=int(camp["numero_provas"] or 1))

        return {"ok": True, "campeonato_id": campeonato_id, "nome": camp["nome"],
                "max_por_chave": self._max_por_chave(camp),
                "inverter_bateria": inverter, "inscritos": len(inscritos),
                "grids": [{
                    "prova": g["prova"], "criterio": g["criterio"],
                    "max_por_chave": g["max_por_chave"],
                    "distribuicao": g["distribuicao"],
                    "chaves": [{"nome": c.nome,
                                "pilotos": [{"piloto_id": p.piloto_id, "nome": p.nome}
                                            for p in c.pilotos]}
                               for c in g["chaves"]],
                } for g in grids]}

    def campeonato_detalhe(self, campeonato_id: int) -> Dict:
        camp = self.banco.campeonato(campeonato_id)
        if not camp:
            raise ValueError("campeonato não encontrado")
        inscricoes = [{"piloto_id": i["piloto_id"], "nome": i["nome"],
                       "transponder": i["transponder"], "frequencia": i["frequencia"],
                       "pontos_ranking": i["pontos_ranking"]}
                      for i in self.banco.listar_inscricoes(campeonato_id)]
        baterias = []
        for b in self.banco.listar_baterias(campeonato_id):
            resultados = self.banco.resultados_bateria(b["id"])
            pilotos_bat = [PilotoCamp(piloto_id=i["piloto_id"], nome=i["nome"],
                                      transponder=i["transponder"],
                                      frequencia=i["frequencia"])
                           for i in inscricoes]  # validação por inscritos do campeonato
            # conflito só entre pilotos desta bateria (resultados conhecidos)
            nomes_bat = {r["nome"] for r in resultados}
            pilotos_bat = [p for p in pilotos_bat if p.nome in nomes_bat]
            validacao = validar_espectro(pilotos_bat)
            baterias.append({"id": b["id"], "nome": b["nome"], "fase": b["fase"],
                             "liberada": bool(b["liberada"]),
                             "espectro": validacao,
                             "resultados": [{"posicao": r["posicao"], "nome": r["nome"],
                                             "pontos": r["pontos"]} for r in resultados]})
        return {"campeonato": {"id": camp["id"], "nome": camp["nome"],
                               "numero_provas": camp["numero_provas"],
                               "pilotos_por_prova": camp["pilotos_por_prova"],
                               "drop_rounds": camp["drop_rounds"],
                               "bonus_pole": camp["bonus_pole"],
                               "bonus_melhor_volta": camp["bonus_melhor_volta"]},
                "inscritos": inscricoes, "baterias": baterias,
                "pilotos": [{"id": p["id"], "nome": p["nome"]}
                            for p in self.banco.listar_pilotos()]}

    def inscrever_piloto(self, campeonato_id: int, piloto_id: int,
                         transponder=None, frequencia=None) -> bool:
        return self.banco.inscrever(campeonato_id, piloto_id, transponder, frequencia)

    def gerar_heats_campeonato(self, campeonato_id: int, num_finais: int = 1,
                               numero_etapa: Optional[int] = None) -> Dict:
        camp = self.banco.campeonato(campeonato_id)
        if not camp:
            raise ValueError("campeonato não encontrado")
        inscricoes = self.banco.listar_inscricoes(campeonato_id)
        if not inscricoes:
            raise ValueError("campeonato sem inscritos")
        # etapa (reusa a informada ou cria a próxima)
        etapas = self.banco.listar_etapas(campeonato_id)
        if numero_etapa:
            etapa_id = self.banco.criar_etapa(campeonato_id, numero_etapa)
        else:
            proxima = (etapas[-1]["numero"] + 1) if etapas else 1
            etapa_id = self.banco.criar_etapa(campeonato_id, proxima)

        pilotos = [PilotoCamp(piloto_id=i["piloto_id"], nome=i["nome"],
                              transponder=i["transponder"], frequencia=i["frequencia"],
                              pontos_ranking=i["pontos_ranking"])
                   for i in inscricoes]
        heats, finais = gerar_heats(pilotos, int(camp["pilotos_por_prova"]), num_finais)

        saida = {"etapa_id": etapa_id, "baterias": [], "bloqueadas": 0}
        for heat in heats + finais:
            bat_id = self.banco.criar_bateria(etapa_id, heat.nome,
                                              "heat" if heat.nome.startswith("Heat")
                                              else "final")
            validacao = validar_espectro(heat.pilotos)
            if not validacao["ok"]:
                saida["bloqueadas"] += 1
            saida["baterias"].append({
                "id": bat_id, "nome": heat.nome,
                "pilotos": [{"piloto_id": p.piloto_id, "nome": p.nome,
                             "transponder": p.transponder, "frequencia": p.frequencia}
                            for p in heat.pilotos],
                "espectro": validacao})
        self.publicar("campeonato", {"msg": "heats gerados"})
        return saida

    def lancar_resultado_bateria(self, bateria_id: int,
                                 resultados: Optional[List[Dict]] = None) -> Dict:
        """Lança resultado: usa a classificação ao vivo (ou lista manual)."""
        if resultados is None:
            if not self.motor:
                raise RuntimeError("nenhuma sessão ativa para lançar resultado")
            resultados = [{"nome": l.nome, "piloto_id": l.piloto_id,
                           "posicao": l.posicao,
                           "melhor_volta_us": int(l.melhor_volta_us or 0)}
                          for l in self.motor.classificacao()]
        # regulamento do campeonato da bateria
        row = self.banco.conn.execute(
            "SELECT c.* FROM baterias b JOIN etapas e ON e.id = b.etapa_id"
            " JOIN campeonatos c ON c.id = e.campeonato_id WHERE b.id = ?",
            (bateria_id,)).fetchone()
        if not row:
            raise ValueError("bateria não encontrada")
        reg = self._regulamento(row)
        nome_para_id = {i["nome"]: i["piloto_id"]
                        for i in self.banco.listar_inscricoes(row["id"])}
        lancados = 0
        for r in resultados:
            piloto_id = r.get("piloto_id") or nome_para_id.get(r.get("nome"))
            if piloto_id is None:
                continue
            melhor = r.get("melhor_volta_us") or 0
            melhor_abs = min((x.get("melhor_volta_us") or 0 for x in resultados), default=0)
            pole = r.get("posicao") == 1
            mv = bool(melhor and melhor == melhor_abs)
            pontos = calcular_pontos(r["posicao"], reg, pole=pole and reg.bonus_pole > 0,
                                     melhor_volta=mv and reg.bonus_melhor_volta > 0)
            self.banco.registrar_resultado(bateria_id, piloto_id, r["posicao"],
                                           pontos, melhor if melhor else None, int(pole))
            lancados += 1
        self.publicar("campeonato", {"msg": f"resultado lançado ({lancados} pilotos)"})
        return {"lancados": lancados}

    def ranking_campeonato(self, campeonato_id: int) -> List[Dict]:
        camp = self.banco.campeonato(campeonato_id)
        if not camp:
            raise ValueError("campeonato não encontrado")
        reg = self._regulamento(camp)
        return ranking_geral(self.banco.resultados_campeonato(campeonato_id), reg)

    # ---------------------------------------------------------------- sync de pilotos (CTAD)
    def _exigir_sync(self):
        if not self.sincronizador.configurado:
            raise ErroAuth("sync não configurado - informe e-mail/senha do CTAD")

    def sync_pilotos_site(self, preview: bool = True) -> Dict:
        """Lista (ou importa) os pilotos do CTAD. `preview=True` só simula."""
        self._exigir_sync()
        r = self.sincronizador.importar_pilotos(preview=preview)
        if not preview:
            self.publicar("pilotos", {"msg": "pilotos sincronizados com o CTAD"})
            self.publicar("sync", {"msg": "pilotos importados do site"})
        return r

    def sync_exportar_piloto(self, piloto_id: int) -> Dict:
        """Cria um piloto do app no CTAD (não sobrescreve)."""
        self._exigir_sync()
        r = self.sincronizador.exportar_piloto(piloto_id)
        self.publicar("sync", {"msg": f"piloto exportado: {r.get('nome', piloto_id)}"})
        return r

    def sync_importar_campeonato(self, campeonato_id: int, chave: str,
                                 preview: bool = True) -> Dict:
        """Traz configuração (chaves!) e inscritos de um campeonato do CTAD."""
        self._exigir_sync()
        r = self.sincronizador.importar_campeonato(chave, campeonato_id, preview=preview)
        if not preview:
            self.publicar("pilotos", {"msg": "inscritos importados do CTAD"})
            self.publicar("campeonato", {"msg": f"campeonato '{chave}' sincronizado"})
        return r

    # ---------------------------------------------------------------- ponte CTAD (plano local)
    def ctad_campeonato_previar(self, chave: str) -> Dict:
        """Prévia da config de um campeonato do CTAD, para o plano de etapas local.

        Mostra o que o site usa nas Chaves A/B/C (``pilotosPorChave`` e
        ``inverterSegundaBateria``) sem precisar criar campeonato no KChrono.
        """
        if not self.sincronizador.configurado:
            raise ErroAuth("sync não configurado - informe e-mail/senha do CTAD")
        return self.sincronizador.campeonato_site(chave)

    # ---------------------------------------------------------------- histórico (Central de Voltas)
    def historico(self) -> List[Dict]:
        saida = []
        for s in self.banco.listar_sessoes():
            if not s["n_voltas"]:
                continue
            saida.append({
                "id": s["id"], "tipo": s["tipo"], "estado": s["estado"],
                "inicio": s["inicio"], "fim": s["fim"],
                "voltas": s["n_voltas"], "pilotos": s["n_pilotos"],
                "melhor_s": round(s["melhor_us"] / 1_000_000, 3)
                if s["melhor_us"] else None})
        return saida

    def historico_sessao(self, sessao_id: str) -> Dict:
        rows = self.banco.voltas_da_sessao_detalhe(sessao_id)
        por: Dict[str, list] = {}
        for r in rows:
            por.setdefault(r["piloto"], []).append(
                {"numero": r["numero"], "tempo": round(r["tempo_us"] / 1e6, 3),
                 "recorde": bool(r["melhor"])})
        pilotos = sorted(por.items(), key=lambda kv: -len(kv[1]))
        max_voltas = max((len(vs) for vs in por.values()), default=0)
        melhor_geral = min((v["tempo"] for vs in por.values() for v in vs), default=None)
        return {"sessao_id": sessao_id, "max_voltas": max_voltas,
                "melhor_geral": melhor_geral,
                "pilotos": [{"nome": n, "voltas": [{"numero": v["numero"],
                                                   "tempo": v["tempo"]}
                                                  for v in vs]}
                            for n, vs in pilotos]}

    # ---------------------------------------------------------------- snapshot
    def snapshot(self) -> Dict:
        motor_estado = self.motor.estado.value if self.motor else "parado"
        tempo_sessao = self.tempo_sessao_s()
        sem_dados_s = None
        if self.conectado and self._ultimo_rx_us:
            sem_dados_s = (agora_monotonic_us() - self._ultimo_rx_us) / 1e6
        return {
            "decoder": {"conectado": self.conectado,
                        "tipo": self.config.get("decoder_tipo", "p3"),
                        "host": getattr(self.driver, "host",
                                        getattr(self.driver, "endereco", None)),
                        "porta": getattr(self.driver, "porta",
                                         getattr(self.driver, "porta_usada", None)),
                        "status": self._ultimo_status,
                        "segundos_sem_dados": sem_dados_s},
            "sessao": {"id": self.sessao_id, "estado": motor_estado,
                       "pausada": self.pausado, "tempo_s": tempo_sessao,
                       "parametros": self.parametros},
            "pista": self.estado_pista(),
            "contadores": self.contadores,
            "classificacao": self._classificacao() if self.motor else [],
            "eventos": self.eventos[-30:],
            "campeonato": self.campeonato_estado(),
        }


def formatar(tempo_us) -> str:
    if tempo_us is None:
        return "-"
    total_s = tempo_us / 1_000_000
    return f"{int(total_s//60)}:{total_s % 60:06.3f}"

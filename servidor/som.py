"""KChrono — módulo de som/locução do servidor (Fase 4).

Centraliza as frases faladas (TTS) e os bipes. Frases configuráveis —
editadas no Admin e persistidas em config.json pelo estado.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Dict, List, Optional

from nucleo.voz import Locutor

log = logging.getLogger("kchrono.som")


def _beep_async(freq: int, ms: int):
    """Bipe não bloqueante.

    ``winsound.Beep`` é síncrono (bloquearia o event loop e atrasaria a linha
    do tempo da largada) — por isso roda numa thread daemon.
    """
    def _run():
        try:
            import winsound
            winsound.Beep(int(freq), int(ms))
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()

#: Frases faladas (placeholders {nome}, {tempo}, {n} são preenchidos na chamada)
FRASES_TTS = {
    "atencao": "Atenção pilotos, preparem-se para a largada!",
    "contagem": "{n}",
    "vai": "Vai!",
    "treino_iniciado": "Treino iniciado. Boa prática a todos!",
    "treino_finalizado": "Treino finalizado.",
    "classificacao_iniciada": "Classificação iniciada. Pista livre para todos os pilotos. Boa sorte!",
    "classificacao_finalizada": "Classificação finalizada.",
    "pausada": "Sessão pausada.",
    "retomada": "Sessão retomada.",
    "finalizada": "Sessão finalizada. Confiram a classificação.",
    "melhor_volta": "Melhor volta: {nome}, {tempo} segundos.",
    "volta": "Volta {numero}: {nome}, {tempo} segundos.",
    "posicoes": "Posições: {lista}.",
    "recorde_pessoal": "Novo recorde pessoal de {nome}: {tempo} segundos!",
    "recorde_pista": "Novo recorde da pista! {nome}, {tempo} segundos!",
    "ghost_lap": "Atenção: volta inválida detectada.",
    "gato": "Atenção: volta marcada como suspeita.",
    "tempo_esgotado": "Tempo acabou! Faltam {n} segundos para concluir a volta.",
    "piloto_finalizou": "{nome} finalizou!",
    "todos_finalizaram": "Todos os pilotos finalizaram. Sessão encerrada.",
    # Eventos (1) — pista/largada/corrida
    "pista_aberta": "Pista aberta para os pilotos:",
    "pista_aberta_treino": "Pista aberta para treino por",
    "carros_prontos": "Carros prontos para largar",
    "largada_liberada": "{nome}, largada liberada",
    "stop_and_go": "{nome}: pare e siga",
    "todos_terminaram": "Todos os pilotos terminaram. Pista fechada.",
    "piloto_terminou": "{nome} terminou",
    "treino_encerrado": "Treino encerrado. Os pilotos devem estar prontos para largar",
    "para_o_fim": "para o fim",
    "deteccao_linha": "{n}% detectado",
    "erro_volta_minima": "erro de volta mínima {nome} {tempo}",
    # Eventos (2) — posições/recordes/estimativa
    "primeira_posicao": "PRIMEIRA POSIÇÃO:",
    "melhor_volta_corrida": "MELHOR VOLTA DA CORRIDA DE: {classe}",
    "melhor_volta_pessoal": "Melhor volta pessoal",
    "melhor_tempo_pessoal": "Melhor tempo pessoal: {classe}",
    "recorde_pista_evento": "{nome} RECORDE DA PISTA {classe} {tempo}",
    "estimativa_chegada": "{nome}, estimativa de chegada: {n} voltas em {tempo}",
    "intervalo_atras": "{nome} {tempo} atrás",
    "estimativa_melhorada": "Estimativa de voltas melhorada",
    "resultado_pessoal_melhorado": "Resultado pessoal melhorado",
    # Sons de passagem (bips) - não usam TTS, são bips puros
    "passagem": "",           # bip curto a cada passagem
    "lider": "",              # bip especial (alto-baixo-alto) quando líder passa
}

#: Ordem e rótulo (PT-BR) de cada frase na tela de Admin.
ROTULOS = [
    ("atencao", "Atenção (largada)"),
    ("vai", "Vai!"),
    ("contagem", "Contagem do semáforo"),
    ("treino_iniciado", "Treino iniciado"),
    ("treino_finalizado", "Treino finalizado"),
    ("classificacao_iniciada", "Classificação"),
    ("classificacao_finalizada", "Classificação finalizada"),
    ("pausada", "Pausada"),
    ("retomada", "Retomada"),
    ("finalizada", "Finalizada"),
    ("volta", "Leitura de volta"),
    ("posicoes", "Leitura de posições"),
    ("recorde_pessoal", "Recorde pessoal"),
    ("recorde_pista", "Recorde da pista"),
    ("melhor_volta", "Melhor volta"),
    ("ghost_lap", "Volta inválida"),
    ("gato", "Gato (suspeita)"),
    ("tempo_esgotado", "Tempo esgotado (início da carência)"),
    ("piloto_finalizou", "Piloto finalizou na carência"),
    ("todos_finalizaram", "Todos finalizaram (fim da carência)"),
    # Eventos (1)
    ("pista_aberta", "Pista aberta para os pilotos"),
    ("pista_aberta_treino", "Pista aberta para treino"),
    ("carros_prontos", "Carros prontos para largar"),
    ("largada_liberada", "Largada liberada (piloto)"),
    ("stop_and_go", "Stop and Go (pare e siga)"),
    ("todos_terminaram", "Todos os pilotos terminaram / pista fechada"),
    ("piloto_terminou", "Piloto terminou"),
    ("treino_encerrado", "Treino encerrado"),
    ("para_o_fim", "Para o fim (alarme)"),
    ("deteccao_linha", "Detecção na linha de chegada"),
    ("erro_volta_minima", "Erro de volta mínima"),
    # Eventos (2)
    ("primeira_posicao", "Primeira posição"),
    ("melhor_volta_corrida", "Melhor volta da corrida"),
    ("melhor_volta_pessoal", "Melhor volta pessoal"),
    ("melhor_tempo_pessoal", "Melhor tempo pessoal"),
    ("recorde_pista_evento", "Recorde da pista (evento)"),
    ("estimativa_chegada", "Estimativa de chegada"),
    ("intervalo_atras", "Intervalo / gap (atrás)"),
    ("estimativa_melhorada", "Estimativa de voltas melhorada"),
    ("resultado_pessoal_melhorado", "Resultado pessoal melhorado"),
    ("passagem", "Bip de passagem (cada piloto)"),
    ("lider", "Bip especial do líder (alto-baixo-alto)"),
]

#: Valores de exemplo usados na pré-escuta de frases com placeholders.
EXEMPLOS = {"{n}": "3", "{nome}": "Piloto", "{tempo}": "9,12",
            "{numero}": "5", "{lista}": "1º Piloto A, 2º Piloto B, 3º Piloto C"}

#: Opções de locução automática (intervalos/eventos), editadas no Admin.
OPCOES_SOM_PADRAO = {
    "intervalo_posicoes": 0,        # segundos entre leituras de posição (0 = desligado)
    "posicoes_topo": 3,              # quantos pilotos ler em cada anúncio
    "anunciar_volta": False,         # fala cada volta (nome + tempo)
    "anunciar_a_cada_voltas": 5,    # lê as posições a cada N voltas do líder (0 = desligado)
    "anunciar_recorde_pessoal": True,
    "anunciar_recorde_pista": True,
    # Controle por tipo de sessão (checkboxes Admin → Voz & Som)
    "anunciar_posicoes_classificacao_durante": True,   # durante a classificação
    "anunciar_posicoes_classificacao_depois": False,    # ao final da classificação
    "anunciar_posicoes_corrida_durante": True,          # durante a corrida
    "anunciar_posicoes_corrida_depois": False,          # ao final da corrida
    # Sons de passagem
    "som_passagem": True,            # bip a cada passagem
    "som_lider": True,               # bip especial do líder
    "som_menor_volta": True,         # 7 bipes da menor volta / recorde
    "bip_luz": True,                 # bipe a cada luz acesa na contagem
    "bip_vai": True,                 # bipe longo no verde (largada)
    # Anúncios estendidos (C42)
    "alarme_fim_corrida": True,      # alarme de fim de corrida
    "falar_tempo_restante": True,    # falar o tempo restante
    "tempo_restante_seg": 30,        # falar o tempo restante com ... s
    "tempo_restante_repetir_seg": 30,# repetir a cada ... s
    "posicoes_troca_lider": 3,      # posições a ler quando houver troca de líder
    "ler_tempos_treino": False,      # ler os tempos do treino
    "ler_estimativa_mudanca": True,  # ler a estimativa quando o valor mudar
    "ler_estimativa_cada_voltas": 0, # ler a estimativa a cada ... voltas (0 = desligado)
    "ler_recorde_melhor_volta_baterias": True,  # ler o recorde de melhor volta em todas as baterias/finais
    "ler_todas_voltas_treino_livre": False,     # ler todas as voltas no treino livre
    "ler_classificacao_cada_min": 0, # ler a classificação a cada ... min (0 = desligado)
    "ler_classificacao_durante_corrida": True,   # leitura da classificação durante a corrida
    "comecar_leitura_volta_n": 1,   # começar a leitura na volta número
    "casas_decimais_volta": 3,      # casas decimais na leitura do tempo de volta
    "ignorar_voltas_maiores_que": 0,# ignorar tempos de volta maiores que ... s (0 = desligado)
    "omitir_minutos_ritmo": False,  # omitir os minutos na leitura do ritmo
    "chamar_pilotos_por": "nome",   # nome | numero | dorsal
}


class ModuloSom:
    """Frases faladas (TTS) + bipes; edição salva em config.json pelo estado."""

    def __init__(self, ativo: bool = True, locutor: Optional[Locutor] = None):
        self.frases = dict(FRASES_TTS)
        self.locutor = locutor
        self.ativo = ativo
        #: chave da frase -> caminho ABSOLUTO de um áudio que substitui a fala
        self.audios: Dict[str, str] = {}
        #: chave da frase -> False desliga aquele som (padrão: ligado)
        self.habilitados: Dict[str, bool] = {"passagem": True, "lider": True}
        if self.ativo and self.locutor is None:
            try:
                self.locutor = Locutor()
            except Exception as e:
                log.warning("módulo de som desligado: %s", e)
                self.ativo = False

    # ----- ligar/desligar sons individualmente -----
    def definir_habilitados(self, mapa: Optional[dict]):
        self.habilitados = {k: bool(v) for k, v in (mapa or {}).items()}

    def habilitado(self, chave: str) -> bool:
        return self.habilitados.get(chave, True)


    # ----- áudios gravados (substituem a frase falada) -----
    def definir_audios(self, audios: Optional[dict]):
        self.audios = {k: v for k, v in (audios or {}).items() if v}

    def _audio_de(self, chave: str) -> Optional[str]:
        caminho = self.audios.get(chave)
        if caminho and os.path.isfile(caminho):
            return caminho
        return None

    def tem_audio(self, chave: str) -> bool:
        caminho = self.audios.get(chave)
        return bool(caminho and os.path.isfile(caminho))

    # ----- configuração de frases -----
    def definir_frases(self, frases: Optional[dict]):
        for chave, texto in (frases or {}).items():
            if chave in FRASES_TTS and texto is not None:
                self.frases[chave] = str(texto)

    def texto(self, chave: str, **kwargs) -> str:
        texto = self.frases.get(chave, chave)
        if kwargs:
            try:
                texto = texto.format(**kwargs)
            except (KeyError, IndexError):
                pass
        return texto

    def frases_publicas(self) -> List[dict]:
        return [{"chave": chave, "rotulo": rotulo, "texto": self.frases.get(chave, ""),
                 "habilitado": self.habilitados.get(chave, True)}
                for chave, rotulo in ROTULOS]

    @staticmethod
    def com_exemplo(texto: str) -> str:
        for marco, valor in EXEMPLOS.items():
            texto = texto.replace(marco, valor)
        return texto

    # ----- fala -----
    def falar(self, chave: str, **kwargs):
        """Fala a frase — ou toca o áudio gravado, se houver para essa chave.

        Respeita a chave ligada/desligada em Admin → Voz & Som.
        """
        if not self.ativo or not self.locutor:
            return
        if self.habilitados.get(chave, True) is False:
            return
        caminho = self.audios.get(chave)
        if caminho and os.path.isfile(caminho):
            self.locutor.tocar_audio(caminho)
            return
        self.locutor.falar(self.texto(chave, **kwargs))

    def ouvir(self, texto: str, chave: Optional[str] = None) -> bool:
        """Pré-escuta (Admin): toca o áudio da frase ou fala o texto."""
        if not self.locutor:
            return False
        caminho = self.audios.get(chave) if chave else None
        if caminho and os.path.isfile(caminho):
            self.locutor.tocar_audio(caminho)
            return True
        self.locutor.ouvir(texto)
        return True

    # ----- sons de passagem -----
    def bip_passagem(self):
        """Bip curto e agudo para cada passagem (padrão: 880Hz, 60ms)."""
        if not self.habilitado("passagem"):
            return
        _beep_async(880, 60)  # agudo, curto

    def bip_lider(self):
        """Bip especial do líder: alto-baixo-alto rápido (3 tons)."""
        if not self.habilitado("lider"):
            return
        # Alto (1200Hz) - Baixo (600Hz) - Alto (1200Hz)
        _beep_async(1200, 55)
        _beep_async(600, 55)
        _beep_async(1200, 55)

    def bip_menor_volta(self):
        """Bip para marcar a menor volta: 7 bipes super curtos e agudos, subindo e descendo o tom."""
        if not self.habilitado("menor_volta"):
            return
        self._padrao_menor_volta()

    def _padrao_menor_volta(self):
        # Padrão: 7 bipes com frequências alternando agudo/grave, 30ms cada
        # (1500/800/1500/700/1500/600/1500 Hz) — sem gate, usado pelos testes
        _beep_async(1500, 30)  # 1º - agudo
        _beep_async(800, 30)   # 2º - grave
        _beep_async(1500, 30)  # 3º - agudo
        _beep_async(700, 30)   # 4º - médio-grave
        _beep_async(1500, 30)  # 5º - agudo
        _beep_async(600, 30)   # 6º - grave
        _beep_async(1500, 30)  # 7º - agudo (fechamento)

    def testar_bip_menor_volta(self):
        """Pré-escuta do bip de menor volta (Admin) — toca mesmo desligado."""
        self._padrao_menor_volta()
        return True

    def bip_contagem(self):
        """Bip de cada luz/numero da contagem (600Hz, 80ms)."""
        if not self.habilitado("bip_luz"):
            return
        _beep_async(600, 80)

    def testar_bip_luz(self):
        """Pré-escuta do bipe da luz da contagem (Admin) — toca mesmo desligado."""
        _beep_async(600, 80)
        return True

    def testar_bip_vai(self):
        """Pré-escuta do bipe do verde (Admin) — toca mesmo desligado."""
        _beep_async(1200, 900)
        return True

    def testar_som_passagem(self):
        """Pré-escuta do bip de passagem (Admin)."""
        self.bip_passagem()
        return True

    def testar_som_lider(self):
        """Pré-escuta do bip do líder (Admin)."""
        self.bip_lider()
        return True

    def audios_publicos(self) -> List[dict]:
        saida = []
        for chave, rotulo in ROTULOS:
            caminho = self.audios.get(chave)
            if caminho and os.path.isfile(caminho):
                saida.append({"chave": chave, "arquivo": os.path.basename(caminho),
                              "url": f"/api/som/audio/{chave}"})
        return saida

    # ----- eventos de corrida -----
    def anunciar_largada(self):
        """'Atenção pilotos, preparem-se para a largada!' + bip de atenção."""
        self.falar("atencao")
        _beep_async(660, 200)

    def bip_largada(self):
        """Bip forte no verde — sinal sonoro da largada (sem locução)."""
        if not self.habilitado("bip_vai"):
            return
        _beep_async(1200, 900)

    def iniciada(self, tipo: str):
        # Na corrida NÃO falamos "Corrida iniciada. Boa sorte a todos!":
        # o anúncio de abertura é a locução da largada ("Atenção pilotos,
        # preparem-se para a largada!"), disparada logo em seguida por
        # anunciar_largada() no fluxo de "Preparar para a Largada".
        if tipo == "corrida":
            return
        if tipo == "classificacao":
            self.falar("classificacao_iniciada")
        else:
            self.falar("treino_iniciado")

    def pausada(self):
        self.falar("pausada")

    def retomada(self):
        self.falar("retomada")

    def _beep(self, freq: int, ms: float):
        """Tone puro (já usado pelos bipes de passagem/leader)."""
        import winsound
        try:
            winsound.Beep(int(freq), int(ms))
        except Exception as e:
            log.warning("bip %sHz/%sms falhou: %s", freq, ms, e)

    def _beep_pattern(self, long_freq: int = 500, long_ms: int = 500,
                      short_freq: int = 1200, short_ms: int = 100, n: int = 5):
        """Toca o padrão em sequência, preservando a cadência dos bips.

        Antes cada bip era colocado em uma thread independente ao mesmo tempo.
        No Windows isso fazia os sons se sobreporem (ou alguns serem perdidos),
        especialmente quando ``finalizada()`` era chamada em uma thread daemon.
        Um único worker mantém a ordem: 1 bip longo, seguido de N bips curtos.
        """
        def _executar():
            self._beep(long_freq, long_ms)
            for _ in range(max(0, int(n))):
                self._beep(short_freq, short_ms)
                threading.Event().wait(0.08)

        threading.Thread(target=_executar, daemon=True, name="kchrono-bips-final").start()

    def bip_finalizacao(self):
        """Bip de finalização da sessão (1 longo + 5 curtos) — chamável isoladamente."""
        try:
            self._beep_pattern(500, 500, 1200, 100, 5)
        except Exception as e:
            log.warning("bips de finalização falharam: %s", e)


    def finalizada(self, tipo: str = "", grid_ordenado: Optional[List[int]] = None,
               grid_invertido: bool = False, resultados: Optional[List[Dict]] = None, tocar_beep: bool = True):
        """Anuncia o fim da sessão com padrão de bips + frase própria do tipo.
        
        Padrão sonoro: 1 bip longo + 5 bips curtos e altos.
        Depois fala a frase correspondente ao tipo da sessão.
        
        * ``grid_ordenado`` : lista de posições (1-based) já ordenadas da Pole.
          Ex.: [1, 2, 3, ...] ou [3, 1, 2] se houver inversão.
        * ``grid_invertido`` : se True, a ordem exibida é invertida (último vira Pole).
        * ``resultados`` : lista de dicts com 'posicao' e 'nome' para anunciar
          o resultado da corrida: "O 1º lugar é de [nome], 2º [nome], etc."
        """
        log.info("finalizada: tipo='%s', habilitados=%s", tipo, self.habilitados)
        # padrão de bips: 1 longo + 5 curtos
        try:
            if tocar_beep:
                self._beep_pattern(500, 500, 1200, 100, 5)
        except Exception as e:
            log.warning("bips de fim de sessão falharam: %s", e)
        # frase final
        try:
            if tipo == "treino":
                self.falar("treino_finalizado")
            elif tipo == "classificacao":
                self.falar("classificacao_finalizada")
            else:
                self.falar("finalizada")
        except Exception as e:
            log.warning("frase de fim de sessão falhou: %s", e)
        # anúncios suplementares — posições/grid só quando o chamador liberou
        # (None = desligado). No treino NUNCA, por garantia extra:
        if tipo == "treino":
            return
        if grid_ordenado is not None:
            # anuncia apenas as posições dos pilotos (resultado), sem a listagem
            # redundante de "1º, 2º, 3º..." do grid.
            pass
        if resultados is not None:
            try:
                self._annuncian_resultados(resultados)
            except Exception as e:
                log.warning("anúncio de resultados falhou: %s", e)

    def _posicao_por_extenso(self, n: int) -> str:
        """Retorna '1º', '2º', '3º', '4º', etc."""
        if 10 <= n % 100 <= 20:
            suffix = "º"
        else:
            suffix = {1: "º", 2: "º", 3: "º"}.get(n % 10, "º")
        return f"{n}{suffix}"

    def _annunciar_grid(self, grid_ordenado: List[int], invertido: bool = False):
        """Anuncia a ordem do grid da Pole para trás.
        
        Se invertido=True, a ordem exibida fica ao contrário (último é Pole).
        A fala segue o padrão: "Pole position, [nº], [nº], ..." ou similar.
        """
        if invertido:
            grid_ordenado = list(reversed(grid_ordenado))
        # monta a frase: "Pole position, 2º lugar, 3º lugar, ..."
        partes = []
        for i, pos in enumerate(grid_ordenado, 1):
            if i == 1:
                partes.append("Pole position")
            else:
                partes.append(f"{self._posicao_por_extenso(pos)} lugar")
        if partes:
            frase = ", ".join(partes) + "."
            self.falar(frase)

    def _annuncian_resultados(self, resultados: List[Dict]):
        """Anuncia o resultado da corrida: 'Em primeiro lugar [piloto], 2º [piloto], ...'"""
        if not resultados:
            return
        partes = []
        for r in resultados:
            pos = r.get("posicao", 0)
            nome = r.get("nome", "Desconhecido")
            if pos == 1:
                partes.append(f"Em primeiro lugar {nome}")
            else:
                partes.append(f"{self._posicao_por_extenso(pos)} {nome}")
        if partes:
            if len(partes) == 1:
                frase = partes[0] + "."
            else:
                ultima = partes[-1]
                resto = ", ".join(partes[:-1])
                frase = f"{resto} e {ultima}."
            self.falar(frase)

    def ghost_lap(self):
        self.falar("ghost_lap")

    def gato(self):
        self.falar("gato")

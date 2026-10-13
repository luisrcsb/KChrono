"""KChrono — motor de campeonatos (Fase 5).

Regras puras (sem I/O): grid builder piramidal, varredura de espectro RF,
pontuação com drop rounds e bônus. Configuração de regulamento espelha o
CTAD (numeroProvas, pilotosPorProva, pontuacaoTabela) e é estendida aqui.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

#: tabela padrão (mesma do CTAD / estilo F1)
TABELA_PADRAO = [25, 18, 15, 12, 10, 8, 6, 4, 2, 1]

LETRAS_FINAIS = "ABC"

#: nº máximo de pilotos por chave quando nada é configurado (default do CTAD)
PADRAO_PILOTOS_POR_CHAVE = 10


# ------------------------------------------------------------------ estruturas
@dataclass
class PilotoCamp:
    piloto_id: int
    nome: str
    transponder: Optional[int] = None
    frequencia: Optional[str] = None
    pontos_ranking: float = 0.0     # pontos carreados (define a ordem de entrada)


@dataclass
class Heat:
    nome: str                       # "Heat 1", "Final A"…
    pilotos: List[PilotoCamp] = field(default_factory=list)

    def conflitos(self) -> List[Dict]:
        return validar_espectro(self.pilotos)["conflitos"]


# ------------------------------------------------------------------ grid builder
def gerar_heats(inscritos: List[PilotoCamp], max_por_heat: int,
                num_finais: int = 1) -> Tuple[List[Heat], List[Heat]]:
    """Divide inscritos (já ordenados por ranking) em heats + finais piramidais.

    Distribuição em serpentina nos heats (equilíbrio de forças) e corte
    piramidal nas finais: Final A (melhores), B, C…
    """
    if max_por_heat < 1:
        raise ValueError("max_por_heat deve ser >= 1")
    P = len(inscritos)
    n_heats = max(1, math.ceil(P / max_por_heat))

    heats: List[Heat] = []
    # serpentina: 1..M | 2M..M+1 | 2M+1..3M ...
    for h in range(n_heats):
        if h % 2 == 0:
            bloco = inscritos[h * max_por_heat:(h + 1) * max_por_heat]
        else:
            ini = h * max_por_heat
            bloco = list(reversed(inscritos[ini:ini + max_por_heat]))
        heats.append(Heat(nome=f"Heat {h + 1}", pilotos=bloco))

    finais: List[Heat] = []
    restantes = list(inscritos)
    for i in range(num_finais):
        tam = max_por_heat if num_finais > 1 else min(len(restantes), max_por_heat)
        finais.append(Heat(nome=f"Final {LETRAS_FINAIS[i % len(LETRAS_FINAIS)]}",
                           pilotos=restantes[:tam]))
        restantes = restantes[tam:]
    return heats, finais


def promover_para_finais(resultados_heats: Dict[str, List[Tuple[str, float]]],
                         num_finais: int,
                         tamanho_final: int) -> List[Heat]:
    """Classifica pelos pontos somados nos heats e corta nas finais (A, B, C…).

    resultados_heats: {"Heat 1": [(nome_piloto, pontos), ...], ...}
    """
    soma: Dict[str, float] = {}
    for heat, resultados in resultados_heats.items():
        for nome, pontos in resultados:
            soma[nome] = soma.get(nome, 0.0) + pontos
    ordenados = sorted(soma.items(), key=lambda kv: (-kv[1], kv[0]))
    finais: List[Heat] = []
    restantes = [nome for nome, _ in ordenados]
    for i in range(num_finais):
        finais.append(Heat(nome=f"Final {LETRAS_FINAIS[i % len(LETRAS_FINAIS)]}",
                           pilotos=[PilotoCamp(piloto_id=-1, nome=n) for n in restantes[:tamanho_final]]))
        restantes = restantes[tamanho_final:]
    return finais


# ------------------------------------------------------------------ espectro RF
def validar_espectro(pilotos: List[PilotoCamp]) -> Dict:
    """Invariância: transponders e frequências distintos dentro da mesma bateria."""
    conflitos: List[Dict] = []
    for i in range(len(pilotos)):
        for j in range(i + 1, len(pilotos)):
            a, b = pilotos[i], pilotos[j]
            if a.transponder is not None and a.transponder == b.transponder:
                conflitos.append({"pilotos": [a.nome, b.nome], "tipo": "transponder",
                                  "valor": a.transponder})
            if a.frequencia and b.frequencia and a.frequencia == b.frequencia:
                conflitos.append({"pilotos": [a.nome, b.nome], "tipo": "frequencia",
                                  "valor": a.frequencia})
    return {"ok": not conflitos, "conflitos": conflitos}


def frequencias_livres(espectro: List[str], usadas: List[str]) -> List[str]:
    return [f for f in espectro if f not in usadas]


# ------------------------------------------------------------------ pontuação
@dataclass
class Regulamento:
    tabela: List[int] = field(default_factory=lambda: list(TABELA_PADRAO))
    drop_rounds: int = 0                 # descartar as N piores etapas
    bonus_pole: int = 0                  # pontos extras pela pole
    bonus_melhor_volta: int = 0          # pontos extra pela melhor volta absoluta
    numero_provas: int = 4
    pilotos_por_prova: int = 10
    #: nº máximo de pilotos por chave (divisão da grade em Chave A/B/C…)
    pilotos_por_chave: int = PADRAO_PILOTOS_POR_CHAVE


# ------------------------------------------------------------------ chaves (grade)
def calcular_distribuicao_chaves(total_pilotos: int, max_por_chave) -> List[int]:
    """Divide o total de pilotos em chaves, conforme a diretiva do CTAD.

    Regras:
      * ``total <= 0``            -> ``[]`` (sem grade)
      * ``total <= max``          -> ``[total]`` (chave única)
      * nº de chaves              = ``ceil(total / max)`` (pode diminuir depois)
      * a **primeira** chave absorve o excedente, **sem** estourar o teto
      * "ninguém corre sozinho": chave final com 1 piloto é absorvida pela anterior
    """
    try:
        maxc = int(max_por_chave)
    except (TypeError, ValueError):
        maxc = PADRAO_PILOTOS_POR_CHAVE
    maxc = max(1, maxc or PADRAO_PILOTOS_POR_CHAVE)

    total = int(total_pilotos or 0)
    if total <= 0:
        return []
    if total <= maxc:
        return [total]

    n = math.ceil(total / maxc)
    base = total // n
    dist = [base] * n
    resto = total - base * n

    # o excedente vai para a 1ª chave em diante, respeitando o teto
    i = 0
    while resto > 0 and i < n:
        espaco = maxc - dist[i]
        add = min(resto, espaco)
        dist[i] += add
        resto -= add
        i += 1

    # ninguém corre sozinho: absorve a última chave se tiver 1 só piloto
    while len(dist) > 1 and dist[-1] == 1:
        ultimo = dist.pop()
        dist[-1] += ultimo
    return dist


def rotulo_chave(indice: int) -> str:
    """Rótulo da chave: ``A``, ``B`` … ``Z`` e, acima de 26, ``27``, ``28``…"""
    if 0 <= indice < 26:
        return chr(ord("A") + indice)
    return str(indice + 1)


def dividir_grade_em_chaves(inscritos: List[PilotoCamp],
                            max_por_chave: int) -> List[Heat]:
    """Corte **contíguo** da grade (já ordenada) nas chaves A, B, C…

    Como a grade chega ordenada por desempenho, a Chave A é o grupo mais rápido,
    a B o seguinte, e assim por diante (semeadura por performance, não sorteio).
    """
    dist = calcular_distribuicao_chaves(len(inscritos), max_por_chave)
    chaves: List[Heat] = []
    cursor = 0
    for i, tam in enumerate(dist):
        chaves.append(Heat(nome=f"Chave {rotulo_chave(i)}",
                           pilotos=list(inscritos[cursor:cursor + tam])))
        cursor += tam
    return chaves


def ordenar_por_treino(voltas_por_piloto: Dict[int, List[float]],
                       n_melhores: int = 3) -> List[Tuple[int, float]]:
    """Ordem de grade pelo treino: média das **N melhores voltas consecutivas**.

    Devolve ``[(piloto_id, media_s), ...]`` ascendente (menor média = 1º).
    Pilotos com menos de N voltas entram pela média simples do que têm.
    """
    saida: List[Tuple[int, float]] = []
    for pid, voltas in (voltas_por_piloto or {}).items():
        vals = [float(v) for v in (voltas or [])]
        if not vals:
            continue
        if len(vals) < n_melhores:
            media = sum(vals) / len(vals)
        else:
            melhor = None
            for i in range(len(vals) - n_melhores + 1):
                j = sum(vals[i:i + n_melhores]) / n_melhores
                if melhor is None or j < melhor:
                    melhor = j
            media = melhor
        saida.append((pid, media))
    saida.sort(key=lambda kv: kv[1])
    return saida


def ordenar_por_resultado(resultado: List[Dict], inverter: bool = False) -> List[Dict]:
    """Ordem da grade pela prova anterior: +voltas, depois -tempo total, depois -melhor volta.

    ``resultado`` = ``[{"piloto_id", "voltas", "tempo_total_s", "melhor_volta_s"}, ...]``.
    Quando não há dados de voltas (ex.: classificação importada), usa a ``posicao``
    (1º melhor). Com ``inverter=True`` a lista é invertida (bateria seguinte espelhada).
    """
    def chave(r: Dict):
        voltas = r.get("voltas")
        if voltas is None:
            voltas = -int(r.get("posicao", 10 ** 6) or 10 ** 6)
        return (-int(voltas),
                float(r.get("tempo_total_s") or 1e18),
                float(r.get("melhor_volta_s") or 1e18))

    ordenado = sorted(resultado or [], key=chave)
    return list(reversed(ordenado)) if inverter else ordenado


def montar_grids_campeonato(inscritos: List[PilotoCamp], max_por_chave: int,
                            resultados_por_prova: Optional[List[List[Dict]]] = None,
                            treino_voltas: Optional[Dict[int, List[float]]] = None,
                            inverter_seguinte: bool = False,
                            n_provas: Optional[int] = None) -> List[Dict]:
    """Monta uma grade (dividida em chaves) por prova.

    * Prova 1  -> ordem do **treino** (3 melhores voltas consecutivas) quando
      ``treino_voltas`` é informado; caso contrário, ordem dos inscritos ("Padrão").
    * Provas 2+ -> resultado da prova anterior (``resultados_por_prova``),
      opcionalmente invertido (``inverter_seguinte``).

    Retorna ``[{"prova", "criterio", "distribuicao", "chaves": [Heat, ...]}, ...]``.
    """
    por_id = {p.piloto_id: p for p in inscritos}
    provas = n_provas or ((len(resultados_por_prova) + 1) if resultados_por_prova else 1)
    grids: List[Dict] = []

    for g in range(provas):
        if g == 0:
            if treino_voltas:
                ordem = ordenar_por_treino(treino_voltas)
                pos = {pid: i for i, (pid, _) in enumerate(ordem)}
                ordenados = [p for p in inscritos if p.piloto_id in pos]
                ordenados.sort(key=lambda p: pos[p.piloto_id])
                base = ordenados + [p for p in inscritos if p.piloto_id not in pos]
                criterio = "Treino"
            else:
                base = list(inscritos)
                criterio = "Padrão"
        else:
            anterior = resultados_por_prova[g - 1] \
                if resultados_por_prova and g - 1 < len(resultados_por_prova) else None
            if not anterior:
                base = list(inscritos)
                criterio = "Aguardando"
            else:
                ordenado = ordenar_por_resultado(anterior, inverter=inverter_seguinte)
                base = [por_id[r["piloto_id"]] for r in ordenado
                        if r.get("piloto_id") in por_id]
                base += [p for p in inscritos if p not in base]
                criterio = "Invertido" if inverter_seguinte else "Direto"

        chaves = dividir_grade_em_chaves(base, max_por_chave)
        grids.append({
            "prova": g + 1,
            "criterio": criterio,
            "max_por_chave": max(1, int(max_por_chave or PADRAO_PILOTOS_POR_CHAVE)),
            "distribuicao": [len(c.pilotos) for c in chaves],
            "chaves": chaves,
        })
    return grids


def calcular_pontos(posicao: int, reg: Regulamento,
                    pole: bool = False, melhor_volta: bool = False) -> int:
    pontos = reg.tabela[posicao - 1] if 1 <= posicao <= len(reg.tabela) else 0
    if pole:
        pontos += reg.bonus_pole
    if melhor_volta:
        pontos += reg.bonus_melhor_volta
    return pontos


def ranking_geral(resultados: Dict[str, Dict[str, List[int]]], reg: Regulamento) -> List[Dict]:
    """ranking: {piloto: {etapa: [pontos, ...]}} com drop rounds.

    `resultados` = {nome_piloto: {etapa: pontos}} — devolve lista ordenada com
    detalhamento (válidos, descartados, total).
    """
    linhas = []
    for piloto, etapas in resultados.items():
        valores = sorted((float(p) for p in etapas.values()), reverse=True)
        if reg.drop_rounds > 0 and len(valores) > reg.drop_rounds:
            validos = valores[:len(valores) - reg.drop_rounds]
            descartados = valores[len(valores) - reg.drop_rounds:]
        else:
            validos, descartados = valores, []
        linhas.append({"piloto": piloto, "etapas": etapas,
                       "validos": validos, "descartados": descartados,
                       "total": sum(validos)})
    linhas.sort(key=lambda l: (-l["total"], l["piloto"]))
    for pos, l in enumerate(linhas, start=1):
        l["posicao"] = pos
    return linhas

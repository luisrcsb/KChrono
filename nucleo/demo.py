"""KChrono — validação do motor (Fase 1).

Duas verificações:
1. REPLAY da captura real de 11/10/2026 (29 passings do transponder 7096340
   no decoder 192.168.0.50) — valida consolidação de voltas, gap e idempotência.
2. SIMULAÇÃO com 3 pilotos — valida classificação, gaps por tempo e por voltas.

Rode: python cli.py replay
"""
from __future__ import annotations

import time
from typing import List, Tuple

from drivers.base import Passing
from .banco import Banco
from .modelos import TipoSessao, formatar_tempo
from .motor_corrida import MotorCorrida
from .relogio import MonitorDrift, agora_epoch_us, agora_monotonic_us
from .ring_buffer import RingBuffer

#: (passing_number, rtc_time_us, strength, hits) — captura real (captura_passing.txt)
CAPTURA_REAL: List[Tuple[int, int, int, int]] = [
    (9156, 1791996679230944, 90, 87),
    (9157, 1791996690879944, 70, 3),
    (9158, 1791996705204944, 103, 552),
    (9159, 1791996720241944, 82, 69),
    (9160, 1791996729837944, 79, 43),
    (9161, 1791996739300944, 93, 89),
    (9162, 1791996745005944, 129, 220),
    (9164, 1791996756020944, 111, 146),   # #9163 não chegou (gap!)
    (9165, 1791996761988944, 111, 148),
    (9166, 1791996769283944, 89, 76),
    (9167, 1791996779499944, 89, 79),
    (9168, 1791996785110944, 102, 117),
    (9169, 1791996791360944, 89, 76),
    (9170, 1791996805086944, 96, 83),
    (9171, 1791996813503944, 107, 121),
    (9172, 1791996819614944, 92, 73),
    (9173, 1791996827826944, 100, 117),
    (9174, 1791996834964944, 88, 71),
    (9175, 1791996842402944, 93, 89),
    (9176, 1791996849555944, 84, 42),
    (9177, 1791996860923944, 97, 100),
    (9178, 1791996867907944, 87, 70),
    (9179, 1791996877055944, 90, 60),
    (9180, 1791996883556944, 76, 25),
    (9181, 1791996891427944, 72, 7),
    (9182, 1791996902398248, 81, 37),
    (9183, 1791996904579944, 89, 97),
    (9184, 1791996910733944, 97, 72),
    (9185, 1791996925038328, 77, 13),
]


def demo_replay() -> bool:
    print("=" * 66)
    print("1) REPLAY da captura real (29 passings, transponder 7096340)")
    print("=" * 66)
    ok = True

    banco = Banco(":memory:")
    piloto_id = banco.criar_piloto("Krathus (replay)", "KR")
    transponder = 7096340
    banco.vincular_transponder(transponder, piloto_id)
    sessao = banco.abrir_sessao(pista_id=None, tipo=TipoSessao.TREINO)

    motor = MotorCorrida(banco=banco, sessao_id=sessao)
    motor.registrar_transponder(transponder, piloto_id)
    motor.vincular_piloto(piloto_id, "Krathus (replay)")
    motor.iniciar(TipoSessao.TREINO)

    voltas = []
    for pn, rtc, strength, hits in CAPTURA_REAL:
        v = motor.processar_passing(Passing(
            transponder=transponder, rtc_time=rtc, passing_number=pn,
            strength=strength, hits=hits))
        if v:
            voltas.append(v)

    total_us = motor._pilotos[piloto_id].tempo_total_us
    melhor = motor._pilotos[piloto_id].melhor_volta_us

    print(f"passings processados : {len(CAPTURA_REAL)}")
    print(f"voltas consolidadas  : {len(voltas)} (esperado 28 = 29 passings - 1 saída)")
    print(f"tempo total          : {formatar_tempo(total_us)}")
    print(f"melhor volta         : {formatar_tempo(melhor)}")
    print(f"gaps detectados      : {len(motor.gaps)} -> {motor.gaps}")
    print(f"passings sem piloto  : {len(motor.passings_sem_piloto)}")

    # verificações
    if len(voltas) != 28:
        print("FALHA: esperado 28 voltas"); ok = False
    if len(motor.gaps) != 1 or motor.gaps[0]["faltando"] != 1:
        print("FALHA: gap de 1 passing esperado (#9162 -> #9164)"); ok = False
    if motor.passings_sem_piloto:
        print("FALHA: passings sem piloto"); ok = False
    if melhor is None or melhor > 10_000_000:
        print("FALHA: melhor volta fora do esperado (~2.2s ~ 15s)"); ok = False

    # idempotência: repetir tudo não pode duplicar voltas no banco
    voltas_banco = banco.voltas_da_sessao(sessao)
    motor2 = MotorCorrida(banco=banco, sessao_id=sessao)
    motor2.registrar_transponder(transponder, piloto_id)
    motor2.vincular_piloto(piloto_id, "Krathus (replay)")
    motor2.iniciar(TipoSessao.TREINO)
    for pn, rtc, strength, hits in CAPTURA_REAL:
        motor2.processar_passing(Passing(transponder=transponder, rtc_time=rtc,
                                         passing_number=pn, strength=strength,
                                         hits=hits))
    if len(banco.voltas_da_sessao(sessao)) != len(voltas_banco):
        print("FALHA: replay duplicou voltas no banco"); ok = False
    else:
        print(f"idempotência         : OK ({len(voltas_banco)} voltas no banco)")

    motor.finalizar()
    print("RESULTADO:", "OK" if ok else "FALHOU")
    return ok


def demo_simulacao() -> bool:
    print()
    print("=" * 66)
    print("2) SIMULAÇÃO com 3 pilotos (classificação, gap por tempo e voltas)")
    print("=" * 66)
    ok = True

    banco = Banco(":memory:")
    sessao = banco.abrir_sessao(pista_id=None, tipo=TipoSessao.CORRIDA)
    # nome, transponder, tempo de volta (µs), nº de passagens
    pilotos = [("Ana", 1001, 12_000_000, 6),     # 6 passagens = 5 voltas
               ("Bruno", 1002, 11_500_000, 6),   # 5 voltas, mais rápido
               ("Carla", 1003, 13_000_000, 5)]   # 5 passagens = 4 voltas

    motor = MotorCorrida(banco=banco, sessao_id=sessao)
    rtc = {}
    for nome, cod, _, _ in pilotos:
        pid = banco.criar_piloto(nome)
        banco.vincular_transponder(cod, pid)
        motor.registrar_transponder(cod, pid)
        motor.vincular_piloto(pid, nome)
        rtc[nome] = 1_800_000_000_000_000  # base arbitrária (µs)

    motor.iniciar(TipoSessao.CORRIDA)
    motor.largada()

    pn = 1
    for rodada in range(6):
        for nome, cod, volta_us, n_pass in pilotos:
            if rodada >= n_pass:
                continue
            rtc[nome] += volta_us
            motor.processar_passing(Passing(transponder=cod, rtc_time=rtc[nome],
                                            passing_number=pn))
            pn += 1

    print(f"{'#':>2} {'piloto':<8} {'voltas':>6} {'tempo':>9} {'melhor':>9}  gap")
    for linha in motor.classificacao():
        print(f"{linha.posicao:>2} {linha.nome:<8} {linha.voltas:>6} "
              f"{formatar_tempo(linha.tempo_total_us):>9} "
              f"{formatar_tempo(linha.melhor_volta_us):>9}  {linha.gap}")

    classificacao = motor.classificacao()
    if [l.nome for l in classificacao] != ["Bruno", "Ana", "Carla"]:
        print("FALHA: ordem esperada Bruno, Ana, Carla"); ok = False
    if classificacao[0].gap != "" or classificacao[1].gap != "+0:02.500" or \
            classificacao[2].gap != "+1 volta(s)":
        print("FALHA: gaps incorretos"); ok = False

    motor.finalizar()
    print("RESULTADO:", "OK" if ok else "FALHOU")
    return ok


def demo_nucleo_hard() -> bool:
    print()
    print("=" * 66)
    print("3) NUCLEO HARD (Fase 1.5): relogio · ring buffer · ghost lap · drift")
    print("=" * 66)
    ok = True

    # 3.1 relogio de alta precisao
    t1 = agora_monotonic_us()
    time.sleep(0.002)
    t2 = agora_monotonic_us()
    delta_ms = (t2 - t1) / 1000
    print(f"relogio        : 2 medidas com 2 ms de intervalo -> delta {delta_ms:.3f} ms "
          f"({t2 - t1} us)")
    if not (1.5 < delta_ms < 8.0):
        print("FALHA: precisao do relogio fora do esperado"); ok = False
    else:
        print("                 precisao OK (monotonico, imune a NTP)")

    # 3.2 monitor de drift
    monitor = MonitorDrift(limite_us=500_000)
    drift = monitor.observar(agora_epoch_us() + 2_000_000)   # decoder 2 s a frente
    print(f"drift          : decoder 2 s a frente -> alerta em {drift} us")
    if drift is None:
        print("FALHA: drift de 2 s deveria ser reportado"); ok = False
    if monitor.observar(agora_epoch_us()) is not None:
        print("FALHA: drift zero nao deveria alertar"); ok = False
    else:
        print("                 decoder sincronizado: sem alerta")

    # 3.3 ring buffer (capacidade 3, 5 pushes)
    rb = RingBuffer(3)
    for i in range(5):
        rb.push(f"p{i}")
    stats = rb.stats()
    print(f"ring buffer    : {stats['recebidos']} recebidos / {stats['descartados']} "
          f"descartados / {rb.tamanho} retidos (esperado 5/2/3)")
    conteudo = rb.pop_tudo()
    if stats["recebidos"] != 5 or stats["descartados"] != 2 or len(conteudo) != 3 \
            or conteudo != ["p2", "p3", "p4"]:
        print(f"FALHA: ring buffer -> {conteudo}"); ok = False
    else:
        print("                 descarte seguro dos mais antigos OK")

    # 3.4 filtro de ghost lap (tempo minimo de 5 s)
    banco = Banco(":memory:")
    piloto_id = banco.criar_piloto("Fantasma (ghost test)")
    transponder = 555
    banco.vincular_transponder(transponder, piloto_id)
    sessao = banco.abrir_sessao(pista_id=None, tipo=TipoSessao.TREINO)
    motor = MotorCorrida(banco=banco, sessao_id=sessao,
                         tempo_minimo_volta_us=5_000_000)
    motor.registrar_transponder(transponder, piloto_id)
    motor.vincular_piloto(piloto_id, "Fantasma (ghost test)")
    motor.iniciar(TipoSessao.TREINO)
    base = 1_000_000_000_000
    motor.processar_passing(Passing(transponder=transponder, rtc_time=base,
                                    passing_number=1))                     # saida
    r2 = motor.processar_passing(Passing(transponder=transponder,
                                         rtc_time=base + 1_000_000,
                                         passing_number=2))                 # delta 1 s
    r3 = motor.processar_passing(Passing(transponder=transponder,
                                         rtc_time=base + 7_000_000,
                                         passing_number=3))                 # delta 6 s
    invalidos = banco.contar_passings_invalidos(sessao)
    voltas = len(motor._pilotos[piloto_id].voltas)
    print(f"ghost lap      : voltas={voltas} rejeitados={len(motor.rejeitados)} "
          f"passings invalidos no banco={invalidos}")
    if r2 is not None or r3 is None or voltas != 1 or len(motor.rejeitados) != 1 \
            or invalidos != 1:
        print("FALHA: filtro de ghost lap"); ok = False
    else:
        print("                 volta fantasma descartada + passagem auditada OK")
    motor.finalizar()

    print("RESULTADO:", "OK" if ok else "FALHOU")
    return ok


def main() -> int:
    ok1 = demo_replay()
    ok2 = demo_simulacao()
    ok3 = demo_nucleo_hard()
    print()
    print("GERAL:", "FASE 1 + 1.5 VALIDADAS" if (ok1 and ok2 and ok3)
          else "COM FALHAS")
    return 0 if (ok1 and ok2 and ok3) else 1

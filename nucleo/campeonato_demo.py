"""KChrono — validação do motor de campeonatos (Fase 5).

Simula um campeonato completo: grid builder (serpentina + finais piramidais),
varredura de espectro RF, promoção para finais e ranking com drop rounds e
bônus. Rode: python cli.py campeonato-teste
"""
from __future__ import annotations

from .campeonatos import (PilotoCamp, Regulamento, frequencias_livres, gerar_heats,
                          promover_para_finais, ranking_geral, validar_espectro)

ESPECTRO = [f"40.{canal:03d}" for canal in range(40, 100)]   # canais de exemplo


def main() -> int:
    print("=" * 68)
    print("MOTOR DE CAMPEONATOS (Fase 5)")
    print("=" * 68)
    ok = True

    # ---------------------------------------------------------- 1. grid builder
    inscritos = [PilotoCamp(piloto_id=i, nome=f"P{i:02d}",
                            transponder=700000 + i,
                            frequencia=ESPECTRO[(i // 3) % len(ESPECTRO)],
                            pontos_ranking=100 - i)
                 for i in range(23)]
    # conflito proposital: P01 mesmo transponder e frequência de P00 (caem no Heat 1)
    inscritos[1].transponder = inscritos[0].transponder
    inscritos[1].frequencia = inscritos[0].frequencia

    heats, finais = gerar_heats(inscritos, max_por_heat=10, num_finais=2)
    print(f"1) GRID BUILDER — {len(inscritos)} inscritos, máx 10/heat:")
    for h in heats + finais:
        print(f"   {h.nome:<9} {len(h.pilotos):>2} pilotos  "
              f"(#{h.pilotos[0].nome}…#{h.pilotos[-1].nome})" if h.pilotos else
              f"   {h.nome:<9}  0 pilotos")
    tamanhos_ok = ([len(h.pilotos) for h in heats] == [10, 10, 3]
                   and [len(f.pilotos) for f in finais] == [10, 10])
    print(f"   heats={[len(h.pilotos) for h in heats]} finais={[len(f.pilotos) for f in finais]}"
          f" {'OK' if tamanhos_ok else 'FALHOU'}")
    if not tamanhos_ok:
        ok = False

    # ---------------------------------------------------------- 2. espectro RF
    print("\n2) VARREDURA DE ESPECTRO (Heat 1):")
    v = validar_espectro(heats[0].pilotos)
    for c in v["conflitos"]:
        print(f"   CONFLITO {c['tipo']}: {c['pilotos'][0]} x {c['pilotos'][1]} ({c['valor']})")
    espectro_ok = (not v["ok"]
                   and any(c["tipo"] == "transponder" and set(c["pilotos"]) == {"P00", "P01"}
                           for c in v["conflitos"])
                   and any(c["tipo"] == "frequencia" for c in v["conflitos"]))
    print(f"   {len(v['conflitos'])} conflito(s) — transponder P00×P01 + "
          f"{sum(1 for c in v['conflitos'] if c['tipo'] == 'frequencia')} de frequência. "
          f"Bateria bloqueada: {'OK' if espectro_ok else 'FALHOU'}")
    if not espectro_ok:
        ok = False
    usadas = [p.frequencia for p in heats[0].pilotos if p.frequencia]
    livres = frequencias_livres(ESPECTRO, usadas)
    print(f"   frequências livres sugeridas: {livres[:5]}… ({len(livres)} canais)")
    if not livres:
        ok = False

    # ---------------------------------------------------------- 3. promoção
    print("\n3) PROMOÇÃO PARA FINAIS (pontos dos heats):")
    resultados_heats = {}
    for h in heats:
        resultados_heats[h.nome] = [(p.nome, float(23 - i)) for i, p in enumerate(h.pilotos)]
    finais_promo = promover_para_finais(resultados_heats, num_finais=2, tamanho_final=10)
    for f in finais_promo:
        print(f"   {f.nome}: {[p.nome for p in f.pilotos[:3]]}… ({len(f.pilotos)})")
    promo_ok = (len(finais_promo) == 2 and len(finais_promo[0].pilotos) == 10
                and finais_promo[0].pilotos[0].nome == "P00")
    print(f"   Final A líderada por P00 (mais pontos): {'OK' if promo_ok else 'FALHOU'}")
    if not promo_ok:
        ok = False

    # ---------------------------------------------------------- 4. pontuação
    print("\n4) RANKING GERAL (drop 1 pior etapa + bônus pole/melhor volta):")
    reg = Regulamento(drop_rounds=1, bonus_pole=1, bonus_melhor_volta=1,
                      numero_provas=4, pilotos_por_prova=10)
    base = {
        "Ana":   {"e1": 26, "e2": 25, "e3": 18, "e4": 10},   # drop 10 → 69
        "Bruno": {"e1": 19, "e2": 26, "e3": 25, "e4": 25},   # drop 19 → 76
        "Carla": {"e1": 25, "e2": 18, "e3": 26, "e4": 18},   # drop 18 → 69
        "Diego": {"e1": 10, "e2": 10, "e3": 10, "e4": 10},   # drop 10 → 30
        "Elisa": {"e1": 12, "e2": 8,  "e3": 6,  "e4": 4},    # drop 4  → 26
    }
    linhas = ranking_geral(base, reg)
    for l in linhas:
        print(f"   {l['posicao']}º {l['piloto']:<6} total={l['total']:>5.0f} "
              f"(válidos {l['validos']}, descartados {l['descartados']})")
    ranking_ok = ([l["piloto"] for l in linhas] == ["Bruno", "Ana", "Carla", "Diego", "Elisa"]
                  and linhas[0]["total"] == 76 and linhas[1]["total"] == 69)
    print(f"   Bruno campeão (76 pts), Ana 2ª (69): {'OK' if ranking_ok else 'FALHOU'}")
    if not ranking_ok:
        ok = False

    print("\nRESULTADO:", "OK" if ok else "FALHOU")
    print("FASE 5 (motor):", "VALIDADA" if ok else "COM FALHAS")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

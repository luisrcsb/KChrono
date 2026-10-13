"""KChrono — CLI (Fase 0: teste ao vivo do driver MyLaps P3).

Uso:
    python cli.py p3 --host 192.168.0.50 [--porta 5403] [--duracao 30]

Fica 100% read-only: conecta no decoder e imprime os eventos que ele envia.
Para ver PASSINGs, passe um transponder pelo loop durante a captura.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time

from drivers.base import Passing, Status
from drivers.mylaps_p3 import MyLapsP3
from nucleo import demo as demo_fase1
from nucleo.log import configurar_log

log = logging.getLogger("kchrono.cli")


def _fmt_num(valor, sufixo=""):
    return "?" if valor is None else f"{valor}{sufixo}"


def _on_passing(p: Passing, pacote, t0: float, contadores: dict):
    contadores["passing"] += 1
    print(f"[{time.monotonic() - t0:7.2f}s] PASSING  #{_fmt_num(p.passing_number)} "
          f"transponder={_fmt_num(p.transponder)} rtc={_fmt_num(p.rtc_time)} "
          f"força={_fmt_num(p.strength)} hits={_fmt_num(p.hits)} "
          f"decoder=0x{(p.decoder_id or 0):06X}")


def _on_status(s: Status, pacote, t0: float, contadores: dict):
    contadores["status"] += 1
    print(f"[{time.monotonic() - t0:7.2f}s] STATUS   temp={_fmt_num(s.temperatura, '°C')} "
          f"tensão={_fmt_num(s.tensao, 'V')} ruído={_fmt_num(s.ruido)} "
          f"gps={_fmt_num(s.gps)} decoder=0x{(s.decoder_id or 0):06X}")


def _on_desconhecido(pacote, t0: float, contadores: dict):
    contadores["outros"] += 1
    campos = {f"0x{k:02X}": v for k, v in pacote["campos"].items()}
    print(f"[{time.monotonic() - t0:7.2f}s] tor=0x{pacote['tor']:04X} campos={campos}")


async def comando_p3(args) -> int:
    decoder = MyLapsP3(args.host, args.porta)
    t0 = time.monotonic()
    contadores = {"passing": 0, "status": 0, "outros": 0}

    try:
        await decoder.connect()
    except (OSError, asyncio.TimeoutError) as e:
        print(f"Falha ao conectar em {args.host}:{args.porta}: {e}")
        return 2

    print(f"Escutando {args.host}:{args.porta} por {args.duracao:.0f}s "
          f"(Ctrl+C para parar antes)...")
    try:
        await asyncio.wait_for(
            decoder.read_loop(
                on_passing=lambda p, pac: _on_passing(p, pac, t0, contadores),
                on_status=lambda s, pac: _on_status(s, pac, t0, contadores),
                on_desconhecido=lambda pac: _on_desconhecido(pac, t0, contadores),
            ),
            timeout=args.duracao)
    except asyncio.TimeoutError:
        pass
    except KeyboardInterrupt:
        print("\ninterrompido pelo usuário")
    finally:
        await decoder.close()

    print(f"\nResumo em {args.duracao:.0f}s: {contadores['passing']} passings, "
          f"{contadores['status']} status, {contadores['outros']} outras mensagens")
    return 0


async def comando_replay(args) -> int:
    return demo_fase1.main()


def comando_campeonato_teste(args) -> int:
    from nucleo.campeonato_demo import main as demo_campo
    return demo_campo()


async def comando_easylap(args) -> int:
    from drivers.easylap import EasyLap
    driver = EasyLap(porta=args.porta)
    t0 = time.monotonic()
    cont = {"passing": 0, "outros": 0}

    def on_pass(p, pac):
        cont["passing"] += 1
        print(f"[{time.monotonic()-t0:6.2f}s] PASSING #{p.passing_number} "
              f"transponder={p.transponder} forca={p.strength} hits={p.hits}")

    def on_out(pac):
        cont["outros"] += 1
        print(f"[{time.monotonic()-t0:6.2f}s] {pac}")

    try:
        await driver.connect()
    except OSError as e:
        print(f"EASYLAP indisponivel: {e}")
        return 2
    print(f"Escutando EASYLAP em {driver.porta_usada} por {args.duracao:.0f}s "
          f"(passe um carro no loop)…")
    try:
        await asyncio.wait_for(driver.read_loop(on_passing=on_pass,
                                                on_desconhecido=on_out),
                               timeout=args.duracao)
    except asyncio.TimeoutError:
        pass
    finally:
        await driver.close()
    print(f"\nResumo: {cont['passing']} passings, {cont['outros']} outras mensagens")
    return 0


async def comando_lapwiz(args) -> int:
    from drivers.lapwiz import LapWiz
    driver = LapWiz(endereco=args.endereco)
    t0 = time.monotonic()
    n = [0]

    def on_out(pac):
        n[0] += 1
        print(f"[{time.monotonic()-t0:6.2f}s] #{n[0]} {pac}")

    try:
        await driver.connect()
    except OSError as e:
        print(f"LapWiz indisponivel: {e}")
        return 2
    print(f"LapWiz {driver.endereco} conectado — capturando notificacoes por "
          f"{args.duracao:.0f}s (passe carros no loop!)…")
    try:
        await asyncio.wait_for(driver.read_loop(on_desconhecido=on_out),
                               timeout=args.duracao)
    except asyncio.TimeoutError:
        pass
    finally:
        await driver.close()
    print(f"\nResumo: {n[0]} notificacoes capturadas (material p/ decodificar o protocolo)")
    return 0


def comando_servidor(args) -> int:
    """Sobe o servidor local com a interface web (bloqueante — fora do asyncio)."""
    import uvicorn
    uvicorn.run("servidor.api:app", host=args.host, port=args.porta, log_level="info")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="kchrono", description="KChrono CLI")
    sub = parser.add_subparsers(dest="comando", required=True)

    p3 = sub.add_parser("p3", help="teste ao vivo do driver MyLaps P3 (read-only)")
    p3.add_argument("--host", default="192.168.0.50", help="IP do decoder (default: 192.168.0.50)")
    p3.add_argument("--porta", type=int, default=5403, help="porta TCP (default: 5403)")
    p3.add_argument("--duracao", type=float, default=30.0, help="segundos de captura (default: 30)")
    p3.set_defaults(func=comando_p3)

    replay = sub.add_parser("replay", help="valida o motor com a captura real + simulação")
    replay.set_defaults(func=comando_replay)

    campo = sub.add_parser("campeonato-teste", help="valida o motor de campeonatos (Fase 5)")
    campo.set_defaults(func=comando_campeonato_teste)

    serv = sub.add_parser("servidor", help="sobe o servidor local (interface web)")
    serv.add_argument("--host", default="0.0.0.0", help="interface de rede (default: 0.0.0.0 = LAN)")
    serv.add_argument("--porta", type=int, default=8780, help="porta HTTP (default: 8780)")
    serv.set_defaults(func=comando_servidor)

    ez = sub.add_parser("easylap", help="teste ao vivo do driver EASYLAP-USB (serial)")
    ez.add_argument("--porta", default=None, help="porta COM (default: auto-detectar)")
    ez.add_argument("--duracao", type=float, default=30.0)
    ez.set_defaults(func=comando_easylap)

    lw = sub.add_parser("lapwiz", help="teste ao vivo do SKYRC LapWiz (BLE) — scan+notify")
    lw.add_argument("--endereco", default=None, help="endereço BLE (default: descobrir por nome)")
    lw.add_argument("--duracao", type=float, default=30.0)
    lw.set_defaults(func=comando_lapwiz)

    args = parser.parse_args(argv)
    configurar_log()
    if args.comando in ("servidor", "campeonato-teste"):
        return args.func(args)
    return asyncio.run(args.func(args))


if __name__ == "__main__":
    sys.exit(main())

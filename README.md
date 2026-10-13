# KChrono (nome provisório)

Software de cronometragem e telemetria PT-BR, substituto do ZRound, para Windows e Linux.
Integra com o hardware MyLaps/AMB já em uso na pista e sincroniza com o CTAD.

- **Arquitetura completa:** [`ARQUITETURA.md`](ARQUITETURA.md)
- **Protocolo MyLaps P3:** [`docs/PROTOCOLO-P3.md`](docs/PROTOCOLO-P3.md)

## Status

| Fase | Entrega | Situação |
|---|---|---|
| **0 — Fundação** | driver `MyLapsP3` + CLI de teste ao vivo | ✅ **Concluída** (11/10/2026 — 29 passings reais capturados do decoder 192.168.0.50) |
| **1 — Motor + banco** | modelos, SQLite, máquina de estados + replay de validação | ✅ **Concluída** (11/10/2026 — 28 voltas consolidadas da captura real; simulação 3 pilotos OK) |
| **1.5 — Núcleo hard** | relógio alta precisão · ring buffer · filtro ghost lap · log | ✅ **Concluída** (11/10/2026 — µs validado, drift, descarte seguro, ghost lap auditado) |
| **2 — Interface operador** | 5 telas reais + telão 4K + módulo de som/voz | ✅ **Implementada** (11/10/2026 — login Steam, dashboard loja, operador ZRound, telão, admin biblioteca) |
| **3 — Sync CTAD** | fila offline, payload no formato do site, auto-upload, dedup | ✅ **Implementada** (11/10/2026 — aguardando teste com conta real) |
| **4 — Telão real** | voz TTS, gráficos Chart.js, track view, estimativas | ✅ **Implementada** (11/10/2026 — Maria pt-BR ativa, gráficos offline) |
| **5 — Campeonatos** | grid builder, espectro RF, drop rounds, bônus, ranking | ✅ **Implementada** (11/10/2026 — motor validado + UI no Admin) |
| 6 — Drivers extras | EASYLAP-USB, SKYRC LapWiz (BLE), LapZ/GiroZ/RiCino | ⬜ |
| 7 — Empacotamento | instaladores Windows/Linux + autoupdate | ⬜ |
| 4 — Telão + mobile | telão 4K, semáforo, colunas selecionáveis | ⬜ |
| 5 — Campeonatos | grid builder, varredura RF, drop rounds, bônus | ⬜ |
| 6 — Drivers extras | LapZ, GiroZ, RiCino, Arduino/RC | ⬜ |
| 7 — Empacotamento | instaladores Windows/Linux + autoupdate | ⬜ |

## Como rodar o teste ao vivo (Fase 0)

Requer Python 3.11+ (nenhuma dependência externa). Com o decoder ligado na rede:

```bash
python cli.py p3 --host 192.168.0.50 --duracao 30
```

- Conecta no decoder (porta TCP 5403) e **apenas escuta** — read-only, sem enviar comandos.
- Imprime em tempo real: `PASSING` (transponder, RTC, força, hits) e `STATUS` (temp, tensão, ruído).
- Para gerar passagens, passe um transponder pelo loop durante a captura.
- Para salvar em arquivo: `python cli.py p3 ... > captura.txt 2>&1`
  (no PowerShell o exit code 1 é NormalCommandError do stderr do log — a captura roda até o fim).

## Estrutura

```
KChrono/
├── ARQUITETURA.md            # arquitetura e roadmap
├── docs/
│   └── PROTOCOLO-P3.md       # spec do protocolo + amostras reais
├── cli.py                    # CLI: p3 (teste ao vivo) e replay (validação do motor)
├── drivers/
│   ├── base.py               # interface comum + eventos Passing/Status
│   ├── mylaps_p3.py          # driver MyLaps P3 (TCP 5403)
│   └── __init__.py
├── nucleo/
│   ├── modelos.py            # entidades + máquina de estados
│   ├── banco.py              # SQLite + migrações
│   ├── motor_corrida.py      # consolida voltas e calcula classificação
│   └── demo.py               # validação: replay da captura real + simulação
└── tools/
    └── crc_probe.py          # sonda do CRC-16 (pendente identificar)
```

## Como validar o motor (Fase 1)

```bash
python cli.py replay
```

Roda duas verificações: (1) **replay da captura real** — os 29 passings capturados do
decoder em 11/10/2026 geram 28 voltas, tempo total, melhor volta e detectam o passing
perdido (#9163) — com prova de idempotência no banco; (2) **simulação com 3 pilotos**
valida classificação e gaps (por tempo e por voltas).

O driver é 100% read-only por design. Comandos que alteram estado do decoder
(ex.: limpar passings, acertar relógio) só serão implementados com ação explícita
do operador.

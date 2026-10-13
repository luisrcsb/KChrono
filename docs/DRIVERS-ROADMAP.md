# KChrono — Roadmap de Drivers (hardware)

> Como cada sistema de cronometragem será integrado. Atualizado em 11/10/2026.

> Como cada sistema de cronometragem será integrado. Atualizado em 12/10/2026.

## Situação

| Driver | Status | Observação |
|---|---|---|
| **MyLaps/AMB P3** | ✅ implementado e validado ao vivo | TCP 5403, protocolo binário decodificado (`docs/PROTOCOLO-P3.md`) |
| **EASYLAP-USB (EZL01)** | ✅ driver pronto (aguarda hardware p/ validar) | serial 38400 8N1, protocolo Robitronic — `drivers/easylap.py` |
| **SKYRC LapWiz (RT004)** | 🟡 driver de descoberta/captura pronto | BLE — `drivers/lapwiz.py`; protocolo a decodificar por RE ao vivo |

> **Seleção de driver:** Admin → 🔧 Hardware & Decoders (tipo p3 / easylap / lapwiz),
> ou testes de bancada pela CLI: `python cli.py easylap --porta COM3` e `python cli.py lapwiz`.

## 1. EASYLAP-USB (EZL01) — prioridade alta

**O que é:** "USB PC-Interface" (2026: USB-C ⇒ USB-A) + 4 módulos receptores IR para ponte;
transponders IR pessoais com ID único (12 × 12 × 6 mm, 1,2 g); compatível com Robitronic;
software oficial para Windows (RCM, ZRound, LiveTime).

**Boa notícia — o protocolo já tem referência pública:**
- O sistema é **compatível com Robitronic**, cujo protocolo serial está documentado
  (Flip Side Racing — `flipsideracing.org/projects/fslapcounter/wiki/RobitronicSerial`):
  - **38400 baud, 8N1**; init: `03 B9 01` ⇒ decoder responde `00` e começa a transmitir;
  - pacote de **carro detectado**: `[len][checksum][0x84][UID 2B LE][00 00][tempo ms 4B LE][hits][strength]`;
  - pacote de **timestamp** a cada ~1 s: `[len][checksum][0x83][tempo 4B LE][14 D0 01 02]`;
  - sem delimitador: o 1º byte é o **tamanho** do pacote.
- Referências abertas de código: **fs-lap-counter** (Flip Side Racing, open source) e
  **LiveTime Scoring** (nextleveltiming.com) — ambos suportam "Easy Lap USB/Serial Decoder"
  e "Robitronic USB/Serial Decoder".

**Estratégia de integração (quando a unidade estiver em mãos):**
1. Captura ao vivo do EasyLap-USB (serial virtual via USB) — mesmo método do P3;
2. Comparar com o protocolo Robitronic documentado (o EasyLap USB deve seguir o mesmo);
3. Confirmar no ZRound 1.28.9.18 (versão mais nova lista EasyLap explicitamente) via
   análise de strings;
4. Implementar `drivers/easylap.py` (pyserial, thread dedicada, ring buffer) + teste ao vivo
   no `cli.py` (subcomando `easylap`).

**Ressalva:** no Linux, o EasyLap USB (USB-serial) funciona via driver FTDI/CH340 padrão;
se o chip for proprietário, usar captura em Windows primeiro.

## 2. SKYRC LapWiz (RT004) — futura

**O que é:** timing unit IR + transponders (T01/T02/T03 Mini-Z/T04 bateria), **comunicação
Bluetooth** (USB-C é apenas para carga). Recursos: Practice/Race/Qualifying, Shadow Run,
cloud, rankings de clube.

**Implicação arquitetural:** não é porta serial — o driver falará **BLE** (Python: `bleak`
multi-plataforma). O protocolo do app SkyRC não é público; será necessária **engenharia
reversa ao vivo** (serviços/características GATT + notifications), como fizemos com o P3.

**Estratégia (quando houver a unidade):**
1. Scan BLE dos serviços GATT (gatttool/bleak);
2. Conectar passivamente e capturar notifications ao passar transponder;
3. Documentar em `docs/PROTOCOLO-LAPWIZ.md`;
4. Implementar `drivers/lapwiz.py` (bleak, assíncrono).

## 3. Como um driver novo entra (regra do projeto)

Todo driver implementa `drivers/base.py` (`connect` / `read_loop` / `close`) e traduz o
protocolo específico para o evento comum `Passing(transponder, rtc_time, passing_number,
strength, hits)`. Drivers seriais usam **worker thread + fila**; BLE e TCP usam **asyncio**.
Nada muda no motor de corrida (Fase 1) — é Plug & Play.

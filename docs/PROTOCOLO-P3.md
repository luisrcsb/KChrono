# Protocolo MyLaps/AMB P3 — especificação de trabalho

> Resultado da análise do `ZRound.exe` 1.28.8.21 integrada a **capturas ao vivo**
> do decoder real em `192.168.0.50:5403` (11/10/2026) + parser de referência open-source
> (`datagutten/amb-p3-parser`, baseado na engenharia reversa de vlad_vy).

## 1. Transporte

- O **decoder escuta** conexões TCP na porta **5403** (até **4 conexões** simultâneas).
- O KChrono (v1.0.7+) usa **2 conexões simultâneas** por redundância: se um canal
  cair, o outro segue recebendo e o canal morto é reaberto com backoff (passings
  vindos dos dois canais são deduplicados).
- Não há request/response obrigatório: ao conectar, o decoder **envia mensagens
  espontâneas** (status, sessão) e passa a transmitir **passings** em tempo real.
- Conexão testada com `Test-NetConnection 192.168.0.50 -Port 5403` → OK (PC da pista: 192.168.0.12).

## 2. Framing (binário)

```
┌────┬─────┬──────────┬────────┬────────┬─────┬─────────────────┬─────┐
│ 8E │ ver │  len LE16│ crc LE │ flags  │ tor │  campos TLV...  │ 8F  │
└────┴─────┴──────────┴────────┴────────┴─────┴─────────────────┴─────┘
```

- `8E` — start byte; `8F` — end byte.
- `ver` — versão (observado `02`).
- `len` — little-endian 16 bits, **tamanho total da mensagem** (validado: 0x1B=27 ✓, 0x1F=31 ✓).
- `crc` — checksum little-endian (a validar contra implementação — ver seção 6).
- `flags` — 16 bits (observado `00 00`).
- `tor` — little-endian 16 bits, **tipo de mensagem**.
- **Escaping**: byte `8D` seguido de `X` representa o valor `X - 0x20` (usado quando o
  payload conteria `8E`/`8F`).

### Tipos de mensagem (TOR)

| tor | nome |
|---|---|
| 0x01 | PASSING (passagem/volta) |
| 0x02 | STATUS |
| 0x45 | FIRST_CONTACT |
| 0xFFFF | ERROR |
| 0x03 | VERSION |
| 0x04 | RESEND |
| 0x05 | CLEAR_PASSING |
| 0x18 | WATCHDOG |
| 0x20 | PING |
| 0x2D | SIGNALS |
| 0x13 | SERVER_SETTINGS |
| 0x15 | SESSION |
| 0x28 | GENERAL_SETTINGS |
| 0x2F | LOOP_TRIGGER |
| 0x30 | GPS_INFO |
| 0x4A | TIMELINE |
| 0x24 | GET_TIME |
| 0x16 | NETWORK_SETTINGS |
| *0x1C* | observado ao vivo (sessão/clock) — **confirmar significado na Fase 0** |

## 3. Campos TLV

Após o header (offset `0x0A`): sequência de `field_id(u8) length(u8) valor(LE)`.
Valores little-endian, inteiros de 1, 2, 4 ou 8 bytes conforme `length`.

### PASSING (tor=0x01)

| id | campo | notas |
|---|---|---|
| 0x01 | PASSING_NUMBER | sequencial do decoder |
| 0x03 | TRANSPONDER | código do transponder |
| 0x04 | RTC_TIME | tempo do decoder (µs; `timestamp = valor / 1_000_000`) |
| 0x05 | STRENGTH | força do sinal |
| 0x06 | HITS | nº de acertos do sinal |
| 0x08 | FLAGS | |
| 0x10 | UTC_TIME | |
| 0x0F | DRIVER_ID | RC4 (com unlock MyLaps) |
| 0x30 | VOLTAGE | RC4 com unlock |
| 0x31 | TEMPERATURE | RC4 com unlock |

### STATUS (tor=0x02)

| id | campo | notas |
|---|---|---|
| 0x01 | NOISE | ruído |
| 0x06 | GPS | |
| 0x07 | TEMPERATURE | °C |
| 0x0A | SATINUSE | satélites em uso |
| 0x0B | LOOP_TRIGGERS | |
| 0x0C | INPUT_VOLTAGE | décimos de volt (`valor / 10`) |

### Comuns (qualquer TOR)

| id | campo |
|---|---|
| 0x81 | DECODER_ID |
| 0x83 | CONTROLLER_ID |
| 0x85 | REQUEST_ID |

## 4. Amostras reais capturadas (11/10/2026, 30 s de escuta passiva)

**Mensagem A — 27 bytes (tor=0x1C):**
```
8E 02 1B 00 09 C4 00 00 1C 00 01 08 97 49 7E 7C 3D BA BD 24 81 04 22 16 04 00 8F
```
- header: ver=02, len=27, crc=0xC409, flags=0, tor=0x001C
- campo 01 len 08 valor `97 49 7E 7C 3D BA BD 24` (8 bytes — id/clock do decoder, decodificar na Fase 0)
- campo 81 len 04 valor `22 16 04 00` → **DECODER_ID = 0x041622**

**Mensagem B — 31 bytes (tor=0x02, STATUS):**
```
8E 02 1F 00 CC B5 00 00 02 00 01 02 39 00 07 02 23 00 0C 01 79 06 01 00 81 04 22 16 04 00 8F
```
- header: ver=02, len=31, crc=0xB5CC, flags=0, tor=0x0002
- campo 01 len 02 `39 00` → NOISE = 57
- campo 07 len 02 `23 00` → TEMPERATURE = 35 °C
- campo 0C len 01 `79` → INPUT_VOLTAGE = 121 → **12,1 V**
- campo 06 len 01 `00` → GPS = 0
- campo 81 len 04 `22 16 04 00` → DECODER_ID = 0x041622

> Decoder com tensão de fonte saudável (12,1 V) e temperatura interna de 35 °C.

### 4.1 Passings reais capturados (11/10/2026, 5 min de escuta)

Transponder passado manualmente pelo loop ~29 vezes em 5 minutos:

```
transponder=7096340 (em todas as passagens)
#9156 rtc=1791996679230944 força=90  hits=87
#9157 rtc=1791996690879944 força=70  hits=3
#9158 rtc=1791996705204944 força=103 hits=552
#9159 rtc=1791996720241944 força=82  hits=69
...
#9185 rtc=1791996925038328 força=77  hits=13    (29 passings, #9156..#9185)
```

**Observações de campo ( importantes para o motor de corrida):**
- `passing_number` é **sequencial por decoder** → permite detectar lacunas
  (ex.: `#9163` não chegou nesta captura). O motor deve reconciliar por número, não por contagem.
- `hits` varia muito (3 a 552) → mede qualidade do sinal; **não usar como filtro rígido**
  de validade da passagem.
- `rtc_time` em **microssegundos desde epoch Unix** → diferença entre RTCs consecutivos
  dá o tempo de volta com precisão de µs.
- Força típica observada: 70–129.

## 5. Cliente de referência (Python)

```python
import socket, struct

HOST, PORT = "192.168.0.50", 5403

def frames(sock):
    buf = b""
    while True:
        if b"\x8e" in buf and b"\x8f" in buf.split(b"\x8e", 1)[1]:
            i = buf.index(b"\x8e")
            j = buf.index(b"\x8f", i + 1)
            yield buf[i:j + 1]
            buf = buf[j + 1:]
        chunk = sock.recv(4096)
        if not chunk:
            return
        buf += chunk

def parse(rec: bytes):
    assert rec[0] == 0x8E and rec[-1] == 0x8F
    ver, length, crc, flags, tor = struct.unpack("<BHHHH", rec[1:10])
    # unescape 8D xx -> (xx - 0x20)
    out, k = bytearray(), 0
    while k < len(rec):
        if rec[k] == 0x8D:
            out.append(rec[k + 1] - 0x20); k += 2
        else:
            out.append(rec[k]); k += 1
    rec = bytes(out)
    campos, pos = {}, 10
    fmts = {1: "<B", 2: "<H", 4: "<I", 8: "<Q"}
    while pos < len(rec) - 1:
        fid, ln = rec[pos], rec[pos + 1]
        valor = struct.unpack(fmts[ln], rec[pos + 2:pos + 2 + ln])[0] if ln in fmts else rec[pos + 2:pos + 2 + ln]
        campos[fid] = valor
        pos += 2 + ln
    return {"ver": ver, "tor": tor, "campos": campos}

with socket.create_connection((HOST, PORT), timeout=5) as s:
    for rec in frames(s):
        print(rec.hex(), parse(rec))
```

## 6. Pendências da Fase 0

1. **Validar o CRC** das mensagens (CRC-16 a identificar — ver `tools/crc_probe.py`; as 10
   variantes comuns não bateram contra as amostras). **Aberto.**
2. **Decodificar o campo de 8 bytes** da mensagem tor=0x1C (id/clock do decoder). **Aberto.**
3. ~~Catalogo completo de TOR~~ — **Fechado para o necessário:** PASSING (0x01) e STATUS (0x02)
   confirmados em captura ao vivo; demais tipos só serão implementados se aparecerem.
4. ~~Passagem real: capturar um PASSING (transponder no loop) para validar TRANSPONDER/RTC_TIME/HITS.~~
   — **Fechado:** 29 passings do transponder 7096340 capturados e decodificados (seção 4.1).
5. **Comandos ao decoder** (opcional, read-only primeiro): documentar comportamento antes de implementar. **Aberto.**
6. **Gaps de passings** (ex.: #9163 perdido): o motor de corrida (Fase 1) deve reconciliar
   voltas por `passing_number`, não por contagem de eventos.
7. ~~Integridade dos frames / robustez de leitura~~ — **Fechado (v1.0.7):** o driver valida o
   campo `tamanho` do header contra o comprimento real (quando sem byte-stuffing) e limita
   os campos TLV ao corpo do frame — frame corrompido é descartado e contabilizado
   (`stats`), com ressincronismo do buffer, canal redundante (2 conexões, dedup),
   timeout de silêncio (conexão zumbi) e reabertura automática de canal.

## 7. Referências

- ZRound 1.28.8.21 (análise de strings do binário) — "Activar sistema AMB (Protocolo P3)", `AMBP3 Host=192.168.0.50`.
- `datagutten/amb-p3-parser` (Python/PHP) — parser de referência.
- `ammconverter.eu` — "AMB connects to those decoders as client and waits for passing data... PASSING messages" (JSON equivalente).
- AMM Converter (Rust) — unifica passings de múltiplos decoders.

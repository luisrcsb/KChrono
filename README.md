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
| **2 — Interface operador** | menu persistente + painel completo + telão + som/voz + QR Gestão Remota | ✅ **Concluída** (menu/corpó, sessão por abertura, wallpaper) |
| **3 — Sync Firebase** | fila offline, payload, auto-upload, dedup — projeto `kchrono` | ✅ **Ligada e validada** (13/10/2026 — login superuser + escrita/leitura no banco novo; falta sessão real) |
| **4 — Telão real** | voz TTS, gráficos Chart.js, track view, estimativas | ✅ **Implementada** (14/10/2026 — locutor **neural offline** (Piper pt-BR) como padrão, SAPI como reserva) |
| **5 — Campeonatos** | grid builder, espectro RF, drop rounds, bônus, ranking | ✅ **Implementada** (11/10/2026 — motor validado + UI no Admin) |
| 6 — Drivers extras | EASYLAP-USB, SKYRC LapWiz (BLE), LapZ/GiroZ/RiCino | 🟡 **Parcial** (EASYLAP pronto s/ hardware · LapWiz só captura · demais roadmap) |
| 7 — Empacotamento | app nativo pywebview + instaladores Windows/Linux + autoupdate | ✅ **Funcional** (13/10/2026 — `KChrono.exe` testado: janela nativa, `/api/sync/status` 200, modo instalado usa `%APPDATA%\KChrono`; `KChrono-Setup.exe` ~64 MB compilado no NSIS com CTAD; falta teste de pista real) |

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
│   ├── PROTOCOLO-P3.md       # spec do protocolo + amostras reais
│   ├── ESPECIFICACAO-TECNICA.md
│   ├── DESIGN-FASE2.md
│   └── DRIVERS-ROADMAP.md
├── cli.py                    # CLI: p3, replay, servidor, easylap, lapwiz, campeonato-teste
├── caminhos.py               # resolve pastas (fonte vs empacotado)
├── atualizador.py            # verifica/baixa novas versões (versao.json)
├── config.json               # config local (Firebase, som, gerente) — não versionado
├── dados/                    # banco SQLite, logs, capturas — não versionado
├── drivers/                  # base.py + mylaps_p3.py, easylap.py, lapwiz.py
├── nucleo/                   # modelos, banco, motor_corrida, relogio, ring_buffer,
│                             # voz, log, campeonatos, demo
├── servidor/                 # api.py, estado.py, config.py, gerente.py, qr.py, som.py
├── sync/                     # ctad_client.py (Auth+RTDB) + sincronizador.py (fila offline)
├── interface/                # index.html, app.js, estilo.css, telao.*, gerente.*
├── imagens/                  # logos, fotos
├── empacotamento/            # PyInstaller, NSIS, systemd, versao.json
└── tools/                    # crc_probe.py
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

---

## 📦 Empacotamento — App Nativo (Fase 7)

O KChrono agora é um **app nativo de verdade** (não abre navegador):
- **Windows**: usa **WebView2** (Edge) via `pywebview` — janela sem barra de endereço, ícone na barra de tarefas, atalhos diretos para Operador / Telão / Gerente.
- **Linux**: usa **WebKitGTK** via `pywebview` — mesmo comportamento, integra com menu de aplicações.

### Build Windows (gera `KChrono.exe` + instalador NSIS)

```bash
cd empacotamento
build-windows.bat          # compila KChrono.exe com PyInstaller
# Depois, no NSIS (makensis instalador.nsi) gera KChrono-Setup.exe
```

**Requisitos**: Python 3.11+, WebView2 Runtime (já incluso no Windows 10/11 atualizado).

### Build Linux (instalação usuário)

```bash
bash empacotamento/instalar-linux.sh
```

Cria dois comandos:
- `kchrono` — servidor headless (para systemd/serviço)
- `kchrono-app` — **app nativo com janela** (WebKitGTK)

Requisitos de sistema: `libwebkit2gtk-4.1-0` (Ubuntu/Debian), `webkit2gtk4.1` (Fedora), `webkit2gtk-4.1` (Arch).

## 🔊 Locutor: voz neural offline (Piper)

A locução usa, nesta ordem:

1. **Piper (neural, offline)** — voz natural em pt-BR, roda no próprio
   computador, **sem internet** (ideal para pista). É o padrão quando há um
   modelo instalado.
2. **SAPI do Windows / OneCore** — `Maria` e `Daniel` (vozes mais "robotizadas").
3. **modo log/bipes** — se nada estiver disponível.

Os modelos ficam em `dados/vozes/*.onnx` (**fora do executável** — não o
incham e não se perdem ao atualizar). Instale pelo
**Admin → 🔊 Voz & Som → ⬇ Baixar voz neural** (≈60 MB, uma única vez) ou na mão:

```bash
pip install piper-tts          # já está no requirements.txt
curl -L -o dados/vozes/pt_BR-faber-medium.onnx \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx
curl -L -o dados/vozes/pt_BR-faber-medium.onnx.json \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx.json
```

A voz neural é adotada automaticamente na primeira execução (a escolha do
operador sempre vale depois). Velocidade e volume continuam nos controles do
Admin; a entonação vem do próprio modelo.

> O `edge-tts` (Azure, online) tem código pronto em `nucleo/voz.py` mas está
> **inativo**: a Microsoft passou a barrar o handshake (HTTP 403) e ele
> dependeria de internet na pista.

### Executar o app nativo (já empacotado)

```bash
# Windows
KChrono.exe                    # Operador (padrão)
KChrono.exe --telao --fullscreen   # Telão em tela cheia
KChrono.exe --gerente              # Gerente de Pista
KChrono.exe --sem-janela           # Headless (serviço)

# Linux
kchrono-app                    # Operador
kchrono-app --telao --fullscreen
kchrono-app --gerente
kchrono --sem-janela           # Headless
```

### Atualização automática

Configure `url_base` em `empacotamento/versao.json` apontando para onde você publica:
- `versao.json` (mesmo formato)
- `KChrono-Setup.exe` (Windows)
- `kchrono-linux.tar.gz` (Linux — opcional)

No painel Admin → **Salvamento/Uploads** aparece botão "Verificar atualização" e "Baixar".

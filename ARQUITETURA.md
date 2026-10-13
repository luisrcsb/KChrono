# KChrono — Arquitetura (nome provisório)

> Software de cronometragem e telemetria PT-BR, substituto do ZRound, para Windows e Linux.
> Ecossistema: alimenta/espelha o CTAD (krathus-telemetria) e integra com o hardware MyLaps já em uso.
>
> **Status:** rascunho v0.1 — criado a partir da análise do ZRound 1.28.8.21 instalado,
> da engenharia reversa do protocolo Live/Results e de capturas ao vivo do decoder AMB P3 (192.168.0.50).
> Data: 11/10/2026

---

## 1. Objetivos e princípios

1. **Substituir o ZRound** no PC da pista: treino, classificação, corrida ao vivo, telão, campeonatos.
2. **PT-BR primeiro**, com i18n desde o dia 1 (gettext `.po`, como o ZRound faz).
3. **Interface web local**: operador, telão e celulares acessam via navegador na LAN.
4. **One-click install** em Windows e Linux, com atualização automática.
5. **Integração total com o CTAD**: mesma conta, sincronização de sessões/voltas/campeonatos.
6. **Hardware real, já validado**: MyLaps AMB P3 via TCP (protocolo decodificado — ver `docs/PROTOCOLO-P3.md`).

Princípios de arquitetura: núcleo independente de UI, drivers de hardware plugáveis,
banco local-first (funciona sem internet), sincronização eventual e tolerante a falhas.

---

## 2. Recomendação de stack (justificada)

**Recomendação: Python 3.11+ com núcleo asyncio + servidor web local (FastAPI/uvicorn) + frontend web vanilla.**

Justificativa ancorada no que você já tem e usa hoje:

| Critério | Por que Python |
|---|---|
| Reuso do seu ecossistema | O CTAD-Upload-Auto já é Python (`ctad_client.py`, `ctad_upload.py`, `parsers.py`) com login Firebase REST, refresh de token, regras de nível, dedup por hash — tudo isso é aproveitado quase sem alteração no novo software. |
| Empacotamento já dominado | PyInstaller + instalador + autoupdate (`app-local/dist/CTAD-Upload-Auto.exe`, `.nsi`, `versao.json`) são um pipeline testado; reaproveitar reduz semanas de trabalho. |
| Protocolo P3 |socket TCP binário, parsing com `struct`, escaping e checksum — Python é ideal. Já existe parser de referência em Python (validado contra seu decoder). |
| Multiplataforma | Windows e Linux com o mesmo código; no Linux roda como serviço (systemd) com venv simples. |
| Banco embutido | SQLite: zero configuração, transações ACID para as voltas, portável para Linux. |
| Tempo real | asyncio: um event loop atende sockets dos decodificadores + servidor WebSocket da interface + fila de sync. |

**Alternativas avaliadas e descartadas:**
- **Node.js**: reescreveria toda a integração Firebase/empacotamento; vantagem só no frontend.
- **Electron/Tauri**: runtime pesado e build complexo para um app que roda em PC de pista; frontend fica preso ao runtime.
- **C#/.NET**: bom em Windows, mas Linux fica em segundo plano; perderia o reuso Python do CTAD.

**Componentes:**
- **Servidor local**: FastAPI + uvicorn, REST para o painel e **WebSocket/SSE** para tempo real (voltas, gaps, countdown).
- **Frontend**: HTML/CSS/JS modular vanilla + Chart.js e Canvas — mesmo estilo do CTAD (sem build step, carrega direto do servidor local).
- **Banco local**: SQLite (`dados/kchrono.db`) com migrações versionadas.
- **Sync**: módulo `sync/` reaproveitando o `CtadClient` (Firebase Auth + RTDB), com fila offline e idempotência.

---

## 3. Arquitetura de módulos

```
kchrono/
├── nucleo/                 # sem dependência de UI ou rede externa
│   ├── loop.py             # event loop asyncio, orquestrador
│   ├── modelos.py          # Pista, Piloto, Transponder, Sessao, Volta...
│   ├── banco.py            # SQLite + migrações
│   └── motor_corrida.py    # máquina de estados + regras (treino/classif/ corrida)
├── drivers/                # um módulo por sistema de cronometragem (interface comum)
│   ├── base.py             # interface Decoder: connect/read/close → eventos Passing
│   ├── mylaps_p3.py        # TCP 5403, protocolo P3 (implementado e validado)
│   ├── mylaps_ambrc.py     # serial (fase futura)
│   └── ...
├── servidor/               # interface web local (operação + telão)
│   ├── api.py              # REST: pilotos, sessões, config, campeonatos
│   └── tempo_real.py       # WebSocket/SSE: passing, classificação, countdown
├── interface/              # frontend web servido pelo servidor local
│   ├── operador.html       # painel de controle da sessão
│   ├── telao.html          # telão 4K / transmissão
│   └── mobile.html         # versão leve para celular na LAN
├── sync/                   # integração com o ecossistema CTAD
│   ├── ctad_client.py      # (reaproveitado do app-local) login Firebase + RTDB
│   └── sincronizador.py    # fila offline, dedup, espelho campeonatos/pilotos/pistas
├── i18n/                   # gettext pt_BR + esqueleto en_US
├── cli.py                  # execução headless (serviço/systemd) e comandos
└── empacotamento/          # PyInstaller, instaladores, autoupdate
```

**Fluxo de dados (corrida típica):**
```
decoder MyLaps P3 ──TCP──► drivers/mylaps_p3.py ──Passing──► motor_corrida.py ──► SQLite (voltas)
                                        │                          │
                                        │                          ├──WebSocket──► interface (telão/operador)
                                        │                          └──fila──► sync/ ──Firebase──► CTAD
                                        └── heartbeat/status (temp, tensão, ruído, GPS)
```

---

## 4. Comunicação com hardware (MyLaps e derivados)

- **P3 (em uso hoje)**: TCP, decoder escuta na **porta 5403**, até 4 conexões; framing
  `8E ver len crc flags tor ... 8F`, campos TLV, escaping `8D`. Especificação completa
  e amostras reais em `docs/PROTOCOLO-P3.md`.
- **Roadmap de drivers** (mesma interface `base.py`): AMBrc serial, RC4/RC (Freespace),
  TranX, ProChip, e outros que o ZRound suporta — cada driver novo é um arquivo,
  sem tocar no núcleo.
- **Regra de ouro do driver**: começar 100% read-only (só escutar passings/status);
  comandos que alteram estado do decoder (clear passings, set clock, sensibilidade)
  só com ação explícita do operador.

---

## 5. Motor de corrida (regras)

Máquina de estados: `PARADO → AQUECIMENTO/TREINO → CLASSIFICAÇÃO → LARGADA → CORRENDO → FINALIZADO`.

**Fonte das regras:** pontuação, nº de voltas, duração, categorias, formato de campeonato e grid
**vêm do CTAD** (fonte única). O KChrono não mantém regras próprias: sincroniza os cadastros
ao abrir o campeonato e opera offline com o cache local. Qualquer mudança de regulamento
é feita no site e chega ao app na próxima sincronização.

Funcionalidades mínimas para substituir o ZRound:
- Modos: treino livre, treino cronometrado, classificação, corrida por tempo ou por voltas;
- Saídas: largada lançada, grid, Le Mans (controle de voltas e saída);
- Cálculos ao vivo: voltas, melhor volta, últimas voltas, gap/diff, pace, consistência, desvio padrão;
- Múltiplas categorias/classes por sessão, separação por transponder ou por piloto;
- Gestão de transponder ↔ piloto (cadastro, troca durante campeonatos — recurso que o ZRound tem);
- Campeonatos: etapas, baterias/chaves, pontuação e grid **definidos no CTAD** (fonte única); o app consome e cacheia localmente para operar offline.

---

## 6. Modelo de dados (SQLite local-first)

Entidades principais (espelhando o que o CTAD já consome):

- **pista** — id, nome, traçado/metadados
- **categoria** — id, nome, regras (pontuação, voltas)
- **piloto** — id, nome, apelido, nacionalidade etc.
- **transponder** — id, código, piloto_id, vigência (troca ao longo do campeonato)
- **sessao** — id, tipo (treino/classif/corrida), pista, data, status, parâmetros
- **passing** — id, sessao_id, transponder, rtc_time, força, hits, nº passing (cru do decoder)
- **volta** — id, sessao_id, piloto_id, nº volta, tempo, melhor?, setores (futuro)
- **campeonato / etapa / inscricao / pontuacao**

Todas com `criado_em`/`atualizado_em` e **UUIDs locais** — a chave local é a fonte da verdade;
o sync mapeia para o banco do CTAD.

---

## 7. Integração com o ecossistema web (CTAD)

- **Autenticação**: mesma conta do CTAD (Firebase Auth REST via `ctad_client.py`);
  conta com nível admin/gestor opera upload; operador de pista usa conta dedicada.
- **Sincronização de sessões**: ao final de cada sessão (ou em lote), envia voltas consolidadas
  para `baterias/{key}` + resumo público, no mesmo formato que o upload manual/automático gera —
  o dashboard de telemetria do CTAD passa a funcionar direto, sem exportar PDF.
- **Espelho no app**: cadastros de campeonatos, pilotos, categorias e pistas podem ser
  puxados/push do site (fonte única = site, app cacheia local e opera offline).
- **Conflitos**: local-first; merge por `atualizado_em` (last-write-wins) por campo.

---

## 8. Interface (web local)

- **Painel do operador**: controle da sessão (iniciar/parar/pausa), classificação ao vivo,
  correção manual de passagens, gestão de transponders, log do decoder.
- **Telão 4K/transmissão**: classificação estilo TV, melhor volta, countdown, logo da pista
  (canvas fullscreen, mesma linguagem visual do Telão do CTAD).
- **Mobile**: página leve (HTML único) consultando a API local — fiscais de prova no celular.
- Acesso por `http://<ip-do-pc>:<porta>` na LAN; **segurança**: bind configurável
  (127.0.0.1 por padrão para operação solo), token de acesso simples para telão/mobile.

---

## 9. Multi-OS e instalação one-click

- **Windows**: PyInstaller (one-dir) + instalador (Inno Setup/NSIS — pipeline já existe no app-local),
  cria pastas de dados em `%APPDATA%\KChrono`, atalhos, inicia com o Windows (opcional).
- **Linux**: pacote com venv próprio + serviço systemd; alternativa AppImage/.deb.
  Propriedade do decoder: sem dependência de driver serial nativo no caso P3 (TCP puro).
- **Atualização automática**: mesmo esquema do CTAD (`downloads/versao.json` + assinatura/versão).

---

## 10. Roadmap por fases

> Detalhamento de baixo nível (relógio de alta precisão, filtros de ruído, grid builder,
> varredura RF, pontuação): [`docs/ESPECIFICACAO-TECNICA.md`](docs/ESPECIFICACAO-TECNICA.md).

| Fase | Entrega | Situação |
|---|---|---|
| **0. Fundação** | driver `MyLapsP3` + CLI ao vivo | ✅ concluída (29 passings reais) |
| **1. Motor + banco** | modelos, SQLite, máquina de estados, replay | ✅ concluída (validado com captura real) |
| **1.5. Núcleo hard** | relógio QPC/monotonic · ring buffer · filtro tempo mínimo/ghost lap · drift · log com severidades | ⬜ próxima |
| **2. Interface operador** | servidor local + telas (design aprovado) + TTS + console com ação contextual | ⬜ |
| **3. Sync CTAD** | envio de sessões/voltas, espelho de cadastros, upload refinado | ⬜ |
| **4. Telão + mobile** | telão 4K, semáforo, colunas selecionáveis, perfis de exibição | ⬜ |
| **5. Campeonatos** | grid builder piramidal, varredura RF, drop rounds, bônus pole/melhor volta | ⬜ |
| **6. Outros decodificadores** | drivers LapZ, GiroZ, RiCino, Arduino/RC | ⬜ |
| **7. Empacotamento** | instaladores Windows/Linux + autoupdate | ⬜ |

---

## 11. Riscos e decisões em aberto

1. **Nome definitivo do produto** (KChrono é provisório).
2. **Múltiplos decodificadores simultâneos** (pistas grandes com 2+ P3) — a interface `base.py` já permite; confirmar necessidade.
3. **Comandos ativos ao decoder** (set clock/clear passings): implementar só com confirmação do operador.
4. **Gravação de voltas de treino**: definir retenção local (o ZRound grava todas; volume cresce).
5. **Pontuação de campeonatos**: ~~regras customizadas por campeonato~~ **Resolvido:** definida no CTAD; o app apenas consome.
6. **VT/Idiomas além de pt-BR**: esqueleto gettext pronto; traduções depois.

## 12. Decisões já tomadas (desta análise)

- Substituir o ZRound por completo (não apenas coletar).
- Interface web local como UI principal; núcleo headless capaz de rodar como serviço.
- Stack Python/asyncio + FastAPI + SQLite + frontend vanilla (justificativa na seção 2).
- Hardware atual: MyLaps P3 via TCP/5403, protocolo decodificado e validado in-loco.
- Local-first + sync eventual com o CTAD via Firebase (reuso do cliente existente).
- **Regras de corrida e campeonatos: fonte única no CTAD** — o app consome e cacheia (offline-first no cadastro, regulamento sempre do site).
- i18n com gettext desde o início; pt-BR como idioma padrão.

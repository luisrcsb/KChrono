# KChrono — Especificação Técnica (baixo nível)

> Consolida a especificação técnica detalhada (11/10/2026). **Aditiva**: não substitui o
> `ARQUITETURA.md`, o `docs/DESIGN-FASE2.md`, o `docs/PROTOCOLO-P3.md` nem o motor da
> Fase 1 — aprofunda o backend, os filtros de ruído, o frontend do operador e o motor de
> campeonatos. Requisitos do regulamento continuam vindo do CTAD (fonte única).

## 1. Visão geral da arquitetura e fluxo de dados

```
DECODIFICADORES / PONTES (MyLaps P3 · LapZ · GiroZ · RiCino · Arduino ...)
        |  TCP/IP ·  COM/RS-232 (USB)  |   leitura assíncrona
        v
BACKEND MASTER (core engine)
  · ingestão de raw packets com ring buffer (descarte seguro de corrompidos)
  · relógio de alta precisão (QPC no Windows / CLOCK_MONOTONIC no Linux)
  · filtros: tempo mínimo de volta · ghost lap interceptor · LapZ bridge reset
        |                                |
        | (eventos de passagem)          | (estado/classificação)
        v                                v
FRONTEND OPERACIONAL        <---->   MOTOR DE CAMPEONATOS
  · monitor principal                · etapas/heats/grids
  · scoreboards independentes        · varredura RF/transponders
  · console de log (50k linhas)      · pontuação/drop rounds
  · locução TTS                      · ranking consolidado
```

## 2. Backend e baixo nível

### 2.1 Ingestão de hardware e portas seriais

- **Worker threads dedicadas** para portas COM virtuais (RS-232 over USB) — `pyserial` é
  bloqueante, fora do event loop; sockets TCP/IP (MyLaps P3) seguem em asyncio.
- **Raw packet**: `[STX][Transponder_ID][Timestamp_μs][ETX]` — drivers traduzem para o
  evento comum `Passing` (`drivers/base.py`).
- **Saturação na largada**: **ring buffer circular** com descarte seguro de pacotes
  corrompidos, anomalia registrada no log **sem travar a thread de UI**.

**Decisões de implementação:**
- Driver P3: reconexão automática com backoff; buffer de reordenação por `passing_number`.
- Drivers seriais: thread + fila thread-safe para o core; framing por STX/ETX com escaping.

### 2.2 Motor de relógio e alta precisão

- **Windows**: `QueryPerformanceCounter` (mandatório); **Linux**: `clock_gettime(CLOCK_MONOTONIC)`.
- Delta entre passagens em **microssegundos**; tolerância a relógios de 1.193 h (64 bits).
- **Política de fonte do tempo por driver**:
  - *P3 (MyLaps)*: o `RTC_TIME` do decoder (µs, epoch) é o **timestamp oficial** da passagem.
  - *Drivers sem timestamp* (LapZ/GiroZ/RiCino/Arduino): relógio local de alta precisão.
  - O core monitora **drift** (RTC do decoder vs. relógio local) e alerta na interface.

### 2.3 Filtragem e mitigação de ruído

**Tempo mínimo de volta (Min Lap Time Enforcement)** — pseudocódigo do requisito, adotado:

```text
Function ProcessPassage(transponderId, packetTimestamp):
    lastPassageTime = ActiveSession.GetLastPassage(transponderId)
    delta = packetTimestamp - lastPassageTime
    if delta < GlobalConfig.MinLapTime:
        SystemLog.AppendWarning("Ghost lap detected for ID: " + transponderId)
        return DROP_PACKET
    else:
        ActiveSession.RecordValidLap(transponderId, packetTimestamp)
        TriggerFrontendUpdate()
```

**Decisões de implementação:**
- `tempo_minimo_volta` **configurável por sessão** (default por pista) — espelha o
  `MinimoVuelta` do ini.ini do ZRound.
- Passing rejeitado **não é volta**, mas fica **gravado com flag `invalido`** no banco
  (auditoria) + log amarelo; a numeração sequencial do decoder permite reconciliar depois.

**LapZ Bridge Reset (watchdog):**
- Watchdog interno dispara pulso/comando de reset controlado na ponte **a cada N baterias**
  (N configurável), com **janela de tolerância estrita de 2 s** para sincronização do buffer
  de hardware; falha na sincronização → log vermelho + sessão marcada para revisão.

## 3. Frontend do operador

### 3.1 Componentes

- **Views desacopladas**: monitor principal e **scoreboards secundários em instâncias de
  renderização independentes** (no app web local: páginas/abas separadas, cada uma com sua
  própria conexão WebSocket — nenhum cálculo pesado bloqueia outra tela).
- **Console de log dinâmico** (buffer de rolagem otimizado, até **50.000 linhas** sem vazamento):
  - branco/cinza — tráfego normal de passagens;
  - **amarelo** — ghost laps, violação de tempo mínimo, avisos de hardware;
  - **vermelho** — erros críticos de hardware e **transponder não cadastrado**.
- **Ação contextual (1-click)**: clique direito no log vermelho de transponder não cadastrado
  abre modal assíncrona com o **ID já injetado** no mapeamento piloto ↔ transponder da sessão
  (auto-vínculo, como "Detectar transponder" do ZRound).

### 3.2 Locução (TTS)

- API nativa do S.O. (SAPI5 no Windows / espeak-ng no Linux) via camada `nucleo/voz.py`.
- **Supressão inicial**: parâmetro `start_reading_on_lap` — ignora os primeiros giros da
  largada (funil compactado) para não sobrecarregar o canal de áudio com parciais sobrepostos.
- Eventos falados e ajustes (locutor/volume/velocidade) conforme `docs/DESIGN-FASE2.md` §4.

## 4. Subsistema de campeonatos e regras

### 4.1 Esquema relacional (extensão do modelo da Fase 1)

```
Pilotos(ID_Piloto, Nome, Club, Transponder_ID, Frequencia_Radio)
Campeonatos(ID_Camp, Nome_Camp, Regulamento_ID)
Etapas(ID_Etapa, ID_Camp, Numero_Etapa, Data, Status_Execucao)
Baterias_Heats(ID_Heat, ID_Etapa, Fase[Qualify/Final], Bloco_Letra[A/B/C], Ordem_Grid)
Resultados_Parciais(ID_Res, ID_Heat, ID_Piloto, Voltas_Totais, Melhor_Tempo, Pontos_Conquistados)
```

O SQLite local (Fase 1) ganha estas tabelas por migração; **os dados de regulamento
(pontuação, nº de etapas válidas, formato de heats) vêm do CTAD** e o app cacheia.

### 4.2 Grid Builder (heats e finais)

- Entrada: inscritos ordenados por ranking da etapa anterior / histórico geral.
- **Particionamento**: divide o total de pilotos `P` pelo tamanho máximo de pista `M` →
  nº de heats; **distribuição piramidal automática** para as finais (Final C → B → A).

### 4.3 Validação preventiva de espectro (Cross-Check RF)

- **Invariância** na consolidação de qualquer heat/final: para todo par de pilotos no mesmo
  heat, `transponder_i ≠ transponder_j` **e** `frequencia_i ≠ frequencia_j`.
- Colisão detectada → **bloqueia a abertura da bateria** e renderiza **matriz de conflito**
  no painel administrativo, sugerindo frequências livres do espectro cadastrado.

### 4.4 Motor de pontuação (AECAR & custom)

- **Drop Rounds Engine**: regras tipo "descartar a pior etapa de cada 4 realizadas".
- **Bonificações automáticas**: pontos base por posição + bônus dinâmicos de **pole position**
  e **melhor volta absoluta da etapa**; ranking geral consolidado sem planilhas externas.

## 5. Impacto no roadmap

| Fase | Conteúdo (atualizado) |
|---|---|
| 0 ✅ | driver MyLaps P3 (validado ao vivo) |
| 1 ✅ | motor de voltas + SQLite + replay de validação |
| **1.5 (novo)** | relógio de alta precisão (QPC/monotonic) · ring buffer · filtro de tempo mínimo/ghost lap · drift · log com severidades | ✅ concluída (11/10/2026) |
| 2 | interface operador (design aprovado) + TTS + console de log com ação contextual |
| 3 | sincronização com o CTAD (motor atual + upload refinado) |
| 4 | telão 4K + semáforo + colunas selecionáveis (design na Fase 2) |
| 5 | **campeonatos completos**: grid builder, varredura RF, drop rounds, bônus |
| 6 | **drivers adicionais**: LapZ, GiroZ, RiCino, Arduino/RC |
| 7 | empacotamento: instaladores Windows/Linux + autoupdate |

## 6. Decisões em aberto (para alinhar)

1. **Fonte oficial do tempo** quando o driver tem timestamp (P3): usar sempre o RTC do
   decoder (proposta) ou o relógio local? — proposta: RTC do decoder, com drift monitorado.
   → **DECIDIDO (11/10/2026): RTC do decoder é o timestamp oficial; relógio local apenas
   para drivers sem timestamp; drift monitorado pelo core.**
2. **Ordem de construção**: endurecer o núcleo (Fase 1.5) antes da interface (Fase 2)?
   Recomendação: sim — é rápido e testável sem depender de design.
3. **Quais drivers de hardware além do P3** você usa/pretende (LapZ, GiroZ, RiCino,
   Arduino)? O ini.ini do ZRound mostra todos desativados — só o AMB P3 ativo hoje.
4. **Campeonatos completos** (grid builder/RF/pontuação) entram na Fase 5, após telão e sync?

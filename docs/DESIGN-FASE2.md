# KChrono — Design & Interface (Fase 2)

> Consolida as requisições de design definidas em 11/10/2026.
> Mockup navegável para aprovação: `interface/mockup/kchrono-mockup.html` (abrir no navegador).
> Detalhamentos adicionais (com fotos) serão incorporados na **Fase 5**.

## 1. Direção de arte

- **Referência: Steam** (base/referência, não cópia): tela de login centralizada, banner de
  destaque no topo, menu lateral escuro, cards, navegação por seções claras.
- **Cores: paleta do site CTAD** (identidade única):

| Uso | Cor |
|---|---|
| Fundo | `#0d111a` |
| Cards / cabeçalhos | `#151c28` / `#1c2638` |
| Texto | `#ffffff` / `#d0d7e3` / `#8492a6` |
| Acento principal | azul `#3a86ff` |
| Destaques | gold `#ffb703`, vermelho `#e63946`, verde `#2ec4b6`, gap `#ff006e` |

- **Tema alto contastro** (opção de acessibilidade, espelhando o CTAD): fundo preto,
  texto branco/amarelo, bordas brancas.
- Idioma: **PT-BR**.

## 2. Telas e perfis de acesso

Níveis (espelham o CTAD — `superuser` / `admin` / `gestor`):

| Recurso | Operador local | Gestor de pista | Admin | Superuser |
|---|:---:|:---:|:---:|:---:|
| Operar sessão (iniciar/pausar/parar) | ✅ | ✅ | ✅ | ✅ |
| Telão / segunda tela | ✅ | ✅ | ✅ | ✅ |
| Controle remoto (iniciar/pausar/parar/**reiniciar**) | — | ✅ | ✅ | ✅ |
| **Apagar volta** | — | — | ✅ | ✅ |
| **Marcar/desmarcar "gato"** (volta suspeita) | — | ✅ | ✅ | ✅ |
| Config de salvamento/upload/voz/telão | — | — | — | ✅ |
| Gerenciar contas | — | — | — | ✅ |

Telas: **Login** (credenciais do CTAD) → **Dashboard** → **Painel do Operador** →
**Telão 4K** → **Admin/Config**. Layout responsivo: PC, tablet e celular na LAN.

## 3. Telão / Segunda tela

- **Abertura**: detecta segunda tela (janela dedicada em fullscreen), tablet ou celular
  pelo navegador na LAN.
- **Contagem regressiva com semáforo** (estilo largada real): luzes sequenciais
  (5 luzes apagando, como na F1 / ou 3 luzes estilo largada de corrida) — tempos
  **ajustáveis** (ex.: 0,5s/1s entre luzes) ou **aleatórios** (largada surpresa).
- **Feedback durante a corrida — colunas selecionáveis** pelo operador, em tempo real:
  Posição · Número · Cor · Abreviado · Piloto · Fotografia · Bandeira · Voltas ·
  Diferença para o seguinte · Diferença para o primeiro · Tempo total · Tempo da última
  volta · Tempo da melhor volta · Tempo médio · Estimativa de voltas · Estimativa de
  tempo · Desvio Padrão · Consistência.
- **Troca de informações**: perfis de exibição (ex.: "TV — Classificação",
  "TV — Gap", "Prática — Treino livre") com transição animada e **rotação automática
  opcional** (intervalo configurável).

## 4. Voz (TTS)

- Backend plugável (`nucleo/voz.py`): **Windows = SAPI5** (mesmo locutor PT-BR do ZRound,
  ex.: "Microsoft Maria Desktop - Portuguese(Brazil)"), **Linux = espeak-ng**.
- Eventos falados (cada um liga/desliga): contagem regressiva ("3, 2, 1, VAI!"),
  largada, melhor volta da sessão, recorde pessoal, mudança de líder, alerta de fim
  ("faltam X segundos"), fim de corrida/treino.
- Ajustes: locutor, volume, velocidade — inspirados no `[SAPI51]` do ZRound.

## 5. Salvamento e upload (controle apurado)

- **Formato de nome configurável** com variáveis e preview ao vivo:
  `{campeonato}_{etapa}_{tipo}_{data}_{hora}`, `{pista}-{sessao}-{AAAA-MM-DD}`, etc.
- **Política de salvamento** por sessão:
  - `automático (completo)`: salva sozinho **quando a corrida corre do início ao fim sem
    interrupções** (sem pausa, reinício ou edições);
  - `perguntar`: ao fim — ou **ao ser interrompida** — pede confirmação e **sugere o nome**
    no formato pré-estabelecido;
  - `manual`: somente sob comando.
- **Detecção de interrupção**: pausa, reinício, volta apagada ou marcada como suspeita
  marcam a sessão como "interrompida" → comportamento de perguntar prevalece sobre o
  automático. Todas as ações ficam em **trilha de auditoria** da sessão (ação, usuário, hora).
- **Upload**: fila local com dedup por hash; envio ao CTAD no momento do salvamento;
  controle de reenvio e log por upload (ajustes finos detalhados na Fase 5).

## 6. Controle remoto (administrativo)

- Ações: **iniciar, pausar, parar, reiniciar** corrida · **apagar volta** ·
  **marcar/desmarcar volta como suspeita ("gato")** — disponíveis pelo painel web
  (LAN) e, quando logado via web, conforme o nível da conta.
- Toda ação administrativa grava evento na sessão (auditoria) e aparece no log do operador.

## 7. Roteiro de aprovação

1. **Agora**: avaliar o mockup (`interface/mockup/kchrono-mockup.html`) — login estilo
   Steam, dashboard, painel do operador, telão com semáforo, tela admin.
2. Ajustar conforme seu retorno (cores, layout, o que exibir em cada tela).
3. **Implementar a Fase 2** (servidor local + telas reais) só depois do design aprovado.
4. **Fase 5**: refinamentos com fotos/texto (telão, upload, vinheta de "gato" etc.).

## 8. Em aberto para a Fase 5

- Fonte das fotos de pilotos no telão (cadastro do CTAD?).
- Cor/abreviado definidos por piloto no cadastro ou avulsos no telão?
- Rotação automática dos perfis de exibição: intervalo e transição.
- Vinheta visual de volta "gato" no telão (ícone/cor).
- Detalhes finos da fila de upload e reprocessamento.

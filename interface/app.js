/* KChrono — frontend (Fase 2): consome a API local e o WebSocket de tempo real. */
"use strict";

let ws = null;
let usuario = { nome: "", nivel: "superuser" };

// ---------------------------------------------------------------- áudio (beep/fala)
let audioCtx = null;
function initAudio() {
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === "suspended") audioCtx.resume();
  } catch (e) {}
}
function beep(freq = 880, dur = 0.08, vol = 0.18) {
  initAudio();
  if (!audioCtx) return;
  try {
    const o = audioCtx.createOscillator(), g = audioCtx.createGain();
    o.frequency.value = freq; o.type = "square"; g.gain.value = vol;
    o.connect(g); g.connect(audioCtx.destination);
    o.start();
    setTimeout(() => { try { o.stop(); } catch (e) {} }, dur * 1000);
  } catch (e) {}
}
function beepPassing() { beep(1200, 0.06, 0.15); }   // bip curto ao passar
function beepVolta() { beep(880, 0.12, 0.22); }       // bip volta completada
function beepRecorde() { beep(1500, 0.2, 0.25); }      // bip recorde

// ---------------------------------------------------------------- navegação
// Shell persistente: o menu lateral está sempre visível; aqui só alterna o
// conteúdo (painel completo do operador, telão ou seções do admin).
// Início padrão: Painel do Operador (1ª opção do menu lateral).
let adminSecaoAtual = "a-gerente";

function marcarNav(btn) {
  const nav = Array.from(document.querySelectorAll(".menu nav a"));
  nav.forEach(a => a.classList.remove("on"));
  if (!btn) return;
  if (typeof btn === "string")
    btn = nav.find(a => (a.getAttribute("onclick") || "").includes(btn));
  if (btn) btn.classList.add("on");
}

function mostrar(id) {
  const op = document.getElementById("operador");
  const adm = document.getElementById("admin-conteudo");
  if (op) op.classList.toggle("visivel", id === "operador");
  if (adm) adm.style.display = id === "admin" ? "" : "none";
  const br = document.getElementById("busca-resultados"); if (br) br.classList.remove("on");
  // QR de Gestão Remota: exclusivo do Painel do Operador
  const sideQr = document.getElementById("side-qr");
  if (sideQr) sideQr.style.display = (id === "operador") ? "" : "none";
}

function mostrarOperador(btn) {
  marcarNav(btn === undefined ? "mostrarOperador" : btn);
  mostrar("operador");
}

function abrirOperador() {
  mostrarOperador();
  // volta ao painel: se o tipo for Campeonato, revalida a lista de campeonatos
  const tipo = (document.getElementById("cfg-tipo") || {}).value;
  if (tipo === "campeonato") carregarCampeonatosOperador();
}

// navega direto para uma seção do Admin (usado por busca/atalhos)
function adminIr(id) {
  adminSecao(null, id);
}


// ---------------------------------------------------------------- API
async function api(caminho, metodo = "POST", params = "", corpo = null) {
  const opcoes = { method: metodo };
  if (corpo !== null && corpo !== undefined) {
    opcoes.headers = { "Content-Type": "application/json" };
    opcoes.body = JSON.stringify(corpo);
  }
  const r = await fetch(`/api/${caminho}${params}`, opcoes);
  return r.json();
}
const conectarDecoder = () => {
  const tipo = document.getElementById("hw-tipo")?.value || "p3";
  if (tipo === "simulador") {
    // alvo = corrida do CTAD; velocidade (0,5x..10x) e sistema de telemetria
    const sessao = document.getElementById("hw-sessao")?.value || "";
    if (!sessao) {
      logMsg("simulador: carregue e escolha uma corrida do CTAD (botão 🔄)",
        "l-erro", "log-operador");
      return Promise.resolve({ ok: false });
    }
    const vel = parseFloat(document.getElementById("hw-velocidade")?.value || "1") || 1;
    const fonte = document.getElementById("hw-sistema")?.value || "p3";
    return api("decoder/conectar", "POST",
      `?tipo=simulador&alvo=${encodeURIComponent(sessao)}&velocidade=${vel}` +
      `&sistema=${encodeURIComponent(fonte)}`);
  }
  const alvoField = document.getElementById("hw-alvo")?.value?.trim() || "";
  if (tipo === "p3") {
    return api("decoder/conectar", "POST",
      `?tipo=p3&alvo=${encodeURIComponent(alvoField || "192.168.0.50")}`);
  }
  return api("decoder/conectar", "POST",
    `?tipo=${encodeURIComponent(tipo)}${alvoField ? "&alvo=" + encodeURIComponent(alvoField) : ""}`);
};
const desconectarDecoder = () => api("decoder/desconectar");
async function carregarAutoConectar() {
  try {
    const r = await api("decoder/auto", "GET");
    document.getElementById("hw-auto").checked = r.ativo !== false;
  } catch (e) {}
}
async function definirAutoConectar() {
  const ativo = document.getElementById("hw-auto").checked;
  const r = await api(`decoder/auto?ativo=${ativo}`);
  logMsg(`auto-conexão do decoder: ${r.ativo ? "ligada (tenta em loop ao abrir)" : "desligada"}`,
    "l-sistema", "log-operador");
}
async function carregarVozContagem() {
  try {
    const r = await api("sessao/voz-contagem", "GET");
    document.getElementById("cfg-voz-contagem").checked = r.ativa !== false;
  } catch (e) {}
}
async function salvarVozContagem() {
  const ativa = document.getElementById("cfg-voz-contagem").checked;
  const r = await api(`sessao/voz-contagem?ativa=${ativa}`);
  logMsg(`voz na contagem: ${r.ativa ? "ligada" : "desligada"}`,
    "l-sistema", "log-operador");
}
async function carregarTelaoTela() {
  const sel = document.getElementById("cfg-telao");
  if (!sel) return;
  let telas = [];
  try {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.telas)
      telas = await window.pywebview.api.telas() || [];
  } catch (e) {}
  if (!telas.length) telas = [{ indice: 0, largura: 0, altura: 0, principal: true }];
  sel.innerHTML = telas.map(t =>
    `<option value="${t.indice}">Tela ${t.indice + 1}${t.principal ? " (principal)" : ""}` +
    `${t.largura ? ` — ${t.largura}x${t.altura}` : ""}</option>`).join("");
  try {
    const r = await api("telao/tela", "GET");
    sel.value = String(r.indice ?? 1);
  } catch (e) {}
}
async function salvarTelaoTela() {
  const i = parseInt((document.getElementById("cfg-telao") || {}).value, 10) || 0;
  const r = await api(`telao/tela?indice=${i}`);
  if (r.ok) logMsg(`telão abre na Tela ${r.indice + 1} (maximizado)`, "l-sistema", "log-operador");
}
async function detectarPortas() {
  const r = await api("decoder/portas", "GET");
  const portas = (r.portas || []);
  if (portas.length) {
    document.getElementById("hw-alvo").value = portas[0];
    logMsg(`portas seriais detectadas: ${portas.join(", ")}`, "l-sistema", "log-operador");
  } else {
    logMsg("nenhuma porta serial detectada (EASYLAP plugado?)", "l-aviso", "log-operador");
  }
}
function hwTrocarTipo() {
  const tipo = document.getElementById("hw-tipo").value;
  const label = document.getElementById("hw-alvo-label");
  const alvo = document.getElementById("hw-alvo");
  const wrapPorta = document.getElementById("hw-porta-wrap");
  const wrapSim = document.getElementById("hw-sim-wrap");
  if (wrapSim) wrapSim.style.display = tipo === "simulador" ? "" : "none";
  if (tipo === "simulador") {
    label.textContent = "IP do decoder"; alvo.disabled = true;
    if (wrapPorta) wrapPorta.style.display = "none";
    carregarSessoesCTAD();
    return;
  }
  alvo.disabled = false;
  if (tipo === "p3") {
    label.textContent = "IP do decoder"; alvo.value = "192.168.0.50";
    if (wrapPorta) wrapPorta.style.display = "";
  } else if (tipo === "easylap") {
    label.textContent = "Porta serial (COM)"; alvo.value = alvo.value.startsWith("COM") ? alvo.value : "COM3";
    if (wrapPorta) wrapPorta.style.display = "none";
  } else {
    label.textContent = "Endereço BLE (vazio = descobrir)"; alvo.value = "";
    if (wrapPorta) wrapPorta.style.display = "none";
  }
}
async function carregarSessoesCTAD() {
  // popula o seletor de corridas enviadas ao CTAD (simulador de transponder)
  const sel = document.getElementById("hw-sessao");
  if (!sel) return;
  const anterior = sel.value;
  sel.innerHTML = `<option value="">carregando…</option>`;
  const r = await api("simulador/sessoes", "GET");
  if (!r.ok) {
    sel.innerHTML = `<option value="">— ${r.erro || "falha ao listar"} —</option>`;
    return;
  }
  const sessoes = r.sessoes || [];
  if (!sessoes.length) {
    sel.innerHTML = `<option value="">— nenhuma corrida enviada ao CTAD —</option>`;
    return;
  }
  sel.innerHTML = sessoes.map(s =>
    `<option value="${s.key}">${s.sessao} · ${s.pilotos} pilotos`
    + (s.melhor ? ` · melhor ${s.melhor}s` : "")
    + `${s.pista ? ` · ${s.pista}` : ""}</option>`).join("");
  if (anterior && [...sel.options].some(o => o.value === anterior)) sel.value = anterior;
}
// Telão em janela NATIVA do app (via Python); fora do app, cai no window.open.
function telaoNativo(segundaTela) {
  try {
    const api = window.pywebview && window.pywebview.api;
    if (!api) return false;
    (segundaTela ? api.telao_segunda_tela() : api.abrir_telao());
    return true;
  } catch (e) { return false; }
}
const abrirTelao = () => { if (!telaoNativo(false)) window.open("/telao", "_blank"); };
function abrirTelaoSegundaTela() {
  if (telaoNativo(true)) return;
  const w = window.open("/telao", "telao-2", "noopener,noreferrer");
  if (w) {
    // Tenta maximizar na segunda tela
    try { w.moveTo(screen.width, 0); w.resizeTo(screen.width, screen.height); } catch (e) {}
  }
}
const iniciarSessao = (tipo) => api("sessao/iniciar?tipo=" + tipo);
const largada = () => {
  const c = parseInt(document.getElementById("cfg-contador").value, 10) || 0;
  return api("sessao/largada?contador_s=" + c);
};
const pausar = (p) => api("sessao/pausar?pausar=" + p);
const finalizar = () => api("sessao/finalizar");

// Um único botão Pausar/Retomar: o rótulo mostra a ação que ele vai executar.
// (só faz sentido com sessão em andamento e sem sessão o botão fica desabilitado)
function atualizarBotaoPausa() {
  const btn = document.getElementById("btn-pausar");
  if (!btn) return;
  btn.disabled = !sessaoAtiva || estadoSessao === "largada";
  const pausada = sessaoPausada;
  btn.textContent = pausada ? "⏵ Retomar" : "⏸ Pausar";
  btn.title = pausada ? "Retomar o cronômetro da sessão" : "Pausar o cronômetro da sessão";
}
function alternarPausa() {
  if (!sessaoAtiva) return;
  pausar(!sessaoPausada);
}

// ---------------------------------------------------------------- WebSocket
function conectarWS() {
  if (ws && ws.readyState <= 1) return;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  const status = document.getElementById("ws-status");

  ws.onopen = () => { status.textContent = "Conectado com o servidor"; status.style.color = "var(--accent-green)"; };
  ws.onclose = () => {
    status.textContent = "Desconectado do servidor"; status.style.color = "var(--accent-red)";
    setTimeout(conectarWS, 2000);   // reconexão automática
  };
  ws.onmessage = (ev) => tratarEvento(JSON.parse(ev.data));
}

function tratarEvento(ev) {
  if (ev.tipo === "snapshot") { renderSnapshot(ev); return; }
  switch (ev.tipo) {
    case "status": marcarRxDecoder(); renderStatus(ev); break;
    case "volta":
      marcarRxDecoder();
      if (ev.recorde) {
        notificar("recorde",
          `Novo recorde ${ev.recorde === "pista" ? "da pista" : "pessoal"}: ${ev.tempo}s`, "⏱️");
        beepRecorde();
        break;
      }
      logMsg(`volta #${ev.numero} — ${ev.nome}: ${ev.tempo}s`, "l-volta", "log-operador");
      logMsg(`volta #${ev.numero} — ${ev.nome}: ${ev.tempo}s`, "l-volta", "log-dashboard");
      const fr = document.getElementById("flag-volta-rapida");
      if (fr) { fr.classList.add("pisca"); setTimeout(() => fr.classList.remove("pisca"), 2500); }
      beepVolta();
      break;
    case "admin":
      logMsg(`[admin] ${ev.msg}`, "l-admin", "log-operador");
      break;
    case "sync":
      logMsg(`[sync] ${ev.msg}`, "l-admin", "log-operador");
      break;
    case "classificacao": renderClassificacao(ev); break;
    case "voltas":
      if (abaOperadorAtiva && [1, 2, 4].includes(abaOperadorAtiva)) desenharGraficoOperador(abaOperadorAtiva);
      break;
    case "ghost_lap":
      logMsg(`GHOST LAP descartado — transponder ${ev.transponder}`, "l-aviso", "log-operador");
      notificar("ghost_lap", `Ghost lap descartado — transponder ${ev.transponder}`, "👻");
      break;
    case "aviso": logMsg(`AVISO: ${ev.msg}`, "l-aviso", "log-operador"); break;
    case "atualizacao":
      if (ev.disponivel) {
        const stU = document.getElementById("upd-status");
        if (stU) stU.innerHTML = `<b style="color:var(--accent-green)">v${ev.versao_remota} disponível</b>` +
          ` (atual v${ev.versao_atual}) — use "Instalar agora"`;
      }
      break;
    case "erro":
      logMsg(`ERRO: ${ev.msg}`, "l-erro", "log-operador");
      if (/decoder|conectad|conex/i.test(ev.msg || "")) refreshDecoderPainel();
      break;
    case "bandeira":
      _renderEstadoPista(ev);
      logMsg(`bandeira: ${ev.bandeira || ev.cor}${ev.motivo ? " — " + ev.motivo : ""}`,
        "l-aviso", "log-operador");
      if (ev.bandeira === "vermelha" || ev.bandeira === "fechada")
        notificar("decoder_offline", `Pista ${ev.bandeira}${ev.motivo ? " — " + ev.motivo : ""}`, "🚩");
      break;
    case "checkin":
      if (Array.isArray(ev.presentes)) { checkinCache.presentes = ev.presentes; renderCheckin(); }
      break;
    case "anuncio":
      logMsg(`anúncio: ${ev.texto}`, "l-admin", "log-operador");
      break;
    case "sessao":
      logMsg(`sessão: ${ev.estado}`, "l-sistema", "log-operador");
      document.getElementById("operador-estado").textContent = ev.estado;
      if (ev.classificacao) renderClassificacao({ linhas: ev.classificacao });
      // estado otimista imediato (o refresh abaixo confirma pelo snapshot)
      if (ev.estado === "finalizada") { sessaoAtiva = false; estadoSessao = "finalizado"; }
      else if (["iniciada", "correndo", "largada", "treino",
                "classificacao"].includes(ev.estado)) sessaoAtiva = true;
      if (typeof ev.pausada === "boolean") sessaoPausada = ev.pausada;
      atualizarBotaoPrincipal();
      atualizarBotaoPausa();
      // atualiza a base do cronômetro (o snapshot só chega ao conectar o WS)
      api("status", "GET").then(s => { if (s && s.sessao) renderSessao(s.sessao); }).catch(() => {});
      break;
    case "sistema":
      logMsg(ev.msg, "l-sistema", "log-operador");
      logMsg(ev.msg, "l-sistema", "log-dashboard");
      if (/decoder|conectad|conex/i.test(ev.msg || "")) refreshDecoderPainel();
      break;
    case "campeonato":
      renderEstadoCampeonato(ev.estado || null);
      logMsg(`[campeonato] ${ev.msg}`, "l-sistema", "log-operador");
      api("status", "GET").then(s => { if (s && s.sessao) renderSessao(s.sessao); }).catch(() => {});
      break;
    case "decoder":
      marcarRxDecoder();
      logMsg(ev.msg, "", "log-dashboard");
      if (ev.msg && /desconect|offline|perd/i.test(ev.msg))
        notificar("decoder_offline", ev.msg, "🔌");
      break;
    case "semaforo":
      renderMiniSemaforo(ev.acesas || 0, ev.fase || "vermelho");
      atualizarRelogioLargada(ev);
      break;
  }
}

function refreshDecoderPainel() {
  api("status", "GET")
    .then(s => { if (s && s.decoder) renderDecoder(s.decoder); })
    .catch(() => {});
}

let ultimaClassificacao = { linhas: [] };

// ---------------------------------------------------------------- render
function renderSnapshot(s) {
  ultimaClassificacao = { linhas: s.classificacao || [] };
  renderDecoder(s.decoder);
  renderSessao(s.sessao);
  const cp = document.getElementById("card-passings");
  if (cp) cp.textContent = s.contadores.passings_validos;
  const cg = document.getElementById("card-ghost");
  if (cg) cg.textContent =
    `${s.contadores.ghost_laps} ghost laps descartados`;
  renderStatus(s.decoder.status ? { ...s.decoder.status } : null);
  renderClassificacao({ linhas: s.classificacao || [] });
  if (s.pista) _renderEstadoPista(s.pista);
  if (Array.isArray(s.checkin)) { checkinCache.presentes = s.checkin; if (checkinCache.pilotos.length) renderCheckin(); }
  if (s.campeonato) renderEstadoCampeonato(s.campeonato);
  (s.eventos || []).slice(-12).forEach(e => {
    const classe = e.tipo === "aviso" || e.tipo === "ghost_lap" ? "l-aviso"
      : e.tipo === "erro" ? "l-erro" : e.tipo === "volta" ? "l-volta" : "l-sistema";
    logMsg(`[${e.ts}] ${e.msg || e.tipo}${e.nome ? " " + e.nome : ""}`, classe, "log-operador");
    logMsg(`[${e.ts}] ${e.msg || e.tipo}${e.nome ? " " + e.nome : ""}`, classe, "log-dashboard");
  });
}

function renderDecoder(d) {
  const el = document.getElementById("card-decoder");
  const sub = document.getElementById("card-decoder-sub");
  const nomes = { p3: "MyLaps P3", easylap: "EASYLAP-USB", lapwiz: "SKYRC LapWiz", simulador: "Simulador CTAD" };
  if (el) {
    el.textContent = d.conectado ? "Conectado" : "Desconectado";
    el.style.color = d.conectado ? "var(--accent-green)" : "var(--accent-red)";
  }
  const fonte = d.tipo === "simulador" && d.sistema ? ` (${nomes[d.sistema] || d.sistema})` : "";
  if (sub) sub.textContent = `${nomes[d.tipo] || d.tipo}${fonte} · ${d.host || "—"}${d.porta ? ":" + d.porta : ""}`;
  const led = document.getElementById("led-decoder");
  const txt = document.getElementById("txt-ligacao");
  if (led) led.classList.toggle("on", d.conectado);
  if (txt) txt.textContent = d.conectado ? "Ligado ao decoder" : "Sem ligação";
  // reflete o estado na aba de Admin > Hardware (sem sobrescrever o que o usuário digita)
  const sel = document.getElementById("hw-tipo");
  if (sel && d.tipo && document.activeElement !== sel) sel.value = d.tipo;
  // espelha as opções do simulador (fonte de telemetria e velocidade)
  const simSel = document.getElementById("hw-sistema");
  if (simSel && d.tipo === "simulador" && d.sistema &&
      [...simSel.options].some(o => o.value === d.sistema) &&
      document.activeElement !== simSel) simSel.value = d.sistema;
  const velSel = document.getElementById("hw-velocidade");
  if (velSel && d.tipo === "simulador" && d.sim_velocidade != null &&
      [...velSel.options].some(o => Number(o.value) === Number(d.sim_velocidade)) &&
      document.activeElement !== velSel) velSel.value = String(Number(d.sim_velocidade));
  const pill = document.getElementById("hw-status-pill");
  if (pill) {
    pill.textContent = d.conectado ? "conectado" : "desconectado";
    pill.className = "pill " + (d.conectado ? "ok" : "novo");
  }
  // espelho no topo do menu lateral (logo abaixo da logomarca)
  const sideLed = document.getElementById("side-led");
  if (sideLed) sideLed.classList.toggle("on", !!d.conectado);
  const sideNome = document.getElementById("side-decoder-nome");
  if (sideNome) sideNome.textContent =
    `Decoder: ${nomes[d.tipo] || d.tipo || "—"}${d.conectado ? "" : " (desconectado)"}`;
  decoderConectado = !!d.conectado;
  decoderBaseTxt = d.conectado ? `${d.host || "—"}${d.porta ? ":" + d.porta : ""}` : "sem ligação";
  ultimoRxDecoder = (typeof d.segundos_sem_dados === "number")
    ? Date.now() - d.segundos_sem_dados * 1000 : (d.conectado ? Date.now() : 0);
  tickDecoderSilencio();
}

// marca todo frame que chega do decoder (status/volta/mensagem crua)
function marcarRxDecoder() { ultimoRxDecoder = Date.now(); tickDecoderSilencio(); }

// "conectado mas sem dados há Xs" — atualizado pelo tick de 500 ms
let decoderConectado = false, decoderBaseTxt = "sem ligação", ultimoRxDecoder = 0;
function tickDecoderSilencio() {
  if (!decoderConectado || !ultimoRxDecoder) return;
  const gap = Math.floor((Date.now() - ultimoRxDecoder) / 1000);
  const suf = gap > 20 ? ` · sem dados há ${gap}s` : "";
  const sub = document.getElementById("side-decoder-sub");
  if (sub) sub.textContent = decoderBaseTxt + suf;
  const txt = document.getElementById("txt-ligacao");
  if (txt) txt.textContent = "Ligado ao decoder" + (gap > 20 ? " — sem dados!" : "");
}

// Mini-semáforo do operador: fase "vermelho" (n luzes), "verde" ou "apagado".
// A sequência de largada pilota luz a luz via evento "semaforo".
function renderMiniSemaforo(acesas, fase) {
  const box = document.getElementById("mini-semaforo");
  if (!box) return;
  const vermelhas = box.querySelectorAll(".mluz.vermelha");
  const verde = box.querySelector(".mluz.verde");
  vermelhas.forEach((l, i) => l.classList.toggle("on", fase === "vermelho" && i < acesas));
  if (verde) verde.classList.toggle("on", fase === "verde");
  // botão Largada piscar vermelho durante a contagem regressiva (semáforo vermelho)
  const btn = document.getElementById("btn-acao-principal");
  if (btn) btn.classList.toggle("btn-regressiva-piscar", fase === "vermelho");
}

// Durante a contagem, o display "Tempo" vira o número da regressiva (o servidor
// é a fonte da verdade: cada evento "semaforo" traz restante_ms e o número).
function atualizarRelogioLargada(ev) {
  if (estadoSessao !== "largada") return;
  const el = document.getElementById("disp-tempo");
  if (!el) return;
  if (ev.fase === "verde") { el.textContent = fmtClock(0); return; }
  const s = Math.ceil((ev.restante_ms || 0) / 1000);
  el.textContent = s > 0 ? String(s) : "0";
}

function renderSessao(s) {
  const cs = document.getElementById("card-sessao");
  if (cs) cs.textContent = s.estado || "—";
  const css = document.getElementById("card-sessao-sub");
  if (css) css.textContent =
    s.id ? `sessão ${s.id.slice(0, 8)}${s.simulacao ? " · SIMULAÇÃO" : ""}` +
           `${s.pausada ? " · pausada" : ""}` : "nenhuma sessão ativa";
  const opEst = document.getElementById("operador-estado");
  if (opEst) opEst.textContent = s.estado || "sem sessão";
  const opSes = document.getElementById("operador-sessao");
  if (opSes) opSes.textContent = s.id ? s.id.slice(0, 8) : "—";
  const opSim = document.getElementById("operador-sim");
  if (opSim) opSim.hidden = !(s.id && s.simulacao);
  // estado da sessão → botão principal de ação
  estadoSessao = s.estado || "parado";
  sessaoAtiva = !!(s.id && !["parado", "finalizado"].includes(estadoSessao));
  sessaoPausada = !!s.pausada;
  atualizarBotaoPrincipal();
  atualizarBotaoPausa();
  // mini-semáforo acompanha o estado (a sequência de largada pilota via evento)
  if (estadoSessao === "largada") renderMiniSemaforo(0, "vermelho");
  else if (["treino", "classificacao", "correndo"].includes(estadoSessao)) renderMiniSemaforo(0, "verde");
  else renderMiniSemaforo(0, "apagado");
  // base do cronômetro da sessão (tick local atualiza o display a cada 500 ms)
  sessaoClock = {
    id: s.id || null, estado: s.estado || "parado",
    base_s: (typeof s.tempo_s === "number" ? s.tempo_s : null),
    restante_s: (typeof s.restante_s === "number" ? s.restante_s : null),
    pausada: !!s.pausada, finalizada: s.estado === "finalizado",
    recebidoEm: Date.now(),
  };
}

// cronômetro da sessão no display "Tempo" enquanto não há líder com voltas.
// (Com voltas, o display mostra o total do líder — vide renderClassificacao.)
// Formato com milésimos: M:SS.mmm (ou H:MM:SS.mmm se passar de 1 hora).
function fmtClock(total_s) {
  total_s = Math.max(0, total_s || 0);
  const total_ms = Math.floor(total_s * 1000);
  const mmm = String(total_ms % 1000).padStart(3, "0");
  let seg = Math.floor(total_ms / 1000);
  const s = String(seg % 60).padStart(2, "0");
  seg = Math.floor(seg / 60);
  const m = seg % 60;
  const h = Math.floor(seg / 60);
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${s}.${mmm}`;
  return `${m}:${s}.${mmm}`;
}
let sessaoClock = null;
function tickRelogioSessao() {
  if (!sessaoClock) return;
  if (!sessaoClock.id) return;
  if (sessaoClock.estado === "largada") return;   // regressiva vem dos eventos "semaforo"
  const el = document.getElementById("disp-tempo");
  if (!el) return;
  // intervalo: mostra a regressiva configurada (tem prioridade sobre o líder)
  if (sessaoClock.restante_s != null) {
    let r = sessaoClock.restante_s;
    if (!sessaoClock.pausada) r = Math.max(0, r - (Date.now() - sessaoClock.recebidoEm) / 1000);
    el.textContent = fmtClock(r);
    return;
  }
  if (sessaoClock.base_s == null) return;
  if (!["treino", "classificacao", "correndo", "largada", "finalizado"].includes(sessaoClock.estado)) return;
  const temVolta = ultimaClassificacao.linhas && ultimaClassificacao.linhas.some(l => l.voltas > 0);
  if (temVolta) return;   // líder manda no display
  let t = sessaoClock.base_s;
  if (!sessaoClock.pausada && !sessaoClock.finalizada)
    t += (Date.now() - sessaoClock.recebidoEm) / 1000;
  el.textContent = fmtClock(t);
}
setInterval(tickDecoderSilencio, 500);
setInterval(tickRelogioSessao, 33);   // ~30 Hz: milésimos animando

function renderStatus(st) {
  if (st) {
    const sub = document.getElementById("card-decoder-sub");
    if (sub) sub.textContent = `${st.temperatura ?? "?"}°C · ${st.tensao ?? "?"}V · ruído ${st.ruido ?? "?"}`;
    const drift = document.getElementById("card-drift");
    if (drift) {
      if (st.drift_us == null) { drift.textContent = "sincronizado"; drift.style.color = "var(--accent-green)"; }
      else { drift.textContent = (st.drift_us / 1e6).toFixed(1) + " s"; drift.style.color = "var(--accent-gold)"; }
    }
    const cat = document.getElementById("tv-cat");
    if (cat) cat.textContent = `${st.temperatura ?? "?"}°C · ao vivo`;
  }
  // hardware (admin)
  const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
  set("med-temp", st ? `${st.temperatura ?? "?"}°C` : "—");
  set("med-tensao", st ? `${st.tensao ?? "?"}V` : "—");
  set("med-ruido", st ? String(st.ruido ?? "—") : "—");
  set("med-drift", st ? (st.drift_us == null ? "0s" : (st.drift_us / 1e6).toFixed(1) + "s") : "—");
  // hardware (admin)
  set("hw-status", st && st.temperatura != null ? "conectado" : "—");
  set("hw-temp", st ? `${st.temperatura ?? "?"}°C` : "—");
  set("hw-tensao", st ? `${st.tensao ?? "?"}V` : "—");
  set("hw-ruido", st ? String(st.ruido ?? "—") : "—");
  // detalhe no menu lateral (status completo sob a logomarca)
  const sideSub = document.getElementById("side-decoder-sub");
  if (sideSub && st && st.temperatura != null)
    sideSub.textContent = `${st.temperatura ?? "?"}°C · ${st.tensao ?? "?"}V · ruído ${st.ruido ?? "?"}`;
}

const HEADER_OP = "<tr><th>Pos</th><th>Nº</th><th>Abr</th><th>Piloto</th><th>Voltas</th><th>Total</th><th>Intervalo</th><th>Gap</th><th>Última</th><th>Melhor</th><th>Média</th><th>Desvio</th><th>Consist.</th><th>Transponder</th><th>Ações</th></tr>";
const VAZIO_OP = '<tr><td colspan="15" style="color:var(--text-muted)">nenhuma volta registrada</td></tr>';
let linhaSel = null;

function renderClassificacao(ev) {
  ultimaClassificacao = ev;
  const linhas = (ev.linhas || []).map(l =>
    `<tr class="${l.posicao === 1 ? "pos1" : ""}" data-piloto="${l.piloto_id}" onclick="selecionarLinha(this)">
       <td>${l.posicao}</td><td>${l.numero || "-"}</td><td>${l.abreviado || ""}</td>
       <td>${l.nome}${l.suspeita ? '<span class="gato">gato</span>' : ""}</td>
       <td>${l.voltas}</td><td>${l.tempo || "-"}</td><td>${l.intervalo || "-"}</td><td>${l.gap || ""}</td>
       <td>${l.ultima || "-"}</td><td>${l.melhor || "-"}</td><td>${l.media || "-"}</td>
       <td>${l.desvio || "-"}</td><td>${l.consistencia || "-"}</td><td>${l.transponder ?? "-"}</td>
       <td><span class="acao" title="marcar gato" onclick="event.stopPropagation();marcarGato()">🚫</span> <span class="acao" title="apagar" onclick="event.stopPropagation();apagarVolta()">🗑</span></td></tr>`).join("");

  const t1 = document.getElementById("tabela-classificacao");
  if (t1) t1.innerHTML = HEADER_OP + (linhas || VAZIO_OP);

  // telão (colunas resumidas)
  const linhasTv = (ev.linhas || []).map(l =>
    `<tr class="${l.posicao === 1 ? "pos1" : ""}">
       <td>${l.posicao}</td><td>${l.numero || "-"}</td><td>${l.abreviado || ""}</td><td>${l.nome}</td>
       <td>${l.voltas}</td><td>${l.melhor || "-"}</td><td>${l.tempo || "-"}</td><td>${l.gap || ""}</td></tr>`).join("");
  const t2 = document.getElementById("tabela-tv");
  if (t2) t2.innerHTML = `<tr><th>Pos</th><th>Nº</th><th>Abr</th><th>Piloto</th><th>Voltas</th><th>Melhor</th><th>Total</th><th>Gap</th></tr>` +
    (linhasTv || `<tr><td colspan="8" style="color:#666">aguardando largada…</td></tr>`);

  // display digital + flags
  const lista = ev.linhas || [];
  const lider = lista[0];
  const emPista = lista.filter(l => l.voltas > 0).length;
  const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
  set("disp-empista", emPista);
  set("disp-voltas", lider ? lider.voltas : 0);
  set("disp-tempo", lider ? lider.tempo : "0:00.000");
  set("flag-primeiro", lider ? `1º: ${lider.nome.split(" ")[0]}` : "1º: —");

  // aba "Tempos"
  const tv = document.getElementById("tabela-voltas");
  if (tv) {
    tv.innerHTML = "<tr><th>Piloto</th><th>Voltas</th><th>Tempo</th></tr>" +
      (linhas || '<tr><td colspan="3" style="color:var(--text-muted)">sem voltas na sessão</td></tr>');
  }

  // líder da sessão (cartões de resumo)
  const el = document.getElementById("card-lider");
  if (el) el.textContent = lider ? lider.nome.split(" ")[0] : "—";
  const sub = document.getElementById("card-lider-sub");
  if (sub) sub.textContent = lider ? `${lider.voltas} voltas · ${lider.melhor || "-"}` : "líder da sessão";
  const voltas = document.getElementById("d-voltas");
  if (voltas && lider) voltas.innerHTML = `${lider.voltas}<span class="un">voltas</span>`;
}

function selecionarLinha(tr) {
  document.querySelectorAll("#tabela-classificacao tr").forEach(r => r.classList.remove("selecionada"));
  tr.classList.add("selecionada");
  linhaSel = { piloto_id: tr.getAttribute("data-piloto") };
}

function iniciarSessaoConfigurada() {
  const tipo = document.getElementById("cfg-tipo").value;
  if (tipo === "campeonato") { iniciarCampeonatoEscolhido(); return; }
  const criterio = document.getElementById("cfg-criterio").value;
  const duracao = parseFloat(document.getElementById("cfg-duracao").value) || 10;
  const tmin = parseFloat(document.getElementById("cfg-tempo-minimo").value) || 0;
  const contador = parseInt(document.getElementById("cfg-contador").value, 10) || 10;
  api(`sessao/iniciar?tipo=${tipo}&tempo_minimo_s=${tmin}` +
      `&duracao=${duracao}&criterio=${encodeURIComponent(criterio)}` +
      `&contador_s=${contador}`).then(r => {
    if (r.ok === false) { logMsg(`sessão: ${r.erro || "não iniciada"}`, "l-erro", "log-operador"); return; }
    logMsg(`sessão iniciada (${tipo}, ${duracao} min, contador ${contador}s)`, "l-sistema", "log-operador");
    abrirOperador();
  });
}

function marcarGato() {
  if (!linhaSel) { logMsg("selecione um piloto na tabela primeiro", "l-aviso", "log-operador"); return; }
  api(`sessao/marcar-gato?piloto_id=${linhaSel.piloto_id}`).then(r => {
    if (r.ok) logMsg("última volta marcada como suspeita ('gato')", "l-admin", "log-operador");
  });
}

function desmarcarGato() {
  if (!linhaSel) { logMsg("selecione um piloto na tabela primeiro", "l-aviso", "log-operador"); return; }
  api(`sessao/desmarcar-gato?piloto_id=${linhaSel.piloto_id}`).then(r => {
    if (r.ok) logMsg("marcação de 'gato' removida", "l-admin", "log-operador");
  });
}

function apagarVolta() {
  if (!linhaSel) { logMsg("selecione um piloto na tabela primeiro", "l-aviso", "log-operador"); return; }
  api(`sessao/apagar-volta?piloto_id=${linhaSel.piloto_id}`).then(r => {
    if (r.ok) logMsg("última volta apagada (ação administrativa)", "l-admin", "log-operador");
  });
}

function aba(btn, i) {
  document.querySelectorAll(".abas button").forEach(b => b.classList.remove("on"));
  btn.classList.add("on");
  for (let k = 0; k < 5; k++) {
    const el = document.getElementById("aba-" + k);
    if (el) el.classList.toggle("on", k === i);
  }
  abaOperadorAtiva = i;
  if ([1, 2, 4].includes(i)) desenharGraficoOperador(i);
}

function logMsg(texto, classe, elementoId) {
  const el = document.getElementById(elementoId);
  if (!el) return;
  const linha = document.createElement("div");
  if (classe) linha.className = classe;
  linha.textContent = texto;
  el.appendChild(linha);
  el.scrollTop = el.scrollHeight;
  while (el.children.length > 120) el.removeChild(el.firstChild);
}

// ---------------------------------------------------------------- gráficos (Fase 4)
const CORES_OP = ["#ffb703", "#3a86ff", "#2ec4b6", "#ff006e", "#a4d007", "#c0c0c0",
                  "#ff8c42", "#bb9af7", "#7aa2f7", "#f7768e", "#9ece6a", "#e0af68"];
let grafOpPos = null, grafOpVoltas = null;
let abaOperadorAtiva = 0;

async function dadosVoltasSessao() {
  try { return await api("sessao/voltas", "GET"); } catch (e) { return null; }
}

function posicoesPorVolta(dados) {
  const pilotos = (dados.pilotos || []).slice(0, 12);
  const maxVoltas = Math.max(0, ...pilotos.map(p => p.voltas.length));
  const series = pilotos.map((p, i) => ({ nome: p.nome, cor: CORES_OP[i % CORES_OP.length], pontos: [] }));
  for (let n = 1; n <= maxVoltas; n++) {
    const ranking = pilotos.filter(p => p.voltas.filter(v => v.numero <= n).length >= n)
      .map(p => ({ nome: p.nome,
                   parcial: p.voltas.filter(v => v.numero <= n).reduce((s, v) => s + v.tempo, 0) }))
      .sort((a, b) => a.parcial - b.parcial);
    ranking.forEach((r, idx) => {
      const s = series.find(s => s.nome === r.nome);
      if (s) s.pontos.push({ x: n, y: idx + 1 });
    });
  }
  return series;
}

async function desenharGraficoOperador(idx) {
  if (typeof Chart === "undefined") return;
  const dados = await dadosVoltasSessao();
  if (!dados || !(dados.pilotos || []).length) return;
  if (idx === 1) {   // posições volta a volta
    const series = posicoesPorVolta(dados);
    if (grafOpPos) grafOpPos.destroy();
    grafOpPos = new Chart(document.getElementById("op-posicoes"), {
      type: "line",
      data: { datasets: series.map(s => ({ label: s.nome, data: s.pontos,
              borderColor: s.cor, backgroundColor: s.cor, stepped: true, pointRadius: 3 })) },
      options: { responsive: true, maintainAspectRatio: false,
        plugins: { legend: { labels: { color: "#d0d7e3" } } },
        scales: {
          x: { title: { display: true, text: "volta", color: "#8492a6" }, ticks: { color: "#8492a6" }, grid: { color: "#1a2438" } },
          y: { reverse: true, min: 1, title: { display: true, text: "posição", color: "#8492a6" }, ticks: { color: "#8492a6", precision: 0 }, grid: { color: "#1a2438" } } } } });
  } else if (idx === 2) {   // melhores voltas (barras)
    const melhores = dados.pilotos.slice(0, 12).map((p, i) => ({
      nome: p.nome, cor: CORES_OP[i % CORES_OP.length],
      melhor: Math.min(...p.voltas.map(v => v.tempo)) }));
    if (grafOpVoltas) grafOpVoltas.destroy();
    grafOpVoltas = new Chart(document.getElementById("op-voltas"), {
      type: "bar",
      data: { labels: melhores.map(m => m.nome),
              datasets: [{ label: "melhor volta (s)", data: melhores.map(m => m.melhor),
                           backgroundColor: melhores.map(m => m.cor) }] },
      options: { responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { color: "#8492a6" }, grid: { color: "#1a2438" } },
          y: { title: { display: true, text: "segundos", color: "#8492a6" }, ticks: { color: "#8492a6" }, grid: { color: "#1a2438" } } } } });
  } else if (idx === 4) {   // track view
    desenharTrackOperador(dados);
  }
}

function desenharTrackOperador(dados) {
  const canvas = document.getElementById("op-track");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const W = canvas.width = canvas.clientWidth, H = canvas.height = 300;
  ctx.clearRect(0, 0, W, H);
  ctx.strokeStyle = "#22304d"; ctx.lineWidth = 24;
  ctx.beginPath(); ctx.ellipse(W / 2, H / 2, W * 0.36, H * 0.36, 0, 0, Math.PI * 2); ctx.stroke();
  ctx.strokeStyle = "#3a86ff"; ctx.lineWidth = 2; ctx.setLineDash([8, 8]);
  ctx.beginPath(); ctx.ellipse(W / 2, H / 2, W * 0.36, H * 0.36, 0, 0, Math.PI * 2); ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = "#fff"; ctx.fillRect(W / 2 + W * 0.36 - 3, H / 2 - 12, 6, 24);
  const pilotos = (dados.pilotos || []).slice(0, 12);
  const maxV = Math.max(1, ...pilotos.map(p => p.voltas.length));
  pilotos.forEach((p, i) => {
    const ang = -Math.PI / 2 + (p.voltas.length / maxV) * Math.PI * 2;
    const x = W / 2 + Math.cos(ang) * W * 0.36;
    const y = H / 2 + Math.sin(ang) * H * 0.36;
    ctx.fillStyle = CORES_OP[i % CORES_OP.length];
    ctx.beginPath(); ctx.arc(x, y, 9, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = "#fff"; ctx.font = "bold 11px Segoe UI"; ctx.textAlign = "center";
    ctx.fillText(String(i + 1), x, y + 4);
  });
}

// ---------------------------------------------------------------- campeonatos (Fase 5)
let campAtual = null;

async function carregarCampeonatos() {
  const r = await api("campeonatos", "GET");
  const sel = document.getElementById("camp-select");
  const lista = r.campeonatos || [];
  sel.innerHTML = lista.length
    ? lista.map(c => `<option value="${c.id}">${c.nome} — ${c.inscritos} inscritos</option>`).join("")
    : '<option value="">— nenhum campeonato —</option>';
  carregarCamposSyncCamp();
  if (lista.length) {
    // seleção pedida pelo painel do operador (botão "Editar campeonato")
    if (campSelecionarPendente
        && lista.some(c => String(c.id) === String(campSelecionarPendente))) {
      sel.value = campSelecionarPendente;
    }
    campSelecionarPendente = null;
    abrirCampeonato();
  } else {
    campSelecionarPendente = null;
  }
}

async function criarCampeonato() {
  const nome = document.getElementById("camp-nome").value.trim();
  if (!nome) { logMsg("campeonato: informe um nome", "l-aviso", "log-operador"); return; }
  const provas = document.getElementById("camp-provas").value || 4;
  const porprova = document.getElementById("camp-porprova").value || 10;
  const porchave = document.getElementById("camp-porchave").value || 10;
  const inverter = document.getElementById("camp-inverter").checked ? 1 : 0;
  const drop = document.getElementById("camp-drop").value || 0;
  const bpole = document.getElementById("camp-bpole").value || 0;
  const bmv = document.getElementById("camp-bmv").value || 0;
  const r = await api(`campeonatos?nome=${encodeURIComponent(nome)}&numero_provas=${provas}`
    + `&pilotos_por_prova=${porprova}&pilotos_por_chave=${porchave}&inverter_bateria=${inverter}`
    + `&drop_rounds=${drop}&bonus_pole=${bpole}&bonus_melhor_volta=${bmv}`);
  if (r.ok) {
    logMsg(`campeonato: '${nome}' criado`, "l-admin", "log-operador");
    document.getElementById("camp-nome").value = "";
    carregarCampeonatos();
  } else {
    logMsg(`campeonato: ${r.erro}`, "l-erro", "log-operador");
  }
}

async function abrirCampeonato() {
  const id = document.getElementById("camp-select").value;
  if (!id) { carregarCamposSyncCamp(); return; }
  campAtual = parseInt(id);
  const r = await api(`campeonatos/${campAtual}`, "GET");
  if (!r.ok) return;
  document.getElementById("camp-inscritos-n").textContent = r.inscritos.length;
  const t = document.getElementById("tabela-inscritos");
  t.innerHTML = "<tr><th>#</th><th>Piloto</th><th>Transponder</th><th>Frequência</th><th>Ranking</th></tr>"
    + (r.inscritos.map((i, k) => `<tr><td>${k + 1}</td><td>${i.nome}</td>
        <td>${i.transponder ?? "—"}</td><td>${i.frequencia ?? "—"}</td>
        <td>${i.pontos_ranking || 0}</td></tr>`).join("")
       || '<tr><td colspan="5" style="color:var(--text-muted)">nenhum inscrito</td></tr>');
  document.getElementById("camp-piloto").innerHTML =
    r.pilotos.map(p => `<option value="${p.id}">${p.nome}</option>`).join("");
  renderBaterias(r.baterias);
  carregarRanking();
  carregarGrids();
}

async function inscreverPilotoCamp() {
  if (!campAtual) { logMsg("campeonato: crie/selecione um campeonato", "l-aviso", "log-operador"); return; }
  const piloto = document.getElementById("camp-piloto").value;
  const t = document.getElementById("camp-transponder").value.trim();
  const f = document.getElementById("camp-freq").value.trim();
  const r = await api(`campeonatos/${campAtual}/inscrever?piloto_id=${piloto}`
    + (t ? `&transponder=${t}` : "") + (f ? `&frequencia=${encodeURIComponent(f)}` : ""));
  if (r.ok) { abrirCampeonato(); } else { logMsg("campeonato: piloto já inscrito", "l-aviso", "log-operador"); }
}

async function gerarHeats() {
  if (!campAtual) { logMsg("campeonato: crie/selecione um campeonato", "l-aviso", "log-operador"); return; }
  const finais = document.getElementById("camp-finais").value || 1;
  const r = await api(`campeonatos/${campAtual}/heats?num_finais=${finais}`);
  if (r.ok) {
    renderBaterias(r.baterias);
    const bloq = r.bloqueadas || 0;
    logMsg(`campeonato: ${r.baterias.length} baterias geradas`
      + (bloq ? ` — ${bloq} BLOQUEADA(S) por conflito de espectro` : " — todas liberadas"),
      bloq ? "l-aviso" : "l-admin", "log-operador");
  } else {
    logMsg(`campeonato: ${r.erro}`, "l-erro", "log-operador");
  }
}

async function lancarResultado(bateriaId) {
  const r = await api(`campeonatos/baterias/${bateriaId}/lancar`);
  if (r.ok) {
    logMsg(`campeonato: resultado lançado (${r.lancados} pilotos)`, "l-admin", "log-operador");
    abrirCampeonato();
  } else {
    logMsg(`campeonato: ${r.erro}`, "l-erro", "log-operador");
  }
}

async function carregarRanking() {
  if (!campAtual) return;
  const r = await api(`campeonatos/${campAtual}/ranking`, "GET");
  const t = document.getElementById("tabela-ranking");
  if (!r.ok || !r.ranking.length) {
    t.innerHTML = '<tr><th>Pos</th><th>Piloto</th><th>Total</th><th>Válidos</th><th>Descartados</th></tr>'
      + '<tr><td colspan="5" style="color:var(--text-muted)">sem resultados lançados</td></tr>';
    return;
  }
  t.innerHTML = '<tr><th>Pos</th><th>Piloto</th><th>Total</th><th>Válidos</th><th>Descartados</th></tr>'
    + r.ranking.map(l => `<tr class="${l.posicao === 1 ? "pos1" : ""}">
        <td>${l.posicao}º</td><td>${l.piloto}</td>
        <td><b>${l.total.toFixed(0)}</b></td>
        <td>[${l.validos.map(v => v.toFixed(0)).join(", ")}]</td>
        <td style="color:var(--accent-red)">[${l.descartados.map(v => v.toFixed(0)).join(", ") || "—"}]</td>
      </tr>`).join("");
}

// ---------------------------------------------------------------- sistema de chaves (CTAD)
async function carregarGrids() {
  const el = document.getElementById("camp-grids");
  if (!campAtual) { if (el) el.innerHTML = ""; return; }
  const r = await api(`campeonatos/${campAtual}/grids`, "GET");
  if (!r || r.ok === false) {
    if (el) el.innerHTML = `<p class="hint">${r && r.erro ? r.erro : "erro ao carregar grids"}</p>`;
    return;
  }
  // valores vigentes (somente leitura — vêm da criação ou da importação do CTAD)
  const val = document.getElementById("camp-chave-max-valor");
  if (val) val.textContent = r.max_por_chave;
  const inpInv = document.getElementById("camp-chave-inv");
  if (inpInv) inpInv.checked = !!r.inverter_bateria;
  renderGrids(r);
}

function renderGrids(r) {
  const el = document.getElementById("camp-grids");
  if (!el) return;
  if (!r.grids || !r.grids.length || !r.inscritos) {
    el.innerHTML = '<p class="hint">sem inscritos — inscreva pilotos para montar as chaves</p>';
    return;
  }
  el.innerHTML = r.grids.map(g => {
    const multi = g.distribuicao.length > 1;
    const titulo = multi
      ? `🏁 Grid — Prova ${g.prova} <span class="hint">(dividida em ${g.distribuicao.length} chaves)</span>`
      : `🏁 Grid — Prova ${g.prova}`;
    const chaves = g.chaves.map(c => {
      const linhas = c.pilotos.map((p, k) =>
        `<tr><td>${k + 1}</td><td>${p.nome}</td><td class="hint">${g.criterio}</td></tr>`).join("");
      const cab = multi
        ? `<div class="admin-secao-tit">🔑 ${c.nome}
             <span class="hint">(${c.pilotos.length} ${c.pilotos.length === 1 ? "piloto" : "pilotos"})</span></div>`
        : "";
      return `<div class="camp-grid-bloco">${cab}
        <div class="card"><div class="tabela-wrap"><table class="admin-tabela">
          <tr><th>Pos</th><th>Piloto</th><th>Critério</th></tr>${linhas}
        </table></div></div>
      </div>`;
    }).join("");
    return `<div class="camp-grid"><div class="admin-secao-tit">${titulo}
      <span class="hint">critério: ${g.criterio}</span></div>${chaves}</div>`;
  }).join("");
}

// Inverte a ordem da bateria seguinte (salva na hora; o nº máximo por chave
// não é editado aqui — vem da criação do campeonato ou da importação do CTAD).
async function salvarInversaoChaves() {
  if (!campAtual) { logMsg("campeonato: crie/selecione um campeonato", "l-aviso", "log-operador"); return; }
  const inv = document.getElementById("camp-chave-inv").checked ? 1 : 0;
  const r = await api(`campeonatos/${campAtual}/chaves?inverter_bateria=${inv}`, "POST");
  if (r && r.ok !== false) {
    logMsg(`inversão da bateria seguinte: ${inv ? "ligada" : "desligada"}`,
           "l-admin", "log-operador");
    renderGrids(r);
  } else {
    logMsg(`campeonato: ${r && r.erro ? r.erro : "erro ao salvar a inversão"}`,
           "l-erro", "log-operador");
    carregarGrids();
  }
}

function renderBaterias(baterias) {
  const el = document.getElementById("baterias-lista");
  if (!baterias.length) { el.innerHTML = '<p class="hint">nenhuma bateria — clique em "Gerar heats &amp; finais"</p>'; return; }
  el.innerHTML = baterias.map(b => {
    const ok = b.espectro.ok;
    const status = ok ? "LIBERADA" : `BLOQUEADA — ${b.espectro.conflitos.length} conflito(s)`;
    const conflitos = b.espectro.conflitos.map(c =>
      `<li>${c.pilotos[0]} × ${c.pilotos[1]} — ${c.tipo} (${c.valor})</li>`).join("");
    return `<div class="card" id="bat-${b.id}" style="margin-bottom:10px">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px">
        <b style="color:#fff">${b.nome}</b>
        <span class="pill ${ok ? "ok" : "err"}">${status}</span>
      </div>
      <div style="font-size:12.5px; color:var(--text-muted)">${(b.pilotos || []).map(p => p.nome).join(" · ") || "—"}</div>
      ${conflitos ? `<ul class="lista-conflitos">${conflitos}</ul>` : ""}
      <div class="acoes" style="margin-top:10px">
        <button onclick="lancarResultado(${b.id})">📤 Lançar resultado da sessão atual</button>
      </div>
    </div>`;
  }).join("");
}

// ---------------------------------------------------------------- central de voltas
let sessoesCache = [];
let sessaoAberta = null;

async function carregarHistorico() {
  const r = await api("historico", "GET");
  sessoesCache = r.sessoes || [];
  document.getElementById("total-sessoes").textContent = sessoesCache.length;
  filtrarSessoes();
}

function filtrarSessoes() {
  const q = (document.getElementById("busca-sessao").value || "").toLowerCase();
  const lista = sessoesCache.filter(s =>
    !q || `${s.tipo} ${s.estado} ${s.inicio || ""}`.toLowerCase().includes(q));
  document.getElementById("lista-sessoes").innerHTML = lista.map(s => {
    const quando = s.inicio ? new Date(s.inicio).toLocaleString("pt-BR",
      { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—";
    return `<div class="item-sessao ${sessaoAberta === s.id ? "on" : ""}"
                 onclick="abrirSessao('${s.id}')">
      <div class="t">${s.tipo} · ${quando}${s.simulacao ? ' <span class="pill novo" title="teste/desenvolvimento — não oficial">simulação</span>' : ""}</div>
      <div class="m">${s.voltas} voltas · ${s.pilotos} piloto(s) · melhor ${s.melhor_s ?? "—"}s</div>
    </div>`;
  }).join("") || '<p class="hint">nenhuma sessão encontrada</p>';
}

async function abrirSessao(id) {
  const d = await api(`historico/${id}`, "GET");
  if (!d.ok) { logMsg(`histórico: ${d.erro}`, "l-erro", "log-operador"); return; }
  sessaoAberta = id;
  const acoes = document.getElementById("acoes-sessao");
  if (acoes) {
    acoes.style.display = "flex";
    // sessão de simulação não vai ao CTAD — esconde o botão de envio
    const btnEnv = acoes.querySelector('button[onclick="enviarSessaoCTAD()"]');
    if (btnEnv) btnEnv.hidden = !!d.simulacao;
  }
  filtrarSessoes();
  renderTabelaHistorico(d);
}

async function enviarSessaoCTAD() {
  if (!sessaoAberta) return;
  const s = sessoesCache.find(x => x.id === sessaoAberta);
  if (s && s.simulacao) {
    alert("Sessão de SIMULAÇÃO — só para testes/desenvolvimento.\n\n" +
          "Resultado não oficial: não vai ao CTAD.");
    return;
  }
  const resumo = s ? `${s.tipo} · ${s.voltas} voltas · ${s.pilotos} piloto(s)`
                   : sessaoAberta.slice(0, 8);
  if (!confirm(`Enviar esta sessão ao CTAD?\n\n${resumo}\n\nEla ficará visível no site do CTAD ` +
               `(pode ser apagada por lá depois).`)) return;
  const r = await api(`sync/enviar?sessao_id=${encodeURIComponent(sessaoAberta)}`);
  if (r.ok) {
    logMsg(`CTAD: ${r.batKey} → enviados ${r.enviados}, duplicados ${r.duplicados}, falhas ${r.falhas}`,
           "l-sistema", "log-operador");
    alert(`Enviado ao CTAD!\n\nenviados: ${r.enviados}\nduplicados: ${r.duplicados}\n` +
          `falhas: ${r.falhas}\n\nchave: ${r.batKey}`);
  } else {
    alert(`Falha no envio: ${r.erro}`);
  }
}

function renderTabelaHistorico(d) {
  const maxV = d.max_voltas;
  document.getElementById("detalhe-titulo").textContent =
    `Voltas volta a volta — ${d.pilotos.length} piloto(s), ${maxV} voltas` +
    (d.simulacao ? " · SIMULAÇÃO (teste — não oficial)" : "");

  // tempos acumulados e líder de cada volta
  const acum = {};
  d.pilotos.forEach(p => {
    let acc = 0;
    acum[p.nome] = p.voltas.map(v => { acc += v.tempo; return acc; });
  });
  const liderPorVolta = {};
  for (let n = 1; n <= maxV; n++) {
    let melhor = null, nome = null;
    d.pilotos.forEach(p => {
      if (p.voltas.length >= n) {
        const a = acum[p.nome][n - 1];
        if (melhor === null || a < melhor) { melhor = a; nome = p.nome; }
      }
    });
    liderPorVolta[n] = { nome: nome, total: melhor };
  }

  const cab = `<tr><th>Pos</th><th>Piloto</th>` +
    Array.from({ length: maxV }, (_, i) => `<th>V${i + 1}</th>`).join("") + "</tr>";
  const linhas = d.pilotos.map((p, idx) => {
    const cels = p.voltas.map((v, i) => {
      const n = i + 1;
      const lider = liderPorVolta[n];
      const gap = (lider && lider.total != null) ? acum[p.nome][i] - lider.total : 0;
      const cls = v.tempo === d.melhor_geral ? "cel-melhor" : (v.recorde ? "cel-recorde" : "");
      const gapTxt = gap > 0.001 ? `<span class="gap-mini">+${gap.toFixed(3)}s</span>` : "";
      return `<td><span class="cel-volta ${cls}">${v.tempo.toFixed(3)}</span>${gapTxt}</td>`;
    }).join("");
    const vazias = Array.from({ length: maxV - p.voltas.length },
      () => "<td>—</td>").join("");
    return `<tr class="${idx === 0 ? "pos1" : ""}">
      <td>${idx + 1}º${idx === 0 ? '<span class="badge lider">líder</span>' : ""}</td>
      <td>${p.nome}</td>${cels}${vazias}</tr>`;
  }).join("");
  document.getElementById("tabela-historico").innerHTML = cab + linhas;
  document.getElementById("detalhe-legenda").innerHTML =
    '<span class="cel-volta cel-melhor">x.xxx</span> melhor volta da sessão · ' +
    '<span class="cel-volta cel-recorde">x.xxx</span> recorde do piloto · ' +
    '+x,xxxs = diferença acumulada para o líder naquela volta';
}

// ---------------------------------------------------------------- admin
// ---------------------------------------------------------------- pilotos (Admin)
let pilotosCache = [];
let pilotoEditando = null;

function _esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function carregarPilotos() {
  const r = await api("pilotos", "GET");
  pilotosCache = r.pilotos || [];
  const n = pilotosCache.length;
  const ativos = pilotosCache.filter(p => p.ativo).length;
  const transp = pilotosCache.reduce((s, p) => s + ((p.transponders || []).length), 0);
  const txt = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
  txt("pil-total", n);
  txt("pil-ativos", ativos);
  txt("pil-inativos", n - ativos);
  txt("pil-transp-n", transp);
  txt("pil-lista-n", n);
  try {
    const st = await api("sync/status", "GET");
    txt("pil-pista", st.pistaId || "—");
  } catch (e) { /* opcional */ }
  renderPilotos();
}

function renderPilotos() {
  const q = (document.getElementById("pil-busca")?.value || "").toLowerCase().trim();
  const lista = pilotosCache.filter(p =>
    !q || `${p.nome} ${p.apelido || ""} ${p.fonia || ""} ${p.telefone || ""} ${(p.funcoes || []).join(" ")} ${(p.transponders || []).join(" ")}`
      .toLowerCase().includes(q));
  const FUNC = { superuser: "superuser", admin: "admin", gestor: "gestor" };
  const linhas = lista.map(p => {
    const funcoes = (p.funcoes || []).filter(f => FUNC[f]);
    return `
    <tr class="${p.ativo ? "" : "linha-inativa"}" data-piloto="${p.id}">
      <td><b>${_esc(p.nome)}</b></td>
      <td>${p.apelido ? _esc(p.apelido) : "—"}</td>
      <td>${p.fonia ? `🔊 ${_esc(p.fonia)}` : "—"}</td>
      <td>${p.telefone ? _esc(p.telefone) : "—"}</td>
      <td>${funcoes.length ? funcoes.map(f => `<span class="pill novo">${f}</span>`).join(" ") : "—"}</td>
      <td>${(p.transponders || []).length ? p.transponders.join(", ") : "—"}</td>
      <td>${p.ativo ? '<span class="pill ok">ativo</span>'
                    : '<span class="pill novo">inativo</span>'}</td>
      <td>
        <button class="btn-mini" onclick="editarPiloto(${p.id})">✏️ Editar</button>
        <button class="btn-mini perigo" onclick="excluirPiloto(${p.id})">🗑 Excluir</button>
      </td>
    </tr>`; }).join("");
  document.getElementById("tabela-pilotos").innerHTML =
    "<tr><th>Nome</th><th>Apelido</th><th>Fonia</th><th>Telefone</th><th>Funções</th><th>Transponder(s)</th><th>Status</th><th>Ações</th></tr>" +
    (linhas || '<tr><td colspan="8" style="color:var(--text-muted)">nenhum piloto encontrado</td></tr>');
}

function novoPiloto() {
  pilotoEditando = null;
  document.getElementById("piloto-form-tit").textContent = "Novo piloto";
  document.getElementById("pil-nome").value = "";
  document.getElementById("pil-apelido").value = "";
  document.getElementById("pil-fonia").value = "";
  document.getElementById("pil-telefone").value = "";
  document.getElementById("pil-funcoes").value = "";
  document.getElementById("pil-transponders").value = "";
  document.getElementById("pil-ativo").value = "1";
}

function editarPiloto(id) {
  const p = pilotosCache.find(x => x.id === id);
  if (!p) return;
  pilotoEditando = id;
  document.getElementById("piloto-form-tit").textContent = `Editar piloto — ${p.nome}`;
  document.getElementById("pil-nome").value = p.nome;
  document.getElementById("pil-apelido").value = p.apelido || "";
  document.getElementById("pil-fonia").value = p.fonia || "";
  document.getElementById("pil-telefone").value = p.telefone || "";
  document.getElementById("pil-funcoes").value = ((p.funcoes || [])[0]) || "";
  document.getElementById("pil-transponders").value = (p.transponders || []).join(", ");
  document.getElementById("pil-ativo").value = p.ativo ? "1" : "0";
  document.getElementById("pil-nome").focus();
}

async function salvarPiloto() {
  const nome = document.getElementById("pil-nome").value.trim();
  if (!nome) { alert("Informe o nome do piloto."); return; }
  const apelido = document.getElementById("pil-apelido").value.trim();
  const fonia = document.getElementById("pil-fonia").value.trim();
  const telefone = document.getElementById("pil-telefone").value.trim();
  const funcoes = document.getElementById("pil-funcoes").value;
  const transp = document.getElementById("pil-transponders").value.trim();
  const ativo = document.getElementById("pil-ativo").value === "1";
  const params = `nome=${encodeURIComponent(nome)}&apelido=${encodeURIComponent(apelido)}` +
    `&fonia=${encodeURIComponent(fonia)}&telefone=${encodeURIComponent(telefone)}` +
    `&funcoes=${encodeURIComponent(funcoes)}&transponders=${encodeURIComponent(transp)}`;
  const r = pilotoEditando
    ? await api(`pilotos/editar?piloto_id=${pilotoEditando}&ativo=${ativo}&${params}`)
    : await api(`pilotos/criar?${params}`);
  if (r.ok) {
    logMsg(`piloto salvo: ${nome}`, "l-sistema", "log-operador");
    novoPiloto();
    carregarPilotos();
  } else {
    alert(`Não foi possível salvar: ${r.erro || "erro"}`);
  }
}

// ---------------------------------------------------------------- sincronia de pilotos (CTAD)
function _syncPlStatus(txt, cor) {
  const el = document.getElementById("sync-pl-status");
  if (el) { el.textContent = txt; el.style.color = cor || "var(--text-muted)"; }
}

function _escTxt(s) { return String(s == null ? "" : s); }

function _renderSyncPilotos(r) {
  const el = document.getElementById("sync-pl-resultado");
  if (!el) return;
  if (!r || r.ok === false) {
    el.innerHTML = `<p class="hint" style="color:var(--accent-red)">${_escTxt(r && r.erro || "falha ao consultar o CTAD")}</p>`;
    return;
  }
  const vinculo = v => v === "telefone" ? "chave primária"
    : v === "nome-adotou-telefone" ? "adotou o telefone"
    : v === "nome" ? "por nome (site sem telefone)" : "";
  const linhas = [];
  (r.novos || []).forEach(n =>
    linhas.push(`<tr><td><b>${_esc(n.nome)}</b></td><td>${_esc(n.apelido || "—")}</td>
      <td><b>${_esc(n.telefone || "—")}</b></td>
      <td><span class="pill ${r.preview ? "novo" : "ok"}">${r.preview ? "será criado" : "criado"}</span></td></tr>`));
  (r.adotados || []).forEach(a =>
    linhas.push(`<tr><td><b>${_esc(a.nome)}</b></td><td>${_esc(a.apelido || "—")}</td>
      <td><b>${_esc(a.telefone)}</b></td>
      <td><span class="pill ${r.preview ? "novo" : "ok"}">adota a chave primária</span></td></tr>`));
  (r.atualizados || []).forEach(a =>
    linhas.push(`<tr><td><b>${_esc(a.nome)}</b></td><td>${_esc(a.apelido || "—")}</td>
      <td><b>${_esc(a.telefone || "—")}</b></td>
      <td><span class="pill novo">atualiza ${(a.campos || []).join(", ")}</span>
          <span class="hint" style="display:block">${vinculo(a.vinculado_por)}</span></td></tr>`));
  (r.conflitos || []).forEach(c =>
    linhas.push(`<tr><td><b>${_esc(c.piloto)}</b></td><td colspan="2"></td>
      <td><span class="pill erro">${_esc(c.motivo)}</span></td></tr>`));

  const resumo = `${r.remotos} no site · <b style="color:var(--accent-green)">${(r.novos || []).length} novos</b>`
    + (r.adotados && r.adotados.length
        ? ` · <b style="color:var(--accent-green)">${r.adotados.length} adotou a chave primária</b>` : "")
    + ` · <b style="color:var(--accent-gold)">${(r.atualizados || []).length} a atualizar</b> · `
    + `${r.iguais} já iguais`
    + ((r.conflitos || []).length ? ` · <b style="color:var(--accent-red)">${r.conflitos.length} conflito(s)</b>` : "");

  el.innerHTML = `
    <div class="admin-secao-tit">${r.preview ? "Prévia" : "Resultado"} — pilotos do CTAD</div>
    <p class="hint">${resumo}</p>
    <div class="tabela-wrap"><table class="admin-tabela">
      <tr><th>Piloto</th><th>Apelido</th><th>Telefone (chave primária)</th><th>Ação</th></tr>
      ${linhas.join("") || '<tr><td colspan="4" style="color:var(--text-muted)">nada a fazer</td></tr>'}
    </table></div>
    ${r.preview && (linhas.length) ? `<div class="acoes" style="margin-top:12px">
      <button class="destaque" onclick="importarPilotosSite(true)">⬇ Confirmar importação</button></div>` : ""}`;
}

async function previaPilotosSite() {
  _syncPlStatus("consultando o CTAD…", "var(--accent-blue)");
  let r;
  try { r = await api("sync/pilotos?previa=true", "GET"); }
  catch (e) { _syncPlStatus("falha de conexão", "var(--accent-red)"); return; }
  if (r && r.ok === false) { _syncPlStatus(r.erro, "var(--accent-red)"); _renderSyncPilotos(r); return; }
  _syncPlStatus(`prévia: ${(r.novos || []).length} novo(s)`, "var(--accent-gold)");
  logMsg(`sync/pilotos: prévia do site — ${r.remotos} pilotos`, "l-sistema", "log-operador");
  _renderSyncPilotos(r);
}

async function importarPilotosSite(confirmado) {
  if (!confirmado && !confirm("Importar os pilotos do CTAD para o KChrono?\n\n"
    + "Fonia, funções e transponders locais NÃO são alterados.")) return;
  _syncPlStatus("importando…", "var(--accent-blue)");
  let r;
  try { r = await api("sync/pilotos?previa=false", "GET"); }
  catch (e) { _syncPlStatus("falha de conexão", "var(--accent-red)"); return; }
  if (r && r.ok === false) { _syncPlStatus(r.erro, "var(--accent-red)"); _renderSyncPilotos(r); return; }
  _syncPlStatus(`importado: ${(r.novos || []).length} novo(s)`, "var(--accent-green)");
  logMsg(`sync/pilotos: ${(r.novos || []).length} criados, `
    + `${(r.atualizados || []).length} atualizados do CTAD`, "l-sistema", "log-operador");
  _renderSyncPilotos(r);
  carregarPilotos();
}

async function exportarPilotoSite() {
  if (pilotoEditando == null) {
    alert("Selecione um piloto na lista (botão ✏️ Editar) para enviá-lo ao site.");
    return;
  }
  const p = pilotosCache.find(x => x.id === pilotoEditando);
  if (!p) return;
  if (!confirm(`Criar "${p.nome}" no cadastro do CTAD?\n\n`
    + "Se o piloto já existir lá, nada é alterado.")) return;
  _syncPlStatus("enviando…", "var(--accent-blue)");
  const r = await api(`sync/pilotos/exportar?piloto_id=${pilotoEditando}`);
  if (r && r.ok === false) {
    _syncPlStatus(r.erro, "var(--accent-red)");
    logMsg(`sync/pilotos: ${r.erro}`, "l-erro", "log-operador");
    return;
  }
  _syncPlStatus(r.criado ? `criado: ${r.nome}` : "já existia no site", "var(--accent-green)");
  logMsg(`sync/pilotos: ${r.msg || r.nome}`, "l-sistema", "log-operador");
}

function carregarCamposSyncCamp() {
  const sel = document.getElementById("sync-camp-local");
  if (!sel) return;
  const lista = (campAtual ? [campAtual] : []);
  // usa a lista completa de campeonatos (camp-select) quando disponível
  const options = [];
  const selAll = document.getElementById("camp-select");
  if (selAll) {
    options.push(...Array.from(selAll.options)
      .filter(o => o.value)
      .map(o => `<option value="${o.value}">${_escTxt(o.textContent)}</option>`));
  } else {
    options.push(...lista.map(id => `<option value="${id}">#${id}</option>`));
  }
  sel.innerHTML = options.join("") || '<option value="">— nenhum campeonato —</option>';
  if (campAtual) sel.value = String(campAtual);
}

function _renderSyncCamp(r) {
  const el = document.getElementById("sync-pl-resultado");
  if (!el) return;
  if (!r || r.ok === false) {
    el.innerHTML = `<p class="hint" style="color:var(--accent-red)">${_escTxt(r && r.erro || "falha ao consultar o CTAD")}</p>`;
    return;
  }
  const cfg = r.config_aplicada || {};
  const ROT = { pilotos_por_chave: "máx. por chave", numero_provas: "nº de provas",
                inverter_bateria: "inverter bateria", pontuacao_tabela: "tabela de pontos" };
  const cfgLinhas = Object.keys(cfg).map(k =>
    `<tr><td>${ROT[k] || k}</td><td>${_escTxt(Array.isArray(cfg[k]) ? cfg[k].join(", ") : cfg[k])}</td></tr>`).join("");
  const insc = (r.a_inscrever || []).map(i => `<li>${_esc(i.nome)}</li>`).join("");
  el.innerHTML = `
    <div class="admin-secao-tit">${r.preview ? "Prévia" : "Resultado"} — campeonato do CTAD</div>
    <p class="hint">Campeonato <b>${_esc(r.campeonato)}</b> · ${r.inscritos_site} inscrito(s) no site ·
      ${r.inscritos_agora} no KChrono ${r.pilotos_criados && r.pilotos_criados.length
        ? ` · ${r.pilotos_criados.length} piloto(s) criado(s)` : ""}.</p>
    ${cfgLinhas ? `<div class="tabela-wrap"><table class="admin-tabela">
      <tr><th>Configuração</th><th>Valor vindo do site</th></tr>${cfgLinhas}</table></div>`
      : '<p class="hint">Configuração já estava igual à do site.</p>'}
    ${insc ? `<p class="hint" style="margin-top:8px">A inscrever:</p><ul style="margin:0 0 0 18px">${insc}</ul>` : ""}
    ${r.preview ? `<div class="acoes" style="margin-top:12px">
      <button class="destaque" onclick="importarCampeonatoSite(true)">⬇ Confirmar importação</button></div>` : ""}`;
}

async function previaCampeonatoSite() {
  const cid = document.getElementById("sync-camp-local").value;
  const chave = document.getElementById("sync-camp-chave").value.trim();
  if (!cid || !chave) { alert("Informe o campeonato local e a chave no CTAD."); return; }
  _syncPlStatus("consultando…", "var(--accent-blue)");
  let r;
  try { r = await api(`sync/campeonatos/${cid}/importar?chave=${encodeURIComponent(chave)}&previa=true`); }
  catch (e) { _syncPlStatus("falha de conexão", "var(--accent-red)"); return; }
  _syncPlStatus(r.ok === false ? r.erro : "prévia pronta",
                r.ok === false ? "var(--accent-red)" : "var(--accent-gold)");
  _renderSyncCamp(r);
}

async function importarCampeonatoSite(confirmado) {
  const cid = document.getElementById("sync-camp-local").value;
  const chave = document.getElementById("sync-camp-chave").value.trim();
  if (!cid || !chave) { alert("Informe o campeonato local e a chave no CTAD."); return; }
  if (!confirmado && !confirm(`Importar configuração e inscritos de "${chave}"?\n\n`
    + "O limite de pilotos por chave será alinhado com o do site.")) return;
  _syncPlStatus("importando…", "var(--accent-blue)");
  let r;
  try { r = await api(`sync/campeonatos/${cid}/importar?chave=${encodeURIComponent(chave)}&previa=false`); }
  catch (e) { _syncPlStatus("falha de conexão", "var(--accent-red)"); return; }
  if (r && r.ok === false) {
    _syncPlStatus(r.erro, "var(--accent-red)");
    _renderSyncCamp(r);
    return;
  }
  _syncPlStatus("campeonato importado", "var(--accent-green)");
  logMsg(`sync/campeonato: "${chave}" importado — `
    + `${(r.a_inscrever || []).length} inscrito(s)`, "l-sistema", "log-operador");
  _renderSyncCamp(r);
  carregarCampeonatos();
  abrirCampeonato();
}

async function excluirPiloto(id) {
  const p = pilotosCache.find(x => x.id === id);
  const nome = p ? p.nome : `#${id}`;
  if (!confirm(`Excluir o piloto "${nome}"?\n\nSe ele tiver voltas no histórico, será inativado ` +
               `(não some das provas antigas).`)) return;
  const r = await api(`pilotos/${id}`, "DELETE");
  if (r.ok) {
    logMsg(`piloto ${nome}: ${r.msg}`, "l-sistema", "log-operador");
    carregarPilotos();
  } else {
    alert(`Não foi possível excluir: ${r.erro || "erro"}`);
  }
}

// ---------------------------------------------------------------- voz & som (Admin)
function rotuloVolume() {
  const el = document.getElementById("som-volume");
  const txt = document.getElementById("som-volume-txt");
  if (el && txt) txt.textContent = `${el.value}%`;
}

function rotuloVelocidade() {
  const el = document.getElementById("som-velocidade");
  const txt = document.getElementById("som-velocidade-txt");
  if (el && txt) txt.textContent = `${el.value} ppm`;
}

function ajustesSom() {
  return {
    volume: parseInt(document.getElementById("som-volume").value, 10) / 100,
    velocidade: parseInt(document.getElementById("som-velocidade").value, 10),
    voz: document.getElementById("som-voz").value || null,
  };
}

function atualizarVozes() {
  carregarSom();
  logMsg("lista de vozes atualizada", "l-sistema", "log-operador");
}

async function baixarVozNeural() {
  const btn = document.getElementById("som-baixar-voz");
  const st = document.getElementById("som-voz-status");
  let livres = [];
  try {
    const r = await api("vozes", "GET");
    livres = (r.modelos || []).filter(m => !m.instalado);
  } catch (e) {}
  if (!livres.length) { carregarSom(); return; }
  const alvo = livres[0].id;
  const rotulo = livres[0].rotulo;
  if (!confirm("Baixar a voz neural " + rotulo + "?\n\n" +
      "O download acontece uma unica vez e depois o locutor funciona " +
      "offline, sem internet na pista.")) return;
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = "baixando... (pode levar alguns minutos)";
  if (st) st.textContent = "baixando " + alvo + "...";
  try {
    const r = await api("vozes/instalar?modelo=" + encodeURIComponent(alvo),
                        "POST", "", "");
    if (r.ok) {
      logMsg("voz neural instalada: " + r.modelo, "l-admin", "log-operador");
      alert("Voz neural '" + r.modelo + "' instalada e em uso.\n\n" +
            "Clique em Testar voz para ouvir.");
    } else {
      logMsg("voz neural: " + (r.erro || "falha no download"), "l-erro", "log-operador");
      alert("Nao foi possivel baixar: " + (r.erro || "erro"));
    }
  } catch (e) {
    logMsg("voz neural: " + e, "l-erro", "log-operador");
    alert("Falha ao baixar: " + e);
  }
  btn.disabled = false;
  btn.textContent = original;
  carregarSom();
}

async function carregarSom() {
  const r = await api("som", "GET");
  const sel = document.getElementById("som-voz");
  sel.innerHTML = "";
  const vozes = r.vozes || [];
  if (vozes.length) {
    vozes.forEach(v => {
      const o = document.createElement("option");
      o.value = v.id;
      // 🧠 marca as vozes neurais offline (Piper)
      o.textContent = (v.fonte === "piper" ? "🧠 " : "") +
        `${v.nome}${v.idiomas ? ` (${v.idiomas})` : ""}`;
      if (v.id === r.voz_id) o.selected = true;
      sel.appendChild(o);
    });
  } else {
    sel.innerHTML = '<option value="">— nenhuma voz (instale pyttsx3) —</option>';
  }
  document.getElementById("som-volume").value = Math.round((r.volume ?? 0.9) * 100);
  document.getElementById("som-velocidade").value = r.velocidade ?? 180;
  rotuloVolume();
  rotuloVelocidade();
  const st = document.getElementById("som-status");
  const nomeBackend = { piper: "neural offline (Piper)", sapi: "SAPI do Windows",
                         log: "modo log/bipes" }[r.backend] || r.backend || "—";
  st.textContent = r.tts_ativo ? `TTS ativo — ${nomeBackend}` : "TTS indisponível (modo log/bipes)";
  const nPiper = vozes.filter(v => v.fonte === "piper").length;
  const ptbr = vozes.filter(v => (v.idiomas || "").toLowerCase().startsWith("pt")).length;
  st.textContent += nPiper ? ` · ${nPiper} voz(es) neural(is)` : "";
  st.textContent += ptbr ? ` · ${ptbr} voz(es) pt-BR` : "";
  st.style.color = r.tts_ativo
    ? (r.backend === "piper" ? "var(--accent-green)" : "var(--accent-gold)")
    : "var(--accent-red)";
  // dica sobre a voz escolhida + estado do download
  const dica = document.getElementById("som-voz-dica");
  if (dica) {
    const atual = vozes.find(v => v.id === r.voz_id);
    dica.innerHTML = atual && atual.fonte === "piper"
      ? "A voz <b>neural</b> roda offline, direto no computador — sem internet na pista."
      : "As vozes SAPI/OneCore soam mais “robotizadas”. Instale uma voz <b>neural</b> (🧠) para ter entonação.";
  }
  const bs = document.getElementById("som-voz-status");
  const bb = document.getElementById("som-baixar-voz");
  if (r.piper_disponivel) {
    if (bs) bs.innerHTML = nPiper
      ? `${nPiper} modelo(s) neural(is) em <code>dados/vozes</code>.`
      : "Nenhum modelo neural instalado — baixe um para ter voz natural (≈60 MB).";
    if (bb) bb.style.display = nPiper ? "none" : "";
  } else {
    if (bs) bs.innerHTML = "Para usar voz neural, instale o pacote <code>piper-tts</code> (requirements.txt).";
    if (bb) bb.style.display = "none";
  }
  const op = r.opcoes || {};
  document.getElementById("som-intervalo").value = op.intervalo_posicoes ?? 0;
  document.getElementById("som-a-cada-voltas").value = op.anunciar_a_cada_voltas ?? 0;
  document.getElementById("som-topo").value = op.posicoes_topo ?? 3;
  document.getElementById("som-anunciar-volta").checked = !!op.anunciar_volta;
  document.getElementById("som-anunciar-rec-pessoal").checked =
    op.anunciar_recorde_pessoal !== false;
  document.getElementById("som-anunciar-rec-pista").checked =
    op.anunciar_recorde_pista !== false;
  document.getElementById("som-passagem").checked = op.som_passagem !== false;
  document.getElementById("som-lider").checked = op.som_lider !== false;
  document.getElementById("som-menor-volta").checked = op.som_menor_volta !== false;
  document.getElementById("bip-luz").checked = op.bip_luz !== false;
  document.getElementById("bip-vai").checked = op.bip_vai !== false;
  // anúncio de posições por tipo de sessão (durante/depois)
  document.getElementById("som-pos-class-durante").checked =
    op.anunciar_posicoes_classificacao_durante !== false;
  document.getElementById("som-pos-class-depois").checked =
    op.anunciar_posicoes_classificacao_depois === true;
  document.getElementById("som-pos-corrida-durante").checked =
    op.anunciar_posicoes_corrida_durante !== false;
  document.getElementById("som-pos-corrida-depois").checked =
    op.anunciar_posicoes_corrida_depois === true;
  carregarVozContagem();   // checkbox "voz na contagem" mora nesta seção agora
  const audios = {};
  (r.audios || []).forEach(a => { audios[a.chave] = a.arquivo; });
  document.getElementById("som-frases").innerHTML = (r.frases || []).map(f => {
    const temAudio = !!audios[f.chave];
    const tag = temAudio
      ? `<span class="audio-tag" title="áudio: ${_esc(audios[f.chave])}">🎵 ${_esc(audios[f.chave])}
           <button class="btn-mini" onclick="removerAudio('${f.chave}')" title="remover áudio">✕</button></span>`
      : "";
    return `
    <div class="frase-input">
      <label class="chk-linha" title="ativar/desativar este som">
        <input type="checkbox" class="frase-hab" data-chave="${f.chave}"
               ${f.habilitado !== false ? "checked" : ""}></label>
      <span class="rot">${_esc(f.rotulo)}${temAudio ? " 🔊" : ""}</span>
      <input id="frase-${f.chave}" value="${_esc(f.texto)}">
      <button class="btn-mini" onclick="ouvirFrase('${f.chave}')">▶ Ouvir</button>
      <button class="btn-mini" onclick="escolherAudio('${f.chave}')"
              title="usar um áudio no lugar desta frase">📁 Áudio</button>
      ${tag}
    </div>`;
  }).join("");
}

async function escolherAudio(chave) {
  const inp = document.createElement("input");
  inp.type = "file";
  inp.accept = "audio/*,.wav,.mp3,.ogg,.m4a,.wma,.aac,.flac";
  inp.onchange = async () => {
    const arq = inp.files && inp.files[0];
    if (!arq) return;
    const url = `/api/som/audio?chave=${encodeURIComponent(chave)}` +
      `&nome=${encodeURIComponent(arq.name)}`;
    try {
      const resp = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": arq.type || "application/octet-stream" },
        body: arq,
      });
      const r = await resp.json();
      if (r.ok) {
        logMsg(`áudio definido para "${chave}" (${r.arquivo})`, "l-sistema", "log-operador");
        carregarSom();
      } else {
        alert(`Não foi possível enviar o áudio: ${r.erro || "erro"}`);
      }
    } catch (e) {
      alert(`Falha no envio do áudio: ${e}`);
    }
  };
  inp.click();
}

async function removerAudio(chave) {
  const r = await api(`som/audio?chave=${encodeURIComponent(chave)}`, "DELETE");
  if (r.ok) {
    logMsg(`áudio removido de "${chave}"`, "l-sistema", "log-operador");
    carregarSom();
  } else {
    alert(r.erro || "erro ao remover o áudio");
  }
}

async function ouvirFrase(chave) {
  const el = document.getElementById(`frase-${chave}`);
  const texto = el ? el.value : "";
  if (!texto.trim()) { alert("A frase está vazia."); return; }
  const r = await api("som/ouvir", "POST", "", { texto, chave, ...ajustesSom() });
  const prev = document.getElementById("som-preview");
  if (r.ok) {
    if (prev) prev.innerHTML = `🔊 <b>${_esc(r.texto)}</b>`;
    if (!r.tts_ativo)
      logMsg("TTS indisponível — a frase foi enviada ao log.", "l-sistema", "log-operador");
  } else {
    alert(`Não foi possível ouvir: ${r.erro || "erro"}`);
  }
}

async function testarVoz() {
  const r = await api("som/ouvir", "POST", "", {
    texto: "Atenção pilotos, preparem-se para a largada!",
    ...ajustesSom(),
  });
  const prev = document.getElementById("som-preview");
  if (r.ok && prev) prev.innerHTML = `🔊 Teste de voz — <b>${_esc(r.texto)}</b>`;
}

async function testarSomPassagem() {
  const r = await api("som/testar_passagem", "POST");
  if (r.ok) {
    logMsg("Teste do bip de passagem executado", "l-sistema", "log-operador");
  } else {
    alert("Não foi possível testar: " + (r.erro || "erro"));
  }
}

async function testarSomLider() {
  const r = await api("som/testar_lider", "POST");
  if (r.ok) {
    logMsg("Teste do bip do líder executado", "l-sistema", "log-operador");
  } else {
    alert("Não foi possível testar: " + (r.erro || "erro"));
  }
}

async function testarMenorVolta() {
  const r = await api("som/testar_menor_volta", "POST");
  if (r.ok) logMsg("Teste do bip da menor volta executado", "l-sistema", "log-operador");
  else alert("Não foi possível testar: " + (r.erro || "erro"));
}

async function testarBipLuz() {
  const r = await api("som/testar_luz", "POST");
  if (r.ok) logMsg("Teste do bipe da luz executado", "l-sistema", "log-operador");
  else alert("Não foi possível testar: " + (r.erro || "erro"));
}

async function testarBipVai() {
  const r = await api("som/testar_vai", "POST");
  if (r.ok) logMsg("Teste do bipe do verde executado", "l-sistema", "log-operador");
  else alert("Não foi possível testar: " + (r.erro || "erro"));
}

async function salvarSom() {
  const frases = {};
  document.querySelectorAll("#som-frases input[id^='frase-']").forEach(inp => {
    frases[inp.id.replace("frase-", "")] = inp.value;
  });
  const habilitados = {};
  document.querySelectorAll("#som-frases .frase-hab").forEach(cb => {
    habilitados[cb.getAttribute("data-chave")] = cb.checked;
  });
  const opcoes = {
    intervalo_posicoes: parseInt(document.getElementById("som-intervalo").value, 10) || 0,
    anunciar_a_cada_voltas: parseInt(document.getElementById("som-a-cada-voltas").value, 10) || 0,
    posicoes_topo: parseInt(document.getElementById("som-topo").value, 10) || 3,
    anunciar_volta: document.getElementById("som-anunciar-volta").checked,
    anunciar_recorde_pessoal: document.getElementById("som-anunciar-rec-pessoal").checked,
    anunciar_recorde_pista: document.getElementById("som-anunciar-rec-pista").checked,
    som_passagem: document.getElementById("som-passagem").checked,
    som_lider: document.getElementById("som-lider").checked,
    som_menor_volta: document.getElementById("som-menor-volta").checked,
    bip_luz: document.getElementById("bip-luz").checked,
    bip_vai: document.getElementById("bip-vai").checked,
    anunciar_posicoes_classificacao_durante:
      document.getElementById("som-pos-class-durante").checked,
    anunciar_posicoes_classificacao_depois:
      document.getElementById("som-pos-class-depois").checked,
    anunciar_posicoes_corrida_durante:
      document.getElementById("som-pos-corrida-durante").checked,
    anunciar_posicoes_corrida_depois:
      document.getElementById("som-pos-corrida-depois").checked,
  };
  const r = await api("som/salvar", "POST", "", { frases, habilitados, ...ajustesSom(), ...opcoes });
  if (r.ok) {
    logMsg("preferências de voz/som salvas", "l-sistema", "log-operador");
  } else {
    alert(`Não foi possível salvar: ${r.erro || "erro"}`);
  }
}

async function anunciarPosicoes() {
  const r = await api("som/anunciar");
  if (r.ok) logMsg(`posições anunciadas (${r.pilotadas})`, "l-sistema", "log-operador");
  else alert(r.erro || "nada para anunciar");
}

function adminSecao(btn, id) {
  if (!btn) {
    const nav = Array.from(document.querySelectorAll(".menu nav a"));
    btn = nav.find(a => (a.getAttribute("onclick") || "").includes(`'${id}'`));
  }
  marcarNav(btn);
  mostrar("admin");
  document.querySelectorAll(".admin-sec").forEach(s => s.classList.remove("on"));
  const sec = document.getElementById(id);
  if (sec) sec.classList.add("on");
  adminSecaoAtual = id;
  const titulo = document.getElementById("admin-titulo");
  if (titulo) titulo.textContent = btn ? btn.textContent.replace(/Fase\s*\d+/i, "").trim() : "Admin";
  if (id === "a-config") carregarAparenciaForm();
  if (id === "a-upload") atualizarSync();
  if (id === "a-camp") { carregarCampeonatos(); carregarPlanoCampeonato(); }
  if (id === "a-pilotos") { carregarPilotos(); carregarCamposSyncCamp(); }
  if (id === "a-voz") carregarSom();
  if (id === "a-sobre") verificarVersao();
  if (id === "a-gerente") carregarGerente();
  if (id === "a-relatorio") carregarRelatorioResumo();
  if (id === "a-voltas") carregarHistorico();
  if (id === "a-notificacoes") carregarNotificacoes();
}

// ---------------------------------------------------------------- busca global (topbar)
let buscaTimer = null;
function buscaGlobalDebounce() {
  clearTimeout(buscaTimer);
  buscaTimer = setTimeout(buscaGlobal, 220);
}
async function buscaGlobal() {
  const inp = document.getElementById("busca-global");
  const box = document.getElementById("busca-resultados");
  if (!inp || !box) return;
  const q = inp.value.trim();
  if (!q) { box.classList.remove("on"); box.innerHTML = ""; return; }
  let r = { pilotos: [], sessoes: [], campeonatos: [], baterias: [] };
  try { r = await api(`busca?q=${encodeURIComponent(q)}`, "GET"); } catch (e) {}
  renderBuscaGlobal(q, r);
}
function _secoesAdmin() {
  return Array.from(document.querySelectorAll("#adm-nav a")).map(a => ({
    id: (a.getAttribute("onclick") || "").match(/'(a-[^']+)'/)?.[1],
    titulo: a.textContent.trim(),
    chaves: ((a.getAttribute("data-titulo") || "") + " " + a.textContent).toLowerCase(),
  })).filter(s => s.id);
}
function renderBuscaGlobal(q, r) {
  const box = document.getElementById("busca-resultados");
  if (!box) return;
  const alvo = q.toLowerCase();
  let html = "";
  const acoes = BUSCA_ACOES.filter(a =>
    (`${a.rotulo} ${a.chaves}`).toLowerCase().includes(alvo));
  if (acoes.length) {
    html += '<div class="busca-grupo-tit">Ações</div>' +
      acoes.map(a => `<div class="busca-item" onclick="buscaIr('acao','${a.chave}')">
        ${a.icone} ${_esc(a.rotulo)}</div>`).join("");
  }
  if (r.pilotos && r.pilotos.length) {
    html += '<div class="busca-grupo-tit">Pilotos</div>' +
      r.pilotos.map(p => `<div class="busca-item" onclick="buscaIr('piloto',${p.id})">
        🏎️ ${_esc(p.nome)}<span class="m">${(p.transponders || []).join(", ") || "sem transponder"}</span></div>`).join("");
  }
  if (r.sessoes && r.sessoes.length) {
    html += '<div class="busca-grupo-tit">Sessões</div>' +
      r.sessoes.map(s => `<div class="busca-item" onclick="buscaIr('sessao','${s.id}')">
        🏁 ${_esc(s.rotulo)}<span class="m">${s.voltas} voltas</span></div>`).join("");
  }
  if (r.campeonatos && r.campeonatos.length) {
    html += '<div class="busca-grupo-tit">Campeonatos</div>' +
      r.campeonatos.map(c => `<div class="busca-item" onclick="buscaIr('campeonato',${c.id})">
        🏆 ${_esc(c.nome)}<span class="m">${c.provas} provas</span></div>`).join("");
  }
  if (r.baterias && r.baterias.length) {
    html += '<div class="busca-grupo-tit">Baterias</div>' +
      r.baterias.map(b => `<div class="busca-item" onclick="buscaIr('bateria','${b.campeonato_id}:${b.bateria_id}')">
        🚦 ${_esc(b.nome)}<span class="m">${_esc(b.campeonato)}</span></div>`).join("");
  }
  const sec = _secoesAdmin().filter(s => s.chaves.includes(alvo));
  if (sec.length) {
    html += '<div class="busca-grupo-tit">Configurações</div>' +
      sec.map(s => `<div class="busca-item" onclick="buscaIr('config','${s.id}')">
        ⚙️ ${_esc(s.titulo)}</div>`).join("");
  }
  box.innerHTML = html || `<div class="busca-vazio">nada encontrado para “${_esc(q)}”</div>`;
  box.classList.add("on");
}

// ---------------------------------------------------------------- índice de ações (a busca executa funções)
const BUSCA_ACOES = [
  { chave: "largada", icone: "▶", rotulo: "Largada", chaves: "largar começar correr iniciar prova",
    ir: () => largada() },
  { chave: "pausar", icone: "⏸", rotulo: "Pausar sessão", chaves: "pausar parar congelar",
    ir: () => pausar(true) },
  { chave: "retomar", icone: "⏵", rotulo: "Retomar sessão", chaves: "retomar continuar despausar",
    ir: () => pausar(false) },
  { chave: "finalizar", icone: "⏹", rotulo: "Finalizar sessão", chaves: "finalizar terminar encerrar parar",
    ir: () => finalizar() },
  { chave: "treino", icone: "🏁", rotulo: "Iniciar treino", chaves: "iniciar treino",
    ir: () => iniciarSessao("treino") },
  { chave: "classificacao", icone: "⏱", rotulo: "Iniciar classificação", chaves: "iniciar classificacao qualy tomada tempo",
    ir: () => iniciarSessao("classificacao") },
  { chave: "corrida", icone: "🏆", rotulo: " Preparar para Largada!", chaves: "iniciar corrida final",
    ir: () => iniciarSessao("corrida") },
  { chave: "proxima-etapa", icone: "⏭", rotulo: "Próxima etapa (campeonato)", chaves: "proxima etapa avancar campeonato",
    ir: () => proximaEtapa() },
  { chave: "gerar-qr", icone: "📱", rotulo: "Gerar QR Code de acesso", chaves: "qr qrcode codigo acesso gerente celular senha",
    ir: () => { adminIr("a-gerente"); adminGerarQR(); } },
  { chave: "enviar-sessao", icone: "📤", rotulo: "Enviar sessão ao CTAD", chaves: "enviar sincronizar upload ctad",
    ir: () => enviarSessao() },
  { chave: "processar-fila", icone: "🔄", rotulo: "Processar fila de envio", chaves: "processar fila retry reenviar",
    ir: () => processarFila() },
  { chave: "conectar-decoder", icone: "🔌", rotulo: "Conectar decoder", chaves: "conectar decoder ligar mylaps",
    ir: () => conectarDecoder() },
  { chave: "abrir-telao", icone: "📺", rotulo: "Abrir telão", chaves: "telao tv placar torcida",
    ir: () => abrirTelao() },
];

function buscaIr(tipo, valor) {
  const box = document.getElementById("busca-resultados");
  if (box) box.classList.remove("on");
  if (tipo === "config") { adminIr(valor); return; }
  if (tipo === "sessao") { adminIr("a-voltas"); abrirSessao(valor); return; }
  if (tipo === "campeonato") {
    campSelecionarPendente = String(valor);
    adminIr("a-camp");
    return;
  }
  if (tipo === "bateria") {
    const [cid, bid] = String(valor).split(":");
    adminIr("a-camp");
    const sel = document.getElementById("camp-select");
    if (sel) { sel.value = String(cid); abrirCampeonato(); }
    setTimeout(() => {
      const el = document.getElementById(`bat-${bid}`);
      if (el) { el.scrollIntoView({ block: "center" }); el.style.outline = "2px solid var(--accent-blue)"; setTimeout(() => { el.style.outline = ""; }, 2200); }
    }, 350);
    return;
  }
  if (tipo === "acao") {
    const a = BUSCA_ACOES.find(x => x.chave === String(valor));
    if (a) { try { a.ir(); } catch (e) { alert("não foi possível executar a ação"); } }
    return;
  }
  if (tipo === "piloto") {
    adminIr("a-pilotos");
    const tr = document.querySelector(`#tabela-pilotos tr[data-piloto="${valor}"]`);
    if (tr) { tr.scrollIntoView({ block: "center" }); tr.style.outline = "2px solid var(--accent-blue)"; setTimeout(() => { tr.style.outline = ""; }, 2200); }
  }
}

// ---------------------------------------------------------------- notificações (sino da topbar)
let notifPrefs = { decoder_offline: true, ghost_lap: true, fila_upload: true,
                   recorde: true, navegador: false, som_alerta: true };
let notifLista = [];

async function carregarNotificacoes() {
  try {
    const r = await api("notificacoes", "GET");
    if (r.notificacoes) notifPrefs = r.notificacoes;
  } catch (e) {}
  Object.keys(notifPrefs).forEach(k => {
    const el = document.getElementById("ntf-" + k);
    if (el) el.checked = !!notifPrefs[k];
  });
}
async function salvarNotificacoes() {
  const vals = {};
  Object.keys(notifPrefs).forEach(k => {
    const el = document.getElementById("ntf-" + k);
    vals[k] = el ? el.checked : notifPrefs[k];
  });
  const r = await api("notificacoes", "POST", "", vals);
  if (r.ok) {
    notifPrefs = r.notificacoes;
    logMsg("notificações: preferências salvas", "l-admin", "log-operador");
    notificar("sistema", "Preferências de notificação salvas.", "🔔");
  } else alert(r.erro || "erro");
}
function pedirPermissaoNotificacoes() {
  if (!("Notification" in window)) { alert("Este navegador não suporta notificações."); return; }
  Notification.requestPermission().then(p => {
    alert(p === "granted" ? "Notificações do navegador autorizadas."
                          : "Permissão não concedida pelo navegador.");
  });
}
function notificar(tipo, texto, icone) {
  if (notifPrefs[tipo] === false) return;
  notifLista.unshift({ tipo, texto, icone: icone || "🔔",
                       ts: new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }) });
  notifLista = notifLista.slice(0, 30);
  renderNotificacoes();
  if (notifPrefs.navegador && "Notification" in window && Notification.permission === "granted") {
    try { new Notification("KChrono", { body: texto }); } catch (e) {}
  }
}
function renderNotificacoes() {
  const badge = document.getElementById("notif-badge");
  if (badge) {
    if (notifLista.length) { badge.hidden = false; badge.textContent = notifLista.length; }
    else badge.hidden = true;
  }
  const lista = document.getElementById("notif-lista");
  if (!lista) return;
  lista.innerHTML = notifLista.length
    ? notifLista.map(n => `<div class="mini-notif"><span class="ico">${n.icone}</span>
        <span>${_esc(n.texto)}</span><span class="ts">${n.ts}</span></div>`).join("")
    : '<div class="drop-vazio">sem notificações</div>';
}
async function renderUploadDrop() {
  const el = document.getElementById("upload-lista");
  if (!el) return;
  let s;
  try { s = await api("sync/status", "GET"); } catch (e) {
    el.innerHTML = '<div class="drop-vazio">indisponível</div>'; return;
  }
  el.innerHTML =
    `<div class="mini-notif"><span class="ico">📥</span><span>na fila</span><span class="ts">${s.pendentes ?? 0}</span></div>` +
    `<div class="mini-notif"><span class="ico">✅</span><span>enviados hoje</span><span class="ts">${s.enviados ?? 0}</span></div>` +
    `<div class="mini-notif"><span class="ico">⚠️</span><span>falhas</span><span class="ts">${s.falhas ?? 0}</span></div>` +
    `<div class="mini-notif"><span class="ico">🔗</span><span>CTAD</span><span class="ts">` +
      `${s.configurado ? "conectado " + (s.nivel || "") : "não configurado"}</span></div>`;
}

// ---------------------------------------------------------------- gerente de pista (Admin)
let checkinCache = { pilotos: [], presentes: [] };
function carregarGerente() {
  carregarCheckin();
  carregarEstadoPista();
  // mostra o QR ativo (sem gerar um novo — só o botão "Gerar QR" rotaciona)
  adminCarregarQR();
}

// ---------------------------------------------------------------- QR Code de acesso (Admin)
let admQRUrl = "";

function admQRErro(msg) {
  const el = document.getElementById("adm-qr-erro");
  if (el) el.textContent = msg || "";
}

function admQRMostrar(r) {
  admQRUrl = r.url || "";
  admQRErro("");
  const img = document.getElementById("adm-qr-img");
  const vazio = document.getElementById("adm-qr-vazio");
  if (img) {
    img.onerror = () => admQRErro("QR recebido do servidor, mas a imagem não exibiu " +
      "neste navegador — tente Chrome/Edge atualizado ou outro aparelho.");
    img.src = r.qrcode;
    img.style.display = "block";
  }
  if (vazio) vazio.style.display = "none";
  const url = document.getElementById("adm-qr-url");
  if (url) url.textContent = admQRUrl;
  const info = document.getElementById("adm-qr-info");
  if (info) info.textContent =
    `QR ativo · vale por ${r.dias} dia(s)` +
    (r.substituidos ? ` · ${r.substituidos} anterior(es) revogado(s)` : "");
  admListarQR();
}

async function adminGerarQR() {
  admQRErro("");
  const dias = parseInt((document.getElementById("adm-qr-dias") || {}).value, 10) || 30;
  let r;
  try { r = await api(`admin/qrcode?dias=${dias}`); }
  catch (e) { admQRErro("falha de comunicação com o servidor"); return; }
  if (!r || !r.ok) { admQRErro((r && r.erro) || "não foi possível gerar o QR Code"); return; }
  admQRMostrar(r);
  logMsg(`QR Code de acesso gerado (vale ${r.dias} dia(s))`, "l-admin", "log-operador");
}

async function adminCarregarQR() {
  let r;
  try { r = await api("admin/qrcode/atual", "GET"); }
  catch (e) { return; }
  if (!r || r.vazio) { adminListarQR(); return; }
  if (!r.ok) return;
  admQRMostrar(r);
}

async function adminListarQR() {
  const info = document.getElementById("adm-qr-info");
  if (!info) return;
  let r;
  try { r = await api("admin/qrcode/convites", "GET"); }
  catch (e) { return; }
  if (!r || !r.ok) return;
  const n = (r.convites || []).length;
  if (!admQRUrl) info.textContent = n ? `${n} QR Code(s) ativo(s).` : "—";
  else if (n) {
    const horas = Math.round(r.convites.reduce((s, c) => s + (c.restante_s || 0), 0)
      / n / 3600);
    info.textContent = `${info.textContent} · validade restante ~${horas}h.`;
  }
}

async function adminRevogarQR() {
  if (!confirm("Revogar o QR Code de acesso?\n\nOs celulares conectados por ele perdem o acesso. A senha do gerente não muda.")) return;
  let r;
  try { r = await api("admin/qrcode", "DELETE"); }
  catch (e) { admQRErro("falha de comunicação"); return; }
  if (!r || !r.ok) { admQRErro((r && r.erro) || "falha ao revogar"); return; }
  admQRUrl = "";
  const img = document.getElementById("adm-qr-img");
  if (img) { img.style.display = "none"; img.removeAttribute("src"); }
  const vazio = document.getElementById("adm-qr-vazio");
  if (vazio) vazio.style.display = "";
  const url = document.getElementById("adm-qr-url");
  if (url) url.textContent = "—";
  const info = document.getElementById("adm-qr-info");
  if (info) info.textContent = "—";
  logMsg(`QR Code revogado (${r.revogados})`, "l-admin", "log-operador");
}

async function adminCopiarQR() {
  if (!admQRUrl) { alert("Gere um QR Code primeiro."); return; }
  try {
    await navigator.clipboard.writeText(admQRUrl);
    logMsg("endereço do QR copiado", "l-admin", "log-operador");
  } catch (e) {
    alert(admQRUrl);
  }
}

// ---------------------------------------------------------------- QR de Gestão Remota (menu lateral)
// Novo código exclusivo a cada abertura do aplicativo, válido até fechar.
async function gerarQRSessao() {
  const info = document.getElementById("side-qr-info");
  let r;
  try { r = await api("admin/qrcode?dias=1"); }
  catch (e) {
    if (info) info.textContent = "falha ao gerar — verifique a conexão";
    return;
  }
  if (!r || !r.ok) {
    if (info) info.textContent = (r && r.erro) || "não foi possível gerar";
    return;
  }
  admQRUrl = r.url || admQRUrl;
  const img = document.getElementById("side-qr-img");
  if (img && r.qrcode) { img.src = r.qrcode; img.style.display = "block"; }
  if (info) info.textContent = "válido até fechar o aplicativo";
}
// Ao fechar, o QR da sessão morre junto (não fica circulando em print de tela).
window.addEventListener("pagehide", () => {
  try { fetch("/api/admin/qrcode", { method: "DELETE", keepalive: true }); }
  catch (e) {}
});

// ---------------------------------------------------------------- Aparência (Admin → Configurações)
const AP_KEY = "kchrono_aparencia";
//: wallpaper que já vem configurado de fábrica — usado quando o operador
// ainda não escolheu nenhum (assim toda instalação/janela nova já entra com imagem).
const WALLPAPER_PADRAO = "/imagens/wallpaper.jpg";
//: URL vigente: a escolhida pelo operador ou, na falta dela, a padrão.
function wallpaperAtual(a) {
  return (a && a.wallpaper) || WALLPAPER_PADRAO;
}
function carregarAparencia() {
  try { return JSON.parse(localStorage.getItem(AP_KEY)) || {}; }
  catch (e) { return {}; }
}
function salvarAparencia(a) {
  try { localStorage.setItem(AP_KEY, JSON.stringify(a)); } catch (e) {}
}
function aplicarAparencia() {
  const a = carregarAparencia();
  const alpha = 1 - Math.min(80, Math.max(0, Number(a.transparencia) || 0)) / 100;
  document.documentElement.style.setProperty("--card-alpha", alpha.toFixed(2));
  const url = wallpaperAtual(a);
  document.querySelectorAll(".corpo, #operador .conteudo").forEach(el => {
    el.classList.toggle("papel-parede", !!url);
    el.style.backgroundImage = url ? `url("${url}")` : "";
  });
}
function carregarAparenciaForm() {
  const a = carregarAparencia();
  const t = Number(a.transparencia) || 0;
  const range = document.getElementById("cfg-transparencia");
  if (range) range.value = t;
  const txt = document.getElementById("cfg-transparencia-txt");
  if (txt) txt.textContent = `${t}%`;
  // o campo mostra a URL em uso (a padrão, quando nada foi escolhido)
  const url = document.getElementById("cfg-wallpaper-url");
  if (url) {
    if (a.wallpaper && !a.wallpaper.startsWith("data:")) url.value = a.wallpaper;
    else if (!a.wallpaper) url.value = WALLPAPER_PADRAO;
    else url.value = "";
  }
  renderWallpaperPrev();
}
function renderWallpaperPrev() {
  const prev = document.getElementById("cfg-wallpaper-prev");
  if (!prev) return;
  const a = carregarAparencia();
  const url = wallpaperAtual(a);
  prev.innerHTML = url
    ? `<img src="${url}" alt="wallpaper atual" style="max-width:100%;border-radius:8px;border:1px solid var(--border-card)">
       <p class="hint" style="margin-top:6px">${
         a.wallpaper ? "wallpaper salvo <b>neste navegador</b>"
                     : `wallpaper <b>padrão</b> — logo do arquivo <code>${WALLPAPER_PADRAO}</code>
                        (nenhuma escolha salva neste navegador)`}</p>`
    : `<span class="hint">sem wallpaper — fundo padrão</span>`;
}
function definirWallpaperURL() {
  const url = (document.getElementById("cfg-wallpaper-url").value || "").trim();
  const a = carregarAparencia();
  if (url) a.wallpaper = url; else delete a.wallpaper;
  salvarAparencia(a); aplicarAparencia(); renderWallpaperPrev();
}
function carregarWallpaperArquivo(input) {
  const f = input && input.files && input.files[0];
  if (!f) return;
  const rd = new FileReader();
  rd.onload = () => {
    const a = carregarAparencia();
    a.wallpaper = String(rd.result);
    try { salvarAparencia(a); }
    catch (e) { alert("imagem muito grande para salvar no navegador — use uma URL."); return; }
    aplicarAparencia(); renderWallpaperPrev();
  };
  rd.readAsDataURL(f);
  input.value = "";
}
function removerWallpaper() {
  const a = carregarAparencia();
  delete a.wallpaper;
  salvarAparencia(a); aplicarAparencia(); renderWallpaperPrev();
  const url = document.getElementById("cfg-wallpaper-url");
  if (url) url.value = WALLPAPER_PADRAO;   // volta a valer o padrão
}
function mudarTransparencia(v) {
  const t = Math.min(80, Math.max(0, parseInt(v, 10) || 0));
  const a = carregarAparencia();
  a.transparencia = t;
  salvarAparencia(a); aplicarAparencia();
  const txt = document.getElementById("cfg-transparencia-txt");
  if (txt) txt.textContent = `${t}%`;
}

function mudarIdioma(lang) {
  localStorage.setItem("kchrono_idioma", lang);
  location.reload();
}

function carregarIdioma() {
  const lang = localStorage.getItem("kchrono_idioma") || "pt_BR";
  const sel = document.getElementById("cfg-idioma");
  if (sel) sel.value = lang;
  return lang;
}
async function carregarEstadoPista() {
  try {
    const r = await api("pista/estado", "GET");
    _renderEstadoPista(r);
  } catch (e) {}
}
function _renderEstadoPista(r) {
  const el = document.getElementById("ger-estado");
  if (!el || !r) return;
  el.textContent = r.bandeira === "verde"
    ? "pista aberta (verde)"
    : `${r.bandeira}${r.motivo ? " — " + r.motivo : ""}`;
  // destaca o botão da bandeira vigente
  document.querySelectorAll("button.bd").forEach(b =>
    b.classList.toggle("ativa", b.classList.contains(r.bandeira)));
}
async function definirBandeira(cor) {
  const motivo = (document.getElementById("ger-motivo").value || "").trim();
  const r = await api(`pista/bandeira?cor=${encodeURIComponent(cor)}&motivo=${encodeURIComponent(motivo)}`);
  if (r.ok) { _renderEstadoPista(r); logMsg(`bandeira: ${cor}${motivo ? " — " + motivo : ""}`, "l-admin", "log-operador"); }
  else alert(r.erro || "erro");
}
async function carregarCheckin() {
  const p = await api("pilotos", "GET");
  const c = await api("checkin", "GET");
  checkinCache.pilotos = (p.pilotos || []).filter(x => x.ativo);
  checkinCache.presentes = c.presentes || [];
  const sel = document.getElementById("ger-volta-piloto");
  if (sel) sel.innerHTML = checkinCache.pilotos.map(x => `<option value="${x.id}">${_esc(x.nome)}</option>`).join("");
  renderCheckin();
}
function renderCheckin() {
  const el = document.getElementById("ger-checkin");
  if (!el) return;
  const q = (document.getElementById("ger-checkin-busca").value || "").toLowerCase();
  const lst = checkinCache.pilotos.filter(p => !q || p.nome.toLowerCase().includes(q));
  el.innerHTML = lst.map(p => {
    const on = checkinCache.presentes.includes(p.id);
    return `<label class="ck-piloto ${on ? "on" : ""}">
      <input type="checkbox" ${on ? "checked" : ""} onchange="toggleCheckin(${p.id}, this.checked)">
      ${_esc(p.nome)}</label>`;
  }).join("") || '<p class="hint">nenhum piloto</p>';
  const n = document.getElementById("ger-checkin-n");
  if (n) n.textContent = checkinCache.presentes.length;
}
async function toggleCheckin(id, presente) {
  const r = await api(`checkin?piloto_id=${id}&presente=${presente}`);
  if (r.ok) { checkinCache.presentes = r.presentes; renderCheckin(); }
}
async function marcarTodosCheckin(todos) {
  const ids = todos ? checkinCache.pilotos.map(p => p.id) : [];
  const r = await api("checkin/lote", "POST", "", { presentes: ids });
  if (r.ok) { checkinCache.presentes = r.presentes; renderCheckin(); }
}
async function anunciarGerente() {
  const texto = document.getElementById("ger-anuncio").value.trim();
  if (!texto) { alert("Digite o texto do anúncio."); return; }
  const r = await api("som/falar", "POST", "", { texto });
  if (r.ok) {
    logMsg(`anúncio: ${r.texto}`, "l-admin", "log-operador");
    document.getElementById("ger-anuncio").value = "";
  } else alert(r.erro || "erro ao anunciar");
}
async function adicionarVoltaManual() {
  const id = document.getElementById("ger-volta-piloto").value;
  const t = parseFloat(document.getElementById("ger-volta-tempo").value);
  if (!id || !(t > 0)) { alert("Selecione o piloto e informe um tempo válido."); return; }
  const r = await api(`sessao/adicionar-volta?piloto_id=${id}&tempo_s=${t}`);
  if (r.ok) logMsg(`volta manual adicionada (${t}s)`, "l-admin", "log-operador");
  else alert("Não foi possível adicionar (há sessão ativa?).");
}

// ---------------------------------------------------------------- relatórios (Admin)
async function carregarRelatorioResumo() {
  const r = await api("relatorios/resumo", "GET");
  const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
  set("rel-sessoes", r.sessoes ?? 0);
  set("rel-pilotos", r.pilotos ?? 0);
  set("rel-voltas", r.voltas ?? 0);
  set("rel-camps", r.campeonatos ?? 0);
}
async function carregarRelatorioSessoes() {
  const qs = [];
  const tipo = document.getElementById("rel-filtro-tipo").value;
  const de = document.getElementById("rel-de").value;
  const ate = document.getElementById("rel-ate").value;
  if (tipo) qs.push("tipo=" + encodeURIComponent(tipo));
  if (de) qs.push("de=" + de);
  if (ate) qs.push("ate=" + ate);
  const r = await api(`relatorios/sessoes${qs.length ? "?" + qs.join("&") : ""}`, "GET");
  const lst = r.sessoes || [];
  document.getElementById("rel-tabela").innerHTML =
    "<tr><th>ID</th><th>Tipo</th><th>Estado</th><th>Início</th><th>Pilotos</th><th>Voltas</th><th>Melhor</th></tr>" +
    (lst.map(s => `<tr><td>${s.id.slice(0, 8)}</td><td>${s.tipo}</td><td>${s.estado}</td>
        <td>${(s.inicio || "").replace("T", " ").slice(0, 16)}</td><td>${s.pilotos}</td>
        <td>${s.voltas}</td><td>${s.melhor}</td></tr>`).join("")
      || '<tr><td colspan="7" style="color:var(--text-muted)">nenhuma sessão no período</td></tr>');
}
async function carregarRelatorioPilotos() {
  const r = await api("relatorios/pilotos", "GET");
  const lst = r.pilotos || [];
  document.getElementById("rel-tabela").innerHTML =
    "<tr><th>Piloto</th><th>Telefone</th><th>Sessões</th><th>Voltas</th><th>Melhor volta</th></tr>" +
    (lst.map(p => `<tr><td>${_esc(p.nome)}</td><td>${p.telefone || "—"}</td>
        <td>${p.sessoes}</td><td>${p.voltas}</td><td>${p.melhor}</td></tr>`).join("")
      || '<tr><td colspan="5" style="color:var(--text-muted)">nenhum piloto</td></tr>');
}
function baixarRelatorio(tipo) {
  window.location.href = `/api/relatorios/${tipo}.csv`;
}

// ---------------------------------------------------------------- campeonato (plano de etapas)
let planoCamp = null;
function tipoSessaoMudou() {
  const escolha = document.getElementById("cfg-camp-escolha");
  const tipo = document.getElementById("cfg-tipo").value;
  const camp = tipo === "campeonato";
  if (escolha) escolha.style.display = camp ? "block" : "none";
  if (camp) carregarCampeonatosOperador();
  // Treino livre por padrão: tempo corre pra cima, sem limite.
  // (Ao sair do treino, volta para "Tempo" se estava em livre.)
  const crit = document.getElementById("cfg-criterio");
  if (crit && !camp) {
    const livre = crit.value.toLowerCase().startsWith("livre");
    if (tipo === "treino" && !livre) crit.value = "livre";
    else if (tipo !== "treino" && livre) crit.value = "Tempo";
  }
  criterioMudou();
  atualizarBotaoPrincipal();
}

// "Tempo livre" não usa duração (sem limite): desabilita o campo.
function criterioMudou() {
  const sel = document.getElementById("cfg-criterio");
  const dur = document.getElementById("cfg-duracao");
  if (!sel || !dur) return;
  const livre = sel.value.toLowerCase().startsWith("livre");
  dur.disabled = livre;
  dur.title = livre ? "tempo livre: sem limite de duração" : "";
}

// ---------------------------------------------------------------- escolha do campeonato (painel do operador)
// O painel do operador apenas PERGUNTA qual campeonato rodar. Criar/editar levam
// ao menu Campeonatos (Admin → 🏆 Campeonatos), onde fica a configuração completa.
let campSelecionarPendente = null;

async function carregarCampeonatosOperador() {
  const sel = document.getElementById("cfg-camp-select");
  if (!sel) return;
  let lista = [];
  try { const r = await api("campeonatos", "GET"); lista = r.campeonatos || []; } catch (e) {}
  sel.innerHTML = lista.length
    ? lista.map(c => `<option value="${c.id}">${_esc(c.nome)} — ${c.inscritos} inscrito(s)</option>`).join("")
    : '<option value="">— nenhum campeonato —</option>';
  const aviso = document.getElementById("cfg-camp-aviso");
  if (aviso) aviso.style.display = lista.length ? "none" : "block";
  atualizarEscolhaCampeonato();
}

// Habilita "Editar" e "Iniciar" só quando há um campeonato escolhido.
function atualizarEscolhaCampeonato() {
  const sel = document.getElementById("cfg-camp-select");
  const tem = !!(sel && sel.value);
  const btnIni = document.getElementById("cfg-camp-iniciar");
  const btnEd = document.getElementById("cfg-camp-editar");
  if (btnIni) btnIni.disabled = !tem;
  if (btnEd) btnEd.disabled = !tem;
}

// Vai ao menu Campeonatos com o formulário de criação em foco.
function menuCriarCampeonato() {
  adminIr("a-camp");
  const nome = document.getElementById("camp-nome");
  if (nome) { try { nome.focus(); } catch (e) {} }
}

// Vai ao menu Campeonatos já com o campeonato escolhido carregado para editar.
function menuEditarCampeonato() {
  const sel = document.getElementById("cfg-camp-select");
  campSelecionarPendente = (sel && sel.value) ? sel.value : null;
  adminIr("a-camp");
}

// Inicia a sequência do campeonato escolhido no painel do operador.
async function iniciarCampeonatoEscolhido() {
  const sel = document.getElementById("cfg-camp-select");
  const id = sel ? sel.value : "";
  if (!id) { logMsg("campeonato: escolha um campeonato", "l-aviso", "log-operador"); return; }
  const nome = sel.options[sel.selectedIndex] ? sel.options[sel.selectedIndex].textContent : id;
  if (!confirm(`Iniciar o campeonato "${nome}"?\n\nA sequência de etapas configurada em ` +
      `🏆 Campeonatos vai começar agora.`)) return;
  const tmin = parseFloat((document.getElementById("cfg-tempo-minimo") || {}).value) || 0;
  const r = await api(`campeonato/iniciar?tempo_minimo_s=${tmin}&campeonato_id=${encodeURIComponent(id)}`);
  if (r.ok) {
    logMsg(`campeonato iniciado — ${r.etapa.rotulo}`, "l-sistema", "log-operador");
    abrirOperador();
  } else {
    alert(r.erro || "erro ao iniciar o campeonato");
  }
}

// Botão principal de ação: rótulo e comportamento seguem o tipo de sessão.
// Treino/classificação saem contando direto (sem largada); corrida pede largada.
let sessaoAtiva = false, estadoSessao = "parado";
//: true quando o cronômetro da sessão está pausado (alimenta o botão Pausar/Retomar)
let sessaoPausada = false;
const ROTULO_ACAO = {
  treino: "▶ Iniciar treino",
  classificacao: "▶ Iniciar classificação",
  corrida: "▶ Preparar para Largada!",
};
function atualizarBotaoPrincipal() {
  const btn = document.getElementById("btn-acao-principal");
  if (!btn) return;
  const tipo = (document.getElementById("cfg-tipo") || {}).value || "treino";
  if (tipo === "campeonato") { btn.style.display = "none"; return; }  // tem botões próprios no plano
  btn.style.display = "";
  if (sessaoAtiva && estadoSessao === "largada") {
    btn.disabled = false;
    btn.textContent = "▶ Largada";
  } else if (sessaoAtiva) {
    btn.disabled = true;
    btn.textContent = "● Em andamento";
  } else {
    btn.disabled = false;
    btn.textContent = ROTULO_ACAO[tipo] || "▶ Iniciar";
  }
}
function acaoPrincipal() {
  const tipo = (document.getElementById("cfg-tipo") || {}).value || "treino";
  if (tipo === "campeonato") return;
  if (sessaoAtiva && estadoSessao === "largada") { largada(); return; }
  if (sessaoAtiva) return;
  iniciarSessaoConfigurada();
}
async function carregarPlanoCampeonato() {
  const r = await api("campeonato/plano", "GET");
  planoCamp = r;
  const np = document.getElementById("camp-num-provas");
  if (np) np.value = r.numero_provas || 1;
  renderPlanoCampeonato();
}
async function remontarPlanoCampeonato() {
  const n = parseInt((document.getElementById("camp-num-provas") || {}).value, 10) || 1;
  const v = (id) => (document.getElementById(id) || {}).value;
  const r = await api(`campeonato/plano/montar?provas=${n}` +
    `&treino=${v("camp-d-treino")}&classificacao=${v("camp-d-class")}` +
    `&corrida=${v("camp-d-corr")}&intervalo=${v("camp-d-int")}`);
  if (!r.ok) { alert(r.erro || "erro ao remontar"); return; }
  planoCamp = r;
  const np = document.getElementById("camp-num-provas");
  if (np) np.value = r.numero_provas || n;
  renderPlanoCampeonato();
  logMsg(`sequência remontada: ${r.numero_provas} prova(s) — ${r.duracao_exata}`, "l-sistema", "log-operador");
}
async function salvarDuracoesCamp() {
  const v = (id, fb) => parseInt((document.getElementById(id) || {}).value, 10) || fb;
  const r = await api("campeonato/duracoes" +
    `?treino=${v("camp-d-treino", 10)}&classificacao=${v("camp-d-class", 10)}` +
    `&corrida=${v("camp-d-corr", 20)}&intervalo=${v("camp-d-int", 5)}`);
  if (!r.ok) { alert(r.erro || "erro ao salvar durações"); return; }
  planoCamp = r;
  renderPlanoCampeonato();
  logMsg("durações do campeonato salvas", "l-sistema", "log-operador");
}
async function salvarClassRegra() {
  const c = document.getElementById("camp-class-3voltas");
  const r = await api(`campeonato/regras?class_3voltas=${c && c.checked ? 1 : 0}`);
  if (!r.ok) { alert(r.erro || "erro ao salvar a regra da classificação"); return; }
  planoCamp = r;
  renderPlanoCampeonato();
  logMsg(`classificação: grid pela ${r.class_3voltas ? "média das 3 melhores voltas" : "melhor volta"}`,
         "l-admin", "log-operador");
}
function renderPlanoCampeonato() {
  const t = document.getElementById("camp-plano-lista");
  if (!t || !planoCamp) return;
  const icones = { treino: "🏎️", intervalo: "⏸", classificacao: "⏱️", corrida: "🏁" };
  // durações (escolhidas 1 vez na configuração da sessão)
  const d = (id, v) => { const el = document.getElementById(id); if (el) el.value = v; };
  d("camp-d-treino", planoCamp.treino_min ?? 10);
  d("camp-d-class", planoCamp.classificacao_min ?? 10);
  d("camp-d-corr", planoCamp.corrida_min ?? 20);
  d("camp-d-int", planoCamp.intervalo_min ?? 5);
  const c3 = document.getElementById("camp-class-3voltas");
  if (c3) c3.checked = planoCamp.class_3voltas !== false;
  // sequência somente-leitura (vem das durações acima + nº de provas)
  t.innerHTML = planoCamp.etapas.map((e, i) =>
    `${i ? '<div class="plano-seta">→</div>' : ""}
     <div class="plano-etapa${e.etapa === "intervalo" ? " intervalo" : ""}">
       <div class="plano-icone">${icones[e.etapa] || "🏁"}</div>
       <div class="plano-rotulo">${_esc(e.rotulo)}</div>
       <div class="plano-dur"><b>${e.duracao}</b><span>min</span></div>
     </div>`).join("");
  if (ultimoEstadoCamp && ultimoEstadoCamp.ativo) {
    const cards = t.querySelectorAll(".plano-etapa");
    cards.forEach((c, i) => c.classList.toggle("atual", i === ultimoEstadoCamp.indice));
  }
  atualizarTotalCamp();
}
function lerPlanoCampeonato() {
  return (planoCamp && planoCamp.etapas) || [];
}
function atualizarTotalCamp() {
  const total = lerPlanoCampeonato().reduce((s, e) => s + e.duracao, 0);
  const el = document.getElementById("camp-plano-total");
  if (el) el.textContent = total >= 60
    ? `${Math.floor(total / 60)}h${String(total % 60).padStart(2, "0")}min`
    : `${total} min`;
}
async function salvarPlanoCampeonato() {
  const r = await api("campeonato/plano", "POST", "", { etapas: lerPlanoCampeonato() });
  if (r.ok) { planoCamp = r; renderPlanoCampeonato(); logMsg("campeonato: plano salvo", "l-admin", "log-operador"); }
  else alert(r.erro || "erro ao salvar o plano");
  return r.ok;
}

// ---------------------------------------------------------------- ponte com o CTAD
async function buscarCampeonatoCTAD() {
  const chave = document.getElementById("camp-chave-ctad").value.trim();
  const box = document.getElementById("camp-ctad-preview");
  if (!chave) { if (box) box.innerHTML = ""; return; }
  if (box) box.innerHTML = '<span class="hint">buscando no CTAD…</span>';
  const r = await api(`campeonato/ctad?chave=${encodeURIComponent(chave)}`, "GET");
  if (!r.ok) {
    if (box) box.innerHTML = `<p class="hint" style="color:var(--accent-red)">${_esc(r.erro || "não encontrado")}</p>`;
    logMsg(`campeonato/ctad: ${r.erro || "não encontrado"}`, "l-aviso", "log-operador");
    return;
  }
  const inv = r.inverterSegundaBateria ? "ligada" : "desligada";
  if (r.numeroProvas) {
    const np = document.getElementById("camp-num-provas");
    if (np) np.value = r.numeroProvas;
  }
  if (box) box.innerHTML = `
    <div class="card" style="padding:12px">
      <b>${_esc(r.nome)}</b>
      <span class="hint"> · ${r.inscritos} inscrito(s) no site</span>
      <div style="margin-top:8px; font-size:13px; line-height:1.7">
        <div>🔑 <b>${r.pilotosPorChave ?? "—"}</b> pilotos por chave (Chave A/B/C)</div>
        <div>🔄 inversão da bateria seguinte: <b>${inv}</b></div>
        <div>🏁 ${r.numeroProvas ?? "—"} provas previstas</div>
        ${Array.isArray(r.pontuacaoTabela)
          ? `<div>🏆 pontos: ${r.pontuacaoTabela.join(", ")}</div>` : ""}
      </div>
    </div>`;
  logMsg(`campeonato/ctad: "${r.nome}" — máx ${r.pilotosPorChave ?? "—"}/chave, inversão ${inv}`,
         "l-sistema", "log-operador");
}

// ---------------------------------------------------------------- campeonato em andamento
let ultimoEstadoCamp = null;
function renderEstadoCampeonato(est) {
  ultimoEstadoCamp = est;
  const el = document.getElementById("camp-atual");
  // destaca na sequência o box da etapa em andamento
  const cards = document.querySelectorAll("#camp-plano-lista .plano-etapa");
  if (!el) return;
  const etapaEl = document.getElementById("camp-etapa-atual");
  if (!est || !est.ativo) {
    el.innerHTML = '<span class="hint">nenhum campeonato em andamento</span>';
    if (etapaEl) etapaEl.textContent = "—";
    cards.forEach(c => c.classList.remove("atual"));
    const prox = document.getElementById("camp-proxima");
    if (prox) prox.disabled = true;
    const enc = document.getElementById("camp-encerrar");
    if (enc) enc.disabled = true;
    return;
  }
  const e = est.etapa;
  const nome = e ? e.rotulo : "—";
  const tipo = e ? e.etapa : "";
  if (etapaEl) etapaEl.textContent = `Etapa ${est.numero} de ${est.total} — ${nome}`;
  cards.forEach((c, i) => c.classList.toggle("atual", i === est.indice));
  el.innerHTML = `
    <div class="camp-etapa-atual">
      ${est.campeonato_nome ? `<span class="camp-etapa-num">🏆 ${_esc(est.campeonato_nome)}</span>` : ""}
      <span class="camp-etapa-num">Etapa ${est.numero} de ${est.total}</span>
      <b>${_esc(nome)}</b>
      ${tipo === "intervalo" ? '<span class="prev">intervalo</span>' : ""}
      ${est.proxima ? `<span class="hint">próxima: ${_esc(est.proxima.rotulo)}</span>`
                   : '<span class="hint">última etapa</span>'}
    </div>`;
  const prox = document.getElementById("camp-proxima");
  if (prox) prox.disabled = !est.proxima;
  const enc = document.getElementById("camp-encerrar");
  if (enc) enc.disabled = false;
}

async function proximaEtapa() {
  if (!confirm("Avançar para a próxima etapa?\n\nA sessão atual é encerrada e a próxima começa.")) return;
  const r = await api("campeonato/proxima", "POST");
  if (r.ok) {
    if (r.concluido) {
      logMsg("campeonato concluído — todas as etapas disputadas", "l-sistema", "log-operador");
      alert("🏆 Campeonato concluído!");
    } else {
      logMsg(`campeonato: avançou para ${r.etapa.rotulo}`, "l-sistema", "log-operador");
    }
    renderEstadoCampeonato(r);
  } else {
    alert(r.erro || "erro ao avançar de etapa");
  }
}

async function encerrarCampeonato() {
  if (!confirm("Encerrar o campeonato em andamento?\n\nA sessão atual é finalizada e o campeonato sai de andamento.")) return;
  const r = await api("campeonato/encerrar", "POST");
  if (r.ok) {
    logMsg("campeonato encerrado pelo operador", "l-sistema", "log-operador");
    renderEstadoCampeonato(r);
  } else {
    alert(r.erro || "erro ao encerrar o campeonato");
  }
}


// ---------------------------------------------------------------- atualizações
async function verificarVersao() {
  const st = document.getElementById("upd-status");
  const versaoEl = document.getElementById("upd-versao");
  if (st) st.textContent = "verificando…";
  const r = await api("versao", "GET");
  // restaura o repositório salvo no campo (sem apagar o que está sendo digitado)
  const repo = document.getElementById("upd-repo");
  if (repo && !repo.value && r.repo) repo.value = r.repo;
  if (versaoEl && r.versao_atual) versaoEl.textContent = r.versao_atual;
  if (!st) return;
  if (r.disponivel) {
    const mb = r.arquivos?.windows?.tamanho;
    st.innerHTML = `<b style="color:var(--accent-green)">v${r.versao_remota} disponível</b>` +
      ` (atual v${r.versao_atual})${mb ? ` · ${(mb / 1e6).toFixed(0)} MB` : ""}` +
      (r.canal ? ` · ${r.canal}` : "");
  } else if (r.erro) {
    st.textContent = `não foi possível verificar: ${r.erro}`;
  } else if (r.motivo) {
    st.textContent = `${r.versao_atual} · ${r.motivo}`;
  } else {
    st.textContent = `${r.versao_atual} · já é a versão mais recente` +
      (r.canal ? ` · ${r.canal}` : "");
  }
}

async function salvarRepoAtualizacao() {
  const inp = document.getElementById("upd-repo");
  // aceita colar a URL do GitHub também (github.com/usuario/repo)
  const repo = (inp?.value || "").trim()
    .replace(/^https?:\/\/(www\.)?github\.com\//i, "").replace(/\/+$/, "");
  if (!repo || !repo.includes("/")) {
    alert("Informe o repositório no formato usuario/repo\n(ex.: seuusuario/KChrono).");
    return;
  }
  const r = await api(`versao/repo?repo=${encodeURIComponent(repo)}`, "POST");
  logMsg(`atualizações: canal definido para ${r.repo}`, "l-admin", "log-operador");
  verificarVersao();
}

async function baixarAtualizacao() {
  const st = document.getElementById("upd-status");
  if (st) st.textContent = "baixando a versão nova… pode levar um minuto";
  const r = await api("versao/baixar", "POST");   // backend escolhe windows/linux
  if (r.ok) {
    if (st) st.innerHTML = `baixado: <b>${r.arquivo}</b> (v${r.versao} · ${r.tamanho_mb} MB)` +
      ` — use "Instalar agora"`;
  } else if (st) {
    st.textContent = `falha no download: ${r.erro}`;
  }
}

async function instalarAtualizacao() {
  const st = document.getElementById("upd-status");
  if (!confirm("Instalar a versão nova agora?\n\nO KChrono baixa a atualização, encerra e " +
    "instala em silêncio (Windows: instalador; Linux: troca do AppImage). Reabra o app em " +
    "instantes — banco, config e vozes não são afetados.")) return;
  if (st) st.textContent = "baixando e preparando a atualização…";
  const r = await api("versao/instalar", "POST");
  if (!r.ok) {
    if (st) st.textContent = `falha: ${r.erro}`;
    return;
  }
  if (st) st.innerHTML = `<b style="color:var(--accent-green)">atualizando para v${r.versao}…</b>` +
    ` o app vai fechar — abra novamente em alguns segundos`;
  logMsg(`atualização para v${r.versao} em andamento — o app vai encerrar`,
    "l-admin", "log-operador");
}

async function encerrarApp() {
  if (!confirm("Sair do KChrono?\n\nO servidor local vai parar (feche a aba depois).")) return;
  const r = await api("app/sair", "POST");
  if (r.ok) logMsg("KChrono encerrando…", "l-admin", "log-operador");
}

async function configurarSync() {
  const email = document.getElementById("sync-email").value.trim();
  const senha = document.getElementById("sync-senha").value;
  const pista = document.getElementById("sync-pista").value.trim() || "krathus";
  if (!email || !senha) { atualizarSyncTexto("informe e-mail e senha", "var(--accent-gold)"); return; }
  atualizarSyncTexto("conectando…", "var(--accent-blue)");
  const r = await api(`sync/configurar?email=${encodeURIComponent(email)}&password=${encodeURIComponent(senha)}&pista_id=${encodeURIComponent(pista)}`);
  if (r.ok) {
    atualizarSyncTexto(`conectado (${r.nivel})`, "var(--accent-green)");
    document.getElementById("sync-nivel").textContent = r.nivel;
    logMsg(`sync: conectado ao CTAD como ${r.nivel}`, "l-admin", "log-operador");
  } else {
    // credenciais ficam salvas mesmo com o teste falhando (rede/login)
    atualizarSyncTexto(`falhou: ${r.erro}${r.salvo ? " — e-mail/senha salvos; tentaremos ao reabrir" : ""}`,
      "var(--accent-red)");
    logMsg(`sync: ${r.erro}${r.salvo ? " (credenciais salvas mesmo assim)" : ""}`, "l-erro", "log-operador");
  }
  atualizarSync();
}

async function enviarSessao() {
  const r = await api("sync/enviar");
  if (r.ok) {
    logMsg(`sync: sessão enviada (${r.enviados} enviados, ${r.duplicados} duplicados, ${r.falhas} falhas)`, "l-admin", "log-operador");
  } else {
    logMsg(`sync: ${r.erro}`, "l-erro", "log-operador");
  }
  atualizarSync();
}

async function processarFila() {
  const r = await api("sync/processar");
  if (r.ok) logMsg(`sync: fila processada — ${r.enviados} enviados`, "l-admin", "log-operador");
  else logMsg(`sync: ${r.erro}`, "l-erro", "log-operador");
  atualizarSync();
}

async function limparFila() {
  if (!confirm("Apagar os itens pendentes/com erro da fila local? (enviados ficam no histórico)")) return;
  const r = await api("sync/fila", "DELETE");
  if (r.ok) logMsg(`sync: ${r.removidos} item(ns) removido(s) da fila local`, "l-admin", "log-operador");
  atualizarSync();
}

function atualizarSyncTexto(texto, cor) {
  const el = document.getElementById("sync-status-text");
  if (el) { el.textContent = texto; el.style.color = cor; }
}

async function atualizarSync() {
  let s;
  try { s = await api("sync/status", "GET"); } catch (e) { return; }
  const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
  // restaura as credenciais salvas nos campos (só quando vazios — o timer de
  // 8s não pode apagar o que o usuário está digitando agora)
  const restaurar = (id, valor) => {
    const el = document.getElementById(id);
    if (el && !el.value && valor) el.value = valor;
  };
  restaurar("sync-email", s.email);
  restaurar("sync-senha", s.password);
  restaurar("sync-pista", s.pistaId);
  set("up-fila", s.pendentes ?? 0);
  set("up-enviados", s.enviados ?? 0);
  set("up-falhas", s.falhas ?? 0);
  const rodape = document.getElementById("rodape-sync");
  if (rodape) {
    rodape.textContent = s.configurado
      ? `CTAD: conectado (${s.nivel || "?"}) · ${s.pendentes ?? 0} na fila`
      : "CTAD: não configurado";
    rodape.style.color = s.configurado ? "var(--accent-green)" : "var(--text-muted)";
  }
  if (!document.getElementById("sync-status-text").textContent.startsWith("conectado")) {
    atualizarSyncTexto(s.configurado ? `conectado (${s.nivel})` : "não configurado",
      s.configurado ? "var(--accent-green)" : "var(--text-muted)");
  }
}

setInterval(atualizarSync, 8000);
atualizarSync();   // logo na abertura: restaura e-mail/senha/pista salvos
verificarVersao(); // checa versão nova na abertura (resultado no Admin → Sobre)

function previewNome() {
  const agora = new Date();
  const tpl = document.getElementById("tpl-input").value;
  const nome = tpl
    .replace("{campeonato}", document.getElementById("tpl-camp").value)
    .replace("{etapa}", document.getElementById("tpl-etapa").value)
    .replace("{tipo}", document.getElementById("tpl-tipo").value)
    .replace("{data}", agora.toISOString().slice(0, 10))
    .replace("{hora}", agora.toTimeString().slice(0, 5).replace(":", "-"));
  document.getElementById("tpl-preview").textContent = nome + ".json";
}

// init — abre direto no painel completo do operador, com o menu sempre visível
previewNome();
aplicarAparencia();
carregarIdioma();
atualizarBotaoPrincipal();
tipoSessaoMudou();   // treino começa em "Tempo livre" (conta pra cima, sem limite)
atualizarBotaoPausa();
carregarAutoConectar();
carregarVozContagem();
carregarTelaoTela();
conectarWS();
carregarNotificacoes();
mostrar("operador");
gerarQRSessao();

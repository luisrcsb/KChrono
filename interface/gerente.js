/* KChrono — Gerente de Pista: painel de controle externo (LAN).
   Acesso SEM SENHA, só por QR Code (token em sessionStorage) + WebSocket com
   o mesmo fluxo de eventos do telão, para operar sessão, bandeiras, check-in
   e locução. */
"use strict";

const G_CHAVE = "kchrono.gerente.token";
let gToken = sessionStorage.getItem(G_CHAVE) || "";
let gWs = null;
let gUsuarioAtual = "";
let gPilotos = [];
let gPresentes = [];
let gClassificacao = [];
let gSessao = {};
let gBandeiraCor = "verde";

// ---------------------------------------------------------------- API
async function gApi(caminho, metodo = "POST", params = "", corpo = null) {
  const opcoes = { method: metodo, headers: {} };
  if (gToken) opcoes.headers["X-Gerente-Token"] = gToken;
  if (corpo !== null && corpo !== undefined) {
    opcoes.headers["Content-Type"] = "application/json";
    opcoes.body = JSON.stringify(corpo);
  }
  const r = await fetch(`/api/gerente/${caminho}${params}`, opcoes);
  if (r.status === 401) { gSair(true); throw new Error("sessão expirada"); }
  return r.json();
}

// ---------------------------------------------------------------- entrada (só QR)
let gTentouQR = false;
async function gInit() {
  gLerTokenDoQR();                       // /gerente#t=... -> entra sem senha
  try {
    const st = await gApi("estado", "GET", "?token=" + encodeURIComponent(gToken));
    if (st.autenticado) { gAbrirApp(st.usuario); return; }
    if (gToken) { gToken = ""; sessionStorage.removeItem(G_CHAVE); }
  } catch (e) { /* servidor fora do ar: mostra a entrada mesmo assim */ }
  gMostrarLogin(gTentouQR
    ? "este convite expirou ou foi substituído — peça um QR novo ao operador"
    : "");
}

// Convite do QR Code: o token vem no FRAGMENTO (#t=...), que não é enviado
// ao servidor. Entramos com ele e limpamos a URL na hora, para o token não
// ficar exposto no histórico nem em um print de tela.
function gLerTokenDoQR() {
  const hash = (location.hash || "").replace(/^#/, "");
  if (!hash) return;
  const params = new URLSearchParams(hash);
  const t = params.get("t");
  if (!t) return;
  gTentouQR = true;
  gToken = t;
  sessionStorage.setItem(G_CHAVE, t);
  history.replaceState(null, "", location.pathname + location.search);
}

function gMostrarLogin(erro) {
  document.getElementById("g-app").classList.remove("visivel");
  const qr = document.getElementById("g-qr");
  if (qr) qr.classList.remove("visivel");
  document.getElementById("g-login").classList.add("visivel");
  gErro(erro || "");
}

function gErro(msg) {
  document.getElementById("g-login-erro").textContent = msg || "";
}

function gSair(expirou) {
  if (gToken) {
    fetch("/api/gerente/logout", {
      method: "POST", headers: { "X-Gerente-Token": gToken },
    }).catch(() => {});
  }
  gToken = "";
  sessionStorage.removeItem(G_CHAVE);
  if (gWs) { try { gWs.onclose = null; gWs.close(); } catch (e) {} gWs = null; }
  const el = document.getElementById("g-ws");
  el.textContent = "offline"; el.className = "g-ws off";
  gMostrarLogin(expirou ? "sessão encerrada — escaneie o QR Code novamente" : "");
}

function gAbrirApp(usuario) {
  if (!gUsuarioAtual) gUsuarioAtual = usuario || "";
  document.getElementById("g-user").textContent = gUsuarioAtual;
  document.getElementById("g-login").classList.remove("visivel");
  document.getElementById("g-app").classList.add("visivel");
  gConectarWS();
  gRecarregarSessao();
}

// ---------------------------------------------------------------- WebSocket
function gConectarWS() {
  if (gWs && gWs.readyState <= 1) return;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  gWs = new WebSocket(`${proto}://${location.host}/ws/gerente?token=${encodeURIComponent(gToken)}`);
  const el = document.getElementById("g-ws");
  gWs.onopen = () => { el.textContent = "● ao vivo"; el.className = "g-ws on"; };
  gWs.onclose = (ev) => {
    el.textContent = "● offline"; el.className = "g-ws off";
    if (ev && ev.code === 4401) { gSair(true); return; }
    setTimeout(() => { if (gToken) gConectarWS(); }, 2500);
  };
  gWs.onmessage = (ev) => gTratar(JSON.parse(ev.data));
}

function gTratar(ev) {
  if (ev.tipo === "snapshot") {
    gRenderDecoder(ev.decoder);
    gRenderSessao(ev.sessao);
    gRenderClassificacao(ev.classificacao || []);
    if (ev.pista) gAtualizarPista(ev.pista.bandeira, ev.pista.motivo);
    if (ev.tracada !== undefined) gRenderTracada(ev.tracada);
    return;
  }
  switch (ev.tipo) {
    case "tracada": gRenderTracada(ev.tracada || null); break;
    case "classificacao": gRenderClassificacao(ev.linhas || []); break;
    case "sessao":
      gRenderSessao({ ...(gSessao || {}), estado: ev.estado, pausada: ev.pausada });
      if (ev.classificacao) gRenderClassificacao(ev.classificacao);
      // re-busca o snapshot real (tempo_s/restante_s) — evita base defasada
      fetch("/api/status").then(r => r.json())
        .then(d => { if (d && d.sessao) gRenderSessao(d.sessao); }).catch(() => {});
      break;
    case "volta":
      gToast(`volta #${ev.numero} — ${ev.nome}: ${ev.tempo}s`, "ok"); break;
    case "bandeira": gAtualizarPista(ev.bandeira, ev.motivo); break;
    case "checkin": gPresentes = ev.presentes || []; gRenderCheckin(); break;
    case "anuncio": gToast(`📢 ${ev.texto}`); break;
    case "admin": gToast(ev.msg || "ação administrativa"); break;
  }
}

// ---------------------------------------------------------------- traçado da pista
let gTracada = null;

function gRenderTracada(tr) {
  gTracada = tr || null;
  const card = document.getElementById("g-track-card");
  if (!card) return;
  const exibir = !!(tr && tr.exibir && tr.exibir.gerente !== false);
  card.hidden = !exibir;
  if (!exibir) return;
  document.getElementById("g-track-nome").textContent = tr.pista_nome || "";
  document.getElementById("g-track-info").textContent =
    tr.comprimento_m ? `${tr.comprimento_m} m por volta` : "";
  gDesenharTracada();
}

function gDesenharTracada() {
  const c = document.getElementById("g-canvas-track");
  if (!c || c.hidden || !gTracada || c.clientWidth < 20) return;
  const ctx = c.getContext("2d");
  TC.desenhar(ctx, c.width = c.clientWidth, c.height = c.clientHeight, gTracada);
}

window.addEventListener("resize", () => gDesenharTracada());

// ---------------------------------------------------------------- sessão
let gCrono = { base: 0, restante: null, ref: performance.now(), correndo: false };

function gRenderDecoder(d) {
  if (!d) return;
  const led = document.getElementById("g-led");
  led.classList.toggle("on", !!d.conectado);
  document.getElementById("g-decoder").textContent =
    d.conectado ? `decoder ${(d.tipo || "").toUpperCase()}`.trim() : "decoder desconectado";
}

function gRenderSessao(s) {
  if (!s) return;
  gSessao = s;
  document.getElementById("g-estado").textContent = s.estado || "sem sessão";
  gCrono = { base: s.tempo_s || 0,
             restante: (typeof s.restante_s === "number" ? s.restante_s : null),
             ref: performance.now(),
             correndo: (["treino", "classificacao", "correndo"].includes(s.estado) && !s.pausada) };
  gPintarCrono(gCrono.restante != null ? gCrono.restante : gCrono.base);
}

function gPintarCrono(t) {
  const min = Math.floor(t / 60);
  document.getElementById("g-crono").textContent =
    `${min}:${(t - min * 60).toFixed(3).padStart(6, "0")}`;
}

setInterval(() => {
  if (!gCrono.correndo) return;
  const decorrido = (performance.now() - gCrono.ref) / 1000;
  const t = gCrono.restante != null
    ? Math.max(0, gCrono.restante - decorrido)   // corrida por tempo: regressiva
    : gCrono.base + decorrido;
  gPintarCrono(t);
}, 33);   // ~30 Hz: milésimos animando

// ---------------------------------------------------------------- classificação
function gRenderClassificacao(linhas) {
  gClassificacao = linhas || [];
  const maxV = gClassificacao.reduce((m, l) => Math.max(m, l.voltas || 0), 0);
  document.getElementById("g-voltas-tot").textContent = `${maxV} voltas`;
  const tb = document.querySelector("#g-tabela tbody");
  if (!gClassificacao.length) {
    tb.innerHTML = `<tr><td colspan="9" class="g-vazio">sem sessão ativa</td></tr>`;
    return;
  }
  tb.innerHTML = gClassificacao.map(l => `
    <tr class="${l.posicao === 1 ? "lider" : ""}">
      <td>${l.posicao}º</td>
      <td>${gEsc(l.nome)}${l.suspeita ? ' <span class="g-pill" style="color:#ff8a99">gato</span>' : ""}</td>
      <td>${l.voltas}</td>
      <td>${l.melhor || "-"}</td>
      <td>${l.velocidade || "-"}</td>
      <td>${l.ultima || "-"}</td>
      <td>${l.tempo || "-"}</td>
      <td>${l.gap || ""}</td>
      <td class="acoes">
        <button class="g-btn mini perigo" title="marcar gato" onclick="gGato(${l.piloto_id})">🚫</button>
        <button class="g-btn mini" title="desmarcar gato" onclick="gDesgato(${l.piloto_id})">♻</button>
        <button class="g-btn mini perigo" title="apagar última volta" onclick="gApagar(${l.piloto_id})">🗑</button>
        <button class="g-btn mini" title="adicionar volta manual" onclick="gAddVolta(${l.piloto_id})">➕</button>
      </td>
    </tr>`).join("");
}

function gGato(pid) { gAcao("voltas/marcar-gato", `?piloto_id=${pid}`); }
function gDesgato(pid) { gAcao("voltas/desmarcar-gato", `?piloto_id=${pid}`); }
function gApagar(pid) {
  if (confirm("Apagar a última volta deste piloto?")) gAcao("voltas/apagar", `?piloto_id=${pid}`);
}
function gAddVolta(pid) {
  const t = prompt("Tempo da volta manual (segundos) — ex.: 9.123");
  if (t == null) return;
  const v = parseFloat(String(t).replace(",", "."));
  if (!(v > 0)) { gToast("tempo inválido", "erro"); return; }
  gAcao("voltas/adicionar", `?piloto_id=${pid}&tempo_s=${v}`);
}

async function gAcao(caminho, params) {
  try {
    const r = await gApi(caminho, "POST", params);
    if (r && r.ok === false) gToast(r.erro || "não foi possível", "erro");
  } catch (e) { /* sessão expirada já tratada */ }
}

// ---------------------------------------------------------------- bandeiras
function gBandeira(cor) {
  if (cor) gBandeiraCor = cor;
  const motivo = document.getElementById("g-motivo").value.trim();
  gAtualizarPista(gBandeiraCor, motivo);            // resposta imediata
  gAcao("pista/bandeira",
        `?cor=${encodeURIComponent(gBandeiraCor)}&motivo=${encodeURIComponent(motivo)}`);
}

function gAtualizarPista(cor, motivo) {
  cor = cor || "verde";
  gBandeiraCor = cor;
  const textos = { verde: "pista livre", amarela: "atenção — bandeira amarela",
                   vermelha: "perigo — bandeira vermelha", fechada: "pista fechada" };
  const faixa = document.getElementById("g-faixa");
  faixa.className = "g-faixa" + (cor !== "verde" ? " " + cor : "");
  faixa.textContent = (textos[cor] || textos.verde) + (motivo ? ` · ${motivo}` : "");
  document.querySelectorAll(".g-bandeira").forEach(b =>
    b.classList.toggle("ativo", b.classList.contains(cor)));
  const campo = document.getElementById("g-motivo");
  if (document.activeElement !== campo) campo.value = motivo || "";
}

// ---------------------------------------------------------------- check-in
function gRenderCheckin() {
  document.getElementById("g-presentes-n").textContent = gPresentes.length;
  const box = document.getElementById("g-checkin");
  const ativos = gPilotos.filter(p => p.ativo);
  if (!ativos.length) { box.innerHTML = `<span class="g-hint">nenhum piloto ativo cadastrado</span>`; return; }
  box.innerHTML = ativos.map(p => {
    const on = gPresentes.includes(p.id);
    return `<label class="${on ? "on" : ""}">
      <input type="checkbox" ${on ? "checked" : ""} onchange="gCheckin(${p.id}, this.checked)">
      <span class="nome" title="${gEsc(p.nome)}">${gEsc(p.nome)}</span></label>`;
  }).join("");
}

async function gCheckin(pid, presente) {
  try {
    const r = await gApi("checkin", "POST", `?piloto_id=${pid}&presente=${presente}`);
    if (r.presentes) { gPresentes = r.presentes; gRenderCheckin(); }
  } catch (e) {}
}

async function gCheckinTodos(presente) {
  const ids = presente ? gPilotos.filter(p => p.ativo).map(p => p.id) : [];
  try {
    const r = await gApi("checkin/lote", "POST", "", { presentes: ids });
    if (r.presentes) { gPresentes = r.presentes; gRenderCheckin(); }
  } catch (e) {}
}

// ---------------------------------------------------------------- locução
async function gAnunciarPosicoes() {
  try {
    const r = await gApi("anunciar", "POST", "", { posicoes: true });
    gToast(r.ok ? "📢 lendo posições…" : (r.erro || "nada a anunciar"),
           r.ok ? "ok" : "erro");
  } catch (e) {}
}

function gFalar() {
  const campo = document.getElementById("g-anuncio");
  const t = campo.value.trim();
  if (!t) { gToast("escreva o anúncio", "erro"); return; }
  campo.value = "";
  gFalarTexto(t);
}

async function gFalarTexto(t) {
  try {
    const r = await gApi("anunciar", "POST", "", { texto: t });
    gToast(r.ok ? `🔊 ${t}` : (r.erro || "falha ao falar"), r.ok ? "ok" : "erro");
  } catch (e) {}
}

// ---------------------------------------------------------------- comandos
async function gComando(caminho, msgOk) {
  try {
    const r = await gApi(caminho, "POST");
    if (r && r.ok === false) { gToast("não foi possível executar", "erro"); return; }
    gToast(msgOk || "ok", "ok");
    gRecarregarSessao();
  } catch (e) {}
}

function gIniciar() {
  const tipo = document.getElementById("g-tipo").value;
  const tmin = parseFloat(document.getElementById("g-tempo-min").value) || 0;
  gComando(`sessao/iniciar?tipo=${encodeURIComponent(tipo)}&tempo_minimo_s=${tmin}`,
           "sessão iniciada");
}
const gLargada = () => gComando("sessao/largada", "🏁 largada!");
const gPausar = (p) => gComando(`sessao/pausar?pausar=${p}`, p ? "sessão pausada" : "sessão retomada");
function gFinalizar() {
  if (confirm("Finalizar a sessão atual?")) gComando("sessao/finalizar", "sessão finalizada");
}

async function gRecarregarSessao() {
  try {
    const d = await gApi("painel", "GET");
    const s = d.snapshot || {};
    if (s.sessao) gRenderSessao(s.sessao);
    if (s.decoder) gRenderDecoder(s.decoder);
    gRenderClassificacao(s.classificacao || []);
    if (s.tracada !== undefined) gRenderTracada(s.tracada);
    if (d.pilotos) gPilotos = d.pilotos;
    if (d.presentes) gPresentes = d.presentes;
    gRenderCheckin();
    if (d.bandeira) gAtualizarPista(d.bandeira, d.motivo);
  } catch (e) {}
}

// ---------------------------------------------------------------- util
function gEsc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---------------------------------------------------------------- QR Code de acesso
let gQRUrl = "";

function gAbrirQR() {
  document.getElementById("g-app").classList.remove("visivel");
  document.getElementById("g-qr").classList.add("visivel");
  // abrir NÃO gera um novo: mostra o QR atual (só "Gerar novo" rotaciona,
  // para não derrubar quem já entrou com o QR anterior)
  gCarregarQRAtual();
}

async function gCarregarQRAtual() {
  gQRErro("");
  let r;
  try {
    r = await gApi("qrcode/atual", "GET");
  } catch (e) { gQRErro("falha de comunicação com o servidor"); return; }
  if (r && r.vazio) {
    gAtualizarInfoQR();
    return;
  }
  if (!r || !r.ok) { gQRErro((r && r.erro) || "não foi possível carregar o QR Code"); return; }
  gMostrarQR(r);
}

function gFecharQR() {
  document.getElementById("g-qr").classList.remove("visivel");
  document.getElementById("g-app").classList.add("visivel");
}

function gQRErro(msg) {
  document.getElementById("g-qr-erro").textContent = msg || "";
}

async function gGerarQR() {
  gQRErro("");
  const dias = parseInt(document.getElementById("g-qr-dias").value, 10) || 30;
  let r;
  try {
    r = await gApi(`qrcode?dias=${dias}`, "POST");
  } catch (e) { gQRErro("falha de comunicação com o servidor"); return; }
  if (!r.ok) { gQRErro(r.erro || "não foi possível gerar o QR Code"); return; }
  gMostrarQR(r);
  if (r.substituidos) gToast(`🔁 ${r.substituidos} QR(s) anterior(es) revogado(s)`, "ok");
  else gToast("📱 QR Code gerado", "ok");
}

function gMostrarQR(r) {
  gQRUrl = r.url || "";
  gQRErro("");
  const img = document.getElementById("g-qr-img");
  const vazio = document.getElementById("g-qr-vazio");
  img.onerror = () => gQRErro("QR recebido do servidor, mas a imagem não exibiu " +
    "neste navegador — tente Chrome/Edge atualizado ou outro aparelho.");
  img.src = r.qrcode;
  img.hidden = false;
  vazio.hidden = true;
  document.getElementById("g-qr-url").textContent = gQRUrl;
  gAtualizarInfoQR();
  gListarConvitesQR();
}

function gAtualizarInfoQR() {
  if (!gQRUrl) { document.getElementById("g-qr-info").textContent = "—"; return; }
  document.getElementById("g-qr-info").textContent =
    "Quem escanear entra direto no painel, sem senha. O acesso pode ser "
    + "revogado aqui a qualquer momento.";
}

async function gListarConvitesQR() {
  let r;
  try { r = await gApi("qrcode/convites", "GET"); }
  catch (e) { return; }
  if (!r || !r.ok) return;
  const el = document.getElementById("g-qr-info");
  const n = (r.convites || []).length;
  if (!gQRUrl) el.textContent = "—";
  if (n) {
    const total = r.convites.reduce((s, c) => s + (c.restante_s || 0), 0) / r.convites.length;
    const horas = Math.round(total / 3600);
    el.textContent = `${n} QR Code(s) ativo(s) · validade média ${horas}h. `
      + "Quem escanear entra direto, sem senha. Revogue aqui quando quiser.";
  }
}

async function gRevogarQR() {
  if (!confirm("Revogar TODOS os QR Codes de acesso?\n\n"
    + "Os celulares já conectados continuam até a aba fechar. "
    + "A senha do gerente não muda.")) return;
  let r;
  try { r = await gApi("qrcode", "DELETE"); }
  catch (e) { gQRErro("falha de comunicação"); return; }
  if (!r.ok) { gQRErro(r.erro || "falha ao revogar"); return; }
  gQRUrl = "";
  const img = document.getElementById("g-qr-img");
  img.hidden = true; img.removeAttribute("src");
  document.getElementById("g-qr-vazio").hidden = false;
  document.getElementById("g-qr-url").textContent = "—";
  document.getElementById("g-qr-info").textContent = "—";
  gToast(`⛔ ${r.revogados} QR Code(s) revogado(s)`, "ok");
}

async function gCopiarEndereco() {
  if (!gQRUrl) { gToast("gere um QR Code primeiro", "erro"); return; }
  try {
    await navigator.clipboard.writeText(gQRUrl);
    gToast("📋 endereço copiado", "ok");
  } catch (e) {
    // sem permissão de clipboard: seleciona o texto para cópia manual
    const alvo = document.getElementById("g-qr-url");
    const sel = window.getSelection();
    const faixa = document.createRange();
    faixa.selectNodeContents(alvo);
    sel.removeAllRanges(); sel.addRange(faixa);
    gToast("selecione e copie o endereço acima", "erro");
  }
}

let gToastTimer = null;
function gToast(msg, tipo) {
  const el = document.getElementById("g-toast");
  el.textContent = msg;
  el.className = "g-toast show" + (tipo ? " " + tipo : "");
  clearTimeout(gToastTimer);
  gToastTimer = setTimeout(() => { el.className = "g-toast"; }, 3200);
}

window.addEventListener("DOMContentLoaded", gInit);

/* KChrono — Telão 4K (Fase 4): semáforo sincronizado, locução, gráficos,
   estimativas e track view. Uma única linha do tempo comanda luzes, números,
   bipes e falas — sincronizado por construção. */
"use strict";

let ws = null;
let estadoAtual = "parado";
let ultimaLinhas = [];
let ultimasVoltas = { pilotos: [], parametros: { duracao: 10, criterio: "tempo" } };
let ultimoTempoSessao = null;
let largadaClock = null;
let graficoRitmo = null, graficoPosicoes = null, trackLoop = null;
let tabAtual = "tv-class";

// ---------------------------------------------------------------- áudio/fala
let audioCtx = null;
function beep(freq = 440, dur = 0.12, vol = 0.22) {
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === "suspended") audioCtx.resume();
    const o = audioCtx.createOscillator(), g = audioCtx.createGain();
    o.frequency.value = freq; o.type = "square"; g.gain.value = vol;
    o.connect(g); g.connect(audioCtx.destination);
    o.start();
    setTimeout(() => { try { o.stop(); } catch (e) {} }, dur * 1000);
  } catch (e) {}
}

function falar(texto) {
  try {
    const u = new SpeechSynthesisUtterance(texto);
    u.lang = "pt-BR";
    const vozes = speechSynthesis.getVoices();
    const pt = vozes.find(v => (v.lang || "").toLowerCase().startsWith("pt"));
    if (pt) u.voice = pt;
    u.rate = 1.1; u.volume = 1;
    speechSynthesis.speak(u);
  } catch (e) { /* sem voz no dispositivo */ }
}

// ---------------------------------------------------------------- WebSocket
function conectarWS() {
  if (ws && ws.readyState <= 1) return;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  const st = document.getElementById("ws-st");
  ws.onopen = () => { st.textContent = "● ao vivo"; st.classList.add("on"); };
  ws.onclose = () => {
    st.textContent = "● offline"; st.classList.remove("on");
    setTimeout(conectarWS, 2000);
  };
  ws.onmessage = (ev) => tratarEvento(JSON.parse(ev.data));
}

function tratarEvento(ev) {
  if (ev.tipo === "snapshot") {
    if (ev.sessao && ev.sessao.tempo_s != null) ultimoTempoSessao = ev.sessao.tempo_s;
    if (ev.sessao && ev.sessao.parametros) ultimasVoltas.parametros = ev.sessao.parametros;
    renderSessao(ev.sessao);
    renderClassificacao(ev.classificacao || []);
    renderBandeira(ev.pista);
    return;
  }
  switch (ev.tipo) {
    case "sessao":
      renderSessao(ev);
      if (ev.classificacao) renderClassificacao(ev.classificacao);
      break;
    case "bandeira":
      renderBandeira(ev);
      break;
    case "classificacao":
    case "classificacao":
      renderClassificacao(ev.linhas || []);
      break;
    case "voltas":
      ultimasVoltas = ev;
      if (tabAtual === "tv-ritmo") desenharRitmo();
      if (tabAtual === "tv-posicoes") desenharPosicoes();
      if (tabAtual === "tv-track") desenharTrack();
      break;
  }
}

// ---------------------------------------------------------------- bandeira
function renderBandeira(p) {
  const el = document.getElementById("bandeira-banner");
  if (!el) return;
  const cor = (p && (p.bandeira || p.cor)) || "verde";
  const textos = { verde: "PISTA LIVRE", amarela: "BANDEIRA AMARELA",
                   vermelha: "BANDEIRA VERMELHA", fechada: "PISTA FECHADA" };
  if (cor === "verde") { el.hidden = true; el.textContent = ""; return; }
  el.hidden = false;
  el.className = "bandeira-banner " + cor;
  el.textContent = (textos[cor] || "") + (p && p.motivo ? ` — ${p.motivo}` : "");
}

// ---------------------------------------------------------------- telas
function renderSessao(s) {
  const estado = s.estado || "parado";
  if (estado === estadoAtual) return;
  estadoAtual = estado;
  const largada = document.getElementById("tela-largada");
  const corrida = document.getElementById("tela-corrida");
  if (estado === "largada") {
    largada.classList.add("visivel");
    corrida.classList.remove("visivel");
    iniciarContagem();
  } else {
    largada.classList.remove("visivel");
    corrida.classList.add("visivel");
    pararContagem();
  }
}

function iniciarContagem() {
  pararContagem();
  const contagem = document.getElementById("contagem");
  const subtitulo = document.getElementById("subtitulo-largada");
  const luzes = [...document.querySelectorAll("#tela-largada .luz")];
  contagem.classList.remove("vai");
  contagem.textContent = "ATENÇÃO, PILOTOS!";
  subtitulo.textContent = "preparem-se para a largada…";
  luzes.forEach(l => { l.classList.remove("on"); l.style.background = "#181f33"; });
  beep(660, 0.18, 0.2);
  falar("Atenção pilotos, preparem-se para a largada!");

  const DUR_FRASE = 3200;
  const tLuzes = DUR_FRASE;
  const luzDur = luzes.map(() => 600 + Math.random() * 600);
  const tFimLuzes = tLuzes + luzDur.reduce((a, b) => a + b, 0);
  const tContagem = tFimLuzes + 400;
  const tFim = tContagem + 5000 + 2500;

  const t0 = performance.now();
  let luzAcesa = -1, numAtual = null;

  function tick() {
    const t = performance.now() - t0;
    if (t >= tLuzes && t < tFimLuzes) {
      let acc = tLuzes;
      for (let i = 0; i < luzes.length; i++) {
        const fim = acc + luzDur[i];
        const acesa = t >= acc && t < fim;
        if (acesa && luzAcesa !== i) { luzAcesa = i; beep(520, 0.09, 0.18); }
        luzes[i].classList.toggle("on", acesa);
        luzes[i].style.background = acesa ? luzes[i].style.color : "#181f33";
        acc = fim;
      }
    } else if (t >= tFimLuzes) {
      luzes.forEach(l => { l.classList.remove("on"); l.style.background = "#181f33"; });
    }
    if (t >= tContagem) {
      const n = 5 - Math.floor((t - tContagem) / 1000);
      if (n > 0 && n !== numAtual) {
        numAtual = n;
        contagem.textContent = n;
        subtitulo.textContent = "";
        beep(600, 0.08, 0.15);
        falar(String(n));
      }
      if (n <= 0 && numAtual !== 0) {
        numAtual = 0;
        contagem.textContent = "VAI!";
        contagem.classList.add("vai");
        beep(880, 0.5, 0.3);
        falar("Vai!");
      }
    }
    if (t < tFim) largadaClock = requestAnimationFrame(tick);
  }
  largadaClock = requestAnimationFrame(tick);
}

function pararContagem() {
  if (largadaClock) cancelAnimationFrame(largadaClock);
  largadaClock = null;
  const luzes = document.querySelectorAll("#tela-largada .luz");
  luzes.forEach(l => { l.classList.remove("on"); l.style.background = "#181f33"; });
}

// ---------------------------------------------------------------- abas
function tabTelao(btn, id) {
  document.querySelectorAll(".abas-telao button").forEach(b => b.classList.remove("on"));
  btn.classList.add("on");
  document.querySelectorAll(".painel").forEach(p => p.classList.remove("on"));
  document.getElementById(id).classList.add("on");
  tabAtual = id;
  if (id === "tv-ritmo") desenharRitmo();
  if (id === "tv-posicoes") desenharPosicoes();
  if (id === "tv-track") iniciarTrack();
  else pararTrack();
}

function telaCheia() {
  const el = document.documentElement;
  if (!document.fullscreenElement) (el.requestFullscreen || el.webkitRequestFullscreen).call(el);
  else document.exitFullscreen();
}

// ---------------------------------------------------------------- classificação
function fmtTempo(s) {
  if (s == null || isNaN(s)) return "-";
  const min = Math.floor(s / 60);
  return `${min}:${(s - min * 60).toFixed(3).padStart(6, "0")}`;
}

function renderClassificacao(linhas) {
  ultimaLinhas = linhas;
  const lider = linhas[0];
  const record = linhas.reduce((m, l) =>
    (l.melhor_us != null && (m == null || l.melhor_us < m)) ? l.melhor_us : m, null);

  document.getElementById("t-laps").textContent = lider ? lider.voltas : 0;
  document.getElementById("t-record").textContent = record ? fmtTempo(record / 1e6) : "—";
  document.getElementById("total-pilotos").textContent =
    linhas.filter(l => l.voltas > 0).length || linhas.length;
  document.getElementById("hora-atual").textContent = new Date().toLocaleTimeString("pt-BR");
  document.getElementById("record-pista").textContent = record ? fmtTempo(record / 1e6) : "—";

  const podio = document.getElementById("podio");
  podio.innerHTML = linhas.length ? linhas.slice(0, 3).map((l, i) => `
    <div class="lugar p${i + 1}">
      <div class="pos">${i + 1}º LUGAR ${i === 0 ? "🏆" : ""}</div>
      <div class="nome">${l.nome}</div>
      <div class="numeracao">${i + 1}</div>
      <div class="dados">
        <div>Melhor<b>${l.melhor || "-"}</b></div>
        <div>Voltas<b>${l.voltas}</b></div>
        <div>Total<b>${l.tempo || "-"}</b></div>
      </div>
    </div>`).join("") : "";

  // tabela com Ritmo (média) e EST (estimativa: total + ritmo)
  const corpo = linhas.map(l => {
    const totalS = l.tempo ? parseFloat(l.tempo.split(":")[0]) * 60 + parseFloat(l.tempo.split(":")[1]) : null;
    const ritmoS = l.media && l.media !== "-"
      ? parseFloat(l.media.split(":")[0]) * 60 + parseFloat(l.media.split(":")[1]) : null;
    const estS = (totalS != null && ritmoS != null) ? totalS + ritmoS : null;
    return `<tr class="${l.posicao === 1 ? "lider" : ""}">
      <td class="pos">${l.posicao}º</td>
      <td>${l.numero || "-"}</td>
      <td>${l.nome}${l.suspeita ? '<span class="badge" style="background:rgba(230,57,70,.2);color:#e63946">gato</span>' : ""}
        ${l.posicao === 1 ? '<span class="badge lider">líder</span>' : ""}</td>
      <td>${l.voltas}</td>
      <td>${l.tempo || "-"}</td>
      <td>${l.intervalo || "-"}</td>
      <td>${l.gap || ""}</td>
      <td>${l.ultima || "-"}</td>
      <td>${l.melhor || "-"}${l.melhor_us === record ? '<span class="badge melhor">record</span>' : ""}</td>
      <td>${l.media && l.media !== "-" ? l.media : "-"}</td>
      <td>${estS != null ? fmtTempo(estS) : "-"}</td>
    </tr>`;
  }).join("");
  document.querySelector("#tabela-telao tbody").innerHTML =
    corpo || '<tr><td colspan="11" style="color:var(--mut)">aguardando largada…</td></tr>';
}

// ---------------------------------------------------------------- gráficos
const CORES = ["#ffb703", "#3a86ff", "#2ec4b6", "#ff006e", "#a4d007", "#c0c0c0",
               "#ff8c42", "#bb9af7", "#7aa2f7", "#f7768e", "#9ece6a", "#e0af68"];

function dadosGraficos() {
  const pilotos = (ultimasVoltas.pilotos || []).slice(0, 12);
  return pilotos.map((p, i) => ({
    nome: p.nome,
    cor: CORES[i % CORES.length],
    x: p.voltas.map(v => v.numero),
    y: p.voltas.map(v => v.tempo),
  }));
}

function posicoesPorVolta() {
  // reconstrói a posição volta a volta de cada piloto
  const pilotos = (ultimasVoltas.pilotos || []).slice(0, 12);
  const maxVoltas = Math.max(0, ...pilotos.map(p => p.voltas.length));
  const series = pilotos.map((p, i) => ({ nome: p.nome, cor: CORES[i % CORES.length], pontos: [] }));
  for (let n = 1; n <= maxVoltas; n++) {
    const ranking = pilotos
      .filter(p => p.voltas.filter(v => v.numero <= n).length >= n)
      .map(p => ({
        nome: p.nome,
        parcial: p.voltas.filter(v => v.numero <= n).reduce((s, v) => s + v.tempo, 0),
      }))
      .sort((a, b) => a.parcial - b.parcial);
    ranking.forEach((r, idx) => {
      const s = series.find(s => s.nome === r.nome);
      if (s) s.pontos.push({ x: n, y: idx + 1 });
    });
  }
  return series;
}

function desenharRitmo() {
  const ctx = document.getElementById("grafico-ritmo");
  if (!ctx || typeof Chart === "undefined") return;
  const dados = dadosGraficos();
  if (graficoRitmo) graficoRitmo.destroy();
  graficoRitmo = new Chart(ctx, {
    type: "line",
    data: { datasets: dados.map(d => ({
      label: d.nome, data: d.x.map((xv, i) => ({ x: xv, y: d.y[i] })),
      borderColor: d.cor, backgroundColor: d.cor, tension: 0.2, pointRadius: 3,
    })) },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: "#d0d7e3" } } },
      scales: {
        x: { title: { display: true, text: "volta", color: "#8492a6" },
             ticks: { color: "#8492a6" }, grid: { color: "#1a2438" } },
        y: { title: { display: true, text: "tempo (s)", color: "#8492a6" },
             ticks: { color: "#8492a6" }, grid: { color: "#1a2438" } },
      },
    },
  });
}

function desenharPosicoes() {
  const ctx = document.getElementById("grafico-posicoes");
  if (!ctx || typeof Chart === "undefined") return;
  const series = posicoesPorVolta();
  if (graficoPosicoes) graficoPosicoes.destroy();
  graficoPosicoes = new Chart(ctx, {
    type: "line",
    data: { datasets: series.map(s => ({
      label: s.nome, data: s.pontos, borderColor: s.cor,
      backgroundColor: s.cor, stepped: true, pointRadius: 3,
    })) },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: "#d0d7e3" } } },
      scales: {
        x: { title: { display: true, text: "volta", color: "#8492a6" },
             ticks: { color: "#8492a6" }, grid: { color: "#1a2438" } },
        y: { reverse: true, min: 1,
             title: { display: true, text: "posição", color: "#8492a6" },
             ticks: { color: "#8492a6", precision: 0 }, grid: { color: "#1a2438" } },
      },
    },
  });
}

// ---------------------------------------------------------------- track view
function iniciarTrack() {
  pararTrack();
  const canvas = document.getElementById("canvas-track");
  if (!canvas) return;
  function loop() {
    desenharTrack();
    trackLoop = requestAnimationFrame(loop);
  }
  loop();
}

function pararTrack() {
  if (trackLoop) cancelAnimationFrame(trackLoop);
  trackLoop = null;
}

function desenharTrack() {
  const canvas = document.getElementById("canvas-track");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const W = canvas.width = canvas.clientWidth;
  const H = canvas.height = canvas.clientHeight;
  ctx.clearRect(0, 0, W, H);

  // traçado default (oval estilo pista) — editável na Fase 5
  ctx.strokeStyle = "#22304d";
  ctx.lineWidth = 26;
  ctx.beginPath();
  ctx.ellipse(W / 2, H / 2, W * 0.36, H * 0.34, 0, 0, Math.PI * 2);
  ctx.stroke();
  ctx.strokeStyle = "#3a86ff";
  ctx.lineWidth = 2;
  ctx.setLineDash([8, 8]);
  ctx.beginPath();
  ctx.ellipse(W / 2, H / 2, W * 0.36, H * 0.34, 0, 0, Math.PI * 2);
  ctx.stroke();
  ctx.setLineDash([]);

  // linha de largada/chegada
  ctx.fillStyle = "#fff";
  ctx.fillRect(W / 2 + W * 0.36 - 3, H / 2 - 13, 6, 26);

  // carros: progresso = voltas / voltas do líder
  const linhas = ultimaLinhas.filter(l => l.voltas > 0);
  if (!linhas.length) {
    ctx.fillStyle = "#5c6470";
    ctx.font = "16px Segoe UI";
    ctx.textAlign = "center";
    ctx.fillText("aguardando passagens…", W / 2, H / 2);
    return;
  }
  const maxV = Math.max(...linhas.map(l => l.voltas));
  linhas.forEach((l, i) => {
    const frac = (l.voltas % 1 === 0 ? l.voltas - 0.02 : l.voltas) / Math.max(maxV, 1);
    const ang = -Math.PI / 2 + frac * Math.PI * 2;
    const x = W / 2 + Math.cos(ang) * W * 0.36;
    const y = H / 2 + Math.sin(ang) * H * 0.34;
    ctx.fillStyle = CORES[l.posicao - 1] || "#fff";
    ctx.beginPath();
    ctx.arc(x, y, 9, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#fff";
    ctx.font = "bold 11px Segoe UI";
    ctx.textAlign = "center";
    ctx.fillText(String(l.posicao), x, y + 4);
  });
}

// race time (tique visual; oficial vem do servidor no snapshot)
setInterval(() => {
  const s = ultimoTempoSessao;
  if (s != null) {
    const min = Math.floor(s / 60), seg = Math.floor(s % 60);
    const cs = Math.floor((s % 1) * 100);
    document.getElementById("t-race").textContent =
      `${String(min).padStart(2, "0")}:${String(seg).padStart(2, "0")}:${String(cs).padStart(2, "0")}`;
  }
}, 250);

conectarWS();

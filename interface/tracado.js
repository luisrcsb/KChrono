/* KChrono — geometria e desenho do traçado de pista (compartilhado pelo
   editor (Admin), painel do operador, telão e gerente celular).

   Modelo salvo em pistas.tracado (JSON):
   {
     "pontos":   [{"x": 120, "y": 300, "curva": {"raio": 80}}],  // unidades de desenho
     "fechada":  true,
     "largada":  {"x": 120, "y": 300, "ang": 0},   // ponto 0 (laco de leitura)
     "grid":     {"x": 60, "y": 300, "ang": 0, "colunas": 2, "vagas": 10},
     "largura":  {"base": 1.0, "inicio": 1.0, "fim": 0.8},  // metros (perfil da volta)
     "comprimento_m": 120.0,                              // comprimento real (estatisticas)
     "exibir":   {"telao": true, "operador": true, "gerente": true, "simulador": true}
   }

   A largura em metros e convertida para pixels via comprimento_m: a escala do
   desenho = comprimento do tracado em unidades / comprimento real em metros.

   Visual: pista cinza escuro com contorno, bordas internas xadrez
   vermelho/branco (1 segmento por metro real), setas do sentido dos carros,
   linha de chegada xadrez e grid alinhado a largura da pista. */
"use strict";

const TC = (() => {

  function norm(x, y) {
    const d = Math.hypot(x, y) || 1;
    return { x: x / d, y: y / d };
  }

  function angEntre(u, v) {
    return Math.acos(Math.max(-1, Math.min(1, u.x * v.x + u.y * v.y)));
  }

  // raio maximo tangente as duas retas do canto (85% do que cabe)
  function raioAutoCanto(A, B, C) {
    if (!A || !B || !C) return 0;
    const u = norm(A.x - B.x, A.y - B.y);
    const w = norm(C.x - B.x, C.y - B.y);
    const teta = angEntre(u, w);
    if (!(teta > 0.15) || teta > Math.PI - 0.05) return 0;
    const l1 = Math.hypot(A.x - B.x, A.y - B.y);
    const l2 = Math.hypot(C.x - B.x, C.y - B.y);
    const tMax = Math.min(l1, l2) / 2;
    return Math.round(tMax * 0.85 * Math.tan(teta / 2));
  }

  // arredonda o vertice B entre as retas A->B e B->C
  function calcularCanto(A, B, C, curva) {
    const u = norm(A.x - B.x, A.y - B.y);   // de B ate A
    const w = norm(C.x - B.x, C.y - B.y);   // de B ate C
    const teta = angEntre(u, w);
    if (!(teta > 0.15) || teta > Math.PI - 0.05) return null;
    const l1 = Math.hypot(A.x - B.x, A.y - B.y);
    const l2 = Math.hypot(C.x - B.x, C.y - B.y);
    const tMax = Math.min(l1, l2) / 2;
    let t = (curva.raio || 0) / Math.tan(teta / 2);
    if (!(t > 0.5)) return null;
    t = Math.min(t, tMax);
    const r = t * Math.tan(teta / 2);
    const T1 = { x: B.x + u.x * t, y: B.y + u.y * t };
    const T2 = { x: B.x + w.x * t, y: B.y + w.y * t };
    const bis = norm(u.x + w.x, u.y + w.y);
    const centro = { x: B.x + bis.x * (r / Math.sin(teta / 2)),
                     y: B.y + bis.y * (r / Math.sin(teta / 2)) };
    const a0 = Math.atan2(T1.y - centro.y, T1.x - centro.x);
    let a1 = Math.atan2(T2.y - centro.y, T2.x - centro.x);
    let delta = a1 - a0;
    while (delta > Math.PI) delta -= 2 * Math.PI;
    while (delta < -Math.PI) delta += 2 * Math.PI;
    return { T1, T2, centro, a0, delta, r, graus: Math.round(Math.abs(delta) * 180 / Math.PI) };
  }

  // amostra o tracado (retas + cantos arredondados) -> [{x,y,d}] (d = percurso acumulado)
  function flatten(tr, passo = 5) {
    const pts = (tr && tr.pontos) || [];
    const n = pts.length;
    if (n < 2) return [];
    const fechado = !!(tr.fechada) && n > 2;
    const ligas = fechado ? n : n - 1;

    // dados de canto por vertice
    const cantos = new Array(n).fill(null);
    for (let k = 0; k < ligas; k++) {
      const i = k % n;
      const j = (k + 1) % n;
      const B = pts[j];
      if (!B.curva || !(B.curva.raio > 0)) continue;
      if (!fechado && (j === 0 || j === n - 1)) continue;
      cantos[j] = calcularCanto(pts[i], B, pts[(j + 1) % n], B.curva);
    }

    const saida = [];
    let d = 0;
    function push(x, y) {
      const ant = saida[saida.length - 1];
      if (ant) d += Math.hypot(x - ant.x, y - ant.y);
      saida.push({ x, y, d });
    }
    function retaAte(alvo) {
      const ant = saida[saida.length - 1];
      if (!ant) { push(alvo.x, alvo.y); return; }
      const dx = alvo.x - ant.x, dy = alvo.y - ant.y;
      const dist = Math.hypot(dx, dy);
      const passos = Math.max(1, Math.ceil(dist / passo));
      for (let p = 1; p <= passos; p++) push(ant.x + dx * p / passos, ant.y + dy * p / passos);
    }
    function arcoAte(c) {
      const compr = Math.abs(c.delta) * c.r;
      const passos = Math.max(3, Math.ceil(compr / passo));
      for (let p = 1; p <= passos; p++) {
        const a = c.a0 + c.delta * (p / passos);
        push(c.centro.x + Math.cos(a) * c.r, c.centro.y + Math.sin(a) * c.r);
      }
    }

    // pista fechada com canto no vertice 0: comeca depois do arco dele
    const c0 = fechado ? cantos[0] : null;
    if (c0) push(c0.T2.x, c0.T2.y);
    else push(pts[0].x, pts[0].y);

    for (let k = 0; k < ligas; k++) {
      const j = (k + 1) % n;
      const c = cantos[j];
      if (c) { retaAte(c.T1); arcoAte(c); }
      else retaAte(pts[j]);
    }
    return saida;
  }

  // comprimento bruto do polilinha (sem cantos) — calibra escala metros
  function comprimentoBruto(tr) {
    const pts = (tr && tr.pontos) || [];
    const n = pts.length;
    if (n < 2) return 0;
    const ligas = tr.fechada ? n : n - 1;
    let t = 0;
    for (let k = 0; k < ligas; k++) {
      const a = pts[k % n], b = pts[(k + 1) % n];
      t += Math.hypot(a.x - b.x, a.y - b.y);
    }
    return t;
  }

  // largura em metros na fracao da volta (0 = largada; perfil inicio->base->fim)
  function larguraEm(tr, frac) {
    const lg = tr.largura || {};
    const base = Number(lg.base) || 1;
    const ini = Number(lg.inicio) || base;
    const fim = Number(lg.fim) || base;
    const u = ((frac % 1) + 1) % 1;
    if (u < 0.5) return ini + (base - ini) * (u / 0.5);
    return base + (fim - base) * ((u - 0.5) / 0.5);
  }

  /* Desenha o tracado no canvas. opts:
       { mundo: {w,h} }  -> usa mapeamento direto mundo->tela (editor)
       { pontos: true }  -> desenha alcas dos vertices (editor)
       { largura: false }-> traco uniforme (mini-mapa sem escala) */
  function desenhar(ctx, W, H, tr, opts = {}) {
    if (!opts.semLimpar) ctx.clearRect(0, 0, W, H);
    if (!tr || !tr.pontos || tr.pontos.length < 2) return null;
    const linhas = flatten(tr);
    if (linhas.length < 2) return null;

    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const p of linhas) {
      if (p.x < minX) minX = p.x;
      if (p.x > maxX) maxX = p.x;
      if (p.y < minY) minY = p.y;
      if (p.y > maxY) maxY = p.y;
    }
    let esc, ox, oy;
    if (opts.mundo) {
      esc = Math.min(W / opts.mundo.w, H / opts.mundo.h);
      ox = (W - opts.mundo.w * esc) / 2;
      oy = (H - opts.mundo.h * esc) / 2;
    } else {
      const marg = 20;
      esc = Math.min((W - marg * 2) / Math.max(1, maxX - minX),
                     (H - marg * 2) / Math.max(1, maxY - minY));
      ox = (W - (maxX - minX) * esc) / 2 - minX * esc;
      oy = (H - (maxY - minY) * esc) / 2 - minY * esc;
    }
    const px = p => ({ x: p.x * esc + ox, y: p.y * esc + oy });

    const lenUnid = linhas[linhas.length - 1].d || 1;
    const compM = Number(tr.comprimento_m) || 0;
    const bruto = comprimentoBruto(tr);
    const unidPorM = (compM > 0 && bruto > 0) ? lenUnid / compM : 0;

    // fracao da largada (ancora do perfil de largura) = ponto do percurso
    // mais proximo da linha de largada
    let fLarg = 0, iLarg = 0;
    if (tr.largada) {
      let melhor = Infinity;
      linhas.forEach((p, i) => {
        const dd = (p.x - tr.largada.x) ** 2 + (p.y - tr.largada.y) ** 2;
        if (dd < melhor) { melhor = dd; fLarg = p.d / lenUnid; iLarg = i; }
      });
    }

    // direcao local da pista numa amostra (sentido da corrida)
    function dirNaAmostra(i, angRef) {
      const a = linhas[Math.max(0, i - 1)];
      const b = linhas[Math.min(linhas.length - 1, i + 1)];
      let dir = { x: b.x - a.x, y: b.y - a.y };
      if (Math.hypot(dir.x, dir.y) < 0.001) {
        dir = { x: Math.cos((angRef || 0) * Math.PI / 180),
                y: Math.sin((angRef || 0) * Math.PI / 180) };
      }
      return norm(dir.x, dir.y);
    }

    const variavel = unidPorM > 0 && opts.largura !== false;
    const larguraPx = frac => variavel
      ? Math.max(3, larguraEm(tr, frac) * unidPorM * esc)
      : 20;
    const pxPorM = unidPorM * esc;   // pixels de tela por metro real

    const traco = pts => {
      ctx.beginPath();
      const a = px(pts[0]);
      ctx.moveTo(a.x, a.y);
      for (let i = 1; i < pts.length; i++) {
        const b = px(pts[i]);
        ctx.lineTo(b.x, b.y);
      }
    };

    // pista: passadas com largura quantizada (0,5 px) para poupar draw calls
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    const trechos = [];
    let run = [linhas[0]];
    let qLarg = -1;
    for (let i = 1; i < linhas.length; i++) {
      const f = ((linhas[i].d / lenUnid) - fLarg + 1) % 1;
      const q = Math.max(3, Math.round(larguraPx(f) * 2) / 2);
      if (q !== qLarg) {
        if (run.length > 1) trechos.push({ pts: run, w: qLarg });
        run = [linhas[i - 1]];
        qLarg = q;
      }
      run.push(linhas[i]);
    }
    if (run.length > 1) trechos.push({ pts: run, w: qLarg });

    // contorno escuro + superficie cinza escuro
    ctx.strokeStyle = "#101318";
    for (const t of trechos) { ctx.lineWidth = t.w + 3; traco(t.pts); ctx.stroke(); }
    ctx.strokeStyle = "#3d434c";
    for (const t of trechos) { ctx.lineWidth = t.w; traco(t.pts); ctx.stroke(); }

    // eixo central tracejado
    ctx.strokeStyle = "rgba(120,165,255,0.45)";
    ctx.lineWidth = 1.5;
    ctx.setLineDash([8, 10]);
    traco(linhas);
    if (tr.fechada) ctx.closePath();
    ctx.stroke();
    ctx.setLineDash([]);

    // bordas internas xadrez vermelho/branco — 1 segmento por metro real
    if (variavel && pxPorM >= 8) {
      const kerbW = frac => Math.max(3, Math.min(12, larguraPx(frac) * 0.22));
      for (const lado of [1, -1]) {
        const borda = [];
        for (let i = 0; i < linhas.length; i++) {
          const dir = dirNaAmostra(i, tr.largada && tr.largada.ang);
          const perp = { x: -dir.y * lado, y: dir.x * lado };
          const f = ((linhas[i].d / lenUnid) - fLarg + 1) % 1;
          const off = larguraPx(f) / 2 - kerbW(f) / 2;
          borda.push({ x: linhas[i].x + perp.x * off, y: linhas[i].y + perp.y * off,
                       d: linhas[i].d, f });
        }
        // quebra nos limites exatos de cada metro (alterna vermelho/branco)
        const met = unidPorM;
        const segs = [];
        let atual = null;
        const empurra = p => {
          if (atual && atual.cor === p.cor) atual.pts.push(p);
          else { atual = { cor: p.cor, pts: [p] }; segs.push(atual); }
        };
        for (let i = 0; i < borda.length - 1; i++) {
          const a = borda[i], b = borda[i + 1];
          const corA = Math.floor(a.d / met) % 2;
          empurra({ x: a.x, y: a.y, d: a.d, f: a.f, cor: corA });
          const prox = (Math.floor(a.d / met) + 1) * met;
          if (prox < b.d) {
            const t = (prox - a.d) / (b.d - a.d);
            empurra({ x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t, d: prox,
                      f: a.f + (b.f - a.f) * t, cor: Math.floor(prox / met) % 2 });
          }
        }
        const ult = borda[borda.length - 1];
        empurra({ x: ult.x, y: ult.y, d: ult.d, f: ult.f, cor: Math.floor(ult.d / met) % 2 });
        ctx.lineCap = "butt";
        for (const s of segs) {
          if (s.pts.length < 2) continue;
          ctx.strokeStyle = s.cor === 0 ? "#d23b3b" : "#f2f4f8";
          ctx.lineWidth = kerbW(s.pts[0].f);
          traco(s.pts);
          ctx.stroke();
        }
      }
      ctx.lineCap = "round";
    }

    // setas do sentido dos carros (a cada volta/N metros)
    if (variavel && pxPorM >= 10 && compM > 0) {
      const passoM = Math.max(3, Math.round(compM / 9));
      const passoD = passoM * unidPorM;
      let proxD = passoD * 0.5;
      ctx.strokeStyle = "rgba(240,244,250,0.6)";
      ctx.lineWidth = 2;
      for (let i = 1; i < linhas.length - 1; i++) {
        if (linhas[i].d < proxD) continue;
        proxD = linhas[i].d + passoD;
        const dir = dirNaAmostra(i, tr.largada && tr.largada.ang);
        const perp = { x: -dir.y, y: dir.x };
        const p = linhas[i];
        const f = ((p.d / lenUnid) - fLarg + 1) % 1;
        const s = Math.max(4, Math.min(11, larguraPx(f) * 0.28));
        const q = px(p);
        const ponta = { x: q.x + dir.x * s * 0.9, y: q.y + dir.y * s * 0.9 };
        ctx.beginPath();
        ctx.moveTo(ponta.x, ponta.y);
        ctx.lineTo(q.x - dir.x * s * 0.5 + perp.x * s * 0.7,
                   q.y - dir.y * s * 0.5 + perp.y * s * 0.7);
        ctx.moveTo(ponta.x, ponta.y);
        ctx.lineTo(q.x - dir.x * s * 0.5 - perp.x * s * 0.7,
                   q.y - dir.y * s * 0.5 - perp.y * s * 0.7);
        ctx.stroke();
      }
    }

    // linha de chegada (xadrez de verdade, cruzando a pista)
    if (tr.largada) {
      // projetada no caminho amostrado: bate com a fracao 0 do perfil de largura
      const p = px(linhas[iLarg]);
      const dir = dirNaAmostra(iLarg, tr.largada.ang);
      const perp = norm(-dir.y, dir.x);
      const larg = larguraPx(0);
      const cols = Math.max(6, Math.min(16, Math.round(larg / 5)));
      const colsPar = cols % 2 ? cols + 1 : cols;
      const cw = larg / colsPar;
      const prof = Math.max(3, Math.min(7, larg * 0.13));
      for (let r = 0; r < 2; r++) {
        for (let c = 0; c < colsPar; c++) {
          ctx.fillStyle = (r + c) % 2 ? "#f2f4f8" : "#14171c";
          const t0 = (c - colsPar / 2) * cw;
          const d0 = prof * 0.5 - r * prof;
          const pt = (tx, dd) => ({ x: p.x + perp.x * tx + dir.x * dd,
                                    y: p.y + perp.y * tx + dir.y * dd });
          const A = pt(t0, d0), B = pt(t0 + cw, d0);
          const C = pt(t0 + cw, d0 - prof), D = pt(t0, d0 - prof);
          ctx.beginPath();
          ctx.moveTo(A.x, A.y); ctx.lineTo(B.x, B.y);
          ctx.lineTo(C.x, C.y); ctx.lineTo(D.x, D.y);
          ctx.closePath();
          ctx.fill();
        }
      }
    }

    // grid (colunas x vagas, atras da linha de largada, no sentido contrario)
    if (tr.grid && tr.grid.colunas >= 1) {
      const g = tr.grid;
      let iG = 0, mg = Infinity;
      linhas.forEach((p, i) => {
        const dd = (p.x - g.x) ** 2 + (p.y - g.y) ** 2;
        if (dd < mg) { mg = dd; iG = i; }
      });
      const p = px(linhas[iG]);
      const dir = dirNaAmostra(iG, g.ang);
      const perp = norm(-dir.y, dir.x);
      const colunas = Math.max(1, Math.min(4, g.colunas | 0));
      const vagas = Math.max(colunas, g.vagas | 0);
      const linhasG = Math.ceil(vagas / colunas);
      const fG = ((linhas[iG].d / lenUnid) - fLarg + 1) % 1;
      const larg = variavel ? larguraPx(fG) : 20;
      const gapC = larg / colunas;
      const celW = Math.max(6, gapC * 0.72);
      const celH = Math.max(8, Math.min(14, celW * 0.9));
      const passoLin = celH * 1.4;
      ctx.fillStyle = "rgba(245,247,251,0.85)";
      ctx.strokeStyle = "#111826";
      ctx.lineWidth = 1;
      for (let li = 0; li < linhasG; li++) {
        for (let ci = 0; ci < colunas; ci++) {
          const dx = -dir.x * (li * passoLin + celH / 2 + 2) + perp.x * (ci - (colunas - 1) / 2) * gapC;
          const dy = -dir.y * (li * passoLin + celH / 2 + 2) + perp.y * (ci - (colunas - 1) / 2) * gapC;
          ctx.beginPath();
          ctx.rect(p.x + dx - celW / 2, p.y + dy - celH / 2, celW, celH);
          ctx.fill();
          ctx.stroke();
        }
      }
    }

    const metrica = { linhas, px, esc, ox, oy, fLarg, lenUnid, unidPorM,
                      largadaPx: tr.largada ? px(linhas[iLarg]) : null,
                      larguraNaPos: f => larguraEm(tr, ((f - fLarg) + 1) % 1) };

    // vertices (modo editor)
    if (opts.pontos) {
      const pts = tr.pontos || [];
      pts.forEach((pt, i) => {
        const q = px(pt);
        ctx.fillStyle = pt.curva && pt.curva.raio > 0 ? "#4fd1a5" : "#8492a6";
        ctx.strokeStyle = "#0d1424";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(q.x, q.y, 6, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        if (opts.sel === i) {
          ctx.strokeStyle = "#3a86ff";
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.arc(q.x, q.y, 11, 0, Math.PI * 2);
          ctx.stroke();
        }
      });
    }
    return metrica;
  }

  // ponto (em pixels) na fracao da volta contada a partir da largada
  function pontoEm(met, frac) {
    const linhas = met.linhas;
    const total = met.lenUnid || 1;
    const alvo = (met.fLarg * total + (((frac % 1) + 1) % 1) * total) % total;
    let lo = 0, hi = linhas.length - 1;
    while (lo < hi - 1) {
      const mid = (lo + hi) >> 1;
      if (linhas[mid].d <= alvo) lo = mid; else hi = mid;
    }
    const a = linhas[lo], b = linhas[hi] || a;
    const t = b.d > a.d ? (alvo - a.d) / (b.d - a.d) : 0;
    return met.px({ x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t });
  }

  // angulo de chegada (graus) do vertice i, entre os dois segmentos
  function anguloVertice(tr, i) {
    const pts = tr.pontos || [];
    const n = pts.length;
    if (n < 3) return 0;
    const A = pts[(i - 1 + n) % n], B = pts[i], C = pts[(i + 1) % n];
    const u = norm(A.x - B.x, A.y - B.y);
    const w = norm(C.x - B.x, C.y - B.y);
    return Math.round((Math.PI - angEntre(u, w)) * 180 / Math.PI);
  }

  return { flatten, desenhar, pontoEm, raioAutoCanto, calcularCanto,
           anguloVertice, larguraEm, comprimentoBruto };
})();

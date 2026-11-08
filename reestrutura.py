with open('interface/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Substituir o header do operador - mover botões para o topo
old_header = '''<!-- OPERADOR (painel completo — 1ª opção do menu) -->
    <section id="operador" class="tela visivel">
      <div class="conteudo">
        <header class="main-header">
          <h1>Painel do Operador</h1>
          <div class="perfil"><span class="tag" id="perfil-nivel">SUPERUSER</span>
            sessão <span id="operador-sessao">—</span> · <span id="operador-estado">sem sessão</span>
            <span class="pill novo" id="operador-sim" hidden>SIMULAÇÃO — não oficial</span></div>
          <div class="acoes-topo">
            <button class="btn-slide" onclick="abrirTelaoSegundaTela()" title="Abre o telão em janela separada (2ª tela)">
              🖥️ Abrir Telão 2ª Tela
            </button>
          </div>
        </header>

        <!-- barra de status + display digital -->
        <div class="barra-op">
          <div class="ligacao"><span class="led" id="led-decoder"></span><span id="txt-ligacao">Sem ligação</span></div>
          <div class="flags">
            <span class="flag primeiro" id="flag-primeiro">1º: —</span>
            <span class="flag volta-rapida" id="flag-volta-rapida">Volta rápida</span>
            <span class="mini-semaforo" id="mini-semaforo" title="Semáforo da largada">
              <span class="mluz vermelha"></span><span class="mluz vermelha"></span><span class="mluz vermelha"></span><span class="mluz vermelha"></span><span class="mluz vermelha"></span><span class="mluz verde"></span>
            </span>
          </div>
          <div class="display-digital">
            <div class="cel"><div class="rot">Em pista</div><div class="val" id="disp-empista">0</div></div>
            <div class="cel"><div class="rot">Tempo</div><div class="val" id="disp-tempo">0:00.000</div></div>
            <div class="cel"><div class="rot">Voltas</div><div class="val" id="disp-voltas">0</div></div>
          </div>
        </div>

        <!-- configuração da sessão -->
        <div class="card" style="margin-bottom:16px">
          <h3>Configuração da sessão</h3>
          <div class="form-sessao centro">
            <div><label>Tipo</label>
              <select id="cfg-tipo" onchange="tipoSessaoMudou()">
                <option value="treino">Treino</option>
                <option value="classificacao">Classificação</option>
                <option value="corrida">Corrida</option>
                <option value="campeonato">Campeonato</option>
              </select></div>
            <div><label>Critério</label>
              <select id="cfg-criterio" onchange="criterioMudou()">
                <option value="Tempo">Tempo</option>
                <option value="Voltas">Voltas</option>
                <option value="livre">Tempo livre (sem limite)</option>
              </select></div>
            <div><label>Duração (min/voltas)</label><input id="cfg-duracao" value="10"></div>
            <div><label>Contador regressivo (s)</label><input id="cfg-contador" value="10"></div>
            <div><label>Aviso de saída (s)</label><input id="cfg-aviso-saida" value="30"></div>
            <div><label>Tempo para terminar (s)</label><input id="cfg-terminar" value="30"></div>
            <div><label>Tempo entre carros (s)</label><input id="cfg-entre-carros" value="2"></div>
            <div><label>Método</label>
              <select id="cfg-metodo"><option>Melhor tempo</option><option>Consecutivas</option></select></div>
            <div><label>Saída</label>
              <select id="cfg-saida"><option>1ª passagem pela meta</option><option>1ª detecção</option></select></div>
            <div><label>Tempo mínimo de volta (s)</label><input id="cfg-tempo-minimo" value="3"></div>
          </div>

          <div id="cfg-camp-escolha" style="display:none;margin-top:14px">
            <h3 style="margin-bottom:8px">Campeonato</h3>
            <div class="form-sessao centro">
              <div><label>Escolher campeonato</label>
                <select id="cfg-camp-select" style="min-width:260px" onchange="atualizarEscolhaCampeonato()"></select></div>
              <div><label>&nbsp;</label>
                <button class="btn-slide" onclick="menuCriarCampeonato()">➕ Criar campeonato</button></div>
              <div><label>&nbsp;</label>
                <button class="btn-slide" id="cfg-camp-editar" onclick="menuEditarCampeonato()" disabled>✏️ Editar campeonato</button></div>
            </div>
            <p class="hint" id="cfg-camp-aviso" style="display:none;margin-top:10px">
              Nenhum campeonato cadastrado ainda — clique em <b>Criar campeonato</b> para montar o primeiro.</p>
            <div class="acoes" style="margin-top:12px">
              <button class="destaque" id="cfg-camp-iniciar" onclick="iniciarCampeonatoEscolhido()" disabled>🏆 Iniciar campeonato</button>
            </div>
          </div>'''

new_header = '''<!-- OPERADOR (painel completo — 1ª opção do menu) -->
    <section id="operador" class="tela visivel">
      <div class="conteudo">
        <header class="main-header">
          <h1>Painel do Operador</h1>
          <div class="perfil"><span class="tag" id="perfil-nivel">SUPERUSER</span>
            sessão <span id="operador-sessao">—</span> · <span id="operador-estado">sem sessão</span>
            <span class="pill novo" id="operador-sim" hidden>SIMULAÇÃO — não oficial</span></div>
          <div class="acoes-topo">
            <button class="btn-slide" onclick="abrirTelaoSegundaTela()" title="Abre o telão em janela separada (2ª tela)">
              🖥️ Abrir Telão 2ª Tela
            </button>
            <!-- Botões de controle movidos para o topo ao lado do semáforo -->
            <button class="destaque" id="btn-acao-principal" onclick="acaoPrincipal()">▶ Iniciar treino</button>
            <button id="btn-pausar" onclick="alternarPausa()" disabled>⏸ Pausar</button>
            <button onclick="finalizar()">⏹ Finalizar</button>
            <button class="perigo" onclick="marcarGato()">🚫 Marcar "gato"</button>
            <button class="perigo" onclick="apagarVolta()">🗑 Apagar volta</button>
            <button onclick="desmarcarGato()">♻️ Desmarcar</button>
          </div>
        </header>

        <!-- barra de status + display digital -->
        <div class="barra-op">
          <div class="ligacao"><span class="led" id="led-decoder"></span><span id="txt-ligacao">Sem ligação</span></div>
          <div class="flags">
            <span class="flag primeiro" id="flag-primeiro">1º: —</span>
            <span class="flag volta-rapida" id="flag-volta-rapida">Volta rápida</span>
            <span class="mini-semaforo" id="mini-semaforo" title="Semáforo da largada">
              <span class="mluz vermelha"></span><span class="mluz vermelha"></span><span class="mluz vermelha"></span><span class="mluz vermelha"></span><span class="mluz vermelha"></span><span class="mluz verde"></span>
            </span>
          </div>
          <div class="display-digital">
            <div class="cel"><div class="rot">Em pista</div><div class="val" id="disp-empista">0</div></div>
            <div class="cel"><div class="rot">Tempo</div><div class="val" id="disp-tempo">0:00.000</div></div>
            <div class="cel"><div class="rot">Voltas</div><div class="val" id="disp-voltas">0</div></div>
          </div>
        </div>

        <!-- tabela completa volta-a-volta (no lugar da configuração) -->
        <div id="tabela-volta-volante" class="card" style="margin-bottom:16px; display:none">
          <h3>Volta a Volta — Operador</h3>
          <div class="tabela-wrap">
            <table class="tabela-op" id="tabela-volta-volante-tabela">
              <tr><th>Pos</th><th>#</th><th>Piloto</th><th>Voltas</th><th>Melhor</th><th>Total</th><th>Gap</th><th>Ações</th></tr>
              <tr><td colspan="8" style="color:var(--text-muted)">carregando…</td></tr>
            </table>
          </div>
        </div>

        <!-- classificação ao vivo (logo abaixo do header) -->
        <div class="card" style="margin-bottom:16px">
          <h3>Classificação ao vivo <span style="font-weight:400;text-transform:none;letter-spacing:0;color:var(--text-main)">— clique numa linha para selecionar o piloto (marcar gato / apagar volta)</span></h3>
          <div class="tabela-wrap">
            <table class="tabela-op" id="tabela-classificacao">
              <tr><th>Pos</th><th>Nº</th><th>Abr</th><th>Piloto</th><th>Voltas</th><th>Total</th><th>Intervalo</th><th>Gap</th><th>Última</th><th>Melhor</th><th>km/h</th><th>Média</th><th>Desvio</th><th>Consist.</th><th>Transponder</th><th>Ações</th></tr>
              <tr><td colspan="16" style="color:var(--text-muted)">nenhuma volta registrada</td></tr>
            </table>
          </div>
        </div>

        <!-- check-in: quem está na pista, antes de iniciar a sessão -->
        <div class="card" style="margin-bottom:16px" id="checkin-card-op">
          <h3>Pilotos na pista — check-in (<span id="op-checkin-n">0</span> marcados)</h3>
          <div class="acoes" style="margin:10px 0">
            <input id="op-checkin-busca" class="input-busca" placeholder="Filtrar pilotos…"
                   oninput="renderCheckin()">
            <button class="btn-mini" onclick="marcarTodosCheckin(true)">✔ Todos presentes</button>
            <button class="btn-mini" onclick="marcarTodosCheckin(false)">✖ Limpar</button>
            <button class="destaque" onclick="checkinToggleForm()">➕ Adicionar piloto</button>
          </div>
          <div id="op-checkin-form" class="card" style="display:none; margin:8px 0; padding:12px">
            <div class="acoes" style="margin:0; flex-wrap:wrap">
              <input id="op-checkin-novo-nome" class="input-busca" placeholder="Nome do piloto*"
                     style="flex:1; min-width:180px">
              <input id="op-checkin-novo-transp" class="input-busca" placeholder="Transponder (ex.: 1234)"
                     style="flex:1; min-width:140px">
              <button class="destaque" onclick="checkinAdicionarPiloto()">✔ Salvar e marcar na pista</button>
            </div>
          </div>
          <div id="op-checkin" class="lista-checkin">carregando…</div>
          <p class="hint" style="margin-top:8px">Marque quem está na pista antes de iniciar a
            sessão: só os pilotos marcados entram na corrida. Se ninguém for marcado, entram
            todos os transponders cadastrados.</p>
        </div>

        <!-- campeonato em andamento -->
        <div class="card" style="margin-bottom:16px" id="camp-card-op">
          <h3>🏆 Campeonato em andamento</h3>
          <div id="camp-atual-op" style="margin:10px 0">
            <span class="hint">nenhum campeonato em andamento</span>
          </div>
          <div class="acoes">
            <button class="destaque" id="camp-proxima-op" onclick="proximaEtapa()" disabled>⏭ Próxima etapa</button>
            <button class="perigo" id="camp-encerrar-op" onclick="encerrarCampeonato()" disabled>⏹ Encerrar campeonato</button>
          </div>
          <p class="hint">O avanço é <b>manual</b>: cada etapa só começa quando você clica em
            "Próxima etapa". A sessão da etapa anterior é encerrada automaticamente.</p>
        </div>

        <!-- controles (visible apenas quando sessão iniciada) -->
        <div class="acoes" id="controles-op" style="display:none; margin-top:12px">
          <button class="destaque" onclick="acaoPrincipal()">▶ Iniciar treino</button>
          <button id="btn-pausar-op" onclick="alternarPausa()" disabled>⏸ Pausar</button>
          <button onclick="finalizar()">⏹ Finalizar</button>
        </div>

        <!-- classification -->
        <div class="card" style="margin-bottom:16px">
          <h3>Classificação ao vivo <span style="font-weight:400;text-transform:none;letter-spacing:0;color:var(--text-main)">— clique numa linha para selecionar o piloto (marcar gato / apagar volta)</span></h3>
          <div class="tabela-wrap">
            <table class="tabela-op" id="tabela-classificacao">
              <tr><th>Pos</th><th>Nº</th><th>Abr</th><th>Piloto</th><th>Voltas</th><th>Total</th><th>Intervalo</th><th>Gap</th><th>Última</th><th>Melhor</th><th>km/h</th><th>Média</th><th>Desvio</th><th>Consist.</th><th>Transponder</th><th>Ações</th></tr>
              <tr><td colspan="16" style="color:var(--text-muted)">nenhuma volta registrada</td></tr>
            </table>
          </div>
        </div>

        <!-- console + abas -->
        <div class="grid g2">
          <div class="card">
            <h3>Console de eventos</h3>
            <div class="console-op" id="log-operador"></div>
          </div>
          <div class="card">
            <div class="abas">
              <button class="on" onclick="aba(this,0)">Tempos</button>
              <button onclick="aba(this,1)">Gráfico Posições</button>
              <button onclick="aba(this,2)">Melhores Voltas</button>
            </div>
            <div id="op-conteudo-abas">
              <!-- conteúdo das abas carregado dinamicamente -->
            </div>
          </div>
        </div>'''

print("Verificando se old_header está no conteúdo...")
if old_header in content:
    print("OLD HEADER ENCONTRADA - fazendo substituição...")
    content = content.replace(old_header, new_header)
    print("Substituição do header realizada com sucesso")
else:
    print("OLD HEADER NÃO ENCONTRADA")
    # Let's find what's there instead
    idx = content.find('<!-- OPERADOR')
    if idx >= 0:
        print("Contexto encontrado a partir da linha", idx)
        print(content[idx:idx+600])

print("Escrevendo arquivo...")
with open('interface/index.html', 'w', encoding='utf-8') as f:
    f.write(content)
print("Arquivo escrito com", len(content), "caracteres")
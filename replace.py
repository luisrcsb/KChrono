import re

with open('interface/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace the "configuração da sessão" section
old_section = '<!-- configura��o da sess�o -->\n    <div class="card" style="margin-bottom:16px">\n      <h3>Configura��o da sess�o</h3>'

new_section = '''<!-- tabela completa volta-a-volta (no lugar da configura��o) -->
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
        <div class="card" style="margin-bottom:16px" id="checkin-card-op">'''

if old_section in content:
    content = content.replace(old_section, new_section)
    print("Substituição realizada com sucesso")
    written = True
else:
    print("Old section not found")
    written = False

with open('interface/index.html', 'w', encoding='utf-8') as f:
    f.write(content)
print("Arquivo gravado")
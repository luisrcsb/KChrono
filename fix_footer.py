with open('interface/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Substituir a versão no rodapé inferior
old_footer = 'KChrono v1.0.6 por Raphael Belowodski'
new_footer = 'KChrono v1.0.7 por Equipe KChrono'

# Substituir no rodapé fixo inferior (apenas a primeira ocorrência)
if old_footer in content:
    content = content.replace(old_footer, new_footer, 1)
    print("Rodapé inferior atualizado")

# Substituir no rodapé lateral (admin-rodape)
old_sidebar = 'KChrono v1.0.6<br>por Raphael Belowodski'
new_sidebar = 'KChrono v1.0.7<br>por Equipe KChrono'

if old_sidebar in content:
    content = content.replace(old_sidebar, new_sidebar)
    print("Rodapé lateral atualizado")

with open('interface/index.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("Arquivo gravado. Verificando...")
# Verificar
if new_footer in content:
    print("✅ Footer inferior correto")
else:
    print("⚠️ Footer inferior NÃO encontrado")

if new_sidebar in content:
    print("✅ Footer lateral correto")
else:
    print("⚠️ Footer lateral NÃO encontrado")
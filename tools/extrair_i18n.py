# -*- coding: utf-8 -*-
"""KChrono — extrai strings para template .pot (gettext)."""
import os
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# padrões para achar strings user-facing
PADROES = [
    # Python: _("...") ou _('...') ou _("""...""")
    (r'_\(\s*([\'\"])(.*?)\1\s*\)', 2),
    # Python: _("""...""")
    (r'_\(\s*([\'\"]{3})(.*?)\1\s*\)', 2),
    # Python f-strings com _()
    (r'_\(f[\'\"](.*?)[\'\"]\s*\)', 1),
    # HTML/JS no Python: strings longas com texto visível
]

# palavras-chave que indicam string de UI (não log/debug)
PALAVRAS_UI = [
    "Iniciar", "Finalizar", "Pausar", "Largada", "Treino", "Classificação", "Corrida",
    "Painel", "Operador", "Telão", "Campeonato", "Piloto", "Voltas", "Melhor volta",
    "Tempo", "Gap", "Intervalo", "Média", "Desvio", "Consistência", "Posição",
    "Configuração", "Sessão", "Decoder", "Conexão", "Sincronização", "Upload",
    "Download", "Salvar", "Carregar", "Apagar", "Editar", "Novo", "Excluir",
    "Gerar", "Importar", "Exportar", "Enviar", "Receber", "Conectar", "Desconectar",
    "Erro", "Aviso", "Sucesso", "Confirmar", "Cancelar", "Sim", "Não", "OK",
    "Voltar", "Próximo", "Anterior", "Buscar", "Filtrar", "Ordenar", "Limpar",
    "Adicionar", "Remover", "Atualizar", "Criar", "Copiar", "Colar", "Selecionar",
    "Todos", "Nenhum", "Nome", "Apelido", "Fonia", "Telefone", "Transponder",
    "Número", "Frequência", "Categoria", "Pista", "Bateria", "Grid", "Chave",
    "Drop rounds", "Bônus", "Pole", "Ranking", "Inscritos", "Heats", "Finais",
    "Varredura", "Espectro", "RF", "Som", "Voz", "Volume", "Velocidade", "Frases",
    "Anúncio", "Locutor", "TTS", "Áudio", "Gravando", "Reproduzindo",
    "QR Code", "Gestão Remota", "Acesso", "Senha", "Login", "Superuser", "Admin",
    "Gestor", "Piloto", "Convidado", "Check-in", "Presente", "Ausente",
    "Bandeira", "Verde", "Amarela", "Vermelha", "Fechada", "Motivo", "Acidente",
    "Notificação", "Alerta", "Som", "Navegador", "Permissão", "Autorizar",
    "Histórico", "Relatório", "CSV", "Exportar", "Gerar", "Visualizar",
    "Sobre", "Créditos", "Versão", "Atualização", "Verificar", "Baixar",
    "Wallpaper", "Transparência", "Aparência", "Fundo", "Imagem", "URL", "Arquivo",
    "Sem sessão", "Sem volta", "Aguardando", "Largada em", "Contagem", "VAI!",
    "Pronto", "Pista aberta", "Pista fechada", "acidente na curva",
    "Novo recorde", "Recorde pessoal", "Recorde da pista", "Melhor volta",
    "Volta rápida", "Volta inválida", "Ghost lap", "Marcar gato", "Desmarcar",
    "Tempos", "Gráfico Posições", "Voltas Rápidas", "Melhores", "Track View",
    "Console", "Eventos", "Sistema", "Volta", "Ação", "Suspeita",
    "Enviar sessão", "Processar fila", "Limpar fila", "Configurar Sync",
    "Conta do CTAD", "E-mail", "Senha", "ID da pista", "Nível",
    "Conexão", "Temperatura", "Tensão", "Ruído", "GPS", "Drift", "Sincronizado",
    "Decoder", "MyLaps", "AMB", "P3", "EASYLAP", "LapWiz", "Serial", "Bluetooth",
    "BLE", "Porta", "IP", "Host", "Porta TCP", "Detectar", "Portas",
    "Instalador", "Windows", "Linux", "Autoupdate", "Verificar", "Baixar",
]

def extrair_python(caminho):
    """Extrai strings de arquivos .py."""
    strings = set()
    try:
        texto = caminho.read_text(encoding="utf-8")
    except Exception:
        return strings
    # _("...")
    for m in re.finditer(r'_\s*\(\s*([\'"])(.*?)(?<!\\)\1\s*\)', texto, re.DOTALL):
        s = m.group(2).strip()
        if s and any(p.lower() in s.lower() for p in PALAVRAS_UI):
            strings.add(s)
    # _('''...''') ou _("""...""")
    for m in re.finditer(r'_\s*\(\s*([\'"]{3})(.*?)\1\s*\)', texto, re.DOTALL):
        s = m.group(2).strip()
        if s and any(p.lower() in s.lower() for p in PALAVRAS_UI):
            strings.add(s.replace('\n', ' '))
    return strings

def extrair_html_js(caminho):
    """Extrai strings de arquivos .html, .js, .css (textContent, placeholders, etc.)."""
    strings = set()
    try:
        texto = caminho.read_text(encoding="utf-8")
    except Exception:
        return strings
    # remove template literals ${...} e expressões JS complexas antes de extrair
    texto_limpo = re.sub(r'\$\{[^}]+\}', '', texto)
    texto_limpo = re.sub(r'`[^`]*`', '', texto_limpo)  # template literals
    # Entre tags: >texto<
    for m in re.finditer(r'>\s*([^<>\n]{3,})\s*<', texto_limpo):
        s = m.group(1).strip()
        if s and any(p.lower() in s.lower() for p in PALAVRAS_UI):
            strings.add(s)
    # placeholder="..."
    for m in re.finditer(r'placeholder\s*=\s*["\']([^"\']+)["\']', texto_limpo):
        s = m.group(1).strip()
        if s and any(p.lower() in s.lower() for p in PALAVRAS_UI):
            strings.add(s)
    # title="..."
    for m in re.finditer(r'title\s*=\s*["\']([^"\']+)["\']', texto_limpo):
        s = m.group(1).strip()
        if s and any(p.lower() in s.lower() for p in PALAVRAS_UI):
            strings.add(s)
    # value="..." em botões/options
    for m in re.finditer(r'value\s*=\s*["\']([^"\']+)["\']', texto_limpo):
        s = m.group(1).strip()
        if s and any(p.lower() in s.lower() for p in PALAVRAS_UI):
            strings.add(s)
    # data-titulo="..."
    for m in re.finditer(r'data-titulo\s*=\s*["\']([^"\']+)["\']', texto_limpo):
        s = m.group(1).strip()
        if s and any(p.lower() in s.lower() for p in PALAVRAS_UI):
            strings.add(s)
    return strings

def main():
    todos = set()
    for ext, func in [(".py", extrair_python), (".html", extrair_html_js),
                      (".js", extrair_html_js), (".css", extrair_html_js)]:
        for arq in RAIZ.rglob(f"*{ext}"):
            if ".git" in arq.parts or "__pycache__" in arq.parts or "mockup" in arq.parts:
                continue
            # pula vendors/minificados
            if any(p in arq.parts for p in ("node_modules", "chart.umd.min.js", "chart.js", ".min.js", ".min.css")):
                continue
            todos.update(func(arq))
    # ordena e escreve .pot
    linhas = ['# KChrono — template de tradução (gettext)',
              '# Gerado automaticamente — edite os .po, não este arquivo',
              '',
              'msgid ""',
              'msgstr ""',
              '"Project-Id-Version: KChrono 1.0.5\\n"',
              '"POT-Creation-Date: 2026-10-13\\n"',
              '"PO-Revision-Date: YEAR-MO-DA HO:MI+ZONE\\n"',
              '"Last-Translator: FULL NAME <EMAIL@ADDRESS>\\n"',
              '"Language-Team: LANGUAGE <LL@li.org>\\n"',
              '"Language: \\n"',
              '"MIME-Version: 1.0\\n"',
              '"Content-Type: text/plain; charset=UTF-8\\n"',
              '"Content-Transfer-Encoding: 8bit\\n"',
              '']
    for s in sorted(todos, key=str.lower):
        linhas.append(f'msgid "{s}"')
        linhas.append('msgstr ""')
        linhas.append('')
    (RAIZ / "i18n" / "kchrono.pot").write_text("\n".join(linhas), encoding="utf-8")
    print(f"Extraidas {len(todos)} strings -> i18n/kchrono.pot")

if __name__ == "__main__":
    main()
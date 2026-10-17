# -*- coding: utf-8 -*-
"""Gera .po a partir do .pot - pt_BR (espelha) e en_US (traduz)."""
import os
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# Dicionário base pt_BR -> en_US para strings comuns da UI
TRADUCOES = {
    # UI geral
    "Iniciar": "Start",
    "Finalizar": "Finish",
    "Pausar": "Pause",
    "Retomar": "Resume",
    "Largada": "Start Lights",
    "Treino": "Practice",
    "Classificação": "Qualifying",
    "Corrida": "Race",
    "Painel": "Dashboard",
    "Operador": "Operator",
    "Telão": "TV Screen",
    "Campeonato": "Championship",
    "Piloto": "Driver",
    "Voltas": "Laps",
    "Melhor volta": "Best lap",
    "Tempo": "Time",
    "Gap": "Gap",
    "Intervalo": "Interval",
    "Média": "Average",
    "Desvio": "Std Dev",
    "Consistência": "Consistency",
    "Posição": "Position",
    "Configuração": "Configuration",
    "Sessão": "Session",
    "Decoder": "Decoder",
    "Conexão": "Connection",
    "Sincronização": "Sync",
    "Upload": "Upload",
    "Download": "Download",
    "Salvar": "Save",
    "Carregar": "Load",
    "Apagar": "Delete",
    "Editar": "Edit",
    "Novo": "New",
    "Excluir": "Remove",
    "Gerar": "Generate",
    "Importar": "Import",
    "Exportar": "Export",
    "Enviar": "Send",
    "Receber": "Receive",
    "Conectar": "Connect",
    "Desconectar": "Disconnect",
    "Erro": "Error",
    "Aviso": "Warning",
    "Sucesso": "Success",
    "Confirmar": "Confirm",
    "Cancelar": "Cancel",
    "Sim": "Yes",
    "Não": "No",
    "OK": "OK",
    "Voltar": "Back",
    "Próximo": "Next",
    "Anterior": "Previous",
    "Buscar": "Search",
    "Filtrar": "Filter",
    "Ordenar": "Sort",
    "Limpar": "Clear",
    "Adicionar": "Add",
    "Remover": "Remove",
    "Atualizar": "Update",
    "Criar": "Create",
    "Copiar": "Copy",
    "Colar": "Paste",
    "Selecionar": "Select",
    "Todos": "All",
    "Nenhum": "None",
    "Nome": "Name",
    "Apelido": "Nickname",
    "Fonia": "Phonetic",
    "Telefone": "Phone",
    "Transponder": "Transponder",
    "Número": "Number",
    "Frequência": "Frequency",
    "Categoria": "Category",
    "Pista": "Track",
    "Bateria": "Heat",
    "Grid": "Grid",
    "Chave": "Key",
    "Drop rounds": "Drop rounds",
    "Bônus": "Bonus",
    "Pole": "Pole",
    "Ranking": "Ranking",
    "Inscritos": "Entries",
    "Heats": "Heats",
    "Finais": "Finals",
    "Varredura": "Scan",
    "Espectro": "Spectrum",
    "RF": "RF",
    "Som": "Sound",
    "Voz": "Voice",
    "Volume": "Volume",
    "Velocidade": "Speed",
    "Frases": "Phrases",
    "Anúncio": "Announcement",
    "Locutor": "Announcer",
    "TTS": "TTS",
    "Áudio": "Audio",
    "Gravando": "Recording",
    "Reproduzindo": "Playing",
    "QR Code": "QR Code",
    "Gestão Remota": "Remote Access",
    "Acesso": "Access",
    "Senha": "Password",
    "Login": "Login",
    "Superuser": "Superuser",
    "Admin": "Admin",
    "Gestor": "Manager",
    "Piloto": "Driver",
    "Convidado": "Guest",
    "Check-in": "Check-in",
    "Presente": "Present",
    "Ausente": "Absent",
    "Bandeira": "Flag",
    "Verde": "Green",
    "Amarela": "Yellow",
    "Vermelha": "Red",
    "Fechada": "Closed",
    "Motivo": "Reason",
    "Acidente": "Accident",
    "Notificação": "Notification",
    "Alerta": "Alert",
    "Som": "Sound",
    "Navegador": "Browser",
    "Permissão": "Permission",
    "Autorizar": "Authorize",
    "Histórico": "History",
    "Relatório": "Report",
    "CSV": "CSV",
    "Exportar": "Export",
    "Gerar": "Generate",
    "Visualizar": "View",
    "Sobre": "About",
    "Créditos": "Credits",
    "Versão": "Version",
    "Atualização": "Update",
    "Verificar": "Check",
    "Baixar": "Download",
    "Wallpaper": "Wallpaper",
    "Transparência": "Transparency",
    "Aparência": "Appearance",
    "Fundo": "Background",
    "Imagem": "Image",
    "URL": "URL",
    "Arquivo": "File",
    "Sem sessão": "No session",
    "Sem volta": "No lap",
    "Aguardando": "Waiting",
    "Largada em": "Start in",
    "Contagem": "Countdown",
    "VAI!": "GO!",
    "Pronto": "Ready",
    "Pista aberta": "Track open",
    "Pista fechada": "Track closed",
    "acidente na curva": "accident at corner",
    "Novo recorde": "New record",
    "Recorde pessoal": "Personal best",
    "Recorde da pista": "Track record",
    "Melhor volta": "Best lap",
    "Volta rápida": "Fast lap",
    "Volta inválida": "Invalid lap",
    "Ghost lap": "Ghost lap",
    "Marcar gato": "Mark suspect",
    "Desmarcar": "Unmark",
    "Tempos": "Times",
    "Gráfico Posições": "Position Chart",
    "Voltas Rápidas": "Fast Laps",
    "Melhores": "Bests",
    "Track View": "Track View",
    "Console": "Console",
    "Eventos": "Events",
    "Sistema": "System",
    "Volta": "Lap",
    "Ação": "Action",
    "Suspeita": "Suspect",
    "Enviar sessão": "Send session",
    "Processar fila": "Process queue",
    "Limpar fila": "Clear queue",
    "Configurar Sync": "Configure Sync",
    "Conta do CTAD": "CTAD Account",
    "E-mail": "Email",
    "Senha": "Password",
    "ID da pista": "Track ID",
    "Nível": "Level",
    "Conexão": "Connection",
    "Temperatura": "Temperature",
    "Tensão": "Voltage",
    "Ruído": "Noise",
    "GPS": "GPS",
    "Drift": "Drift",
    "Sincronizado": "Synced",
    "Decoder": "Decoder",
    "MyLaps": "MyLaps",
    "AMB": "AMB",
    "P3": "P3",
    "EASYLAP": "EASYLAP",
    "LapWiz": "LapWiz",
    "Serial": "Serial",
    "Bluetooth": "Bluetooth",
    "BLE": "BLE",
    "Porta": "Port",
    "IP": "IP",
    "Host": "Host",
    "Porta TCP": "TCP Port",
    "Detectar": "Detect",
    "Portas": "Ports",
    "Instalador": "Installer",
    "Windows": "Windows",
    "Linux": "Linux",
    "Autoupdate": "Autoupdate",
    "Verificar": "Check",
    "Baixar": "Download",
    "0 voltas": "0 laps",
    "0% = cartões sólidos · 80% = máximo de transparência.": "0% = solid cards · 80% = max transparency.",
    "5 · 4 · 3 · 2 · 1 · VAI!": "5 · 4 · 3 · 2 · 1 · GO!",
    "A bandeira ativa aparece imediatamente no telão.": "Active flag appears immediately on TV screen.",
    "a cada N voltas do líder": "every N leader laps",
    "Acesso da direção de prova —": "Race control access —",
    "acesso total": "full access",
    "Acúmulo na fila de upload": "Upload queue buildup",
    "Admin": "Admin",
    "admin": "admin",
    "Admin → Gerente de Pista": "Admin → Track Manager",
    "Admin → 🏎️ Pilotos": "Admin → 🏎️ Drivers",
    "adota a chave primária": "adopts primary key",
    "adotou a chave primária": "adopted primary key",
    "aguardando": "waiting",
    "Admin": "Admin",
    "A bandeira ativa aparece imediatamente no telão.": "Active flag appears immediately on TV screen.",
    "a cada N voltas do líder": "every N leader laps",
    "Acesso da direção de prova —": "Race control access —",
    "acesso total": "full access",
    "Acúmulo na fila de upload": "Upload queue buildup",
}

def carregar_pot(caminho):
    """Carrega msgids do .pot"""
    texto = caminho.read_text(encoding="utf-8")
    msgids = []
    atual = None
    for linha in texto.splitlines():
        if linha.startswith('msgid "'):
            atual = linha[7:-1]  # remove msgid " e "
            if atual:
                msgids.append(atual)
    return msgids

def traduzir(msgid):
    """Traduz um msgid para inglês."""
    if msgid in TRADUCOES:
        return TRADUCOES[msgid]
    # tenta tradução palavra a palavra para compostos simples
    palavras = msgid.split()
    if len(palavras) <= 3:
        traduzidas = [TRADUCOES.get(p, p) for p in palavras]
        if traduzidas != palavras:
            return " ".join(traduzidas)
    return msgid  # mantém original se não sabe traduzir

def gerar_po(msgids, saida, idioma):
    """Gera arquivo .po"""
    linhas = [
        f'# KChrono — tradução {idioma}',
        '# Gerado automaticamente a partir do kchrono.pot',
        '',
        'msgid ""',
        'msgstr ""',
        f'"Project-Id-Version: KChrono 1.0.5\\n"',
        f'"PO-Revision-Date: 2026-10-13\\n"',
        f'"Last-Translator: Auto-generated\\n"',
        f'"Language-Team: KChrono Team\\n"',
        f'"Language: {idioma}\\n"',
        '"MIME-Version: 1.0\\n"',
        '"Content-Type: text/plain; charset=UTF-8\\n"',
        '"Content-Transfer-Encoding: 8bit\\n"',
        '"Plural-Forms: nplurals=2; plural=(n != 1);\\n"',
        ''
    ]
    for msgid in sorted(msgids, key=str.lower):
        msgstr = traduzir(msgid) if idioma == "en_US" else msgid
        # escapa aspas
        msgid_esc = msgid.replace('\\', '\\\\').replace('"', '\\"')
        msgstr_esc = msgstr.replace('\\', '\\\\').replace('"', '\\"')
        linhas.append(f'msgid "{msgid_esc}"')
        linhas.append(f'msgstr "{msgstr_esc}"')
        linhas.append('')
    saida.write_text("\n".join(linhas), encoding="utf-8")
    print(f"Gerado {saida.name}: {len(msgids)} entradas")

def main():
    pot = RAIZ / "i18n" / "kchrono.pot"
    msgids = carregar_pot(pot)
    print(f"Carregados {len(msgids)} msgids do .pot")

    gerar_po(msgids, RAIZ / "i18n" / "pt_BR" / "LC_MESSAGES" / "kchrono.po", "pt_BR")
    gerar_po(msgids, RAIZ / "i18n" / "en_US" / "LC_MESSAGES" / "kchrono.po", "en_US")
    print("Concluído!")

if __name__ == "__main__":
    main()
# KChrono — Empacotamento e instalação (Fase 7)

Esta pasta reúne tudo para transformar o KChrono em um aplicativo instalável
no **Windows** e no **Linux**. Os dados do usuário (histórico de voltas
`dados/kchrono.db`, `config.json`, uploads) ficam sempre em uma pasta gravável
separada do executável:

| Sistema | Executável | Dados do usuário |
|---|---|---|
| Windows | `C:\Program Files\KChrono\KChrono.exe` | `%APPDATA%\KChrono` |
| Linux   | `~/.local/share/KChrono` | `~/.local/share/KChrono` |

---

## Versão — toda atualização sobe a versão

**Regra do projeto:** toda alteração entregue ao operador sobe a versão. Não
existe correção silenciosa.

A **fonte única** da versão é `empacotamento/versao.json`. A ferramenta
`tools/versao.py` sobe a versão e reescreve todos os espelhos de uma vez:

```bat
python tools\versao.py bump --notas "o que mudou nesta versão"
```

Espelhos mantidos em sincronia automaticamente:

| Onde | O quê |
|---|---|
| `empacotamento/versao.json` | versão, notas e nomes dos artefatos (fonte) |
| `empacotamento/instalador.nsi` | `!define VERSAO` e `VERSAO_ARQ` (nome do instalador) |
| `interface/index.html` | rodapés, card "Sobre", exemplos de ajuda e cache-buster dos assets |
| `empacotamento/LEIA-ME.md` | exemplo do nome do instalador |
| `servidor/api.py` | versão do FastAPI (lê da fonte, nunca fixa) |
| `tools/gerar_po.py`, `tools/extrair_i18n.py` | cabeçalho `Project-Id-Version` (lê da fonte) |

Outros comandos:

```bat
python tools\versao.py show                 :: mostra a versão atual
python tools\versao.py check                :: 1 (erro) se houver dessincronia
python tools\versao.py sync                 :: reescreve os espelhos
python tools\versao.py bump --dry-run       :: mostra o que mudaria (não grava)
python tools\versao.py bump --minor         :: 1.0.8 -> 1.1.0
```

`empacotamento/build.py` chama o `check` antes de empacotar: se a versão
estiver fora de sincronia o build é **recusado**, com a mensagem do que rodar.
Ou seja, não sai pacote com versão errada.

Depois do bump: tag `v<versão>` no git + release no GitHub (a CI anexa o
instalador, o AppImage e a ISO).

---

## Windows — gerar o `.exe`

Pré-requisitos: Python 3.11+ instalado e no `PATH`.

```bat
cd empacotamento
build-windows.bat
```

Resultado: `empacotamento\dist\KChrono.exe` (arquivo único, com a interface e
as imagens embutidas). Dê duplo clique para abrir o aplicativo em **janela
nativa (WebView2) maximizada, com a barra de título** (minimizar/maximizar/
fechar à mão) — sem navegador e sem barra de endereço.

Opções de linha de comando do app:

```bat
KChrono.exe                 REM janela maximizada com barra de título (padrão)
KChrono.exe --janela        REM janela normal, redimensionável (desenvolvimento)
KChrono.exe --fullscreen    REM tela cheia real, sem barra de título (kiosk)
KChrono.exe --porta 9000    REM porta alternativa
KChrono.exe --telao         REM abre direto no telão
KChrono.exe --gerente       REM abre direto no gerente (celular)
KChrono.exe --sem-janela    REM headless (serviço)
```

### Gerar o instalador (NSIS)

1. Instale o [NSIS](https://nsis.sourceforge.io/).
2. Abra `instalador.nsi` e compile (`makensis instalador.nsi`).
3. Resultado: `empacotamento\KChrono-Setup-<versão>.exe` (ex.:
   `KChrono-Setup-1-0-10.exe` — a versão entra no nome com hífens).

O instalador cria atalhos no Menu Iniciar e na Área de Trabalho, registra a
desinstalação e oferece a opção de iniciar com o Windows.

---

## Linux — instalar

```bash
bash empacotamento/instalar-linux.sh
```

O script copia o projeto para `~/.local/share/KChrono`, cria um *virtualenv*,
instala as dependências e publica o comando `kchrono` e o atalho de menu.

```bash
kchrono                 # sobe o servidor em http://localhost:8780
kchrono --porta 9000    # porta alternativa
```

### Rodar como serviço (systemd, opcional)

```bash
sed "s|__DEST__|$HOME/.local/share/KChrono|" empacotamento/kchrono.service \
  | sudo tee /etc/systemd/system/kchrono.service
sudo systemctl enable --now kchrono
```

---

## Atualizações

O KChrono consulta um arquivo `versao.json` publicado em um servidor
(configurável em `empacotamento/versao.json` → campo `"url_base"`). Em
**Admin → 🖥️ Sobre o KChrono** há os botões **Verificar** e **Baixar**.

Para ativar:
1. Publique `versao.json` e os pacotes (`KChrono-Setup-<versão>.exe`,
   `kchrono-linux.tar.gz`) em um endereço HTTPS.
2. Preencha `"url_base"` em `versao.json`.
3. A cada novo lançamento, **incremente a versão com a ferramenta** (ela reescreve todos os espelhos) e republique os arquivos:
   `python tools\versao.py bump --notas "o que mudou"`.

> A aplicação da atualização é feita executando o instalador baixado
> (Windows) ou reextraindo o pacote (Linux) — o verificador apenas informa
> e baixa.

---

## Arquivos desta pasta

| Arquivo | Função |
|---|---|
| `kchrono_launcher.py` | ponto de entrada do executável (sobe o servidor e abre a janela nativa em tela cheia) |
| `KChrono.spec` | receita do PyInstaller |
| `build-windows.bat` | gera `KChrono.exe` |
| `instalador.nsi` | instalador Windows (NSIS) |
| `instalar-linux.sh` | instalação Linux por usuário |
| `kchrono.desktop` | atalho de menu (Linux) |
| `kchrono.service` | unidade systemd opcional |
| `versao.json` | manifesto de versão para o atualizador (fonte única) |

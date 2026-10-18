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

## Windows — gerar o `.exe`

Pré-requisitos: Python 3.11+ instalado e no `PATH`.

```bat
cd empacotamento
build-windows.bat
```

Resultado: `empacotamento\dist\KChrono.exe` (arquivo único, com a interface e
as imagens embutidas). Dê duplo clique para subir o servidor — o navegador
abre automaticamente em <http://localhost:8780>.

### Gerar o instalador (NSIS)

1. Instale o [NSIS](https://nsis.sourceforge.io/).
2. Abra `instalador.nsi` e compile (`makensis instalador.nsi`).
3. Resultado: `empacotamento\KChrono-Setup-<versão>.exe` (ex.:
   `KChrono-Setup-1-0-6.exe` — a versão entra no nome com hífens).

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
2. Preencha `"url_base"` em `versao.json` e ajuste o número de `"versao"`.
3. A cada novo lançamento, incremente a versão e republic​e os arquivos.

> A aplicação da atualização é feita executando o instalador baixado
> (Windows) ou reextraindo o pacote (Linux) — o verificador apenas informa
> e baixa.

---

## Arquivos desta pasta

| Arquivo | Função |
|---|---|
| `kchrono_launcher.py` | ponto de entrada do executável (sobe o servidor e abre o navegador) |
| `KChrono.spec` | receita do PyInstaller |
| `build-windows.bat` | gera `KChrono.exe` |
| `instalador.nsi` | instalador Windows (NSIS) |
| `instalar-linux.sh` | instalação Linux por usuário |
| `kchrono.desktop` | atalho de menu (Linux) |
| `kchrono.service` | unidade systemd opcional |
| `versao.json` | manifesto de versão para o atualizador |

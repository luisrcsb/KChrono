---
name: KChrono Release
description: Fluxo de entrega do KChrono — bump de versão, build PyInstaller, instalador NSIS e smoke test. Use ao concluir qualquer alteração que o operador perceba.
---

# KChrono — entrega de versão

Use esta skill ao terminar uma alteração no KChrono que o operador percebe
(interface, servidor, motor, empacotamento ou documentação de uso).

## Regra obrigatória

**Toda alteração entregue sobe a versão, é recompilada e gera instalador novo.**
Não existe correção silenciosa e não se entrega só o código-fonte.

Uma entrega só está concluída depois destes quatro passos:

1. `python tools/versao.py bump --notas "..."` — sempre, mesmo que a mudança
   pareça pequena.
2. `python empacotamento/build.py` — recompilar o executável.
3. `cd empacotamento` + `makensis instalador.nsi` — recompilar o instalador NSIS.
4. `python tools/versao.py check` + smoke test do `.exe`.

A fonte única da versão é `empacotamento/versao.json`; nunca edite os espelhos
à mão. O `build.py` recusa empacotar se `python tools/versao.py check` falhar.

## 1. Pré-voo

No diretório raiz do repositório:

```powershell
git status --short
node --check interface/app.js
```

- Rode `node --check` apenas se mexeu em JavaScript da interface.
- Para Python alterado, valide o arquivo ou o teste que já existe no projeto.
- Não reverta alterações não relacionadas que já estavam na árvore de trabalho.
- Se a mudança for visual, teste no navegador com o servidor local antes do build:
  `python cli.py servidor --host 127.0.0.1 --porta 8799` e abra
  `http://127.0.0.1:8799/`. Confira o console sem erros e o comportamento em tempo
  real por WebSocket (sem polling, sem piscar e sem perder a rolagem).

## 2. Subir a versão

```powershell
python tools\versao.py bump --notas "descrição curta do que mudou"
```

- Padrão: patch (`1.1.11` → `1.1.12`).
- Use `--minor` para recurso novo relevante e `--major` para mudança incompatível.
- O comando sincroniza instalador NSIS, HTMLs, cache-busters e LEIA-ME.
- Para conferir sem escrever: `python tools\versao.py bump --dry-run`.

## 3. Build do executável

Feche instâncias abertas antes de compilar:

```powershell
Get-Process -Name "KChrono*" -ErrorAction SilentlyContinue | Stop-Process -Force
python empacotamento\build.py
```

- Leva cerca de 2 minutos; não use timeout curto.
- Para rodar em segundo plano, redirecione a saída para um log em
  `C:\Users\luisr\AppData\Local\Temp\opencode\`.
- Saída esperada: a pasta `empacotamento\dist\KChrono-<versao>\` com o
  executável `KChrono-<versao>.exe` e a subpasta `_internal` (**onedir**).
- O build usa **onedir** (não onefile), **sem UPX** e com **metadados** de
  versão — decisões deliberadas para reduzir falso positivo de antivírus.
  Não volte para onefile/UPX sem necessidade real.
- O build já sincroniza `!define VERSAO` e `VERSAO_ARQ` do `instalador.nsi`.
- Se `KCHRONO_SIGN_PFX` (e `KCHRONO_SIGN_PASSWORD`) estiverem definidas, o
  `build.py` assina o `.exe` ao final via `empacotamento/assinar.py`. Sem
  certificado configurado, a assinatura é ignorada (no-op) e o build segue.

## 4. Instalador NSIS

```powershell
cd empacotamento
& "C:\Program Files (x86)\NSIS\makensis.exe" instalador.nsi
```

- Se o NSIS estiver no PATH, `makensis instalador.nsi` também funciona.
- O instalador copia a pasta onedir (`File /r "dist\KChrono-<versao>\*.*"`):
  o `.exe` e a subpasta `_internal` vão para `$INSTDIR`.
- O `.nsi` preenche os metadados do instalador (`VIProductVersion` +
  `VIAddVersionKey`) — não os remova: instalador sem versão/empresa é gatilho
  de heurística.
- Saída esperada: `empacotamento\KChrono-Setup-<versao-com-hifens>.exe`
  (ex.: versão `1.1.11` → `KChrono-Setup-1-1-11.exe`).
- A tela final do instalador traz a opção **“Iniciar o KChrono agora”** (marcada
  por padrão), configurada por `MUI_FINISHPAGE_RUN` e `MUI_FINISHPAGE_RUN_TEXT`.
  Preserve essa opção ao editar o `.nsi`.
- Ao instalar por cima de uma versão antiga, o instalador:
  1. **fecha o KChrono** (Operador, Telão, Gerente e Serviço) com `taskkill`,
     repetindo até não sobrar processo (o WebView2 demora a liberar o `.exe`);
  2. **desinstala a versão anterior** rodando `Desinstalar.exe /S` em modo
     silencioso e esperando ele terminar;
  3. faz uma **limpeza residual** (exe com versão no nome, atalhos e registro),
     preservando os dados do usuário em `APPDATA\KChrono`.
  Preserve esse fluxo ao editar o `.nsi`.
- É normal aparecer o aviso `Variable "INSTALAR_AUTO" not referenced` em versões
  antigas do script; se ele reaparecer, remova a variável não usada.
- Sempre recompile o instalador após mexer no `.nsi` ou no executável.

## 5. Verificação final

```powershell
python tools\versao.py check
Get-ChildItem empacotamento\dist\KChrono-*\KChrono-*.exe | Select-Object Name, Length, LastWriteTime
Get-ChildItem empacotamento\KChrono-Setup-*.exe | Select-Object Name, Length, LastWriteTime
```

Se houver certificado configurado, confira a assinatura:

```powershell
python empacotamento\assinar.py --verificar empacotamento\KChrono-Setup-<versao-com-hifens>.exe
```

Smoke test do executável (abre, espera alguns segundos e fecha):

```powershell
$exe = (Resolve-Path "empacotamento\dist\KChrono-<versao>\KChrono-<versao>.exe").Path
Start-Process -FilePath $exe
Start-Sleep -Seconds 8
Get-Process -Name "KChrono*" -ErrorAction SilentlyContinue | Select-Object Id, ProcessName
Get-Process -Name "KChrono*" -ErrorAction SilentlyContinue | Stop-Process -Force
```

Se o executável permanecer aberto sem erro, o smoke test passou.

## 6. Relatar a entrega

Informe em português:

- o que mudou, em linguagem de operador;
- a versão nova;
- o caminho do executável e do instalador;
- que o instalador oferece a opção **“Iniciar o KChrono agora”** na tela final
  (marcada por padrão e pode ser desmarcada);
- o resultado do smoke test;
- que o instalador fecha o KChrono em execução e desinstala a versão anterior
  antes de instalar (mantendo os dados em `APPDATA\KChrono`);
- que o build agora é **onedir, sem UPX e com metadados**, e que o `.exe`/o
  instalador são assinados se houver certificado configurado (reduz falso
  positivo de antivírus);
- que, para instalar, basta executar o instalador como administrador.

## Git, tag e release

Só faça commit, tag (`v<versao>`) ou release no GitHub quando o usuário pedir
explicitamente. O `versao.py` sugere a tag, mas não a cria.

## Armadilhas conhecidas

- **Zero é valor válido** em durações: não use `parseFloat(valor) || padrao`
  quando `0` significa “sem limite”. Valide com `Number.isFinite` e teste o caso 0.
- **Tempo real é WebSocket**: não introduza polling, `setInterval` de refresh ou
  re-render que perca a rolagem.
- **Não edite espelhos de versão manualmente**: rode `bump` ou `sync`.
- **Não apague `empacotamento/dist` durante o build**; o PyInstaller escreve ali.
- **`empacotamento/config.json` e dados locais** podem ter alterações do usuário:
  não os substitua nem reverta sem pedir.
- **Não volte para onefile/UPX**: o app é onedir de propósito (anti-falso-positivo).
  Ao mexer no `.spec`/`.nsi`, preserve `upx=False`, `version=`, `uac_admin=False`
  e os metadados `VIProductVersion`/`VIAddVersionKey`.
- **Assinatura é opcional e por variável de ambiente**: nunca coloque senha de
  certificado no código; use `KCHRONO_SIGN_PASSWORD`.

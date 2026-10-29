"""KChrono — controle de versão (fonte única: ``empacotamento/versao.json``).

REGRA DO PROJETO
----------------
**Toda alteração entregue ao usuário sobe a versão.** Não existe "correção
silenciosa": se mudou algo que o operador percebe, a versão sobe junto.

Esta ferramenta existe para que a versão nunca fique esquecida nem
dessincronizada. Ela é a **única** forma de subir a versão e mantém todos os
espelhos (instalador NSIS, interface, i18n, documentação) iguais à fonte.

Comandos
--------
    python tools/versao.py bump [--patch|--minor|--major] [--notas "texto"]
    python tools/versao.py sync      # reescreve os espelhos (sem subir a versão)
    python tools/versao.py check     # sai com 1 se houver dessincronia
    python tools/versao.py show      # mostra a versão atual

``empacotamento/build.py`` chama ``check`` antes de empacotar — se a versão
estiver fora de sincronia o build é recusado, com a mensagem do que rodar.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
VERSAO_JSON = os.path.join(RAIZ, "empacotamento", "versao.json")

#: Espelhos da versão: (arquivo, regex, template).
#: ``{v}`` = versão (1.0.8) e ``{vh}`` = versão com hífens (1-0-8).
#: O template reescreve a versão **no lugar** — o resto do arquivo fica intacto.
ESPELHOS = [
    # instalador NSIS (nome do arquivo e registro do Windows)
    ("empacotamento/instalador.nsi", r'(!define VERSAO ")[^"]*(")', r"\g<1>{v}\g<2>"),
    ("empacotamento/instalador.nsi", r'(!define VERSAO_ARQ ")[^"]*(")', r"\g<1>{vh}\g<2>"),
    # interface: rodapés, card "Sobre" e exemplos de ajuda
    #   (o rodapé usa <span class="js-versao">v1.0.8</span> — preenchido em
    #    tempo de execução pelo app.js; o texto fixo é só o fallback)
    ("interface/index.html", r'(KChrono v|js-versao">v)\d+\.\d+\.\d+', r"\g<1>{v}"),
    ("interface/index.html", r'(id="upd-versao">)\d+\.\d+\.\d+(</div>)', r"\g<1>{v}\g<2>"),
    ("interface/index.html", r'(<code>v)\d+\.\d+\.\d+(</code>)', r"\g<1>{v}\g<2>"),
    ("interface/index.html", r'(<code>KChrono-Setup-)\d+-\d+-\d+(\.exe</code>)',
     r"\g<1>{vh}\g<2>"),
    # interface: "cache-buster" dos assets (muda junto com a versão)
    ("interface/index.html", r'(estilo\.css\?v=)[0-9.]+', r"\g<1>{v}"),
    ("interface/index.html", r'(tracado\.js\?v=)[0-9.]+', r"\g<1>{v}"),
    ("interface/index.html", r'(app\.js\?v=)[0-9.]+', r"\g<1>{v}"),
    ("interface/telao.html", r'(telao\.css\?v=)[0-9.]+', r"\g<1>{v}"),
    ("interface/telao.html", r'(tracado\.js\?v=)[0-9.]+', r"\g<1>{v}"),
    ("interface/telao.html", r'(telao\.js\?v=)[0-9.]+', r"\g<1>{v}"),
    ("interface/gerente.html", r'(gerente\.css\?v=)[0-9.]+', r"\g<1>{v}"),
    ("interface/gerente.html", r'(tracado\.js\?v=)[0-9.]+', r"\g<1>{v}"),
    ("interface/gerente.html", r'(gerente\.js\?v=)[0-9.]+', r"\g<1>{v}"),
    # documentação do empacotamento
    ("empacotamento/LEIA-ME.md", r'(KChrono-Setup-)\d+-\d+-\d+(\.exe)', r"\g<1>{vh}\g<2>"),
]

#: Arquivos que NÃO podem ter versão fixa: precisam ler da fonte.
#: (arquivo, trecho obrigatório)
ASSERCOES = [
    ("servidor/api.py", "version=VERSAO_ATUAL"),
    ("tools/gerar_po.py", "versao_atual()"),
    ("tools/extrair_i18n.py", "versao_atual()"),
]


# ------------------------------------------------------------------ fonte
def _ler_json() -> dict:
    with open(VERSAO_JSON, encoding="utf-8") as f:
        return json.load(f)


def _salvar_json(dados: dict) -> None:
    with open(VERSAO_JSON, "w", encoding="utf-8", newline="\n") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
        f.write("\n")


def versao_atual() -> str:
    """Versão atual (fonte única). Também usado pelos geradores de i18n."""
    try:
        return str(_ler_json().get("versao", "0.0.0"))
    except Exception:
        return "0.0.0"


def _incrementar(versao: str, parte: str) -> str:
    """1.0.7 + patch → 1.0.8 · minor → 1.1.0 · major → 2.0.0."""
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)", (versao or "").strip())
    if not m:
        raise SystemExit(f"versão inválida: {versao!r} (esperado X.Y.Z)")
    mai, min_, patch = (int(x) for x in m.groups())
    if parte == "major":
        return f"{mai + 1}.0.0"
    if parte == "minor":
        return f"{mai}.{min_ + 1}.0"
    return f"{mai}.{min_}.{patch + 1}"


def _corpo_das_notas(notas: str, versao: str) -> str:
    """Tira o prefixo "Versão X.Y.Z — " das notas, mantendo o resto."""
    txt = (notas or "").strip()
    return re.sub(rf"^Vers[aã]o\s+{re.escape(versao)}\s*[—–-]\s*", "", txt)


# ------------------------------------------------------------------ espelhos
def _aplicar(conteudo: str, versao: str) -> str:
    vh = versao.replace(".", "-")
    for _arq, regex, tpl in ESPELHOS:
        conteudo = re.sub(regex, tpl.format(v=versao, vh=vh), conteudo)
    return conteudo


def sincronizar(versao: str | None = None, silencioso: bool = False) -> list:
    """Reescreve os espelhos com a versão. Devolve a lista do que mudou."""
    versao = versao or versao_atual()
    mudados = []
    for arq, _regex, _tpl in ESPELHOS:
        caminho = os.path.join(RAIZ, arq)
        if not os.path.exists(caminho):
            continue
        with open(caminho, encoding="utf-8", errors="surrogateescape") as f:
            antes = f.read()
        depois = _aplicar(antes, versao)
        if depois != antes:
            with open(caminho, "w", encoding="utf-8", errors="surrogateescape",
                      newline="") as f:
                f.write(depois)
            mudados.append(arq)
            if not silencioso:
                print(f"[versao] {arq} -> {versao}")
    # nomes dos artefatos dentro do próprio versao.json
    dados = _ler_json()
    vh = versao.replace(".", "-")
    arquivos = dados.setdefault("arquivos", {})
    if arquivos.get("windows") != f"KChrono-Setup-{vh}.exe":
        arquivos["windows"] = f"KChrono-Setup-{vh}.exe"
        mudados.append("empacotamento/versao.json")
    if arquivos.get("linux") != f"KChrono-{versao}-x86_64.AppImage":
        arquivos["linux"] = f"KChrono-{versao}-x86_64.AppImage"
        mudados.append("empacotamento/versao.json")
    if "empacotamento/versao.json" in mudados:
        _salvar_json(dados)
        if not silencioso:
            print(f"[versao] empacotamento/versao.json -> nomes dos artefatos")
    return mudados


def verificar() -> list:
    """Devolve a lista de problemas (vazia = tudo em sincronia)."""
    versao = versao_atual()
    problemas = []

    for arq, _regex, _tpl in ESPELHOS:
        caminho = os.path.join(RAIZ, arq)
        if not os.path.exists(caminho):
            continue
        with open(caminho, encoding="utf-8", errors="surrogateescape") as f:
            txt = f.read()
        if _aplicar(txt, versao) != txt:
            problemas.append(f"{arq} está fora de sincronia com {versao}")

    for arq, trecho in ASSERCOES:
        caminho = os.path.join(RAIZ, arq)
        if not os.path.exists(caminho):
            continue
        with open(caminho, encoding="utf-8", errors="surrogateescape") as f:
            txt = f.read()
        if trecho not in txt:
            problemas.append(f"{arq} não lê a versão da fonte (falta {trecho!r})")

    # versao.json: nomes dos artefatos
    dados = _ler_json()
    vh = versao.replace(".", "-")
    arquivos = dados.get("arquivos", {})
    if arquivos.get("windows") != f"KChrono-Setup-{vh}.exe":
        problemas.append(f"versao.json: arquivos.windows deveria ser "
                         f"KChrono-Setup-{vh}.exe")
    if arquivos.get("linux") != f"KChrono-{versao}-x86_64.AppImage":
        problemas.append(f"versao.json: arquivos.linux deveria ser "
                         f"KChrono-{versao}-x86_64.AppImage")
    return problemas


# ------------------------------------------------------------------ comandos
def cmd_bump(args) -> int:
    antiga = versao_atual()
    nova = _incrementar(antiga, args.parte)
    dados = _ler_json()
    corpo = _corpo_das_notas(dados.get("notas", ""), antiga)
    if args.notas:
        corpo = args.notas.strip()
    dados["versao"] = nova
    dados["notas"] = (f"Versão {nova} — {corpo}" if corpo else f"Versão {nova}")
    if args.dry_run:
        print(f"[versao] (simulacao) {antiga} -> {nova}")
        print(f"[versao] (simulacao) notas: {dados['notas']}")
        mudaria = set()
        for arq, _regex, _tpl in ESPELHOS:
            caminho = os.path.join(RAIZ, arq)
            if not os.path.exists(caminho):
                continue
            with open(caminho, encoding="utf-8", errors="surrogateescape") as f:
                antes = f.read()
            if _aplicar(antes, nova) != antes:
                mudaria.add(arq)
        for arq in sorted(mudaria):
            print(f"[versao] (simulacao) {arq} seria atualizado")
        return 0
    _salvar_json(dados)
    print(f"[versao] {antiga} -> {nova}")
    sincronizar(nova)
    problemas = verificar()
    if problemas:
        print("[versao] ainda restam diferenças:")
        for p in problemas:
            print(f"   - {p}")
        return 1
    print(f"[versao] tudo em sincronia ({nova})")
    print(f"[versao] próxima etapa: tag git v{nova} + release no GitHub")
    return 0


def cmd_sync(args) -> int:
    versao = versao_atual()
    mudados = sincronizar(versao)
    if mudados:
        print(f"[versao] {len(set(mudados))} arquivo(s) sincronizado(s) com {versao}")
    else:
        print(f"[versao] já estava em sincronia ({versao})")
    return 0


def cmd_check(args) -> int:
    problemas = verificar()
    if problemas:
        print(f"[versao] FORA DE SINCRONIA (v{versao_atual()}):")
        for p in problemas:
            print(f"   - {p}")
        print("[versao] rode: python tools/versao.py sync")
        return 1
    print(f"[versao] em sincronia (v{versao_atual()})")
    return 0


def cmd_show(args) -> int:
    dados = _ler_json()
    print(f"versão   : {dados.get('versao')}")
    print(f"canal    : {dados.get('canal')}")
    print(f"notas    : {dados.get('notas')}")
    print(f"windows  : {dados.get('arquivos', {}).get('windows')}")
    print(f"linux    : {dados.get('arquivos', {}).get('linux')}")
    return 0


def main(argv=None) -> int:
    # o console do Windows costuma ser cp1252: nunca quebrar por causa de
    # um caractere de acento ou seta na saída
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    p = argparse.ArgumentParser(description="controle de versão do KChrono")
    sub = p.add_subparsers(dest="cmd")

    b = sub.add_parser("bump", help="sobe a versão e sincroniza tudo")
    b.add_argument("--patch", action="store_true", help="1.0.7 → 1.0.8 (padrão)")
    b.add_argument("--minor", action="store_true", help="1.0.7 → 1.1.0")
    b.add_argument("--major", action="store_true", help="1.0.7 → 2.0.0")
    b.add_argument("--notas", default="", help="notas de releases desta versão")
    b.add_argument("--dry-run", action="store_true",
                   help="mostra o que mudaria, sem escrever nada")
    b.set_defaults(func=cmd_bump)

    s = sub.add_parser("sync", help="reescreve os espelhos sem subir a versão")
    s.set_defaults(func=cmd_sync)

    c = sub.add_parser("check", help="verifica se tudo está em sincronia")
    c.set_defaults(func=cmd_check)

    sh = sub.add_parser("show", help="mostra a versão atual")
    sh.set_defaults(func=cmd_show)

    args = p.parse_args(argv)
    if not args.cmd:
        args = p.parse_args(["--help"])
        return 0
    # --patch é o padrão (se nenhum foi escolhido)
    if args.cmd == "bump":
        if args.major:
            args.parte = "major"
        elif args.minor:
            args.parte = "minor"
        else:
            args.parte = "patch"
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

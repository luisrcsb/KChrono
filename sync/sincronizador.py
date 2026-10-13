"""KChrono — sincronização com o CTAD (Fase 3).

Fluxo de resultados (envio): monta o payload exatamente no formato que o site
espera (`baterias/{key}` + `publicResumo` + `uploadLog`), com fila local offline,
dedup por SHA-256 e reenvio.

Fluxo de cadastro (mão dupla): traz os pilotos de `pilotosMetadados` e a
configuração/inscritos de um `campeonatos/{chave}` — com as chaves A/B/C já
alinhadas (`pilotosPorChave`, `inverterSegundaBateria`) — e publica pilotos
novos de volta em `pilotosMetadados` (sem sobrescrever o que já existe).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from typing import Dict, List

from nucleo.campeonatos import PADRAO_PILOTOS_POR_CHAVE

from .ctad_client import CtadClient, ErroAuth, ErroBanco

log = logging.getLogger("kchrono.sync")

PARSER_VERSION = 2  # mesma versão do parser do site (v2)


def _slug(texto: str) -> str:
    return "".join(c.lower() if c.isalnum() else "_" for c in texto)


def meta_key(nome) -> str:
    """Chave de um piloto no Firebase — MESMA normalização usada pelo site.

    `joão.silva/2` vira `joão_silva_2`. Espelha o `metaKey` de
    ``pilotos-v2.js``/``pilotos.js`` para os dois lados concordarem
    (`.` `#` `$` `/` `[` `]` viram `_`).
    """
    return re.sub(r"[.#$/\[\]]", "_", str(nome or ""))


def _so_digitos(valor) -> str:
    """Telefone reduzido a dígitos (mesmo critério da API de pilotos)."""
    return "".join(c for c in str(valor or "") if c.isdigit())


def _norm_nome(nome) -> str:
    """Nome comparável (minúsculo, sem espaços extras) — desempate do match."""
    return " ".join(str(nome or "").lower().split())


def max_por_chave(camp) -> int:
    """Teto de pilotos por chave, com fallback para ``pilotos_por_prova``."""
    try:
        valor = camp["pilotos_por_chave"]
    except (IndexError, KeyError):
        valor = None
    return int(valor or camp["pilotos_por_prova"] or PADRAO_PILOTOS_POR_CHAVE)


def gerar_resumo(reg: Dict) -> Dict:
    """Porte fiel do gerar_resumo() do site (portal-pistas / parsers)."""
    proc = []
    for d in reg.get("dados") or []:
        nome = str(d.get("piloto") or "").strip()
        laps = [t for t in (d.get("laps") or []) if isinstance(t, (int, float)) and t > 0]
        if nome and laps:
            proc.append({"piloto": nome, "voltas": len(laps), "melhor": min(laps)})
    proc.sort(key=lambda p: (-p["voltas"], p["melhor"]))
    podio = [p["piloto"] for p in proc[:3]]
    melhor = min(proc, key=lambda p: p["melhor"]) if proc else None
    return {"pistaId": reg.get("pistaId"), "nomePista": reg.get("pistaId"),
            "sessao": reg.get("sessao"),
            "firebaseKey": reg.get("firebaseKey") or reg.get("bateriaKey"),
            "podio": podio, "totalPilotos": len(proc),
            "melhorVolta": ({"piloto": melhor["piloto"],
                             "tempo": round(melhor["melhor"], 3)} if melhor else None),
            "atualizadoEm": int(time.time() * 1000)}


class Sincronizador:
    """Converte sessões locais no formato do CTAD e gerencia a fila de envio."""

    def __init__(self, banco=None, cliente: CtadClient = None,
                 pista_id: str = "krathus"):
        self.banco = banco
        self.cliente = cliente
        self.pista_id = pista_id

    # ----- status -----
    @property
    def configurado(self) -> bool:
        return self.cliente is not None

    def status(self) -> Dict:
        fila = self.banco.stats_sync() if self.banco else {}
        return {
            "configurado": self.configurado,
            "nivel": self.cliente.nivel if self.cliente else None,
            "uid": self.cliente.uid if self.cliente else None,
            "pistaId": self.pista_id,
            **fila,
        }

    # ----- montagem -----
    def sessao_para_upload(self, sessao_id: str, nome_sessao: str) -> Dict:
        if not self.banco:
            raise RuntimeError("sincronizador sem banco")
        voltas = self.banco.voltas_da_sessao(sessao_id)
        por_piloto: Dict[int, list] = {}
        for v in voltas:
            por_piloto.setdefault(v.piloto_id, []).append(v)

        itens = []
        for piloto_id, vs in por_piloto.items():
            piloto = self.banco.buscar_piloto(piloto_id)
            nome = piloto.nome if piloto else str(piloto_id)
            tempos = [v.tempo_us / 1_000_000 for v in vs]
            if not tempos:
                continue
            melhor = min(tempos)
            media = sum(tempos) / len(tempos)
            desvio = (sum((t - media) ** 2 for t in tempos) / len(tempos)) ** 0.5
            itens.append((piloto_id, nome, tempos, melhor, media, desvio))
        if not itens:
            raise ValueError("sessão sem voltas para enviar")
        itens.sort(key=lambda it: (-len(it[2]), it[3]))

        bat_key = "bat_" + _slug(nome_sessao) + f"_{int(time.time() * 1000)}"
        dados = []
        for pos, (piloto_id, nome, tempos, melhor, media, desvio) in enumerate(itens, start=1):
            dados.append({
                "piloto": nome, "pos": f"{pos}º", "bateriaKey": bat_key,
                "sessao": nome_sessao,
                "voltasTotais": len(tempos),
                "melhorVoltaVal": round(melhor, 3),
                "melhorVoltaTxt": f"{melhor:.3f}s".replace(".", ","),
                "mediaVal": round(media, 3),
                "mediaTxt": f"{media:.3f}s".replace(".", ","),
                "desvioVal": round(desvio, 3),
                "desvio": f"±{desvio:.3f}s".replace(".", ","),
                "laps": [round(t, 3) for t in tempos],
            })

        linhas = [f"Sessão: {nome_sessao}", f"Pista: {self.pista_id}",
                  f"Origem: KChrono (sensor direto)", ""]
        for d in dados:
            linhas.append(f"{d['pos']} {d['piloto']} — {d['voltasTotais']} voltas, "
                          f"melhor {d['melhorVoltaTxt']}, média {d['mediaTxt']}")
        texto = "\n".join(linhas)

        payload = {
            "bateriaKey": bat_key, "sessao": nome_sessao,
            "id": int(time.time() * 1000), "dados": dados,
            "nomeArquivoOriginal": f"{nome_sessao}.json",
            "historicoNomesOriginais": {d["piloto"]: d["piloto"] for d in dados},
            "textoExtraido": texto, "statusProcessamento": "processado",
            "fileHash": "", "parserVersion": PARSER_VERSION,
            "fileSize": len(texto.encode("utf-8")),
            "uploadedBy": self.cliente.uid if self.cliente else "local",
            "uploadedAt": int(time.time() * 1000),
            "pistaId": self.pista_id, "origem": "kchrono",
        }
        payload["fileHash"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        return payload

    # ----- fila -----
    def enfileirar(self, payload: Dict) -> str:
        if not self.banco:
            raise RuntimeError("sincronizador sem banco")
        self.banco.enfileirar_sync(payload["bateriaKey"], payload)
        return payload["bateriaKey"]

    def processar(self) -> Dict:
        if not self.cliente:
            raise ErroAuth("sync não configurado (configure e-mail/senha)")
        if not self.banco:
            raise RuntimeError("sincronizador sem banco")
        enviados = duplicados = falhas = 0
        for item in self.banco.fila_pendentes():
            payload = json.loads(item["payload"])
            try:
                dup, de_quem = self.cliente.existe_hash(payload["fileHash"])
                if dup:
                    self.banco.marcar_sync(item["id"], "duplicado")
                    duplicados += 1
                    log.info("%s duplicado de %s", payload["bateriaKey"], de_quem)
                    continue
                self.cliente.salvar_bateria(payload["bateriaKey"], payload,
                                            gerar_resumo(payload))
                self.banco.marcar_sync(item["id"], "enviado")
                enviados += 1
                log.info("%s enviado ao CTAD", payload["bateriaKey"])
            except (ErroAuth, ErroBanco) as e:
                self.banco.marcar_sync(item["id"], "erro", str(e))
                falhas += 1
                log.warning("falha ao enviar %s: %s", payload["bateriaKey"], e)
        return {"enviados": enviados, "duplicados": duplicados, "falhas": falhas}

    # ----- pilotos (CTAD <-> KChrono) -----
    def _mesclagens(self) -> Dict:
        """alias -> nome real (cache curto; o nó é público)."""
        import time as _t
        agora = _t.time()
        if getattr(self, "_mesclas_em", 0) and (agora - self._mesclas_em) < 300:
            return self._mesclas or {}
        try:
            self._mesclas = self.cliente.rtdb_get("mesclagensPilotos") or {} \
                if self.cliente else {}
        except ErroBanco as e:
            log.warning("não foi possível ler mesclagensPilotos: %s", e)
            self._mesclas = {}
        self._mesclas_em = agora
        return self._mesclas

    def nome_dono(self, nome) -> str:
        """Resolve alias para o nome real do piloto (mesma regra do site)."""
        if nome is None:
            return nome
        chave = meta_key(nome)
        dono = (self._mesclagens() or {}).get(chave)
        return dono if dono else nome

    def listar_pilotos_site(self) -> List[Dict]:
        """Lê o cadastro público de pilotos do CTAD (``pilotosMetadados``)."""
        if not self.cliente:
            raise ErroAuth("sync não configurado (configure e-mail/senha do CTAD)")
        metas = self.cliente.rtdb_get("pilotosMetadados") or {}
        saida: List[Dict] = []
        for chave, meta in metas.items():
            meta = meta or {}
            nome = self.nome_dono(str(chave or ""))
            nome = " ".join(str(nome).split())
            if not nome:
                continue
            saida.append({"chave": chave, "nome": nome,
                          "apelido": " ".join(str(meta.get("apelido") or "").split()),
                          "telefone": _so_digitos(meta.get("telefone")),
                          "criadoEm": meta.get("criadoEm") or 0})
        saida.sort(key=lambda d: (-int(d["criadoEm"] or 0), d["nome"].lower()))
        return saida

    def importar_pilotos(self, preview: bool = False) -> Dict:
        """Traz os pilotos do site para o KChrono.

        **Telefone é a CHAVE PRIMÁRIA** — a identidade do piloto. Não é um
        critério de casamento: ela *decide* quem é quem.

        Regras de identidade, em ordem:
          1. site com telefone -> busca local POR TELEFONE (autoritativo).
             Nome diferente **não** desfaz o vínculo; o nome é só atributo.
          2. não achado por telefone -> se existir UM único piloto local com o
             mesmo nome e SEM telefone, ele ADOTA o telefone (ganha a chave).
          3. se o local já tem OUTRO telefone, é outra pessoa: conflito.
             Um telefone nunca é sobrescrito por outro.
          4. site SEM telefone -> identidade indeterminada; resta casar por nome,
             e só quando o nomelocal for único.

        Só preenche ``nome``/``apelido``/``telefone`` — ``fonia``, ``funções``,
        ``ativo`` e transponders são exclusivos do app e **nunca** são sobrescritos.
        """
        if not self.cliente:
            raise ErroAuth("sync não configurado (configure e-mail/senha do CTAD)")
        if not self.banco:
            raise RuntimeError("sincronizador sem banco")

        remotos = self.listar_pilotos_site()
        # índice local: telefone -> id e nome normalizado -> [ids]
        por_tel: Dict[str, int] = {}
        por_nome: Dict[str, List[int]] = {}
        locais = {r["id"]: r for r in self.banco.listar_pilotos()}
        for pid, row in locais.items():
            tel = _so_digitos(row["telefone"])
            if tel:
                por_tel.setdefault(tel, pid)
            por_nome.setdefault(_norm_nome(row["nome"]), []).append(pid)

        novos, atualizados, adotados, iguais, conflitos = [], [], [], [], []
        telefone_no_lote: Dict[str, str] = {}

        for r in remotos:
            tel, nome = r["telefone"], r["nome"]
            chave_nome = _norm_nome(nome)
            vinculado_por = None

            # telefone repetido dentro do próprio site
            if tel:
                if tel in telefone_no_lote:
                    conflitos.append(
                        {"piloto": nome,
                         "motivo": f"telefone {tel} repetido no site "
                                   f"({telefone_no_lote[tel]})"})
                    continue
                telefone_no_lote[tel] = nome

            # ---------- resolve a identidade pela CHAVE PRIMÁRIA ----------
            if tel:
                alvo = por_tel.get(tel)
                if alvo is not None:
                    vinculado_por = "telefone"
                else:
                    # sem telefone local ainda: um único homônimo sem telefone
                    # pode adotar a chave (dois homônimos = ambíguo, não mexe)
                    sem_tel = [i for i in por_nome.get(chave_nome, [])
                               if not _so_digitos(locais[i]["telefone"])]
                    if len(sem_tel) == 1:
                        alvo, vinculado_por = sem_tel[0], "nome-adotou-telefone"
                    elif len(sem_tel) > 1:
                        conflitos.append(
                            {"piloto": nome,
                             "motivo": "vários pilotos locais sem telefone com esse "
                                       "nome — informe o telefone neles para vincular"})
                        continue
                    else:
                        alvo = None
            else:
                # site sem telefone: só o nome pode vincular, e só se for único
                homon = por_nome.get(chave_nome, [])
                if len(homon) == 1:
                    alvo, vinculado_por = homon[0], "nome"
                elif len(homon) > 1:
                    conflitos.append(
                        {"piloto": nome,
                         "motivo": "vários pilotos locais com esse nome (site sem "
                                   "telefone) — cadastre o telefone para vincular"})
                    continue
                else:
                    alvo = None

            if alvo is None:
                # Divergência de cadastro: o site dá um telefone para um nome que
                # LOCALMENTE já tem outro telefone. Criar outro registro duplicaria
                # a mesma pessoa — o telefone (chave primária) não é sobrescrito.
                if tel:
                    divergente = [i for i in por_nome.get(chave_nome, [])
                                  if _so_digitos(locais[i]["telefone"])]
                    if divergente:
                        divergente.sort()
                        conflitos.append(
                            {"piloto": nome,
                             "motivo": f"o site informa o telefone {tel}, mas "
                                       f"'{locais[divergente[0]]['nome']}' já tem "
                                       f"{_so_digitos(locais[divergente[0]]['telefone'])} — "
                                       "telefone não é sobrescrito"})
                        continue
                    if self.banco.piloto_com_telefone(tel):
                        conflitos.append({"piloto": nome,
                                          "motivo": f"telefone {tel} já é de outro piloto"})
                        continue
                novos.append({"nome": nome, "apelido": r["apelido"], "telefone": tel})
                # reserva a identidade no lote: o mesmo telefone/nome não entra
                # duas vezes (o site pode repetir a chave em outro formato)
                if tel:
                    por_tel[tel] = -1
                por_nome[chave_nome] = [-1]
                continue

            if alvo <= 0:
                # identidade já criada/atualizada neste mesmo lote
                iguais.append({"id": 0, "nome": nome})
                continue

            row = locais.get(alvo)
            if row is None:
                continue
            tel_atual = _so_digitos(row["telefone"])

            # um telefone NUNCA é trocado por outro (seria outra pessoa)
            if tel and tel_atual and tel != tel_atual:
                conflitos.append(
                    {"piloto": nome,
                     "motivo": f"'{row['nome']}' já tem o telefone {tel_atual} — "
                               f"o site informou {tel}; telefone não é sobrescrito"})
                continue

            mudar: List[str] = []
            adota = bool(tel) and tel != tel_atual
            if adota:
                mudar.append("telefone (chave primária)")
            if row["nome"] != nome:
                mudar.append("nome")
            if (row["apelido"] or "") != r["apelido"]:
                mudar.append("apelido")
            if not mudar:
                iguais.append({"id": alvo, "nome": row["nome"]})
                continue

            reg = {"id": alvo, "nome": nome, "apelido": r["apelido"], "telefone": tel or tel_atual,
                   "telefone_anterior": tel_atual, "campos": mudar, "vinculado_por": vinculado_por}
            if adota and row["nome"] == nome and (row["apelido"] or "") == r["apelido"]:
                adotados.append(reg)
            else:
                atualizados.append(reg)
            if not preview:
                self.banco.atualizar_piloto(alvo, nome, r["apelido"],
                                            row["fonia"] or "", bool(row["ativo"]),
                                            reg["telefone"], row["funcoes"] or "")

        if novos and not preview:
            for n in novos:
                pid = self.banco.criar_piloto(n["nome"], n["apelido"], "",
                                              n["telefone"], "")
                n["id"] = pid

        resultado = {"ok": True, "preview": preview, "remotos": len(remotos),
                     "novos": novos, "atualizados": atualizados, "adotados": adotados,
                     "iguais": len(iguais), "conflitos": conflitos}
        if not preview:
            self.banco.conn.commit()
        return resultado

    def exportar_piloto(self, piloto_id: int) -> Dict:
        """Cria o piloto no CTAD se ainda não existir (nunca sobrescreve)."""
        if not self.cliente:
            raise ErroAuth("sync não configurado (configure e-mail/senha do CTAD)")
        piloto = self.banco.buscar_piloto(piloto_id)
        if not piloto:
            raise ValueError("piloto não encontrado")
        chave = meta_key(piloto.nome)
        if self.cliente.rtdb_get(f"pilotosMetadados/{chave}") is not None:
            return {"ok": True, "criado": False, "chave": chave,
                    "msg": f"'{piloto.nome}' já existe no site"}
        dados: Dict = {"criadoEm": int(time.time() * 1000), "origem": "kchrono"}
        if (piloto.apelido or "").strip():
            dados["apelido"] = piloto.apelido.strip()
        if piloto.telefone:
            dados["telefone"] = piloto.telefone
        self.cliente.rtdb_put(f"pilotosMetadados/{chave}", dados)
        return {"ok": True, "criado": True, "chave": chave, "nome": piloto.nome}

    def importar_campeonato(self, chave_campeonato: str, campeonato_id: int,
                            preview: bool = False) -> Dict:
        """Traz **configuração + inscritos** de um campeonato do site.

        Alinha o campeonato local com o do CTAD: ``pilotosPorChave`` vira o teto
        das Chaves A/B/C, ``numeroProvas`` o número de provas e
        ``inverterSegundaBateria`` a inversão da grade da prova seguinte.
        """
        if not self.cliente:
            raise ErroAuth("sync não configurado (configure e-mail/senha do CTAD)")
        if not self.banco:
            raise RuntimeError("sincronizador sem banco")
        camp = self.banco.campeonato(campeonato_id)
        if not camp:
            raise ValueError("campeonato não encontrado")
        remoto = self.cliente.rtdb_get(f"campeonatos/{chave_campeonato}") or {}
        if not isinstance(remoto, dict) or not remoto:
            raise ValueError(f"campeonato '{chave_campeonato}' não encontrado no site")

        conf = remoto.get("configuracoes") or {}
        teto_atual = max_por_chave(camp)
        chave_max = int(conf.get("pilotosPorChave")
                        or conf.get("pilotosPorProva") or 0) or None
        n_provas = int(conf.get("numeroProvas") or 0) or None
        inverter = conf.get("inverterSegundaBateria")
        tabela = conf.get("pontuacaoTabela")
        config_aplicada: Dict = {}
        if chave_max and chave_max != teto_atual:
            config_aplicada["pilotos_por_chave"] = chave_max
        if n_provas and n_provas != int(camp["numero_provas"]):
            config_aplicada["numero_provas"] = n_provas
        if inverter is not None and bool(inverter) != bool(camp["inverter_bateria"]):
            config_aplicada["inverter_bateria"] = 1 if inverter else 0
        if isinstance(tabela, list) and tabela:
            config_aplicada["pontuacao_tabela"] = [int(x) for x in tabela]

        # inscritos -> pilotos locais -> inscrição no campeonato
        inscritos = remoto.get("pilotosInscritos") or {}
        ja_inscritos = {r["piloto_id"] for r in self.banco.listar_inscricoes(campeonato_id)}
        # nomes já existentes ANTES do loop, para saber quem foi criado agora
        antes = {_norm_nome(r["nome"]): r["id"] for r in self.banco.listar_pilotos()}
        entrar, criados = [], []
        vistos_nome = set()
        for _, obj in (inscritos or {}).items():
            nome = " ".join(str(self.nome_dono((obj or {}).get("nome") or "")).split())
            if not nome or nome in vistos_nome:
                continue
            vistos_nome.add(nome)
            pid = self.banco.garantir_piloto(nome)
            if _norm_nome(nome) not in antes:
                criados.append({"piloto_id": pid, "nome": nome})
            if pid not in ja_inscritos:
                entrar.append({"piloto_id": pid, "nome": nome})

        if not preview:
            if config_aplicada:
                self.banco.atualizar_campeonato(campeonato_id, **config_aplicada)
            for e in entrar:
                self.banco.inscrever(campeonato_id, e["piloto_id"])
            self.banco.conn.commit()

        return {"ok": True, "preview": preview,
                "campeonato": remoto.get("nome") or chave_campeonato,
                "config_aplicada": config_aplicada,
                "inscritos_site": len(inscritos), "a_inscrever": entrar,
                "pilotos_criados": criados,
                "inscritos_agora": len(ja_inscritos) + len(entrar)}

    def campeonato_site(self, chave_campeonato: str) -> Dict:
        """Lê ``campeonatos/<chave>`` do CTAD para o plano de etapas local.

        Devolve só a configuração que importa para as Chaves A/B/C, sem
        precisar de campeonato criado no KChrono.
        """
        if not self.cliente:
            raise ErroAuth("sync não configurado (configure e-mail/senha do CTAD)")
        remoto = self.cliente.rtdb_get(f"campeonatos/{chave_campeonato}") or {}
        if not isinstance(remoto, dict) or not remoto:
            raise ValueError(f"campeonato '{chave_campeonato}' não encontrado no site")
        conf = remoto.get("configuracoes") or {}
        return {"ok": True, "chave": chave_campeonato,
                "nome": remoto.get("nome") or chave_campeonato,
                "pilotosPorChave": (int(conf.get("pilotosPorChave")
                                        or conf.get("pilotosPorProva") or 0) or None),
                "inverterSegundaBateria": bool(conf.get("inverterSegundaBateria")),
                "numeroProvas": int(conf.get("numeroProvas") or 0) or None,
                "pontuacaoTabela": conf.get("pontuacaoTabela"),
                "inscritos": len(remoto.get("pilotosInscritos") or {})}

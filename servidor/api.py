"""KChrono — API REST + WebSocket do servidor local (Fase 2)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Dict, Optional

from fastapi import (Body, Depends, FastAPI, Header, HTTPException, Query, Request,
                     WebSocket, WebSocketDisconnect)
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .estado import EstadoApp
from .gerente import acesso
from .qr import (base_url_para_qr as qr_base_url, data_uri as qr_data_uri,
                 disponivel as qr_disponivel)
from sync import ErroAuth, ErroBanco
from caminhos import dir_recursos

log = logging.getLogger("kchrono.api")

DIR_PROJETO = dir_recursos()
DIR_INTERFACE = DIR_PROJETO / "interface"
DIR_IMAGENS = DIR_PROJETO / "imagens"

estado = EstadoApp()

app = FastAPI(title="KChrono", version="1.0.4")

app.mount("/imagens", StaticFiles(directory=DIR_IMAGENS), name="imagens")
app.mount("/static", StaticFiles(directory=DIR_INTERFACE), name="static")


@app.middleware("http")
async def _sem_cache_na_interface(request: Request, call_next):
    """Impede o WebView2 de servir HTML/JS/CSS antigos do cache.

    A janela nativa usa perfil persistente (``private_mode=False``); sem isso,
    após uma atualização o app continuava exibindo a interface anterior.
    Só as páginas/arquivos da interface recebem ``no-store`` — as APIs seguem
    normais.
    """
    resp = await call_next(request)
    caminho = request.url.path
    if (caminho.startswith("/static") or caminho.startswith("/imagens")
            or caminho in ("/", "/telao", "/gerente")):
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    return resp


@app.on_event("startup")
async def _auto_conectar_sync():
    """Reconecta o sync no boot (thread separada — nunca trava a subida)."""
    cfg = estado.config
    if not (cfg.get("email") and cfg.get("password")):
        pass
    elif not estado.sincronizador.configurado:
        try:
            info = await asyncio.to_thread(
                estado.configurar_sync,
                cfg["email"], cfg["password"], cfg.get("pistaId"))
            log.info("sync reconectado no boot (nível %s)", info.get("nivel"))
        except Exception as e:
            log.warning("sync não reconectado no boot: %s", e)
    # auto-conexão do decoder em loop (checkbox 'Conectar ao abrir', padrão on)
    estado.iniciar_auto_conectar()
    # aviso discreto de versão nova (uma vez por abertura, sem travar o boot)
    asyncio.create_task(_checar_atualizacao_boot())


async def _checar_atualizacao_boot():
    """Verifica o canal de atualização e avisa no log/painel se há versão nova."""
    await asyncio.sleep(20)
    try:
        from atualizador import verificar
        ver = await asyncio.to_thread(verificar)
    except Exception as e:
        log.debug("verificação de atualização falhou: %s", e)
        return
    if ver.get("disponivel"):
        msg = (f"v{ver['versao_remota']} disponível (atual v{ver['versao_atual']})"
               " — Admin → Sobre → Atualizações")
        log.info("atualização: %s", msg)
        estado.publicar("aviso", {"msg": msg})


@app.get("/api/status")
async def api_status():
    return estado.snapshot()


@app.post("/api/decoder/conectar")
async def api_conectar(tipo: str = Query("p3"), alvo: Optional[str] = Query(None),
                       velocidade: Optional[float] = Query(None)):
    if tipo == "simulador" and velocidade:
        estado.config["sim_velocidade"] = float(velocidade)
    return {"ok": await estado.conectar_decoder(tipo, alvo)}


@app.get("/api/simulador/sessoes")
async def api_simulador_sessoes():
    """Lista as corridas enviadas ao CTAD (opções do simulador de transponder)."""
    try:
        return {"ok": True, "sessoes": await asyncio.to_thread(estado.listar_sessoes_ctad)}
    except (ErroAuth, ErroBanco, ValueError, RuntimeError) as e:
        return {"ok": False, "erro": str(e)}


@app.get("/api/decoder/auto")
async def api_decoder_auto():
    """Checkbox 'Conectar ao abrir' (padrão ligado)."""
    return {"ativo": estado.decoder_auto_ativo()}


@app.post("/api/decoder/auto")
async def api_decoder_auto_definir(ativo: bool = Query(True)):
    return estado.definir_decoder_auto(ativo)


@app.get("/api/sessao/voz-contagem")
async def api_voz_contagem():
    """Checkbox 'voz na contagem' (padrão ligada)."""
    return {"ativa": estado.voz_contagem_ativa()}


@app.post("/api/sessao/voz-contagem")
async def api_voz_contagem_definir(ativa: bool = Query(True)):
    return estado.definir_voz_contagem(ativa)


@app.get("/api/telao/tela")
async def api_telao_tela():
    """Monitor escolhido para o telão 2ª tela."""
    return estado.telao_tela()


@app.post("/api/telao/tela")
async def api_telao_tela_definir(indice: int = Query(1)):
    try:
        return estado.definir_telao_tela(indice)
    except ValueError as e:
        return {"ok": False, "erro": str(e)}


@app.post("/api/decoder/desconectar")
async def api_desconectar():
    await estado.desconectar_decoder()
    return {"ok": True}


@app.get("/api/decoder/portas")
async def api_portas():
    from drivers.easylap import EasyLap
    return {"portas": EasyLap.listar_portas(), "drivers": ["p3", "easylap", "lapwiz"]}


@app.get("/api/versao")
async def api_versao():
    from atualizador import VERSAO_ATUAL, verificar
    return {"versao_atual": VERSAO_ATUAL, **await asyncio.to_thread(verificar)}


@app.post("/api/versao/baixar")
async def api_versao_baixar(chave: str = Query("windows")):
    from atualizador import baixar
    return await asyncio.to_thread(baixar, chave)


@app.post("/api/versao/repo")
async def api_versao_repo(repo: str = Query(...)):
    """Define o repositório GitHub (usuario/repo) usado para atualizar o app."""
    from .config import carregar_config, salvar_config
    cfg = carregar_config()
    cfg["atualizacao_repo"] = (repo or "").strip().strip("/")
    salvar_config(cfg)
    estado.config = cfg                       # mantém o config vivo em sincronia
    return {"ok": True, "repo": cfg["atualizacao_repo"]}


@app.post("/api/versao/instalar")
async def api_versao_instalar():
    """Baixa a versão nova, executa o instalador em silêncio e encerra o app."""
    from atualizador import instalar
    return await asyncio.to_thread(instalar)


# ---------------------------------------------------------------- voz / som (Admin)
@app.get("/api/som")
async def api_som():
    return estado.som_info()


@app.post("/api/som/ouvir")
async def api_som_ouvir(dados: dict = Body(...)):
    try:
        return estado.ouvir_som(**dados)
    except ValueError as e:
        return {"ok": False, "erro": str(e)}


@app.post("/api/som/salvar")
async def api_som_salvar(dados: dict = Body(...)):
    try:
        return estado.salvar_som(**dados)
    except ValueError as e:
        return {"ok": False, "erro": str(e)}


@app.post("/api/som/anunciar")
async def api_som_anunciar():
    return estado.anunciar_posicoes()


@app.post("/api/som/testar_passagem")
async def api_som_testar_passagem():
    """Pré-escuta do bip de passagem."""
    estado.som.bip_passagem()
    return {"ok": True}


@app.post("/api/som/testar_lider")
async def api_som_testar_lider():
    """Pré-escuta do bip do líder."""
    estado.som.bip_lider()
    return {"ok": True}


@app.post("/api/som/testar_menor_volta")
async def api_som_testar_menor_volta():
    """Pré-escuta dos 7 bipes da menor volta."""
    estado.som.testar_bip_menor_volta()
    return {"ok": True}


@app.post("/api/som/testar_luz")
async def api_som_testar_luz():
    """Pré-escuta do bipe de cada luz da contagem."""
    estado.som.testar_bip_luz()
    return {"ok": True}


@app.post("/api/som/testar_vai")
async def api_som_testar_vai():
    """Pré-escuta do bipe longo no verde (largada)."""
    estado.som.testar_bip_vai()
    return {"ok": True}


# ----- vozes neurais offline (Piper) -----
@app.get("/api/vozes")
async def api_vozes():
    """Modelos neurais disponíveis para baixar + os já instalados."""
    return estado.vozes_info()


@app.post("/api/vozes/instalar")
async def api_instalar_voz(modelo: str = Query("pt_BR-faber-medium")):
    """Baixa um modelo neural (Piper) para dados/vozes e passa a usá-lo."""
    try:
        return await estado.instalar_voz_neural(modelo)
    except ValueError as e:
        return {"ok": False, "erro": str(e)}


@app.delete("/api/vozes/{modelo}")
async def api_remover_voz(modelo: str):
    try:
        return estado.remover_voz_neural(modelo)
    except ValueError as e:
        return {"ok": False, "erro": str(e)}


@app.post("/api/som/falar")
async def api_som_falar(dados: dict = Body(default={})):
    """Fala um texto livre ou uma frase cadastrada (com placeholders)."""
    try:
        # o resto do corpo vira placeholders: {nome}, {tempo}, {n}...
        extra = {k: v for k, v in (dados or {}).items()
                 if k not in ("texto", "chave")}
        return estado.anunciar_texto(dados.get("texto"), dados.get("chave"),
                                     **extra)
    except (ValueError, TypeError) as e:
        return {"ok": False, "erro": str(e)}


# ----- estado da pista / check-in (acesso local do Admin) -----
@app.get("/api/pista/estado")
async def api_pista_estado():
    return estado.estado_pista()


@app.post("/api/pista/bandeira")
async def api_pista_bandeira(cor: str = Query(...), motivo: str = Query("")):
    try:
        return estado.definir_bandeira(cor, motivo)
    except ValueError as e:
        return {"ok": False, "erro": str(e)}


@app.get("/api/checkin")
async def api_checkin_listar():
    return {"presentes": estado.listar_presentes()}


@app.post("/api/checkin")
async def api_checkin(piloto_id: int = Query(...), presente: bool = Query(True)):
    try:
        return estado.definir_presente(piloto_id, presente)
    except ValueError as e:
        return {"ok": False, "erro": str(e)}


@app.post("/api/checkin/lote")
async def api_checkin_lote(dados: dict = Body(...)):
    try:
        return estado.definir_presentes(dados.get("presentes"))
    except ValueError as e:
        return {"ok": False, "erro": str(e)}


# ----- áudio gravado por frase (substitui a locução TTS) -----
@app.post("/api/som/audio")
async def api_som_audio_upload(request: Request, chave: str = Query(...),
                               nome: str = Query("audio.wav")):
    try:
        dados = await request.body()
        return estado.salvar_audio(chave, nome, dados)
    except ValueError as e:
        return {"ok": False, "erro": str(e)}


@app.get("/api/som/audio/{chave}")
async def api_som_audio_obter(chave: str):
    caminho = estado.caminho_audio(chave)
    if not caminho:
        return Response(status_code=404, content="áudio não encontrado")
    return FileResponse(caminho, filename=os.path.basename(caminho))


@app.delete("/api/som/audio")
async def api_som_audio_remover(chave: str = Query(...)):
    return estado.remover_audio(chave)


@app.post("/api/sessao/iniciar")
async def api_iniciar(tipo: str = Query("treino"), tempo_minimo_s: float = Query(0),
                      duracao: float = Query(10), criterio: str = Query("tempo"),
                      contador_s: Optional[int] = Query(None)):
    if contador_s is not None:
        estado.definir_contador_s(contador_s)
    return {"ok": estado.iniciar_sessao(tipo, tempo_minimo_s, duracao, criterio)}


@app.get("/api/sessao/contador")
async def api_contador():
    """Segundos da contagem antes da largada."""
    return {"contador_s": estado.contador_s(),
            "voz_contagem": estado.voz_contagem_ativa(),
            "rodando": bool(estado._largada and estado._largada.get("ativa")),
            **(estado._resumo_largada() if estado._largada else {"restante": 0})}


@app.post("/api/sessao/contador")
async def api_contador_definir(contador_s: int = Query(...)):
    try:
        return estado.definir_contador_s(contador_s)
    except ValueError as e:
        return {"ok": False, "erro": str(e)}


@app.post("/api/sessao/largada")
async def api_largada(contador_s: Optional[int] = Query(None)):
    """Começa a contagem regressiva (ou larga direto com contador 0)."""
    try:
        return estado.iniciar_largada(contador_s)
    except ValueError as e:
        return {"ok": False, "erro": str(e)}


@app.post("/api/sessao/marcar-gato")
async def api_marcar_gato(piloto_id: int = Query(...), volta: Optional[int] = Query(None)):
    return {"ok": estado.marcar_gato(piloto_id, volta)}


@app.post("/api/sessao/desmarcar-gato")
async def api_desmarcar(piloto_id: int = Query(...), volta: Optional[int] = Query(None)):
    return {"ok": estado.desmarcar_gato(piloto_id, volta)}


@app.post("/api/sessao/apagar-volta")
async def api_apagar_volta(piloto_id: int = Query(...), volta: Optional[int] = Query(None)):
    return {"ok": estado.apagar_volta(piloto_id, volta)}


@app.post("/api/sessao/adicionar-volta")
async def api_adicionar_volta(piloto_id: int = Query(...), tempo_s: float = Query(...)):
    ok = estado.adicionar_volta(piloto_id, tempo_s)
    if ok:
        return {"ok": True}
    return {"ok": False,
            "erro": "piloto fora da sessão (confira o check-in) ou tempo inválido"}


# ---------------------------------------------------------------- sync (Fase 3)
@app.post("/api/sync/configurar")
async def api_sync_configurar(email: str = Query(...), password: str = Query(...),
                              pista_id: Optional[str] = Query(None)):
    try:
        return {"ok": True, **estado.configurar_sync(email, password, pista_id)}
    except ErroAuth as e:
        # credenciais já foram persistidas antes do teste (configurar_sync)
        return {"ok": False, "erro": str(e), "salvo": True}


@app.post("/api/sync/enviar")
async def api_sync_enviar(nome: Optional[str] = Query(None),
                          sessao_id: Optional[str] = Query(None)):
    try:
        return {"ok": True, **estado.enviar_sessao(nome, sessao_id)}
    except (ErroAuth, ValueError, RuntimeError) as e:
        return {"ok": False, "erro": str(e)}


@app.get("/api/sync/previa/{sessao_id}")
async def api_sync_previa(sessao_id: str, nome: Optional[str] = Query(None)):
    try:
        return {"ok": True, "payload": estado.previa_sessao(sessao_id, nome)}
    except (ValueError, RuntimeError) as e:
        return {"ok": False, "erro": str(e)}


@app.post("/api/sync/processar")
async def api_sync_processar():
    try:
        return {"ok": True, **estado.sync_processar()}
    except (ErroAuth, RuntimeError) as e:
        return {"ok": False, "erro": str(e)}


@app.get("/api/sync/status")
async def api_sync_status():
    """Status do sync + credenciais salvas (app local: os campos do Admin
    precisam voltar a mostrar o que foi configurado)."""
    cfg = estado.config
    return {**estado.sincronizador.status(),
            "email": cfg.get("email", ""),
            "password": cfg.get("password", ""),
            "pistaId": cfg.get("pistaId", "krathus")}


@app.get("/api/sync/pilotos")
async def api_sync_pilotos(previa: bool = Query(True)):
    """Pilotos do CTAD. `previa=false` grava no banco local."""
    try:
        return estado.sync_pilotos_site(preview=previa)
    except ErroAuth as e:
        return {"ok": False, "erro": str(e)}


@app.post("/api/sync/pilotos/exportar")
async def api_sync_exportar_piloto(piloto_id: int = Query(...)):
    try:
        return estado.sync_exportar_piloto(piloto_id)
    except (ErroAuth, ValueError) as e:
        return {"ok": False, "erro": str(e)}


@app.post("/api/sync/campeonatos/{campeonato_id}/importar")
async def api_sync_importar_campeonato(campeonato_id: int, chave: str = Query(...),
                                       previa: bool = Query(True)):
    """Traz config (chaves) + inscritos de um campeonato do CTAD."""
    try:
        return estado.sync_importar_campeonato(campeonato_id, chave, preview=previa)
    except (ErroAuth, ValueError) as e:
        return {"ok": False, "erro": str(e)}


# ---------------------------------------------------------------- pilotos (Admin)
@app.get("/api/pilotos")
async def api_pilotos():
    return {"pilotos": estado.listar_pilotos()}


@app.get("/api/busca")
async def api_busca(q: str = Query(""), limite: int = Query(10)):
    return estado.buscar(q, limite)


@app.get("/api/notificacoes")
async def api_notificacoes():
    return {"notificacoes": estado.notificacoes()}


@app.post("/api/notificacoes")
async def api_salvar_notificacoes(dados: dict = Body(...)):
    return estado.salvar_notificacoes(dados)


# ---------------------------------------------------------------- campeonato (plano de etapas)
@app.get("/api/campeonato/plano")
async def api_campeonato_plano():
    return estado.campeonato_plano()


@app.post("/api/campeonato/plano")
async def api_salvar_campeonato_plano(dados: dict = Body(...)):
    try:
        return estado.salvar_campeonato_plano(dados.get("etapas"))
    except ValueError as e:
        return {"ok": False, "erro": str(e)}


@app.post("/api/campeonato/plano/montar")
async def api_montar_campeonato_plano(provas: int = Query(1),
                                      treino: Optional[int] = Query(None),
                                      classificacao: Optional[int] = Query(None),
                                      corrida: Optional[int] = Query(None),
                                      intervalo: Optional[int] = Query(None),
                                      class_3voltas: Optional[bool] = Query(None)):
    """Remonta a sequência (treino → classificação → corridas) pelo nº de provas."""
    try:
        return estado.montar_plano_campeonato(provas, treino, classificacao,
                                              corrida, intervalo, class_3voltas)
    except ValueError as e:
        return {"ok": False, "erro": str(e)}


@app.post("/api/campeonato/duracoes")
async def api_salvar_duracoes(treino: int = Query(10), classificacao: int = Query(10),
                              corrida: int = Query(20), intervalo: int = Query(5)):
    """Salva as durações do campeonato (escolhidas 1 vez) e remonta a sequência."""
    try:
        return estado.montar_plano_campeonato(
            (estado.campeonato_plano().get("numero_provas") or 1),
            treino, classificacao, corrida, intervalo)
    except ValueError as e:
        return {"ok": False, "erro": str(e)}


@app.post("/api/campeonato/regras")
async def api_campeonato_regras(class_3voltas: bool = Query(True)):
    """Regra do grid: classificação pelas 3 melhores voltas (média) ou melhor volta."""
    return estado.definir_class_regra(class_3voltas)


@app.post("/api/campeonato/iniciar")
async def api_iniciar_campeonato(tempo_minimo_s: float = Query(0),
                                 campeonato_id: Optional[int] = Query(None)):
    try:
        return estado.iniciar_campeonato(tempo_minimo_s, campeonato_id=campeonato_id)
    except ValueError as e:
        return {"ok": False, "erro": str(e)}


@app.get("/api/campeonato/estado")
async def api_campeonato_estado():
    """Situação do campeonato em andamento (etapa atual, próxima e total)."""
    return estado.campeonato_estado()


@app.post("/api/campeonato/proxima")
async def api_campeonato_proxima():
    """Avança MANUALMENTE para a próxima etapa (botão do operador)."""
    try:
        return estado.campeonato_proxima()
    except ValueError as e:
        return {"ok": False, "erro": str(e)}


@app.post("/api/campeonato/encerrar")
async def api_campeonato_encerrar():
    """Encerra o campeonato em andamento."""
    try:
        return estado.campeonato_encerrar()
    except ValueError as e:
        return {"ok": False, "erro": str(e)}


@app.get("/api/campeonato/ctad")
async def api_campeonato_ctad(chave: str = Query(...)):
    """Prévia da config de um campeonato do CTAD, para o plano de etapas local."""
    try:
        return estado.ctad_campeonato_previar(chave)
    except (ErroAuth, ValueError) as e:
        return {"ok": False, "erro": str(e)}


# ---------------------------------------------------------------- banner do dashboard
@app.get("/api/banner")
async def api_banner():
    """Slides do carrossel do dashboard."""
    return estado.banner()


@app.post("/api/banner")
async def api_salvar_banner(dados: dict = Body(...)):
    """Grava os slides do carrossel (Admin → Carrossel)."""
    try:
        return estado.salvar_banner(dados.get("slides"))
    except ValueError as e:
        return {"ok": False, "erro": str(e)}


# ---------------------------------------------------------------- relatórios
@app.get("/api/relatorios/resumo")
async def api_relatorio_resumo():
    return estado.relatorio_resumo()


@app.get("/api/relatorios/pilotos")
async def api_relatorio_pilotos():
    return {"pilotos": estado.relatorio_pilotos()}


@app.get("/api/relatorios/sessoes")
async def api_relatorio_sessoes(tipo: Optional[str] = Query(None),
                                de: Optional[str] = Query(None),
                                ate: Optional[str] = Query(None)):
    return {"sessoes": estado.relatorio_sessoes(tipo, de, ate)}


@app.get("/api/relatorios/sessao/{sessao_id}")
async def api_relatorio_sessao(sessao_id: str):
    try:
        return {"ok": True, **estado.relatorio_sessao(sessao_id)}
    except Exception as e:
        return {"ok": False, "erro": str(e)}


@app.get("/api/relatorios/{tipo}.csv")
async def api_relatorio_csv(tipo: str):
    if tipo not in ("pilotos", "sessoes"):
        return Response(status_code=404, content="relatório desconhecido")
    csv_txt = estado.relatorio_csv(tipo)
    return Response(content=csv_txt, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{tipo}.csv"'})


@app.post("/api/pilotos/criar")
async def api_criar_piloto(nome: str = Query(...), apelido: str = Query(""),
                           fonia: str = Query(""),
                           telefone: str = Query(""),
                           funcoes: str = Query(""),
                           transponders: Optional[str] = Query(None)):
    try:
        return {"ok": True, **estado.criar_piloto(nome, apelido, fonia, transponders,
                                                   telefone, funcoes)}
    except ValueError as e:
        return {"ok": False, "erro": str(e)}


@app.post("/api/pilotos/editar")
async def api_editar_piloto(piloto_id: int = Query(...), nome: str = Query(...),
                            apelido: str = Query(""), fonia: str = Query(""),
                            ativo: bool = Query(True),
                            telefone: str = Query(""), funcoes: str = Query(""),
                            transponders: Optional[str] = Query(None)):
    try:
        return {"ok": True, **estado.editar_piloto(piloto_id, nome, apelido, fonia,
                                                   ativo, transponders, telefone, funcoes)}
    except ValueError as e:
        return {"ok": False, "erro": str(e)}


@app.delete("/api/pilotos/{piloto_id}")
async def api_excluir_piloto(piloto_id: int):
    try:
        return {"ok": True, **estado.excluir_piloto(piloto_id)}
    except ValueError as e:
        return {"ok": False, "erro": str(e)}


# ---------------------------------------------------------------- campeonatos (Fase 5)
@app.get("/api/campeonatos")
async def api_campeonatos():
    return {"campeonatos": estado.campeonatos_resumo()}


@app.post("/api/campeonatos")
async def api_criar_campeonato(nome: str = Query(...), numero_provas: int = Query(4),
                               pilotos_por_prova: int = Query(10),
                               drop_rounds: int = Query(0),
                               bonus_pole: int = Query(0),
                               bonus_melhor_volta: int = Query(0),
                               tabela: Optional[str] = Query(None),
                               pilotos_por_chave: int = Query(10),
                               inverter_bateria: int = Query(0)):
    try:
        cid = estado.criar_campeonato(nome, numero_provas, pilotos_por_prova,
                                      drop_rounds, bonus_pole, bonus_melhor_volta,
                                      json.loads(tabela) if tabela else None,
                                      pilotos_por_chave=pilotos_por_chave,
                                      inverter_bateria=inverter_bateria)
        return {"ok": True, "id": cid}
    except ValueError as e:
        return {"ok": False, "erro": str(e)}


@app.get("/api/campeonatos/chaves")
async def api_distribuicao_chaves(total: int = Query(0), max: int = Query(10)):
    """Utilitário: distribuição das chaves para um total de pilotos (diretiva do CTAD)."""
    from nucleo.campeonatos import calcular_distribuicao_chaves
    return {"ok": True, "distribuicao": calcular_distribuicao_chaves(total, max)}


@app.get("/api/campeonatos/{campeonato_id}/grids")
async def api_campeonato_grids(campeonato_id: int):
    try:
        return estado.campeonato_grids(campeonato_id)
    except ValueError as e:
        return {"ok": False, "erro": str(e)}


@app.post("/api/campeonatos/{campeonato_id}/chaves")
async def api_definir_chaves(campeonato_id: int, max_por_chave: Optional[int] = Query(None),
                             inverter_bateria: Optional[int] = Query(None)):
    try:
        return estado.campeonato_definir_chaves(
            campeonato_id, max_por_chave,
            None if inverter_bateria is None else bool(inverter_bateria))
    except ValueError as e:
        return {"ok": False, "erro": str(e)}


@app.get("/api/campeonatos/{campeonato_id}")
async def api_campeonato_detalhe(campeonato_id: int):
    try:
        return {"ok": True, **estado.campeonato_detalhe(campeonato_id)}
    except ValueError as e:
        return {"ok": False, "erro": str(e)}


@app.post("/api/campeonatos/{campeonato_id}/inscrever")
async def api_inscrever(campeonato_id: int, piloto_id: int = Query(...),
                        transponder: Optional[int] = Query(None),
                        frequencia: Optional[str] = Query(None)):
    return {"ok": estado.inscrever_piloto(campeonato_id, piloto_id,
                                          transponder, frequencia)}


@app.post("/api/campeonatos/{campeonato_id}/heats")
async def api_gerar_heats(campeonato_id: int, num_finais: int = Query(1),
                          etapa: Optional[int] = Query(None)):
    try:
        return {"ok": True, **estado.gerar_heats_campeonato(campeonato_id,
                                                            num_finais, etapa)}
    except ValueError as e:
        return {"ok": False, "erro": str(e)}


@app.post("/api/campeonatos/baterias/{bateria_id}/lancar")
async def api_lancar_resultado(bateria_id: int):
    try:
        return {"ok": True, **estado.lancar_resultado_bateria(bateria_id)}
    except (ValueError, RuntimeError) as e:
        return {"ok": False, "erro": str(e)}


@app.get("/api/campeonatos/{campeonato_id}/ranking")
async def api_ranking(campeonato_id: int):
    try:
        return {"ok": True, "ranking": estado.ranking_campeonato(campeonato_id)}
    except ValueError as e:
        return {"ok": False, "erro": str(e)}


# ---------------------------------------------------------------- histórico (Central de Voltas)
@app.get("/api/historico")
async def api_historico():
    return {"sessoes": estado.historico()}


@app.get("/api/historico/{sessao_id}")
async def api_historico_sessao(sessao_id: str):
    d = estado.historico_sessao(sessao_id)
    if not d["pilotos"]:
        return {"ok": False, "erro": "sessão sem voltas registradas"}
    return {"ok": True, **d}


@app.delete("/api/sync/fila")
async def api_sync_limpar_fila():
    return {"ok": True, "removidos": estado.limpar_fila_sync()}


@app.post("/api/sessao/pausar")
async def api_pausar(pausar: bool = Query(True)):
    return {"ok": estado.pausar(pausar)}


@app.post("/api/sessao/finalizar")
async def api_finalizar():
    return {"ok": estado.finalizar()}


@app.get("/api/sessao/voltas")
async def api_voltas():
    return estado.dados_voltas()


# ---------------------------------------------------------------- gerente de pista
def _token_gerente(request: Request,
                   x_gerente_token: Optional[str] = Header(default=None)) -> Optional[str]:
    return x_gerente_token or request.query_params.get("token")


def exigir_gerente(request: Request,
                   x_gerente_token: Optional[str] = Header(default=None)) -> dict:
    sessao = acesso.validar(_token_gerente(request, x_gerente_token))
    if not sessao:
        raise HTTPException(status_code=401, detail="não autenticado")
    return sessao


@app.get("/api/gerente/estado")
async def gerente_estado(request: Request,
                         x_gerente_token: Optional[str] = Header(default=None)):
    sessao = acesso.validar(_token_gerente(request, x_gerente_token))
    return {"ok": True, "configurado": acesso.configurado(),
            "autenticado": bool(sessao),
            "usuario": sessao["usuario"] if sessao else None,
            "pista": estado.estado_pista()}


@app.post("/api/gerente/configurar")
async def gerente_configurar(dados: dict = Body(...),
                             x_gerente_token: Optional[str] = Header(default=None)):
    token = dados.get("token") or x_gerente_token
    if acesso.configurado() and not acesso.validar(token):
        return {"ok": False, "erro": "já configurado — faça login para trocar a senha"}
    try:
        trocou = acesso.configurado()
        info = acesso.definir_credenciais(dados.get("usuario"), dados.get("senha"), trocou)
        novo = acesso.criar_token(info["usuario"])
        return {"ok": True, "token": novo, "usuario": info["usuario"]}
    except ValueError as e:
        return {"ok": False, "erro": str(e)}


@app.post("/api/gerente/login")
async def gerente_login(dados: dict = Body(...)):
    if not acesso.configurado():
        return {"ok": False, "precisa_configurar": True}
    if acesso.conferir(dados.get("usuario"), dados.get("senha")):
        return {"ok": True, "token": acesso.criar_token(dados.get("usuario")),
                "usuario": acesso.usuario()}
    return {"ok": False, "erro": "usuário ou senha inválidos"}


@app.post("/api/gerente/logout")
async def gerente_logout(request: Request,
                          x_gerente_token: Optional[str] = Header(default=None)):
    acesso.revogar(_token_gerente(request, x_gerente_token))
    return {"ok": True}


@app.post("/api/gerente/qrcode")
async def gerente_qrcode(request: Request,
                         sessao: dict = Depends(exigir_gerente),
                         x_gerente_token: Optional[str] = Header(default=None),
                         dias: int = Query(30)):
    """Emite um QR Code de acesso — **rotaciona** o anterior.

    O token vai no **fragmento** da URL (``#t=...``): não aparece no histórico
    do servidor nem no ``Referer``. Vale por ``dias`` e o QR anterior deixa de
    valer na hora. A sessão de quem gerou é preservada.
    """
    if not qr_disponivel():
        return {"ok": False, "erro": "biblioteca de QR indisponível (pip install segno)"}
    try:
        return {"ok": True, **_emitir_qr(request, dias,
                                         preservar=_token_gerente(request, x_gerente_token))}
    except (RuntimeError, ValueError) as e:
        return {"ok": False, "erro": str(e)}


def _emitir_qr(request: Request, dias: int = 30,
               preservar: Optional[str] = None) -> Dict:
    """Emite (rotacionando) um convite de acesso + QR em data URI.

    Lógica compartilhada entre a página do gerente (autenticada) e o Admin
    local (operador da máquina, já com acesso total — dispensa o login).
    """
    janela = max(1, min(int(dias), 365))
    convite = acesso.criar_convite(ttl_s=janela * 86400, preservar=preservar)
    # NUNCA localhost: o QR é para o celular (na LAN), e localhost no celular
    # é o próprio celular — não conecta e cai na tela de login.
    base = qr_base_url(request.url.hostname, request.url.port)
    url = f"{base}/gerente#t={convite['token']}"
    imagem = qr_data_uri(url, escala=8)
    return {"url": url, "token": convite["token"], "qrcode": imagem,
            "expira_em": convite["expira_em"], "ttl_s": convite["ttl_s"],
            "substituidos": convite["substituidos"], "dias": janela}


@app.post("/api/admin/qrcode")
async def admin_qrcode(request: Request, dias: int = Query(30)):
    """Emite o QR Code de acesso pelo Admin (operador local, sem login)."""
    if not qr_disponivel():
        return {"ok": False, "erro": "biblioteca de QR indisponível (pip install segno)"}
    try:
        return {"ok": True, **_emitir_qr(request, dias)}
    except (RuntimeError, ValueError) as e:
        return {"ok": False, "erro": str(e)}


@app.get("/api/admin/qrcode/convites")
async def admin_convites():
    """QR Code ativo e seu tempo restante (Admin local)."""
    return {"ok": True, "convites": acesso.convites()}


@app.delete("/api/admin/qrcode")
async def admin_revogar_qrcode():
    """Invalida o QR Code atual pelo Admin. A senha do gerente continua valendo."""
    return {"ok": True, "revogados": acesso.revogar_convites()}


@app.get("/api/gerente/qrcode/convites")
async def gerente_convites(sessao: dict = Depends(exigir_gerente)):
    """QR Code ativo e seu tempo restante (para poder revogar)."""
    return {"ok": True, "convites": acesso.convites()}


def _qr_atual(request: Request) -> Dict:
    """Devolve o QR ativo (sem gerar um novo).

    Abrir a tela do QR não rotaciona mais: só o botão "Gerar" troca o QR.
    """
    ativos = acesso.convites()
    if not ativos:
        return {"ok": False, "vazio": True}
    atual = ativos[-1]
    base = qr_base_url(request.url.hostname, request.url.port)
    url = f"{base}/gerente#t={atual['token']}"
    imagem = qr_data_uri(url, escala=8)
    return {"ok": True, "url": url, "token": atual["token"], "qrcode": imagem,
            "expira_em": atual["expira_em"], "ttl_s": atual["restante_s"],
            "dias": max(1, round(atual["restante_s"] / 86400))}


@app.get("/api/gerente/qrcode/atual")
async def gerente_qr_atual(request: Request,
                           sessao: dict = Depends(exigir_gerente)):
    """Mostra o QR ativo sem rotacionar (abrir a tela não derruba ninguém)."""
    if not qr_disponivel():
        return {"ok": False, "erro": "biblioteca de QR indisponível (pip install segno)"}
    try:
        return _qr_atual(request)
    except (RuntimeError, ValueError) as e:
        return {"ok": False, "erro": str(e)}


@app.get("/api/admin/qrcode/atual")
async def admin_qr_atual(request: Request):
    """Mostra o QR ativo sem rotacionar (Admin local)."""
    if not qr_disponivel():
        return {"ok": False, "erro": "biblioteca de QR indisponível (pip install segno)"}
    try:
        return _qr_atual(request)
    except (RuntimeError, ValueError) as e:
        return {"ok": False, "erro": str(e)}


@app.delete("/api/gerente/qrcode")
async def gerente_revogar_qrcode(request: Request,
                                 sessao: dict = Depends(exigir_gerente),
                                 x_gerente_token: Optional[str] = Header(default=None)):
    """Invalida o QR Code atual. A senha do gerente continua valendo."""
    preservar = _token_gerente(request, x_gerente_token)
    return {"ok": True, "revogados": acesso.revogar_convites(preservar=preservar)}


@app.get("/api/gerente/painel")
async def gerente_painel(sessao: dict = Depends(exigir_gerente)):
    return {"ok": True, "usuario": sessao["usuario"], **estado.painel_gerente()}


@app.post("/api/gerente/sessao/iniciar")
async def gerente_iniciar(tipo: str = Query("treino"),
                          tempo_minimo_s: float = Query(0),
                          duracao: float = Query(10),
                          criterio: str = Query("tempo"),
                          sessao: dict = Depends(exigir_gerente)):
    return {"ok": estado.iniciar_sessao(tipo, tempo_minimo_s, duracao, criterio)}


@app.post("/api/gerente/sessao/largada")
async def gerente_largada(contador_s: Optional[int] = Query(None),
                          sessao: dict = Depends(exigir_gerente)):
    """Começa a contagem regressiva (mesma linha do tempo do operador)."""
    try:
        return estado.iniciar_largada(contador_s)
    except ValueError as e:
        return {"ok": False, "erro": str(e)}


@app.post("/api/gerente/sessao/pausar")
async def gerente_pausar(pausar: bool = Query(True),
                         sessao: dict = Depends(exigir_gerente)):
    return {"ok": estado.pausar(pausar)}


@app.post("/api/gerente/sessao/finalizar")
async def gerente_finalizar(sessao: dict = Depends(exigir_gerente)):
    return {"ok": estado.finalizar()}


@app.post("/api/gerente/voltas/marcar-gato")
async def gerente_marcar_gato(piloto_id: int = Query(...),
                              volta: Optional[int] = Query(None),
                              sessao: dict = Depends(exigir_gerente)):
    return {"ok": estado.marcar_gato(piloto_id, volta)}


@app.post("/api/gerente/voltas/desmarcar-gato")
async def gerente_desmarcar_gato(piloto_id: int = Query(...),
                                 volta: Optional[int] = Query(None),
                                 sessao: dict = Depends(exigir_gerente)):
    return {"ok": estado.desmarcar_gato(piloto_id, volta)}


@app.post("/api/gerente/voltas/apagar")
async def gerente_apagar_volta(piloto_id: int = Query(...),
                               volta: Optional[int] = Query(None),
                               sessao: dict = Depends(exigir_gerente)):
    return {"ok": estado.apagar_volta(piloto_id, volta)}


@app.post("/api/gerente/voltas/adicionar")
async def gerente_adicionar_volta(piloto_id: int = Query(...),
                                  tempo_s: float = Query(...),
                                  sessao: dict = Depends(exigir_gerente)):
    return {"ok": estado.adicionar_volta(piloto_id, tempo_s)}


@app.post("/api/gerente/pista/bandeira")
async def gerente_bandeira(cor: str = Query(...), motivo: str = Query(""),
                           sessao: dict = Depends(exigir_gerente)):
    try:
        return estado.definir_bandeira(cor, motivo)
    except ValueError as e:
        return {"ok": False, "erro": str(e)}


@app.post("/api/gerente/checkin")
async def gerente_checkin(piloto_id: int = Query(...),
                          presente: bool = Query(True),
                          sessao: dict = Depends(exigir_gerente)):
    try:
        return estado.definir_presente(piloto_id, presente)
    except ValueError as e:
        return {"ok": False, "erro": str(e)}


@app.post("/api/gerente/checkin/lote")
async def gerente_checkin_lote(dados: dict = Body(...),
                               sessao: dict = Depends(exigir_gerente)):
    try:
        return estado.definir_presentes(dados.get("presentes"))
    except ValueError as e:
        return {"ok": False, "erro": str(e)}


@app.post("/api/gerente/anunciar")
async def gerente_anunciar(dados: dict = Body(default={}),
                           sessao: dict = Depends(exigir_gerente)):
    try:
        if dados.get("posicoes"):
            return estado.anunciar_posicoes()
        return estado.anunciar_texto(dados.get("texto"), dados.get("chave"))
    except ValueError as e:
        return {"ok": False, "erro": str(e)}


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    fila = estado.assinar()
    try:
        await websocket.send_json({"tipo": "snapshot", **estado.snapshot()})
        while True:
            evento = await fila.get()
            await websocket.send_json(evento)
    except WebSocketDisconnect:
        pass
    finally:
        estado.cancelar(fila)


@app.get("/")
async def home():
    return FileResponse(DIR_INTERFACE / "index.html")


@app.get("/telao")
async def tela_telao():
    return FileResponse(DIR_INTERFACE / "telao.html")


@app.get("/gerente")
async def tela_gerente():
    return FileResponse(DIR_INTERFACE / "gerente.html")


@app.websocket("/ws/gerente")
async def ws_gerente(websocket: WebSocket):
    """Mesmo fluxo de eventos do /ws, porém exige o token do gerente."""
    if not acesso.validar(websocket.query_params.get("token")):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    fila = estado.assinar()
    try:
        await websocket.send_json({"tipo": "snapshot", **estado.snapshot()})
        while True:
            evento = await fila.get()
            await websocket.send_json(evento)
    except WebSocketDisconnect:
        pass
    finally:
        estado.cancelar(fila)

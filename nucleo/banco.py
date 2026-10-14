"""KChrono — banco local SQLite com migrações (Fase 1).

Local-first: todas as sessões ficam gravadas aqui; a sincronização com o CTAD
(Fase 3) é uma camada separada sobre estes dados.

Thread-safety: a conexão é envolvida por _ConexaoTravada (RLock) — o uvicorn
atende cada request em thread própria e o loop do decoder roda em outra;
sem a trava, `sqlite3.ProgrammingError: objects created in a thread can only
be used in that same thread` derruba /api/sync/status e afins.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from typing import Dict, List, Optional

from .modelos import (EstadoSessao, Pista, Piloto, Sessao, TipoSessao,
                      Transponder, Volta, agora_iso)


class _CursorBufferizado:
    """Cursor com linhas já buscadas — seguro para usar após liberar a trava.

    Suporta o que o código usa: fetchone/fetchall, iteração, índice [0],
    lastrowid e rowcount.
    """

    def __init__(self, linhas, lastrowid=None, rowcount=-1):
        self._linhas = linhas
        self._pos = 0
        self.lastrowid = lastrowid
        self.rowcount = rowcount

    def fetchone(self):
        if self._pos >= len(self._linhas):
            return None
        linha = self._linhas[self._pos]
        self._pos += 1
        return linha

    def fetchall(self):
        resto = self._linhas[self._pos:]
        self._pos = len(self._linhas)
        return resto

    def __iter__(self):
        while self._pos < len(self._linhas):
            yield self.fetchone()

    def __getitem__(self, i):
        return self._linhas[i]


class _ConexaoTravada:
    """Envolve sqlite3.Connection com RLock — todo acesso é serializado.

    Compatível com os usos existentes: execute/executemany/executescript,
    commit/rollback e o bloco `with conn:` (transação).

    Detalhe importante: execute/executemany já devolvem as linhas buscadas
    (_CursorBufferizado) AINDA COM a trava — o fetch acontece dentro do
    lock, então duas threads nunca intercalam buscas na mesma conexão.
    """

    def __init__(self, caminho: str):
        interna = sqlite3.connect(caminho, check_same_thread=False)
        interna.row_factory = sqlite3.Row
        interna.execute("PRAGMA foreign_keys = ON")
        interna.execute("PRAGMA busy_timeout = 5000")
        object.__setattr__(self, "_interna", interna)
        object.__setattr__(self, "_trava", threading.RLock())

    def _executar(self, metodo: str, *a, **kw):
        trava = object.__getattribute__(self, "_trava")
        interna = object.__getattribute__(self, "_interna")
        with trava:
            cur = getattr(interna, metodo)(*a, **kw)
            try:
                linhas = cur.fetchall()
            except Exception:
                linhas = []
            return _CursorBufferizado(
                linhas,
                lastrowid=getattr(cur, "lastrowid", None),
                rowcount=getattr(cur, "rowcount", -1))

    def execute(self, *a, **kw):
        return self._executar("execute", *a, **kw)

    def executemany(self, *a, **kw):
        return self._executar("executemany", *a, **kw)

    def executescript(self, *a, **kw):
        trava = object.__getattribute__(self, "_trava")
        interna = object.__getattribute__(self, "_interna")
        with trava:
            return interna.executescript(*a, **kw)

    def __getattr__(self, nome):
        alvo = getattr(object.__getattribute__(self, "_interna"), nome)
        if callable(alvo):
            trava = object.__getattribute__(self, "_trava")

            def embrulhado(*a, **kw):
                with trava:
                    return alvo(*a, **kw)
            return embrulhado
        return alvo

    def __setattr__(self, nome, valor):
        if nome in ("_interna", "_trava"):
            object.__setattr__(self, nome, valor)
        else:
            with object.__getattribute__(self, "_trava"):
                setattr(object.__getattribute__(self, "_interna"), nome, valor)

    def __enter__(self):
        object.__getattribute__(self, "_trava").acquire()
        object.__getattribute__(self, "_interna").__enter__()
        return self

    def __exit__(self, *exc):
        try:
            return object.__getattribute__(self, "_interna").__exit__(*exc)
        finally:
            object.__getattribute__(self, "_trava").release()

ESQUEMA_V1 = """
CREATE TABLE IF NOT EXISTS pistas (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pilotos (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    nome   TEXT NOT NULL,
    apelido TEXT NOT NULL DEFAULT '',
    ativo  INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS transponders (
    codigo    INTEGER PRIMARY KEY,
    piloto_id INTEGER NOT NULL REFERENCES pilotos(id)
);

CREATE TABLE IF NOT EXISTS sessoes (
    id         TEXT PRIMARY KEY,
    pista_id   INTEGER REFERENCES pistas(id),
    tipo       TEXT NOT NULL,
    estado     TEXT NOT NULL,
    inicio     TEXT,
    fim        TEXT,
    parametros TEXT NOT NULL DEFAULT '{}'
);

-- Passings crus, exatamente como chegaram do decoder (auditoria/replay).
CREATE TABLE IF NOT EXISTS passings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sessao_id       TEXT NOT NULL REFERENCES sessoes(id),
    transponder     INTEGER NOT NULL,
    rtc_time        INTEGER NOT NULL,   -- microssegundos (epoch do decoder)
    passing_number  INTEGER,
    strength        INTEGER,
    hits            INTEGER,
    recebido_em     TEXT NOT NULL,
    processado      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_passings_sessao ON passings(sessao_id);

-- Voltas já consolidadas (idempotente por (sessao, piloto, numero)).
CREATE TABLE IF NOT EXISTS voltas (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    sessao_id  TEXT NOT NULL REFERENCES sessoes(id),
    piloto_id  INTEGER NOT NULL REFERENCES pilotos(id),
    numero     INTEGER NOT NULL,
    tempo_us   INTEGER NOT NULL,
    melhor     INTEGER NOT NULL DEFAULT 0,
    UNIQUE (sessao_id, piloto_id, numero)
);
CREATE INDEX IF NOT EXISTS idx_voltas_sessao ON voltas(sessao_id);
"""

#: Fase 3 — fila de sincronização com o CTAD
ESQUEMA_V3 = """
CREATE TABLE IF NOT EXISTS fila_sync (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    bat_key     TEXT NOT NULL UNIQUE,
    payload     TEXT NOT NULL,
    estado      TEXT NOT NULL DEFAULT 'pendente',   -- pendente/enviado/duplicado/erro
    tentativas  INTEGER NOT NULL DEFAULT 0,
    erro        TEXT,
    criado_em   TEXT NOT NULL,
    enviado_em  TEXT
);
CREATE INDEX IF NOT EXISTS idx_fila_estado ON fila_sync(estado);
"""

#: Fase 5 — campeonatos (grid builder, espectro, pontuação)
ESQUEMA_V4 = """
CREATE TABLE IF NOT EXISTS campeonatos (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    nome                TEXT NOT NULL,
    numero_provas       INTEGER NOT NULL DEFAULT 4,
    pilotos_por_prova   INTEGER NOT NULL DEFAULT 10,
    pontuacao_tabela    TEXT NOT NULL DEFAULT '[25,18,15,12,10,8,6,4,2,1]',
    drop_rounds         INTEGER NOT NULL DEFAULT 0,
    bonus_pole          INTEGER NOT NULL DEFAULT 0,
    bonus_melhor_volta  INTEGER NOT NULL DEFAULT 0,
    criado_em           TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inscricoes (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    campeonato_id  INTEGER NOT NULL REFERENCES campeonatos(id),
    piloto_id      INTEGER NOT NULL REFERENCES pilotos(id),
    transponder    INTEGER,
    frequencia     TEXT,
    pontos_ranking REAL NOT NULL DEFAULT 0,
    UNIQUE (campeonato_id, piloto_id)
);
CREATE TABLE IF NOT EXISTS etapas (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    campeonato_id  INTEGER NOT NULL REFERENCES campeonatos(id),
    numero         INTEGER NOT NULL,
    data           TEXT,
    status         TEXT NOT NULL DEFAULT 'pendente'
);
CREATE TABLE IF NOT EXISTS baterias (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    etapa_id   INTEGER NOT NULL REFERENCES etapas(id),
    nome       TEXT NOT NULL,
    fase       TEXT NOT NULL DEFAULT 'heat',
    sessao_id  TEXT,
    liberada   INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS resultados (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bateria_id      INTEGER NOT NULL REFERENCES baterias(id),
    piloto_id       INTEGER NOT NULL,
    posicao         INTEGER NOT NULL,
    pontos          INTEGER NOT NULL DEFAULT 0,
    melhor_volta_us INTEGER,
    pole            INTEGER NOT NULL DEFAULT 0
);
"""


class Banco:
    """Acesso ao SQLite local com migrações versionadas (PRAGMA user_version).

    Thread-safe via _ConexaoTravada — pode ser usado do loop asyncio do
    decoder e das threads do uvicorn ao mesmo tempo.
    """

    def __init__(self, caminho: str = ":memory:"):
        self.conn = _ConexaoTravada(caminho)
        self._migrar()

    # ----- migrações -----
    def _migrar(self):
        versao = self.conn.execute("PRAGMA user_version").fetchone()[0]
        with self.conn:
            if versao < 1:
                self.conn.executescript(ESQUEMA_V1)
                self.conn.execute("PRAGMA user_version = 1")
                self.conn.execute(
                    "CREATE TABLE IF NOT EXISTS _migracoes ("
                    " versao INTEGER PRIMARY KEY, aplicada_em TEXT)")
                self.conn.execute(
                    "INSERT OR REPLACE INTO _migracoes (versao, aplicada_em)"
                    " VALUES (1, ?)", (agora_iso(),))
            if versao < 2:
                # Fase 1.5: auditoria de passings rejeitados (ghost lap / tempo mínimo)
                self.conn.execute(
                    "ALTER TABLE passings ADD COLUMN valido INTEGER NOT NULL DEFAULT 1")
                self.conn.execute("PRAGMA user_version = 2")
                self.conn.execute(
                    "INSERT OR REPLACE INTO _migracoes (versao, aplicada_em)"
                    " VALUES (2, ?)", (agora_iso(),))
            if versao < 3:
                # Fase 3: fila de sincronização com o CTAD (offline-first)
                self.conn.executescript(ESQUEMA_V3)
                self.conn.execute("PRAGMA user_version = 3")
                self.conn.execute(
                    "INSERT OR REPLACE INTO _migracoes (versao, aplicada_em)"
                    " VALUES (3, ?)", (agora_iso(),))
            if versao < 4:
                # Fase 5: campeonatos (heats, espectro, pontuação)
                self.conn.executescript(ESQUEMA_V4)
                self.conn.execute("PRAGMA user_version = 4")
                self.conn.execute(
                    "INSERT OR REPLACE INTO _migracoes (versao, aplicada_em)"
                    " VALUES (4, ?)", (agora_iso(),))
            if versao < 5:
                # Fase 4.1: fonia do piloto (pronúncia do nome na locução TTS)
                self.conn.execute(
                    "ALTER TABLE pilotos ADD COLUMN fonia TEXT NOT NULL DEFAULT ''")
                self.conn.execute("PRAGMA user_version = 5")
                self.conn.execute(
                    "INSERT OR REPLACE INTO _migracoes (versao, aplicada_em)"
                    " VALUES (5, ?)", (agora_iso(),))
            if versao < 6:
                # Fase 8: telefone (chave natural única) + funções extra do piloto
                self.conn.execute(
                    "ALTER TABLE pilotos ADD COLUMN telefone TEXT NOT NULL DEFAULT ''")
                self.conn.execute(
                    "ALTER TABLE pilotos ADD COLUMN funcoes TEXT NOT NULL DEFAULT ''")
                # telefone vira chave primária lógica: único quando informado
                self.conn.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_pilotos_telefone"
                    " ON pilotos(telefone) WHERE telefone <> ''")
                self.conn.execute("PRAGMA user_version = 6")
                self.conn.execute(
                    "INSERT OR REPLACE INTO _migracoes (versao, aplicada_em)"
                    " VALUES (6, ?)", (agora_iso(),))
            if versao < 7:
                # Fase 5.1: sistema de chaves (divisão da grade) + inversão da bateria
                self.conn.execute(
                    "ALTER TABLE campeonatos ADD COLUMN pilotos_por_chave INTEGER NOT NULL DEFAULT 10")
                self.conn.execute(
                    "ALTER TABLE campeonatos ADD COLUMN inverter_bateria INTEGER NOT NULL DEFAULT 0")
                self.conn.execute("PRAGMA user_version = 7")
                self.conn.execute(
                    "INSERT OR REPLACE INTO _migracoes (versao, aplicada_em)"
                    " VALUES (7, ?)", (agora_iso(),))

    # ----- pistas -----
    def criar_pista(self, nome: str) -> int:
        with self.conn:
            cur = self.conn.execute("INSERT INTO pistas (nome) VALUES (?)", (nome,))
        return cur.lastrowid

    # ----- pilotos -----
    def criar_piloto(self, nome: str, apelido: str = "", fonia: str = "",
                     telefone: str = "", funcoes: str = "") -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO pilotos (nome, apelido, fonia, telefone, funcoes)"
                " VALUES (?, ?, ?, ?, ?)",
                (nome, apelido, fonia, telefone, funcoes))
        return cur.lastrowid

    def garantir_piloto(self, nome: str, apelido: str = "", fonia: str = "") -> int:
        """Retorna o id de um piloto existente com esse nome, ou cria um novo."""
        row = self.conn.execute(
            "SELECT id FROM pilotos WHERE nome = ? ORDER BY id LIMIT 1", (nome,)).fetchone()
        return row["id"] if row else self.criar_piloto(nome, apelido, fonia)

    def piloto_com_telefone(self, telefone: str, ignorar_id: Optional[int] = None):
        """Piloto dono deste telefone (chave natural), se houver."""
        telefone = (telefone or "").strip()
        if not telefone:
            return None
        if ignorar_id is not None:
            return self.conn.execute(
                "SELECT * FROM pilotos WHERE telefone = ? AND id <> ?",
                (telefone, ignorar_id)).fetchone()
        return self.conn.execute(
            "SELECT * FROM pilotos WHERE telefone = ?", (telefone,)).fetchone()

    def atualizar_piloto(self, piloto_id: int, nome: str, apelido: str = "",
                         fonia: str = "", ativo: bool = True,
                         telefone: str = "", funcoes: str = "") -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE pilotos SET nome = ?, apelido = ?, fonia = ?, ativo = ?,"
                " telefone = ?, funcoes = ? WHERE id = ?",
                (nome, apelido, fonia, 1 if ativo else 0, telefone, funcoes, piloto_id))

    def pilotos_detalhado(self):
        """Pilotos com a lista de transponders agregada (Admin → Pilotos)."""
        return self.conn.execute(
            "SELECT p.id, p.nome, p.apelido, p.fonia, p.ativo, p.telefone, p.funcoes,"
            " GROUP_CONCAT(t.codigo) AS transponders"
            " FROM pilotos p LEFT JOIN transponders t ON t.piloto_id = p.id"
            " GROUP BY p.id ORDER BY p.ativo DESC, p.nome COLLATE NOCASE").fetchall()

    def transponders_do_piloto(self, piloto_id: int) -> list:
        rows = self.conn.execute(
            "SELECT codigo FROM transponders WHERE piloto_id = ? ORDER BY codigo",
            (piloto_id,)).fetchall()
        return [r["codigo"] for r in rows]

    def definir_transponders(self, piloto_id: int, codigos: list) -> None:
        """Substitui a lista de transponders do piloto (reassocia códigos existentes)."""
        with self.conn:
            self.conn.execute("DELETE FROM transponders WHERE piloto_id = ?", (piloto_id,))
            for c in codigos:
                self.conn.execute("INSERT OR REPLACE INTO transponders (codigo, piloto_id)"
                                  " VALUES (?, ?)", (int(c), piloto_id))

    def piloto_tem_historico(self, piloto_id: int) -> bool:
        for tabela in ("voltas", "inscricoes", "resultados"):
            if self.conn.execute(
                    f"SELECT 1 FROM {tabela} WHERE piloto_id = ? LIMIT 1",
                    (piloto_id,)).fetchone():
                return True
        return False

    def excluir_piloto(self, piloto_id: int) -> Dict:
        """Remove o piloto e seus transponders; com histórico, apenas inativa."""
        if not self.buscar_piloto(piloto_id):
            raise ValueError("piloto não encontrado")
        if self.piloto_tem_historico(piloto_id):
            with self.conn:
                self.conn.execute("UPDATE pilotos SET ativo = 0 WHERE id = ?", (piloto_id,))
            return {"modo": "inativado",
                    "msg": "piloto tem histórico de voltas — foi inativado em vez de apagado"}
        with self.conn:
            self.conn.execute("DELETE FROM transponders WHERE piloto_id = ?", (piloto_id,))
            self.conn.execute("DELETE FROM pilotos WHERE id = ?", (piloto_id,))
        return {"modo": "excluido", "msg": "piloto excluído"}

    def buscar_piloto(self, piloto_id: int) -> Optional[Piloto]:
        row = self.conn.execute("SELECT * FROM pilotos WHERE id = ?", (piloto_id,)).fetchone()
        if not row:
            return None
        return Piloto(id=row["id"], nome=row["nome"], apelido=row["apelido"],
                      fonia=row["fonia"] or "", ativo=bool(row["ativo"]),
                      telefone=row["telefone"] or "", funcoes=row["funcoes"] or "")

    # ----- transponders -----
    def vincular_transponder(self, codigo: int, piloto_id: int):
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO transponders (codigo, piloto_id) VALUES (?, ?)",
                (codigo, piloto_id))

    def listar_transponders(self):
        """Todos os vínculos transponder → piloto (para montar o motor da sessão)."""
        return self.conn.execute(
            "SELECT codigo, piloto_id FROM transponders ORDER BY codigo").fetchall()

    def piloto_do_transponder(self, codigo: int) -> Optional[Piloto]:
        row = self.conn.execute(
            "SELECT p.* FROM transponders t JOIN pilotos p ON p.id = t.piloto_id"
            " WHERE t.codigo = ?", (codigo,)).fetchone()
        if not row:
            return None
        return Piloto(id=row["id"], nome=row["nome"], apelido=row["apelido"],
                      fonia=row["fonia"] or "", ativo=bool(row["ativo"]))

    # ----- recordes (locução) -----
    def melhor_volta_pista_us(self) -> Optional[int]:
        """Melhor volta absoluta já registrada (todas as sessões)."""
        row = self.conn.execute("SELECT MIN(tempo_us) AS m FROM voltas").fetchone()
        return row["m"] if row and row["m"] is not None else None

    def melhores_por_piloto(self) -> Dict[int, int]:
        """Melhor volta de cada piloto (todas as sessões) — base do recorde pessoal."""
        rows = self.conn.execute(
            "SELECT piloto_id, MIN(tempo_us) AS m FROM voltas GROUP BY piloto_id").fetchall()
        return {r["piloto_id"]: r["m"] for r in rows}

    # ----- sessões -----
    def abrir_sessao(self, pista_id: Optional[int], tipo: TipoSessao,
                     parametros: Optional[dict] = None) -> str:
        import json
        sessao_id = str(uuid.uuid4())
        with self.conn:
            self.conn.execute(
                "INSERT INTO sessoes (id, pista_id, tipo, estado, inicio, parametros)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (sessao_id, pista_id, tipo.value, EstadoSessao.PARADO.value,
                 agora_iso(), json.dumps(parametros or {})))
        return sessao_id

    def atualizar_estado_sessao(self, sessao_id: str, estado: EstadoSessao):
        with self.conn:
            self.conn.execute("UPDATE sessoes SET estado = ? WHERE id = ?",
                              (estado.value, sessao_id))

    def fechar_sessao(self, sessao_id: str, estado: EstadoSessao = EstadoSessao.FINALIZADO):
        with self.conn:
            self.conn.execute("UPDATE sessoes SET estado = ?, fim = ? WHERE id = ?",
                              (estado.value, agora_iso(), sessao_id))

    # ----- passings / voltas -----
    def registrar_passing(self, sessao_id: str, transponder: int, rtc_time: int,
                          passing_number: Optional[int], strength: Optional[int],
                          hits: Optional[int], valido: int = 1) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO passings (sessao_id, transponder, rtc_time, passing_number,"
                " strength, hits, recebido_em, valido) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (sessao_id, transponder, rtc_time, passing_number, strength, hits,
                 agora_iso(), valido))
        return cur.lastrowid

    def contar_passings_invalidos(self, sessao_id: str) -> int:
        """Passings gravados mas rejeitados pelo filtro de ghost lap (auditoria)."""
        row = self.conn.execute(
            "SELECT COUNT(*) FROM passings WHERE sessao_id = ? AND valido = 0",
            (sessao_id,)).fetchone()
        return row[0]

    def registrar_volta(self, volta: Volta) -> bool:
        """Insere a volta; False se já existia (idempotente)."""
        with self.conn:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO voltas (sessao_id, piloto_id, numero, tempo_us,"
                " melhor) VALUES (?, ?, ?, ?, ?)",
                (volta.sessao_id, volta.piloto_id, volta.numero, volta.tempo_us,
                 int(volta.melhor)))
        return cur.rowcount > 0

    def voltas_da_sessao(self, sessao_id: str) -> List[Volta]:
        rows = self.conn.execute(
            "SELECT * FROM voltas WHERE sessao_id = ? ORDER BY piloto_id, numero",
            (sessao_id,)).fetchall()
        return [Volta(sessao_id=r["sessao_id"], piloto_id=r["piloto_id"],
                      numero=r["numero"], tempo_us=r["tempo_us"],
                      melhor=bool(r["melhor"])) for r in rows]

    # ----- fila de sincronização (Fase 3) -----
    def enfileirar_sync(self, bat_key: str, payload) -> bool:
        """Enfileira um payload p/ o CTAD. False se o bat_key já está na fila."""
        with self.conn:
            try:
                self.conn.execute(
                    "INSERT INTO fila_sync (bat_key, payload, criado_em) VALUES (?, ?, ?)",
                    (bat_key, json.dumps(payload, ensure_ascii=False), agora_iso()))
                return True
            except sqlite3.IntegrityError:
                return False

    def fila_pendentes(self, limite: int = 20):
        return self.conn.execute(
            "SELECT * FROM fila_sync WHERE estado = 'pendente' ORDER BY id LIMIT ?",
            (limite,)).fetchall()

    def marcar_sync(self, item_id: int, estado: str, erro: Optional[str] = None):
        with self.conn:
            self.conn.execute(
                "UPDATE fila_sync SET estado = ?, erro = ?, tentativas = tentativas + 1,"
                " enviado_em = ? WHERE id = ?",
                (estado, erro,
                 agora_iso() if estado in ("enviado", "duplicado") else None,
                 item_id))

    def stats_sync(self) -> Dict[str, int]:
        rows = self.conn.execute(
            "SELECT estado, COUNT(*) AS n FROM fila_sync GROUP BY estado").fetchall()
        stats = {"pendentes": 0, "enviados": 0, "duplicados": 0, "falhas": 0}
        for r in rows:
            if r["estado"] == "pendente":
                stats["pendentes"] = r["n"]
            elif r["estado"] == "enviado":
                stats["enviados"] = r["n"]
            elif r["estado"] == "duplicado":
                stats["duplicados"] = r["n"]
            elif r["estado"] == "erro":
                stats["falhas"] = r["n"]
        return stats

    # ----- campeonatos (Fase 5) -----
    def criar_campeonato(self, nome: str, numero_provas: int = 4,
                         pilotos_por_prova: int = 10, tabela=None,
                         drop_rounds: int = 0, bonus_pole: int = 0,
                         bonus_melhor_volta: int = 0,
                         pilotos_por_chave: int = 10,
                         inverter_bateria: int = 0) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO campeonatos (nome, numero_provas, pilotos_por_prova,"
                " pontuacao_tabela, drop_rounds, bonus_pole, bonus_melhor_volta,"
                " pilotos_por_chave, inverter_bateria, criado_em)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (nome, numero_provas, pilotos_por_prova,
                 json.dumps(tabela or [25, 18, 15, 12, 10, 8, 6, 4, 2, 1]),
                 drop_rounds, bonus_pole, bonus_melhor_volta,
                 pilotos_por_chave, 1 if inverter_bateria else 0, agora_iso()))
        return cur.lastrowid

    def definir_chaves(self, campeonato_id: int, max_por_chave=None,
                       inverter_bateria=None) -> bool:
        """Ajusta o teto de pilotos por chave e a inversão da bateria seguinte."""
        campos, valores = [], []
        if max_por_chave is not None:
            campos.append("pilotos_por_chave = ?")
            valores.append(max(1, int(max_por_chave)))
        if inverter_bateria is not None:
            campos.append("inverter_bateria = ?")
            valores.append(1 if inverter_bateria else 0)
        if not campos:
            return False
        valores.append(campeonato_id)
        with self.conn:
            self.conn.execute(
                f"UPDATE campeonatos SET {', '.join(campos)} WHERE id = ?", valores)
        return True

    def atualizar_campeonato(self, campeonato_id: int, numero_provas=None,
                             pilotos_por_prova=None, pilotos_por_chave=None,
                             inverter_bateria=None, pontuacao_tabela=None) -> bool:
        """Atualiza a configuração de um campeonato (sincronização com o CTAD)."""
        campos, valores = [], []
        for col, val in (("numero_provas", numero_provas),
                         ("pilotos_por_prova", pilotos_por_prova),
                         ("pilotos_por_chave", pilotos_por_chave),
                         ("inverter_bateria", inverter_bateria)):
            if val is None:
                continue
            campos.append(f"{col} = ?")
            valores.append(int(val))
        if pontuacao_tabela is not None:
            campos.append("pontuacao_tabela = ?")
            valores.append(json.dumps(list(pontuacao_tabela)))
        if not campos:
            return False
        valores.append(campeonato_id)
        with self.conn:
            self.conn.execute(
                f"UPDATE campeonatos SET {', '.join(campos)} WHERE id = ?", valores)
        return True

    def listar_campeonatos(self):
        return self.conn.execute(
            "SELECT * FROM campeonatos ORDER BY id DESC").fetchall()

    def campeonato(self, campeonato_id: int):
        return self.conn.execute(
            "SELECT * FROM campeonatos WHERE id = ?", (campeonato_id,)).fetchone()

    def inscrever(self, campeonato_id: int, piloto_id: int,
                  transponder=None, frequencia=None) -> bool:
        with self.conn:
            try:
                self.conn.execute(
                    "INSERT INTO inscricoes (campeonato_id, piloto_id, transponder,"
                    " frequencia) VALUES (?, ?, ?, ?)",
                    (campeonato_id, piloto_id, transponder, frequencia))
                return True
            except sqlite3.IntegrityError:
                return False

    def listar_inscricoes(self, campeonato_id: int):
        return self.conn.execute(
            "SELECT i.*, p.nome FROM inscricoes i JOIN pilotos p ON p.id = i.piloto_id"
            " WHERE i.campeonato_id = ? ORDER BY i.pontos_ranking DESC, p.nome",
            (campeonato_id,)).fetchall()

    def buscar_baterias(self, termo: str, limite: int = 8):
        """Baterias cujo nome/fase casa com o termo (para a busca global)."""
        t = f"%{(termo or '').lower()}%"
        return self.conn.execute(
            "SELECT b.id AS bateria_id, b.nome AS bateria, b.fase, e.numero AS etapa,"
            " c.id AS campeonato_id, c.nome AS campeonato"
            " FROM baterias b JOIN etapas e ON e.id = b.etapa_id"
            " JOIN campeonatos c ON c.id = e.campeonato_id"
            " WHERE lower(b.nome) LIKE ? OR lower(b.fase) LIKE ?"
            " ORDER BY c.id DESC, e.numero, b.id LIMIT ?",
            (t, t, limite)).fetchall()

    def criar_etapa(self, campeonato_id: int, numero: int) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO etapas (campeonato_id, numero) VALUES (?, ?)",
                (campeonato_id, numero))
        return cur.lastrowid

    def listar_etapas(self, campeonato_id: int):
        return self.conn.execute(
            "SELECT * FROM etapas WHERE campeonato_id = ? ORDER BY numero",
            (campeonato_id,)).fetchall()

    def criar_bateria(self, etapa_id: int, nome: str, fase: str = "heat") -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO baterias (etapa_id, nome, fase) VALUES (?, ?, ?)",
                (etapa_id, nome, fase))
        return cur.lastrowid

    def listar_baterias(self, campeonato_id: int):
        return self.conn.execute(
            "SELECT b.* FROM baterias b JOIN etapas e ON e.id = b.etapa_id"
            " WHERE e.campeonato_id = ? ORDER BY e.numero, b.id",
            (campeonato_id,)).fetchall()

    def registrar_resultado(self, bateria_id: int, piloto_id: int, posicao: int,
                            pontos: int, melhor_volta_us=None, pole: int = 0):
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO resultados (bateria_id, piloto_id, posicao,"
                " pontos, melhor_volta_us, pole) VALUES (?, ?, ?, ?, ?, ?)",
                (bateria_id, piloto_id, posicao, pontos, melhor_volta_us, pole))

    def resultados_bateria(self, bateria_id: int):
        return self.conn.execute(
            "SELECT r.*, p.nome FROM resultados r JOIN pilotos p ON p.id = r.piloto_id"
            " WHERE r.bateria_id = ? ORDER BY r.posicao", (bateria_id,)).fetchall()

    def resultados_campeonato(self, campeonato_id: int) -> Dict:
        """{nome_piloto: {'E1': pontos, ...}} consumido pelo motor de ranking."""
        rows = self.conn.execute(
            "SELECT p.nome AS nome, e.numero AS etapa, r.pontos AS pontos"
            " FROM resultados r JOIN baterias b ON b.id = r.bateria_id"
            " JOIN etapas e ON e.id = b.etapa_id"
            " JOIN pilotos p ON p.id = r.piloto_id"
            " WHERE e.campeonato_id = ? ORDER BY e.numero, r.posicao",
            (campeonato_id,)).fetchall()
        saida: Dict[str, Dict[str, int]] = {}
        for r in rows:
            saida.setdefault(r["nome"], {})[f"E{r['etapa']}"] = r["pontos"]
        return saida

    def classificacao_etapa(self, etapa_id: int):
        """Melhor posição de cada piloto na etapa (agrega as baterias)."""
        return self.conn.execute(
            "SELECT r.piloto_id AS piloto_id, p.nome AS nome,"
            " MIN(r.posicao) AS posicao, MIN(r.melhor_volta_us) AS melhor_volta_us"
            " FROM resultados r JOIN baterias b ON b.id = r.bateria_id"
            " JOIN pilotos p ON p.id = r.piloto_id"
            " WHERE b.etapa_id = ? GROUP BY r.piloto_id ORDER BY posicao",
            (etapa_id,)).fetchall()

    def ultima_sessao(self, tipo=None, estado: str = "finalizado"):
        """Sessão mais recente (opcionalmente filtrando por tipo/estado)."""
        if tipo:
            return self.conn.execute(
                "SELECT * FROM sessoes WHERE estado = ? AND tipo = ?"
                " ORDER BY inicio DESC LIMIT 1", (estado, tipo)).fetchone()
        return self.conn.execute(
            "SELECT * FROM sessoes WHERE estado = ? ORDER BY inicio DESC LIMIT 1",
            (estado,)).fetchone()

    def voltas_por_piloto(self, sessao_id: str) -> Dict[int, list]:
        """{piloto_id: [tempo_s, ...]} na ordem das voltas — base para o grid do treino."""
        rows = self.conn.execute(
            "SELECT piloto_id, tempo_us FROM voltas"
            " WHERE sessao_id = ? ORDER BY piloto_id, numero", (sessao_id,)).fetchall()
        saida: Dict[int, list] = {}
        for r in rows:
            saida.setdefault(r["piloto_id"], []).append(r["tempo_us"] / 1_000_000)
        return saida

    def listar_pilotos(self):
        return self.conn.execute(
            "SELECT * FROM pilotos ORDER BY nome").fetchall()

    # ----- histórico de voltas (todas as sessões) -----
    def listar_sessoes(self):
        return self.conn.execute(
            "SELECT s.*,"
            " (SELECT COUNT(*) FROM voltas v WHERE v.sessao_id = s.id) AS n_voltas,"
            " (SELECT COUNT(DISTINCT v.piloto_id) FROM voltas v WHERE v.sessao_id = s.id)"
            "   AS n_pilotos,"
            " (SELECT MIN(v.tempo_us) FROM voltas v WHERE v.sessao_id = s.id) AS melhor_us"
            " FROM sessoes s ORDER BY s.inicio DESC").fetchall()

    def voltas_da_sessao_detalhe(self, sessao_id: str):
        return self.conn.execute(
            "SELECT v.numero, v.tempo_us, v.melhor, p.nome AS piloto"
            " FROM voltas v JOIN pilotos p ON p.id = v.piloto_id"
            " WHERE v.sessao_id = ? ORDER BY p.nome, v.numero",
            (sessao_id,)).fetchall()

    # ----- relatórios -----
    def relatorio_contagens(self) -> Dict:
        def _n(sql):
            return self.conn.execute(sql).fetchone()[0]
        return {
            "sessoes": _n("SELECT COUNT(*) FROM sessoes"),
            "sessoes_finalizadas": _n("SELECT COUNT(*) FROM sessoes WHERE estado = 'finalizado'"),
            "pilotos": _n("SELECT COUNT(*) FROM pilotos"),
            "pilotos_ativos": _n("SELECT COUNT(*) FROM pilotos WHERE ativo = 1"),
            "transponders": _n("SELECT COUNT(*) FROM transponders"),
            "voltas": _n("SELECT COUNT(*) FROM voltas"),
            "passings": _n("SELECT COUNT(*) FROM passings"),
            "campeonatos": _n("SELECT COUNT(*) FROM campeonatos"),
        }

    def relatorio_pilotos(self):
        """Agregado por piloto: voltas, sessões, melhor volta e última atividade."""
        return self.conn.execute(
            "SELECT p.id, p.nome, p.apelido, p.telefone, p.funcoes, p.ativo,"
            " COUNT(v.id) AS voltas,"
            " COUNT(DISTINCT v.sessao_id) AS sessoes,"
            " MIN(v.tempo_us) AS melhor_us,"
            " MAX(s.inicio) AS ultima_sessao"
            " FROM pilotos p"
            " LEFT JOIN voltas v ON v.piloto_id = p.id"
            " LEFT JOIN sessoes s ON s.id = v.sessao_id"
            " GROUP BY p.id ORDER BY voltas DESC, p.nome COLLATE NOCASE").fetchall()

    def fechar(self):
        self.conn.close()

"""KChrono — modelos de domínio (Fase 1)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional


class TipoSessao(str, Enum):
    TREINO = "treino"
    CLASSIFICACAO = "classificacao"
    CORRIDA = "corrida"
    CAMPEONATO = "campeonato"   # corrida em etapas: treino → intervalo → classificação → intervalo → corrida


class EstadoSessao(str, Enum):
    PARADO = "parado"
    TREINO = "treino"                # treino em andamento
    CLASSIFICACAO = "classificacao"  # classificação em andamento
    LARGADA = "largada"              # corrida iniciada, aguardando largada
    CORRENDO = "correndo"
    FINALIZADO = "finalizado"


@dataclass
class Pista:
    id: Optional[int]
    nome: str
    comprimento_m: Optional[float] = None  # comprimento real (estatísticas)
    ativa: bool = False                    # pista das sessões em andamento


@dataclass
class Piloto:
    id: Optional[int]
    nome: str
    apelido: str = ""
    fonia: str = ""       # como o nome deve ser pronunciado no TTS
    ativo: bool = True
    telefone: str = ""    # chave natural do piloto (login/identidade)
    funcoes: str = ""     # funções extra opcionais: admin, gestor (CSV)


@dataclass
class Transponder:
    codigo: int                    # código do transponder (ex.: 7096340)
    piloto_id: int


@dataclass
class Sessao:
    id: str                        # uuid local
    pista_id: Optional[int]
    tipo: TipoSessao
    estado: EstadoSessao = EstadoSessao.PARADO
    inicio: Optional[str] = None
    fim: Optional[str] = None
    parametros: Dict = field(default_factory=dict)  # voltas, duração, categoria...


@dataclass
class Volta:
    """Volta completada por um piloto em uma sessão."""
    sessao_id: str
    piloto_id: int
    numero: int                    # 1, 2, 3...
    tempo_us: int                  # duração em microssegundos
    melhor: bool = False

    @property
    def tempo_s(self) -> Decimal:
        return Decimal(self.tempo_us) / Decimal(1_000_000)


@dataclass
class LinhaClassificação:
    posicao: int
    piloto_id: int
    nome: str
    voltas: int
    tempo_total_us: int
    melhor_volta_us: Optional[int]
    ultima_volta_us: Optional[int]
    gap: str = ""
    numero: str = ""
    abreviado: str = ""
    intervalo_us: Optional[int] = None      # diferença para o seguinte
    media_us: Optional[float] = None        # tempo médio das voltas
    desvio_us: Optional[float] = None       # desvio padrão
    consistencia_pct: Optional[float] = None
    transponder: Optional[int] = None
    suspeita: bool = False                  # volta marcada como "gato"


def formatar_tempo(tempo_us: Optional[int]) -> str:
    """Formata microssegundos como m:ss.mmm (ou '-')."""
    if tempo_us is None:
        return "-"
    total_s = Decimal(tempo_us) / Decimal(1_000_000)
    minutos = int(total_s // 60)
    segundos = total_s - minutos * 60
    return f"{minutos}:{segundos:06.3f}"


def agora_iso() -> str:
    return datetime.now().isoformat(timespec="milliseconds")

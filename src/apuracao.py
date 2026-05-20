"""Lógica de apuração de banco de horas — Provida Centro Médico.

Reimplementa em Python as fórmulas Excel de BatidasOCR + ApuracaoAutomatica:

  Por dia (replica fórmulas das colunas J, K, L de BatidasOCR):
    HRS_TRABALHADAS = (saída_almoço - entrada_manhã) + (saída_tarde - volta_almoço)
    JORNADA_ESPERADA = lookup Cadastro, zerado em Domingo/Feriado/Folga/etc
    DIFERENÇA_DIA    = HRS_TRABALHADAS - JORNADA_ESPERADA

  Por mês (replica ApuracaoAutomatica):
    HORAS_EXTRAS    = soma de DIFERENÇA_DIA > 0
    FALTAS_ATRASOS  = soma de abs(DIFERENÇA_DIA < 0) + dias úteis sem batida
    SALDO_MÊS       = HORAS_EXTRAS - FALTAS_ATRASOS

Regras de negócio confirmadas:
  - Sem tolerância de atraso
  - Sábado: jornada zerada se colaborador não trabalha sábado (ver Cadastro)
  - Dia útil sem nenhuma batida = falta da jornada completa
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Tipos de dia que resultam em JORNADA_ESPERADA = 0
_TIPOS_SEM_JORNADA = {
    "DOMINGO", "FERIADO", "FOLGA", "ATESTADO",
    "FERIAS", "FÉRIAS", "AUSENCIA", "AUSÊNCIA",
}


# ── Modelos de dados ─────────────────────────────────────────────────────────

@dataclass
class ColaboradorCadastro:
    nome: str
    setor: str
    jornada_horas: float        # horas/dia em dias úteis
    trabalha_sab: bool
    jornada_sab_horas: float    # horas no sábado (0 se não trabalha)


@dataclass
class ResultadoDia:
    data: date
    dia_semana: str
    tipo_dia: str               # NORMAL | SÁBADO | DOMINGO | FOLGA | FERIADO | ...
    hrs_trabalhadas: Optional[timedelta]
    jornada_esperada: timedelta
    diferenca: Optional[timedelta]   # positivo = extra, negativo = falta/atraso


@dataclass
class ResultadoMes:
    colaborador: str
    competencia: str            # formato "MM/AAAA"
    horas_extras: timedelta
    faltas_atrasos: timedelta
    saldo_mes: timedelta
    dias_com_batida: int
    dias_sem_batida: int        # dias úteis sem nenhuma batida
    total_dias_uteis: int
    confianca_media: float
    carga_horas_dia: float      # jornada do colaborador (do Cadastro)
    trabalha_sab: bool
    detalhes: list[ResultadoDia] = field(default_factory=list)


# ── Helpers de tempo ─────────────────────────────────────────────────────────

def td(t: Optional[time]) -> Optional[timedelta]:
    """datetime.time → timedelta. None se t for None."""
    if t is None:
        return None
    return timedelta(hours=t.hour, minutes=t.minute)


def td_to_hhmm(delta: timedelta) -> str:
    """timedelta → 'HH:MM' com sinal para negativos. Ex: '-01:30'."""
    total_sec = int(delta.total_seconds())
    sinal = "-" if total_sec < 0 else ""
    total_sec = abs(total_sec)
    h, resto = divmod(total_sec, 3600)
    m = resto // 60
    return f"{sinal}{h:02d}:{m:02d}"


def hhmm_to_td(s: str) -> timedelta:
    """'HH:MM' ou '-HH:MM' → timedelta. Retorna zero se inválido."""
    if not s or not isinstance(s, str):
        return timedelta(0)
    s = s.strip()
    negativo = s.startswith("-")
    s = s.lstrip("-").strip()
    m = re.fullmatch(r"(\d+):([0-5]\d)", s)
    if not m:
        return timedelta(0)
    delta = timedelta(hours=int(m.group(1)), minutes=int(m.group(2)))
    return -delta if negativo else delta


def competencia_para_aaaaMM(comp: str) -> str:
    """'04/2026' → '2026-04' (formato usado na Apuracao_Consolidada)."""
    m = re.fullmatch(r"(\d{1,2})/(\d{4})", comp.strip())
    if not m:
        return comp
    return f"{m.group(2)}-{m.group(1).zfill(2)}"


def aaaaMM_para_competencia(s: str) -> str:
    """'2026-04' → '04/2026' (formato interno do sistema)."""
    m = re.fullmatch(r"(\d{4})-(\d{2})", s.strip())
    if not m:
        return s
    return f"{m.group(2)}/{m.group(1)}"


# ── Cadastro ─────────────────────────────────────────────────────────────────

def ler_cadastro(planilha_path: Path) -> dict[str, ColaboradorCadastro]:
    """Lê a aba Cadastro e retorna dict {nome → ColaboradorCadastro}."""
    import openpyxl
    wb = openpyxl.load_workbook(str(planilha_path), read_only=True, keep_vba=True, data_only=True)
    ws = wb["Cadastro"]

    colaboradores: dict[str, ColaboradorCadastro] = {}
    for row in ws.iter_rows(min_row=3, values_only=True):
        nome = row[1]
        if not nome or not str(nome).strip():
            continue
        nome = str(nome).strip()
        setor = str(row[2] or "").strip()
        jornada = float(row[5] or 8)
        trab_sab_raw = str(row[6] or "Não").strip().lower()
        trab_sab = trab_sab_raw in ("sim", "s", "yes")
        jornada_sab = float(row[7] or 0)

        colaboradores[nome] = ColaboradorCadastro(
            nome=nome,
            setor=setor,
            jornada_horas=jornada,
            trabalha_sab=trab_sab,
            jornada_sab_horas=jornada_sab,
        )

    wb.close()
    logger.info(f"Cadastro: {len(colaboradores)} colaborador(es) carregado(s)")
    return colaboradores


def nomes_cadastro(planilha_path: Path) -> list[str]:
    """Retorna lista de nomes válidos do Cadastro (para validação e dropdown)."""
    return sorted(ler_cadastro(planilha_path).keys())


# ── Cálculos por dia ─────────────────────────────────────────────────────────

def calcular_hrs_trabalhadas(
    entrada_manha: Optional[time],
    saida_almoco: Optional[time],
    volta_almoco: Optional[time],
    saida_tarde: Optional[time],
) -> Optional[timedelta]:
    """Replica: =IF(OR(ISBLANK...), "", (G-F)+(I-H)).

    Retorna None se qualquer horário estiver ausente.
    Retorna None se o resultado for negativo (erro de leitura OCR).
    """
    if any(h is None for h in [entrada_manha, saida_almoco, volta_almoco, saida_tarde]):
        return None
    manha = td(saida_almoco) - td(entrada_manha)
    tarde = td(saida_tarde) - td(volta_almoco)
    total = manha + tarde
    if total < timedelta(0):
        logger.debug(f"HRS_TRABALHADAS negativa: {total} — descartada")
        return None
    return total


def _tipo_dia_efetivo(dia_semana: str, observacoes: str) -> str:
    """Determina o tipo de dia a partir do dia da semana e observações da batida."""
    dia_up = (dia_semana or "").strip().upper()

    # Extrai tipo da observação (formato gerado pelo pipeline: "tipo=FOLGA")
    obs_up = (observacoes or "").strip().upper()
    m = re.search(r"TIPO=(\w+)", obs_up)
    if m:
        tipo = m.group(1)
        if tipo in _TIPOS_SEM_JORNADA or tipo in ("SABADO", "SÁBADO", "DOMINGO"):
            return tipo

    if "DOMINGO" in dia_up:
        return "DOMINGO"
    if "SÁBADO" in dia_up or "SABADO" in dia_up:
        return "SÁBADO"

    return "NORMAL"


def calcular_jornada_esperada(
    dia_semana: str,
    observacoes: str,
    emp: Optional[ColaboradorCadastro],
) -> timedelta:
    """Replica: JORNADA_ESPERADA com lookup no Cadastro.

    Regras:
    - Domingo / Feriado / Folga / Atestado / Férias / Ausência → 0
    - Sábado: usa jornada_sab do Cadastro se trabalha sábado, senão 0
    - Dia útil: usa jornada_horas do Cadastro (default 8h)
    """
    tipo = _tipo_dia_efetivo(dia_semana, observacoes)

    if tipo == "DOMINGO" or tipo in _TIPOS_SEM_JORNADA:
        return timedelta(0)

    if tipo in ("SÁBADO", "SABADO"):
        if emp and emp.trabalha_sab:
            return timedelta(hours=emp.jornada_sab_horas)
        return timedelta(0)

    # Dia útil normal
    horas = emp.jornada_horas if emp else 8.0
    return timedelta(hours=horas)


# ── Apuração mensal ──────────────────────────────────────────────────────────

def apurar_mes(
    batidas: list,                        # list[BatidaDiaria] do pipeline
    planilha_path: Path,
    colaborador: str,
    competencia: str,                     # "MM/AAAA"
    confianca_media: float = 0.0,
) -> ResultadoMes:
    """Calcula apuração mensal completa para um colaborador.

    Replica o que ApuracaoAutomatica faz via SUMPRODUCT, mas em Python puro —
    sem depender do Excel estar aberto ou das fórmulas recalculadas.
    """
    cadastro = ler_cadastro(planilha_path)
    emp = cadastro.get(colaborador)

    if emp is None:
        logger.warning(f"Colaborador '{colaborador}' não encontrado no Cadastro")

    extras = timedelta(0)
    faltas = timedelta(0)
    dias_com = 0
    dias_sem = 0
    dias_uteis = 0
    detalhes: list[ResultadoDia] = []

    for b in batidas:
        jornada = calcular_jornada_esperada(
            b.dia_semana, getattr(b, "observacoes", ""), emp
        )
        hrs = calcular_hrs_trabalhadas(
            b.entrada_manha, b.saida_almoco, b.volta_almoco, b.saida_tarde
        )

        eh_dia_util = jornada > timedelta(0)
        if eh_dia_util:
            dias_uteis += 1

        diferenca: Optional[timedelta] = None

        if hrs is not None:
            diferenca = hrs - jornada
            if diferenca > timedelta(0):
                extras += diferenca
            elif diferenca < timedelta(0):
                faltas += abs(diferenca)
            dias_com += 1
        elif eh_dia_util:
            # Dia útil sem nenhuma batida = falta da jornada completa
            faltas += jornada
            dias_sem += 1

        tipo = _tipo_dia_efetivo(b.dia_semana, getattr(b, "observacoes", ""))
        detalhes.append(ResultadoDia(
            data=b.data,
            dia_semana=b.dia_semana or "",
            tipo_dia=tipo,
            hrs_trabalhadas=hrs,
            jornada_esperada=jornada,
            diferenca=diferenca,
        ))

    saldo_mes = extras - faltas

    return ResultadoMes(
        colaborador=colaborador,
        competencia=competencia,
        horas_extras=extras,
        faltas_atrasos=faltas,
        saldo_mes=saldo_mes,
        dias_com_batida=dias_com,
        dias_sem_batida=dias_sem,
        total_dias_uteis=dias_uteis,
        confianca_media=confianca_media,
        carga_horas_dia=emp.jornada_horas if emp else 8.0,
        trabalha_sab=emp.trabalha_sab if emp else False,
        detalhes=detalhes,
    )

"""Extração de campos estruturados a partir do texto bruto do OCR.

OCR retorna texto livre. Este módulo tenta identificar:
- Nome do colaborador
- Competência (MM/AAAA)
- Datas do mês (DD/MM)
- Horários de cada batida (HH:MM)

Não assume OCR perfeito: retorna valores com flag de confiança individual.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, time
from typing import Optional

logger = logging.getLogger(__name__)

# --- Padrões regex ---
_TIME_RE = re.compile(r"\b([0-1]?\d|2[0-3])[:hH]([0-5]\d)\b")
_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})\b")
_COMPETENCIA_RE = re.compile(r"\b(\d{1,2})[/\-](\d{4})\b")

# Dias da semana em português (para identificar linhas de data)
_DIAS_SEMANA = {
    "seg": "Segunda", "ter": "Terça", "qua": "Quarta",
    "qui": "Quinta", "sex": "Sexta", "sáb": "Sábado",
    "sab": "Sábado", "dom": "Domingo",
}


@dataclass
class CampoExtraido:
    """Um valor extraído com sua confiança individual."""
    valor: Optional[str]
    confianca: float          # 0–100
    raw: str                  # texto original que gerou o valor


def extrair_horario(texto: str) -> CampoExtraido:
    """Extrai primeiro HH:MM encontrado no texto.

    Confiança alta (90) se padrão perfeito, baixa (40) se estimativa.
    """
    m = _TIME_RE.search(texto)
    if not m:
        return CampoExtraido(valor=None, confianca=0.0, raw=texto)
    hora, minuto = int(m.group(1)), int(m.group(2))
    try:
        t = time(hora, minuto)
        return CampoExtraido(valor=t.strftime("%H:%M"), confianca=85.0, raw=m.group(0))
    except ValueError:
        return CampoExtraido(valor=None, confianca=0.0, raw=m.group(0))


def extrair_data(texto: str, ano: int) -> CampoExtraido:
    """Extrai DD/MM e resolve o ano pelo contexto (mês da competência)."""
    m = _DATE_RE.search(texto)
    if not m:
        return CampoExtraido(valor=None, confianca=0.0, raw=texto)
    dia, mes = int(m.group(1)), int(m.group(2))
    try:
        d = date(ano, mes, dia)
        return CampoExtraido(valor=d.isoformat(), confianca=80.0, raw=m.group(0))
    except ValueError:
        return CampoExtraido(valor=None, confianca=0.0, raw=m.group(0))


def extrair_competencia(texto: str) -> CampoExtraido:
    """Extrai competência MM/AAAA do cabeçalho da folha."""
    m = _COMPETENCIA_RE.search(texto)
    if not m:
        return CampoExtraido(valor=None, confianca=0.0, raw=texto)
    mes = m.group(1).zfill(2)
    ano = m.group(2)
    valor = f"{mes}/{ano}"
    return CampoExtraido(valor=valor, confianca=75.0, raw=m.group(0))


def identificar_dia_semana(texto: str) -> Optional[str]:
    """Retorna nome do dia da semana se encontrado no texto."""
    texto_lower = texto.lower()
    for prefixo, nome in _DIAS_SEMANA.items():
        if prefixo in texto_lower:
            return nome
    return None


def extrair_linha_batidas(linha: str) -> dict[str, CampoExtraido]:
    """Extrai todos os horários de uma linha de texto (uma linha da folha).

    Assume que a ordem dos horários na linha é:
    entrada_manhã | saída_almoço | volta_almoço | saída_tarde

    Retorna dict com até 4 campos + dia_semana (string).
    """
    matches = list(_TIME_RE.finditer(linha))
    campos_ordem = ["entrada_manha", "saida_almoco", "volta_almoco", "saida_tarde"]
    resultado: dict[str, CampoExtraido] = {}

    for i, campo in enumerate(campos_ordem):
        if i < len(matches):
            m = matches[i]
            try:
                t = time(int(m.group(1)), int(m.group(2)))
                resultado[campo] = CampoExtraido(
                    valor=t.strftime("%H:%M"),
                    confianca=85.0,
                    raw=m.group(0),
                )
            except ValueError:
                resultado[campo] = CampoExtraido(valor=None, confianca=0.0, raw=m.group(0))
        else:
            resultado[campo] = CampoExtraido(valor=None, confianca=0.0, raw="")

    resultado["dia_semana"] = CampoExtraido(
        valor=identificar_dia_semana(linha),
        confianca=60.0 if identificar_dia_semana(linha) else 0.0,
        raw=linha,
    )

    return resultado

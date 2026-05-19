"""Normalização: strings brutas do OCR → objetos Python tipados.

O OCR retorna texto livre com erros comuns: "8h30", "08 30", "O8:OO" (letra O no lugar do zero).
Este módulo tenta ser tolerante a essas variações.
"""
from __future__ import annotations

import logging
import re
from datetime import time
from typing import Optional

logger = logging.getLogger(__name__)

# Aceita: "08:00", "8h30", "8 30", "8:3O" (OCR confunde 0 com O)
_TIME_RE = re.compile(r"([0-2]?[0-9O])[:\sh]([0-5][0-9O])")

_DIAS_SEMANA_MAP = {
    "segunda": "Segunda", "terca": "Terça", "terça": "Terça",
    "quarta": "Quarta", "quinta": "Quinta", "sexta": "Sexta",
    "sabado": "Sábado", "sábado": "Sábado",
    "domingo": "Domingo",
    "seg": "Segunda", "ter": "Terça", "qua": "Quarta",
    "qui": "Quinta", "sex": "Sexta", "sab": "Sábado", "dom": "Domingo",
}


def _corrigir_ocr_numeros(s: str) -> str:
    """Substitui letras O por 0 — erro frequente do Tesseract em horários."""
    return s.replace("O", "0").replace("o", "0").replace("l", "1").replace("I", "1")


def parse_time(raw: str) -> Optional[time]:
    """Converte string de horário em datetime.time.

    Tolerante a: "08:00", "8h30", "8 30", "8:3O" (O → 0).
    Retorna None se não conseguir parsear.
    """
    if not raw or not raw.strip():
        return None

    limpo = _corrigir_ocr_numeros(raw.strip())
    m = _TIME_RE.search(limpo)
    if not m:
        logger.debug(f"parse_time: não conseguiu parsear '{raw}'")
        return None

    try:
        hora = int(m.group(1))
        minuto = int(m.group(2))
        if 0 <= hora <= 23 and 0 <= minuto <= 59:
            return time(hora, minuto)
        logger.debug(f"parse_time: valores fora de range h={hora} m={minuto}")
        return None
    except ValueError:
        return None


def time_to_str(t: Optional[time]) -> str:
    """datetime.time → 'HH:MM'. String vazia se None (para células Excel vazias)."""
    return t.strftime("%H:%M") if t else ""


def normalize_colaborador(raw: str) -> str:
    """Remove espaços extras e normaliza maiúsculas para comparar com Cadastro."""
    if not raw:
        return ""
    return " ".join(raw.strip().split()).title()


def normalize_competencia(raw: str) -> Optional[str]:
    """'5/2026', '05-2026', '05/26' → '05/2026'. None se inválido."""
    m = re.search(r"(\d{1,2})[/\-](\d{2,4})", raw)
    if not m:
        return None
    mes = m.group(1).zfill(2)
    ano = m.group(2)
    if len(ano) == 2:
        ano = "20" + ano
    if not (1 <= int(mes) <= 12 and 2000 <= int(ano) <= 2099):
        return None
    return f"{mes}/{ano}"


def normalize_dia_semana(raw: str) -> Optional[str]:
    """'seg', 'segunda-feira', 'SEGUNDA' → 'Segunda'. None se não reconhecido."""
    if not raw:
        return None
    chave = raw.strip().lower().split("-")[0].split(" ")[0]
    return _DIAS_SEMANA_MAP.get(chave)

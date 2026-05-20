"""Normalização: strings brutas do OCR → objetos Python tipados.

O OCR de formulários manuscritos produz erros sistemáticos:
  - Letras como dígitos: O→0, l→1, I→1, Z→2, S→5, (→0, [→0
  - Separadores alternativos: "." "°" "/" em vez de ":"
  - Sem separador: "0800" em vez de "08:00"
  - Horas impossíveis: "32:00" (3→1 mal lido) → tentar corrigir
"""
from __future__ import annotations

import logging
import re
from datetime import time
from typing import Optional

logger = logging.getLogger(__name__)

# Mapa de substituições de caracteres OCR → dígitos
_OCR_CORRECOES = str.maketrans({
    "O": "0", "o": "0",
    "l": "1", "I": "1",
    "Z": "2",
    "S": "5",
    "(": "0", "[": "0",
    "°": ":", ".": ":", "/": ":",
})

# Aceita: "08:00", "8h30", "8.30", "8°30", "0800" (4 dígitos sem separador)
_TIME_SEP_RE  = re.compile(r"(\d{1,2})[:h](\d{2})")
_TIME_HHMM_RE = re.compile(r"\b(\d{2})(\d{2})\b")          # 4 dígitos colados

_DIAS_SEMANA_MAP = {
    "segunda": "Segunda", "terca": "Terça", "terça": "Terça",
    "quarta": "Quarta", "quinta": "Quinta", "sexta": "Sexta",
    "sabado": "Sábado", "sábado": "Sábado",
    "domingo": "Domingo",
    "seg": "Segunda", "ter": "Terça", "qua": "Quarta",
    "qui": "Quinta", "sex": "Sexta", "sab": "Sábado", "dom": "Domingo",
}

# Horas típicas da Provida — usadas para corrigir leituras impossíveis por proximidade
_HORAS_TIPICAS = [7, 8, 11, 12, 13, 17, 18]


def _corrigir_hora_impossivel(hora: int) -> Optional[int]:
    """Tenta corrigir hora > 23 por proximidade com horas típicas.

    Ex: 32 → 12 (3→1 erro OCR), 57 → 17 (5→1), 42 → 12 (4→1 ou 4→0+2=02?)
    Retorna None se não conseguir corrigir com confiança.
    """
    # Troca o primeiro dígito: 32→12, 57→17, 42→12, 81→01
    primeiro = hora // 10
    segundo = hora % 10
    for candidato_primeiro in [0, 1, 2]:
        nova_hora = candidato_primeiro * 10 + segundo
        if 0 <= nova_hora <= 23 and candidato_primeiro != primeiro:
            # Aceita apenas se a hora corrigida estiver nas horas típicas
            if nova_hora in _HORAS_TIPICAS:
                return nova_hora
    return None


def parse_time(raw: str) -> Optional[time]:
    """Converte string de horário em datetime.time com tolerância a erros OCR.

    Estratégias em ordem:
      1. Aplica correções de caracteres OCR
      2. Tenta HH:MM (com separador)
      3. Tenta HHMM (sem separador, 4 dígitos)
      4. Tenta corrigir horas impossíveis (>23) por proximidade com horas típicas
    Retorna None se não conseguir parsear.
    """
    if not raw or not raw.strip():
        return None

    limpo = raw.strip().translate(_OCR_CORRECOES)

    # Estratégia 1: HH:MM com separador
    m = _TIME_SEP_RE.search(limpo)
    if m:
        try:
            h, mn = int(m.group(1)), int(m.group(2))
            if 0 <= h <= 23 and 0 <= mn <= 59:
                return time(h, mn)
            # Hora impossível: tenta corrigir
            h_corr = _corrigir_hora_impossivel(h)
            if h_corr is not None and 0 <= mn <= 59:
                logger.debug(f"Hora corrigida: {h}:{mn:02d} → {h_corr}:{mn:02d}")
                return time(h_corr, mn)
        except ValueError:
            pass

    # Estratégia 2: HHMM sem separador (ex: "1300", "0800")
    m = _TIME_HHMM_RE.search(limpo)
    if m:
        try:
            h, mn = int(m.group(1)), int(m.group(2))
            if 0 <= h <= 23 and 0 <= mn <= 59:
                return time(h, mn)
            h_corr = _corrigir_hora_impossivel(h)
            if h_corr is not None and 0 <= mn <= 59:
                logger.debug(f"HHMM corrigido: {h}{mn:02d} → {h_corr}:{mn:02d}")
                return time(h_corr, mn)
        except ValueError:
            pass

    logger.debug(f"parse_time: não conseguiu parsear '{raw}' (limpo: '{limpo}')")
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

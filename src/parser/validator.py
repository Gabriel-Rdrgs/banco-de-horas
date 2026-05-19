"""Validação de regras de negócio sobre as batidas extraídas.

Não valida OCR — valida se os horários fazem sentido para a Provida.
Erros aqui indicam que a revisão humana é obrigatória, não opcional.
"""
from __future__ import annotations

import logging
from datetime import time
from typing import Optional

from src.models.folha import BatidaDiaria

logger = logging.getLogger(__name__)

# Limites absolutos de horário aceitos
_HORA_MIN = time(5, 0)
_HORA_MAX = time(23, 59)
_ALMOCO_MIN_MINUTOS = 30


def _minutos(t: time) -> int:
    return t.hour * 60 + t.minute


def _delta_minutos(t1: time, t2: time) -> int:
    """Minutos entre t1 e t2 (t2 - t1). Pode ser negativo."""
    return _minutos(t2) - _minutos(t1)


def validate_batida(batida: BatidaDiaria) -> list[str]:
    """Valida uma batida diária contra as regras de negócio da Provida.

    Retorna lista de strings de erro. Lista vazia = válido.
    """
    erros: list[str] = []
    horarios: dict[str, Optional[time]] = {
        "ENTRADA_MANHA": batida.entrada_manha,
        "SAIDA_ALMOCO": batida.saida_almoco,
        "VOLTA_ALMOCO": batida.volta_almoco,
        "SAIDA_TARDE": batida.saida_tarde,
    }

    # Faixa absoluta
    for nome, h in horarios.items():
        if h is not None and not (_HORA_MIN <= h <= _HORA_MAX):
            erros.append(f"{nome} fora do intervalo permitido (05:00–23:59): {h}")

    # Sequência lógica
    em = batida.entrada_manha
    sa = batida.saida_almoco
    va = batida.volta_almoco
    st = batida.saida_tarde

    if em and sa and sa <= em:
        erros.append(f"SAIDA_ALMOCO ({sa}) não pode ser ≤ ENTRADA_MANHA ({em})")

    if sa and va and va <= sa:
        erros.append(f"VOLTA_ALMOCO ({va}) não pode ser ≤ SAIDA_ALMOCO ({sa})")

    if va and st and st <= va:
        erros.append(f"SAIDA_TARDE ({st}) não pode ser ≤ VOLTA_ALMOCO ({va})")

    # Intervalo de almoço mínimo
    if sa and va:
        delta = _delta_minutos(sa, va)
        if delta < _ALMOCO_MIN_MINUTOS:
            erros.append(
                f"Intervalo almoço de {delta}min abaixo do mínimo de {_ALMOCO_MIN_MINUTOS}min"
            )

    # Jornada total implausível (> 14h sugere erro de leitura)
    if em and st:
        jornada = _delta_minutos(em, st)
        if jornada > 14 * 60:
            erros.append(f"Jornada total de {jornada//60}h parece implausível (> 14h)")

    if erros:
        logger.debug(f"Batida {batida.colaborador} {batida.data}: {len(erros)} erro(s) de validação")

    return erros


def classify_status(batida: BatidaDiaria, limiar_confianca: float = 70.0) -> str:
    """Define STATUS_OCR baseado em confiança e validade da batida.

    Retorna: "OK" | "BAIXA_CONFIANCA" | "NAO_LIDO" | "INVALIDO"
    """
    erros = validate_batida(batida)
    if erros:
        return "INVALIDO"
    if batida.horarios_preenchidos() == 0:
        return "NAO_LIDO"
    if batida.confianca < limiar_confianca:
        return "BAIXA_CONFIANCA"
    return "OK"

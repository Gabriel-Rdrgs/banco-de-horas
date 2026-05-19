"""Orquestrador do pipeline OCR de folhas de ponto.

Coordena: arquivo → pré-processamento → OCR → extração → validação → modelos.
O chamador decide se exporta direto ou aguarda revisão humana.

Estado atual: esqueleto com OCR ainda não implementado (Fase 2.1).
Para testar o fluxo de exportação, use processar_folha_manual().
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path

from src.models.folha import BatidaDiaria, FolhaImportacao
from src.models.log import LogProcessamento

logger = logging.getLogger(__name__)


def processar_folha(
    arquivo: Path,
    colaborador: str,
    competencia: str,
    planilha: Path,
    usuario: str = "SISTEMA",
    motor_ocr: str = "tesseract",
    limiar_confianca: float = 70.0,
) -> tuple[FolhaImportacao, LogProcessamento]:
    """Pipeline completo: arquivo → FolhaImportacao + LogProcessamento.

    O caller decide o que fazer com o resultado:
      - exportar diretamente se confiança alta
      - gerar CSV de revisão se confiança baixa
      - descartar em caso de erro

    TODO (Fase 2.1): implementar OCR real aqui.
    Hoje retorna folha vazia com status ESQUELETO_SEM_OCR.
    """
    id_imp = uuid.uuid4().hex[:8].upper()

    folha = FolhaImportacao(
        id_importacao=id_imp,
        arquivo=arquivo.name,
        colaborador=colaborador,
        competencia=competencia,
        data_importacao=datetime.now(),
        usuario=usuario,
        status="PENDENTE_REVISAO",
        confianca_media=0.0,
        batidas=[],
    )

    log = LogProcessamento(
        id_importacao=id_imp,
        data_hora=datetime.now(),
        arquivo=arquivo.name,
        colaborador=colaborador,
        competencia=competencia,
        linhas_importadas=0,
        confianca_media=0.0,
        status="ESQUELETO_SEM_OCR",
        mensagem_erro="OCR não implementado nesta versão (esqueleto Fase 2.0)",
        usuario=usuario,
    )

    # --- Fase 2.1: descomentar e implementar ---
    # from src.ocr.preprocessor import pdf_to_images, preprocess_image
    # from src.ocr.engine import get_engine
    # from src.ocr.extractor import extrair_linha_batidas, extrair_competencia
    # from src.parser.normalizer import parse_time, normalize_dia_semana
    # from src.parser.validator import classify_status, validate_batida
    #
    # engine = get_engine(motor_ocr)
    # imagens = pdf_to_images(arquivo) if arquivo.suffix.lower() == ".pdf" else [arquivo]
    # for img_path in imagens:
    #     img_proc = preprocess_image(img_path)
    #     resultado = engine.read(img_proc or img_path)
    #     ... extrair campos, construir BatidaDiaria, validar ...

    logger.warning(f"[{id_imp}] Pipeline esqueleto — OCR não executado para '{arquivo.name}'")
    return folha, log


def processar_folha_manual(
    colaborador: str,
    competencia: str,
    batidas_raw: list[dict],
    usuario: str = "SISTEMA",
) -> tuple[FolhaImportacao, LogProcessamento]:
    """Cria FolhaImportacao a partir de dados inseridos manualmente (sem OCR).

    Permite testar o fluxo de exportação para Excel sem depender do OCR.

    batidas_raw: lista de dicts com chaves:
      data (str "DD/MM/AAAA" ou date),
      dia_semana, entrada_manha, saida_almoco, volta_almoco, saida_tarde
      (horários como str "HH:MM" ou None)
    """
    from datetime import date
    from src.parser.normalizer import parse_time, normalize_dia_semana
    from src.parser.validator import classify_status

    id_imp = uuid.uuid4().hex[:8].upper()
    batidas: list[BatidaDiaria] = []

    for raw in batidas_raw:
        if isinstance(raw["data"], str):
            dia, mes, ano = raw["data"].split("/")
            data_obj = date(int(ano), int(mes), int(dia))
        else:
            data_obj = raw["data"]

        batida = BatidaDiaria(
            colaborador=colaborador,
            competencia=competencia,
            data=data_obj,
            dia_semana=normalize_dia_semana(raw.get("dia_semana", "")) or raw.get("dia_semana", ""),
            entrada_manha=parse_time(raw.get("entrada_manha") or ""),
            saida_almoco=parse_time(raw.get("saida_almoco") or ""),
            volta_almoco=parse_time(raw.get("volta_almoco") or ""),
            saida_tarde=parse_time(raw.get("saida_tarde") or ""),
            status_ocr="OK",
            confianca=100.0,   # manual = confiança total
            id_importacao=id_imp,
        )
        batida.status_ocr = classify_status(batida, limiar_confianca=70.0)
        batidas.append(batida)

    folha = FolhaImportacao(
        id_importacao=id_imp,
        arquivo="ENTRADA_MANUAL",
        colaborador=colaborador,
        competencia=competencia,
        data_importacao=datetime.now(),
        usuario=usuario,
        status="APROVADO",
        confianca_media=100.0,
        batidas=batidas,
    )
    folha.calcular_confianca_media()

    log = LogProcessamento(
        id_importacao=id_imp,
        data_hora=datetime.now(),
        arquivo="ENTRADA_MANUAL",
        colaborador=colaborador,
        competencia=competencia,
        linhas_importadas=len(batidas),
        confianca_media=folha.confianca_media,
        status="OK",
        usuario=usuario,
    )

    logger.info(f"[{id_imp}] Folha manual criada: {colaborador} {competencia} — {len(batidas)} batida(s)")
    return folha, log

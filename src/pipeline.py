"""Orquestrador do pipeline OCR de folhas de ponto.

Fluxo completo:
  arquivo (PDF/imagem)
    → renderizar páginas (PyMuPDF)
    → pré-processar imagem (OpenCV)
    → OCR (Tesseract)
    → parse do layout (folha_parser)
    → construir BatidaDiaria + validar
    → retornar FolhaImportacao + LogProcessamento

O chamador decide se exporta direto ou aguarda revisão humana.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path

from src.models.folha import BatidaDiaria, FolhaImportacao
from src.models.log import LogProcessamento
from src.parser.validator import classify_status

logger = logging.getLogger(__name__)


def _renderizar_pdf(arquivo: Path, dpi: int = 400) -> list[Path]:
    """Converte PDF em imagens PNG via PyMuPDF (sem Poppler).

    400 DPI produz imagens de boa qualidade para OCR de manuscritos.
    """
    from src.ocr.preprocessor import pdf_to_images_mupdf
    return pdf_to_images_mupdf(arquivo, dpi=dpi)


def _preprocessar(image_path: Path) -> Path:
    """Pré-processamento completo: remoção de grade + binarização adaptativa.

    A remoção de grade é essencial para formulários tabulares como esta folha de ponto.
    """
    from src.ocr.preprocessor import preprocess_for_ocr
    return preprocess_for_ocr(image_path)


def _linhas_para_batidas(
    linhas,
    colaborador: str,
    competencia: str,
    id_importacao: str,
    confianca_ocr: float,
) -> list[BatidaDiaria]:
    """Converte LinhaFolha (do parser) em BatidaDiaria."""
    from src.ocr.folha_parser import LinhaFolha

    batidas: list[BatidaDiaria] = []
    for lf in linhas:
        if lf.data is None:
            continue

        # Confiança da batida = média entre confiança do OCR e dos horários
        confianca_batida = (confianca_ocr + lf.confianca_horarios) / 2

        b = BatidaDiaria(
            colaborador=colaborador,
            competencia=competencia,
            data=lf.data,
            dia_semana=lf.dia_semana or "",
            entrada_manha=lf.entrada_manha,
            saida_almoco=lf.saida_almoco,
            volta_almoco=lf.volta_almoco,
            saida_tarde=lf.saida_tarde,
            status_ocr="OK",
            confianca=round(confianca_batida, 1),
            observacoes=f"tipo={lf.tipo}" if lf.tipo != "NORMAL" else "",
            id_importacao=id_importacao,
        )
        b.status_ocr = classify_status(b)
        batidas.append(b)

    return batidas


def processar_folha(
    arquivo: Path,
    colaborador: str,
    competencia: str,
    usuario: str = "SISTEMA",
    motor_ocr: str = "tesseract",
    limiar_confianca: float = 70.0,
) -> tuple[FolhaImportacao, LogProcessamento]:
    """Pipeline completo: PDF/imagem → FolhaImportacao + LogProcessamento.

    Passos:
      1. Renderiza PDF em imagens (PyMuPDF)
      2. Pré-processa cada imagem (OpenCV)
      3. Executa OCR (Tesseract)
      4. Parseia layout da folha Provida
      5. Constrói e valida BatidaDiaria
      6. Retorna modelos prontos para exportação ou revisão
    """
    from src.ocr.engine import get_engine
    from src.ocr.folha_parser import parse_pagina, parse_pagina_azure

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
        status="ERRO",
        usuario=usuario,
    )

    try:
        from src.config import cfg
        engine_kwargs: dict = {}

        if motor_ocr == "azure_vision":
            if cfg.azure_configurado:
                engine_kwargs["endpoint"] = cfg.azure_endpoint
                engine_kwargs["api_key"]  = cfg.azure_key
            else:
                raise RuntimeError(
                    "Azure Vision não configurado.\n"
                    "Preencha AZURE_VISION_ENDPOINT e AZURE_VISION_KEY no arquivo .env"
                )

        elif motor_ocr == "google_vision":
            chave = Path(__file__).parent.parent / "gcp_key.json"
            if chave.exists():
                engine_kwargs["credentials_path"] = chave

        elif motor_ocr == "claude_vision":
            if cfg.anthropic_configurado:
                engine_kwargs["api_key"] = cfg.anthropic_api_key

        engine = get_engine(motor_ocr, **engine_kwargs)

        # 1. PDF → imagens
        if arquivo.suffix.lower() == ".pdf":
            imagens = _renderizar_pdf(arquivo, dpi=400)
        else:
            imagens = [arquivo]

        todas_batidas: list[BatidaDiaria] = []

        for img_path in imagens:
            # 2. Pré-processar (remoção de grade + binarização)
            img_proc = _preprocessar(img_path)

            # 3. OCR
            resultado_ocr = engine.read(img_proc)
            logger.info(f"OCR: {len(resultado_ocr.texto)} chars, confiança {resultado_ocr.confianca:.1f}%")

            if not resultado_ocr.texto.strip():
                logger.warning(f"OCR retornou texto vazio para {img_path.name}")
                continue

            # 4. Parse do layout
            # Azure Vision retorna uma célula por linha — parser específico
            if motor_ocr == "azure_vision":
                cabecalho, linhas = parse_pagina_azure(resultado_ocr.texto)
            else:
                cabecalho, linhas = parse_pagina(resultado_ocr.texto)

            # Usa colaborador/competência passados pelo usuário como fonte primária;
            # cabeçalho do OCR entra como fallback ou validação
            collab = colaborador or cabecalho.colaborador or "DESCONHECIDO"
            comp   = competencia or cabecalho.competencia or "00/0000"

            if cabecalho.colaborador and cabecalho.colaborador.upper() != colaborador.upper():
                logger.warning(
                    f"Nome no OCR ('{cabecalho.colaborador}') difere do informado ('{colaborador}')"
                )

            # 5. Construir batidas
            batidas_pagina = _linhas_para_batidas(
                linhas, collab, comp, id_imp, resultado_ocr.confianca
            )
            todas_batidas.extend(batidas_pagina)

        folha.batidas = todas_batidas
        folha.calcular_confianca_media()

        pendentes = folha.batidas_pendentes_revisao(limiar_confianca)
        folha.status = "PENDENTE_REVISAO" if pendentes else "APROVADO"

        log.linhas_importadas = len(todas_batidas)
        log.confianca_media = folha.confianca_media
        log.status = "REVISAO_PENDENTE" if pendentes else "OK"
        log.mensagem_erro = ""

        logger.info(
            f"[{id_imp}] Pipeline OK: {len(todas_batidas)} batida(s), "
            f"confiança {folha.confianca_media:.1f}%, "
            f"{len(pendentes)} pendente(s) revisão"
        )

    except Exception as e:
        log.mensagem_erro = str(e)
        log.status = "ERRO"
        logger.error(f"[{id_imp}] Erro no pipeline: {e}", exc_info=True)

    return folha, log


def processar_folha_manual(
    colaborador: str,
    competencia: str,
    batidas_raw: list[dict],
    usuario: str = "SISTEMA",
) -> tuple[FolhaImportacao, LogProcessamento]:
    """Cria FolhaImportacao a partir de dados manuais (sem OCR).

    Útil para testes e para entrada manual no fluxo atual (Fase 1).
    batidas_raw: lista de dicts com chaves:
      data (str "DD/MM/AAAA"), dia_semana, entrada_manha,
      saida_almoco, volta_almoco, saida_tarde (HH:MM ou None)
    """
    from datetime import date
    from src.parser.normalizer import parse_time, normalize_dia_semana

    id_imp = uuid.uuid4().hex[:8].upper()
    batidas: list[BatidaDiaria] = []

    for raw in batidas_raw:
        if isinstance(raw["data"], str):
            dia, mes, ano = raw["data"].split("/")
            data_obj = date(int(ano), int(mes), int(dia))
        else:
            data_obj = raw["data"]

        b = BatidaDiaria(
            colaborador=colaborador,
            competencia=competencia,
            data=data_obj,
            dia_semana=normalize_dia_semana(raw.get("dia_semana", "")) or raw.get("dia_semana", ""),
            entrada_manha=parse_time(raw.get("entrada_manha") or ""),
            saida_almoco=parse_time(raw.get("saida_almoco") or ""),
            volta_almoco=parse_time(raw.get("volta_almoco") or ""),
            saida_tarde=parse_time(raw.get("saida_tarde") or ""),
            status_ocr="OK",
            confianca=100.0,
            id_importacao=id_imp,
        )
        b.status_ocr = classify_status(b)
        batidas.append(b)

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

    logger.info(f"[{id_imp}] Manual: {colaborador} {competencia} — {len(batidas)} batida(s)")
    return folha, log

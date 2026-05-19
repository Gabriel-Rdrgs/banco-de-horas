"""Geração de CSV de revisão humana para campos com baixa confiança.

Fluxo:
  1. Pipeline detecta batidas com confiança < limiar
  2. Este módulo gera CSV em saida/revisao/
  3. Revisor abre o CSV, preenche 'valor_corrigido' e 'revisado_por'
  4. Script futuro reimporta o CSV corrigido e atualiza a planilha

Decisão de design: CSV simples, não banco de dados.
O CSV é auditável, versionável e abrível em Excel pelo time da Provida.
"""
from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.models.folha import BatidaDiaria, FolhaImportacao
from src.models.log import CampoRevisao
from src.parser.normalizer import time_to_str

logger = logging.getLogger(__name__)

_CAMPOS_HORARIO = ["entrada_manha", "saida_almoco", "volta_almoco", "saida_tarde"]
_NOME_LEGIVEL = {
    "entrada_manha": "ENTRADA_MANHA",
    "saida_almoco": "SAIDA_ALMOCO",
    "volta_almoco": "VOLTA_ALMOCO",
    "saida_tarde": "SAIDA_TARDE",
}
_CSV_CABECALHO = [
    "id_batida", "data", "dia_semana", "campo",
    "valor_ocr", "confianca",
    "valor_corrigido", "revisado_por", "data_revisao",
    "observacoes",
]


def _campos_para_revisao(batida: BatidaDiaria, limiar: float) -> list[CampoRevisao]:
    """Retorna lista de CampoRevisao para uma batida com confiança abaixo do limiar."""
    if not batida.precisa_revisao(limiar):
        return []

    id_bat = f"{batida.colaborador.replace(' ', '_').upper()}_{batida.data.strftime('%Y%m%d')}"
    campos: list[CampoRevisao] = []

    for campo_attr in _CAMPOS_HORARIO:
        valor = getattr(batida, campo_attr)
        campos.append(CampoRevisao(
            id_batida=id_bat,
            data=batida.data,
            campo=_NOME_LEGIVEL[campo_attr],
            valor_ocr=time_to_str(valor) if valor else "NAO_LIDO",
            confianca=batida.confianca,
        ))

    return campos


def gerar_csv_revisao(
    folha: FolhaImportacao,
    limiar: float = 70.0,
    output_dir: Optional[Path] = None,
) -> Optional[Path]:
    """Gera CSV com todos os campos que precisam de revisão humana.

    Retorna caminho do CSV gerado, ou None se nenhuma batida precisar revisão.
    """
    if output_dir is None:
        output_dir = Path("saida/revisao")

    pendentes: list[CampoRevisao] = []
    for batida in folha.batidas:
        pendentes.extend(_campos_para_revisao(batida, limiar))

    if not pendentes:
        logger.info("Nenhum campo pendente de revisão — CSV não gerado")
        return None

    output_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    nome_collab = folha.colaborador.replace(" ", "_").upper()[:20]
    csv_path = output_dir / f"revisao_{nome_collab}_{ts}.csv"

    # utf-8-sig garante que Excel abre o CSV com acentos corretamente
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_CABECALHO)
        writer.writeheader()

        for c in pendentes:
            # Recupera dia_semana da batida original para contexto visual
            batida_ref = next(
                (b for b in folha.batidas if b.data == c.data), None
            )
            writer.writerow({
                "id_batida":       c.id_batida,
                "data":            c.data.strftime("%d/%m/%Y"),
                "dia_semana":      batida_ref.dia_semana if batida_ref else "",
                "campo":           c.campo,
                "valor_ocr":       c.valor_ocr,
                "confianca":       f"{c.confianca:.1f}",
                "valor_corrigido": "",
                "revisado_por":    "",
                "data_revisao":    "",
                "observacoes":     "",
            })

    logger.info(f"CSV de revisão gerado: {csv_path} ({len(pendentes)} campo(s))")
    return csv_path


def carregar_csv_revisao(csv_path: Path) -> list[CampoRevisao]:
    """Carrega CSV de revisão preenchido pelo revisor.

    Retorna apenas registros onde 'valor_corrigido' foi preenchido.
    Usado futuramente para reimportar correções na planilha.
    """
    revisados: list[CampoRevisao] = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("valor_corrigido", "").strip():
                continue
            from datetime import date
            revisados.append(CampoRevisao(
                id_batida=row["id_batida"],
                data=date.fromisoformat(
                    datetime.strptime(row["data"], "%d/%m/%Y").strftime("%Y-%m-%d")
                ),
                campo=row["campo"],
                valor_ocr=row["valor_ocr"],
                confianca=float(row["confianca"]),
                valor_corrigido=row["valor_corrigido"],
                revisado_por=row.get("revisado_por") or None,
                data_revisao=datetime.fromisoformat(row["data_revisao"])
                if row.get("data_revisao") else None,
            ))

    logger.info(f"CSV de revisão carregado: {len(revisados)} campo(s) corrigido(s)")
    return revisados

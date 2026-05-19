"""Modelos para log de processamento e controle de revisão humana."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional


@dataclass
class LogProcessamento:
    """Representa uma linha da aba ControleOCR.

    Registra cada importação de folha: quem, quando, resultado.
    Nunca é alterado após gravação — é um log auditável.
    """
    id_importacao: str
    data_hora: datetime
    arquivo: str
    colaborador: str
    competencia: str
    linhas_importadas: int
    confianca_media: float        # 0–100 (%)
    status: str                   # "OK" | "REVISAO_PENDENTE" | "ERRO" | "ESQUELETO_SEM_OCR"
    mensagem_erro: str = ""
    usuario: str = "SISTEMA"


@dataclass
class CampoRevisao:
    """Representa um campo específico de uma batida que precisa de revisão humana.

    Gerado quando confianca < limiar. É exportado para CSV na pasta saida/revisao/.
    O revisor preenche valor_corrigido, revisado_por e data_revisao no CSV
    e reimporta manualmente ou via script futuro.
    """
    id_batida: str                # ex: "Amanda Curcino_20260501"
    data: date
    campo: str                    # "ENTRADA_MANHA" | "SAIDA_ALMOCO" | "VOLTA_ALMOCO" | "SAIDA_TARDE"
    valor_ocr: str                # valor bruto lido pelo OCR ("08:00" ou "?")
    confianca: float              # confiança específica deste campo (0–100)
    valor_corrigido: Optional[str] = None
    revisado_por: Optional[str] = None
    data_revisao: Optional[datetime] = None

    @property
    def revisado(self) -> bool:
        return self.valor_corrigido is not None

    def to_csv_row(self) -> dict:
        """Serializa para uma linha de CSV de revisão."""
        return {
            "id_batida": self.id_batida,
            "data": self.data.isoformat(),
            "campo": self.campo,
            "valor_ocr": self.valor_ocr,
            "confianca": self.confianca,
            "valor_corrigido": self.valor_corrigido or "",
            "revisado_por": self.revisado_por or "",
            "data_revisao": self.data_revisao.isoformat() if self.data_revisao else "",
        }

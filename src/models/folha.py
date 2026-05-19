"""Modelos de dados para importação de folhas de ponto."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Optional


@dataclass
class BatidaDiaria:
    """Representa uma linha de batidas de um colaborador em um dia específico.

    Mapeia diretamente para uma linha da aba BatidasOCR da planilha.
    Colunas J, K, L (HRS_TRABALHADAS, JORNADA_ESPERADA, DIFERENÇA_DIA)
    são calculadas pelo Excel — não gravar nesses campos.
    """
    colaborador: str
    competencia: str              # formato "MM/AAAA", ex: "05/2026"
    data: date
    dia_semana: str               # "Segunda", "Terça", ... "Domingo"
    entrada_manha: Optional[time]
    saida_almoco: Optional[time]
    volta_almoco: Optional[time]
    saida_tarde: Optional[time]
    status_ocr: str               # "OK" | "BAIXA_CONFIANCA" | "NAO_LIDO"
    confianca: float              # 0–100 (%)
    observacoes: str = ""
    id_importacao: str = ""       # chave para LogProcessamento

    def precisa_revisao(self, limiar: float = 70.0) -> bool:
        """True se a confiança de leitura está abaixo do limiar."""
        return self.confianca < limiar

    def horarios_preenchidos(self) -> int:
        """Quantidade de campos de horário que foram lidos (0–4)."""
        return sum(1 for h in [
            self.entrada_manha,
            self.saida_almoco,
            self.volta_almoco,
            self.saida_tarde,
        ] if h is not None)


@dataclass
class FolhaImportacao:
    """Representa uma folha de ponto completa importada via OCR.

    Contém a lista de BatidaDiaria e os metadados da importação.
    É a unidade de trabalho do pipeline.
    """
    id_importacao: str            # ex: "A3F2B1C0" (UUID truncado)
    arquivo: str                  # nome do arquivo original
    colaborador: str
    competencia: str              # "MM/AAAA"
    data_importacao: datetime
    usuario: str
    status: str                   # "PENDENTE_REVISAO" | "APROVADO" | "ERRO"
    confianca_media: float        # média de confiança de todas as batidas
    batidas: list[BatidaDiaria] = field(default_factory=list)

    def batidas_pendentes_revisao(self, limiar: float = 70.0) -> list[BatidaDiaria]:
        """Retorna batidas que precisam de revisão humana."""
        return [b for b in self.batidas if b.precisa_revisao(limiar)]

    def calcular_confianca_media(self) -> float:
        """Recalcula e atualiza confianca_media com base nas batidas atuais."""
        if not self.batidas:
            return 0.0
        media = sum(b.confianca for b in self.batidas) / len(self.batidas)
        self.confianca_media = round(media, 1)
        return self.confianca_media

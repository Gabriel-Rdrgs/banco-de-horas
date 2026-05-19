"""Motor OCR plugável.

Abstração que permite trocar o engine (Tesseract → EasyOCR → Google Vision)
sem alterar o pipeline. Adicione novos engines implementando OCREngine.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class OCRResult:
    """Resultado bruto de uma leitura OCR."""
    texto: str
    confianca: float      # 0–100; -1.0 se o engine não fornecer confiança
    pagina: int = 1


class OCREngine(ABC):
    """Interface base para engines OCR."""

    @abstractmethod
    def read(self, image_path: Path) -> OCRResult:
        """Executa OCR numa imagem pré-processada. Retorna texto + confiança."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """True se as dependências do engine estão instaladas e configuradas."""
        ...

    @property
    @abstractmethod
    def nome(self) -> str:
        """Nome do engine para logs e metadados."""
        ...


class TesseractEngine(OCREngine):
    """Engine Tesseract via pytesseract.

    Requer:
      - Tesseract binário instalado no sistema (https://github.com/UB-Mannheim/tesseract/wiki)
      - pytesseract: pip install pytesseract
      - Dados de idioma português: tessdata-por (instalar no Tesseract)
    """

    def __init__(self, lang: str = "por", psm: int = 6):
        self.lang = lang
        # PSM 6 = bloco uniforme de texto (bom para formulários)
        self._config = f"--psm {psm}"

    @property
    def nome(self) -> str:
        return "tesseract"

    def is_available(self) -> bool:
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            return True
        except Exception as e:
            logger.warning(f"Tesseract não disponível: {e}")
            return False

    def read(self, image_path: Path) -> OCRResult:
        try:
            import pytesseract
            from PIL import Image
        except ImportError:
            raise RuntimeError("Instale: pip install pytesseract Pillow")

        img = Image.open(str(image_path))
        data = pytesseract.image_to_data(
            img,
            lang=self.lang,
            config=self._config,
            output_type=pytesseract.Output.DICT,
        )

        palavras = [
            w for w, c in zip(data["text"], data["conf"])
            if str(c).lstrip("-").isdigit() and int(c) > 0 and str(w).strip()
        ]
        confianças = [
            int(c) for c in data["conf"]
            if str(c).lstrip("-").isdigit() and int(c) > 0
        ]

        texto = " ".join(palavras)
        confianca = sum(confianças) / len(confianças) if confianças else 0.0

        logger.debug(f"Tesseract leu {len(palavras)} palavras, confiança média {confianca:.1f}%")
        return OCRResult(texto=texto, confianca=round(confianca, 1))


# --- Registro de engines disponíveis ---
_ENGINES: dict[str, type[OCREngine]] = {
    "tesseract": TesseractEngine,
    # "easyocr": EasyOCREngine,       # Fase 2.1 — verificar compatibilidade Python 3.14
    # "google_vision": GoogleVisionEngine,  # Fase 2.2 — requer credenciais GCP
}


def get_engine(nome: str = "tesseract") -> OCREngine:
    """Fábrica de engines. Levanta ValueError se o nome não existir."""
    if nome not in _ENGINES:
        disponiveis = list(_ENGINES.keys())
        raise ValueError(f"Engine '{nome}' não registrado. Disponíveis: {disponiveis}")
    engine = _ENGINES[nome]()
    if not engine.is_available():
        raise RuntimeError(
            f"Engine '{nome}' não está disponível no ambiente atual. "
            "Verifique se o binário e as dependências Python estão instalados."
        )
    return engine

"""Configuração centralizada do sistema.

Carrega variáveis de ambiente do arquivo .env na raiz do projeto.
Todos os módulos devem importar as credenciais daqui — nunca de os.environ direto.

Uso:
    from src.config import cfg
    engine = get_engine(cfg.ocr_engine, endpoint=cfg.azure_endpoint, api_key=cfg.azure_key)
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Carrega .env da raiz do projeto (pasta pai de src/)
_ROOT = Path(__file__).parent.parent
_ENV_FILE = _ROOT / ".env"

try:
    from dotenv import load_dotenv
    if _ENV_FILE.exists():
        load_dotenv(_ENV_FILE, override=False)   # override=False: env vars do sistema têm precedência
        logger.debug(f".env carregado de {_ENV_FILE}")
    else:
        logger.debug(".env não encontrado — usando variáveis de ambiente do sistema")
except ImportError:
    logger.warning("python-dotenv não instalado — instale: pip install python-dotenv")


@dataclass(frozen=True)
class Config:
    """Configuração imutável carregada do .env e variáveis de ambiente."""

    # Engine OCR
    ocr_engine: str
    ocr_confianca_minima: float
    ocr_usuario_padrao: str

    # Azure Vision
    azure_endpoint: str
    azure_key: str

    # Google Vision (opcional)
    google_credentials_path: str

    # Anthropic (opcional)
    anthropic_api_key: str

    # Planilha Excel
    planilha_path: Path

    @property
    def azure_configurado(self) -> bool:
        return bool(self.azure_endpoint and self.azure_key
                    and self.azure_key != "COLE_SUA_CHAVE_AZURE_AQUI")

    @property
    def google_configurado(self) -> bool:
        cred = self.google_credentials_path
        return bool(cred and Path(cred).exists())

    @property
    def anthropic_configurado(self) -> bool:
        return bool(self.anthropic_api_key
                    and not self.anthropic_api_key.startswith("sk-ant-api03-..."))

    def engine_disponivel(self) -> bool:
        """True se o engine configurado tem credenciais prontas."""
        checks = {
            "azure_vision":  self.azure_configurado,
            "google_vision": self.google_configurado,
            "claude_vision": self.anthropic_configurado,
            "tesseract":     True,
        }
        return checks.get(self.ocr_engine, False)

    def resumo(self) -> str:
        """String de diagnóstico para logs e debug."""
        linhas = [
            f"Engine: {self.ocr_engine}",
            f"  Azure:    {'OK' if self.azure_configurado else 'NAO CONFIGURADO'}",
            f"  Google:   {'OK' if self.google_configurado else 'NAO CONFIGURADO'}",
            f"  Anthropic:{'OK' if self.anthropic_configurado else 'NAO CONFIGURADO'}",
            f"  Confiança mínima: {self.ocr_confianca_minima}%",
            f"  Planilha: {self.planilha_path}",
        ]
        return "\n".join(linhas)


def _load() -> Config:
    """Lê todas as configurações do ambiente e retorna um Config imutável."""
    return Config(
        ocr_engine             = os.environ.get("OCR_ENGINE", "azure_vision"),
        ocr_confianca_minima   = float(os.environ.get("OCR_CONFIANCA_MINIMA", "70.0")),
        ocr_usuario_padrao     = os.environ.get("OCR_USUARIO_PADRAO", "SISTEMA"),
        azure_endpoint         = os.environ.get("AZURE_VISION_ENDPOINT", ""),
        azure_key              = os.environ.get("AZURE_VISION_KEY", ""),
        google_credentials_path= os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", ""),
        anthropic_api_key      = os.environ.get("ANTHROPIC_API_KEY", ""),
        planilha_path          = _ROOT / "planilha" / "BancoHoras_Provida_v2.xlsm",
    )


# Instância global — importar e usar diretamente
cfg = _load()

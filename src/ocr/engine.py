"""Motor OCR plugável.

Abstração que permite trocar o engine (Tesseract → Google Vision → EasyOCR)
sem alterar o pipeline. Adicione novos engines implementando OCREngine.

Engines disponíveis:
  tesseract      — local, gratuito, funciona offline. Ruim para manuscrito.
  google_vision  — cloud, 1.000 imagens/mês grátis. Excelente para manuscrito.
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
        """Executa OCR numa imagem. Retorna texto com quebras de linha + confiança média."""
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


# ---------------------------------------------------------------------------
# Engine 1: Tesseract (local, offline)
# ---------------------------------------------------------------------------

class TesseractEngine(OCREngine):
    """Engine Tesseract via pytesseract.

    Requer:
      - Tesseract binário: winget install UB-Mannheim.TesseractOCR
      - pytesseract: pip install pytesseract
      - Idioma português incluído no instalador UB-Mannheim
    """

    _WIN_PATHS = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]

    def __init__(self, lang: str = "por+eng", psm: int = 4):
        self.lang = lang
        # PSM 4 = coluna única de texto variável — melhor para formulários tabulares
        # OEM 3 = modo padrão (LSTM neural net)
        self._config = f"--psm {psm} --oem 3"
        self._configurar_path()

    def _configurar_path(self) -> None:
        import sys
        if sys.platform != "win32":
            return
        import pytesseract
        for caminho in self._WIN_PATHS:
            if Path(caminho).exists():
                pytesseract.pytesseract.tesseract_cmd = caminho
                logger.debug(f"Tesseract: {caminho}")
                return
        logger.warning("Tesseract não encontrado. Instale: winget install UB-Mannheim.TesseractOCR")

    @property
    def nome(self) -> str:
        return "tesseract"

    def is_available(self) -> bool:
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            return True
        except Exception as e:
            logger.warning(f"Tesseract indisponível: {e}")
            return False

    def read(self, image_path: Path) -> OCRResult:
        try:
            import pytesseract
            from PIL import Image
        except ImportError:
            raise RuntimeError("Instale: pip install pytesseract Pillow")

        img = Image.open(str(image_path))
        texto = pytesseract.image_to_string(img, lang=self.lang, config=self._config)

        data = pytesseract.image_to_data(
            img, lang=self.lang, config=self._config,
            output_type=pytesseract.Output.DICT,
        )
        confs = [int(c) for c in data["conf"] if str(c).lstrip("-").isdigit() and int(c) > 0]
        confianca = sum(confs) / len(confs) if confs else 0.0

        logger.debug(f"Tesseract: confiança {confianca:.1f}%")
        return OCRResult(texto=texto, confianca=round(confianca, 1))


# ---------------------------------------------------------------------------
# Engine 2: Google Cloud Vision (cloud, melhor para manuscrito)
# ---------------------------------------------------------------------------

class GoogleVisionEngine(OCREngine):
    """Engine Google Cloud Vision via REST API.

    Usa document_text_detection — endpoint otimizado para documentos densos
    com texto misto (impresso + manuscrito), preservando layout e linhas.

    Requer:
      - pip install google-cloud-vision
      - Arquivo de credenciais JSON (service account) em gcp_key.json
        OU variável GOOGLE_APPLICATION_CREDENTIALS apontando para o JSON
      - Vision API ativada no projeto GCP
      - Cota gratuita: 1.000 imagens/mês

    Referência de preços: cloud.google.com/vision/pricing
    """

    def __init__(self, credentials_path: str | Path | None = None):
        """
        credentials_path: caminho para o JSON da service account.
        Se None, usa GOOGLE_APPLICATION_CREDENTIALS ou ADC.
        """
        self._credentials_path = Path(credentials_path) if credentials_path else None
        self._client = None

    def _get_client(self):
        """Cria ou retorna o cliente Vision (lazy initialization)."""
        if self._client is not None:
            return self._client

        try:
            from google.cloud import vision
            from google.oauth2 import service_account
        except ImportError:
            raise RuntimeError(
                "google-cloud-vision não instalado.\n"
                "Execute: pip install google-cloud-vision"
            )

        if self._credentials_path and self._credentials_path.exists():
            creds = service_account.Credentials.from_service_account_file(
                str(self._credentials_path),
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            self._client = vision.ImageAnnotatorClient(credentials=creds)
            logger.info(f"Google Vision: credenciais carregadas de {self._credentials_path.name}")
        else:
            # Usa Application Default Credentials (gcloud auth, env var, etc.)
            self._client = vision.ImageAnnotatorClient()
            logger.info("Google Vision: usando Application Default Credentials")

        return self._client

    @property
    def nome(self) -> str:
        return "google_vision"

    def is_available(self) -> bool:
        try:
            from google.cloud import vision  # noqa: F401
            return True
        except ImportError:
            logger.warning("google-cloud-vision não instalado")
            return False

    def read(self, image_path: Path) -> OCRResult:
        """Envia imagem ao Google Vision e retorna texto estruturado por linhas.

        Usa document_text_detection (DOCUMENT_TEXT_DETECTION) que é superior
        ao text_detection para documentos com tabelas e manuscrito misto.
        A API retorna texto com quebras de linha que preservam o layout da página.
        """
        from google.cloud import vision

        client = self._get_client()

        with open(str(image_path), "rb") as f:
            content = f.read()

        image = vision.Image(content=content)
        response = client.document_text_detection(image=image)

        if response.error.message:
            raise RuntimeError(
                f"Google Vision API erro: {response.error.message}\n"
                "Verifique se a Vision API está ativada no projeto GCP."
            )

        annotation = response.full_text_annotation
        if not annotation or not annotation.text:
            logger.warning("Google Vision retornou texto vazio")
            return OCRResult(texto="", confianca=0.0)

        # Calcula confiança média a partir dos símbolos (nível mais granular)
        confs: list[float] = []
        for page in annotation.pages:
            for block in page.blocks:
                for para in block.paragraphs:
                    for word in para.words:
                        for symbol in word.symbols:
                            if hasattr(symbol, "confidence") and symbol.confidence > 0:
                                confs.append(symbol.confidence * 100)

        confianca = sum(confs) / len(confs) if confs else 85.0  # Vision raramente retorna confiança

        n_palavras = len(annotation.text.split())
        logger.debug(f"Google Vision: {n_palavras} palavras, confiança {confianca:.1f}%")

        return OCRResult(texto=annotation.text, confianca=round(confianca, 1))


# ---------------------------------------------------------------------------
# Engine 3: Claude Vision (Anthropic API)
# ---------------------------------------------------------------------------

_PROMPT_EXTRACAO = """\
Você está analisando uma Folha de Ponto Individual de Trabalho da Provida Centro Médico.

Extraia TODOS os dias listados na tabela de pontos.
Para cada linha retorne exatamente neste formato (separado por espaços):

DATA DIA_DA_SEMANA ENTRADA_MANHA SAIDA_ALMOCO VOLTA_ALMOCO SAIDA_TARDE

Regras obrigatórias:
- DATA: formato DD/MM/AAAA
- DIA_DA_SEMANA: Segunda-Feira, Terça-Feira, Quarta-Feira, Quinta-Feira, Sexta-Feira, Sábado ou Domingo
- Horários: formato HH:MM em 24h. Use -- se o campo estiver em branco ou ilegível
- Sábado, Domingo e dias de folga: registre a data e o dia, com -- em todos os horários
- Retorne UMA linha por dia, sem cabeçalho, sem totais, sem explicação

Exemplo de saída esperada:
16/04/2026 Quinta-Feira 07:42 12:00 13:00 17:19
17/04/2026 Sexta-Feira 07:55 12:00 13:00 17:00
18/04/2026 Sábado -- -- -- --
19/04/2026 Domingo -- -- -- --
"""


class ClaudeVisionEngine(OCREngine):
    """Engine Claude Vision via Anthropic Messages API.

    Envia a imagem da folha de ponto para o Claude com um prompt estruturado.
    Claude lê o formulário com compreensão contextual — muito superior ao Tesseract
    para manuscrito, pois entende o layout do formulário, não só os pixels.

    Requer:
      - pip install anthropic
      - Variável de ambiente ANTHROPIC_API_KEY
        OU parâmetro api_key no construtor

    Modelos disponíveis (custo crescente / qualidade crescente):
      claude-haiku-4-5       — rápido, barato, bom para OCR simples
      claude-sonnet-4-6      — equilibrado, recomendado para manuscrito
      claude-opus-4-7        — máxima qualidade (desnecessário para OCR)
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-haiku-4-5",
    ):
        self._api_key = api_key       # None → usa ANTHROPIC_API_KEY do ambiente
        self.model = model
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import anthropic
        except ImportError:
            raise RuntimeError("Instale: pip install anthropic")

        self._client = anthropic.Anthropic(
            api_key=self._api_key   # None → lê ANTHROPIC_API_KEY automaticamente
        )
        return self._client

    @property
    def nome(self) -> str:
        return "claude_vision"

    def is_available(self) -> bool:
        try:
            import anthropic  # noqa: F401
            import os
            return bool(self._api_key or os.environ.get("ANTHROPIC_API_KEY"))
        except ImportError:
            return False

    def read(self, image_path: Path) -> OCRResult:
        """Envia imagem para o Claude e recebe dados estruturados por linha.

        O prompt instrui o Claude a retornar cada dia numa linha no formato
        DD/MM/AAAA DIA HH:MM HH:MM HH:MM HH:MM — compatível com folha_parser.
        """
        import base64
        import anthropic

        client = self._get_client()

        # Determina media_type pela extensão
        ext = image_path.suffix.lower()
        media_type = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
        }.get(ext, "image/png")

        with open(str(image_path), "rb") as f:
            img_b64 = base64.standard_b64encode(f.read()).decode("utf-8")

        logger.info(f"Claude Vision ({self.model}): enviando {image_path.name}...")

        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=2048,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": img_b64,
                                },
                            },
                            {
                                "type": "text",
                                "text": _PROMPT_EXTRACAO,
                            },
                        ],
                    }
                ],
            )
        except anthropic.AuthenticationError:
            raise RuntimeError(
                "ANTHROPIC_API_KEY inválida ou não definida.\n"
                "Defina: $env:ANTHROPIC_API_KEY = 'sk-ant-...'"
            )

        texto = response.content[0].text.strip()
        n_linhas = len([l for l in texto.splitlines() if l.strip()])

        logger.info(f"Claude Vision: {n_linhas} linha(s) extraída(s)")
        logger.debug(f"Resposta Claude:\n{texto[:500]}")

        # Claude entende o contexto — atribuímos confiança base alta
        # Reduzida levemente pois ainda pode errar em caligrafia muito ruim
        return OCRResult(texto=texto, confianca=88.0)


# ---------------------------------------------------------------------------
# Engine 4: Azure AI Vision (skeleton — implementar quando necessário)
# ---------------------------------------------------------------------------

class AzureVisionEngine(OCREngine):
    """Engine Azure Computer Vision — Read API (Image Analysis 4.0).

    Free tier F0: 5.000 transações/mês, sem pré-pagamento.
    Excelente para manuscrito; preserva estrutura de linhas da tabela.

    Requer:
      - pip install azure-ai-vision-imageanalysis
      - Recurso "Computer Vision" criado no portal.azure.com (tier F0)
      - Endpoint: https://<nome>.cognitiveservices.azure.com/
      - Chave: obtida em "Chaves e Ponto de Extremidade" no portal

    Credenciais via construtor OU variáveis de ambiente:
      AZURE_VISION_ENDPOINT  e  AZURE_VISION_KEY
    """

    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
    ):
        import os
        self._endpoint = (endpoint or os.environ.get("AZURE_VISION_ENDPOINT", "")).rstrip("/")
        self._api_key  = api_key or os.environ.get("AZURE_VISION_KEY", "")
        self._client   = None

    def _get_client(self):
        if self._client is not None:
            return self._client

        if not self._endpoint or not self._api_key:
            raise RuntimeError(
                "Azure Vision: endpoint e/ou chave não configurados.\n"
                "Defina AZURE_VISION_ENDPOINT e AZURE_VISION_KEY no ambiente,\n"
                "ou passe endpoint= e api_key= ao construtor."
            )

        try:
            from azure.ai.vision.imageanalysis import ImageAnalysisClient
            from azure.core.credentials import AzureKeyCredential
        except ImportError:
            raise RuntimeError(
                "SDK Azure não instalado.\n"
                "Execute: pip install azure-ai-vision-imageanalysis"
            )

        self._client = ImageAnalysisClient(
            endpoint=self._endpoint,
            credential=AzureKeyCredential(self._api_key),
        )
        logger.info(f"Azure Vision: cliente criado para {self._endpoint}")
        return self._client

    @property
    def nome(self) -> str:
        return "azure_vision"

    def is_available(self) -> bool:
        try:
            from azure.ai.vision.imageanalysis import ImageAnalysisClient  # noqa: F401
            return bool(self._endpoint and self._api_key)
        except ImportError:
            return False

    def read(self, image_path: Path) -> OCRResult:
        """Extrai texto da imagem usando Azure Computer Vision Read.

        Retorna texto com quebras de linha preservadas — compatível com folha_parser.
        O Read API do Azure é assíncrono internamente mas o SDK abstrai isso.
        """
        try:
            from azure.ai.vision.imageanalysis.models import VisualFeatures
        except ImportError:
            raise RuntimeError("Execute: pip install azure-ai-vision-imageanalysis")

        client = self._get_client()

        with open(str(image_path), "rb") as f:
            image_data = f.read()

        logger.info(f"Azure Vision: enviando {image_path.name} ({len(image_data)//1024} KB)...")

        result = client.analyze(
            image_data=image_data,
            visual_features=[VisualFeatures.READ],
        )

        if not result.read or not result.read.blocks:
            logger.warning("Azure Vision: nenhum bloco de texto detectado")
            return OCRResult(texto="", confianca=0.0)

        # Monta texto preservando estrutura de linhas da página
        linhas: list[str] = []
        for block in result.read.blocks:
            for line in block.lines:
                linhas.append(line.text)

        texto = "\n".join(linhas)

        # Confiança: média das palavras (Azure retorna por palavra)
        confs: list[float] = []
        for block in result.read.blocks:
            for line in block.lines:
                for word in line.words:
                    if word.confidence is not None:
                        confs.append(word.confidence * 100)

        confianca = sum(confs) / len(confs) if confs else 82.0

        n_palavras = sum(len(line.words) for block in result.read.blocks for line in block.lines)
        logger.info(f"Azure Vision: {n_palavras} palavras, confiança {confianca:.1f}%")

        return OCRResult(texto=texto, confianca=round(confianca, 1))


# ---------------------------------------------------------------------------
# Registro e fábrica
# ---------------------------------------------------------------------------

_ENGINES: dict[str, type[OCREngine]] = {
    "tesseract":    TesseractEngine,
    "google_vision": GoogleVisionEngine,
    "claude_vision": ClaudeVisionEngine,
    "azure_vision":  AzureVisionEngine,   # skeleton — não implementado ainda
}


def get_engine(nome: str = "tesseract", **kwargs) -> OCREngine:
    """Fábrica de engines. Passa kwargs para o construtor do engine.

    Exemplos:
      get_engine("tesseract")
      get_engine("google_vision", credentials_path="gcp_key.json")
    """
    if nome not in _ENGINES:
        raise ValueError(f"Engine '{nome}' desconhecido. Disponíveis: {list(_ENGINES)}")

    engine = _ENGINES[nome](**kwargs)

    if not engine.is_available():
        raise RuntimeError(
            f"Engine '{nome}' indisponível. "
            "Verifique dependências e credenciais."
        )
    return engine

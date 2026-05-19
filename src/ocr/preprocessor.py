"""Pré-processamento de imagem antes do OCR.

Pipeline: PDF/imagem → grayscale → ampliação → binarização → (deskew futuro)
Projetado para folhas de ponto manuscritas digitalizadas em baixa qualidade.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import cv2
    import numpy as np
    _OPENCV_OK = True
except ImportError:
    _OPENCV_OK = False
    logger.warning("opencv-python não instalado — pré-processamento desabilitado")


def preprocess_image(image_path: Path, scale: float = 2.0) -> Optional["np.ndarray"]:
    """Carrega e pré-processa uma imagem para OCR.

    Retorna array numpy pronto para passar ao OCR, ou None se OpenCV ausente.
    Passos: load → grayscale → ampliar → binarizar (Otsu).
    """
    if not _OPENCV_OK:
        logger.warning("Pré-processamento pulado: OpenCV não disponível")
        return None

    img = cv2.imread(str(image_path))
    if img is None:
        raise FileNotFoundError(f"Não foi possível ler a imagem: {image_path}")

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    if scale != 1.0:
        h, w = gray.shape
        gray = cv2.resize(
            gray,
            (int(w * scale), int(h * scale)),
            interpolation=cv2.INTER_CUBIC,
        )
        logger.debug(f"Imagem ampliada {scale}x: {w}x{h} → {int(w*scale)}x{int(h*scale)}")

    # Binarização adaptativa é melhor que global para iluminação irregular
    binary = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=11,
        C=2,
    )

    return binary


def pdf_to_images(pdf_path: Path, dpi: int = 300) -> list[Path]:
    """Converte páginas de um PDF em arquivos de imagem PNG.

    Retorna lista de caminhos para as imagens geradas em diretório temporário.
    Requer pdf2image e Poppler instalados no sistema.
    """
    try:
        from pdf2image import convert_from_path
    except ImportError:
        raise RuntimeError(
            "pdf2image não instalado. Execute: pip install pdf2image\n"
            "Também é necessário o Poppler no PATH do sistema."
        )

    output_dir = Path(tempfile.mkdtemp(prefix="bancohoras_ocr_"))
    logger.info(f"Convertendo PDF: {pdf_path.name} ({dpi} DPI) → {output_dir}")

    pages = convert_from_path(str(pdf_path), dpi=dpi, output_folder=str(output_dir), fmt="png")

    paths: list[Path] = []
    for i, page_img in enumerate(pages):
        p = output_dir / f"page_{i + 1:03d}.png"
        page_img.save(str(p), "PNG")
        paths.append(p)
        logger.debug(f"Página {i + 1} salva: {p.name}")

    logger.info(f"PDF convertido: {len(paths)} página(s)")
    return paths


def save_debug_image(image: "np.ndarray", output_path: Path) -> None:
    """Salva imagem pré-processada para inspeção manual. Útil durante desenvolvimento."""
    if not _OPENCV_OK:
        return
    cv2.imwrite(str(output_path), image)
    logger.debug(f"Imagem debug salva: {output_path}")

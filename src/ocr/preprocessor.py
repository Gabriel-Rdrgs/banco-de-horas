"""Pré-processamento de imagem antes do OCR.

Pipeline: PDF (PyMuPDF) → grayscale → remoção de grade → binarização adaptativa
Projetado para folhas de ponto manuscritas digitalizadas (formulários com grade).
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


def _remover_grade(img_gray: "np.ndarray") -> "np.ndarray":
    """Remove linhas horizontais e verticais da grade do formulário.

    Formulários impressos têm grade que interfere no OCR de células.
    Técnica: detectar linhas por morfologia → subtrair da imagem binarizada.
    """
    _, binary = cv2.threshold(img_gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Linhas horizontais: kernel largo e fino
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (60, 1))
    h_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, h_kernel, iterations=2)

    # Linhas verticais: kernel alto e fino
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 60))
    v_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, v_kernel, iterations=2)

    grade = cv2.add(h_lines, v_lines)
    sem_grade = cv2.subtract(binary, grade)

    # Retorna para fundo branco / texto preto (padrão para Tesseract)
    return cv2.bitwise_not(sem_grade)


def pdf_to_images_mupdf(pdf_path: Path, dpi: int = 400) -> list[Path]:
    """Converte páginas de PDF em imagens PNG via PyMuPDF (sem Poppler).

    Renderiza em escala de cinza diretamente, evitando etapa de conversão.
    DPI padrão 400 — balanceia qualidade e tempo de processamento.
    """
    try:
        import fitz
    except ImportError:
        raise RuntimeError("PyMuPDF não instalado. Execute: pip install pymupdf")

    output_dir = Path(tempfile.mkdtemp(prefix="bancohoras_ocr_"))
    doc = fitz.open(str(pdf_path))
    paths: list[Path] = []

    mat = fitz.Matrix(dpi / 72, dpi / 72)   # 72 DPI é o padrão PDF
    for i, page in enumerate(doc):
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
        p = output_dir / f"page_{i + 1:03d}.png"
        pix.save(str(p))
        paths.append(p)
        logger.debug(f"Página {i + 1} renderizada a {dpi} DPI: {p.name}")

    doc.close()
    logger.info(f"'{pdf_path.name}': {len(paths)} página(s) renderizada(s) a {dpi} DPI")
    return paths


def preprocess_for_ocr(image_path: Path) -> Path:
    """Pipeline completo de pré-processamento para OCR em formulários.

    Salva imagem processada ao lado da original (sufixo _proc).
    Retorna path da imagem processada (ou original se OpenCV indisponível).

    Passos:
      1. Carregar em escala de cinza
      2. Remover grade do formulário (linhas H e V)
      3. Binarização adaptativa (lida com iluminação irregular)
    """
    if not _OPENCV_OK:
        logger.warning("OpenCV indisponível — imagem original será usada no OCR")
        return image_path

    img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        logger.error(f"Não foi possível ler: {image_path}")
        return image_path

    # Remove grade do formulário
    sem_grade = _remover_grade(img)

    # Binarização adaptativa garante leitura em áreas com iluminação variada
    processed = cv2.adaptiveThreshold(
        sem_grade, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY,
        blockSize=15, C=4,
    )

    out_path = image_path.parent / f"proc_{image_path.name}"
    cv2.imwrite(str(out_path), processed)
    logger.debug(f"Pré-processamento OK: {out_path.name}")
    return out_path


def save_debug_image(image: "np.ndarray", output_path: Path) -> None:
    """Salva imagem intermediária para inspeção manual durante desenvolvimento."""
    if not _OPENCV_OK:
        return
    cv2.imwrite(str(output_path), image)
    logger.debug(f"Debug image salva: {output_path}")

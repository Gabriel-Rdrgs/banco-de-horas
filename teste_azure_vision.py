"""Teste do pipeline com Azure Computer Vision (Read API).

Pré-requisitos:
  1. Recurso "Computer Vision" criado no portal.azure.com (tier F0 - gratuito)
  2. Endpoint e Chave obtidos em "Chaves e Ponto de Extremidade"
  3. Definir as variáveis de ambiente abaixo no PowerShell:

     $env:AZURE_VISION_ENDPOINT = "https://provida-vision.cognitiveservices.azure.com/"
     $env:AZURE_VISION_KEY      = "SUA_CHAVE_AQUI"

  4. Executar: python teste_azure_vision.py

Free tier F0: 5.000 chamadas/mês. Estes 2 PDFs = 2 chamadas = R$0.
"""
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-8s %(name)s: %(message)s",
    stream=sys.stdout,
)

BASE = Path(__file__).parent

# --- Carregar configuração do .env ---
from src.config import cfg   # já carrega o .env automaticamente

# --- Verificar SDK ---
print("Verificando azure-ai-vision-imageanalysis...")
try:
    from azure.ai.vision.imageanalysis import ImageAnalysisClient  # noqa: F401
    print("SDK Azure OK")
except ImportError:
    print("[ERRO] SDK não instalado. Execute: pip install azure-ai-vision-imageanalysis")
    sys.exit(1)

# --- Verificar credenciais ---
if not cfg.azure_configurado:
    print(
        "\n[ERRO] Credenciais Azure não configuradas.\n\n"
        "Abra o arquivo .env na pasta 'banco de horas' e preencha:\n"
        "  AZURE_VISION_ENDPOINT=https://seu-recurso.cognitiveservices.azure.com/\n"
        "  AZURE_VISION_KEY=sua-chave-aqui\n"
    )
    sys.exit(1)

endpoint = cfg.azure_endpoint
key      = cfg.azure_key
print(f"Endpoint: {endpoint}")
print(f"Chave:    ...{key[-6:]}\n")

# --- Teste de conectividade ---
print("Testando conexão com Azure Vision API...")
from src.ocr.engine import AzureVisionEngine

engine = AzureVisionEngine(endpoint=endpoint, api_key=key)
try:
    client = engine._get_client()
    print("Conexão OK\n")
except Exception as e:
    print(f"[ERRO] {e}")
    sys.exit(1)

# --- Processar PDFs ---
from src.pipeline import processar_folha
from src.review.reviewer import gerar_csv_revisao

AMOSTRAS = [
    {
        "arquivo":     BASE / "amostras" / "MODELOS FOLHA DE PONTO AMANDA.pdf",
        "colaborador": "Amanda Curcino dos Santos",
        "competencia": "04/2026",
    },
    {
        "arquivo":     BASE / "amostras" / "MODELOS FOLHA DE PONTO EMANUELLY.pdf",
        "colaborador": "Emanuelly Ribeiro de Aguiar",
        "competencia": "05/2025",
    },
]

LIMIAR = 70.0
resultados = []

for amostra in AMOSTRAS:
    nome = amostra["colaborador"].split()[0]
    print(f"{'='*62}")
    print(f"Processando: {amostra['colaborador']} ({amostra['competencia']})")
    print(f"Engine: Azure Computer Vision (Read API)")
    print()

    folha, log = processar_folha(
        arquivo=amostra["arquivo"],
        colaborador=amostra["colaborador"],
        competencia=amostra["competencia"],
        usuario="TESTE_AZURE",
        motor_ocr="azure_vision",
        limiar_confianca=LIMIAR,
    )

    print(f"Status: {log.status}")
    print(f"Batidas extraídas: {len(folha.batidas)}")
    print(f"Confiança média: {folha.confianca_media:.1f}%")
    if log.mensagem_erro:
        print(f"ERRO: {log.mensagem_erro}")

    print()
    print("Data         Dia         Entrada  S.Alm   V.Alm   S.Tarde  Conf%  Status")
    print("-" * 80)
    for b in folha.batidas:
        def fmt(t):
            return t.strftime("%H:%M") if t else "  --  "
        print(
            f"{b.data.strftime('%d/%m/%Y')}  "
            f"{(b.dia_semana or '?')[:10]:<10} "
            f"{fmt(b.entrada_manha)}  "
            f"{fmt(b.saida_almoco)}  "
            f"{fmt(b.volta_almoco)}  "
            f"{fmt(b.saida_tarde)}  "
            f"{b.confianca:5.1f}  "
            f"{b.status_ocr}"
        )

    pendentes = folha.batidas_pendentes_revisao(LIMIAR)
    print(f"\nPendentes revisão humana: {len(pendentes)}")

    if pendentes:
        csv_path = gerar_csv_revisao(
            folha, limiar=LIMIAR, output_dir=BASE / "saida" / "revisao"
        )
        if csv_path:
            print(f"CSV gerado: {csv_path.name}")

    resultados.append({
        "nome": nome,
        "batidas": len(folha.batidas),
        "confianca": folha.confianca_media,
        "pendentes": len(pendentes),
        "status": log.status,
    })
    print()

# --- Resumo comparativo ---
print("=" * 62)
print("COMPARATIVO DE ENGINES")
print("=" * 62)
print(f"{'Engine':<18} {'Colaborador':<12} {'Batidas':>8} {'Confiança':>10} {'Revisão':>8}")
print("-" * 60)
refs = [
    ("Tesseract",    "Amanda",    18, 47.0, 15),
    ("Tesseract",    "Emanuelly", 20, 52.0, 14),
]
for r in refs:
    print(f"{r[0]:<18} {r[1]:<12} {r[2]:>8} {r[3]:>9.1f}% {r[4]:>8}")
for r in resultados:
    print(f"{'Azure Vision':<18} {r['nome']:<12} {r['batidas']:>8} {r['confianca']:>9.1f}% {r['pendentes']:>8}")
print()
print("Verifique saida/revisao/ para os CSVs gerados.")

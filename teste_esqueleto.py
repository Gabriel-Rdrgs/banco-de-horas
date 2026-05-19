"""Smoke test do esqueleto — valida modelos, parser e exportação sem OCR.

Execução: python teste_esqueleto.py
Não requer Tesseract nem OpenCV instalados.
"""
import sys
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

# --- 1. Modelos ---
print("\n[1] Testando modelos...")
from src.models.folha import BatidaDiaria, FolhaImportacao
from src.models.log import LogProcessamento, CampoRevisao
from datetime import date, time, datetime

batida = BatidaDiaria(
    colaborador="Amanda Curcino dos Santos",
    competencia="05/2026",
    data=date(2026, 5, 2),
    dia_semana="Sexta",
    entrada_manha=time(8, 0),
    saida_almoco=time(12, 0),
    volta_almoco=time(13, 0),
    saida_tarde=time(17, 0),
    status_ocr="OK",
    confianca=95.0,
)
assert batida.horarios_preenchidos() == 4
assert not batida.precisa_revisao()
print("   BatidaDiaria OK")

batida_ruim = BatidaDiaria(
    colaborador="Amanda Curcino dos Santos",
    competencia="05/2026",
    data=date(2026, 5, 5),
    dia_semana="Segunda",
    entrada_manha=None,
    saida_almoco=None,
    volta_almoco=None,
    saida_tarde=None,
    status_ocr="NAO_LIDO",
    confianca=30.0,
)
assert batida_ruim.precisa_revisao(limiar=70.0)
print("   BatidaDiaria (baixa confiança) OK")

# --- 2. Normalizer ---
print("\n[2] Testando normalizer...")
from src.parser.normalizer import parse_time, normalize_colaborador, normalize_competencia

assert parse_time("08:00") == time(8, 0)
assert parse_time("8h30")  == time(8, 30)
assert parse_time("O8:OO") == time(8, 0)   # O → 0
assert parse_time("")      is None
assert parse_time("abc")   is None
print("   parse_time OK")

assert normalize_competencia("5/2026")   == "05/2026"
assert normalize_competencia("05-2026")  == "05/2026"
assert normalize_competencia("05/26")    == "05/2026"
assert normalize_competencia("13/2026")  is None      # mês inválido
print("   normalize_competencia OK")

# --- 3. Validator ---
print("\n[3] Testando validator...")
from src.parser.validator import validate_batida, classify_status

erros = validate_batida(batida)
assert erros == [], f"Esperava sem erros, mas: {erros}"
print("   validate_batida (válida) OK")

batida_invalida = BatidaDiaria(
    colaborador="Teste",
    competencia="05/2026",
    data=date(2026, 5, 2),
    dia_semana="Sexta",
    entrada_manha=time(12, 0),
    saida_almoco=time(8, 0),   # saída antes da entrada — erro!
    volta_almoco=time(13, 0),
    saida_tarde=time(17, 0),
    status_ocr="INVALIDO",
    confianca=50.0,
)
erros = validate_batida(batida_invalida)
assert len(erros) > 0
print(f"   validate_batida (inválida) OK — {len(erros)} erro(s) detectado(s)")

# --- 4. Pipeline manual ---
print("\n[4] Testando pipeline manual (sem OCR)...")
from src.pipeline import processar_folha_manual

folha, log = processar_folha_manual(
    colaborador="Amanda Curcino dos Santos",
    competencia="05/2026",
    batidas_raw=[
        {"data": "02/05/2026", "dia_semana": "Sexta",
         "entrada_manha": "08:00", "saida_almoco": "12:00",
         "volta_almoco": "13:00", "saida_tarde": "17:00"},
        {"data": "05/05/2026", "dia_semana": "Segunda",
         "entrada_manha": "08:00", "saida_almoco": "12:00",
         "volta_almoco": "13:00", "saida_tarde": "17:00"},
    ],
    usuario="TESTE",
)
assert len(folha.batidas) == 2
assert folha.confianca_media == 100.0
assert log.status == "OK"
print(f"   processar_folha_manual OK — {len(folha.batidas)} batida(s), confiança {folha.confianca_media}%")

# --- 5. Review CSV ---
print("\n[5] Testando geração de CSV de revisão...")
from src.review.reviewer import gerar_csv_revisao

folha_com_problema, log2 = processar_folha_manual(
    colaborador="Amanda Curcino dos Santos",
    competencia="05/2026",
    batidas_raw=[
        {"data": "06/05/2026", "dia_semana": "Terça",
         "entrada_manha": None, "saida_almoco": None,
         "volta_almoco": None, "saida_tarde": None},
    ],
    usuario="TESTE",
)
# Força confiança baixa para acionar revisão
folha_com_problema.batidas[0].confianca = 40.0

csv_path = gerar_csv_revisao(folha_com_problema, limiar=70.0, output_dir=Path("saida/revisao"))
assert csv_path is not None and csv_path.exists()
print(f"   CSV de revisão gerado: {csv_path.name}")

# --- 6. Export dry_run ---
print("\n[6] Testando exportação dry_run (sem salvar planilha)...")
planilha = Path("planilha/BancoHoras_Provida_v2.xlsm")
if planilha.exists():
    from src.export.excel_writer import exportar_para_excel
    n = exportar_para_excel(planilha, folha, log, dry_run=True)
    print(f"   dry_run OK — {n} linha(s) seriam gravadas na planilha")
else:
    print("   Planilha não encontrada — pulando teste de exportação")

print("\n[OK] Todos os testes passaram. Esqueleto funcional.")

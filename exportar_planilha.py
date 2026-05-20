"""Exportação de folha de ponto para a planilha BancoHoras_Provida_v2.xlsm.

Fluxo:
  1. Lê o PDF via Azure Vision
  2. Mostra os dados extraídos para revisão visual
  3. Pergunta se deve gravar (dry_run por padrão)
  4. Grava nas abas BatidasOCR e ControleOCR sem tocar nas fórmulas

Uso:
  python exportar_planilha.py

O script lê as configurações do .env automaticamente.
"""
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.WARNING,           # silencia logs de infraestrutura
    format="%(levelname)s: %(message)s",
    stream=sys.stdout,
)

BASE = Path(__file__).parent

from src.config import cfg

# ── Verificação rápida de pré-requisitos ────────────────────────────────────

if not cfg.azure_configurado:
    print("[ERRO] Azure Vision não configurado. Verifique o arquivo .env.")
    sys.exit(1)

if not cfg.planilha_path.exists():
    print(f"[ERRO] Planilha não encontrada: {cfg.planilha_path}")
    sys.exit(1)

# ── Configuração da importação ───────────────────────────────────────────────

FOLHAS = [
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

LIMIAR = cfg.ocr_confianca_minima
USUARIO = cfg.ocr_usuario_padrao


def fmt(t):
    return t.strftime("%H:%M") if t else "  --  "


def exibir_resultado(folha, log):
    """Imprime tabela de batidas para inspeção antes de gravar."""
    status_icon = {"OK": "OK", "BAIXA_CONFIANCA": "??", "NAO_LIDO": "--", "INVALIDO": "!!"}

    print(f"\n  Colaborador : {folha.colaborador}")
    print(f"  Competência : {folha.competencia}")
    print(f"  Arquivo     : {folha.arquivo}")
    print(f"  Batidas     : {len(folha.batidas)}")
    print(f"  Confiança   : {folha.confianca_media:.1f}%")
    print(f"  Status OCR  : {log.status}")
    if log.mensagem_erro:
        print(f"  Erro        : {log.mensagem_erro}")

    print()
    print(f"  {'Data':<12} {'Dia':<10} {'Entrada':>7} {'S.Alm':>7} {'V.Alm':>7} {'S.Tarde':>7}  {'Conf':>5}  St")
    print(f"  {'-'*72}")

    for b in folha.batidas:
        icone = status_icon.get(b.status_ocr, "?")
        print(
            f"  {b.data.strftime('%d/%m/%Y'):<12}"
            f" {(b.dia_semana or '?')[:9]:<10}"
            f" {fmt(b.entrada_manha):>7}"
            f" {fmt(b.saida_almoco):>7}"
            f" {fmt(b.volta_almoco):>7}"
            f" {fmt(b.saida_tarde):>7}"
            f"  {b.confianca:>4.0f}%"
            f"  {icone}"
        )

    pendentes = folha.batidas_pendentes_revisao(LIMIAR)
    invalidas  = [b for b in folha.batidas if b.status_ocr == "INVALIDO"]

    print()
    if invalidas:
        print(f"  [!!] {len(invalidas)} batida(s) com horário inválido — serão marcadas como INVALIDO na planilha")
    if pendentes:
        print(f"  [??] {len(pendentes)} batida(s) com confiança abaixo de {LIMIAR:.0f}% — CSV de revisão será gerado")
    if not invalidas and not pendentes:
        print("  [OK] Todos os dados dentro dos critérios de confiança")


def confirmar(pergunta: str) -> bool:
    """Solicita confirmação S/N do usuário."""
    while True:
        resp = input(f"\n  {pergunta} [S/N]: ").strip().upper()
        if resp in ("S", "SIM", "Y", "YES"):
            return True
        if resp in ("N", "NAO", "NÃO", "NO"):
            return False
        print("  Responda S ou N.")


# ── Pipeline principal ───────────────────────────────────────────────────────

from src.pipeline import processar_folha
from src.export.excel_writer import exportar_para_excel
from src.review.reviewer import gerar_csv_revisao

print("=" * 60)
print("  EXPORTAÇÃO — Banco de Horas Provida Centro Médico")
print("=" * 60)
print(f"  Planilha : {cfg.planilha_path.name}")
print(f"  Engine   : {cfg.ocr_engine}")
print(f"  Folhas   : {len(FOLHAS)}")

resultados = []

for config_folha in FOLHAS:
    arquivo = config_folha["arquivo"]
    if not arquivo.exists():
        print(f"\n[AVISO] Arquivo não encontrado, pulando: {arquivo.name}")
        continue

    print(f"\n{'─'*60}")
    print(f"  Processando: {config_folha['colaborador']} ({config_folha['competencia']})")
    print(f"  Lendo PDF via {cfg.ocr_engine}...", end=" ", flush=True)

    folha, log = processar_folha(
        arquivo=arquivo,
        colaborador=config_folha["colaborador"],
        competencia=config_folha["competencia"],
        usuario=USUARIO,
        motor_ocr=cfg.ocr_engine,
        limiar_confianca=LIMIAR,
    )
    print("OK")

    exibir_resultado(folha, log)

    if log.status == "ERRO":
        print(f"\n  [ERRO] Pipeline falhou: {log.mensagem_erro}")
        print("  Esta folha não será gravada.")
        continue

    resultados.append((folha, log))

if not resultados:
    print("\nNenhuma folha processada com sucesso. Encerrando.")
    sys.exit(0)

# ── Dry-run ──────────────────────────────────────────────────────────────────

print(f"\n{'='*60}")
print("  DRY-RUN — Simulando gravação (planilha NÃO será alterada)")
print(f"{'='*60}")

for folha, log in resultados:
    n = exportar_para_excel(
        planilha_path=cfg.planilha_path,
        folha=folha,
        log=log,
        dry_run=True,
    )
    print(f"  {folha.colaborador}: {n} linha(s) seriam gravadas em BatidasOCR")

# ── Confirmação e gravação real ───────────────────────────────────────────────

print()
if not confirmar("Confirma a gravação REAL na planilha? Esta ação não pode ser desfeita"):
    print("\n  Operação cancelada. A planilha não foi alterada.")
    sys.exit(0)

print("\n  Gravando...")
for folha, log in resultados:
    # Gera CSV de revisão para campos com baixa confiança antes de gravar
    pendentes = folha.batidas_pendentes_revisao(LIMIAR)
    if pendentes:
        csv_path = gerar_csv_revisao(
            folha, limiar=LIMIAR, output_dir=BASE / "saida" / "revisao"
        )
        if csv_path:
            print(f"  CSV de revisão: {csv_path.name}")

    n = exportar_para_excel(
        planilha_path=cfg.planilha_path,
        folha=folha,
        log=log,
        dry_run=False,
    )
    print(f"  {folha.colaborador}: {n} linha(s) gravadas — OK")

print(f"\n{'='*60}")
print("  Exportação concluída.")
print(f"  Abra a planilha e verifique as abas BatidasOCR e ControleOCR.")
print(f"{'='*60}\n")

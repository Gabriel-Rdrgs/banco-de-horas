"""Banco de Horas — Provida Centro Médico
Interface web para importação de folhas de ponto e apuração automática.

Execução: python -m streamlit run app.py
"""
from __future__ import annotations

import subprocess
import tempfile
from datetime import time
from pathlib import Path
from typing import Optional
import re

import pandas as pd
import streamlit as st

# ── Configuração da página ───────────────────────────────────────────────────

st.set_page_config(
    page_title="Banco de Horas — Provida",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    [data-testid="stSidebar"] { background: #1E3A8A; }
    [data-testid="stSidebar"] * { color: #E2E8F0 !important; }

    [data-testid="metric-container"] {
        background: white;
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        padding: 1rem 1.2rem;
        box-shadow: 0 1px 3px rgba(0,0,0,.06);
    }
    .titulo { font-size:1.5rem; font-weight:700; color:#1E3A8A; margin-bottom:.2rem; }
    .subtitulo { font-size:.9rem; color:#64748B; margin-bottom:1.5rem; }
    .secao { font-size:1rem; font-weight:600; color:#1E293B; margin:1.5rem 0 .5rem 0;
             border-left:4px solid #1D4ED8; padding-left:10px; }
    .badge-ok    { background:#D1FAE5; color:#065F46; padding:2px 8px; border-radius:12px; font-size:.8rem; font-weight:600; }
    .badge-warn  { background:#FEF3C7; color:#92400E; padding:2px 8px; border-radius:12px; font-size:.8rem; font-weight:600; }
    .badge-error { background:#FEE2E2; color:#991B1B; padding:2px 8px; border-radius:12px; font-size:.8rem; font-weight:600; }
    .badge-gray  { background:#F1F5F9; color:#475569; padding:2px 8px; border-radius:12px; font-size:.8rem; font-weight:600; }
    .stButton > button[kind="primary"] { font-size:1rem; padding:.55rem 1.8rem; }
</style>
""", unsafe_allow_html=True)

# ── Config e módulos ─────────────────────────────────────────────────────────

from src.config import cfg
from src.apuracao import (
    ler_cadastro, nomes_cadastro, apurar_mes, td_to_hhmm, hhmm_to_td, ResultadoMes,
)

PLANILHA = cfg.planilha_path

# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### 🏥 Provida Centro Médico")
    st.markdown("**Banco de Horas**")
    st.markdown("---")
    pagina = st.radio(
        "Menu",
        ["📂  Ver Planilha", "📥  Importar Folha", "📊  Calcular Apuração"],
        label_visibility="collapsed",
    )
    st.markdown("---")
    st.caption(f"Engine: **{cfg.ocr_engine}**")
    st.caption(f"Confiança mínima: **{cfg.ocr_confianca_minima:.0f}%**")


# ── Helpers ──────────────────────────────────────────────────────────────────

def fmt_time(t: Optional[time]) -> str:
    return t.strftime("%H:%M") if t else ""


def parse_time_str(s: str) -> Optional[time]:
    s = str(s or "").strip()
    m = re.fullmatch(r"(\d{1,2}):([0-5]\d)", s)
    if not m:
        return None
    try:
        return time(int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


def abrir_excel(path: Path) -> None:
    """Abre o arquivo no Excel (Windows)."""
    subprocess.Popen(["cmd", "/c", "start", "", str(path)], shell=False)


# ═══════════════════════════════════════════════════════════════════════════
# PÁGINA 1 — VER PLANILHA (abre o Excel)
# ═══════════════════════════════════════════════════════════════════════════

if pagina == "📂  Ver Planilha":
    st.markdown('<p class="titulo">📂 Ver Planilha</p>', unsafe_allow_html=True)
    st.markdown('<p class="subtitulo">Abre a planilha BancoHoras_Provida_v2.xlsm diretamente no Excel</p>',
                unsafe_allow_html=True)

    if not PLANILHA.exists():
        st.error(f"Planilha não encontrada: `{PLANILHA}`")
        st.stop()

    st.info(
        f"A planilha será aberta no Excel com todas as abas disponíveis:\n\n"
        f"**BatidasOCR** · **ApuracaoAutomatica** · **Apuracao_Consolidada** · "
        f"**ControleOCR** · **Cadastro** · Dashboard · e mais."
    )

    if st.button("📂 Abrir no Excel", type="primary"):
        abrir_excel(PLANILHA)
        st.success(f"Abrindo **{PLANILHA.name}** no Excel...")

    st.markdown("---")
    st.caption(f"Caminho: `{PLANILHA}`")


# ═══════════════════════════════════════════════════════════════════════════
# PÁGINA 2 — IMPORTAR FOLHA
# ═══════════════════════════════════════════════════════════════════════════

elif pagina == "📥  Importar Folha":
    st.markdown('<p class="titulo">📥 Importar Folha de Ponto</p>', unsafe_allow_html=True)
    st.markdown('<p class="subtitulo">Upload PDF → OCR → revisão manual → gravar em BatidasOCR</p>',
                unsafe_allow_html=True)

    if not cfg.azure_configurado:
        st.error("Azure Vision não configurado. Verifique o arquivo `.env`.")
        st.stop()

    if not PLANILHA.exists():
        st.error(f"Planilha não encontrada: `{PLANILHA}`")
        st.stop()

    # ── Passo 1: Identificação ────────────────────────────────────────────
    st.markdown('<p class="secao">1. Identificação</p>', unsafe_allow_html=True)

    nomes = nomes_cadastro(PLANILHA)
    col1, col2 = st.columns([3, 2])
    with col1:
        colaborador = st.selectbox("Colaborador *", ["— selecione —"] + nomes)
    with col2:
        competencia_raw = st.text_input("Competência * (MM/AAAA)", placeholder="04/2026")

    comp_ok = bool(re.fullmatch(r"\d{2}/\d{4}", competencia_raw.strip()))
    collab_ok = colaborador != "— selecione —"

    # ── Passo 2: Upload ───────────────────────────────────────────────────
    st.markdown('<p class="secao">2. Arquivo PDF</p>', unsafe_allow_html=True)
    arquivo = st.file_uploader("Selecione a folha de ponto (PDF)", type=["pdf"])

    # ── Passo 3: Processar OCR ────────────────────────────────────────────
    pode_processar = arquivo and collab_ok and comp_ok

    if not pode_processar and arquivo:
        if not collab_ok:
            st.warning("Selecione o colaborador antes de processar.")
        if not comp_ok:
            st.warning("Informe a competência no formato MM/AAAA.")

    if pode_processar:
        if st.button("🔍 Processar OCR", type="primary"):
            with st.spinner(f"Lendo folha de {colaborador} via Azure Vision..."):
                from src.pipeline import processar_folha

                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(arquivo.read())
                    tmp_path = Path(tmp.name)

                folha, log = processar_folha(
                    arquivo=tmp_path,
                    colaborador=colaborador,
                    competencia=competencia_raw.strip(),
                    usuario=cfg.ocr_usuario_padrao,
                    motor_ocr=cfg.ocr_engine,
                    limiar_confianca=cfg.ocr_confianca_minima,
                )
                tmp_path.unlink(missing_ok=True)

            if log.status == "ERRO":
                st.error(f"Erro no OCR: {log.mensagem_erro}")
            else:
                n_ok = sum(1 for b in folha.batidas if b.status_ocr == "OK")
                n_rev = sum(1 for b in folha.batidas if b.precisa_revisao(cfg.ocr_confianca_minima))
                st.success(
                    f"OCR concluído — **{len(folha.batidas)}** dias extraídos | "
                    f"Confiança média: **{folha.confianca_media:.1f}%** | "
                    f"OK: {n_ok} | Revisar: {n_rev}"
                )
                st.session_state["folha_ocr"] = folha
                st.session_state["log_ocr"]   = log

    # ── Passo 4: Revisão e edição ─────────────────────────────────────────
    if "folha_ocr" in st.session_state:
        folha = st.session_state["folha_ocr"]

        st.markdown('<p class="secao">3. Revisão — corrija horários e classifique dias sem registro</p>',
                    unsafe_allow_html=True)
        st.caption(
            "✏️ **Horários:** clique para editar (HH:MM). Deixe em branco se não há registro.  |  "
            "📋 **Tipo:** selecione para dias sem horário — "
            "**Falta** desconta do banco, **Feriado / Férias / Folga / Atestado** não descontam."
        )

        _TIPOS_OPCOES = ["Normal", "Falta", "Feriado", "Férias", "Folga", "Atestado"]

        def tipo_inicial(b) -> str:
            """Determina o tipo padrão de um dia baseado nos dados do OCR."""
            tem_horario = any([b.entrada_manha, b.saida_almoco,
                               b.volta_almoco, b.saida_tarde])
            if tem_horario:
                return "Normal"
            dia_up = (b.dia_semana or "").upper()
            if "SÁBADO" in dia_up or "SABADO" in dia_up:
                return "Normal"   # Sábado sem dado é normal (a maioria não trabalha)
            if "DOMINGO" in dia_up:
                return "Normal"   # Domingo sem dado é normal
            obs_up = (b.observacoes or "").upper()
            if "FERIADO" in obs_up:
                return "Feriado"
            if "FÉRIAS" in obs_up or "FERIAS" in obs_up:
                return "Férias"
            if "FOLGA" in obs_up:
                return "Folga"
            if "ATESTADO" in obs_up:
                return "Atestado"
            # Dia útil sem horário → Falta por padrão
            return "Falta"

        dados = []
        for b in folha.batidas:
            tem_horario = any([b.entrada_manha, b.saida_almoco,
                               b.volta_almoco, b.saida_tarde])
            dados.append({
                "Data":           b.data.strftime("%d/%m/%Y"),
                "Dia":            b.dia_semana or "",
                "Tipo":           tipo_inicial(b),
                "Entrada":        fmt_time(b.entrada_manha),
                "Saída Almoço":   fmt_time(b.saida_almoco),
                "Volta Almoço":   fmt_time(b.volta_almoco),
                "Saída Tarde":    fmt_time(b.saida_tarde),
                "Conf.%":         round(b.confianca),
            })
        df_edit = pd.DataFrame(dados)

        col_config = {
            "Data":  st.column_config.TextColumn("Data",  disabled=True, width="small"),
            "Dia":   st.column_config.TextColumn("Dia",   disabled=True, width="medium"),
            "Tipo":  st.column_config.SelectboxColumn(
                "Tipo",
                options=_TIPOS_OPCOES,
                width="medium",
                help="Relevante apenas para dias SEM horários registrados. "
                     "Falta = desconta. Feriado / Férias / Folga / Atestado = não desconta.",
            ),
            "Entrada":      st.column_config.TextColumn("Entrada",      width="small",
                                help="HH:MM"),
            "Saída Almoço": st.column_config.TextColumn("Saída Almoço", width="small"),
            "Volta Almoço": st.column_config.TextColumn("Volta Almoço", width="small"),
            "Saída Tarde":  st.column_config.TextColumn("Saída Tarde",  width="small"),
            "Conf.%":       st.column_config.NumberColumn("Conf.%", disabled=True,
                                format="%d%%", width="small"),
        }

        df_editado = st.data_editor(
            df_edit,
            column_config=col_config,
            width="stretch",
            hide_index=True,
            num_rows="fixed",
            height=min(650, 55 + len(df_edit) * 37),
        )

        # ── Passo 5: Confirmar ────────────────────────────────────────────
        st.markdown('<p class="secao">4. Confirmar e gravar em BatidasOCR</p>',
                    unsafe_allow_html=True)

        n_pendentes = sum(1 for b in folha.batidas
                         if b.precisa_revisao(cfg.ocr_confianca_minima))
        if n_pendentes:
            st.warning(f"⚠️ {n_pendentes} dia(s) com confiança abaixo de "
                       f"{cfg.ocr_confianca_minima:.0f}% — verifique antes de confirmar.")

        col_btn, col_cancel = st.columns([2, 1])
        with col_btn:
            confirmar = st.button("✅ Confirmar e Gravar", type="primary")
        with col_cancel:
            if st.button("🗑️ Cancelar e recomeçar"):
                st.session_state.pop("folha_ocr", None)
                st.session_state.pop("log_ocr", None)
                st.rerun()

        if confirmar:
            # Aplica as edições do usuário às batidas
            for i, row in df_editado.iterrows():
                b = folha.batidas[i]
                b.entrada_manha  = parse_time_str(row["Entrada"])
                b.saida_almoco   = parse_time_str(row["Saída Almoço"])
                b.volta_almoco   = parse_time_str(row["Volta Almoço"])
                b.saida_tarde    = parse_time_str(row["Saída Tarde"])

                # Aplica o Tipo apenas para dias SEM horários
                # (dias com horário são tratados pela apuração normalmente)
                tipo = str(row.get("Tipo", "Normal"))
                tem_horario = any([b.entrada_manha, b.saida_almoco,
                                   b.volta_almoco, b.saida_tarde])
                if not tem_horario and tipo != "Normal":
                    # Feriado, Férias, Folga, Atestado → jornada zero (não desconta)
                    # Falta → observações vazias (apuração trata como falta automaticamente)
                    if tipo in ("Feriado", "Férias", "Folga", "Atestado"):
                        b.observacoes = f"tipo={tipo.upper().replace('Ê', 'E')}"
                    else:
                        b.observacoes = ""   # Falta — comportamento padrão da apuração

            folha.calcular_confianca_media()

            from src.export.excel_writer import exportar_para_excel
            log_final = st.session_state["log_ocr"]
            log_final.linhas_importadas = len(folha.batidas)
            log_final.confianca_media   = folha.confianca_media

            try:
                with st.spinner("Gravando em BatidasOCR..."):
                    exportar_para_excel(PLANILHA, folha, log_final, dry_run=False)
            except PermissionError:
                st.error(
                    "❌ **Planilha bloqueada pelo Excel.**\n\n"
                    "Feche o arquivo `BancoHoras_Provida_v2.xlsm` no Excel e tente novamente."
                )
                st.stop()

            st.success(
                f"✅ **{len(folha.batidas)} linhas** gravadas em BatidasOCR para "
                f"**{folha.colaborador}** / **{folha.competencia}**\n\n"
                f"Vá para **Calcular Apuração** para fechar o mês e limpar os dados de staging."
            )
            # Guarda referência para calcular apuração logo após
            st.session_state["collab_importado"] = folha.colaborador
            st.session_state["comp_importada"]   = folha.competencia
            st.session_state.pop("folha_ocr", None)
            st.session_state.pop("log_ocr", None)


# ═══════════════════════════════════════════════════════════════════════════
# PÁGINA 3 — CALCULAR APURAÇÃO
# ═══════════════════════════════════════════════════════════════════════════

elif pagina == "📊  Calcular Apuração":
    st.markdown('<p class="titulo">📊 Calcular Apuração Mensal</p>', unsafe_allow_html=True)
    st.markdown('<p class="subtitulo">Calcula saldo do mês a partir das batidas confirmadas e grava na Apuração Consolidada</p>',
                unsafe_allow_html=True)

    if not PLANILHA.exists():
        st.error(f"Planilha não encontrada: `{PLANILHA}`")
        st.stop()

    # Pré-preenche se vier da página de importação
    collab_default = st.session_state.get("collab_importado", "")
    comp_default   = st.session_state.get("comp_importada",   "")

    st.markdown('<p class="secao">Selecionar período</p>', unsafe_allow_html=True)
    col1, col2 = st.columns([3, 2])
    with col1:
        nomes = nomes_cadastro(PLANILHA)
        idx_default = (nomes.index(collab_default) + 1) if collab_default in nomes else 0
        colaborador_ap = st.selectbox("Colaborador", ["— selecione —"] + nomes,
                                       index=idx_default, key="ap_collab")
    with col2:
        competencia_ap = st.text_input("Competência (MM/AAAA)", value=comp_default,
                                        placeholder="04/2026", key="ap_comp")

    comp_ap_ok   = bool(re.fullmatch(r"\d{2}/\d{4}", competencia_ap.strip()))
    collab_ap_ok = colaborador_ap != "— selecione —"

    if collab_ap_ok and comp_ap_ok:
        if st.button("🔢 Calcular", type="primary"):
            import openpyxl
            from src.models.folha import BatidaDiaria

            wb = openpyxl.load_workbook(str(PLANILHA), read_only=True,
                                         keep_vba=True, data_only=True)
            ws_bat = wb["BatidasOCR"]

            def cell_to_time(v) -> Optional[time]:
                if v is None or v == "":
                    return None
                if isinstance(v, str):
                    return parse_time_str(v)
                if isinstance(v, float):
                    total_min = round(v * 24 * 60)
                    h, m = divmod(total_min, 60)
                    try:
                        return time(h % 24, m)
                    except Exception:
                        return None
                return None

            batidas_filtradas: list[BatidaDiaria] = []
            for row in ws_bat.iter_rows(min_row=3, values_only=True):
                if str(row[1] or "").strip() != colaborador_ap:
                    continue
                if str(row[2] or "").strip() != competencia_ap.strip():
                    continue

                data_v = row[3]
                if hasattr(data_v, "date"):
                    data_obj = data_v.date()
                elif isinstance(data_v, str):
                    from datetime import datetime as _dt
                    try:
                        data_obj = _dt.strptime(data_v, "%d/%m/%Y").date()
                    except Exception:
                        continue
                else:
                    continue

                batidas_filtradas.append(BatidaDiaria(
                    colaborador  = str(row[1]).strip(),
                    competencia  = str(row[2]).strip(),
                    data         = data_obj,
                    dia_semana   = str(row[4] or ""),
                    entrada_manha  = cell_to_time(row[5]),
                    saida_almoco   = cell_to_time(row[6]),
                    volta_almoco   = cell_to_time(row[7]),
                    saida_tarde    = cell_to_time(row[8]),
                    status_ocr     = str(row[13] or "NAO_LIDO"),
                    confianca      = float(row[14] or 0),
                    observacoes    = str(row[15] or ""),
                ))
            wb.close()

            if not batidas_filtradas:
                st.warning(
                    f"Nenhuma batida encontrada para **{colaborador_ap}** / "
                    f"**{competencia_ap}** em BatidasOCR.\n\n"
                    "Importe a folha primeiro na página **Importar Folha**."
                )
                st.stop()

            confianca_media = (sum(b.confianca for b in batidas_filtradas)
                               / len(batidas_filtradas))

            resultado: ResultadoMes = apurar_mes(
                batidas        = batidas_filtradas,
                planilha_path  = PLANILHA,
                colaborador    = colaborador_ap,
                competencia    = competencia_ap.strip(),
                confianca_media= confianca_media,
            )
            st.session_state["resultado_apuracao"] = resultado

    # ── Exibe resultado ───────────────────────────────────────────────────
    if "resultado_apuracao" in st.session_state:
        res: ResultadoMes = st.session_state["resultado_apuracao"]

        st.markdown('<p class="secao">Resultado calculado</p>', unsafe_allow_html=True)

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Dias úteis",       res.total_dias_uteis)
        c2.metric("Com batida",        res.dias_com_batida)
        c3.metric("Sem batida",        res.dias_sem_batida)
        c4.metric("Horas extras",      td_to_hhmm(res.horas_extras))
        c5.metric("Faltas / Atrasos",  td_to_hhmm(res.faltas_atrasos))

        saldo_td  = res.saldo_mes
        saldo_str = td_to_hhmm(saldo_td)
        delta_cor = "normal" if saldo_td.total_seconds() >= 0 else "inverse"
        st.metric("**Saldo do Mês**", saldo_str, delta=saldo_str, delta_color=delta_cor)

        # Detalhe por dia
        st.markdown('<p class="secao">Detalhe por dia</p>', unsafe_allow_html=True)
        rows_det = []
        for d in res.detalhes:
            rows_det.append({
                "Data":       d.data.strftime("%d/%m/%Y"),
                "Dia":        d.dia_semana,
                "Trabalhado": td_to_hhmm(d.hrs_trabalhadas) if d.hrs_trabalhadas else "--",
                "Jornada":    td_to_hhmm(d.jornada_esperada),
                "Diferença":  td_to_hhmm(d.diferenca) if d.diferenca is not None else "--",
            })

        def colorir_det(row):
            diff = row.get("Diferença", "--")
            if diff == "--":
                return [""] * len(row)
            if diff.startswith("-"):
                return ["background-color:#FFF1F2"] * len(row)
            if diff != "00:00":
                return ["background-color:#F0FDF4"] * len(row)
            return [""] * len(row)

        st.dataframe(
            pd.DataFrame(rows_det).style.apply(colorir_det, axis=1),
            width="stretch",
            hide_index=True,
            height=400,
        )

        # ── Gravar e limpar ───────────────────────────────────────────────
        st.markdown('<p class="secao">Gravar na Apuração Consolidada</p>',
                    unsafe_allow_html=True)

        st.info(
            "Após confirmar, o sistema:\n"
            "1. Grava o saldo do mês na **Apuração Consolidada**\n"
            "2. **Remove as linhas** correspondentes de **BatidasOCR** (staging limpo)"
        )

        col_btn2, col_warn = st.columns([2, 3])
        with col_btn2:
            gravar_btn = st.button("💾 Gravar e Limpar BatidasOCR", type="primary")
        with col_warn:
            st.caption("⚠️ Ação irreversível. As batidas serão removidas de BatidasOCR após gravação na Consolidada.")

        if gravar_btn:
            from src.export.consolidada_writer import gravar_apuracao
            from src.export.excel_writer import limpar_batidas

            try:
                with st.spinner("Gravando na Apuração Consolidada..."):
                    vals = gravar_apuracao(PLANILHA, res, dry_run=False)

                with st.spinner("Limpando BatidasOCR (staging)..."):
                    n_removidas = limpar_batidas(PLANILHA, res.colaborador, res.competencia)

            except PermissionError:
                st.error(
                    "❌ **Planilha bloqueada pelo Excel.**\n\n"
                    "Feche o arquivo `BancoHoras_Provida_v2.xlsm` no Excel e tente novamente. "
                    "Se a gravação na Consolidada já foi feita, a limpeza de BatidasOCR "
                    "pode ser feita na próxima sessão."
                )
                st.stop()
            except ValueError as e:
                st.error(str(e))
                st.stop()
            else:

                st.success(
                    f"✅ **Apuração gravada e BatidasOCR limpo!**\n\n"
                    f"**{res.colaborador}** · {res.competencia}\n\n"
                    f"| Saldo anterior | Horas extras | Faltas | Saldo mês | Saldo líquido |\n"
                    f"|---|---|---|---|---|\n"
                    f"| `{vals['saldo_ant']}` | `{vals['hrs_extras']}` | "
                    f"`{vals['faltas']}` | `{vals['saldo_mes']}` | **`{vals['saldo_liquido']}`** |\n\n"
                    f"🗑️ {n_removidas} linha(s) removidas de BatidasOCR."
                )

                # Limpa estado da sessão
                st.session_state.pop("resultado_apuracao", None)
                st.session_state.pop("collab_importado", None)
                st.session_state.pop("comp_importada", None)

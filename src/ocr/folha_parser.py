"""Parser específico para o layout da Folha de Ponto Individual da Provida.

Layout identificado nas amostras:
  Cabeçalho: EMPREGADO/NOME, FUNÇÃO, MÊS, ANO
  Tabela:    DATA | DIA DA SEMANA | ENTRADA_MANHÃ | SAÍDA_ALMOÇO |
             VOLTA_ALMOÇO | SAÍDA_TARDE | TOTAL HS | ASSINATURA

Estratégia de parsing:
  1. Quebrar texto em linhas
  2. Identificar linha de cabeçalho (nome/competência) por palavras-chave
  3. Identificar linhas de dados pela âncora DD/MM/AAAA no início
  4. Extrair horários por ordem de aparição na linha (HH:MM tokens)
  5. Classificar linhas FOLGA / DOMINGO / SÁBADO (sem horários)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, time
from typing import Optional

from src.parser.normalizer import parse_time, normalize_colaborador, normalize_competencia, time_to_str

logger = logging.getLogger(__name__)

# --- Padrões ---
_DATA_RE = re.compile(r"\b(\d{1,2})[/\.\-](\d{1,2})[/\.\-](\d{4})\b")
_TIME_RE = re.compile(r"\b([0-1]?\d|2[0-3])[:hH]([0-5]\d)\b")
_MES_ANO_RE = re.compile(r"\bm[eê]s\b.{0,20}?(\d{1,2}).{0,20}?ano.{0,20}?(\d{4})", re.IGNORECASE)

_DIAS_MAP = {
    "SEGUNDA": "Segunda", "TERCA": "Terça", "TERÇA": "Terça",
    "QUARTA": "Quarta", "QUINTA": "Quinta", "SEXTA": "Sexta",
    "SABADO": "Sábado", "SÁBADO": "Sábado", "DOMINGO": "Domingo",
}

_LINHAS_SEM_HORARIO = {"DOMINGO", "SÁBADO", "SABADO", "FOLGA", "FERIADO", "ATESTADO", "FERIAS", "FÉRIAS"}


@dataclass
class LinhaFolha:
    """Resultado de parsing de uma linha da tabela da folha de ponto."""
    data: Optional[date]
    dia_semana: Optional[str]
    entrada_manha: Optional[time]
    saida_almoco: Optional[time]
    volta_almoco: Optional[time]
    saida_tarde: Optional[time]
    tipo: str = "NORMAL"        # "NORMAL" | "FOLGA" | "DOMINGO" | "SABADO" | "DESCONHECIDO"
    linha_raw: str = ""
    confianca_horarios: float = 0.0


@dataclass
class CabecalhoFolha:
    """Metadados extraídos do cabeçalho da folha."""
    colaborador: Optional[str] = None
    competencia: Optional[str] = None   # "MM/AAAA"
    confianca: float = 0.0
    raw: str = ""


def _extrair_data(texto: str) -> Optional[date]:
    """Extrai DD/MM/AAAA do texto."""
    m = _DATA_RE.search(texto)
    if not m:
        return None
    try:
        dia, mes, ano = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return date(ano, mes, dia)
    except ValueError:
        return None


def _extrair_dia_semana(texto: str) -> Optional[str]:
    """Identifica o dia da semana no texto da linha."""
    texto_upper = texto.upper()
    for chave, nome in _DIAS_MAP.items():
        if chave in texto_upper:
            return nome
    return None


def _eh_linha_sem_horario(texto: str) -> Optional[str]:
    """Retorna tipo especial se a linha não deveria ter horários."""
    texto_upper = texto.upper()
    for marker in _LINHAS_SEM_HORARIO:
        if marker in texto_upper:
            return marker.replace("SÁBADO", "SABADO")
    return None


def _tokenizar_linha(texto: str) -> list[str]:
    """Divide linha em tokens separando data e dia do restante.

    Retorna lista de tokens candidatos a horário (após data + dia da semana).
    """
    # Remove a data (DD/MM/AAAA) do início
    texto_sem_data = _DATA_RE.sub("", texto).strip()

    # Remove o dia da semana
    for chave in _DIAS_MAP:
        padrao = re.compile(re.escape(chave) + r"[\-\s]*FEIRA", re.IGNORECASE)
        texto_sem_data = padrao.sub("", texto_sem_data)
        texto_sem_data = re.sub(chave, "", texto_sem_data, flags=re.IGNORECASE)

    # Tokeniza por espaços e caracteres de separação do formulário
    tokens = re.split(r"[\s|]+", texto_sem_data.strip())
    return [t.strip() for t in tokens if t.strip() and len(t.strip()) >= 3]


def _extrair_horarios(texto: str) -> tuple[list[Optional[time]], float]:
    """Extrai até 4 horários do texto usando parse_time() com correção de OCR.

    Estratégia:
      1. Tenta extrair tokens tipo HH:MM com regex clássico (alta confiança)
      2. Para cada token restante, tenta parse_time() permissivo (baixa confiança)
      3. Retorna lista de até 4 tempos (None onde não leu) + confiança média

    Retorna (lista_de_4_times_ou_none, confianca_0_a_100).
    """
    # Estratégia 1: regex clássico HH:MM (mais confiável)
    matches_classicos = list(_TIME_RE.finditer(texto))
    horarios_classicos: list[time] = []
    for m in matches_classicos[:4]:
        try:
            t = time(int(m.group(1)), int(m.group(2)))
            horarios_classicos.append(t)
        except ValueError:
            pass

    if len(horarios_classicos) >= 3:
        # Boa leitura clássica
        result: list[Optional[time]] = horarios_classicos[:4]
        while len(result) < 4:
            result.append(None)
        confianca = 85.0 if len(horarios_classicos) == 4 else 60.0
        return result, confianca

    # Estratégia 2: parse_time permissivo nos tokens da linha
    tokens = _tokenizar_linha(texto)
    horarios_permissivos: list[Optional[time]] = []
    sucessos = 0

    for token in tokens[:6]:    # máximo 6 tokens para evitar ler assinatura como horário
        if len(horarios_permissivos) >= 4:
            break
        t = parse_time(token)
        if t is not None:
            horarios_permissivos.append(t)
            sucessos += 1
        elif any(c.isdigit() for c in token):
            horarios_permissivos.append(None)   # token numérico mas ilegível

    while len(horarios_permissivos) < 4:
        horarios_permissivos.append(None)

    # Confiança: % de slots preenchidos, com penalidade por usar estratégia 2
    pct = sucessos / 4
    confianca = round(pct * 65.0, 1)   # máximo 65 para leituras permissivas

    return horarios_permissivos[:4], confianca


def parse_linha(linha: str) -> Optional[LinhaFolha]:
    """Tenta parsear uma linha de texto como linha de dados da folha.

    Retorna None se a linha não parecer uma linha de dados.
    """
    linha_limpa = linha.strip()
    if not linha_limpa or len(linha_limpa) < 8:
        return None

    data = _extrair_data(linha_limpa)
    if data is None:
        return None     # linhas de dados sempre começam com uma data

    dia_semana = _extrair_dia_semana(linha_limpa)
    tipo_especial = _eh_linha_sem_horario(linha_limpa)

    if tipo_especial:
        return LinhaFolha(
            data=data,
            dia_semana=dia_semana or tipo_especial.capitalize(),
            entrada_manha=None,
            saida_almoco=None,
            volta_almoco=None,
            saida_tarde=None,
            tipo=tipo_especial,
            linha_raw=linha_limpa,
            confianca_horarios=100.0,  # sem horário é o esperado nesse tipo
        )

    horarios, confianca = _extrair_horarios(linha_limpa)   # sempre lista de 4

    return LinhaFolha(
        data=data,
        dia_semana=dia_semana,
        entrada_manha=horarios[0],
        saida_almoco=horarios[1],
        volta_almoco=horarios[2],
        saida_tarde=horarios[3],
        tipo="NORMAL",
        linha_raw=linha_limpa,
        confianca_horarios=confianca,
    )


def parse_cabecalho(texto_pagina: str) -> CabecalhoFolha:
    """Extrai colaborador e competência do bloco de texto completo da página.

    Estratégia: busca por palavras-chave próximas do nome e do mês/ano.
    """
    cab = CabecalhoFolha(raw=texto_pagina[:500])

    # Competência: busca padrão "MÊS ... [número] ... ANO ... [número]"
    m_comp = _MES_ANO_RE.search(texto_pagina)
    if m_comp:
        comp = normalize_competencia(f"{m_comp.group(1)}/{m_comp.group(2)}")
        if comp:
            cab.competencia = comp
            cab.confianca += 40.0
            logger.debug(f"Competência encontrada: {comp}")
    else:
        # Fallback: busca padrão MM/AAAA diretamente
        m_alt = re.search(r"\b(\d{1,2})[/\-](\d{4})\b", texto_pagina)
        if m_alt:
            comp = normalize_competencia(f"{m_alt.group(1)}/{m_alt.group(2)}")
            if comp:
                cab.competencia = comp
                cab.confianca += 25.0

    # Colaborador: linha após palavras-chave "EMPREGADO" ou "NOME"
    linhas = texto_pagina.splitlines()
    for i, linha in enumerate(linhas):
        linha_up = linha.upper()
        if any(kw in linha_up for kw in ["EMPREGADO", "NOME DO EMPREGADO", "NOME:"]):
            # O nome pode estar na mesma linha (após ":") ou na próxima
            partes = linha.split(":", 1)
            candidato = partes[1].strip() if len(partes) > 1 else ""
            if not candidato and i + 1 < len(linhas):
                candidato = linhas[i + 1].strip()
            # Filtra linhas que são cabeçalhos da empresa
            if candidato and "PROVIDA" not in candidato.upper() and len(candidato) > 5:
                cab.colaborador = normalize_colaborador(candidato)
                cab.confianca += 40.0
                logger.debug(f"Colaborador encontrado: {cab.colaborador}")
                break

    return cab


def parse_pagina(texto_pagina: str) -> tuple[CabecalhoFolha, list[LinhaFolha]]:
    """Parser modo Tesseract: cada linha da tabela numa só linha de texto.

    Retorna (cabecalho, lista_de_linhas_de_dados).
    """
    cabecalho = parse_cabecalho(texto_pagina)
    linhas: list[LinhaFolha] = []

    for linha in texto_pagina.splitlines():
        resultado = parse_linha(linha)
        if resultado is not None:
            linhas.append(resultado)

    logger.info(f"Parse: {len(linhas)} linha(s) de dados extraída(s) para {cabecalho.colaborador or '?'}")
    return cabecalho, linhas


def _parse_bloco_azure(data: date, bloco: list[str]) -> LinhaFolha:
    """Extrai dia da semana e horários de um bloco de linhas de um mesmo dia.

    O Azure Vision retorna cada célula como linha separada, então um dia
    ocupa várias linhas: [data, dia_semana, time1, time2, time3, time4, assinatura].
    """
    dia_semana: Optional[str] = None
    horarios: list[time] = []
    tipo = "NORMAL"
    raw_parts: list[str] = []

    for linha in bloco:
        linha_limpa = linha.strip()
        if not linha_limpa:
            continue

        raw_parts.append(linha_limpa)

        # Pula a própria data
        if _DATA_RE.fullmatch(linha_limpa.strip()):
            continue

        # Tipo especial (SÁBADO, DOMINGO, FOLGA, FERIADO)
        tipo_esp = _eh_linha_sem_horario(linha_limpa)
        if tipo_esp:
            tipo = tipo_esp

        # Dia da semana (pode estar junto com o primeiro horário: "SEGUNDA-FEIRA 07:48")
        if dia_semana is None:
            ds = _extrair_dia_semana(linha_limpa)
            if ds:
                dia_semana = ds

        # Horários — Azure lê com alta precisão, usar regex clássico é suficiente
        for m in _TIME_RE.finditer(linha_limpa):
            if len(horarios) >= 4:
                break
            try:
                t = time(int(m.group(1)), int(m.group(2)))
                horarios.append(t)
            except ValueError:
                pass

    # Confiança por completude
    if tipo in _LINHAS_SEM_HORARIO:
        confianca = 95.0
    elif len(horarios) == 4:
        confianca = 92.0
    elif len(horarios) == 3:
        confianca = 75.0
    elif len(horarios) >= 1:
        confianca = 50.0
    else:
        confianca = 20.0

    while len(horarios) < 4:
        horarios.append(None)

    return LinhaFolha(
        data=data,
        dia_semana=dia_semana,
        entrada_manha=horarios[0],
        saida_almoco=horarios[1],
        volta_almoco=horarios[2],
        saida_tarde=horarios[3],
        tipo=tipo,
        linha_raw=" | ".join(raw_parts[:6]),
        confianca_horarios=confianca,
    )


def parse_pagina_azure(texto_pagina: str) -> tuple[CabecalhoFolha, list[LinhaFolha]]:
    """Parser modo Azure Vision: cada célula da tabela é uma linha separada.

    O Azure retorna texto preservando a estrutura de células — cada coluna da
    tabela (data, dia, horário1..4, assinatura) vem como linha distinta.
    Estratégia: agrupar linhas por data-âncora e extrair do bloco.
    """
    cabecalho = parse_cabecalho(texto_pagina)
    linhas_texto = texto_pagina.splitlines()

    # Localiza todos os índices onde há uma data
    indices_datas: list[tuple[int, date]] = []
    for i, linha in enumerate(linhas_texto):
        d = _extrair_data(linha)
        if d is not None:
            indices_datas.append((i, d))

    linhas_resultado: list[LinhaFolha] = []
    for g, (idx, data) in enumerate(indices_datas):
        proximo_idx = indices_datas[g + 1][0] if g + 1 < len(indices_datas) else len(linhas_texto)
        bloco = linhas_texto[idx:proximo_idx]
        lf = _parse_bloco_azure(data, bloco)
        linhas_resultado.append(lf)

    logger.info(
        f"Parse Azure: {len(linhas_resultado)} linha(s) para {cabecalho.colaborador or '?'}"
    )
    return cabecalho, linhas_resultado

"""
Validação e formatação de RG (Registro Geral).

Arquitetura preparada para validadores por UF:
  validadores/rg_sp.py  (implementado)
  validadores/rg_mg.py  (reservado)
  validadores/rg_rj.py  (reservado)

Quando a UF não tiver algoritmo, aplica validação estrutural.
"""

from __future__ import annotations

import re

from validadores import rg_mg, rg_rj, rg_sp

# Máscara de exibição: 99.999.999-9 (último pode ser X em SP)
RG_PLACEHOLDER = 'Ex.: 12.345.678-9'
RG_TAMANHO_MIN = 7
RG_TAMANHO_MAX = 9

_SEQ_OBVIAS = {
    '0000000', '1111111', '2222222', '3333333', '4444444',
    '5555555', '6666666', '7777777', '8888888', '9999999',
    '00000000', '11111111', '22222222', '33333333', '44444444',
    '55555555', '66666666', '77777777', '88888888', '99999999',
    '000000000', '111111111', '222222222', '333333333', '444444444',
    '555555555', '666666666', '777777777', '888888888', '999999999',
    '123456789', '987654321', '012345678', '876543210',
    '1234567', '12345678', '7654321', '87654321',
}

_VALIDADORES_UF = {
    'SP': rg_sp.validar,
    'MG': rg_mg.validar,
    'RJ': rg_rj.validar,
}


def rg_digits(valor):
    """Extrai dígitos e X (DV SP), sem pontuação. Máx. 9 posições."""
    if valor is None:
        return ''
    s = re.sub(r'[^0-9Xx]', '', str(valor).strip()).upper()
    return s[:RG_TAMANHO_MAX]


def sanitizar_rg(valor):
    """Remove pontos/hífen e devolve só o conteúdo sanitizado (ou '')."""
    return rg_digits(valor)


def format_rg(valor):
    """Formata RG no padrão 99.999.999-9 (aceita X no DV)."""
    s = rg_digits(valor)
    if not s:
        return ''
    if len(s) <= 2:
        return s
    if len(s) <= 5:
        return f'{s[:2]}.{s[2:]}'
    if len(s) <= 8:
        return f'{s[:2]}.{s[2:5]}.{s[5:]}'
    return f'{s[:2]}.{s[2:5]}.{s[5:8]}-{s[8:]}'


def _eh_sequencia_obvia(s):
    if not s:
        return True
    corpo = re.sub(r'[^0-9]', '', s)
    if not corpo:
        return True
    if corpo == corpo[0] * len(corpo):
        return True
    if s in _SEQ_OBVIAS or corpo in _SEQ_OBVIAS:
        return True
    if s.replace('X', '0') in _SEQ_OBVIAS:
        return True
    return False


def validar_rg_estrutural(valor):
    """
    Validação estrutural (sem algoritmo de UF):
    - 7 a 9 posições
    - somente dígitos (DV pode ser X)
    - rejeita sequências óbvias
    """
    s = rg_digits(valor)
    if not s:
        return False
    if len(s) < RG_TAMANHO_MIN or len(s) > RG_TAMANHO_MAX:
        return False
    corpo, dv = s[:-1], s[-1]
    if not corpo.isdigit():
        return False
    if not (dv.isdigit() or dv == 'X'):
        return False
    if _eh_sequencia_obvia(s):
        return False
    return True


def validar_rg_por_uf(valor, uf=None):
    """
    Aplica validador da UF quando disponível.
    Retorna:
      True / False  -> resultado do algoritmo da UF
      None          -> UF sem validador (usar estrutural)
    """
    s = rg_digits(valor)
    if not s:
        return False
    uf_norm = (uf or '').strip().upper()
    if not uf_norm:
        return None
    fn = _VALIDADORES_UF.get(uf_norm)
    if not fn:
        return None
    resultado = fn(s)
    # None = UF reservada / não implementada
    return resultado


def validar_rg(valor, uf=None, obrigatorio=False):
    """
    Valida RG. Se uf informada e houver algoritmo, usa-o;
    caso contrário, usa validação estrutural.
    """
    s = rg_digits(valor)
    if not s:
        return not obrigatorio
    if _eh_sequencia_obvia(s):
        return False
    por_uf = validar_rg_por_uf(s, uf)
    if por_uf is True:
        return True
    if por_uf is False:
        # SP clássico exige 9 posições; RGs mais curtos caem no estrutural
        if uf and str(uf).strip().upper() == 'SP' and len(s) == 9:
            return False
        return validar_rg_estrutural(s)
    return validar_rg_estrutural(s)


def validar_e_formatar_rg(valor, uf=None, obrigatorio=False):
    """
    Retorna (rg_sanitizado, None) ou (None, mensagem_erro).
    Armazena sem pontuação (apenas dígitos/X), conforme sanitização do projeto.
    """
    s = sanitizar_rg(valor)
    if not s:
        if obrigatorio:
            return None, 'Informe um RG válido.'
        return None, None
    if not validar_rg(s, uf=uf, obrigatorio=True):
        return None, 'Informe um RG válido.'
    return s, None

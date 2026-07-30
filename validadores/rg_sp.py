"""Validador de RG emitido pela SSP-SP."""

import re

_SEQ_INVALIDAS = {
    '123456789',
    '987654321',
    '012345678',
    '876543210',
}


def _normalizar(valor):
    if valor is None:
        return ''
    return re.sub(r'[^0-9Xx]', '', str(valor).strip()).upper()[:9]


def calcular_dv_sp(digitos8):
    """Calcula o dígito verificador do RG SP (0-9 ou X)."""
    d = re.sub(r'\D', '', str(digitos8 or ''))[:8]
    if len(d) != 8:
        return None
    soma = sum(int(d[i]) * (i + 2) for i in range(8))
    resto = soma % 11
    return 'X' if resto == 10 else str(resto)


def validar(valor):
    """
    Valida RG paulista clássico (9 posições: 8 dígitos + DV).
    Retorna True/False.
    """
    s = _normalizar(valor)
    if len(s) != 9:
        return False
    corpo, dv = s[:8], s[8]
    if not corpo.isdigit():
        return False
    if not (dv.isdigit() or dv == 'X'):
        return False
    if corpo == corpo[0] * 8:
        return False
    if s in _SEQ_INVALIDAS or s.replace('X', '0') in _SEQ_INVALIDAS:
        return False
    esperado = calcular_dv_sp(corpo)
    return esperado is not None and dv == esperado

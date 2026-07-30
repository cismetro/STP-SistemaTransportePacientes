"""
Cálculo centralizado de idade a partir da data de nascimento.

Única fonte oficial de idade no STP: nunca persistir no banco;
sempre derivar de data_nascimento em listagens e documentos.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional, Union

DataLike = Union[date, datetime, None]

DATA_NASCIMENTO_MINIMA = date(1850, 1, 1)


def data_ref_normalizada(data_ref: DataLike = None) -> date:
    ref = data_ref or date.today()
    if isinstance(ref, datetime):
        ref = ref.date()
    return ref


def idade_em_anos(data_nasc: DataLike, data_ref: DataLike = None) -> Optional[int]:
    """Idade completa em anos (int) ou None se sem data / data futura."""
    if not data_nasc:
        return None
    if isinstance(data_nasc, datetime):
        data_nasc = data_nasc.date()
    ref = data_ref_normalizada(data_ref)
    if data_nasc > ref:
        return None
    anos = ref.year - data_nasc.year
    if (ref.month, ref.day) < (data_nasc.month, data_nasc.day):
        anos -= 1
    return max(anos, 0)


def calcular_idade(data_nasc: DataLike, data_ref: DataLike = None) -> str:
    """Idade em anos como string numérica (cartão/folha) ou '—'."""
    anos = idade_em_anos(data_nasc, data_ref)
    return '—' if anos is None else str(anos)


def formatar_idade_exibir(data_nasc: DataLike, data_ref: DataLike = None) -> str:
    """
    Exibição amigável da idade (listagens):
    - anos completos: '45 anos'
    - menor de 1 ano: '8 meses' ou '20 dias'
    """
    if not data_nasc:
        return '—'
    if isinstance(data_nasc, datetime):
        data_nasc = data_nasc.date()
    ref = data_ref_normalizada(data_ref)
    if data_nasc > ref:
        return '—'
    anos = idade_em_anos(data_nasc, ref)
    if anos is None:
        return '—'
    if anos >= 1:
        return f'{anos} ano' if anos == 1 else f'{anos} anos'
    meses = (ref.year - data_nasc.year) * 12 + (ref.month - data_nasc.month)
    if ref.day < data_nasc.day:
        meses -= 1
    meses = max(meses, 0)
    if meses >= 1:
        return f'{meses} mês' if meses == 1 else f'{meses} meses'
    dias = (ref - data_nasc).days
    if dias <= 0:
        return '0 dias'
    return f'{dias} dia' if dias == 1 else f'{dias} dias'


def data_limite_por_idade(anos: int, data_ref: DataLike = None) -> date:
    """Data de nascimento máxima para ter pelo menos `anos` completos."""
    ref = data_ref_normalizada(data_ref)
    try:
        return ref.replace(year=ref.year - int(anos))
    except ValueError:
        return ref.replace(year=ref.year - int(anos), day=28)

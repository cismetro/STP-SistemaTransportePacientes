"""Validadores de documentos reutilizáveis do STP."""

from validadores.rg import (
    format_rg,
    rg_digits,
    sanitizar_rg,
    validar_e_formatar_rg,
    validar_rg,
    validar_rg_por_uf,
)
from validadores.idade import (
    DATA_NASCIMENTO_MINIMA,
    calcular_idade,
    formatar_idade_exibir,
    idade_em_anos,
)

__all__ = [
    'DATA_NASCIMENTO_MINIMA',
    'calcular_idade',
    'format_rg',
    'formatar_idade_exibir',
    'idade_em_anos',
    'rg_digits',
    'sanitizar_rg',
    'validar_e_formatar_rg',
    'validar_rg',
    'validar_rg_por_uf',
]

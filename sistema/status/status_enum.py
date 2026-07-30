#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de Transporte de Pacientes
Desenvolvido para a Prefeitura Municipal de Cosmópolis
Pode ser usado por terceiros autorizados

Enumerações de Status
Centraliza todos os status e constantes do sistema
"""

from enum import Enum
from typing import Dict, List, Tuple

class StatusAgendamento(Enum):
    """
    Status possíveis para agendamentos
    Sistema da Prefeitura Municipal de Cosmópolis
    """
    AGENDADO = 'agendado'
    CONFIRMADO = 'confirmado'
    EM_ANDAMENTO = 'em_andamento'
    CONCLUIDO = 'concluido'
    CANCELADO = 'cancelado'
    NAO_COMPARECEU = 'nao_compareceu'
    
    @classmethod
    def get_choices(cls) -> List[Tuple[str, str]]:
        """Retorna lista de tuplas (valor, label) para formulários"""
        return [
            (cls.AGENDADO.value, 'Agendado'),
            (cls.CONFIRMADO.value, 'Confirmado'),
            (cls.EM_ANDAMENTO.value, 'Em Andamento'),
            (cls.CONCLUIDO.value, 'Concluído'),
            (cls.CANCELADO.value, 'Cancelado'),
            (cls.NAO_COMPARECEU.value, 'Não Compareceu')
        ]
    
    @classmethod
    def get_display_name(cls, status: str) -> str:
        """Retorna nome para exibição do status"""
        mapping = {
            cls.AGENDADO.value: 'Agendado',
            cls.CONFIRMADO.value: 'Confirmado',
            cls.EM_ANDAMENTO.value: 'Em Andamento',
            cls.CONCLUIDO.value: 'Concluído',
            cls.CANCELADO.value: 'Cancelado',
            cls.NAO_COMPARECEU.value: 'Não Compareceu'
        }
        return mapping.get(status, status.title())
    
    @classmethod
    def get_css_class(cls, status: str) -> str:
        """Retorna classe CSS para estilização do status"""
        mapping = {
            cls.AGENDADO.value: 'status-agendado',
            cls.CONFIRMADO.value: 'status-confirmado',
            cls.EM_ANDAMENTO.value: 'status-em-andamento',
            cls.CONCLUIDO.value: 'status-concluido',
            cls.CANCELADO.value: 'status-cancelado',
            cls.NAO_COMPARECEU.value: 'status-nao-compareceu'
        }
        return mapping.get(status, 'status-default')
    
    @classmethod
    def get_color(cls, status: str) -> str:
        """Retorna cor para o status"""
        mapping = {
            cls.AGENDADO.value: '#ffc107',      # Amarelo - warning
            cls.CONFIRMADO.value: '#17a2b8',    # Azul - info
            cls.EM_ANDAMENTO.value: '#fd7e14',  # Laranja - primary
            cls.CONCLUIDO.value: '#28a745',     # Verde - success
            cls.CANCELADO.value: '#dc3545',     # Vermelho - danger
            cls.NAO_COMPARECEU.value: '#6c757d' # Cinza - secondary
        }
        return mapping.get(status, '#6c757d')
    
    @classmethod
    def is_active(cls, status: str) -> bool:
        """Verifica se o status indica agendamento ativo"""
        return status in [cls.AGENDADO.value, cls.CONFIRMADO.value, cls.EM_ANDAMENTO.value]
    
    @classmethod
    def is_finished(cls, status: str) -> bool:
        """Verifica se o status indica agendamento finalizado"""
        return status in [cls.CONCLUIDO.value, cls.CANCELADO.value, cls.NAO_COMPARECEU.value]
    
    @classmethod
    def can_edit(cls, status: str) -> bool:
        """Verifica se agendamento com este status pode ser editado"""
        return status in [cls.AGENDADO.value, cls.CONFIRMADO.value]
    
    @classmethod
    def can_cancel(cls, status: str) -> bool:
        """Verifica se agendamento com este status pode ser cancelado"""
        return status in [cls.AGENDADO.value, cls.CONFIRMADO.value]

class TipoAtendimento(Enum):
    """
    Tipos de atendimento médico
    """
    EXAME = 'exame'
    CONSULTA = 'consulta'
    PROCEDIMENTO = 'procedimento'
    RETORNO = 'retorno'
    CIRURGIA = 'cirurgia'
    FISIOTERAPIA = 'fisioterapia'
    QUIMIOTERAPIA = 'quimioterapia'
    RADIOTERAPIA = 'radioterapia'
    HEMODIALISE = 'hemodialise'
    
    @classmethod
    def get_choices(cls) -> List[Tuple[str, str]]:
        """Retorna lista de tuplas (valor, label) para formulários"""
        return [
            (cls.EXAME.value, 'Exame'),
            (cls.CONSULTA.value, 'Consulta Médica'),
            (cls.PROCEDIMENTO.value, 'Procedimento'),
            (cls.RETORNO.value, 'Retorno'),
            (cls.CIRURGIA.value, 'Cirurgia'),
            (cls.FISIOTERAPIA.value, 'Fisioterapia'),
            (cls.QUIMIOTERAPIA.value, 'Quimioterapia'),
            (cls.RADIOTERAPIA.value, 'Radioterapia'),
            (cls.HEMODIALISE.value, 'Hemodiálise')
        ]
    
    @classmethod
    def get_display_name(cls, tipo: str) -> str:
        """Retorna nome para exibição do tipo"""
        mapping = {
            cls.EXAME.value: 'Exame',
            cls.CONSULTA.value: 'Consulta Médica',
            cls.PROCEDIMENTO.value: 'Procedimento',
            cls.RETORNO.value: 'Retorno',
            cls.CIRURGIA.value: 'Cirurgia',
            cls.FISIOTERAPIA.value: 'Fisioterapia',
            cls.QUIMIOTERAPIA.value: 'Quimioterapia',
            cls.RADIOTERAPIA.value: 'Radioterapia',
            cls.HEMODIALISE.value: 'Hemodiálise'
        }
        return mapping.get(tipo, tipo.title())
    
    @classmethod
    def get_icon(cls, tipo: str) -> str:
        """Retorna ícone FontAwesome para o tipo"""
        mapping = {
            cls.EXAME.value: 'fas fa-microscope',
            cls.CONSULTA.value: 'fas fa-user-md',
            cls.PROCEDIMENTO.value: 'fas fa-procedures',
            cls.RETORNO.value: 'fas fa-redo',
            cls.CIRURGIA.value: 'fas fa-cut',
            cls.FISIOTERAPIA.value: 'fas fa-running',
            cls.QUIMIOTERAPIA.value: 'fas fa-syringe',
            cls.RADIOTERAPIA.value: 'fas fa-radiation',
            cls.HEMODIALISE.value: 'fas fa-heartbeat'
        }
        return mapping.get(tipo, 'fas fa-calendar-check')
    
    @classmethod
    def requires_return(cls, tipo: str) -> bool:
        """Verifica se o tipo geralmente requer agendamento de retorno"""
        return tipo in [cls.CIRURGIA.value, cls.QUIMIOTERAPIA.value, cls.RADIOTERAPIA.value, cls.HEMODIALISE.value]

class PrioridadeAgendamento(Enum):
    """
    Prioridades de agendamento
    """
    BAIXA = 'baixa'
    NORMAL = 'normal'
    ALTA = 'alta'
    URGENTE = 'urgente'
    
    @classmethod
    def get_choices(cls) -> List[Tuple[str, str]]:
        """Retorna lista de tuplas (valor, label) para formulários"""
        return [
            (cls.BAIXA.value, 'Baixa'),
            (cls.NORMAL.value, 'Normal'),
            (cls.ALTA.value, 'Alta'),
            (cls.URGENTE.value, 'Urgente')
        ]
    
    @classmethod
    def get_display_name(cls, prioridade: str) -> str:
        """Retorna nome para exibição da prioridade"""
        mapping = {
            cls.BAIXA.value: 'Baixa',
            cls.NORMAL.value: 'Normal',
            cls.ALTA.value: 'Alta',
            cls.URGENTE.value: 'Urgente'
        }
        return mapping.get(prioridade, prioridade.title())
    
    @classmethod
    def get_color(cls, prioridade: str) -> str:
        """Retorna cor para a prioridade"""
        mapping = {
            cls.BAIXA.value: '#6c757d',     # Cinza
            cls.NORMAL.value: '#17a2b8',    # Azul
            cls.ALTA.value: '#ffc107',      # Amarelo
            cls.URGENTE.value: '#dc3545'    # Vermelho
        }
        return mapping.get(prioridade, '#17a2b8')
    
    @classmethod
    def get_order_value(cls, prioridade: str) -> int:
        """Retorna valor numérico para ordenação (maior = mais prioritário)"""
        mapping = {
            cls.BAIXA.value: 1,
            cls.NORMAL.value: 2,
            cls.ALTA.value: 3,
            cls.URGENTE.value: 4
        }
        return mapping.get(prioridade, 2)

class TipoUsuario(Enum):
    """
    Tipos de usuário do sistema
    """
    ADMIN = 'admin'
    OPERADOR = 'operador'
    CONSULTA = 'consulta'
    
    @classmethod
    def get_choices(cls) -> List[Tuple[str, str]]:
        """Retorna lista de tuplas (valor, label) para formulários"""
        return [
            (cls.ADMIN.value, 'Administrador'),
            (cls.OPERADOR.value, 'Operador'),
            (cls.CONSULTA.value, 'Consulta')
        ]
    
    @classmethod
    def get_display_name(cls, tipo: str) -> str:
        """Retorna nome para exibição do tipo"""
        mapping = {
            cls.ADMIN.value: 'Administrador',
            cls.OPERADOR.value: 'Operador',
            cls.CONSULTA.value: 'Consulta'
        }
        return mapping.get(tipo, tipo.title())
    
    @classmethod
    def get_description(cls, tipo: str) -> str:
        """Retorna descrição das permissões do tipo"""
        mapping = {
            cls.ADMIN.value: 'Acesso total ao sistema, incluindo gerenciamento de usuários',
            cls.OPERADOR.value: 'Acesso a operações do dia a dia, criação e edição de agendamentos',
            cls.CONSULTA.value: 'Acesso apenas para visualização e relatórios'
        }
        return mapping.get(tipo, '')

class TipoVeiculo(Enum):
    """
    Tipos de veículo
    """
    VAN = 'van'
    MICRO_ONIBUS = 'micro_onibus'
    AMBULANCIA = 'ambulancia'
    VEICULO_COMUM = 'veiculo_comum'
    
    @classmethod
    def get_choices(cls) -> List[Tuple[str, str]]:
        """Retorna lista de tuplas (valor, label) para formulários"""
        return [
            (cls.VAN.value, 'Van'),
            (cls.MICRO_ONIBUS.value, 'Micro-ônibus'),
            (cls.AMBULANCIA.value, 'Ambulância'),
            (cls.VEICULO_COMUM.value, 'Veículo Comum')
        ]
    
    @classmethod
    def get_display_name(cls, tipo: str) -> str:
        """Retorna nome para exibição do tipo"""
        mapping = {
            cls.VAN.value: 'Van',
            cls.MICRO_ONIBUS.value: 'Micro-ônibus',
            cls.AMBULANCIA.value: 'Ambulância',
            cls.VEICULO_COMUM.value: 'Veículo Comum'
        }
        return mapping.get(tipo, tipo.replace('_', ' ').title())
    
    @classmethod
    def get_icon(cls, tipo: str) -> str:
        """Retorna ícone FontAwesome para o tipo"""
        mapping = {
            cls.VAN.value: 'fas fa-shuttle-van',
            cls.MICRO_ONIBUS.value: 'fas fa-bus',
            cls.AMBULANCIA.value: 'fas fa-ambulance',
            cls.VEICULO_COMUM.value: 'fas fa-car'
        }
        return mapping.get(tipo, 'fas fa-car')
    
    @classmethod
    def get_capacity_range(cls, tipo: str) -> Tuple[int, int]:
        """Retorna faixa de capacidade típica para o tipo (min, max)"""
        mapping = {
            cls.VAN.value: (8, 15),
            cls.MICRO_ONIBUS.value: (16, 30),
            cls.AMBULANCIA.value: (1, 4),
            cls.VEICULO_COMUM.value: (4, 7)
        }
        return mapping.get(tipo, (1, 10))

class TipoVinculo(Enum):
    """
    Tipos de vínculo do motorista
    """
    FUNCIONARIO = 'funcionario'
    TERCEIRIZADO = 'terceirizado'
    VOLUNTARIO = 'voluntario'
    
    @classmethod
    def get_choices(cls) -> List[Tuple[str, str]]:
        """Retorna lista de tuplas (valor, label) para formulários"""
        return [
            (cls.FUNCIONARIO.value, 'Funcionário'),
            (cls.TERCEIRIZADO.value, 'Terceirizado'),
            (cls.VOLUNTARIO.value, 'Voluntário')
        ]
    
    @classmethod
    def get_display_name(cls, vinculo: str) -> str:
        """Retorna nome para exibição do vínculo"""
        mapping = {
            cls.FUNCIONARIO.value: 'Funcionário',
            cls.TERCEIRIZADO.value: 'Terceirizado',
            cls.VOLUNTARIO.value: 'Voluntário'
        }
        return mapping.get(vinculo, vinculo.title())

class CategoriaCNH(Enum):
    """
    Categorias da CNH
    """
    A = 'A'
    B = 'B'
    C = 'C'
    D = 'D'
    E = 'E'
    AB = 'AB'
    AC = 'AC'
    AD = 'AD'
    AE = 'AE'
    ACC = 'ACC'
    
    @classmethod
    def get_choices(cls) -> List[Tuple[str, str]]:
        """Retorna lista de tuplas (valor, label) para formulários"""
        return [
            (cls.A.value, 'A - Motocicletas'),
            (cls.B.value, 'B - Automóveis'),
            (cls.C.value, 'C - Veículos de Carga'),
            (cls.D.value, 'D - Transporte de Passageiros'),
            (cls.E.value, 'E - Veículos Articulados'),
            (cls.AB.value, 'AB - A + B (Moto e Auto)'),
            (cls.AC.value, 'AC - A + C (Moto e Carga)'),
            (cls.AD.value, 'AD - A + D (Moto e Passageiros)'),
            (cls.AE.value, 'AE - A + E (Moto e Articulados)'),
            (cls.ACC.value, 'ACC - Ciclomotor')
        ]
    
    @classmethod
    def get_display_name(cls, categoria: str) -> str:
        """Retorna nome para exibição da categoria"""
        mapping = {
            cls.A.value: 'A - Motocicletas',
            cls.B.value: 'B - Automóveis',
            cls.C.value: 'C - Veículos de Carga',
            cls.D.value: 'D - Transporte de Passageiros',
            cls.E.value: 'E - Veículos Articulados',
            cls.AB.value: 'AB - Moto + Auto',
            cls.AC.value: 'AC - Moto + Carga',
            cls.AD.value: 'AD - Moto + Passageiros',
            cls.AE.value: 'AE - Moto + Articulados',
            cls.ACC.value: 'ACC - Ciclomotor'
        }
        return mapping.get(categoria, categoria)
    
    @classmethod
    def can_drive_vehicle(cls, categoria_cnh: str, tipo_veiculo: str) -> bool:
        """Verifica se categoria CNH permite dirigir tipo de veículo"""
        permissions = {
            cls.A.value: [],
            cls.B.value: [TipoVeiculo.VEICULO_COMUM.value, TipoVeiculo.AMBULANCIA.value],
            cls.C.value: [TipoVeiculo.VEICULO_COMUM.value, TipoVeiculo.AMBULANCIA.value, TipoVeiculo.VAN.value],
            cls.D.value: [TipoVeiculo.VEICULO_COMUM.value, TipoVeiculo.AMBULANCIA.value, TipoVeiculo.VAN.value, TipoVeiculo.MICRO_ONIBUS.value],
            cls.E.value: [TipoVeiculo.VEICULO_COMUM.value, TipoVeiculo.AMBULANCIA.value, TipoVeiculo.VAN.value, TipoVeiculo.MICRO_ONIBUS.value],
            cls.AB.value: [TipoVeiculo.VEICULO_COMUM.value, TipoVeiculo.AMBULANCIA.value],
            cls.AC.value: [TipoVeiculo.VEICULO_COMUM.value, TipoVeiculo.AMBULANCIA.value, TipoVeiculo.VAN.value],
            cls.AD.value: [TipoVeiculo.VEICULO_COMUM.value, TipoVeiculo.AMBULANCIA.value, TipoVeiculo.VAN.value, TipoVeiculo.MICRO_ONIBUS.value],
            cls.AE.value: [TipoVeiculo.VEICULO_COMUM.value, TipoVeiculo.AMBULANCIA.value, TipoVeiculo.VAN.value, TipoVeiculo.MICRO_ONIBUS.value],
            cls.ACC.value: []
        }
        return tipo_veiculo in permissions.get(categoria_cnh, [])

class TipoCombustivel(Enum):
    """
    Tipos de combustível
    """
    GASOLINA = 'gasolina'
    ETANOL = 'etanol'
    DIESEL = 'diesel'
    FLEX = 'flex'
    GNV = 'gnv'
    ELETRICO = 'eletrico'
    HIBRIDO = 'hibrido'
    
    @classmethod
    def get_choices(cls) -> List[Tuple[str, str]]:
        """Retorna lista de tuplas (valor, label) para formulários"""
        return [
            (cls.GASOLINA.value, 'Gasolina'),
            (cls.ETANOL.value, 'Etanol'),
            (cls.DIESEL.value, 'Diesel'),
            (cls.FLEX.value, 'Flex (Gasolina/Etanol)'),
            (cls.GNV.value, 'GNV'),
            (cls.ELETRICO.value, 'Elétrico'),
            (cls.HIBRIDO.value, 'Híbrido')
        ]
    
    @classmethod
    def get_display_name(cls, combustivel: str) -> str:
        """Retorna nome para exibição do combustível"""
        mapping = {
            cls.GASOLINA.value: 'Gasolina',
            cls.ETANOL.value: 'Etanol',
            cls.DIESEL.value: 'Diesel',
            cls.FLEX.value: 'Flex',
            cls.GNV.value: 'GNV',
            cls.ELETRICO.value: 'Elétrico',
            cls.HIBRIDO.value: 'Híbrido'
        }
        return mapping.get(combustivel, combustivel.title())

# === FUNÇÕES UTILITÁRIAS ===

def get_all_status_choices() -> Dict[str, List[Tuple[str, str]]]:
    """
    Retorna todas as escolhas de status organizadas por categoria
    """
    return {
        'agendamento': StatusAgendamento.get_choices(),
        'atendimento': TipoAtendimento.get_choices(),
        'prioridade': PrioridadeAgendamento.get_choices(),
        'usuario': TipoUsuario.get_choices(),
        'veiculo': TipoVeiculo.get_choices(),
        'vinculo': TipoVinculo.get_choices(),
        'cnh': CategoriaCNH.get_choices(),
        'combustivel': TipoCombustivel.get_choices()
    }

def get_status_colors() -> Dict[str, str]:
    """
    Retorna mapeamento de cores para todos os status
    """
    colors = {}
    
    # Status de agendamento
    for status in StatusAgendamento:
        colors[f'agendamento_{status.value}'] = StatusAgendamento.get_color(status.value)
    
    # Prioridades
    for prioridade in PrioridadeAgendamento:
        colors[f'prioridade_{prioridade.value}'] = PrioridadeAgendamento.get_color(prioridade.value)
    
    return colors

def validate_status_transition(current_status: str, new_status: str) -> bool:
    """
    Valida se a transição de status é permitida
    """
    # Definir transições válidas para agendamentos
    valid_transitions = {
        StatusAgendamento.AGENDADO.value: [
            StatusAgendamento.CONFIRMADO.value,
            StatusAgendamento.CANCELADO.value,
            StatusAgendamento.NAO_COMPARECEU.value
        ],
        StatusAgendamento.CONFIRMADO.value: [
            StatusAgendamento.EM_ANDAMENTO.value,
            StatusAgendamento.CANCELADO.value,
            StatusAgendamento.NAO_COMPARECEU.value
        ],
        StatusAgendamento.EM_ANDAMENTO.value: [
            StatusAgendamento.CONCLUIDO.value,
            StatusAgendamento.CANCELADO.value
        ],
        StatusAgendamento.CONCLUIDO.value: [],  # Status final
        StatusAgendamento.CANCELADO.value: [],  # Status final
        StatusAgendamento.NAO_COMPARECEU.value: []  # Status final
    }
    
    return new_status in valid_transitions.get(current_status, [])

def get_next_possible_status(current_status: str) -> List[str]:
    """
    Retorna os próximos status possíveis para o status atual
    """
    transitions = {
        StatusAgendamento.AGENDADO.value: [StatusAgendamento.CONFIRMADO.value],
        StatusAgendamento.CONFIRMADO.value: [StatusAgendamento.EM_ANDAMENTO.value],
        StatusAgendamento.EM_ANDAMENTO.value: [StatusAgendamento.CONCLUIDO.value]
    }
    
    return transitions.get(current_status, [])

def get_urgency_level(prioridade: str, data_agendamento) -> str:
    """
    Calcula nível de urgência baseado na prioridade e proximidade da data
    """
    from datetime import date, timedelta
    
    hoje = date.today()
    
    if isinstance(data_agendamento, str):
        from datetime import datetime
        data_agendamento = datetime.strptime(data_agendamento, '%Y-%m-%d').date()
    
    dias_restantes = (data_agendamento - hoje).days
    
    # Se é urgente ou alta prioridade
    if prioridade in [PrioridadeAgendamento.URGENTE.value, PrioridadeAgendamento.ALTA.value]:
        return 'alta'
    
    # Se é para hoje ou amanhã
    if dias_restantes <= 1:
        return 'alta'
    
    # Se é para os próximos 3 dias
    if dias_restantes <= 3:
        return 'media'
    
    return 'baixa'

# === CONFIGURAÇÕES DO SISTEMA ===

class ConfiguracaoSistema:
    """
    Configurações padrão do sistema
    Prefeitura Municipal de Cosmópolis
    """
    
    # Horários de funcionamento
    HORARIO_INICIO_PADRAO = '06:00'
    HORARIO_FIM_PADRAO = '18:00'
    
    # Dias de funcionamento (0=Segunda, 6=Domingo)
    DIAS_FUNCIONAMENTO = [0, 1, 2, 3, 4]  # Segunda a Sexta
    
    # Intervalos de agendamento (em minutos)
    INTERVALO_AGENDAMENTO = 30
    
    # Antecedência mínima para agendamento (em horas)
    ANTECEDENCIA_MINIMA = 24
    
    # Tempo máximo de viagem (em minutos)
    TEMPO_VIAGEM_MAXIMO = 480  # 8 horas
    
    # Capacidades máximas
    CAPACIDADE_MAXIMA_VEICULO = 50
    CAPACIDADE_MAXIMA_CADEIRANTES = 4
    
    # Quilometragem para revisão
    KM_PARA_REVISAO = 10000
    DIAS_PARA_REVISAO = 180
    
    # Alertas de vencimento
    DIAS_ALERTA_CNH = 30
    DIAS_ALERTA_LICENCIAMENTO = 30
    DIAS_ALERTA_SEGURO = 15
    
    @classmethod
    def get_horarios_disponiveis(cls) -> List[str]:
        """Retorna lista de horários disponíveis para agendamento"""
        from datetime import datetime, timedelta
        
        inicio = datetime.strptime(cls.HORARIO_INICIO_PADRAO, '%H:%M')
        fim = datetime.strptime(cls.HORARIO_FIM_PADRAO, '%H:%M')
        intervalo = timedelta(minutes=cls.INTERVALO_AGENDAMENTO)
        
        horarios = []
        atual = inicio
        
        while atual <= fim:
            horarios.append(atual.strftime('%H:%M'))
            atual += intervalo
        
        return horarios
    
    @classmethod
    def is_dia_funcionamento(cls, data) -> bool:
        """Verifica se a data é dia de funcionamento"""
        if isinstance(data, str):
            from datetime import datetime
            data = datetime.strptime(data, '%Y-%m-%d').date()
        
        return data.weekday() in cls.DIAS_FUNCIONAMENTO
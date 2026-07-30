#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de Transporte de Pacientes
Desenvolvido para a Prefeitura Municipal de Cosmópolis
Pode ser usado por terceiros autorizados

Modelo: Veículo
Representa os veículos cadastrados no sistema
"""

from datetime import datetime, date
from sqlalchemy import Column, Integer, String, Text, Date, DateTime, Boolean, Float
from sqlalchemy.orm import validates, relationship
from sqlalchemy.ext.hybrid import hybrid_property
import re

from db.database import db

class Veiculo(db.Model):
    """
    Modelo de Veículo
    Sistema da Prefeitura Municipal de Cosmópolis
    
    Representa um veículo cadastrado no sistema de transporte de pacientes
    """
    
    __tablename__ = 'veiculos'
    
    # === CAMPOS PRINCIPAIS ===
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Identificação do veículo
    placa = Column(String(8), unique=True, nullable=False, index=True)
    renavam = Column(String(20), unique=True, nullable=False, index=True)
    chassi = Column(String(30), unique=True, nullable=False)
    
    # Dados do veículo
    marca = Column(String(50), nullable=False)
    modelo = Column(String(100), nullable=False)
    ano_fabricacao = Column(Integer, nullable=False)
    ano_modelo = Column(Integer, nullable=False)
    cor = Column(String(30), nullable=False)
    combustivel = Column(String(20), nullable=False)  # gasolina, etanol, diesel, flex, gnv
    
    # Características técnicas
    tipo_veiculo = Column(String(20), nullable=False)  # van, micro_onibus, ambulancia, veiculo_comum
    capacidade_passageiros = Column(Integer, nullable=False)
    capacidade_cadeirantes = Column(Integer, default=0, nullable=False)
    ar_condicionado = Column(Boolean, default=False, nullable=False)
    acessibilidade_total = Column(Boolean, default=False, nullable=False)
    elevador_cadeirante = Column(Boolean, default=False, nullable=False)
    maca = Column(Boolean, default=False, nullable=False)
    
    # Documentação
    data_licenciamento = Column(Date, nullable=False, index=True)
    data_vencimento_licenciamento = Column(Date, nullable=False, index=True)
    seguro_vigente = Column(Boolean, default=False, nullable=False)
    data_vencimento_seguro = Column(Date, nullable=True, index=True)
    seguradora = Column(String(100), nullable=True)
    numero_apolice = Column(String(50), nullable=True)
    
    # Informações técnicas
    quilometragem_atual = Column(Integer, default=0, nullable=False)
    consumo_medio = Column(Float, nullable=True)  # km/l
    capacidade_tanque = Column(Float, nullable=True)  # litros
    
    # Manutenção
    data_ultima_revisao = Column(Date, nullable=True)
    quilometragem_ultima_revisao = Column(Integer, nullable=True)
    proxima_revisao_km = Column(Integer, nullable=True)
    proxima_revisao_data = Column(Date, nullable=True)
    
    # Status operacional
    ativo = Column(Boolean, default=True, nullable=False, index=True)
    disponivel = Column(Boolean, default=True, nullable=False, index=True)
    em_manutencao = Column(Boolean, default=False, nullable=False, index=True)
    motivo_indisponibilidade = Column(String(200), nullable=True)
    
    # Observações e controle
    observacoes = Column(Text, nullable=True)
    numero_patrimonio = Column(String(20), nullable=True, unique=True)  # Número do patrimônio da prefeitura
    
    # Timestamps
    data_cadastro = Column(DateTime, default=datetime.utcnow, nullable=False)
    data_atualizacao = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # === RELACIONAMENTOS ===
    # Um veículo pode ter vários agendamentos
    agendamentos = relationship('Agendamento', backref='veiculo', lazy='dynamic', cascade='all, delete-orphan')
    
    # === PROPRIEDADES CALCULADAS ===
    @hybrid_property
    def idade_veiculo(self):
        """Calcula a idade do veículo em anos"""
        if self.ano_fabricacao:
            return date.today().year - self.ano_fabricacao
        return None
    
    @hybrid_property
    def placa_formatada(self):
        """Retorna a placa formatada (ABC-1234 ou ABC1D23)"""
        if not self.placa:
            return self.placa
        
        placa_limpa = re.sub(r'[^A-Z0-9]', '', self.placa.upper())
        
        if len(placa_limpa) == 7:
            # Placa Mercosul (ABC1D23)
            return f"{placa_limpa[:3]}{placa_limpa[3]}{placa_limpa[4]}{placa_limpa[5:]}"
        elif len(placa_limpa) == 7:
            # Placa antiga (ABC1234)
            return f"{placa_limpa[:3]}-{placa_limpa[3:]}"
        
        return self.placa
    
    @hybrid_property
    def licenciamento_vencido(self):
        """Verifica se o licenciamento está vencido"""
        if self.data_vencimento_licenciamento:
            return self.data_vencimento_licenciamento < date.today()
        return True
    
    @hybrid_property
    def licenciamento_vence_em_30_dias(self):
        """Verifica se o licenciamento vence nos próximos 30 dias"""
        if self.data_vencimento_licenciamento:
            dias_para_vencimento = (self.data_vencimento_licenciamento - date.today()).days
            return 0 <= dias_para_vencimento <= 30
        return False
    
    @hybrid_property
    def seguro_vencido(self):
        """Verifica se o seguro está vencido"""
        if not self.seguro_vigente or not self.data_vencimento_seguro:
            return True
        return self.data_vencimento_seguro < date.today()
    
    @hybrid_property
    def necessita_revisao(self):
        """Verifica se o veículo precisa de revisão"""
        if self.proxima_revisao_km and self.quilometragem_atual >= self.proxima_revisao_km:
            return True
        if self.proxima_revisao_data and self.proxima_revisao_data <= date.today():
            return True
        return False
    
    @hybrid_property
    def apto_para_uso(self):
        """Verifica se o veículo está apto para uso"""
        return (
            self.ativo and 
            self.disponivel and 
            not self.em_manutencao and 
            not self.licenciamento_vencido and 
            not self.seguro_vencido
        )
    
    @hybrid_property
    def autonomia_estimada(self):
        """Calcula autonomia estimada em km"""
        if self.capacidade_tanque and self.consumo_medio:
            return self.capacidade_tanque * self.consumo_medio
        return None
    
    @hybrid_property
    def descricao_completa(self):
        """Retorna descrição completa do veículo"""
        return f"{self.marca} {self.modelo} {self.ano_modelo} - {self.placa_formatada}"
    
    # === VALIDAÇÕES ===
    @validates('placa')
    def validate_placa(self, key, placa):
        """Valida a placa do veículo"""
        if not placa:
            raise ValueError("Placa é obrigatória")
        
        placa = placa.upper().strip()
        placa_limpa = re.sub(r'[^A-Z0-9]', '', placa)
        
        if len(placa_limpa) != 7:
            raise ValueError("Placa deve ter 7 caracteres")
        
        # Validar formato da placa
        # Placa antiga: ABC1234
        # Placa Mercosul: ABC1D23
        if not (re.match(r'^[A-Z]{3}[0-9]{4}$', placa_limpa) or 
                re.match(r'^[A-Z]{3}[0-9][A-Z][0-9]{2}$', placa_limpa)):
            raise ValueError("Formato de placa inválido")
        
        return placa_limpa
    
    @validates('renavam')
    def validate_renavam(self, key, renavam):
        """Valida o RENAVAM"""
        if not renavam:
            raise ValueError("RENAVAM é obrigatório")
        
        renavam_numeros = re.sub(r'\D', '', renavam)
        
        if len(renavam_numeros) < 9 or len(renavam_numeros) > 11:
            raise ValueError("RENAVAM deve ter entre 9 e 11 dígitos")
        
        return renavam_numeros
    
    @validates('chassi')
    def validate_chassi(self, key, chassi):
        """Valida o número do chassi"""
        if not chassi:
            raise ValueError("Número do chassi é obrigatório")
        
        chassi = chassi.upper().strip()
        
        if len(chassi) != 17:
            raise ValueError("Chassi deve ter 17 caracteres")
        
        # Verificar caracteres proibidos no chassi
        caracteres_proibidos = ['I', 'O', 'Q']
        if any(char in chassi for char in caracteres_proibidos):
            raise ValueError("Chassi não pode conter os caracteres I, O ou Q")
        
        return chassi
    
    @validates('ano_fabricacao', 'ano_modelo')
    def validate_ano(self, key, ano):
        """Valida anos de fabricação e modelo"""
        if not ano:
            raise ValueError(f"{key.replace('_', ' ').title()} é obrigatório")
        
        ano_atual = date.today().year
        
        if ano < 1990:
            raise ValueError("Ano muito antigo para o sistema")
        
        if ano > ano_atual + 1:
            raise ValueError("Ano não pode ser superior ao ano seguinte")
        
        return ano
    
    @validates('tipo_veiculo')
    def validate_tipo_veiculo(self, key, tipo):
        """Valida o tipo de veículo"""
        if not tipo:
            raise ValueError("Tipo de veículo é obrigatório")
        
        tipos_validos = ['van', 'micro_onibus', 'ambulancia', 'veiculo_comum']
        tipo = tipo.lower()
        
        if tipo not in tipos_validos:
            raise ValueError(f"Tipo deve ser: {', '.join(tipos_validos)}")
        
        return tipo
    
    @validates('combustivel')
    def validate_combustivel(self, key, combustivel):
        """Valida o tipo de combustível"""
        if not combustivel:
            raise ValueError("Tipo de combustível é obrigatório")
        
        combustiveis_validos = ['gasolina', 'etanol', 'diesel', 'flex', 'gnv', 'eletrico', 'hibrido']
        combustivel = combustivel.lower()
        
        if combustivel not in combustiveis_validos:
            raise ValueError(f"Combustível deve ser: {', '.join(combustiveis_validos)}")
        
        return combustivel
    
    @validates('capacidade_passageiros')
    def validate_capacidade_passageiros(self, key, capacidade):
        """Valida a capacidade de passageiros"""
        if capacidade is None or capacidade <= 0:
            raise ValueError("Capacidade de passageiros deve ser maior que zero")
        
        if capacidade > 50:
            raise ValueError("Capacidade máxima é 50 passageiros")
        
        return capacidade
    
    @validates('capacidade_cadeirantes')
    def validate_capacidade_cadeirantes(self, key, capacidade):
        """Valida a capacidade de cadeirantes"""
        if capacidade is None:
            return 0
        
        if capacidade < 0:
            raise ValueError("Capacidade de cadeirantes não pode ser negativa")
        
        if capacidade > 4:
            raise ValueError("Capacidade máxima de cadeirantes é 4")
        
        return capacidade
    
    @validates('quilometragem_atual')
    def validate_quilometragem(self, key, km):
        """Valida a quilometragem atual"""
        if km is None:
            return 0
        
        if km < 0:
            raise ValueError("Quilometragem não pode ser negativa")
        
        if km > 2000000:  # 2 milhões de km
            raise ValueError("Quilometragem muito alta")
        
        return km
    
    @validates('data_vencimento_licenciamento')
    def validate_vencimento_licenciamento(self, key, data):
        """Valida a data de vencimento do licenciamento"""
        if not data:
            raise ValueError("Data de vencimento do licenciamento é obrigatória")
        
        if isinstance(data, str):
            try:
                data = datetime.strptime(data, '%Y-%m-%d').date()
            except ValueError:
                raise ValueError("Data de vencimento do licenciamento inválida")
        
        return data
    
    # === MÉTODOS DO MODELO ===
    def pode_transportar_paciente(self, paciente):
        """Verifica se o veículo pode transportar determinado paciente"""
        if not self.apto_para_uso:
            return False, "Veículo não está apto para uso"
        
        if paciente.usa_cadeira_rodas and self.capacidade_cadeirantes == 0:
            return False, "Veículo não possui acessibilidade para cadeirantes"
        
        if paciente.mobilidade_reduzida and not self.acessibilidade_total:
            return False, "Veículo não possui acessibilidade total"
        
        return True, "Veículo adequado"
    
    def atualizar_quilometragem(self, nova_quilometragem):
        """Atualiza a quilometragem do veículo"""
        if nova_quilometragem < self.quilometragem_atual:
            raise ValueError("Nova quilometragem não pode ser menor que a atual")
        
        self.quilometragem_atual = nova_quilometragem
        
        # Verificar se precisa de revisão
        if (self.proxima_revisao_km and 
            self.quilometragem_atual >= self.proxima_revisao_km):
            return True  # Precisa de revisão
        
        return False
    
    def registrar_manutencao(self, tipo_manutencao, data_manutencao=None, quilometragem=None):
        """Registra uma manutenção no veículo"""
        if data_manutencao is None:
            data_manutencao = date.today()
        
        if quilometragem is None:
            quilometragem = self.quilometragem_atual
        
        self.data_ultima_revisao = data_manutencao
        self.quilometragem_ultima_revisao = quilometragem
        
        # Calcular próxima revisão (a cada 10.000 km ou 6 meses)
        self.proxima_revisao_km = quilometragem + 10000
        self.proxima_revisao_data = data_manutencao + datetime.timedelta(days=180)
    
    def to_dict(self):
        """Converte o modelo para dicionário"""
        return {
            'id': self.id,
            'placa': self.placa_formatada,
            'renavam': self.renavam,
            'chassi': self.chassi,
            'marca': self.marca,
            'modelo': self.modelo,
            'ano_fabricacao': self.ano_fabricacao,
            'ano_modelo': self.ano_modelo,
            'cor': self.cor.title(),
            'combustivel': self.combustivel.title(),
            'tipo_veiculo': self.tipo_veiculo.replace('_', ' ').title(),
            'capacidade_passageiros': self.capacidade_passageiros,
            'capacidade_cadeirantes': self.capacidade_cadeirantes,
            'ar_condicionado': self.ar_condicionado,
            'acessibilidade_total': self.acessibilidade_total,
            'elevador_cadeirante': self.elevador_cadeirante,
            'maca': self.maca,
            'data_vencimento_licenciamento': self.data_vencimento_licenciamento.strftime('%d/%m/%Y') if self.data_vencimento_licenciamento else None,
            'licenciamento_vencido': self.licenciamento_vencido,
            'licenciamento_vence_em_30_dias': self.licenciamento_vence_em_30_dias,
            'seguro_vigente': self.seguro_vigente,
            'data_vencimento_seguro': self.data_vencimento_seguro.strftime('%d/%m/%Y') if self.data_vencimento_seguro else None,
            'seguro_vencido': self.seguro_vencido,
            'quilometragem_atual': self.quilometragem_atual,
            'consumo_medio': self.consumo_medio,
            'autonomia_estimada': self.autonomia_estimada,
            'necessita_revisao': self.necessita_revisao,
            'apto_para_uso': self.apto_para_uso,
            'ativo': self.ativo,
            'disponivel': self.disponivel,
            'em_manutencao': self.em_manutencao,
            'motivo_indisponibilidade': self.motivo_indisponibilidade,
            'numero_patrimonio': self.numero_patrimonio,
            'descricao_completa': self.descricao_completa,
            'idade_veiculo': self.idade_veiculo,
            'observacoes': self.observacoes,
            'data_cadastro': self.data_cadastro.strftime('%d/%m/%Y %H:%M') if self.data_cadastro else None
        }
    
    def __repr__(self):
        """Representação string do modelo"""
        return f'<Veiculo {self.placa_formatada} - {self.marca} {self.modelo}>'
    
    def __str__(self):
        """String amigável do modelo"""
        return self.descricao_completa
    
    # === MÉTODOS DE CLASSE ===
    @classmethod
    def buscar_por_placa(cls, placa):
        """Busca veículo pela placa"""
        placa_limpa = re.sub(r'[^A-Z0-9]', '', placa.upper())
        return cls.query.filter_by(placa=placa_limpa).first()
    
    @classmethod
    def buscar_por_renavam(cls, renavam):
        """Busca veículo pelo RENAVAM"""
        renavam_numeros = re.sub(r'\D', '', renavam)
        return cls.query.filter_by(renavam=renavam_numeros).first()
    
    @classmethod
    def veiculos_ativos(cls):
        """Retorna query de veículos ativos"""
        return cls.query.filter_by(ativo=True)
    
    @classmethod
    def veiculos_disponiveis(cls):
        """Retorna veículos disponíveis para uso"""
        hoje = date.today()
        return cls.query.filter(
            cls.ativo == True,
            cls.disponivel == True,
            cls.em_manutencao == False,
            cls.data_vencimento_licenciamento >= hoje
        )
    
    @classmethod
    def veiculos_acessiveis(cls):
        """Retorna veículos com acessibilidade para cadeirantes"""
        return cls.query.filter(
            cls.ativo == True,
            cls.disponivel == True,
            cls.capacidade_cadeirantes > 0
        )
    
    @classmethod
    def licenciamento_vencendo(cls, dias=30):
        """Retorna veículos com licenciamento vencendo"""
        data_limite = date.today() + datetime.timedelta(days=dias)
        return cls.query.filter(
            cls.ativo == True,
            cls.data_vencimento_licenciamento <= data_limite,
            cls.data_vencimento_licenciamento >= date.today()
        )
    
    @classmethod
    def necessitam_revisao(cls):
        """Retorna veículos que necessitam revisão"""
        hoje = date.today()
        return cls.query.filter(
            cls.ativo == True,
            db.or_(
                cls.proxima_revisao_data <= hoje,
                cls.quilometragem_atual >= cls.proxima_revisao_km
            )
        )
    
    @classmethod
    def estatisticas(cls):
        """Retorna estatísticas dos veículos"""
        total = cls.query.count()
        ativos = cls.query.filter_by(ativo=True).count()
        disponiveis = cls.veiculos_disponiveis().count()
        em_manutencao = cls.query.filter_by(em_manutencao=True).count()
        licenciamento_vencendo = cls.licenciamento_vencendo().count()
        necessitam_revisao = cls.necessitam_revisao().count()
        acessiveis = cls.veiculos_acessiveis().count()
        
        return {
            'total': total,
            'ativos': ativos,
            'disponiveis': disponiveis,
            'em_manutencao': em_manutencao,
            'licenciamento_vencendo': licenciamento_vencendo,
            'necessitam_revisao': necessitam_revisao,
            'acessiveis': acessiveis
        }
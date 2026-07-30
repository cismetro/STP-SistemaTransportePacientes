#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de Transporte de Pacientes
Desenvolvido para a Prefeitura Municipal de Cosmópolis
Pode ser usado por terceiros autorizados

Modelo: Motorista
Representa os motoristas cadastrados no sistema
"""

from datetime import datetime, date
from sqlalchemy import Column, Integer, String, Text, Date, DateTime, Boolean
from sqlalchemy.orm import validates, relationship
from sqlalchemy.ext.hybrid import hybrid_property
import re

from db.database import db

class Motorista(db.Model):
    """
    Modelo de Motorista
    Sistema da Prefeitura Municipal de Cosmópolis
    
    Representa um motorista cadastrado no sistema de transporte de pacientes
    """
    
    __tablename__ = 'motoristas'
    
    # === CAMPOS PRINCIPAIS ===
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Dados pessoais
    nome_completo = Column(String(200), nullable=False, index=True)
    cpf = Column(String(14), unique=True, nullable=False, index=True)
    rg = Column(String(20), nullable=False)
    data_nascimento = Column(Date, nullable=False, index=True)
    
    # CNH (Carteira Nacional de Habilitação)
    numero_cnh = Column(String(20), unique=True, nullable=False, index=True)
    categoria_cnh = Column(String(5), nullable=False)  # A, B, C, D, E, AB, AC, AD, AE
    data_vencimento_cnh = Column(Date, nullable=False, index=True)
    data_primeira_habilitacao = Column(Date, nullable=False)
    
    # Contato
    telefone_principal = Column(String(20), nullable=False)
    telefone_secundario = Column(String(20), nullable=True)
    email = Column(String(120), nullable=True)
    
    # Endereço
    cep = Column(String(10), nullable=False)
    logradouro = Column(String(200), nullable=False)
    numero = Column(String(10), nullable=False)
    complemento = Column(String(100), nullable=True)
    bairro = Column(String(100), nullable=False)
    cidade = Column(String(100), nullable=False, default='Cosmópolis')
    uf = Column(String(2), nullable=False, default='SP')
    
    # Informações profissionais
    registro_funcional = Column(String(20), unique=True, nullable=True)  # Para funcionários da prefeitura
    tipo_vinculo = Column(String(20), nullable=False, default='funcionario')  # funcionario, terceirizado, voluntario
    data_admissao = Column(Date, nullable=False, default=date.today)
    salario = Column(String(20), nullable=True)  # Armazenado como string por questões de privacidade
    
    # Qualificações e certificações
    curso_transporte_pacientes = Column(Boolean, default=False, nullable=False)
    data_curso_transporte = Column(Date, nullable=True)
    certificado_emergencia = Column(Boolean, default=False, nullable=False)
    data_certificado_emergencia = Column(Date, nullable=True)
    
    # Informações de saúde
    atestado_saude = Column(Boolean, default=False, nullable=False)
    data_atestado_saude = Column(Date, nullable=True)
    restricoes_medicas = Column(Text, nullable=True)
    
    # Avaliações e desempenho
    pontuacao_cnh = Column(Integer, default=0, nullable=False)  # Pontos na CNH
    avaliacoes_positivas = Column(Integer, default=0, nullable=False)
    avaliacoes_negativas = Column(Integer, default=0, nullable=False)
    
    # Status e controle
    ativo = Column(Boolean, default=True, nullable=False, index=True)
    disponivel = Column(Boolean, default=True, nullable=False, index=True)
    observacoes = Column(Text, nullable=True)
    motivo_inativacao = Column(String(200), nullable=True)
    
    # Timestamps
    data_cadastro = Column(DateTime, default=datetime.utcnow, nullable=False)
    data_atualizacao = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # === RELACIONAMENTOS ===
    # Um motorista pode ter vários agendamentos
    agendamentos = relationship('Agendamento', backref='motorista', lazy='dynamic', cascade='all, delete-orphan')
    
    # === PROPRIEDADES CALCULADAS ===
    @hybrid_property
    def idade(self):
        """Calcula a idade do motorista"""
        if self.data_nascimento:
            hoje = date.today()
            return hoje.year - self.data_nascimento.year - (
                (hoje.month, hoje.day) < (self.data_nascimento.month, self.data_nascimento.day)
            )
        return None
    
    @hybrid_property
    def anos_experiencia(self):
        """Calcula anos de experiência de direção"""
        if self.data_primeira_habilitacao:
            hoje = date.today()
            return hoje.year - self.data_primeira_habilitacao.year - (
                (hoje.month, hoje.day) < (self.data_primeira_habilitacao.month, self.data_primeira_habilitacao.day)
            )
        return None
    
    @hybrid_property
    def cnh_vencida(self):
        """Verifica se a CNH está vencida"""
        if self.data_vencimento_cnh:
            return self.data_vencimento_cnh < date.today()
        return True
    
    @hybrid_property
    def cnh_vence_em_30_dias(self):
        """Verifica se a CNH vence nos próximos 30 dias"""
        if self.data_vencimento_cnh:
            dias_para_vencimento = (self.data_vencimento_cnh - date.today()).days
            return 0 <= dias_para_vencimento <= 30
        return False
    
    @hybrid_property
    def habilitado_para_transporte_pacientes(self):
        """Verifica se está habilitado para transporte de pacientes"""
        return (
            self.ativo and 
            self.disponivel and 
            not self.cnh_vencida and 
            self.atestado_saude and 
            (self.categoria_cnh in ['D', 'E', 'AD', 'AE'] or self.curso_transporte_pacientes)
        )
    
    @hybrid_property
    def endereco_completo(self):
        """Retorna o endereço completo formatado"""
        endereco = f"{self.logradouro}, {self.numero}"
        if self.complemento:
            endereco += f", {self.complemento}"
        endereco += f" - {self.bairro} - {self.cidade}/{self.uf} - CEP: {self.cep}"
        return endereco
    
    @hybrid_property
    def cpf_formatado(self):
        """Retorna o CPF formatado"""
        if self.cpf and len(self.cpf) == 11:
            return f"{self.cpf[:3]}.{self.cpf[3:6]}.{self.cpf[6:9]}-{self.cpf[9:]}"
        return self.cpf
    
    @hybrid_property
    def telefone_formatado(self):
        """Retorna o telefone principal formatado"""
        if self.telefone_principal:
            numeros = re.sub(r'\D', '', self.telefone_principal)
            if len(numeros) == 11:  # Celular
                return f"({numeros[:2]}) {numeros[2:7]}-{numeros[7:]}"
            elif len(numeros) == 10:  # Fixo
                return f"({numeros[:2]}) {numeros[2:6]}-{numeros[6:]}"
        return self.telefone_principal
    
    @hybrid_property
    def avaliacao_geral(self):
        """Calcula avaliação geral do motorista"""
        total_avaliacoes = self.avaliacoes_positivas + self.avaliacoes_negativas
        if total_avaliacoes == 0:
            return 0
        return round((self.avaliacoes_positivas / total_avaliacoes) * 100, 1)
    
    # === VALIDAÇÕES ===
    @validates('cpf')
    def validate_cpf(self, key, cpf):
        """Valida o CPF do motorista"""
        if not cpf:
            raise ValueError("CPF é obrigatório")
        
        cpf_numeros = re.sub(r'\D', '', cpf)
        
        if len(cpf_numeros) != 11:
            raise ValueError("CPF deve ter 11 dígitos")
        
        if cpf_numeros == cpf_numeros[0] * 11:
            raise ValueError("CPF inválido")
        
        if not self._validar_cpf(cpf_numeros):
            raise ValueError("CPF inválido")
        
        return cpf_numeros
    
    @validates('nome_completo')
    def validate_nome(self, key, nome):
        """Valida o nome do motorista"""
        if not nome:
            raise ValueError("Nome completo é obrigatório")
        
        nome = nome.strip()
        if len(nome) < 3:
            raise ValueError("Nome deve ter pelo menos 3 caracteres")
        
        if len(nome) > 200:
            raise ValueError("Nome não pode ter mais de 200 caracteres")
        
        palavras = nome.split()
        if len(palavras) < 2:
            raise ValueError("Informe nome e sobrenome")
        
        return nome.title()
    
    @validates('data_nascimento')
    def validate_data_nascimento(self, key, data):
        """Valida a data de nascimento"""
        if not data:
            raise ValueError("Data de nascimento é obrigatória")
        
        if isinstance(data, str):
            try:
                data = datetime.strptime(data, '%Y-%m-%d').date()
            except ValueError:
                raise ValueError("Data de nascimento inválida")
        
        if data > date.today():
            raise ValueError("Data de nascimento não pode ser futura")
        
        # Verificar idade mínima para motorista (18 anos)
        idade = date.today().year - data.year
        if idade < 18:
            raise ValueError("Motorista deve ter pelo menos 18 anos")
        
        if idade > 80:
            raise ValueError("Idade máxima permitida é 80 anos")
        
        return data
    
    @validates('numero_cnh')
    def validate_numero_cnh(self, key, numero_cnh):
        """Valida o número da CNH"""
        if not numero_cnh:
            raise ValueError("Número da CNH é obrigatório")
        
        # Remove caracteres não numéricos
        cnh_numeros = re.sub(r'\D', '', numero_cnh)
        
        if len(cnh_numeros) != 11:
            raise ValueError("CNH deve ter 11 dígitos")
        
        return cnh_numeros
    
    @validates('categoria_cnh')
    def validate_categoria_cnh(self, key, categoria):
        """Valida a categoria da CNH"""
        if not categoria:
            raise ValueError("Categoria da CNH é obrigatória")
        
        categorias_validas = ['A', 'B', 'C', 'D', 'E', 'AB', 'AC', 'AD', 'AE', 'ACC']
        categoria = categoria.upper()
        
        if categoria not in categorias_validas:
            raise ValueError(f"Categoria deve ser uma das seguintes: {', '.join(categorias_validas)}")
        
        return categoria
    
    @validates('data_vencimento_cnh')
    def validate_data_vencimento_cnh(self, key, data):
        """Valida a data de vencimento da CNH"""
        if not data:
            raise ValueError("Data de vencimento da CNH é obrigatória")
        
        if isinstance(data, str):
            try:
                data = datetime.strptime(data, '%Y-%m-%d').date()
            except ValueError:
                raise ValueError("Data de vencimento da CNH inválida")
        
        # CNH não pode estar vencida há mais de 30 dias
        if (date.today() - data).days > 30:
            raise ValueError("CNH não pode estar vencida há mais de 30 dias")
        
        return data
    
    @validates('data_primeira_habilitacao')
    def validate_data_primeira_habilitacao(self, key, data):
        """Valida a data da primeira habilitação"""
        if not data:
            raise ValueError("Data da primeira habilitação é obrigatória")
        
        if isinstance(data, str):
            try:
                data = datetime.strptime(data, '%Y-%m-%d').date()
            except ValueError:
                raise ValueError("Data da primeira habilitação inválida")
        
        if data > date.today():
            raise ValueError("Data da primeira habilitação não pode ser futura")
        
        return data
    
    @validates('telefone_principal', 'telefone_secundario')
    def validate_telefone(self, key, telefone):
        """Valida telefones"""
        if not telefone:
            if key == 'telefone_principal':
                raise ValueError("Telefone principal é obrigatório")
            return telefone
        
        numeros = re.sub(r'\D', '', telefone)
        
        if len(numeros) not in [10, 11]:
            raise ValueError("Telefone deve ter 10 ou 11 dígitos")
        
        if not numeros.startswith(('11', '12', '13', '14', '15', '16', '17', '18', '19')):
            raise ValueError("Código de área inválido para São Paulo")
        
        return numeros
    
    @validates('tipo_vinculo')
    def validate_tipo_vinculo(self, key, tipo):
        """Valida o tipo de vínculo"""
        if not tipo:
            raise ValueError("Tipo de vínculo é obrigatório")
        
        tipos_validos = ['funcionario', 'terceirizado', 'voluntario']
        tipo = tipo.lower()
        
        if tipo not in tipos_validos:
            raise ValueError(f"Tipo de vínculo deve ser: {', '.join(tipos_validos)}")
        
        return tipo
    
    @validates('pontuacao_cnh')
    def validate_pontuacao_cnh(self, key, pontos):
        """Valida pontuação da CNH"""
        if pontos is None:
            return 0
        
        if pontos < 0:
            raise ValueError("Pontuação não pode ser negativa")
        
        if pontos > 20:
            raise ValueError("Motorista com mais de 20 pontos não pode dirigir")
        
        return pontos
    
    # === MÉTODOS AUXILIARES ===
    def _validar_cpf(self, cpf):
        """Algoritmo de validação do CPF"""
        try:
            # Primeiro dígito verificador
            soma = sum(int(cpf[i]) * (10 - i) for i in range(9))
            resto = soma % 11
            digito1 = 11 - resto if resto >= 2 else 0
            
            if int(cpf[9]) != digito1:
                return False
            
            # Segundo dígito verificador
            soma = sum(int(cpf[i]) * (11 - i) for i in range(10))
            resto = soma % 11
            digito2 = 11 - resto if resto >= 2 else 0
            
            return int(cpf[10]) == digito2
        except (ValueError, IndexError):
            return False
    
    # === MÉTODOS DO MODELO ===
    def pode_dirigir_veiculo(self, categoria_veiculo):
        """Verifica se pode dirigir determinado tipo de veículo"""
        if not self.habilitado_para_transporte_pacientes:
            return False
        
        # Mapeamento de categorias de CNH para tipos de veículo
        categorias_permitidas = {
            'van': ['B', 'C', 'D', 'E', 'AB', 'AC', 'AD', 'AE'],
            'micro_onibus': ['D', 'E', 'AD', 'AE'],
            'ambulancia': ['B', 'C', 'D', 'E', 'AB', 'AC', 'AD', 'AE'],
            'veiculo_comum': ['B', 'C', 'D', 'E', 'AB', 'AC', 'AD', 'AE']
        }
        
        return self.categoria_cnh in categorias_permitidas.get(categoria_veiculo, [])
    
    def adicionar_avaliacao(self, positiva=True):
        """Adiciona uma avaliação ao motorista"""
        if positiva:
            self.avaliacoes_positivas += 1
        else:
            self.avaliacoes_negativas += 1
    
    def to_dict(self):
        """Converte o modelo para dicionário"""
        return {
            'id': self.id,
            'nome_completo': self.nome_completo,
            'cpf': self.cpf_formatado,
            'rg': self.rg,
            'data_nascimento': self.data_nascimento.strftime('%d/%m/%Y') if self.data_nascimento else None,
            'idade': self.idade,
            'telefone_principal': self.telefone_formatado,
            'telefone_secundario': self.telefone_secundario,
            'email': self.email,
            'endereco_completo': self.endereco_completo,
            'numero_cnh': self.numero_cnh,
            'categoria_cnh': self.categoria_cnh,
            'data_vencimento_cnh': self.data_vencimento_cnh.strftime('%d/%m/%Y') if self.data_vencimento_cnh else None,
            'cnh_vencida': self.cnh_vencida,
            'cnh_vence_em_30_dias': self.cnh_vence_em_30_dias,
            'anos_experiencia': self.anos_experiencia,
            'registro_funcional': self.registro_funcional,
            'tipo_vinculo': self.tipo_vinculo.title(),
            'data_admissao': self.data_admissao.strftime('%d/%m/%Y') if self.data_admissao else None,
            'curso_transporte_pacientes': self.curso_transporte_pacientes,
            'certificado_emergencia': self.certificado_emergencia,
            'atestado_saude': self.atestado_saude,
            'pontuacao_cnh': self.pontuacao_cnh,
            'avaliacao_geral': self.avaliacao_geral,
            'habilitado_para_transporte_pacientes': self.habilitado_para_transporte_pacientes,
            'ativo': self.ativo,
            'disponivel': self.disponivel,
            'observacoes': self.observacoes,
            'data_cadastro': self.data_cadastro.strftime('%d/%m/%Y %H:%M') if self.data_cadastro else None
        }
    
    def __repr__(self):
        """Representação string do modelo"""
        return f'<Motorista {self.nome_completo} - CNH: {self.numero_cnh}>'
    
    def __str__(self):
        """String amigável do modelo"""
        return f'{self.nome_completo} (CNH: {self.numero_cnh})'
    
    # === MÉTODOS DE CLASSE ===
    @classmethod
    def buscar_por_cpf(cls, cpf):
        """Busca motorista pelo CPF"""
        cpf_numeros = re.sub(r'\D', '', cpf)
        return cls.query.filter_by(cpf=cpf_numeros).first()
    
    @classmethod
    def buscar_por_cnh(cls, numero_cnh):
        """Busca motorista pelo número da CNH"""
        cnh_numeros = re.sub(r'\D', '', numero_cnh)
        return cls.query.filter_by(numero_cnh=cnh_numeros).first()
    
    @classmethod
    def motoristas_ativos(cls):
        """Retorna query de motoristas ativos"""
        return cls.query.filter_by(ativo=True)
    
    @classmethod
    def motoristas_disponiveis(cls):
        """Retorna motoristas disponíveis para trabalho"""
        return cls.query.filter_by(ativo=True, disponivel=True)
    
    @classmethod
    def motoristas_habilitados(cls):
        """Retorna motoristas habilitados para transporte de pacientes"""
        hoje = date.today()
        return cls.query.filter(
            cls.ativo == True,
            cls.disponivel == True,
            cls.data_vencimento_cnh >= hoje,
            cls.atestado_saude == True
        )
    
    @classmethod
    def cnh_vencendo(cls, dias=30):
        """Retorna motoristas com CNH vencendo nos próximos dias"""
        data_limite = date.today() + datetime.timedelta(days=dias)
        return cls.query.filter(
            cls.ativo == True,
            cls.data_vencimento_cnh <= data_limite,
            cls.data_vencimento_cnh >= date.today()
        )
    
    @classmethod
    def estatisticas(cls):
        """Retorna estatísticas dos motoristas"""
        total = cls.query.count()
        ativos = cls.query.filter_by(ativo=True).count()
        disponiveis = cls.query.filter_by(ativo=True, disponivel=True).count()
        habilitados = cls.motoristas_habilitados().count()
        cnh_vencendo = cls.cnh_vencendo().count()
        
        return {
            'total': total,
            'ativos': ativos,
            'disponiveis': disponiveis,
            'habilitados': habilitados,
            'cnh_vencendo': cnh_vencendo
        }
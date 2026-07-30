
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de Transporte de Pacientes
Desenvolvido para a Prefeitura Municipal de Cosmópolis
Pode ser usado por terceiros autorizados

Modelo: Paciente
Representa os pacientes cadastrados no sistema
"""

from datetime import datetime, date
from sqlalchemy import Column, Integer, String, Text, Date, DateTime, Boolean
from sqlalchemy.orm import validates, relationship
from sqlalchemy.ext.hybrid import hybrid_property
import re

from db.database import db

class Paciente(db.Model):
    """
    Modelo de Paciente
    Sistema da Prefeitura Municipal de Cosmópolis
    
    Representa um paciente cadastrado no sistema de transporte
    """
    
    __tablename__ = 'pacientes'
    
    # === CAMPOS PRINCIPAIS ===
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Dados pessoais
    nome_completo = Column(String(200), nullable=False, index=True)
    cpf = Column(String(14), unique=True, nullable=False, index=True)
    rg = Column(String(20), nullable=True)
    data_nascimento = Column(Date, nullable=False, index=True)
    
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
    
    # Informações médicas
    observacoes_medicas = Column(Text, nullable=True)
    necessita_acompanhante = Column(Boolean, default=False, nullable=False)
    mobilidade_reduzida = Column(Boolean, default=False, nullable=False)
    usa_cadeira_rodas = Column(Boolean, default=False, nullable=False)
    
    # Dados do responsável (se menor de idade ou incapaz)
    nome_responsavel = Column(String(200), nullable=True)
    cpf_responsavel = Column(String(14), nullable=True)
    telefone_responsavel = Column(String(20), nullable=True)
    parentesco_responsavel = Column(String(50), nullable=True)
    
    # Status e controle
    ativo = Column(Boolean, default=True, nullable=False, index=True)
    observacoes = Column(Text, nullable=True)
    
    # Timestamps
    data_cadastro = Column(DateTime, default=datetime.utcnow, nullable=False)
    data_atualizacao = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # === RELACIONAMENTOS ===
    # Um paciente pode ter vários agendamentos
    agendamentos = relationship('Agendamento', backref='paciente', lazy='dynamic', cascade='all, delete-orphan')
    
    # === PROPRIEDADES CALCULADAS ===
    @hybrid_property
    def idade(self):
        """Calcula a idade do paciente"""
        if self.data_nascimento:
            hoje = date.today()
            return hoje.year - self.data_nascimento.year - (
                (hoje.month, hoje.day) < (self.data_nascimento.month, self.data_nascimento.day)
            )
        return None
    
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
            # Remove caracteres não numéricos
            numeros = re.sub(r'\D', '', self.telefone_principal)
            if len(numeros) == 11:  # Celular
                return f"({numeros[:2]}) {numeros[2:7]}-{numeros[7:]}"
            elif len(numeros) == 10:  # Fixo
                return f"({numeros[:2]}) {numeros[2:6]}-{numeros[6:]}"
        return self.telefone_principal
    
    @hybrid_property
    def eh_menor_idade(self):
        """Verifica se o paciente é menor de idade"""
        return self.idade and self.idade < 18
    
    @hybrid_property
    def precisa_responsavel(self):
        """Verifica se precisa de dados do responsável"""
        return self.eh_menor_idade or self.nome_responsavel is not None
    
    # === VALIDAÇÕES ===
    @validates('cpf')
    def validate_cpf(self, key, cpf):
        """Valida o CPF do paciente"""
        if not cpf:
            raise ValueError("CPF é obrigatório")
        
        # Remove caracteres não numéricos
        cpf_numeros = re.sub(r'\D', '', cpf)
        
        if len(cpf_numeros) != 11:
            raise ValueError("CPF deve ter 11 dígitos")
        
        # Verifica se não são todos os dígitos iguais
        if cpf_numeros == cpf_numeros[0] * 11:
            raise ValueError("CPF inválido")
        
        # Validação matemática do CPF
        if not self._validar_cpf(cpf_numeros):
            raise ValueError("CPF inválido")
        
        return cpf_numeros
    
    @validates('nome_completo')
    def validate_nome(self, key, nome):
        """Valida o nome do paciente"""
        if not nome:
            raise ValueError("Nome completo é obrigatório")
        
        nome = nome.strip()
        if len(nome) < 3:
            raise ValueError("Nome deve ter pelo menos 3 caracteres")
        
        if len(nome) > 200:
            raise ValueError("Nome não pode ter mais de 200 caracteres")
        
        # Verificar se contém pelo menos nome e sobrenome
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
                raise ValueError("Data de nascimento inválida. Use o formato YYYY-MM-DD")
        
        # Verificar se a data não é futura
        if data > date.today():
            raise ValueError("Data de nascimento não pode ser futura")
        
        # Verificar idade mínima e máxima razoável
        idade = date.today().year - data.year
        if idade > 120:
            raise ValueError("Data de nascimento muito antiga")
        
        return data
    
    @validates('telefone_principal', 'telefone_secundario', 'telefone_responsavel')
    def validate_telefone(self, key, telefone):
        """Valida telefones"""
        if not telefone:
            if key == 'telefone_principal':
                raise ValueError("Telefone principal é obrigatório")
            return telefone
        
        # Remove caracteres não numéricos
        numeros = re.sub(r'\D', '', telefone)
        
        # Verifica se tem 10 ou 11 dígitos
        if len(numeros) not in [10, 11]:
            raise ValueError("Telefone deve ter 10 ou 11 dígitos")
        
        # Verifica se começa com código de área válido
        if not numeros.startswith(('11', '12', '13', '14', '15', '16', '17', '18', '19')):
            # Códigos de área de SP
            raise ValueError("Código de área inválido para São Paulo")
        
        return numeros
    
    @validates('email')
    def validate_email(self, key, email):
        """Valida email"""
        if not email:
            return email
        
        email = email.strip().lower()
        
        # Validação básica de email
        padrao_email = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(padrao_email, email):
            raise ValueError("Email inválido")
        
        return email
    
    @validates('cep')
    def validate_cep(self, key, cep):
        """Valida CEP"""
        if not cep:
            raise ValueError("CEP é obrigatório")
        
        # Remove caracteres não numéricos
        cep_numeros = re.sub(r'\D', '', cep)
        
        if len(cep_numeros) != 8:
            raise ValueError("CEP deve ter 8 dígitos")
        
        return cep_numeros
    
    @validates('cpf_responsavel')
    def validate_cpf_responsavel(self, key, cpf):
        """Valida CPF do responsável"""
        if not cpf:
            return cpf
        
        # Remove caracteres não numéricos
        cpf_numeros = re.sub(r'\D', '', cpf)
        
        if len(cpf_numeros) != 11:
            raise ValueError("CPF do responsável deve ter 11 dígitos")
        
        # Verifica se não são todos os dígitos iguais
        if cpf_numeros == cpf_numeros[0] * 11:
            raise ValueError("CPF do responsável inválido")
        
        # Validação matemática do CPF
        if not self._validar_cpf(cpf_numeros):
            raise ValueError("CPF do responsável inválido")
        
        return cpf_numeros
    
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
            'cep': self.cep,
            'logradouro': self.logradouro,
            'numero': self.numero,
            'complemento': self.complemento,
            'bairro': self.bairro,
            'cidade': self.cidade,
            'uf': self.uf,
            'observacoes_medicas': self.observacoes_medicas,
            'necessita_acompanhante': self.necessita_acompanhante,
            'mobilidade_reduzida': self.mobilidade_reduzida,
            'usa_cadeira_rodas': self.usa_cadeira_rodas,
            'nome_responsavel': self.nome_responsavel,
            'cpf_responsavel': self.cpf_responsavel,
            'telefone_responsavel': self.telefone_responsavel,
            'parentesco_responsavel': self.parentesco_responsavel,
            'ativo': self.ativo,
            'observacoes': self.observacoes,
            'data_cadastro': self.data_cadastro.strftime('%d/%m/%Y %H:%M') if self.data_cadastro else None,
            'data_atualizacao': self.data_atualizacao.strftime('%d/%m/%Y %H:%M') if self.data_atualizacao else None
        }
    
    def __repr__(self):
        """Representação string do modelo"""
        return f'<Paciente {self.nome_completo} - CPF: {self.cpf_formatado}>'
    
    def __str__(self):
        """String amigável do modelo"""
        return f'{self.nome_completo} ({self.cpf_formatado})'
    
    # === MÉTODOS DE CLASSE ===
    @classmethod
    def buscar_por_cpf(cls, cpf):
        """Busca paciente pelo CPF"""
        cpf_numeros = re.sub(r'\D', '', cpf)
        return cls.query.filter_by(cpf=cpf_numeros).first()
    
    @classmethod
    def buscar_por_nome(cls, nome):
        """Busca pacientes por nome (busca parcial)"""
        return cls.query.filter(cls.nome_completo.contains(nome)).all()
    
    @classmethod
    def pacientes_ativos(cls):
        """Retorna query de pacientes ativos"""
        return cls.query.filter_by(ativo=True)
    
    @classmethod
    def pacientes_com_mobilidade_reduzida(cls):
        """Retorna pacientes com mobilidade reduzida"""
        return cls.query.filter_by(mobilidade_reduzida=True, ativo=True)
    
    @classmethod
    def pacientes_cadeirantes(cls):
        """Retorna pacientes que usam cadeira de rodas"""
        return cls.query.filter_by(usa_cadeira_rodas=True, ativo=True)
    
    @classmethod
    def estatisticas(cls):
        """Retorna estatísticas dos pacientes"""
        total = cls.query.count()
        ativos = cls.query.filter_by(ativo=True).count()
        inativos = total - ativos
        mobilidade_reduzida = cls.query.filter_by(mobilidade_reduzida=True, ativo=True).count()
        cadeirantes = cls.query.filter_by(usa_cadeira_rodas=True, ativo=True).count()
        menores_idade = cls.query.filter(cls.data_nascimento > date.today().replace(year=date.today().year - 18)).count()
        
        return {
            'total': total,
            'ativos': ativos,
            'inativos': inativos,
            'mobilidade_reduzida': mobilidade_reduzida,
            'cadeirantes': cadeirantes,
            'menores_idade': menores_idade
        }
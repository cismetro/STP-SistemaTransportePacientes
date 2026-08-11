import os
import sys
from datetime import datetime, date, timedelta
from flask import Flask, render_template, redirect, url_for, flash, request, get_flashed_messages, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
import json
# ===== IMPORTS PARA SISTEMA DE BACKUP =====
import shutil
import zipfile
import schedule
import time
import threading
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from werkzeug.middleware.proxy_fix import ProxyFix

from cnes_destinos import (
    cidade_cnes_por_nome,
    formatar_destino_cnes,
    listar_cidades_destino_cnes,
    listar_estabelecimentos_cache,
    obter_estabelecimento_cache,
    qtd_cidades_destino_cnes,
    sincronizar_cnes_cidade,
)
from validadores.rg import (
    RG_PLACEHOLDER,
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
    data_limite_por_idade,
    data_ref_normalizada as _data_ref_normalizada,
    formatar_idade_exibir,
    idade_em_anos,
)


# ===== MIDDLEWARE PARA PREFIXO /transporte =====
class PrefixMiddleware:
    """Adiciona suporte ao prefixo /transporte.

    Modo standalone:  /transporte/login  →  /login  (SCRIPT_NAME=/transporte)
    Modo proxy (nginx): /login (já sem prefixo) → /login (SCRIPT_NAME=/transporte)
    """
    def __init__(self, app, prefix='/transporte'):
        self.app = app
        self.prefix = prefix

    def __call__(self, environ, start_response):
        # Modo reverse proxy: nginx já removeu o prefixo do path,
        # mas precisamos informar o SCRIPT_NAME ao Flask para url_for()
        # gerar URLs com o prefixo correto (/transporte/login, etc.)
        forwarded_prefix = environ.get('HTTP_X_FORWARDED_PREFIX')
        if forwarded_prefix:
            environ['SCRIPT_NAME'] = forwarded_prefix
            return self.app(environ, start_response)

        # Modo standalone: extrai o prefixo do PATH_INFO
        path = environ.get('PATH_INFO', '')
        if path.startswith(self.prefix):
            environ['PATH_INFO'] = path[len(self.prefix):]
            environ['SCRIPT_NAME'] = self.prefix
            return self.app(environ, start_response)

        # Se não tem prefixo nem X-Forwarded-Prefix, deixa passar
        # (pode ser request do nginx sem o header, ou erro do cliente — o Flask trata)
        return self.app(environ, start_response)


# ===== VARIÁVEIS GLOBAIS DO SISTEMA =====
sistema_backup = None
whatsapp_service = None
notificacao_agendamento = None
agendador_lembretes = None

# ===== FUNÇÕES DE SAUDAÇÃO =====
def obter_saudacao():
    """Retorna a saudação apropriada baseada no horário atual"""
    agora = datetime.now()
    hora = agora.hour
    
    if 5 <= hora < 12:
        return "Bom dia! 🌅"
    elif 12 <= hora < 18:
        return "Boa tarde! ☀️"
    else:
        return "Boa noite! 🌙"

def obter_emoji_horario():
    """Retorna o emoji apropriado para o horário"""
    agora = datetime.now()
    hora = agora.hour
    
    if 5 <= hora < 12:
        return "🌅"
    elif 12 <= hora < 18:
        return "☀️"
    else:
        return "🌙"


from functools import wraps


# 🆕 DECORADORES DE PERMISSÃO FINANCEIRA
def contador_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.can_manage_finances():
            flash('Acesso negado! Apenas contadores e administradores podem acessar esta página.', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def finance_view_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.can_view_finances():
            flash('Acesso negado! Permissão insuficiente para visualizar dados financeiros.', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function


# Inicializar extensões
db = SQLAlchemy()
login_manager = LoginManager()

# ===== MODELOS DE BANCO DE DADOS =====
class Usuario(db.Model):
    __tablename__ = 'usuarios'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    nome_completo = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120))
    tipo_usuario = db.Column(
        db.String(20),
        nullable=False,
        default='atendente'  # atendente, supervisor, administrador, contador
    )
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    data_cadastro = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)  # 🆕 NOVO
    
    def check_password(self, password):
        try:
            if not self.password_hash:
                return False
            return check_password_hash(self.password_hash, password)
        except Exception as e:
            print(f"Erro ao verificar senha: {e}")
            return False
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    @property
    def is_authenticated(self):
        return True
    
    @property
    def is_active(self):
        return self.ativo
    
    @property
    def is_anonymous(self):
        return False
    
    def get_id(self):
        return str(self.id)
    
    # ===== PERMISSÕES ESPECÍFICAS =====
    def is_contador(self):
        return self.tipo_usuario == 'contador'

    def can_manage_finances(self):
        """Quem pode gerenciar finanças: contador e administrador"""
        return self.tipo_usuario in ['contador', 'administrador']

    def can_view_finances(self):
        """Quem pode visualizar relatórios financeiros: contador, supervisor e administrador"""
        return self.tipo_usuario in ['contador', 'supervisor', 'administrador']

    def can_generate_invoices(self):
        """Quem pode gerar faturas: apenas contador e administrador"""
        return self.tipo_usuario in ['contador', 'administrador']

class Paciente(db.Model):
    __tablename__ = 'pacientes'
    
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    cpf = db.Column(db.String(14), unique=True, nullable=False)
    tel_cel = db.Column(db.String(16))   # (00) 00000-0000
    tel_res = db.Column(db.String(15))   # (00) 0000-0000
    telefone = db.Column(db.String(15), nullable=False)  # legado / WhatsApp (tel_cel ou tel_res)
    data_nascimento = db.Column(db.Date, nullable=False)
    endereco = db.Column(db.Text, nullable=False)
    cep = db.Column(db.String(9))
    logradouro = db.Column(db.String(200))
    numero = db.Column(db.String(10))
    bairro = db.Column(db.String(100))
    complemento = db.Column(db.String(200))
    ponto_referencia = db.Column(db.String(200))
    ponto_embarque = db.Column(db.String(200))
    cartao_sus = db.Column(db.String(20))
    observacoes = db.Column(db.Text)
    # Condição especial (só quando toggle ligado)
    condicao_especial = db.Column(db.Boolean, nullable=False, default=False)
    condicao_paciente = db.Column(db.String(120))
    condicao_outros = db.Column(db.String(255))
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    data_cadastro = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # Relacionamentos
    agendamentos = db.relationship('Agendamento', backref='paciente', lazy=True)
    acompanhantes = db.relationship(
        'Acompanhante',
        backref='paciente',
        lazy=True,
        cascade='all, delete-orphan',
        order_by='Acompanhante.nome',
    )


class Acompanhante(db.Model):
    """Acompanhante cadastrado e vinculado a um paciente."""
    __tablename__ = 'acompanhantes'

    id = db.Column(db.Integer, primary_key=True)
    paciente_id = db.Column(db.Integer, db.ForeignKey('pacientes.id'), nullable=False, index=True)
    nome = db.Column(db.String(120), nullable=False)
    rg = db.Column(db.String(20))
    cpf = db.Column(db.String(14))
    telefone = db.Column(db.String(16))
    data_nascimento = db.Column(db.Date)
    parentesco = db.Column(db.String(80))
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    data_cadastro = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class Parentesco(db.Model):
    """Tabela de domínio de parentescos / vínculos (reutilizável no sistema)."""
    __tablename__ = 'parentescos'

    id = db.Column(db.Integer, primary_key=True)
    descricao = db.Column(db.String(80), nullable=False, unique=True)
    grupo = db.Column(db.String(60), nullable=False, default='Outros')
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    ordem = db.Column(db.Integer, nullable=False, default=0)


class Veiculo(db.Model):
    __tablename__ = 'veiculos'
    
    id = db.Column(db.Integer, primary_key=True)
    placa = db.Column(db.String(8), unique=True, nullable=False)
    numero_frota = db.Column(db.String(20))
    frota_id = db.Column(db.Integer, db.ForeignKey('frotas.id'), index=True)  # 1 frota ↔ 1 veículo
    marca = db.Column(db.String(50), nullable=False)
    modelo = db.Column(db.String(50), nullable=False)
    ano = db.Column(db.Integer, nullable=False)
    cor = db.Column(db.String(30))
    tipo = db.Column(db.String(30), nullable=False)
    capacidade = db.Column(db.Integer)
    adaptado = db.Column(db.Boolean, nullable=False, default=False)
    observacoes = db.Column(db.Text)
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    data_cadastro = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # 🆕 CAMPOS DE CONTROLE FINANCEIRO
    tipo_propriedade = db.Column(db.String(20), nullable=False, default='proprio')  # 'proprio' ou 'terceirizado'
    proprietario_nome = db.Column(db.String(120))  # Nome do proprietário (se terceirizado)
    proprietario_cpf_cnpj = db.Column(db.String(18))  # CPF/CNPJ do proprietário
    proprietario_telefone = db.Column(db.String(15))  # Telefone do proprietário
    valor_km = db.Column(db.Numeric(10, 2))  # Valor por KM rodado (terceirizados)
    valor_diaria = db.Column(db.Numeric(10, 2))  # Valor da diária (terceirizados)
    conta_bancaria = db.Column(db.String(100))  # Dados bancários para pagamento
    
    # Relacionamentos
    agendamentos = db.relationship('Agendamento', backref='veiculo', lazy=True)
    usos = db.relationship('UsoVeiculo', backref='veiculo', lazy=True)
    frota = db.relationship('Frota', foreign_keys=[frota_id], back_populates='veiculos')


class Frota(db.Model):
    """Cadastro de frotas (agrupamento de veículos)."""
    __tablename__ = 'frotas'

    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(30), unique=True, nullable=False, index=True)  # ex.: F00267
    nome = db.Column(db.String(120), unique=True, nullable=False, index=True)  # ex.: NI Frota 267
    # Campos reservados para expansões futuras (sem refatoração estrutural)
    descricao = db.Column(db.Text)
    responsavel = db.Column(db.String(120))
    unidade = db.Column(db.String(120))
    municipio = db.Column(db.String(100))
    observacoes = db.Column(db.Text)
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    data_cadastro = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    data_inativacao = db.Column(db.DateTime)

    veiculos = db.relationship('Veiculo', back_populates='frota', lazy=True, foreign_keys='Veiculo.frota_id')

class Motorista(db.Model):
    __tablename__ = 'motoristas'
    
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    cpf = db.Column(db.String(14), unique=True, nullable=False)
    telefone = db.Column(db.String(15), nullable=False)
    data_nascimento = db.Column(db.Date, nullable=False)
    cnh = db.Column(db.String(20), unique=True, nullable=False)
    categoria_cnh = db.Column(db.String(5), nullable=False)
    vencimento_cnh = db.Column(db.Date, nullable=False)
    endereco = db.Column(db.Text)
    cep = db.Column(db.String(9))
    logradouro = db.Column(db.String(200))
    numero = db.Column(db.String(10))
    bairro = db.Column(db.String(100))
    ponto_referencia = db.Column(db.String(200))
    status = db.Column(db.String(20), nullable=False, default='ativo')
    observacoes = db.Column(db.Text)
    data_cadastro = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # Relacionamentos
    agendamentos = db.relationship('Agendamento', backref='motorista', lazy=True)

class Agendamento(db.Model):
    __tablename__ = 'agendamentos'
    
    id = db.Column(db.Integer, primary_key=True)
    paciente_id = db.Column(db.Integer, db.ForeignKey('pacientes.id'), nullable=False)
    veiculo_id = db.Column(db.Integer, db.ForeignKey('veiculos.id'))
    frota_id = db.Column(db.Integer, db.ForeignKey('frotas.id'))  # alternativa ao veículo na programação
    motorista_id = db.Column(db.Integer, db.ForeignKey('motoristas.id'))
    tipo_transporte = db.Column(db.String(120), nullable=False)  # persiste Especialidade Médica

    data = db.Column(db.Date, nullable=False)
    hora = db.Column(db.Time, nullable=False)
    hora_consulta = db.Column(db.Time)  # horário da consulta no destino (Folha Espelho / Cartão)
    origem = db.Column(db.Text, nullable=False)
    destino = db.Column(db.Text, nullable=False)
    # 🆕 NOVOS CAMPOS DE CEP E LOCALIZAÇÃO
    cep_origem = db.Column(db.String(9))  # CEP da origem
    cep_destino = db.Column(db.String(9))  # CEP do destino
    cidade_origem = db.Column(db.String(100))  # Cidade de origem
    cidade_destino = db.Column(db.String(100))  # Cidade de destino
    endereco_destino_manual = db.Column(db.Text)  # Endereço manual
    tipo_destino = db.Column(db.String(20), default='cep')  # 'cep', 'cidade', 'cnes', 'manual'
    destino_cnes_codigo = db.Column(db.String(10))  # código CNES do estabelecimento
    destino_cnes_nome = db.Column(db.String(200))  # nome oficial / fantasia
    distancia_km = db.Column(db.Float)  # Distância calculada
    observacoes = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default='agendado')
    data_cadastro = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    # Acompanhante desta viagem (cadastro fica no paciente)
    possui_acompanhante = db.Column(db.Boolean, nullable=False, default=False)
    acompanhante_id = db.Column(db.Integer, db.ForeignKey('acompanhantes.id'), nullable=True)
    acompanhante = db.relationship('Acompanhante', foreign_keys=[acompanhante_id])
    frota = db.relationship('Frota', foreign_keys=[frota_id])


class CnesEstabelecimento(db.Model):
    """Cache local de estabelecimentos CNES (Dados Abertos MS)."""
    __tablename__ = 'cnes_estabelecimentos'

    id = db.Column(db.Integer, primary_key=True)
    codigo_cnes = db.Column(db.String(10), unique=True, nullable=False, index=True)
    codigo_municipio = db.Column(db.String(6), nullable=False, index=True)
    municipio_nome = db.Column(db.String(100), nullable=False, index=True)
    nome_fantasia = db.Column(db.String(200), nullable=False)
    razao_social = db.Column(db.String(200))
    endereco = db.Column(db.String(200))
    numero = db.Column(db.String(20))
    bairro = db.Column(db.String(100))
    cep = db.Column(db.String(10))
    telefone = db.Column(db.String(40))
    tipo_unidade = db.Column(db.Integer)
    esfera = db.Column(db.String(60))
    atualizado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class UsoVeiculo(db.Model):
    __tablename__ = 'uso_veiculos'
    
    id = db.Column(db.Integer, primary_key=True)
    agendamento_id = db.Column(db.Integer, db.ForeignKey('agendamentos.id'), nullable=False)
    veiculo_id = db.Column(db.Integer, db.ForeignKey('veiculos.id'), nullable=False)
    motorista_id = db.Column(db.Integer, db.ForeignKey('motoristas.id'), nullable=False)
    
    # Dados do trajeto
    data_uso = db.Column(db.Date, nullable=False)
    hora_saida = db.Column(db.Time, nullable=False)
    hora_retorno = db.Column(db.Time)
    km_inicial = db.Column(db.Integer)  # Quilometragem inicial
    km_final = db.Column(db.Integer)    # Quilometragem final
    km_rodados = db.Column(db.Integer)  # Calculado automaticamente
    
    # Endereços
    endereco_origem = db.Column(db.Text, nullable=False)
    endereco_destino = db.Column(db.Text, nullable=False)
    
    # Dados financeiros (para terceirizados)
    valor_km = db.Column(db.Numeric(10, 2))      # Valor por KM (na data do uso)
    valor_diaria = db.Column(db.Numeric(10, 2))  # Valor da diária (na data do uso)
    valor_total = db.Column(db.Numeric(10, 2))   # Valor total calculado
    combustivel_valor = db.Column(db.Numeric(10, 2))  # Valor do combustível
    
    # Controle
    status = db.Column(db.String(20), nullable=False, default='em_andamento')  # em_andamento, concluido, cancelado
    observacoes = db.Column(db.Text)
    data_cadastro = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # Relacionamentos
    agendamento = db.relationship('Agendamento', backref='uso_veiculo')
    motorista = db.relationship('Motorista', backref='usos_motorista')
    
    
    
    
    @property
    def duracao_horas(self):
        """Calcula duração em horas entre saída e retorno"""
        if self.hora_saida and self.hora_retorno:
            # Converter para datetime para calcular diferença
            from datetime import datetime, timedelta
            inicio = datetime.combine(self.data_uso, self.hora_saida)
            fim = datetime.combine(self.data_uso, self.hora_retorno)
            
            # Se retorno for no dia seguinte
            if fim < inicio:
                fim += timedelta(days=1)
            
            diferenca = fim - inicio
            return round(diferenca.total_seconds() / 3600, 2)  # Em horas
        return 0
    
    def calcular_valor_total(self):
        """Calcula valor total baseado no tipo de cobrança"""
        if not self.veiculo:
            return 0
        
        valor = 0
        
        # Se veículo é terceirizado, calcular valor
        if self.veiculo.tipo_propriedade == 'terceirizado':
            # Priorizar cobrança por KM se disponível
            if self.km_rodados and self.valor_km:
                valor = float(self.km_rodados) * float(self.valor_km)
            elif self.valor_diaria:
                # Cobrança por diária
                valor = float(self.valor_diaria)
        
        # Adicionar combustível se houver
        if self.combustivel_valor:
            valor += float(self.combustivel_valor)
        
        self.valor_total = valor
        return valor

class Abastecimento(db.Model):
    __tablename__ = 'abastecimentos'
    
    id = db.Column(db.Integer, primary_key=True)
    veiculo_id = db.Column(db.Integer, db.ForeignKey('veiculos.id'), nullable=False)
    
    # Dados do abastecimento
    data_abastecimento = db.Column(db.Date, nullable=False)
    hora_abastecimento = db.Column(db.Time, nullable=False)
    km_atual = db.Column(db.Integer, nullable=False)
    
    # Dados do combustível
    tipo_combustivel = db.Column(db.String(20), nullable=False)
    litros_abastecidos = db.Column(db.Numeric(8, 3), nullable=False)
    valor_litro = db.Column(db.Numeric(10, 3), nullable=False)
    valor_total = db.Column(db.Numeric(10, 2), nullable=False)
    
    # Local e responsável
    posto_nome = db.Column(db.String(100))
    posto_endereco = db.Column(db.String(200))
    motorista_id = db.Column(db.Integer, db.ForeignKey('motoristas.id'))
    
    # Controle
    tanque_cheio = db.Column(db.Boolean, nullable=False, default=False)
    comprovante_numero = db.Column(db.String(50))
    observacoes = db.Column(db.Text)
    
    # Metadados
    data_cadastro = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    usuario_cadastro_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    
    # Relacionamentos
    veiculo = db.relationship('Veiculo', backref='abastecimentos')
    motorista = db.relationship('Motorista', backref='abastecimentos')
    usuario_cadastro = db.relationship('Usuario', backref='abastecimentos_cadastrados')
    
    @property
    def consumo_medio(self):
        """Calcula consumo médio desde o último abastecimento"""
        try:
            ultimo_abastecimento = Abastecimento.query.filter(
                Abastecimento.veiculo_id == self.veiculo_id,
                Abastecimento.data_abastecimento < self.data_abastecimento,
                Abastecimento.id != self.id
            ).order_by(Abastecimento.data_abastecimento.desc()).first()
            
            if ultimo_abastecimento and ultimo_abastecimento.tanque_cheio and self.tanque_cheio:
                km_rodados = self.km_atual - ultimo_abastecimento.km_atual
                if km_rodados > 0 and self.litros_abastecidos > 0:
                    return round(km_rodados / float(self.litros_abastecidos), 2)
            
            return None
        except:
            return None



class FaturaTerceirizado(db.Model):
    __tablename__ = 'faturas_terceirizados'
    
    id = db.Column(db.Integer, primary_key=True)
    veiculo_id = db.Column(db.Integer, db.ForeignKey('veiculos.id'), nullable=False)
    
    # Período da fatura
    mes_referencia = db.Column(db.Integer, nullable=False)  # 1-12
    ano_referencia = db.Column(db.Integer, nullable=False)  # 2024, 2025...
    
    # Valores
    total_km = db.Column(db.Integer, default=0)
    total_diarias = db.Column(db.Integer, default=0)
    valor_km_total = db.Column(db.Numeric(10, 2), default=0)
    valor_diarias_total = db.Column(db.Numeric(10, 2), default=0)
    valor_combustivel = db.Column(db.Numeric(10, 2), default=0)
    valor_total = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    
    # Controle de pagamento
    status = db.Column(db.String(20), nullable=False, default='pendente')  # pendente, pago, cancelado
    data_vencimento = db.Column(db.Date)
    data_pagamento = db.Column(db.Date)
    numero_nota_fiscal = db.Column(db.String(50))
    
    # Observações
    observacoes = db.Column(db.Text)
    data_geracao = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    usuario_gerou_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    
    # Relacionamentos
    veiculo = db.relationship('Veiculo', backref='faturas')
    usuario_gerou = db.relationship('Usuario', backref='faturas_geradas')
    
    @property
    def periodo_referencia(self):
        """Retorna período formatado (MM/AAAA)"""
        return f"{self.mes_referencia:02d}/{self.ano_referencia}"
    
    def gerar_usos_periodo(self):
        """Retorna lista de usos do veículo no período da fatura"""
        from calendar import monthrange
        
        # Primeiro e último dia do mês
        primeiro_dia = date(self.ano_referencia, self.mes_referencia, 1)
        ultimo_dia_num = monthrange(self.ano_referencia, self.mes_referencia)[1]
        ultimo_dia = date(self.ano_referencia, self.mes_referencia, ultimo_dia_num)
        
        return UsoVeiculo.query.filter(
            UsoVeiculo.veiculo_id == self.veiculo_id,
            UsoVeiculo.data_uso.between(primeiro_dia, ultimo_dia),
            UsoVeiculo.status == 'concluido'
        ).order_by(UsoVeiculo.data_uso).all()

  
# ===== SISTEMA DE BACKUP AUTOMÁTICO ===== INICIO
class SistemaBackup:
    def __init__(self, app, db):
        self.app = app
        self.db = db
        self.backup_dir = os.path.join(os.path.dirname(__file__), 'backups')
        os.makedirs(self.backup_dir, exist_ok=True)
        self.criar_estrutura_diretorios()  # ← ADICIONAR ESTA LINHA
        
    def iniciar_agendamento(self):
        """Inicia agendamento automático de backups CORRIGIDO"""
        try:
            # Backup diário às 02:00
            schedule.every().day.at("02:00").do(self.backup_automatico_diario)
            
            # ✅ CORREÇÃO: Verificar backup mensal todo dia às 03:00
            schedule.every().day.at("03:00").do(self.verificar_backup_mensal)
            
            # Limpeza automática toda segunda-feira às 04:00
            schedule.every().monday.at("04:00").do(self.limpeza_automatica)
            
            print("✅ Sistema de backup automático iniciado!")
            
        except Exception as e:
            print(f"❌ Erro ao iniciar agendamento: {e}")
    
    def verificar_backup_mensal(self):
        """Verifica se deve fazer backup mensal (dia 1 do mês)"""
        try:
            hoje = datetime.now()
            if hoje.day == 1:  # Primeiro dia do mês
                print("📅 Executando backup mensal...")
                self.backup_automatico_mensal()
        except Exception as e:
            print(f"❌ Erro no backup mensal: {e}")
    
    def backup_automatico_diario(self):
        """Executa backup diário automático"""
        print("✅ Backup diário executado!")
    
    def backup_automatico_mensal(self):
        """Executa backup mensal automático"""
        print("✅ Backup mensal executado!")
    

    # ========= MÉTODOS ADICIONADOS =========
    def backup_banco_dados(self, tipo='manual'):
        """Realiza backup do banco de dados"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            if tipo == 'diario':
                backup_subdir = 'diarios'
            elif tipo == 'mensal':
                backup_subdir = 'mensais'
            else:
                backup_subdir = 'manuais'
            
            # Criar subdiretório se não existir
            subdir_path = os.path.join(self.backup_dir, backup_subdir)
            os.makedirs(subdir_path, exist_ok=True)
            
            db_source = os.path.join(os.path.dirname(__file__), 'db', 'transporte_pacientes.db')
            backup_filename = f'backup_db_{timestamp}.db'
            backup_path = os.path.join(subdir_path, backup_filename)
            
            # Copiar banco de dados
            shutil.copy2(db_source, backup_path)
            
            # Criar ZIP
            zip_filename = f'backup_completo_{timestamp}.zip'
            zip_path = os.path.join(subdir_path, zip_filename)
            
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                zipf.write(backup_path, backup_filename)
                
                info = {
                    'data_backup': timestamp,
                    'tipo': tipo,
                    'tamanho_db': os.path.getsize(backup_path),
                    'versao_sistema': '1.0.0',
                    'usuario': 'sistema'
                }
                
                zipf.writestr('info_backup.json', json.dumps(info, indent=2))
            
            # Remover arquivo temporário
            os.remove(backup_path)
            
            # Registrar no histórico
            self.registrar_backup(zip_filename, tipo, os.path.getsize(zip_path))
            
            return {
                'sucesso': True,
                'arquivo': zip_filename,
                'caminho': zip_path,
                'tamanho': os.path.getsize(zip_path)
            }
            
        except Exception as e:
            return {
                'sucesso': False,
                'erro': str(e)
            }
    
    def exportar_para_excel(self):
        """Exporta dados para Excel"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'dados_completos_{timestamp}.xlsx'
            
            # Criar subdiretório se não existir
            excel_dir = os.path.join(self.backup_dir, 'excel')
            os.makedirs(excel_dir, exist_ok=True)
            
            filepath = os.path.join(excel_dir, filename)
            
            wb = Workbook()
            ws = wb.active
            ws.title = "Backup Dados"
            ws.append(['Backup realizado em', timestamp])
            ws.append(['Sistema', 'Transporte de Pacientes'])
            ws.append(['Versão', '1.0.0'])
            
            wb.save(filepath)
            self.registrar_backup(filename, 'excel', os.path.getsize(filepath))
            
            return {
                'sucesso': True,
                'arquivo': filename,
                'caminho': filepath,
                'tamanho': os.path.getsize(filepath)
            }
            
        except Exception as e:
            return {
                'sucesso': False,
                'erro': str(e)
            }
    
    def registrar_backup(self, arquivo, tipo, tamanho):
        """Registra backup no histórico"""
        try:
            historico_path = os.path.join(self.backup_dir, 'historico_backups.json')
            
            if os.path.exists(historico_path):
                with open(historico_path, 'r', encoding='utf-8') as f:
                    historico = json.load(f)
            else:
                historico = []
            
            novo_backup = {
                'arquivo': arquivo,
                'data': datetime.now().isoformat(),
                'tipo': tipo,
                'tamanho': tamanho,
                'tamanho_mb': round(tamanho / (1024*1024), 2)
            }
            
            historico.append(novo_backup)
            
            # Manter apenas últimos 100 registros
            if len(historico) > 100:
                historico = historico[-100:]
            
            with open(historico_path, 'w', encoding='utf-8') as f:
                json.dump(historico, f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            print(f"Erro ao registrar backup: {e}")
    
    def obter_historico_backups(self):
        """Retorna histórico de backups"""
        try:
            historico_path = os.path.join(self.backup_dir, 'historico_backups.json')
            
            if os.path.exists(historico_path):
                with open(historico_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                return []
                
        except Exception as e:
            print(f"Erro ao obter histórico: {e}")
            return []
    
    def criar_estrutura_diretorios(self):
        """Cria estrutura de diretórios para backups"""
        directories = [
            self.backup_dir,
            os.path.join(self.backup_dir, 'diarios'),
            os.path.join(self.backup_dir, 'mensais'),
            os.path.join(self.backup_dir, 'excel'),
            os.path.join(self.backup_dir, 'manuais')
        ]
        
        for directory in directories:
            os.makedirs(directory, exist_ok=True)
            
    def limpeza_automatica(self):
        """Remove backups antigos conforme política de retenção"""
        try:
            print("🧹 Iniciando limpeza automática de backups antigos...")

            agora = datetime.now()

            # Políticas de retenção
            limites = {
                'diarios': agora - timedelta(days=30),
                'mensais': agora - timedelta(days=365),
                'excel': agora - timedelta(days=90),
                'manuais': agora - timedelta(days=180)  # extra: 6 meses para manuais
            }

            arquivos_removidos = 0

            # Varre todas as pastas de backup
            for pasta, limite_data in limites.items():
                pasta_path = os.path.join(self.backup_dir, pasta)
                if not os.path.exists(pasta_path):
                    continue

                for arquivo in os.listdir(pasta_path):
                    arquivo_path = os.path.join(pasta_path, arquivo)
                    if os.path.isfile(arquivo_path):
                        mod_time = datetime.fromtimestamp(os.path.getmtime(arquivo_path))
                        if mod_time < limite_data:
                            os.remove(arquivo_path)
                            arquivos_removidos += 1
                            dias_passados = (agora - mod_time).days
                            print(f"🗑️ Removido: {arquivo} ({pasta}, idade: {dias_passados} dias)")

            print(f"✅ Limpeza concluída: {arquivos_removidos} arquivos removidos")
            return arquivos_removidos

        except Exception as e:
            print(f"❌ Erro na limpeza: {e}")
            raise e

# ===== SISTEMA DE BACKUP AUTOMÁTICO ===== FINAL
# ===== SISTEMA DE NOTIFICAÇÃO POR WHATSAPP ===== INICIO
try:
    import pywhatkit as kit
except Exception as e:
    kit = None
    print(f'[AVISO] pywhatkit indisponivel ({e}). WhatsApp Web desativado.')
import threading
import queue
from datetime import datetime, timedelta
import re


def whatsapp_bloqueado_por_simulacao():
    """STP_BLOQUEAR_WHATSAPP=1 → nenhum envio real (teste/simulação)."""
    return (os.environ.get('STP_BLOQUEAR_WHATSAPP') or '').strip().lower() in (
        '1', 'true', 'sim', 'yes', 'on',
    )


def telefone_whatsapp_paciente(paciente):
    """Telefone preferencial para WhatsApp: celular > legado > residencial."""
    if not paciente:
        return ''
    for cand in (
        getattr(paciente, 'tel_cel', None),
        getattr(paciente, 'telefone', None),
        getattr(paciente, 'tel_res', None),
    ):
        if cand and str(cand).strip():
            digitos = re.sub(r'\D', '', str(cand))
            if len(digitos) >= 10:
                return str(cand).strip()
    return ''


def _whatsapp_admin_required():
    """Somente administrador gerencia o módulo WhatsApp."""
    if not current_user.is_authenticated or current_user.tipo_usuario != 'administrador':
        return False
    return True


WHATSAPP_TELEFONE_CENTRAL = os.environ.get('MUNICIPIO_TELEFONE', '(19) 3872-1234')


class WhatsAppNotificacao:
    def __init__(self, app, db):
        self.app = app
        self.db = db
        self.fila_mensagens = queue.Queue()
        self.ativo = False
        self.thread_worker = None
        self._lock = threading.Lock()
        self.logs_dir = os.path.join(os.path.dirname(__file__), 'logs_whatsapp')
        os.makedirs(self.logs_dir, exist_ok=True)
        
        # Templates de mensagens
        self.templates = {
            'confirmacao_agendamento': f"""
🚑 *TRANSPORTE CONFIRMADO* 🚑

Olá, {{nome_paciente}}!

Seu transporte foi confirmado:
📅 *Data:* {{data_agendamento}}
⏰ *Hora:* {{hora_agendamento}}
🏠 *Origem:* {{endereco_origem}}
🏥 *Destino:* {{endereco_destino}}
🚗 *Tipo:* {{tipo_transporte}}

ℹ️ *Instruções importantes:*
• Aguarde o motorista no local combinado
• Tenha seus documentos em mãos
• Em caso de emergência: {WHATSAPP_TELEFONE_CENTRAL}

_Prefeitura Municipal de Cosmópolis_
_Secretaria de Saúde_
            """,
            
            'lembrete_1_dia': f"""
🔔 *LEMBRETE DE TRANSPORTE* 🔔

Olá, {{nome_paciente}}!

Lembramos que você tem transporte marcado para *AMANHÃ*:

📅 *Data:* {{data_agendamento}}
⏰ *Hora:* {{hora_agendamento}}
🏥 *Destino:* {{endereco_destino}}

⚠️ *Importante:*
• Esteja pronto 15 minutos antes
• Confirme sua presença: {WHATSAPP_TELEFONE_CENTRAL}
• Cancele com antecedência se necessário

_Prefeitura Municipal de Cosmópolis_
            """,
            
            'motorista_saiu': f"""
🚗 *MOTORISTA A CAMINHO* 🚗

Olá, {{nome_paciente}}!

O motorista saiu para buscá-lo:

👨‍💼 *Motorista:* {{nome_motorista}}
📱 *Telefone:* {{telefone_motorista}}
🚗 *Veículo:* {{veiculo_info}}
⏱️ *Previsão:* {{tempo_estimado}}

🏠 Aguarde no endereço: {{endereco_origem}}

_Em caso de dúvidas, ligue: {WHATSAPP_TELEFONE_CENTRAL}_
            """,
            
            'confirmacao_chegada': f"""
✅ *TRANSPORTE CONCLUÍDO* ✅

Olá, {{nome_paciente}}!

Confirmamos que você chegou ao seu destino:

🏥 *Local:* {{endereco_destino}}
⏰ *Horário de chegada:* {{hora_chegada}}
👨‍💼 *Motorista:* {{nome_motorista}}

🔄 *Para o retorno,* aguarde instruções ou entre em contato conosco.

📞 *Central de Transportes:* {WHATSAPP_TELEFONE_CENTRAL}

_Prefeitura Municipal de Cosmópolis_
_Secretaria de Saúde_
            """,
            
            'status_cancelado': f"""
❌ *TRANSPORTE CANCELADO* ❌

Olá, {{nome_paciente}}!

Informamos que seu transporte foi cancelado:

📅 *Data original:* {{data_agendamento}}
⏰ *Hora original:* {{hora_agendamento}}
🔄 *Motivo:* {{motivo_cancelamento}}

Para reagendar, entre em contato:
📞 {WHATSAPP_TELEFONE_CENTRAL}

_Prefeitura Municipal de Cosmópolis_
            """
        }
    
    def iniciar_servico(self):
        """Inicia o serviço de envio de mensagens (idempotente)."""
        with self._lock:
            if self.ativo and self.thread_worker and self.thread_worker.is_alive():
                print("ℹ️ Serviço WhatsApp já estava ativo")
                return True
            try:
                self.ativo = True
                self.thread_worker = threading.Thread(target=self._processar_fila, daemon=True, name='whatsapp-worker')
                self.thread_worker.start()
                print("✅ Serviço WhatsApp iniciado!")
                return True
            except Exception as e:
                self.ativo = False
                print(f"❌ Erro ao iniciar WhatsApp: {e}")
                return False
    
    def parar_servico(self):
        """Para o serviço de envio"""
        with self._lock:
            self.ativo = False
            worker = self.thread_worker
        if worker and worker.is_alive():
            worker.join(timeout=8)
        print("🛑 Serviço WhatsApp parado!")
    
    def _processar_fila(self):
        """Processa a fila de mensagens"""
        while self.ativo:
            try:
                try:
                    mensagem_data = self.fila_mensagens.get(timeout=5)
                except queue.Empty:
                    continue
                self._enviar_mensagem_agora(mensagem_data)
                self.fila_mensagens.task_done()
            except Exception as e:
                print(f"❌ Erro no processamento: {e}")
                time.sleep(5)
    
    def _enviar_mensagem_agora(self, mensagem_data):
        """Envia mensagem via WhatsApp Web com confirmação reforçada do Enter.

        O pywhatkit.registera sucesso só por abrir a aba e pressionar Enter uma vez;
        em mensagens longas/multilinha ou com foco perdido, o texto fica no campo
        sem chegar ao celular. Aqui reforçamos foco, espera e envio.
        """
        if whatsapp_bloqueado_por_simulacao():
            tel = (mensagem_data or {}).get('telefone', '')
            tipo = (mensagem_data or {}).get('tipo', '')
            print(f'[SIMULAÇÃO] WhatsApp BLOQUEADO — NÃO enviado ({tipo}) → {tel}')
            return False

        telefone = (mensagem_data or {}).get('telefone', '')
        mensagem = (mensagem_data or {}).get('mensagem', '')
        tipo = (mensagem_data or {}).get('tipo', 'desconhecido')
        meta = (mensagem_data or {}).get('meta') or {}
        inicio = time.time()
        try:
            telefone_limpo = self._validar_telefone(telefone)
            if not telefone_limpo:
                self._log_erro(f"Telefone inválido: {telefone}", meta=meta)
                return False

            ok = self._enviar_whatsapp_web_confiavel(telefone_limpo, mensagem)
            duracao_ms = int((time.time() - inicio) * 1000)
            if not ok:
                self._log_erro(
                    f"Falha ao confirmar envio para {telefone_limpo} (WhatsApp Web)",
                    meta=meta,
                )
                return False

            self._log_sucesso(telefone_limpo, tipo, mensagem, meta=meta, duracao_ms=duracao_ms)
            print(f"✅ WhatsApp enviado para {telefone_limpo}")
            return True

        except Exception as e:
            self._log_erro(f"Erro ao enviar para {telefone}: {e}", meta=meta)
            return False

    def _enviar_whatsapp_web_confiavel(self, telefone_e164, mensagem):
        """Abre WhatsApp Web, aguarda carregar e força o envio (Enter / Ctrl+Enter)."""
        import webbrowser
        from urllib.parse import quote
        import pyautogui as pg

        pg.FAILSAFE = False

        # Tempo para o WhatsApp Web carregar (rede/PC lentos precisam de mais)
        wait_time = int(os.environ.get('WHATSAPP_WAIT_TIME', '30'))
        close_time = int(os.environ.get('WHATSAPP_CLOSE_TIME', '5'))
        wait_time = max(wait_time, 20)

        # URL oficial: país+DDD+número SEM o sinal '+'
        phone_url = re.sub(r'[^\d]', '', telefone_e164)
        texto = (mensagem or '').strip()
        url = f'https://web.whatsapp.com/send?phone={phone_url}&text={quote(texto)}'

        print(f'📱 Abrindo WhatsApp Web → {telefone_e164} (aguarde ~{wait_time}s, não mexa no mouse/teclado)')
        webbrowser.open(url)

        # Espera inicial para a aba abrir e o chat carregar
        time.sleep(min(8, wait_time // 2))

        width, height = pg.size()
        # Foco na janela: clique no centro (área do chat)
        pg.click(width / 2, height / 2)
        time.sleep(0.8)

        # Espera restante até o campo de mensagem estar pronto
        restante = max(wait_time - 8, 5)
        time.sleep(restante)

        # Foco explícito na caixa de mensagem (parte inferior do WhatsApp Web)
        pg.click(width / 2, int(height * 0.90))
        time.sleep(0.6)

        # 1ª tentativa: Enter (padrão WhatsApp = enviar)
        pg.press('enter')
        time.sleep(1.2)

        # 2ª tentativa: Enter de novo (caso a 1ª só tenha focado o campo)
        pg.click(width / 2, int(height * 0.90))
        time.sleep(0.3)
        pg.press('enter')
        time.sleep(0.8)

        # 3ª tentativa: Ctrl+Enter (alguns layouts usam Enter = nova linha)
        pg.hotkey('ctrl', 'enter')
        time.sleep(1.0)

        # Fecha a aba do envio para não acumular abas
        time.sleep(close_time)
        try:
            pg.hotkey('ctrl', 'w')
            time.sleep(0.5)
        except Exception:
            pass

        # Também registra no histórico do pywhatkit (compatibilidade)
        try:
            from pywhatkit.core import log as pwk_log
            pwk_log.log_message(_time=time.localtime(), receiver=telefone_e164, message=texto)
        except Exception:
            pass

        return True
    
    def agendar_mensagem(self, telefone, tipo_template, dados, data_envio=None, meta=None):
        """Agenda uma mensagem para envio"""
        try:
            if whatsapp_bloqueado_por_simulacao():
                print(
                    f'[SIMULAÇÃO] WhatsApp BLOQUEADO — mensagem NÃO agendada '
                    f'({tipo_template}) → {telefone}'
                )
                return False

            if data_envio is None:
                data_envio = datetime.now()
            
            telefone_limpo = self._validar_telefone(telefone)
            if not telefone_limpo:
                self._log_erro(f"Telefone inválido ao agendar ({tipo_template}): {telefone}", meta=meta)
                return False
            
            mensagem = self._gerar_mensagem(tipo_template, dados)
            if not mensagem:
                return False
            
            mensagem_data = {
                'telefone': telefone_limpo,
                'mensagem': mensagem,
                'tipo': tipo_template,
                'data_envio': data_envio,
                'dados': dados,
                'meta': meta or {},
            }
            
            if data_envio <= datetime.now():
                self.fila_mensagens.put(mensagem_data)
            else:
                self._agendar_para_futuro(mensagem_data)
            
            return True
            
        except Exception as e:
            print(f"❌ Erro ao agendar mensagem: {e}")
            return False
    
    def _gerar_mensagem(self, tipo_template, dados):
        """Gera mensagem a partir do template"""
        try:
            if tipo_template not in self.templates:
                print(f"❌ Template não encontrado: {tipo_template}")
                return None
            
            template = self.templates[tipo_template]
            mensagem = template.format(**dados)
            return mensagem.strip()
            
        except KeyError as e:
            print(f"❌ Campo faltando no template {tipo_template}: {e}")
            return None
        except Exception as e:
            print(f"❌ Erro ao gerar mensagem: {e}")
            return None
    
    def _validar_telefone(self, telefone):
        """Valida e formata telefone brasileiro para WhatsApp (+55…)."""
        try:
            if not telefone:
                return None
            telefone_limpo = re.sub(r'[^\d]', '', str(telefone))
            
            # Remove zero à esquerda do DDD antigo (0XX…)
            if telefone_limpo.startswith('0') and len(telefone_limpo) in (11, 12):
                telefone_limpo = telefone_limpo[1:]
            
            if len(telefone_limpo) == 11:  # DDD + 9 dígitos (celular)
                return '+55' + telefone_limpo
            if len(telefone_limpo) == 10:  # DDD + 8 dígitos — WhatsApp exige celular; rejeita fixo
                return None
            if len(telefone_limpo) == 13 and telefone_limpo.startswith('55'):
                return '+' + telefone_limpo
            if len(telefone_limpo) == 12 and telefone_limpo.startswith('55'):
                # 55 + DDD + 8 dígitos (fixo) — rejeita
                return None
            if str(telefone).strip().startswith('+') and len(telefone_limpo) >= 12:
                return '+' + telefone_limpo
            return None
            
        except Exception as e:
            print(f"❌ Erro na validação do telefone: {e}")
            return None
    
    def _log_sucesso(self, telefone, tipo, mensagem, meta=None, duracao_ms=None):
        """Registra envio bem-sucedido"""
        try:
            meta = meta or {}
            trecho = (mensagem or '').replace('\n', ' ')[:120]
            log_file = os.path.join(self.logs_dir, f'whatsapp_success_{date.today().strftime("%Y%m%d")}.log')
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(
                    f"{datetime.now().isoformat()} - SUCESSO - tel={telefone} - tipo={tipo}"
                    f" - agendamento_id={meta.get('agendamento_id', '')}"
                    f" - usuario={meta.get('usuario', '')}"
                    f" - ms={duracao_ms if duracao_ms is not None else ''}"
                    f" - msg={trecho}\n"
                )
        except Exception as e:
            print(f"❌ Erro no log: {e}")
    
    def _log_erro(self, erro, meta=None):
        """Registra erros"""
        try:
            meta = meta or {}
            log_file = os.path.join(self.logs_dir, f'whatsapp_errors_{date.today().strftime("%Y%m%d")}.log')
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(
                    f"{datetime.now().isoformat()} - ERRO - {erro}"
                    f" - agendamento_id={meta.get('agendamento_id', '')}"
                    f" - usuario={meta.get('usuario', '')}\n"
                )
        except Exception as e:
            print(f"❌ Erro no log de erro: {e}")
    
    def _agendar_para_futuro(self, mensagem_data):
        """Agenda mensagem para data futura (thread com delay — perde no restart)."""
        def enviar_com_delay():
            agora = datetime.now()
            data_envio = mensagem_data['data_envio']
            delay = (data_envio - agora).total_seconds()
            
            if delay > 0:
                time.sleep(delay)
            if self.ativo:
                self.fila_mensagens.put(mensagem_data)
        
        thread_delay = threading.Thread(target=enviar_com_delay, daemon=True)
        thread_delay.start()
    
    def obter_logs_recentes(self, limite=8):
        """Últimas linhas de sucesso/erro de hoje (para UI)."""
        linhas = []
        hoje = date.today().strftime("%Y%m%d")
        for kind, fname in (
            ('sucesso', f'whatsapp_success_{hoje}.log'),
            ('erro', f'whatsapp_errors_{hoje}.log'),
        ):
            path = os.path.join(self.logs_dir, fname)
            if not os.path.exists(path):
                continue
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    for line in f.readlines()[-limite:]:
                        linhas.append({'tipo': kind, 'texto': line.strip()})
            except Exception:
                pass
        return linhas[-limite:]

    def obter_estatisticas(self):
        """Retorna estatísticas de envio"""
        try:
            hoje = date.today().strftime("%Y%m%d")
            
            # Contar sucessos
            success_file = os.path.join(self.logs_dir, f'whatsapp_success_{hoje}.log')
            sucessos = 0
            if os.path.exists(success_file):
                with open(success_file, 'r', encoding='utf-8') as f:
                    sucessos = len(f.readlines())
            
            # Contar erros
            error_file = os.path.join(self.logs_dir, f'whatsapp_errors_{hoje}.log')
            erros = 0
            if os.path.exists(error_file):
                with open(error_file, 'r', encoding='utf-8') as f:
                    erros = len(f.readlines())
            
            worker_vivo = bool(self.thread_worker and self.thread_worker.is_alive())
            return {
                'sucessos_hoje': sucessos,
                'erros_hoje': erros,
                'fila_pendente': self.fila_mensagens.qsize(),
                'servico_ativo': bool(self.ativo and worker_vivo)
            }
            
        except Exception as e:
            print(f"❌ Erro ao obter estatísticas: {e}")
            return {'sucessos_hoje': 0, 'erros_hoje': 0, 'fila_pendente': 0, 'servico_ativo': False}

from datetime import datetime, timedelta, date
import threading
import time
import schedule

# ===== INTEGRAÇÃO COM AGENDAMENTOS =====
class NotificacaoAgendamento:
    def __init__(self, whatsapp_service):
        self.whatsapp = whatsapp_service

    def _meta(self, agendamento=None):
        usuario = ''
        try:
            if current_user and getattr(current_user, 'is_authenticated', False):
                usuario = getattr(current_user, 'username', '') or str(getattr(current_user, 'id', ''))
        except Exception:
            pass
        return {
            'agendamento_id': getattr(agendamento, 'id', '') if agendamento else '',
            'usuario': usuario,
        }
    
    def notificar_confirmacao(self, agendamento):
        """Envia confirmação de agendamento"""
        telefone = telefone_whatsapp_paciente(agendamento.paciente)
        if not telefone:
            print('⚠️ Confirmação WA ignorada: paciente sem celular válido')
            return False
        dados = {
            'nome_paciente': agendamento.paciente.nome,
            'data_agendamento': agendamento.data.strftime('%d/%m/%Y'),
            'hora_agendamento': agendamento.hora.strftime('%H:%M'),
            'endereco_origem': agendamento.origem,
            'endereco_destino': agendamento.destino,
            'tipo_transporte': formatar_especialidade_exibir(agendamento.tipo_transporte)
        }
        
        return self.whatsapp.agendar_mensagem(
            telefone,
            'confirmacao_agendamento',
            dados,
            meta=self._meta(agendamento),
        )
    
    def agendar_lembrete(self, agendamento):
        """Agenda lembrete para 1 dia antes (14:00). Evitado se o job diário cobrir — mantido por compatibilidade."""
        telefone = telefone_whatsapp_paciente(agendamento.paciente)
        if not telefone:
            return False
        data_lembrete = datetime.combine(agendamento.data, agendamento.hora) - timedelta(days=1)
        data_lembrete = data_lembrete.replace(hour=14, minute=0, second=0, microsecond=0)
        
        dados = {
            'nome_paciente': agendamento.paciente.nome,
            'data_agendamento': agendamento.data.strftime('%d/%m/%Y'),
            'hora_agendamento': agendamento.hora.strftime('%H:%M'),
            'endereco_destino': agendamento.destino
        }
        
        return self.whatsapp.agendar_mensagem(
            telefone,
            'lembrete_1_dia',
            dados,
            data_lembrete,
            meta=self._meta(agendamento),
        )
    
    def notificar_cancelamento(self, agendamento, motivo='Cancelado pela central de transportes'):
        """Notifica cancelamento do transporte."""
        telefone = telefone_whatsapp_paciente(agendamento.paciente)
        if not telefone:
            return False
        dados = {
            'nome_paciente': agendamento.paciente.nome,
            'data_agendamento': agendamento.data.strftime('%d/%m/%Y'),
            'hora_agendamento': agendamento.hora.strftime('%H:%M'),
            'motivo_cancelamento': motivo or 'Cancelado pela central de transportes',
        }
        return self.whatsapp.agendar_mensagem(
            telefone,
            'status_cancelado',
            dados,
            meta=self._meta(agendamento),
        )
    
    def notificar_motorista_saiu(self, uso_veiculo):
        """Notifica que motorista saiu"""
        agendamento = uso_veiculo.agendamento
        if not agendamento or not agendamento.paciente:
            return False
        telefone = telefone_whatsapp_paciente(agendamento.paciente)
        if not telefone:
            return False
        
        dados = {
            'nome_paciente': agendamento.paciente.nome,
            'nome_motorista': uso_veiculo.motorista.nome if uso_veiculo.motorista else '—',
            'telefone_motorista': (uso_veiculo.motorista.telefone if uso_veiculo.motorista else '') or '—',
            'veiculo_info': (
                f"{uso_veiculo.veiculo.marca} {uso_veiculo.veiculo.modelo} - {uso_veiculo.veiculo.placa}"
                if uso_veiculo.veiculo else '—'
            ),
            'tempo_estimado': "15-30 minutos",
            'endereco_origem': uso_veiculo.endereco_origem
        }
        
        return self.whatsapp.agendar_mensagem(
            telefone,
            'motorista_saiu',
            dados,
            meta=self._meta(agendamento),
        )
    
    def notificar_chegada(self, uso_veiculo):
        """Notifica chegada ao destino"""
        agendamento = uso_veiculo.agendamento
        if not agendamento or not agendamento.paciente:
            return False
        telefone = telefone_whatsapp_paciente(agendamento.paciente)
        if not telefone:
            return False
        
        dados = {
            'nome_paciente': agendamento.paciente.nome,
            'endereco_destino': uso_veiculo.endereco_destino,
            'hora_chegada': datetime.now().strftime('%H:%M'),
            'nome_motorista': uso_veiculo.motorista.nome if uso_veiculo.motorista else '—'
        }
        
        return self.whatsapp.agendar_mensagem(
            telefone,
            'confirmacao_chegada',
            dados,
            meta=self._meta(agendamento),
        )

# ===== SISTEMA DE AGENDAMENTO AUTOMÁTICO =====
class AgendadorLembretes:
    def __init__(self, whatsapp_service, db, flask_app=None):
        self.whatsapp = whatsapp_service
        self.db = db
        self.flask_app = flask_app
        self.ativo = False
        self._job_registrado = False
        
    def iniciar_agendador(self):
        """Inicia o agendador de lembretes automáticos"""
        try:
            if not self._job_registrado:
                schedule.every().day.at("14:00").do(self.processar_lembretes_diarios)
                self._job_registrado = True
            
            def executar_agendador_lembretes():
                while self.ativo:
                    schedule.run_pending()
                    time.sleep(60)
            
            if self.ativo:
                print("ℹ️ Agendador de lembretes já ativo")
                return
            self.ativo = True
            thread = threading.Thread(target=executar_agendador_lembretes, daemon=True, name='whatsapp-lembretes')
            thread.start()
            
            print("✅ Agendador de lembretes WhatsApp iniciado!")
            
        except Exception as e:
            print(f"❌ Erro ao iniciar agendador lembretes: {e}")
    
    def processar_lembretes_diarios(self):
        """Processa lembretes para agendamentos de amanhã (apenas ativos)."""
        def _run():
            amanha = date.today() + timedelta(days=1)
            agendamentos = Agendamento.query.filter(
                Agendamento.data == amanha,
                Agendamento.status.in_(['agendado', 'confirmado']),
            ).all()
            
            enviados = 0
            for agendamento in agendamentos:
                telefone = telefone_whatsapp_paciente(agendamento.paciente)
                if not telefone:
                    continue
                dados = {
                    'nome_paciente': agendamento.paciente.nome,
                    'data_agendamento': agendamento.data.strftime('%d/%m/%Y'),
                    'hora_agendamento': agendamento.hora.strftime('%H:%M'),
                    'endereco_destino': agendamento.destino
                }
                if self.whatsapp.agendar_mensagem(
                    telefone,
                    'lembrete_1_dia',
                    dados,
                    meta={'agendamento_id': agendamento.id, 'usuario': 'agendador'},
                ):
                    enviados += 1
            
            print(f"✅ {enviados} lembretes automáticos enviados para amanhã ({amanha.strftime('%d/%m/%Y')})")

        try:
            if self.flask_app is not None:
                with self.flask_app.app_context():
                    _run()
            else:
                _run()
        except Exception as e:
            print(f"❌ Erro ao processar lembretes diários: {e}")
    
    def parar_agendador(self):
        """Para o agendador"""
        self.ativo = False

# ===== SISTEMA DE NOTIFICAÇÃO POR WHATSAPP ===== FINAL

@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(Usuario, int(user_id))
    except:
        return None

def verificar_e_criar_banco():
    """Verifica se o banco existe e cria se necessário"""
    basedir = os.path.abspath(os.path.dirname(__file__))
    db_dir = os.path.join(basedir, 'db')
    db_path = os.path.join(db_dir, 'transporte_pacientes.db')
    
    print(f"🔍 Verificando banco em: {db_path}")
    
    # Criar diretório se não existir
    if not os.path.exists(db_dir):
        print(f"📁 Criando diretório: {db_dir}")
        os.makedirs(db_dir, exist_ok=True)
    
    # Verificar se o banco existe
    if not os.path.exists(db_path):
        print("❌ Banco de dados não encontrado. Criando automaticamente...")
        criar_banco_e_usuario()
    else:
        print(f"✅ Banco de dados encontrado: {db_path}")
        verificar_usuario_admin()
        migrar_paciente_novos_campos()
        migrar_enderecos_pacientes_estruturados()
        migrar_motorista_novos_campos()
        migrar_telefones_paciente()
        migrar_frotas()
        migrar_numero_frota_veiculo()
        migrar_acompanhantes()
        migrar_parentescos()
        migrar_especialidade_agendamento()
        migrar_cnes_estabelecimentos()
    
    return db_path

def criar_banco_e_usuario():
    """Cria o banco e o usuário administrador"""
    try:
        # Criar as tabelas
        db.create_all()
        print("✅ Tabelas criadas no banco de dados")
        migrar_telefones_paciente()
        migrar_frotas()
        migrar_numero_frota_veiculo()
        migrar_paciente_novos_campos()
        migrar_enderecos_pacientes_estruturados()
        migrar_motorista_novos_campos()
        migrar_acompanhantes()
        migrar_parentescos()
        migrar_especialidade_agendamento()
        migrar_cnes_estabelecimentos()
        
        # Criar usuário admin
        admin = Usuario(
            username='admin',
            nome_completo='Administrador do Sistema',
            email='admin@cosmopolis.sp.gov.br',
            tipo_usuario='administrador',
            ativo=True
        )
        admin.set_password('admin123')
        
        db.session.add(admin)
        db.session.commit()
        print("✅ Usuário administrador criado: admin / admin123")
        
    except Exception as e:
        print(f"❌ Erro ao criar banco: {e}")
        db.session.rollback()

def verificar_usuario_admin():
    """Verifica se o usuário admin existe e tem hash válido"""
    try:
        admin = Usuario.query.filter_by(username='admin').first()
        if not admin:
            print("❌ Usuário admin não encontrado. Criando...")
            criar_banco_e_usuario()
        else:
            if not admin.check_password('admin123'):
                print("❌ Hash do usuário admin inválido. Resetando senha...")
                admin.set_password('admin123')
                db.session.commit()
                print("✅ Senha do usuário admin resetada para: admin123")
            else:
                print("✅ Usuário admin válido encontrado")
    except Exception as e:
        print(f"❌ Erro ao verificar usuário admin: {e}")

# Função para escapar strings para JavaScript
def escape_js_string(s):
    """Escapa uma string para uso seguro em JavaScript"""
    if s is None:
        return ''
    return str(s).replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'").replace('\n', '\\n').replace('\r', '\\r')


def aplicar_filtro_busca(query, termo, *campos):
    """Aplica filtro de texto em múltiplos campos (OR)."""
    from sqlalchemy import or_

    termo = (termo or '').strip()
    if not termo or not campos:
        return query
    like = f'%{termo}%'
    return query.filter(or_(*[campo.ilike(like) for campo in campos]))


def parse_data_br(valor):
    """Converte data em formato brasileiro ou ISO para date."""
    if not valor or not str(valor).strip():
        return None
    valor = str(valor).strip()
    for fmt in ('%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(valor, fmt).date()
        except ValueError:
            continue
    return None


def formatar_tel_cel(valor):
    """Formata celular brasileiro: (00) 00000-0000"""
    digitos = re.sub(r'\D', '', valor or '')[:11]
    if not digitos:
        return ''
    if len(digitos) <= 2:
        return f'({digitos}'
    if len(digitos) <= 7:
        return f'({digitos[:2]}) {digitos[2:]}'
    return f'({digitos[:2]}) {digitos[2:7]}-{digitos[7:]}'


def formatar_tel_res(valor):
    """Formata telefone fixo brasileiro: (00) 0000-0000"""
    digitos = re.sub(r'\D', '', valor or '')[:10]
    if not digitos:
        return ''
    if len(digitos) <= 2:
        return f'({digitos}'
    if len(digitos) <= 6:
        return f'({digitos[:2]}) {digitos[2:]}'
    return f'({digitos[:2]}) {digitos[2:6]}-{digitos[6:]}'


def telefone_e_celular(valor):
    digitos = re.sub(r'\D', '', valor or '')
    return len(digitos) >= 11 or (len(digitos) == 10 and digitos[2] == '9')


def telefones_paciente_exibir(paciente):
    """Retorna (celular, residencial) para exibição, com fallback no campo legado."""
    cel = paciente.tel_cel or ''
    res = paciente.tel_res or ''
    if not cel and not res and paciente.telefone:
        if telefone_e_celular(paciente.telefone):
            cel = formatar_tel_cel(paciente.telefone)
        else:
            res = formatar_tel_res(paciente.telefone)
    return cel or '—', res or '—'


def telefones_paciente_form(paciente):
    """Retorna (celular, residencial) para formulários de edição."""
    cel = paciente.tel_cel or ''
    res = paciente.tel_res or ''
    if not cel and not res and paciente.telefone:
        if telefone_e_celular(paciente.telefone):
            cel = formatar_tel_cel(paciente.telefone)
        else:
            res = formatar_tel_res(paciente.telefone)
    return cel, res


def aplicar_telefones_paciente(paciente, tel_cel, tel_res):
    """Persiste celular/residencial e mantém campo legado para integrações."""
    paciente.tel_cel = formatar_tel_cel(tel_cel) if tel_cel else None
    paciente.tel_res = formatar_tel_res(tel_res) if tel_res else None
    principal = paciente.tel_cel or paciente.tel_res or ''
    paciente.telefone = principal[:15]


def migrar_telefones_paciente():
    """Adiciona colunas tel_cel/tel_res e migra dados do campo telefone."""
    from sqlalchemy import inspect, text

    try:
        insp = inspect(db.engine)
        cols = [c['name'] for c in insp.get_columns('pacientes')]
        if 'tel_cel' not in cols:
            with db.engine.begin() as conn:
                conn.execute(text('ALTER TABLE pacientes ADD COLUMN tel_cel VARCHAR(16)'))
                conn.execute(text('ALTER TABLE pacientes ADD COLUMN tel_res VARCHAR(15)'))
            print('✅ Colunas Tel Cel / Tel Resi criadas')

        alterados = 0
        for paciente in Paciente.query.all():
            if paciente.tel_cel or paciente.tel_res:
                continue
            if not paciente.telefone:
                continue
            if telefone_e_celular(paciente.telefone):
                paciente.tel_cel = formatar_tel_cel(paciente.telefone)
            else:
                paciente.tel_res = formatar_tel_res(paciente.telefone)
            alterados += 1
        if alterados:
            db.session.commit()
            print(f'✅ Telefones migrados para {alterados} paciente(s)')
    except Exception as e:
        db.session.rollback()
        print(f'⚠️ Migração telefones paciente: {e}')


def cpf_digits(value):
    """Extrai só os dígitos do CPF (até 11)."""
    if value is None:
        return ''
    s = str(value).strip()
    if s.endswith('.0'):
        s = s[:-2]
    s = re.sub(r'\D', '', s)
    if not s or s == '0':
        return ''
    return s.zfill(11) if len(s) <= 11 else s[:11]


def calc_cpf_check(digits9):
    """Calcula os 2 dígitos verificadores do CPF."""
    def dv(nums, start):
        s = sum(int(n) * w for n, w in zip(nums, range(start, 1, -1)))
        r = (s * 10) % 11
        return '0' if r == 10 else str(r)

    return dv(digits9, 10) + dv(digits9 + dv(digits9, 10), 11)


def validar_cpf_digits(d):
    """Valida CPF pelos dígitos verificadores (algoritmo Receita Federal)."""
    if len(d) != 11 or d == d[0] * 11:
        return False
    return calc_cpf_check(d[:9]) == d[9:]


def format_cpf(digits11):
    d = digits11.zfill(11)
    return f'{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}'


def validar_e_formatar_cpf(valor):
    """Retorna (cpf_formatado, None) ou (None, mensagem_erro)."""
    d = cpf_digits(valor)
    if len(d) != 11:
        return None, 'CPF deve conter 11 dígitos.'
    if not validar_cpf_digits(d):
        return None, 'CPF inválido. Verifique os números digitados.'
    return format_cpf(d), None


def cns_digits(value):
    """Extrai só os dígitos do CNS (até 15)."""
    if value is None:
        return ''
    s = re.sub(r'\D', '', str(value).strip())
    return s[:15]


def validar_cns(cns):
    """Valida o Cartão Nacional de Saúde (CNS) - algoritmo oficial de 15 dígitos."""
    d = cns_digits(cns)
    if len(d) != 15:
        return False
    # O primeiro dígito deve ser 1, 2, 7, 8 ou 9
    if d[0] not in '12789':
        return False
    try:
        soma = sum(int(d[i]) * (15 - i) for i in range(15))
        return soma % 11 == 0
    except (ValueError, IndexError):
        return False


def format_cns(digits15):
    """Formata CNS no padrão 000 0000 0000 0000."""
    d = digits15.zfill(15)
    return f'{d[:3]} {d[3:7]} {d[7:11]} {d[11:]}'


def validar_e_formatar_cns(valor):
    """Retorna (cns_formatado, None) ou (None, mensagem_erro)."""
    d = cns_digits(valor)
    if len(d) != 15:
        return None, 'Número do Cartão SUS inválido.'
    if not validar_cns(d):
        return None, 'Número do Cartão SUS inválido.'
    return format_cns(d), None


def validar_cpf_simples(cpf):
    """Valida CPF e retorna apenas True/False (para uso inline)."""
    d = cpf_digits(cpf)
    return len(d) == 11 and validar_cpf_digits(d)


def buscar_motorista_por_cpf(cpf_valor, excluir_id=None):
    """Busca motorista pelo CPF (ignora máscara)."""
    alvo = cpf_digits(cpf_valor)
    if not alvo:
        return None
    for motorista in Motorista.query.all():
        if excluir_id and motorista.id == excluir_id:
            continue
        if cpf_digits(motorista.cpf) == alvo:
            return motorista
    return None


def html_script_cpf_validacao():
    """Máscara e validação de CPF no cliente (mesmo algoritmo do servidor)."""
    return '''
        <style>
            #cpf-status {
                display: block;
                margin-top: 0.25rem;
                font-size: 0.875rem;
                transition: color 0.2s ease;
            }
            #cpf-status.cpf-invalido {
                color: var(--danger-color) !important;
                font-weight: 600;
                animation: cpfPulseInvalido 2.2s ease-in-out infinite;
            }
            #cpf-status.cpf-valido { color: var(--success-color) !important; animation: none; }
            #cpf-status.cpf-pendente { color: var(--warning-color) !important; animation: none; }
            @keyframes cpfPulseInvalido {
                0%, 100% { opacity: 1; }
                50% { opacity: 0.35; }
            }
        </style>
        <script>
        (function() {
            function cpfDigitos(v) { return (v || '').replace(/\\D/g, '').slice(0, 11); }
            function cpfValido(d) {
                if (d.length !== 11 || /^(\\d)\\1{10}$/.test(d)) return false;
                var s = 0, i, r, d1, d2;
                for (i = 0; i < 9; i++) s += parseInt(d[i], 10) * (10 - i);
                r = (s * 10) % 11; d1 = r === 10 ? 0 : r;
                if (d1 !== parseInt(d[9], 10)) return false;
                s = 0;
                for (i = 0; i < 10; i++) s += parseInt(d[i], 10) * (11 - i);
                r = (s * 10) % 11; d2 = r === 10 ? 0 : r;
                return d2 === parseInt(d[10], 10);
            }
            function mascaraCPF(v) {
                v = cpfDigitos(v);
                if (v.length <= 3) return v;
                if (v.length <= 6) return v.slice(0, 3) + '.' + v.slice(3);
                if (v.length <= 9) return v.slice(0, 3) + '.' + v.slice(3, 6) + '.' + v.slice(6);
                return v.slice(0, 3) + '.' + v.slice(3, 6) + '.' + v.slice(6, 9) + '-' + v.slice(9);
            }
            function setStatusCPF(status, tipo, texto) {
                status.classList.remove('cpf-valido', 'cpf-invalido', 'cpf-pendente');
                status.style.color = '';
                if (tipo) status.classList.add(tipo);
                status.textContent = texto;
            }
            function atualizarStatusCPF() {
                var input = document.getElementById('cpf');
                var status = document.getElementById('cpf-status');
                if (!input || !status) return true;
                var d = cpfDigitos(input.value);
                if (!d.length) {
                    setStatusCPF(status, null, '');
                    return false;
                }
                if (d.length < 11) {
                    setStatusCPF(status, 'cpf-pendente', 'Digite os 11 dígitos do CPF');
                    return false;
                }
                if (cpfValido(d)) {
                    setStatusCPF(status, 'cpf-valido', 'CPF válido');
                    return true;
                }
                setStatusCPF(status, 'cpf-invalido', 'CPF inválido');
                return false;
            }
            var cpfInput = document.getElementById('cpf');
            if (cpfInput) {
                cpfInput.addEventListener('input', function(e) {
                    e.target.value = mascaraCPF(e.target.value);
                    atualizarStatusCPF();
                });
                cpfInput.addEventListener('blur', atualizarStatusCPF);
                if (cpfDigitos(cpfInput.value).length === 11) atualizarStatusCPF();
            }
            var form = document.querySelector('form');
            if (form) {
                form.addEventListener('submit', function(e) {
                    if (!atualizarStatusCPF()) {
                        e.preventDefault();
                        alert('Informe um CPF válido antes de salvar.');
                        document.getElementById('cpf').focus();
                    }
                });
            }
        })();
        </script>
    '''


def html_validacao_cns():
    """Máscara e validação de CNS no cliente (mesmo algoritmo do servidor)."""
    return '''
        <style>
            #cns-status {
                display: block;
                margin-top: 0.25rem;
                font-size: 0.875rem;
                transition: color 0.2s ease;
            }
            #cns-status.cns-invalido {
                color: var(--danger-color) !important;
                font-weight: 600;
            }
            #cns-status.cns-valido { color: var(--success-color) !important; }
            #cns-status.cns-pendente { color: var(--warning-color) !important; }
        </style>
        <script>
        (function() {
            function cnsDigitos(v) { return (v || '').replace(/\\D/g, '').slice(0, 15); }
            function cnsValido(d) {
                if (d.length !== 15) return false;
                if ('12789'.indexOf(d[0]) === -1) return false;
                var soma = 0;
                for (var i = 0; i < 15; i++) soma += parseInt(d[i], 10) * (15 - i);
                return soma % 11 === 0;
            }
            function mascaraCNS(v) {
                v = cnsDigitos(v);
                if (v.length <= 3) return v;
                if (v.length <= 7) return v.slice(0, 3) + ' ' + v.slice(3);
                if (v.length <= 11) return v.slice(0, 3) + ' ' + v.slice(3, 7) + ' ' + v.slice(7);
                return v.slice(0, 3) + ' ' + v.slice(3, 7) + ' ' + v.slice(7, 11) + ' ' + v.slice(11);
            }
            function setStatusCNS(status, tipo, texto) {
                status.classList.remove('cns-valido', 'cns-invalido', 'cns-pendente');
                status.style.color = '';
                if (tipo) status.classList.add(tipo);
                status.textContent = texto;
            }
            function atualizarStatusCNS() {
                var input = document.getElementById('cns');
                var status = document.getElementById('cns-status');
                if (!input || !status) return true;
                var d = cnsDigitos(input.value);
                if (!d.length) {
                    setStatusCNS(status, null, '');
                    return true;
                }
                if (d.length < 15) {
                    setStatusCNS(status, 'cns-pendente', 'Digite os 15 dígitos do Cartão SUS');
                    return false;
                }
                if (cnsValido(d)) {
                    setStatusCNS(status, 'cns-valido', 'Cartão SUS válido');
                    return true;
                }
                setStatusCNS(status, 'cns-invalido', 'Cartão SUS inválido');
                return false;
            }
            var cnsInput = document.getElementById('cns');
            if (cnsInput) {
                cnsInput.addEventListener('input', function(e) {
                    e.target.value = mascaraCNS(e.target.value);
                    atualizarStatusCNS();
                });
                cnsInput.addEventListener('blur', atualizarStatusCNS);
            }
        })();
        </script>
    '''


def html_campo_rg(name='ac_rg', valor='', required=False, field_id=None, label='RG'):
    """Campo RG padronizado: máscara 99.999.999-9, placeholder e status."""
    from html import escape
    fid = field_id or name
    req_attr = ' required' if required else ''
    req_data = ' data-rg-required="1"' if required else ''
    req_mark = ' <span class="required-mark" aria-hidden="true">*</span>' if required else ''
    return f'''
    <div class="form-group">
      <label for="{escape(fid)}">{escape(label)}{req_mark}</label>
      <input type="text" id="{escape(fid)}" name="{escape(name)}"
             class="stp-rg" data-mask="rg"{req_data}
             value="{escape(format_rg(valor))}"
             placeholder="{escape(RG_PLACEHOLDER)}"
             maxlength="12" inputmode="text" autocomplete="off"{req_attr}>
      <small class="stp-rg-status" aria-live="polite"></small>
    </div>
    '''


def extrair_numero_frota_observacoes(observacoes):
    """Extrai número de frota legado das observações do veículo."""
    if not observacoes:
        return None
    import re
    m = re.search(r'N[uú]mero de frota Access:\s*(\S+)', str(observacoes), re.I)
    return m.group(1) if m else None


def numero_frota_exibir(veiculo):
    """Número de frota para exibição (planilha Daniel), não a placa placeholder."""
    if not veiculo:
        return '—'
    if veiculo.numero_frota:
        return veiculo.numero_frota
    extraido = extrair_numero_frota_observacoes(veiculo.observacoes)
    if extraido:
        return extraido
    return veiculo.placa or '—'


def migrar_numero_frota_veiculo():
    """Adiciona coluna numero_frota e preenche a partir das observações Access."""
    from sqlalchemy import inspect, text

    try:
        insp = inspect(db.engine)
        cols = [c['name'] for c in insp.get_columns('veiculos')]
        if 'numero_frota' not in cols:
            with db.engine.begin() as conn:
                conn.execute(text('ALTER TABLE veiculos ADD COLUMN numero_frota VARCHAR(20)'))
            print('✅ Coluna numero_frota criada em veiculos')

        alterados = 0
        for veiculo in Veiculo.query.all():
            if veiculo.numero_frota:
                continue
            extraido = extrair_numero_frota_observacoes(veiculo.observacoes)
            if extraido:
                veiculo.numero_frota = extraido
                alterados += 1
        if alterados:
            db.session.commit()
            print(f'✅ Número de frota preenchido em {alterados} veículo(s)')
    except Exception as e:
        db.session.rollback()
        print(f'⚠️ Migração numero_frota veículos: {e}')


def migrar_paciente_novos_campos():
    """Adiciona colunas de endereço e condição especial em pacientes."""
    from sqlalchemy import inspect, text
    try:
        insp = inspect(db.engine)
        cols = [c['name'] for c in insp.get_columns('pacientes')]
        novas = {
            'logradouro': 'VARCHAR(200)',
            'numero': 'VARCHAR(10)',
            'bairro': 'VARCHAR(100)',
            'complemento': 'VARCHAR(200)',
            'ponto_referencia': 'VARCHAR(200)',
            'ponto_embarque': 'VARCHAR(200)',
            'condicao_especial': 'BOOLEAN DEFAULT 0 NOT NULL',
            'condicao_paciente': 'VARCHAR(120)',
            'condicao_outros': 'VARCHAR(255)',
        }
        for col, tipo in novas.items():
            if col not in cols:
                with db.engine.begin() as conn:
                    conn.execute(text(f'ALTER TABLE pacientes ADD COLUMN {col} {tipo}'))
                print(f'✅ Coluna {col} criada em pacientes')
        # Compatibilidade: copia ponto_referencia → ponto_embarque quando legado
        cols2 = [c['name'] for c in inspect(db.engine).get_columns('pacientes')]
        if 'ponto_embarque' in cols2 and 'ponto_referencia' in cols2:
            with db.engine.begin() as conn:
                r = conn.execute(text(
                    "UPDATE pacientes SET ponto_embarque = ponto_referencia "
                    "WHERE (ponto_embarque IS NULL OR TRIM(ponto_embarque) = '') "
                    "AND ponto_referencia IS NOT NULL AND TRIM(ponto_referencia) != ''"
                ))
                n = r.rowcount if r.rowcount is not None and r.rowcount >= 0 else 0
                if n:
                    print(f'✅ ponto_embarque preenchido a partir de ponto_referencia em {n} paciente(s)')
    except Exception as e:
        print(f'⚠️ Migração pacientes: {e}')


def migrar_enderecos_pacientes_estruturados():
    """
    Preenche logradouro/numero/bairro/complemento a partir do texto legado em
    pacientes.endereco (e de logradouro “tudo junto”), sem apagar endereco.
    """
    try:
        atualizados = 0
        for pac in Paciente.query.all():
            log = (pac.logradouro or '').strip()
            num = (pac.numero or '').strip()
            bai = (pac.bairro or '').strip()
            comp = (getattr(pac, 'complemento', None) or '').strip()
            end_txt = (pac.endereco or '').strip()

            precisa = (not log or not num) or (',' in log and not num)
            if not precisa:
                continue

            fonte = end_txt if end_txt else log
            if not fonte:
                continue

            log2, num2, bai2, comp2 = partir_endereco_completo(fonte)
            mudou = False
            if not log and log2:
                pac.logradouro = log2[:200]
                mudou = True
            elif log and ',' in log and not num and log2:
                pac.logradouro = log2[:200]
                mudou = True
            if not num and num2:
                pac.numero = num2[:10]
                mudou = True
            if not bai and bai2:
                pac.bairro = bai2[:100]
                mudou = True
            if not comp and comp2:
                pac.complemento = comp2[:200]
                mudou = True
            if mudou:
                # Mantém endereco composto coerente com os campos
                composto = compor_endereco_paciente(
                    pac.logradouro, pac.numero, pac.bairro, pac.complemento
                )
                if composto:
                    pac.endereco = composto
                atualizados += 1
        if atualizados:
            db.session.commit()
            print(f'✅ Endereços estruturados preenchidos em {atualizados} paciente(s)')
    except Exception as e:
        db.session.rollback()
        print(f'⚠️ Migração endereços estruturados: {e}')


def migrar_acompanhantes():
    """Cria tabela acompanhantes e colunas de vínculo no agendamento."""
    from sqlalchemy import inspect, text
    try:
        db.create_all()
        insp = inspect(db.engine)
        tabelas = insp.get_table_names()
        if 'acompanhantes' not in tabelas:
            with db.engine.begin() as conn:
                conn.execute(text('''
                    CREATE TABLE acompanhantes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        paciente_id INTEGER NOT NULL,
                        nome VARCHAR(120) NOT NULL,
                        rg VARCHAR(20),
                        cpf VARCHAR(14),
                        telefone VARCHAR(16),
                        data_nascimento DATE,
                        parentesco VARCHAR(50),
                        ativo BOOLEAN NOT NULL DEFAULT 1,
                        data_cadastro DATETIME NOT NULL,
                        FOREIGN KEY(paciente_id) REFERENCES pacientes (id)
                    )
                '''))
            print('✅ Tabela acompanhantes criada')

        if 'agendamentos' in tabelas:
            cols = [c['name'] for c in insp.get_columns('agendamentos')]
            if 'possui_acompanhante' not in cols:
                with db.engine.begin() as conn:
                    conn.execute(text(
                        'ALTER TABLE agendamentos ADD COLUMN possui_acompanhante BOOLEAN DEFAULT 0 NOT NULL'
                    ))
                print('✅ Coluna possui_acompanhante criada em agendamentos')
            if 'acompanhante_id' not in cols:
                with db.engine.begin() as conn:
                    conn.execute(text(
                        'ALTER TABLE agendamentos ADD COLUMN acompanhante_id INTEGER'
                    ))
                print('✅ Coluna acompanhante_id criada em agendamentos')
            if 'hora_consulta' not in cols:
                with db.engine.begin() as conn:
                    conn.execute(text(
                        'ALTER TABLE agendamentos ADD COLUMN hora_consulta TIME'
                    ))
                print('✅ Coluna hora_consulta criada em agendamentos')
            if 'destino_cnes_codigo' not in cols:
                with db.engine.begin() as conn:
                    conn.execute(text(
                        'ALTER TABLE agendamentos ADD COLUMN destino_cnes_codigo VARCHAR(10)'
                    ))
                print('✅ Coluna destino_cnes_codigo criada em agendamentos')
            if 'destino_cnes_nome' not in cols:
                with db.engine.begin() as conn:
                    conn.execute(text(
                        'ALTER TABLE agendamentos ADD COLUMN destino_cnes_nome VARCHAR(200)'
                    ))
                print('✅ Coluna destino_cnes_nome criada em agendamentos')
            if 'frota_id' not in cols:
                with db.engine.begin() as conn:
                    conn.execute(text(
                        'ALTER TABLE agendamentos ADD COLUMN frota_id INTEGER'
                    ))
                print('✅ Coluna frota_id criada em agendamentos')
    except Exception as e:
        print(f'⚠️ Migração acompanhantes: {e}')


def migrar_cnes_estabelecimentos():
    """Garante tabela de cache CNES."""
    try:
        db.create_all()
        print('✅ Cache CNES (cnes_estabelecimentos) verificado')
    except Exception as e:
        print(f'⚠️ Migração CNES: {e}')


def migrar_frotas():
    """Garante tabela de frotas e vínculo veiculos.frota_id."""
    from sqlalchemy import inspect, text
    try:
        db.create_all()
        insp = inspect(db.engine)
        if 'veiculos' in insp.get_table_names():
            cols = [c['name'] for c in insp.get_columns('veiculos')]
            if 'frota_id' not in cols:
                with db.engine.begin() as conn:
                    conn.execute(text('ALTER TABLE veiculos ADD COLUMN frota_id INTEGER'))
                print('✅ Coluna frota_id criada em veiculos')
        print('✅ Tabela frotas verificada')
    except Exception as e:
        print(f'⚠️ Migração frotas: {e}')


def normalizar_numero_frota_cadastro(valor):
    """Padroniza número da frota (ex.: F00267)."""
    import re
    texto = ' '.join(str(valor or '').strip().split())
    if not texto:
        return ''
    texto = texto.upper()
    texto = re.sub(r'\s+', '', texto)
    return texto[:30]


def normalizar_nome_frota_cadastro(valor):
    """Remove espaços excedentes do nome da frota."""
    return ' '.join(str(valor or '').strip().split())[:120]


def frota_identificacao_exibir(frota):
    """Padrão visual: Nome - Número (ex.: NI Frota 267 - F00267)."""
    if not frota:
        return '—'
    nome = (frota.nome or '').strip()
    numero = (frota.numero or '').strip()
    if nome and numero:
        return f'{nome} - {numero}'
    return nome or numero or '—'


def frota_veiculo_vinculado(frota_id, excluir_veiculo_id=None):
    """Retorna o veículo já atrelado à frota (regra: 1 frota ↔ 1 veículo), ou None."""
    if not frota_id:
        return None
    q = Veiculo.query.filter_by(frota_id=frota_id)
    if excluir_veiculo_id:
        q = q.filter(Veiculo.id != excluir_veiculo_id)
    return q.order_by(Veiculo.id.asc()).first()


def vincular_veiculo_a_frota(veiculo, frota, sincronizar_numero=True):
    """
    Associa veículo à frota.
    Regra: 1 frota ↔ 1 veículo (uma frota só pode ter um veículo; um veículo só uma frota).
    Retorna (ok: bool, erro: str|None).
    """
    if not veiculo or not frota:
        return False, 'Veículo ou frota inválidos.'
    ocupado = frota_veiculo_vinculado(frota.id, excluir_veiculo_id=veiculo.id)
    if ocupado:
        return False, (
            f'A frota "{frota_identificacao_exibir(frota)}" já está vinculada ao veículo '
            f'"{ocupado.placa}". Remova o vínculo atual antes de atrelar outro.'
        )
    if veiculo.frota_id and veiculo.frota_id != frota.id:
        return False, (
            f'O veículo "{veiculo.placa}" já pertence a outra frota. '
            'Remova o vínculo anterior antes de transferir.'
        )
    veiculo.frota_id = frota.id
    if sincronizar_numero and frota.numero:
        veiculo.numero_frota = frota.numero
    return True, None


def desvincular_veiculo_da_frota(veiculo):
    """Remove vínculo do veículo com a frota (não exclui o veículo)."""
    if not veiculo:
        return False
    veiculo.frota_id = None
    return True


def html_ajuda_botao(ajuda_id, title='Ajuda sobre este cadastro'):
    """Botão ⓘ discreto."""
    from html import escape
    aid = ''.join(ch for ch in str(ajuda_id or 'ajuda') if ch.isalnum() or ch in '-_')
    tip = escape(title or 'Ajuda')
    return (
        f'<button type="button" class="stp-ajuda-btn" id="stp-ajuda-btn-{aid}" '
        f'data-stp-ajuda="{aid}" title="{tip}" aria-label="{tip}" '
        f'aria-expanded="false" aria-controls="stp-ajuda-painel-{aid}">'
        f'<i class="ti ti-info-circle" aria-hidden="true"></i></button>'
    )


def html_ajuda_painel(ajuda_id, corpo_html):
    """Painel oculto do ⓘ (abre no clique)."""
    aid = ''.join(ch for ch in str(ajuda_id or 'ajuda') if ch.isalnum() or ch in '-_')
    return (
        f'<div class="stp-ajuda-painel" id="stp-ajuda-painel-{aid}" hidden role="region" '
        f'aria-labelledby="stp-ajuda-btn-{aid}">'
        f'<div class="stp-ajuda-painel__body">{corpo_html}</div></div>'
    )


def html_page_header_ajuda(titulo, subtitulo, ajuda_id, corpo_html, title_curto=None):
    """Cabeçalho de cadastro com ⓘ sutil ao lado do título."""
    sub = f'<p>{subtitulo}</p>' if subtitulo else ''
    return f'''
    <div class="page-header">
      <div class="stp-ajuda-title-row">
        <h2>{titulo}</h2>
        {html_ajuda_botao(ajuda_id, title=title_curto or 'Ajuda sobre este cadastro')}
      </div>
      {html_ajuda_painel(ajuda_id, corpo_html)}
      {sub}
    </div>
    '''


AJUDA_PACIENTE = (
    '<p style="margin:0;">Cadastre os dados do paciente. Eles serão usados nos '
    '<strong>agendamentos</strong> e no transporte. Mantenha telefone e endereço atualizados.</p>'
)

AJUDA_ACOMPANHANTE = (
    '<p style="margin:0;">O acompanhante fica <strong>vinculado a um paciente</strong> já cadastrado. '
    'Sem paciente, não é possível salvar. Depois, no agendamento, escolha quem vai na viagem.</p>'
)

AJUDA_MOTORISTA = (
    '<p style="margin:0;">Cadastre o motorista com CPF e CNH válidos. '
    'Ele será escolhido na <strong>programação</strong> da viagem (Cartão / Folha Espelho).</p>'
)

AJUDA_VEICULO = (
    '<p style="margin:0;">Informe placa, tipo e capacidade. Use a consulta FIPE para preencher '
    'marca, modelo e ano. O veículo pode ficar avulso ou vinculado a <strong>uma frota</strong> '
    '(regra: 1 frota = 1 veículo).</p>'
)

AJUDA_VEICULO_FROTA = (
    '<p style="margin:0 0 0.5rem;">Use as abas:</p>'
    '<ul style="margin:0;padding-left:1.2rem;">'
    '<li><strong>Veículo</strong> — cadastro individual (placa, tipo, capacidade).</li>'
    '<li><strong>Frota</strong> — salve a frota e depois vincule <strong>um</strong> veículo.</li>'
    '</ul>'
    '<p style="margin:0.5rem 0 0;"><strong>Regra:</strong> 1 frota ↔ 1 veículo.</p>'
)

AJUDA_FROTA_FLUXO = (
    '<ol style="margin:0;padding-left:1.2rem;">'
    '<li>Salve a frota (número e nome).</li>'
    '<li>Em seguida, vincule ou cadastre <strong>um único veículo</strong> nesta frota.</li>'
    '<li><strong>Regra:</strong> 1 frota = 1 veículo. Para trocar, remova o vínculo atual antes.</li>'
    '</ol>'
)


def html_titulo_aba_cadastro(titulo, ajuda_id, corpo_html, title_curto=None, exemplo=None):
    """Título de aba (Veículo / Frota) com ⓘ discreto e texto de exemplo."""
    exemplo_html = ''
    if exemplo:
        exemplo_html = (
            f'<p style="margin:0.65rem 0 0;color:var(--gray-color);font-size:0.95rem;">{exemplo}</p>'
        )
    return f'''
    <div class="stp-ajuda-bloco" style="margin:0 0 1.25rem;">
      <div class="stp-ajuda-title-row">
        <h3 style="margin:0;font-size:1.1rem;color:var(--primary-color);">{titulo}</h3>
        {html_ajuda_botao(ajuda_id, title=title_curto or 'Ajuda sobre este cadastro')}
      </div>
      {html_ajuda_painel(ajuda_id, corpo_html)}
      {exemplo_html}
    </div>
    '''


def html_ajuda_titulo_veiculo():
    return html_titulo_aba_cadastro(
        '🚗 Cadastro de Veículo',
        'veiculo',
        AJUDA_VEICULO,
        title_curto='Ajuda sobre o cadastro de veículo',
        exemplo=(
            'Cadastre o veículo com placa, tipo e capacidade. Use a consulta FIPE para preencher '
            'marca, modelo e ano (ex.: <em>ABC1D23 — Van Fiat Ducato</em>).'
        ),
    )


def html_ajuda_fluxo_frota():
    """ⓘ discreto na aba Frota — explica o fluxo só se o usuário abrir."""
    return html_titulo_aba_cadastro(
        '🚌 Cadastro de Frota',
        'frota',
        AJUDA_FROTA_FLUXO,
        title_curto='Como funciona o fluxo da frota',
        exemplo=(
            'Cadastre a frota com número e nome. A identificação padrão será '
            '<strong>Nome - Número</strong> (ex.: <em>NI Frota 267 - F00267</em>).'
        ),
    )


def html_secao_veiculos_da_frota(frota):
    """Seção Veículo da Frota (1 frota ↔ 1 veículo: listagem + vincular/cadastrar)."""
    from html import escape
    from flask import url_for

    if not frota:
        return '''
        <div style="margin-top:2rem;padding:1.25rem;border-radius:0.5rem;background:var(--color-95);border:1px dashed var(--border-color);">
            <h4 style="margin:0 0 0.5rem;color:var(--primary-color);">🚗 Veículo da Frota</h4>
            <p style="margin:0;color:var(--gray-color);">Salve a frota para cadastrar ou vincular o veículo (1 frota = 1 veículo).</p>
        </div>
        '''

    identificacao = escape(frota_identificacao_exibir(frota))
    veiculo_atual = frota_veiculo_vinculado(frota.id)
    disponiveis = (
        Veiculo.query.filter(Veiculo.ativo.is_(True), Veiculo.frota_id.is_(None))
        .order_by(Veiculo.placa.asc())
        .all()
    )

    if veiculo_atual:
        v = veiculo_atual
        situacao = 'Ativo' if v.ativo else 'Inativo'
        prefixo = escape(numero_frota_exibir(v) or '—')
        linhas = f'''
        <tr>
            <td style="padding:0.65rem;border-bottom:1px solid var(--border-color);">{escape(v.placa or '')}</td>
            <td style="padding:0.65rem;border-bottom:1px solid var(--border-color);">{prefixo}</td>
            <td style="padding:0.65rem;border-bottom:1px solid var(--border-color);">{escape(v.marca or '')}</td>
            <td style="padding:0.65rem;border-bottom:1px solid var(--border-color);">{escape(v.modelo or '')}</td>
            <td style="padding:0.65rem;border-bottom:1px solid var(--border-color);">{v.ano or '—'}</td>
            <td style="padding:0.65rem;border-bottom:1px solid var(--border-color);">{v.capacidade if v.capacidade is not None else '—'}</td>
            <td style="padding:0.65rem;border-bottom:1px solid var(--border-color);">{situacao}</td>
            <td style="padding:0.65rem;border-bottom:1px solid var(--border-color);text-align:center;">
                <form method="POST" style="display:inline;" class="stp-acoes"
                      onsubmit="return confirm('Remover o vínculo deste veículo com a frota?');">
                    <input type="hidden" name="form_tipo" value="desvincular_veiculo_frota">
                    <input type="hidden" name="frota_id" value="{frota.id}">
                    <input type="hidden" name="veiculo_id" value="{v.id}">
                    {html_acao_icone('ti-eye', 'Visualizar / editar veículo', href=url_for('veiculos_editar', veiculo_id=v.id), variant='ver')}
                    {html_acao_icone('ti-edit', 'Editar veículo', href=url_for('veiculos_editar', veiculo_id=v.id), variant='editar')}
                    <button type="submit" class="stp-acao stp-acao--excluir"
                            title="Remover do vínculo" aria-label="Remover do vínculo">
                        <i class="ti ti-unlink" aria-hidden="true"></i>
                    </button>
                </form>
            </td>
        </tr>
        '''
        status_txt = f'Veículo vinculado: <strong>{escape(v.placa or "")}</strong>'
        acoes_topo = f'''
            <a href="{url_for('veiculos_cadastrar', aba='frota')}" class="btn btn-secondary">🚌 Nova frota</a>
        '''
        form_vincular = f'''
        <div class="alert alert-info" style="margin-bottom:1.25rem;">
          Esta frota já possui um veículo. Remova o vínculo (ícone desvincular) se precisar atrelar outro.
          <strong>Regra: 1 frota = 1 veículo.</strong>
        </div>
        '''
    else:
        linhas = '''
        <tr>
            <td colspan="8" style="padding:1rem;color:var(--gray-color);text-align:center;">
                Nenhum veículo vinculado a esta frota.
            </td>
        </tr>
        '''
        status_txt = 'Sem veículo · pode vincular ou cadastrar <strong>um</strong> veículo'
        href_novo = url_for('veiculos_cadastrar', aba='veiculo', frota_id=frota.id)
        acoes_topo = f'''
            <a href="{href_novo}" class="btn btn-success">➕ Cadastrar veículo nesta frota</a>
            <a href="{url_for('veiculos_cadastrar', aba='frota')}" class="btn btn-secondary">🚌 Nova frota</a>
        '''
        opts_disp = '<option value="">Selecione um veículo...</option>'
        for v in disponiveis:
            opts_disp += (
                f'<option value="{v.id}">{escape(v.placa)} — '
                f'{escape(v.marca or "")} {escape(v.modelo or "")}</option>'
            )
        form_vincular = f'''
        <form method="POST" style="margin-bottom:1.25rem;padding:1rem;background:var(--color-95);border-radius:0.5rem;">
            <input type="hidden" name="form_tipo" value="vincular_veiculo_frota">
            <input type="hidden" name="frota_id" value="{frota.id}">
            <label for="veiculo_vincular_id" style="font-weight:600;">Vincular veículo existente</label>
            <div class="form-row" style="margin-top:0.5rem;align-items:end;">
                <div class="form-group" style="flex:2;">
                    <select id="veiculo_vincular_id" name="veiculo_id" required {"disabled" if not disponiveis else ""}>
                        {opts_disp if disponiveis else '<option value="">Nenhum veículo disponível sem frota</option>'}
                    </select>
                    <small style="color:var(--gray-color);">
                      Somente veículos ainda sem frota. Regra: <strong>1 frota = 1 veículo</strong>.
                    </small>
                </div>
                <div class="form-group">
                    <button type="submit" class="btn btn-primary" {"disabled" if not disponiveis else ""}>🔗 Vincular</button>
                </div>
            </div>
        </form>
        '''

    return f'''
    <div style="margin-top:2rem;padding:1.25rem;border-radius:0.5rem;background:#fff;
                border:1px solid var(--border-color);border-left:4px solid #28a745;">
        <div style="display:flex;justify-content:space-between;gap:1rem;flex-wrap:wrap;align-items:center;margin-bottom:1rem;">
            <div>
                <h4 style="margin:0 0 0.25rem;color:#28a745;">🚗 Veículo da Frota</h4>
                <p style="margin:0;color:var(--gray-color);font-size:0.9rem;">
                    Frota: <strong>{identificacao}</strong> · {status_txt}
                </p>
            </div>
            <div style="display:flex;gap:0.5rem;flex-wrap:wrap;">
                {acoes_topo}
            </div>
        </div>

        {form_vincular}

        <div class="table-container">
            <table style="width:100%;border-collapse:collapse;">
                <thead>
                    <tr>
                        <th style="padding:0.65rem;text-align:left;border-bottom:2px solid var(--primary-color);">Placa</th>
                        <th style="padding:0.65rem;text-align:left;border-bottom:2px solid var(--primary-color);">Prefixo</th>
                        <th style="padding:0.65rem;text-align:left;border-bottom:2px solid var(--primary-color);">Marca</th>
                        <th style="padding:0.65rem;text-align:left;border-bottom:2px solid var(--primary-color);">Modelo</th>
                        <th style="padding:0.65rem;text-align:left;border-bottom:2px solid var(--primary-color);">Ano</th>
                        <th style="padding:0.65rem;text-align:left;border-bottom:2px solid var(--primary-color);">Capacidade</th>
                        <th style="padding:0.65rem;text-align:left;border-bottom:2px solid var(--primary-color);">Situação</th>
                        <th style="padding:0.65rem;text-align:center;border-bottom:2px solid var(--primary-color);">Ações</th>
                    </tr>
                </thead>
                <tbody>{linhas}</tbody>
            </table>
        </div>
    </div>
    '''


# Lista oficial revisada (auditoria): grupos + descrição + ordem
# Removidos: Marido/Mulher (≈ Esposo/Esposa), Parceiro/Parceira (≈ Companheiro/a),
#            Pessoa da Família (≈ Familiar), Contato genérico (ficar Contato de Emergência).
PARENTESCOS_SEED = [
    # Pais
    ('Pais', 'Pai', 10),
    ('Pais', 'Mãe', 20),
    ('Pais', 'Padrasto', 30),
    ('Pais', 'Madrasta', 40),
    # Filhos
    ('Filhos', 'Filho', 50),
    ('Filhos', 'Filha', 60),
    ('Filhos', 'Enteado', 70),
    ('Filhos', 'Enteada', 80),
    # Avós / Bisavós
    ('Avós', 'Avô', 90),
    ('Avós', 'Avó', 100),
    ('Avós', 'Bisavô', 110),
    ('Avós', 'Bisavó', 120),
    # Netos / Bisnetos
    ('Netos', 'Neto', 130),
    ('Netos', 'Neta', 140),
    ('Netos', 'Bisneto', 150),
    ('Netos', 'Bisneta', 160),
    # Irmãos
    ('Irmãos', 'Irmão', 170),
    ('Irmãos', 'Irmã', 180),
    ('Irmãos', 'Meio-irmão', 190),
    ('Irmãos', 'Meio-irmã', 200),
    # Tios / Sobrinhos / Primos
    ('Tios', 'Tio', 210),
    ('Tios', 'Tia', 220),
    ('Sobrinhos', 'Sobrinho', 230),
    ('Sobrinhos', 'Sobrinha', 240),
    ('Primos', 'Primo', 250),
    ('Primos', 'Prima', 260),
    # Cônjuges / união
    ('Cônjuges / União', 'Esposo', 270),
    ('Cônjuges / União', 'Esposa', 280),
    ('Cônjuges / União', 'Cônjuge', 290),
    ('Cônjuges / União', 'União Estável', 300),
    ('Cônjuges / União', 'Companheiro', 310),
    ('Cônjuges / União', 'Companheira', 320),
    # Afinidade
    ('Afinidade', 'Genro', 330),
    ('Afinidade', 'Nora', 340),
    ('Afinidade', 'Sogro', 350),
    ('Afinidade', 'Sogra', 360),
    ('Afinidade', 'Cunhado', 370),
    ('Afinidade', 'Cunhada', 380),
    # Compadrio
    ('Compadrio', 'Padrinho', 390),
    ('Compadrio', 'Madrinha', 400),
    ('Compadrio', 'Afilhado', 410),
    ('Compadrio', 'Afilhada', 420),
    # Tutela / representação (saúde / jurídico)
    ('Tutela / Representação', 'Tutor', 430),
    ('Tutela / Representação', 'Tutora', 440),
    ('Tutela / Representação', 'Curador', 450),
    ('Tutela / Representação', 'Curadora', 460),
    ('Tutela / Representação', 'Responsável Legal', 470),
    ('Tutela / Representação', 'Representante Legal', 480),
    ('Tutela / Representação', 'Procurador', 490),
    ('Tutela / Representação', 'Guardião', 500),
    ('Tutela / Representação', 'Guardiã', 510),
    ('Tutela / Representação', 'Responsável Financeiro', 520),
    ('Tutela / Representação', 'Responsável', 530),
    # Outros vínculos / saúde
    ('Outros vínculos', 'Familiar', 540),
    ('Outros vínculos', 'Parente', 550),
    ('Outros vínculos', 'Agregado', 560),
    ('Outros vínculos', 'Contato de Emergência', 570),
    ('Outros vínculos', 'Pessoa de Confiança', 580),
    ('Outros vínculos', 'Cuidador', 590),
    ('Outros vínculos', 'Cuidadora', 600),
    ('Outros vínculos', 'Enfermeiro', 610),
    ('Outros vínculos', 'Enfermeira', 620),
    ('Outros vínculos', 'Técnico de Enfermagem', 630),
    ('Outros vínculos', 'Assistente Social', 640),
    ('Outros vínculos', 'Vizinho', 650),
    ('Outros vínculos', 'Vizinha', 660),
    ('Outros vínculos', 'Amigo', 670),
    ('Outros vínculos', 'Amiga', 680),
    ('Outros vínculos', 'Conhecido', 690),
    ('Outros vínculos', 'Outros', 999),
]


PARENTESCO_OUTROS_VALOR = 'Outros'


def migrar_parentescos():
    """Cria tabela de domínio parentescos e faz seed (idempotente)."""
    from sqlalchemy import inspect, text
    try:
        db.create_all()
        insp = inspect(db.engine)
        if 'parentescos' not in insp.get_table_names():
            with db.engine.begin() as conn:
                conn.execute(text('''
                    CREATE TABLE parentescos (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        descricao VARCHAR(80) NOT NULL UNIQUE,
                        grupo VARCHAR(60) NOT NULL DEFAULT 'Outros',
                        ativo BOOLEAN NOT NULL DEFAULT 1,
                        ordem INTEGER NOT NULL DEFAULT 0
                    )
                '''))
            print('✅ Tabela parentescos criada')

        # Amplia coluna parentesco em acompanhantes se necessário
        if 'acompanhantes' in insp.get_table_names():
            # SQLite não altera facilmente o tamanho; aceita VARCHAR(50) legado
            pass

        existentes = {p.descricao.lower(): p for p in Parentesco.query.all()}
        # Migra rótulo antigo "Outro" → "Outros"
        if 'outro' in existentes and 'outros' not in existentes:
            p_antigo = existentes['outro']
            p_antigo.descricao = PARENTESCO_OUTROS_VALOR
            existentes['outros'] = p_antigo
            del existentes['outro']
            print('✅ Parentesco "Outro" renomeado para "Outros"')

        novos = 0
        for grupo, descricao, ordem in PARENTESCOS_SEED:
            key = descricao.lower()
            if key in existentes:
                p = existentes[key]
                alterou = False
                if p.grupo != grupo:
                    p.grupo = grupo
                    alterou = True
                if p.ordem != ordem:
                    p.ordem = ordem
                    alterou = True
                if not p.ativo:
                    p.ativo = True
                    alterou = True
                if alterou:
                    novos += 1
            else:
                db.session.add(Parentesco(
                    descricao=descricao,
                    grupo=grupo,
                    ativo=True,
                    ordem=ordem,
                ))
                novos += 1
        # Desativa legado "Outro" se ainda existir junto com "Outros"
        p_outro = Parentesco.query.filter(db.func.lower(Parentesco.descricao) == 'outro').first()
        p_outros = Parentesco.query.filter(db.func.lower(Parentesco.descricao) == 'outros').first()
        if p_outro and p_outros and p_outro.id != p_outros.id:
            p_outro.ativo = False
            novos += 1
        if novos:
            db.session.commit()
            print(f'✅ Domínio parentescos sincronizado ({novos} inclusão/atualização)')
        else:
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f'⚠️ Migração parentescos: {e}')


def listar_parentescos_ativos():
    """Parentescos ativos ordenados por grupo/ordem/descrição."""
    return (
        Parentesco.query
        .filter_by(ativo=True)
        .order_by(Parentesco.ordem, Parentesco.grupo, Parentesco.descricao)
        .all()
    )


def normalizar_parentesco_form(valor, texto_outros=None):
    """
    Valida parentesco contra o domínio.
    Se for 'Outros', usa o texto livre (o que será impresso no cartão).
    Retorna (descricao|None, erro|None).
    """
    raw = (valor or '').strip()
    if not raw:
        return None, None
    # Aceita id numérico ou descrição
    if raw.isdigit():
        p = db.session.get(Parentesco, int(raw))
        if p and p.ativo:
            raw = p.descricao
        else:
            return None, 'Parentesco inválido.'
    else:
        p = Parentesco.query.filter(
            db.func.lower(Parentesco.descricao) == raw.lower(),
            Parentesco.ativo.is_(True),
        ).first()
        if not p:
            # Valor livre legado (já gravado) ou digitado fora do domínio
            if (texto_outros or '').strip():
                return (texto_outros or '').strip()[:80], None
            return None, f'Parentesco "{raw}" não encontrado no domínio. Selecione uma opção da lista.'
        raw = p.descricao

    if raw.strip().lower() == PARENTESCO_OUTROS_VALOR.lower():
        livre = (texto_outros or '').strip()
        if not livre:
            return None, 'Informe o parentesco no campo quando selecionar "Outros".'
        return livre[:80], None
    return raw, None


def html_options_parentesco(valor_atual=None):
    """Options agrupadas para select de parentesco."""
    from html import escape
    from collections import OrderedDict
    atual = (valor_atual or '').strip()
    grupos = OrderedDict()
    for p in listar_parentescos_ativos():
        grupos.setdefault(p.grupo, []).append(p)

    # Se o valor atual não está no domínio, trata como "Outros" + texto livre
    descricoes = {p.descricao.lower() for p in listar_parentescos_ativos()}
    selecionou_outros = bool(atual) and atual.lower() not in descricoes

    html = '<option value="">Selecione o parentesco...</option>'
    for grupo, itens in grupos.items():
        html += f'<optgroup label="{escape(grupo)}">'
        for p in itens:
            if p.descricao.lower() == PARENTESCO_OUTROS_VALOR.lower():
                sel = ' selected' if selecionou_outros or (
                    atual and atual.lower() == PARENTESCO_OUTROS_VALOR.lower()
                ) else ''
            else:
                sel = ' selected' if atual and atual.lower() == p.descricao.lower() else ''
            html += f'<option value="{escape(p.descricao)}"{sel}>{escape(p.descricao)}</option>'
        html += '</optgroup>'
    return html


def html_select_parentesco(name='ac_parentesco', valor_atual=None, required=False, field_id=None,
                           outros_name='ac_parentesco_outros'):
    """Select de parentesco + campo livre quando 'Outros' (valor impresso no cartão)."""
    from html import escape
    fid = field_id or name
    req = ' required' if required else ''
    atual = (valor_atual or '').strip()
    descricoes = {p.descricao.lower() for p in listar_parentescos_ativos()}
    is_outros = bool(atual) and (
        atual.lower() == PARENTESCO_OUTROS_VALOR.lower() or atual.lower() not in descricoes
    )
    texto_outros = atual if (atual and atual.lower() not in descricoes) else ''
    display_outros = 'block' if is_outros else 'none'
    wrap_id = f'{fid}_outros_wrap'
    outros_id = f'{fid}_outros'

    return f'''
    <div class="stp-parentesco-field">
      <select id="{escape(fid)}" name="{escape(name)}" class="stp-parentesco-select"{req}
              data-placeholder="Selecione o parentesco..."
              data-outros-valor="{escape(PARENTESCO_OUTROS_VALOR)}"
              data-outros-wrap="{escape(wrap_id)}"
              data-outros-input="{escape(outros_id)}"
              aria-label="Parentesco">
        {html_options_parentesco(valor_atual)}
      </select>
      <div id="{escape(wrap_id)}" class="stp-parentesco-outros-wrap" style="display:{display_outros};margin-top:0.5rem;">
        <label for="{escape(outros_id)}">Especifique o parentesco (Outros) *</label>
        <input type="text" id="{escape(outros_id)}" name="{escape(outros_name)}"
               class="stp-parentesco-outros-input" maxlength="80"
               value="{escape(texto_outros)}"
               placeholder="Digite o parentesco que será impresso no cartão"
               {'required' if is_outros else ''}>
        <small style="color:#666;">Este texto será o parentesco gravado e impresso no cartão.</small>
      </div>
    </div>
    '''


def html_assets_parentesco_select():
    """CDN + init Tom Select para selects .stp-parentesco-select (pesquisável, limpar, teclado)."""
    return '''
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/tom-select@2.3.1/dist/css/tom-select.min.css">
<script src="https://cdn.jsdelivr.net/npm/tom-select@2.3.1/dist/js/tom-select.complete.min.js"></script>
<style>
  .stp-parentesco-field { width: 100%; }

  /* Controle principal — alinhado aos inputs do STP */
  .stp-parentesco-field .ts-wrapper.single .ts-control,
  .stp-parentesco-field .ts-wrapper .ts-control {
    width: 100%;
    min-height: 2.65rem;
    padding: 0.45rem 2.75rem 0.45rem 0.75rem !important;
    border: 1.5px solid #c5d0d8 !important;
    border-radius: 8px !important;
    background: #fff !important;
    box-shadow: 0 1px 2px rgba(16, 40, 60, 0.04);
    font-size: 0.95rem;
    line-height: 1.4;
    gap: 0.35rem;
    align-items: center;
    transition: border-color .15s ease, box-shadow .15s ease;
    position: relative;
  }
  .stp-parentesco-field .ts-wrapper.single .ts-control::after {
    border-color: #5a6b7a transparent transparent transparent;
    margin-top: 0;
    right: 0.75rem;
  }
  .stp-parentesco-field .ts-wrapper.focus .ts-control,
  .stp-parentesco-field .ts-wrapper.dropdown-active .ts-control {
    border-color: var(--primary-color, #4fc9c4) !important;
    box-shadow: 0 0 0 3px rgba(79, 201, 196, 0.22) !important;
  }
  .stp-parentesco-field .ts-control input {
    font-size: 0.95rem !important;
    color: #1f2a33 !important;
    font-weight: 400 !important;
  }
  .stp-parentesco-field .ts-control .item {
    color: #1f2a33;
    font-weight: 400 !important;
    padding: 0 !important;
    margin: 0 !important;
    max-width: calc(100% - 0.25rem);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .stp-parentesco-field .ts-control input::placeholder {
    color: #8a97a3;
    font-weight: 400;
  }
  /* X à esquerda da seta, sem cobrir o texto */
  .stp-parentesco-field .ts-wrapper.plugin-clear_button .clear-button,
  .stp-parentesco-field .ts-wrapper .clear-button {
    position: absolute !important;
    right: 1.85rem !important;
    top: 50% !important;
    transform: translateY(-50%);
    margin: 0 !important;
    color: #7a8794;
    font-size: 1rem;
    opacity: 0.85;
    z-index: 2;
    line-height: 1;
  }
  .stp-parentesco-field .ts-wrapper .clear-button:hover { color: #c0392b; opacity: 1; }

  /* Dropdown */
  .stp-parentesco-field .ts-dropdown,
  .ts-dropdown.stp-parentesco-select {
    border: 1px solid #d5dee6 !important;
    border-radius: 10px !important;
    box-shadow: 0 10px 28px rgba(20, 40, 60, 0.14) !important;
    margin-top: 4px !important;
    overflow: hidden;
    z-index: 1200;
  }
  .stp-parentesco-field .ts-dropdown .ts-dropdown-content {
    max-height: 280px;
    padding: 0.35rem;
  }
  .stp-parentesco-field .ts-dropdown .optgroup-header {
    background: #f0f6f6;
    color: var(--primary-dark, #2a8f8a);
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    padding: 0.45rem 0.65rem;
    margin: 0.15rem 0;
    border-radius: 6px;
  }
  .stp-parentesco-field .ts-dropdown .option {
    border-radius: 6px;
    padding: 0.5rem 0.7rem;
    color: #243039;
    font-size: 0.92rem;
  }
  .stp-parentesco-field .ts-dropdown .option:hover,
  .stp-parentesco-field .ts-dropdown .option.active {
    background: rgba(79, 201, 196, 0.16);
    color: #1a3d3b;
  }
  .stp-parentesco-field .ts-dropdown .option.selected {
    background: linear-gradient(90deg, var(--primary-color, #4fc9c4), var(--primary-dark, #2a8f8a));
    color: #fff;
    font-weight: 600;
  }
  .stp-parentesco-field .ts-dropdown .no-results {
    padding: 0.75rem;
    color: #6b7782;
    text-align: center;
  }
  .stp-parentesco-field .ts-dropdown .dropdown-input-wrap {
    padding: 0.5rem 0.5rem 0.25rem;
    border-bottom: 1px solid #e8eef2;
  }
  .stp-parentesco-field .ts-dropdown .dropdown-input {
    width: 100%;
    border: 1.5px solid #c5d0d8;
    border-radius: 7px;
    padding: 0.45rem 0.65rem;
    font-size: 0.92rem;
  }
  .stp-parentesco-field .ts-dropdown .dropdown-input:focus {
    outline: none;
    border-color: var(--primary-color, #4fc9c4);
    box-shadow: 0 0 0 3px rgba(79, 201, 196, 0.18);
  }

  /* Campo Outros */
  .stp-parentesco-outros-wrap {
    margin-top: 0.65rem;
    padding: 0.75rem 0.85rem;
    background: #f4fbfb;
    border: 1px dashed var(--primary-color, #4fc9c4);
    border-radius: 8px;
  }
  .stp-parentesco-outros-wrap label {
    display: block;
    font-weight: 600;
    margin-bottom: 0.35rem;
    color: #2a3a44;
  }
  .stp-parentesco-outros-wrap input {
    width: 100%;
    padding: 0.55rem 0.7rem;
    border: 1.5px solid #c5d0d8;
    border-radius: 8px;
    font-size: 0.95rem;
    background: #fff;
  }
  .stp-parentesco-outros-wrap input:focus {
    outline: none;
    border-color: var(--primary-color, #4fc9c4);
    box-shadow: 0 0 0 3px rgba(79, 201, 196, 0.2);
  }
  .stp-parentesco-outros-wrap small {
    display: block;
    margin-top: 0.35rem;
    color: #6b7782;
  }
</style>
<script>
(function () {
  function syncParentescoOutros(sel) {
    if (!sel) return;
    var outrosValor = (sel.getAttribute('data-outros-valor') || 'Outros').toLowerCase();
    var wrap = document.getElementById(sel.getAttribute('data-outros-wrap') || '');
    var inp = document.getElementById(sel.getAttribute('data-outros-input') || '');
    var val = (sel.value || '').trim().toLowerCase();
    var isOutros = val === outrosValor;
    if (wrap) wrap.style.display = isOutros ? 'block' : 'none';
    if (inp) {
      inp.required = isOutros;
      if (!isOutros) inp.value = '';
      if (isOutros) setTimeout(function () { inp.focus(); }, 50);
    }
  }

  function bindParentescoOutros(sel) {
    if (!sel || sel._stpOutrosBound) return;
    sel._stpOutrosBound = true;
    sel.addEventListener('change', function () { syncParentescoOutros(sel); });
    syncParentescoOutros(sel);
  }

  function initParentescoSelects(root) {
    if (typeof TomSelect === 'undefined') {
      (root || document).querySelectorAll('select.stp-parentesco-select').forEach(bindParentescoOutros);
      return;
    }
    (root || document).querySelectorAll('select.stp-parentesco-select').forEach(function (el) {
      if (el.tomselect) {
        bindParentescoOutros(el);
        return;
      }
      new TomSelect(el, {
        create: false,
        allowEmptyOption: true,
        placeholder: el.getAttribute('data-placeholder') || 'Selecione o parentesco...',
        maxOptions: null,
        searchField: ['text'],
        plugins: ['clear_button', 'dropdown_input'],
        render: {
          no_results: function () {
            return '<div class="no-results">Nenhum parentesco encontrado</div>';
          }
        },
        onChange: function () { syncParentescoOutros(el); },
        onClear: function () { syncParentescoOutros(el); }
      });
      bindParentescoOutros(el);
    });
  }
  window.initParentescoSelects = initParentescoSelects;
  window.syncParentescoOutros = syncParentescoOutros;
  window.rebuildParentescoFieldInClone = function (clone) {
    var field = clone.querySelector('.stp-parentesco-field');
    if (!field) return;
    var base = document.querySelector('select.stp-parentesco-select');
    var uid = 'acp_' + Date.now() + '_' + Math.floor(Math.random() * 1000);
    var wrapId = uid + '_outros_wrap';
    var inpId = uid + '_outros';
    var selId = uid;
    var opts = base ? base.innerHTML : '<option value="">Selecione o parentesco...</option>';
    var outrosValor = (base && base.getAttribute('data-outros-valor')) || 'Outros';
    field.innerHTML =
      '<select id="' + selId + '" name="ac_parentesco" class="stp-parentesco-select"' +
      ' data-placeholder="Selecione o parentesco..." data-outros-valor="' + outrosValor + '"' +
      ' data-outros-wrap="' + wrapId + '" data-outros-input="' + inpId + '"' +
      ' aria-label="Parentesco">' + opts + '</select>' +
      '<div id="' + wrapId + '" class="stp-parentesco-outros-wrap" style="display:none;margin-top:0.5rem;">' +
      '<label for="' + inpId + '">Especifique o parentesco (Outros) *</label>' +
      '<input type="text" id="' + inpId + '" name="ac_parentesco_outros" class="stp-parentesco-outros-input" maxlength="80"' +
      ' placeholder="Digite o parentesco que será impresso no cartão" value="">' +
      '<small>Este texto será o parentesco gravado e impresso no cartão.</small></div>';
    var sel = field.querySelector('select');
    if (sel) sel.value = '';
  };
  document.addEventListener('DOMContentLoaded', function () { initParentescoSelects(); });
})();
</script>
'''


# ===== ESPECIALIDADE MÉDICA (reusa coluna agendamentos.tipo_transporte) =====
ESPECIALIDADE_OUTRO_VALOR = 'Outro'
_ESPECIALIDADES_CACHE = None


def caminho_especialidades_json():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'data', 'especialidades.json')


def carregar_dados_especialidades():
    """Carrega JSON de especialidades (simples / completa). Cache em memória."""
    global _ESPECIALIDADES_CACHE
    if _ESPECIALIDADES_CACHE is not None:
        return _ESPECIALIDADES_CACHE
    path = caminho_especialidades_json()
    try:
        with open(path, encoding='utf-8') as f:
            _ESPECIALIDADES_CACHE = json.load(f)
    except Exception as e:
        print(f'⚠️ Especialidades JSON: {e}')
        _ESPECIALIDADES_CACHE = {
            'modo_padrao': 'simples',
            'simples': ['Clínica Geral / Clínica Médica', 'Cardiologia', 'Pediatria'],
            'completa': {'Geral': ['Clínica Geral / Clínica Médica']},
        }
    return _ESPECIALIDADES_CACHE


def modo_lista_especialidades():
    """simples | completa — via env ESPECIALIDADES_MODO ou JSON modo_padrao."""
    env = (os.environ.get('ESPECIALIDADES_MODO') or '').strip().lower()
    if env in ('simples', 'completa'):
        return env
    dados = carregar_dados_especialidades()
    modo = (dados.get('modo_padrao') or 'simples').strip().lower()
    return modo if modo in ('simples', 'completa') else 'simples'


def listar_especialidades_para_select(modo=None):
    """Retorna lista de (grupo|None, descricao). modo: simples|completa (default: config)."""
    dados = carregar_dados_especialidades()
    modo = (modo or modo_lista_especialidades() or 'simples').strip().lower()
    if modo not in ('simples', 'completa'):
        modo = 'simples'
    itens = []
    if modo == 'completa':
        completa = dados.get('completa') or {}
        if isinstance(completa, dict):
            for grupo, lista in completa.items():
                for nome in lista or []:
                    n = str(nome).strip()
                    if n:
                        itens.append((grupo, n))
        elif isinstance(completa, list):
            for nome in completa:
                n = str(nome).strip()
                if n:
                    itens.append((None, n))
    else:
        for nome in dados.get('simples') or []:
            n = str(nome).strip()
            if n:
                itens.append((None, n))
    vistos = set()
    uniq = []
    for g, n in itens:
        key = n.lower()
        if key in vistos or key == ESPECIALIDADE_OUTRO_VALOR.lower():
            continue
        vistos.add(key)
        uniq.append((g, n))
    return uniq


def migrar_especialidade_agendamento():
    """Loga modo da lista; coluna tipo_transporte já reutilizada para especialidade."""
    try:
        print(f'✅ Especialidades: modo lista = {modo_lista_especialidades()}')
    except Exception as e:
        print(f'⚠️ Migração especialidade: {e}')


def normalizar_especialidade_form(form):
    """Select tipo_transporte (+ Outro) → valor a gravar em Agendamento.tipo_transporte."""
    sel = (form.get('tipo_transporte') or form.get('especialidade') or '').strip()
    outro = (form.get('tipo_transporte_outro') or form.get('especialidade_outro') or '').strip()
    if not sel:
        return None, 'Selecione a especialidade.'
    if sel.lower() == ESPECIALIDADE_OUTRO_VALOR.lower():
        if not outro:
            return None, 'Informe a especialidade no campo quando selecionar "Outro".'
        return outro[:120], None
    return sel[:120], None


def formatar_especialidade_exibir(valor):
    """Exibição amigável da especialidade (coluna tipo_transporte)."""
    if not valor:
        return '—'
    texto = str(valor).strip()
    legados = {
        'consulta': 'Consulta Médica',
        'exame': 'Exame',
        'cirurgia': 'Cirurgia',
        'tratamento': 'Tratamento',
        'emergencia': 'Emergência',
        'retorno': 'Consulta de Retorno',
        'outro': 'Outro',
    }
    return legados.get(texto.lower(), texto)


def html_options_especialidade(valor_atual=None, modo='simples'):
    from html import escape
    from collections import OrderedDict
    atual = (valor_atual or '').strip()
    itens = listar_especialidades_para_select(modo=modo or 'simples')
    nomes = {n.lower() for _, n in itens}
    is_outro = bool(atual) and atual.lower() not in nomes and atual.lower() not in (
        'consulta', 'exame', 'cirurgia', 'tratamento', 'emergencia', 'retorno'
    )

    html = '<option value="">Selecione a especialidade...</option>'
    tem_grupo = any(g for g, _ in itens)
    if tem_grupo:
        grupos = OrderedDict()
        for g, n in itens:
            grupos.setdefault(g or 'Outras', []).append(n)
        for grupo, lista in grupos.items():
            html += f'<optgroup label="{escape(grupo)}">'
            for n in lista:
                sel = ' selected' if atual and atual.lower() == n.lower() else ''
                html += f'<option value="{escape(n)}"{sel}>{escape(n)}</option>'
            html += '</optgroup>'
    else:
        for _, n in itens:
            sel = ' selected' if atual and atual.lower() == n.lower() else ''
            html += f'<option value="{escape(n)}"{sel}>{escape(n)}</option>'

    sel_outro = ' selected' if (is_outro or atual.lower() == ESPECIALIDADE_OUTRO_VALOR.lower()) else ''
    html += f'<option value="{escape(ESPECIALIDADE_OUTRO_VALOR)}"{sel_outro}>{escape(ESPECIALIDADE_OUTRO_VALOR)}</option>'
    return html, (atual if is_outro else '')


def html_select_especialidade(valor_atual=None, required=True):
    """Select Especialidade (lista simples) + campo Outro — persiste em tipo_transporte."""
    from html import escape
    opts, texto_outro = html_options_especialidade(valor_atual, modo='simples')
    req = ' required' if required else ''
    display = 'block' if texto_outro else 'none'
    return f'''
    <div class="stp-especialidade-field">
      <label for="tipo_transporte">Especialidade <span class="required-mark" aria-hidden="true">*</span></label>
      <select id="tipo_transporte" name="tipo_transporte" class="stp-especialidade-select"{req}
              data-placeholder="Selecione a especialidade..."
              data-outro-valor="{escape(ESPECIALIDADE_OUTRO_VALOR)}"
              aria-label="Especialidade">
        {opts}
      </select>
      <div id="especialidade-outro-wrap" class="stp-especialidade-outro-wrap" style="display:{display};margin-top:0.55rem;">
        <label for="tipo_transporte_outro">Informe a especialidade (Outro) *</label>
        <input type="text" id="tipo_transporte_outro" name="tipo_transporte_outro" maxlength="120"
               value="{escape(texto_outro)}" placeholder="Digite a especialidade médica">
      </div>
    </div>
    '''


def html_assets_especialidade_select():
    """Tom Select + campo Outro para especialidade (lista simples)."""
    return '''
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/tom-select@2.3.1/dist/css/tom-select.min.css">
<style>
  .stp-especialidade-field .ts-wrapper { width: 100%; }
  .stp-especialidade-field .ts-wrapper .ts-control {
    min-height: 2.65rem;
    padding: 0.45rem 2.75rem 0.45rem 0.75rem !important;
    border: 1.5px solid #c5d0d8 !important;
    border-radius: 8px !important;
    background: #fff !important;
    font-size: 0.95rem;
    font-weight: 400 !important;
  }
  .stp-especialidade-field .ts-control .item { font-weight: 400 !important; }
  .stp-especialidade-field .ts-wrapper.focus .ts-control {
    border-color: var(--primary-color, #4fc9c4) !important;
    box-shadow: 0 0 0 3px rgba(79, 201, 196, 0.22) !important;
  }
  .stp-especialidade-field .ts-wrapper .clear-button {
    position: absolute !important; right: 1.85rem !important; top: 50% !important;
    transform: translateY(-50%); margin: 0 !important;
  }
  .stp-especialidade-field .ts-dropdown {
    border-radius: 10px !important;
    box-shadow: 0 10px 28px rgba(20,40,60,.14) !important;
  }
  .stp-especialidade-field .ts-dropdown .option.selected {
    background: linear-gradient(90deg, var(--primary-color, #4fc9c4), var(--primary-dark, #2a8f8a));
    color: #fff;
  }
  .stp-especialidade-outro-wrap {
    padding: 0.75rem 0.85rem; background: #f4fbfb;
    border: 1px dashed var(--primary-color, #4fc9c4); border-radius: 8px;
  }
  .stp-especialidade-outro-wrap input {
    width: 100%; padding: 0.55rem 0.7rem; border: 1.5px solid #c5d0d8;
    border-radius: 8px; font-size: 0.95rem;
  }
</style>
<script src="https://cdn.jsdelivr.net/npm/tom-select@2.3.1/dist/js/tom-select.complete.min.js"></script>
<script>
(function () {
  function syncEspOutro(sel) {
    var wrap = document.getElementById('especialidade-outro-wrap');
    var inp = document.getElementById('tipo_transporte_outro');
    var outro = (sel.getAttribute('data-outro-valor') || 'Outro').toLowerCase();
    var isOutro = ((sel.value || '').trim().toLowerCase() === outro);
    if (wrap) wrap.style.display = isOutro ? 'block' : 'none';
    if (inp) {
      inp.required = isOutro;
      if (!isOutro) inp.value = '';
      if (isOutro) setTimeout(function () { inp.focus(); }, 40);
    }
  }
  function initEspecialidadeSelect() {
    var el = document.getElementById('tipo_transporte');
    if (!el || typeof TomSelect === 'undefined') {
      if (el) el.addEventListener('change', function () { syncEspOutro(el); });
      return;
    }
    if (el.tomselect) { syncEspOutro(el); return; }
    new TomSelect(el, {
      create: false,
      allowEmptyOption: true,
      placeholder: el.getAttribute('data-placeholder') || 'Selecione a especialidade...',
      maxOptions: null,
      searchField: ['text'],
      plugins: ['clear_button', 'dropdown_input'],
      onChange: function () { syncEspOutro(el); },
      onClear: function () { syncEspOutro(el); }
    });
    syncEspOutro(el);
  }
  document.addEventListener('DOMContentLoaded', initEspecialidadeSelect);
})();
</script>
'''


CONDICOES_PACIENTE_OPTGROUPS = [
    ('Mobilidade', [
        'Acamado',
        'Cadeirante',
        'Deambula sem auxílio',
        'Deambula com dificuldade',
        'Uso de andador',
        'Uso de muletas',
        'Uso de bengala',
        'Amputado',
        'Mobilidade reduzida temporária (fratura, pós-operatório)',
        'Bariátrico / obesidade severa',
    ]),
    ('Equipamentos necessários', [
        'Maca',
        'Cadeira de rodas',
        'Prancha rígida',
        'Colar cervical',
        'Imobilizador de membros',
        'Cadeira de evacuação (escadas)',
    ]),
    ('Suporte respiratório', [
        'Uso de oxigênio (O₂)',
        'Cânula nasal',
        'Máscara de oxigênio',
        'Traqueostomizado',
        'Ventilação mecânica',
        'CPAP/BiPAP',
        'Necessita aspiração de vias aéreas',
    ]),
    ('Suporte clínico', [
        'Bomba de infusão',
        'Monitorização cardíaca',
        'Monitor multiparamétrico',
        'Acesso venoso contínuo',
        'Drenos',
        'Cateter venoso central',
        'Sonda vesical de demora',
        'Sonda nasoenteral/nasogástrica',
        'Ostomia (colostomia, ileostomia etc.)',
    ]),
    ('Estado clínico', [
        'Estável',
        'Debilitado',
        'Dor intensa',
        'Confuso/Desorientado',
        'Sedado',
        'Inconsciente',
        'Convulsões recorrentes',
        'Alto risco de queda',
        'Restrito ao leito',
        'Cuidados paliativos',
    ]),
    ('Controle de infecção', [
        'Isolamento de contato',
        'Isolamento respiratório',
        'Isolamento por gotículas',
        'Isolamento reverso (imunossuprimido)',
    ]),
    ('Necessidade de acompanhamento', [
        'Sem acompanhante',
        'Necessita acompanhante',
        'Necessita técnico de enfermagem',
        'Necessita enfermeiro',
        'Necessita médico',
        'Necessita fisioterapeuta',
    ]),
    ('Condições especiais', [
        'Gestante',
        'Recém-nascido',
        'Pediátrico',
        'Idoso frágil',
        'Deficiência visual',
        'Deficiência auditiva',
        'Transtorno cognitivo (demência, Alzheimer)',
        'Transtorno do Espectro Autista (TEA)',
        'Paciente psiquiátrico',
        'Necessita contenção física autorizada',
    ]),
    ('Observações', [
        'Outros (campo livre)',
    ]),
]

CONDICAO_OUTROS_VALOR = 'Outros (campo livre)'


def extrair_condicao_paciente_form(form):
    """Lê toggle + select do formulário. Retorna (ok, erro, dados) ou (True, None, dict)."""
    especial = bool(form.get('condicao_especial'))
    condicao = (form.get('condicao_paciente') or '').strip()
    outros = (form.get('condicao_outros') or '').strip()

    if not especial:
        return True, None, {
            'condicao_especial': False,
            'condicao_paciente': None,
            'condicao_outros': None,
        }

    if not condicao:
        return False, 'Selecione a condição do paciente (toggle de condição especial ligado).', None

    if condicao == CONDICAO_OUTROS_VALOR:
        if not outros:
            return False, 'Descreva a condição especial no campo livre (Outros).', None
        return True, None, {
            'condicao_especial': True,
            'condicao_paciente': CONDICAO_OUTROS_VALOR,
            'condicao_outros': outros[:255],
        }

    return True, None, {
        'condicao_especial': True,
        'condicao_paciente': condicao[:120],
        'condicao_outros': None,
    }


def aplicar_condicao_paciente(paciente, dados_condicao):
    paciente.condicao_especial = bool(dados_condicao.get('condicao_especial'))
    paciente.condicao_paciente = dados_condicao.get('condicao_paciente')
    paciente.condicao_outros = dados_condicao.get('condicao_outros')


def formatar_condicao_paciente_exibir(paciente):
    """Texto amigável da condição especial para listagens."""
    if not getattr(paciente, 'condicao_especial', False):
        return '—'
    condicao = (getattr(paciente, 'condicao_paciente', None) or '').strip()
    outros = (getattr(paciente, 'condicao_outros', None) or '').strip()
    if condicao == CONDICAO_OUTROS_VALOR and outros:
        return f'Outros: {outros}'
    return condicao or 'Condição especial'


def html_badge_condicao_paciente(paciente):
    """Badge compacto para a coluna Condição na listagem."""
    if not getattr(paciente, 'condicao_especial', False):
        return '<span style="color: var(--gray-color);">—</span>'
    texto = formatar_condicao_paciente_exibir(paciente)
    titulo = texto.replace('"', '&quot;')
    return (
        f'<span title="{titulo}" style="display:inline-block; max-width:14rem; overflow:hidden; '
        f'text-overflow:ellipsis; white-space:nowrap; padding:0.2rem 0.55rem; border-radius:999px; '
        f'background:#fff7ed; color:#9a3412; border:1px solid #fdba74; font-size:0.78rem; font-weight:600;">'
        f'{texto}</span>'
    )


def html_campos_condicao_paciente(paciente=None):
    """Toggle + select com optgroup — coluna ao lado da data de nascimento."""
    especial = bool(getattr(paciente, 'condicao_especial', False)) if paciente else False
    condicao_atual = (getattr(paciente, 'condicao_paciente', None) or '') if paciente else ''
    outros_atual = (getattr(paciente, 'condicao_outros', None) or '') if paciente else ''
    checked = 'checked' if especial else ''
    display_campos = 'block' if especial else 'none'
    display_outros = 'block' if (especial and condicao_atual == CONDICAO_OUTROS_VALOR) else 'none'
    required_sel = 'required' if especial else ''
    disabled_sel = '' if especial else 'disabled'

    options_html = ['<option value="">Selecione a condição...</option>']
    for grupo, itens in CONDICOES_PACIENTE_OPTGROUPS:
        options_html.append(f'<optgroup label="{grupo}">')
        for item in itens:
            sel = ' selected' if item == condicao_atual else ''
            options_html.append(f'<option value="{item}"{sel}>{item}</option>')
        options_html.append('</optgroup>')

    return f'''
    <div class="form-group condicao-especial-bloco">
        <label for="condicao_especial">Condição do paciente</label>
        <div class="condicao-toggle-row">
            <label class="stp-switch" title="Ligado: condição especial · Desligado: paciente normal">
                <input type="checkbox" id="condicao_especial" name="condicao_especial" value="1" {checked}>
                <span class="stp-switch-slider"></span>
            </label>
            <span class="condicao-toggle-label" id="condicao_especial_label">
                {'Condição especial ativada' if especial else 'Paciente sem condição especial'}
            </span>
        </div>
        <small class="condicao-hint">Ligue o interruptor somente se o paciente precisar de condição especial.</small>
        <div id="condicao-especial-campos" style="display:{display_campos}; margin-top:0.75rem;">
            <div class="condicao-select-centralizado">
                <label for="condicao_paciente">Selecionar condição *</label>
                <select id="condicao_paciente" name="condicao_paciente" {required_sel} {disabled_sel}>
                    {''.join(options_html)}
                </select>
            </div>
            <div id="condicao-outros-wrap" style="display:{display_outros}; margin-top:0.65rem;">
                <label for="condicao_outros">Descreva a condição (Outros) *</label>
                <input type="text" id="condicao_outros" name="condicao_outros" maxlength="255"
                       value="{outros_atual}" placeholder="Descreva a condição especial">
            </div>
        </div>
    </div>
    <style>
        .condicao-toggle-row {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
            min-height: 2.5rem;
        }}
        .condicao-toggle-label {{
            font-size: 0.9rem;
            color: var(--text-color, #3f485d);
            font-weight: 500;
        }}
        .condicao-hint {{
            display: block;
            margin-top: 0.35rem;
            color: var(--gray-color, #6d7a8c);
            font-size: 0.8rem;
        }}
        .condicao-select-centralizado {{
            width: 100%;
            max-width: 22rem;
            margin: 0 auto;
            text-align: center;
        }}
        .condicao-select-centralizado label {{
            display: block;
            text-align: center;
        }}
        .condicao-select-centralizado select {{
            width: 100%;
            text-align: left;
        }}
        .stp-switch {{
            position: relative;
            display: inline-block;
            width: 48px;
            height: 26px;
            flex-shrink: 0;
            cursor: pointer;
        }}
        .stp-switch input {{
            opacity: 0;
            width: 0;
            height: 0;
        }}
        .stp-switch-slider {{
            position: absolute;
            inset: 0;
            background: #cbd5e1;
            border-radius: 999px;
            transition: 0.2s;
        }}
        .stp-switch-slider::before {{
            content: '';
            position: absolute;
            height: 20px;
            width: 20px;
            left: 3px;
            top: 3px;
            background: #fff;
            border-radius: 50%;
            transition: 0.2s;
            box-shadow: 0 1px 3px rgba(0,0,0,0.2);
        }}
        .stp-switch input:checked + .stp-switch-slider {{
            background: var(--primary-color, #4fc9c4);
        }}
        .stp-switch input:checked + .stp-switch-slider::before {{
            transform: translateX(22px);
        }}
        .stp-switch input:focus-visible + .stp-switch-slider {{
            outline: 2px solid var(--primary-color, #4fc9c4);
            outline-offset: 2px;
        }}
        @media (max-width: 640px) {{
            .condicao-select-centralizado {{
                max-width: 100%;
            }}
        }}
    </style>
    '''


def html_script_condicao_paciente():
    """JS: toggle libera o select; Outros abre campo livre."""
    return f'''
    <script>
    (function () {{
        var toggle = document.getElementById('condicao_especial');
        var campos = document.getElementById('condicao-especial-campos');
        var select = document.getElementById('condicao_paciente');
        var outrosWrap = document.getElementById('condicao-outros-wrap');
        var outrosInput = document.getElementById('condicao_outros');
        var label = document.getElementById('condicao_especial_label');
        var OUTROS = {CONDICAO_OUTROS_VALOR!r};

        function syncOutros() {{
            var isOutros = select && select.value === OUTROS;
            if (outrosWrap) outrosWrap.style.display = isOutros ? 'block' : 'none';
            if (outrosInput) {{
                outrosInput.required = !!(toggle && toggle.checked && isOutros);
                if (!isOutros) outrosInput.value = '';
            }}
        }}

        function syncToggle() {{
            var on = !!(toggle && toggle.checked);
            if (campos) campos.style.display = on ? 'block' : 'none';
            if (label) label.textContent = on
                ? 'Condição especial ativada'
                : 'Paciente sem condição especial';
            if (select) {{
                select.disabled = !on;
                select.required = on;
                if (!on) {{
                    select.value = '';
                    if (outrosInput) outrosInput.value = '';
                }}
            }}
            syncOutros();
        }}

        if (toggle) toggle.addEventListener('change', syncToggle);
        if (select) select.addEventListener('change', syncOutros);
        syncToggle();
    }})();
    </script>
    '''


# Ícones SVG do toggle de senha (padrão único do sistema)
_SVG_EYE_SHOW = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"/>'
    '<circle cx="12" cy="12" r="3"/></svg>'
)
_SVG_EYE_HIDE = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/>'
    '<path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/>'
    '<path d="M14.12 14.12a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>'
)


def html_campo_senha(
    input_id='password',
    name='password',
    label='Senha',
    required=False,
    value='',
    placeholder='',
    autocomplete='current-password',
    hint='',
    include_label=True,
):
    """Campo de senha padronizado com botão mostrar/ocultar (ícone dentro do input)."""
    from html import escape
    req_attr = ' required' if required else ''
    req_mark = ' <span class="required-mark" aria-hidden="true">*</span>' if required else ''
    label_html = (
        f'<label for="{escape(input_id)}">{escape(label)}{req_mark}</label>'
        if include_label else ''
    )
    hint_html = f'<small class="field-hint" id="{escape(input_id)}-hint">{escape(hint)}</small>' if hint else ''
    describedby = f' aria-describedby="{escape(input_id)}-hint"' if hint else ''
    return f'''
    <div class="form-group">
        {label_html}
        <div class="password-field">
            <input type="password" id="{escape(input_id)}" name="{escape(name)}"
                   value="{escape(value)}" placeholder="{escape(placeholder)}"
                   autocomplete="{escape(autocomplete)}"{req_attr}{describedby}>
            <button type="button" class="password-toggle" data-password-toggle="{escape(input_id)}"
                    aria-label="Mostrar senha" aria-pressed="false" title="Mostrar senha">
                {_SVG_EYE_SHOW}
            </button>
        </div>
        {hint_html}
    </div>
    '''


def migrar_motorista_novos_campos():
    """Adiciona colunas logradouro, numero, bairro, ponto_referencia em motoristas."""
    from sqlalchemy import inspect, text
    try:
        insp = inspect(db.engine)
        cols = [c['name'] for c in insp.get_columns('motoristas')]
        novas = {'logradouro': 'VARCHAR(200)', 'numero': 'VARCHAR(10)', 'bairro': 'VARCHAR(100)', 'ponto_referencia': 'VARCHAR(200)'}
        for col, tipo in novas.items():
            if col not in cols:
                with db.engine.begin() as conn:
                    conn.execute(text(f'ALTER TABLE motoristas ADD COLUMN {col} {tipo}'))
                print(f'✅ Coluna {col} criada em motoristas')
    except Exception as e:
        print(f'⚠️ Migração motoristas: {e}')


def format_data_br(valor):
    """Formata data para exibição dd/mm/aaaa."""
    if not valor:
        return ''
    if isinstance(valor, datetime):
        return valor.strftime('%d/%m/%Y')
    if isinstance(valor, date):
        return valor.strftime('%d/%m/%Y')
    d = parse_data_br(valor)
    return d.strftime('%d/%m/%Y') if d else str(valor)


def format_numero_br(valor):
    """Formata inteiro com separador de milhar brasileiro (16.969)."""
    try:
        return f'{int(valor):,}'.replace(',', '.')
    except (TypeError, ValueError):
        return str(valor or 0)


_DIAS_SEMANA_PT = (
    'Segunda-Feira', 'Terça-Feira', 'Quarta-Feira', 'Quinta-Feira',
    'Sexta-Feira', 'Sábado', 'Domingo',
)
_MESES_PT = (
    'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
    'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro',
)


def format_data_extenso_pt(valor=None):
    """Ex: Sexta-Feira, 12 de Janeiro de 2026"""
    d = valor if isinstance(valor, date) else date.today()
    return f'{_DIAS_SEMANA_PT[d.weekday()]}, {d.day} de {_MESES_PT[d.month - 1]} de {d.year}'


def truncar_com_tooltip(texto, max_len=30):
    """Texto truncado com tooltip nativo e visual ao passar o mouse."""
    from html import escape
    if texto is None or str(texto).strip() == '':
        return '—'
    texto = str(texto).strip()
    esc = escape(texto)
    if len(texto) <= max_len:
        return esc
    curto = escape(texto[:max_len] + '...')
    return f'<span class="stp-tooltip" title="{esc}">{curto}</span>'


def celula_truncada(texto, max_len=30, extra_style=''):
    """Gera conteúdo de <td> com truncamento e tooltip."""
    return f'<span style="{extra_style}">{truncar_com_tooltip(texto, max_len)}</span>'


def html_th_id():
    """Cabeçalho padrão da coluna ID nas listagens."""
    return (
        '<th style="padding:0.75rem;text-align:center;border-bottom:2px solid var(--primary-color);'
        'width:4rem;">ID</th>'
    )


def html_td_id(registro_id):
    """Célula padrão com o ID do registro (sempre visível)."""
    return (
        f'<td style="padding:0.75rem;border-bottom:1px solid var(--border-color);'
        f'text-align:center;font-weight:700;color:var(--primary-color);'
        f'font-variant-numeric:tabular-nums;">{registro_id}</td>'
    )


def html_id_badge(registro_id):
    """Badge compacto #ID para títulos e cards."""
    return (
        f'<span style="color:var(--primary-color);font-weight:700;'
        f'font-variant-numeric:tabular-nums;margin-right:0.35rem;">#{registro_id}</span>'
    )


def html_acao_icone(
    icon,
    label,
    href=None,
    variant='neutral',
    disabled=False,
    target=None,
    onclick=None,
    confirm_msg=None,
    as_button=False,
):
    """
    Ícone de ação padronizado (Tabler Icons, outline) com tooltip/aria-label.
    Preserva a mesma navegação/onclick do botão textual antigo.
    `icon` deve ser o nome Tabler com prefixo, ex.: 'ti-bus', 'ti-circle-check'.
    """
    from html import escape
    label_esc = escape(label or '')
    icon_esc = escape(icon or 'ti-circle')
    if not icon_esc.startswith('ti-'):
        icon_esc = f'ti-{icon_esc}'
    variant_esc = escape(variant or 'neutral')
    classes = f'stp-acao stp-acao--{variant_esc}'
    if disabled:
        classes += ' is-disabled'
    attrs = [
        f'class="{classes}"',
        f'title="{label_esc}"',
        f'aria-label="{label_esc}"',
    ]
    if target:
        attrs.append(f'target="{escape(target)}"')
        if target == '_blank':
            attrs.append('rel="noopener noreferrer"')
    js_click = onclick or ''
    if confirm_msg and not disabled:
        conf = escape(confirm_msg).replace("'", "\\'")
        conf_js = f"return confirm('{conf}');"
        js_click = f"{conf_js} {js_click}".strip() if js_click else conf_js
    if js_click:
        attrs.append(f'onclick="{js_click}"')

    inner = f'<i class="ti {icon_esc}" aria-hidden="true"></i>'
    if disabled or as_button or not href:
        attrs.append('type="button"')
        if disabled:
            attrs.append('disabled')
            attrs.append('aria-disabled="true"')
        return f'<button {" ".join(attrs)}>{inner}</button>'
    attrs.append(f'href="{escape(href)}"')
    return f'<a {" ".join(attrs)}>{inner}</a>'


def html_acoes_toolbar(*acoes, aria_label='Ações'):
    """Agrupa ícones de ação em toolbar compacta e alinhada."""
    from html import escape
    itens = ''.join(a for a in acoes if a)
    return (
        f'<div class="stp-acoes" role="group" aria-label="{escape(aria_label)}">'
        f'{itens}</div>'
    )


def html_mobile_card(*, title, meta='', status_html='', rows=None, acoes_html=''):
    """
    Card de listagem para telas ≤768px (par tabela desktop).
    rows: lista de (rótulo, valor_html) — valor pode ser HTML já escapado.
    """
    from html import escape
    rows = rows or []
    rows_html = ''.join(
        f'<div class="stp-mobile-card__row">'
        f'<div class="stp-mobile-card__label">{escape(str(lab))}</div>'
        f'<div class="stp-mobile-card__value">{val if val is not None else "—"}</div>'
        f'</div>'
        for lab, val in rows
    )
    meta_html = f'<div class="stp-mobile-card__meta">{meta}</div>' if meta else ''
    status_block = f'<div class="stp-mobile-card__status">{status_html}</div>' if status_html else ''
    acoes_block = f'<div class="stp-mobile-card__acoes">{acoes_html}</div>' if acoes_html else ''
    return f'''
    <article class="stp-mobile-card">
      <div class="stp-mobile-card__top">
        <div style="min-width:0;">
          <div class="stp-mobile-card__title">{escape(str(title))}</div>
          {meta_html}
        </div>
        {status_block}
      </div>
      {rows_html}
      {acoes_block}
    </article>'''


def html_esc(texto):
    """Escape HTML curto para valores de cards mobile."""
    from html import escape
    if texto is None:
        return '—'
    return escape(str(texto))


def input_data_br(name, valor, label):
    """Campo de data com padrão brasileiro."""
    from html import escape
    return f'''
    <div class="form-group">
        <label style="display:block; font-size:0.85rem; margin-bottom:0.25rem;">{escape(label)}</label>
        <input type="text" class="data-br" name="{escape(name)}" value="{escape(format_data_br(valor))}"
               placeholder="dd/mm/aaaa" maxlength="10" inputmode="numeric"
               style="width:100%; padding:0.55rem 0.65rem; border:1px solid var(--border-color); border-radius:6px;">
    </div>
    '''


def filtros_tem_valores(filtros, ignorar=None):
    ignorar = ignorar or set()
    return any(filtros.get(k) for k in filtros if k not in ignorar)


def estilo_painel_filtros():
    return 'background: var(--color-95); padding: 1.25rem; border-radius: 0.5rem; margin-bottom: 1rem; border: 1px solid var(--border-color);'


def estilo_grid_filtros():
    return 'display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 0.75rem; align-items: end;'


def input_texto_filtro(name, valor, label, placeholder=''):
    from html import escape
    return f'''
    <div class="form-group">
        <label style="display:block; font-size:0.85rem; margin-bottom:0.25rem;">{escape(label)}</label>
        <input type="text" name="{escape(name)}" value="{escape(valor or '')}" placeholder="{escape(placeholder)}"
               style="width:100%; padding:0.55rem 0.65rem; border:1px solid var(--border-color); border-radius:6px;">
    </div>
    '''


def botoes_filtro(endpoint, tem_filtro, limpar_params=None):
    from flask import url_for
    limpar = (
        f'<a href="{url_for(endpoint, **(limpar_params or {}))}" class="btn" style="background:var(--gray-color);">Limpar filtros</a>'
        if tem_filtro else ''
    )
    return f'''
    <div class="form-group" style="display:flex; gap:0.5rem; flex-wrap:wrap;">
        <button type="submit" class="btn">🔍 Filtrar</button>
        {limpar}
    </div>
    '''


def contador_filtros(exibidos, total, tem_filtro):
    extra = ' (filtros ativos)' if tem_filtro else ''
    return f'''
    <p style="margin: 0.85rem 0 0; color: var(--gray-color); font-size: 0.95rem;">
        Exibindo <strong style="color: var(--primary-color);">{format_numero_br(exibidos)}</strong>
        de <strong>{format_numero_br(total)}</strong> registros{extra}
    </p>
    '''


def gerar_barra_busca_contador(endpoint, termo, placeholder, total, exibidos, extra_params=None):
    """Gera barra de busca GET + contador de registros."""
    from html import escape
    from flask import url_for
    from urllib.parse import urlencode

    termo_safe = escape(termo or '')
    limpar_btn = ''
    if termo:
        limpar_btn = (
            f'<a href="{url_for(endpoint)}" class="btn" '
            f'style="background: var(--gray-color); margin-left: 0.5rem;">Limpar</a>'
        )

    if termo and exibidos != total:
        detalhe = f' para <strong>"{termo_safe}"</strong>'
    elif termo:
        detalhe = f' para <strong>"{termo_safe}"</strong>'
    else:
        detalhe = ''

    hidden_params = ''
    if extra_params:
        for key, value in extra_params.items():
            if value is not None and key != 'q':
                hidden_params += f'<input type="hidden" name="{escape(key)}" value="{escape(str(value))}">'

    return f'''
    <div class="card" style="margin-bottom: 1rem;">
        <form method="GET" action="{url_for(endpoint)}" style="display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: center;">
            <input type="text" name="q" value="{termo_safe}" placeholder="{escape(placeholder)}"
                   style="flex: 1; min-width: 220px; padding: 0.6rem 0.75rem; border: 1px solid var(--border-color); border-radius: 6px;">
            {hidden_params}
            <button type="submit" class="btn">🔍 Buscar</button>
            {limpar_btn}
        </form>
        <p style="margin: 0.75rem 0 0; color: var(--gray-color); font-size: 0.95rem;">
            Exibindo <strong style="color: var(--primary-color);">{exibidos}</strong>
            de <strong>{total}</strong> registros{detalhe}
        </p>
    </div>
    '''


def gerar_paginacao(endpoint, page, per_page, total, filtros=None):
    """Gera controles de paginação reutilizáveis."""
    from html import escape
    from flask import url_for
    from urllib.parse import urlencode

    filtros = {k: v for k, v in (filtros or {}).items() if v}

    if total <= per_page:
        return ''

    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    inicio = (page - 1) * per_page + 1
    fim = min(page * per_page, total)

    def link_pagina(num, label=None):
        params = {'page': num, 'per_page': per_page, **filtros}
        href = url_for(endpoint) + '?' + urlencode(params)
        cls = 'btn btn-small'
        if num == page:
            cls += '" style="background: var(--primary-color); color: white; padding: 0.35rem 0.75rem; font-size: 0.875rem; margin: 0 0.15rem;'
        else:
            cls += '" style="background: var(--color-95); color: var(--primary-color); padding: 0.35rem 0.75rem; font-size: 0.875rem; margin: 0 0.15rem;'
        return f'<a href="{href}" class="{cls}">{escape(label or str(num))}</a>'

    links = []
    if page > 1:
        links.append(link_pagina(page - 1, '« Anterior'))

    start = max(1, page - 2)
    end = min(total_pages, page + 2)
    if start > 1:
        links.append(link_pagina(1))
        if start > 2:
            links.append('<span style="padding: 0 0.25rem;">...</span>')
    for num in range(start, end + 1):
        links.append(link_pagina(num))
    if end < total_pages:
        if end < total_pages - 1:
            links.append('<span style="padding: 0 0.25rem;">...</span>')
        links.append(link_pagina(total_pages))

    if page < total_pages:
        links.append(link_pagina(page + 1, 'Próxima »'))

    per_page_opts = ''
    for n in (25, 50, 100):
        params = {'page': 1, 'per_page': n, **filtros}
        href = url_for(endpoint) + '?' + urlencode(params)
        sel = 'font-weight: bold; color: var(--primary-color);' if n == per_page else ''
        per_page_opts += f'<a href="{href}" style="margin-right: 0.75rem; {sel}">{n}</a>'

    return f'''
    <div class="card" style="margin-top: 1rem; display: flex; flex-wrap: wrap; gap: 1rem; align-items: center; justify-content: space-between;">
        <div style="color: var(--gray-color); font-size: 0.9rem;">
            Registros <strong>{format_numero_br(inicio)}</strong>–<strong>{format_numero_br(fim)}</strong> de <strong>{format_numero_br(total)}</strong>
            · Página <strong>{format_numero_br(page)}</strong> de <strong>{format_numero_br(total_pages)}</strong>
        </div>
        <div style="display: flex; flex-wrap: wrap; align-items: center; gap: 0.25rem;">
            {''.join(links)}
        </div>
        <div style="font-size: 0.875rem; color: var(--gray-color);">
            Por página: {per_page_opts}
        </div>
    </div>
    '''


def gerar_paginacao_agendamentos(page, per_page, total, filtros=None):
    return gerar_paginacao('agendamentos', page, per_page, total, filtros)


def obter_paginacao_request(padrao=50):
    from flask import request
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', padrao, type=int)
    per_page = min(max(per_page, 25), 100)
    page = max(page, 1)
    return page, per_page


def listar_paginado(query, page, per_page, *order_by):
    """Executa query com contagem, offset e limite."""
    total = query.order_by(None).count()
    offset = (page - 1) * per_page
    if total and offset >= total:
        page = max(1, (total + per_page - 1) // per_page)
        offset = (page - 1) * per_page
    q = query
    if order_by:
        q = q.order_by(*order_by)
    return q.offset(offset).limit(per_page).all(), total, page


def obter_filtros_agendamentos_request():
    """Lê filtros da query string para listagem de agendamentos."""
    from flask import request
    return {
        'id': request.args.get('id', '').strip(),
        'q': request.args.get('q', '').strip(),
        'paciente': request.args.get('paciente', '').strip(),
        'data': request.args.get('data', '').strip(),
        'data_inicio': request.args.get('data_inicio', '').strip(),
        'data_fim': request.args.get('data_fim', '').strip(),
        'status': request.args.get('status', '').strip(),
        'motorista': request.args.get('motorista', '').strip(),
        'frota': request.args.get('frota', '').strip(),
        'destino': request.args.get('destino', '').strip(),
        'origem': request.args.get('origem', '').strip(),
        'placa': request.args.get('placa', '').strip(),
        'tipo_transporte': request.args.get('tipo_transporte', '').strip(),
        'periodo': request.args.get('periodo', '').strip(),
    }


def filtros_agendamentos_ativos(filtros):
    return any(filtros.get(k) for k in filtros if k != 'periodo') or bool(filtros.get('periodo'))


def montar_query_agendamentos(filtros):
    """Monta query de agendamentos com filtros opcionais."""
    from sqlalchemy import or_
    from sqlalchemy.orm import contains_eager

    filtros = filtros or {}
    query = (
        Agendamento.query
        .outerjoin(Paciente, Agendamento.paciente_id == Paciente.id)
        .outerjoin(Motorista, Agendamento.motorista_id == Motorista.id)
        .outerjoin(Veiculo, Agendamento.veiculo_id == Veiculo.id)
        .outerjoin(Frota, Agendamento.frota_id == Frota.id)
        .options(
            contains_eager(Agendamento.paciente),
            contains_eager(Agendamento.motorista),
            contains_eager(Agendamento.veiculo),
            contains_eager(Agendamento.frota),
        )
    )

    periodo = filtros.get('periodo', '')
    if periodo == 'hoje':
        query = query.filter(Agendamento.data == date.today())
    elif periodo == 'amanha':
        query = query.filter(Agendamento.data == date.today() + timedelta(days=1))
    elif periodo == 'semana':
        inicio = date.today() - timedelta(days=date.today().weekday())
        fim = inicio + timedelta(days=6)
        query = query.filter(Agendamento.data.between(inicio, fim))
    elif periodo == 'mes':
        hoje = date.today()
        inicio = hoje.replace(day=1)
        if hoje.month == 12:
            fim = hoje.replace(day=31)
        else:
            fim = (hoje.replace(month=hoje.month + 1, day=1) - timedelta(days=1))
        query = query.filter(Agendamento.data.between(inicio, fim))

    if filtros.get('data'):
        data_unica = parse_data_br(filtros['data'])
        if data_unica:
            query = query.filter(Agendamento.data == data_unica)
    else:
        d_ini = parse_data_br(filtros.get('data_inicio'))
        d_fim = parse_data_br(filtros.get('data_fim'))
        if d_ini:
            query = query.filter(Agendamento.data >= d_ini)
        if d_fim:
            query = query.filter(Agendamento.data <= d_fim)

    if filtros.get('status'):
        query = query.filter(Agendamento.status == filtros['status'])
    else:
        # Por padrão não polui a listagem com cancelados (use filtro Status=Cancelado).
        query = query.filter(Agendamento.status != 'cancelado')

    id_raw = (filtros.get('id') or '').strip()
    if id_raw.isdigit():
        query = query.filter(Agendamento.id == int(id_raw))

    if filtros.get('tipo_transporte'):
        query = query.filter(Agendamento.tipo_transporte.ilike(f"%{filtros['tipo_transporte']}%"))

    if filtros.get('paciente'):
        query = query.filter(Paciente.nome.ilike(f"%{filtros['paciente']}%"))

    if filtros.get('motorista'):
        mot = (filtros['motorista'] or '').strip()
        if mot.isdigit():
            query = query.filter(Motorista.id == int(mot))
        else:
            query = query.filter(Motorista.nome.ilike(f"%{mot}%"))

    if filtros.get('frota'):
        frota_termo = (filtros['frota'] or '').strip()
        if frota_termo.isdigit():
            query = query.filter(Frota.id == int(frota_termo))
        else:
            like_f = f'%{frota_termo}%'
            query = query.filter(
                or_(
                    Frota.nome.ilike(like_f),
                    Frota.numero.ilike(like_f),
                )
            )

    if filtros.get('destino'):
        query = query.filter(Agendamento.destino.ilike(f"%{filtros['destino']}%"))

    if filtros.get('origem'):
        query = query.filter(Agendamento.origem.ilike(f"%{filtros['origem']}%"))

    if filtros.get('placa'):
        query = query.filter(Veiculo.placa.ilike(f"%{filtros['placa']}%"))

    if filtros.get('q'):
        termo = filtros['q']
        like = f'%{termo}%'
        condicoes_q = [
            Paciente.nome.ilike(like),
            Agendamento.destino.ilike(like),
            Agendamento.origem.ilike(like),
            Agendamento.status.ilike(like),
            Agendamento.observacoes.ilike(like),
            Agendamento.tipo_transporte.ilike(like),
            Motorista.nome.ilike(like),
            Veiculo.placa.ilike(like),
            Frota.nome.ilike(like),
            Frota.numero.ilike(like),
        ]
        if termo.isdigit():
            tid = int(termo)
            condicoes_q.extend([
                Motorista.id == tid,
                Frota.id == tid,
                Agendamento.id == tid,
            ])
        query = query.filter(or_(*condicoes_q))

    return query


def obter_intervalo_paginas_impressao(paginas, page, total_pages):
    """Define intervalo de páginas para impressão."""
    if paginas == 'atual':
        return page, page
    if paginas == '1-2':
        return 1, min(2, total_pages)
    if paginas == '1-3':
        return 1, min(3, total_pages)
    if paginas == 'todas':
        return 1, total_pages
    return page, page


def aplicar_filtro_faixa_etaria(query, campo_data_nasc, faixa, data_ref=None):
    """Filtra por faixa etária (0-5, 6-12, 13-17, 18-59, 60+)."""
    faixa = (faixa or '').strip()
    if not faixa:
        return query
    ref = _data_ref_normalizada(data_ref)
    if faixa == '0-5':
        return query.filter(campo_data_nasc > data_limite_por_idade(6, ref), campo_data_nasc <= ref)
    if faixa == '6-12':
        return query.filter(
            campo_data_nasc > data_limite_por_idade(13, ref),
            campo_data_nasc <= data_limite_por_idade(6, ref),
        )
    if faixa == '13-17':
        return query.filter(
            campo_data_nasc > data_limite_por_idade(18, ref),
            campo_data_nasc <= data_limite_por_idade(13, ref),
        )
    if faixa == '18-59':
        return query.filter(
            campo_data_nasc > data_limite_por_idade(60, ref),
            campo_data_nasc <= data_limite_por_idade(18, ref),
        )
    if faixa == '60+':
        return query.filter(campo_data_nasc <= data_limite_por_idade(60, ref))
    return query


def validar_data_nascimento(valor, obrigatorio=True, label='Data de nascimento'):
    """
    Valida e normaliza data de nascimento.
    Aceita ISO (yyyy-mm-dd) ou BR (dd/mm/aaaa).
    Retorna (date|None, erro|None).
    """
    if isinstance(valor, datetime):
        dn = valor.date()
    elif isinstance(valor, date):
        dn = valor
    else:
        raw = (valor or '').strip()
        if not raw:
            if obrigatorio:
                return None, f'Informe a {label.lower()}.'
            return None, None
        dn = None
        try:
            dn = datetime.strptime(str(raw), '%Y-%m-%d').date()
        except ValueError:
            dn = parse_data_br(raw)
        if not dn:
            return None, f'{label} inválida. Use o calendário ou o formato dd/mm/aaaa.'
    hoje = date.today()
    if dn > hoje:
        return None, f'{label} não pode ser uma data futura.'
    if dn < DATA_NASCIMENTO_MINIMA:
        return None, f'{label} inválida (anterior a {DATA_NASCIMENTO_MINIMA.strftime("%d/%m/%Y")}).'
    return dn, None


def html_campo_data_nascimento(
    name='data_nascimento',
    valor=None,
    required=True,
    field_id=None,
    label='Data de Nascimento',
):
    """Campo type=date (dia/mês/ano). Idade não é exibida em formulários — só em listagens/documentos."""
    from html import escape
    fid = field_id or name
    req = ' required' if required else ''
    req_mark = ' <span class="required-mark" aria-hidden="true">*</span>' if required else ''
    if isinstance(valor, datetime):
        valor = valor.date()
    val = valor.strftime('%Y-%m-%d') if isinstance(valor, date) else ''
    return f'''
    <div class="form-group" style="flex:1;min-width:11rem;">
      <label for="{escape(fid)}">{escape(label)}{req_mark}</label>
      <input type="date" id="{escape(fid)}" name="{escape(name)}" class="stp-data-nascimento"
             value="{escape(val)}" min="{DATA_NASCIMENTO_MINIMA.isoformat()}" max="{date.today().isoformat()}"
             autocomplete="bday"{req}>
      <small style="color:#666;">Selecione dia, mês e ano no calendário</small>
    </div>
    '''


def extrair_acompanhante_observacoes(observacoes):
    """Tenta extrair nome de acompanhante das observações."""
    dados = parse_dados_acompanhante_cartao(observacoes)
    if dados.get('nome'):
        return dados['nome']
    if dados.get('tem_acompanhante'):
        return 'Sim'
    return '—'


def acompanhante_para_dict(ac, data_ref=None):
    """Normaliza dados de um Acompanhante para cartão/API."""
    if not ac:
        return {
            'tem_acompanhante': False,
            'nome': '',
            'idade': '',
            'rg': '',
            'tel': '',
            'id': None,
            'parentesco': '',
        }
    idade = ''
    if ac.data_nascimento:
        idade = calcular_idade(ac.data_nascimento, data_ref)
        if idade == '—':
            idade = ''
    return {
        'tem_acompanhante': True,
        'id': ac.id,
        'nome': (ac.nome or '').strip(),
        'idade': idade,
        'rg': format_rg(ac.rg) if ac.rg else '',
        'tel': (ac.telefone or '').strip(),
        'parentesco': (ac.parentesco or '').strip(),
        'cpf': (ac.cpf or '').strip(),
        'data_nascimento': ac.data_nascimento.strftime('%Y-%m-%d') if ac.data_nascimento else '',
    }


def dados_acompanhante_do_agendamento(agendamento):
    """
    Preferência: acompanhante estruturado da viagem.
    Fallback: texto em observações (legado).
    """
    if getattr(agendamento, 'possui_acompanhante', False):
        ac = getattr(agendamento, 'acompanhante', None)
        if ac is None and getattr(agendamento, 'acompanhante_id', None):
            ac = db.session.get(Acompanhante, agendamento.acompanhante_id)
        if ac and getattr(ac, 'ativo', True):
            return acompanhante_para_dict(ac, agendamento.data)
        # Marcado como possui, mas sem cadastro (ainda mostra AC=1 no cartão se houver texto)
    return parse_dados_acompanhante_cartao(getattr(agendamento, 'observacoes', None))


def listar_acompanhantes_paciente(paciente_id, somente_ativos=True):
    q = Acompanhante.query.filter_by(paciente_id=paciente_id)
    if somente_ativos:
        q = q.filter_by(ativo=True)
    return q.order_by(Acompanhante.nome).all()


NOME_ACOMPANHANTE_NAO_INFORMADO = 'NOME NÃO INFORMADO'


def html_campo_nome_acompanhante(nome=''):
    """Campo nome + opção quando o nome ainda não é conhecido."""
    from html import escape
    nome_atual = (nome or '').strip()
    nao_info = nome_atual.upper() == NOME_ACOMPANHANTE_NAO_INFORMADO
    checked = ' checked' if nao_info else ''
    flag_val = '1' if nao_info else '0'
    readonly = ' readonly' if nao_info else ''
    bg = ' style="background:#f0f3f5;"' if nao_info else ''
    return f'''
    <div class="form-group stp-ac-nome-wrap">
      <label>Nome</label>
      <input type="text" name="ac_nome" class="stp-ac-nome-input" value="{escape(nome_atual)}"
             placeholder="Nome completo (se souber)" autocomplete="name"{readonly}{bg}>
      <label class="stp-ac-nome-desconhecido" style="display:flex;align-items:flex-start;gap:0.45rem;margin-top:0.45rem;font-weight:500;cursor:pointer;">
        <input type="hidden" name="ac_nome_nao_informado" value="{flag_val}" class="stp-ac-nome-flag">
        <input type="checkbox" class="stp-ac-nome-check" style="margin-top:0.2rem;"{checked}
               onchange="alternarNomeAcompanhanteDesconhecido(this)">
        <span>Nome ainda não informado / desconhecido<br>
          <small style="color:#666;font-weight:400;">Grava “NOME NÃO INFORMADO” e aparece assim no cartão do motorista.</small>
        </span>
      </label>
    </div>
    '''


def html_campo_nasc_acompanhante(valor=None, field_id=None, required=True):
    """Data de nascimento do acompanhante (somente data; idade só em listagens/documentos)."""
    return html_campo_data_nascimento(
        name='ac_data_nascimento',
        valor=valor,
        required=required,
        field_id=field_id or 'ac_data_nascimento',
        label='Data de Nascimento',
    )


def html_script_nome_acompanhante():
    """JS do checkbox nome desconhecido (por linha do formulário)."""
    return '''
<script>
function alternarNomeAcompanhanteDesconhecido(chk) {
  var wrap = chk.closest('.stp-ac-nome-wrap');
  if (!wrap) return;
  var inp = wrap.querySelector('.stp-ac-nome-input');
  var flag = wrap.querySelector('.stp-ac-nome-flag');
  if (flag) flag.value = chk.checked ? '1' : '0';
  if (!inp) return;
  if (chk.checked) {
    inp.value = 'NOME NÃO INFORMADO';
    inp.required = false;
    inp.readOnly = true;
    inp.style.background = '#f0f3f5';
    inp.placeholder = 'NOME NÃO INFORMADO';
  } else {
    inp.readOnly = false;
    inp.required = true;
    inp.style.background = '';
    if ((inp.value || '').toUpperCase() === 'NOME NÃO INFORMADO') inp.value = '';
    inp.placeholder = 'Nome completo (se souber)';
  }
}
function resetNomeAcompanhanteLinha(clone) {
  var wrap = clone.querySelector('.stp-ac-nome-wrap');
  if (!wrap) return;
  var inp = wrap.querySelector('.stp-ac-nome-input');
  var flag = wrap.querySelector('.stp-ac-nome-flag');
  var chk = wrap.querySelector('.stp-ac-nome-check');
  if (flag) flag.value = '0';
  if (chk) chk.checked = false;
  if (inp) {
    inp.readOnly = false;
    inp.required = true;
    inp.style.background = '';
    inp.value = '';
    inp.placeholder = 'Nome completo (se souber)';
  }
}
window.alternarNomeAcompanhanteDesconhecido = alternarNomeAcompanhanteDesconhecido;
window.resetNomeAcompanhanteLinha = resetNomeAcompanhanteLinha;
</script>
'''


def _extrair_dados_acompanhante_form(form):
    """Valida e normaliza campos do form de acompanhante. Retorna (dict|None, erro|None)."""
    nome_nao_info = str(form.get('ac_nome_nao_informado') or form.get('nome_nao_informado') or '').strip() in (
        '1', 'true', 'on', 'yes', 'sim'
    )
    nome = (form.get('ac_nome') or form.get('nome') or '').strip()
    if nome_nao_info:
        nome = NOME_ACOMPANHANTE_NAO_INFORMADO
    elif not nome:
        return None, 'Informe o nome do acompanhante ou marque "Nome ainda não informado".'
    rg = (form.get('ac_rg') or form.get('rg') or '').strip() or None
    cpf = (form.get('ac_cpf') or form.get('cpf') or '').strip() or None
    telefone = (form.get('ac_telefone') or form.get('telefone') or '').strip() or None
    parentesco_raw = (form.get('ac_parentesco') or form.get('parentesco') or '').strip() or None
    parentesco_outros = (
        form.get('ac_parentesco_outros')
        or form.get('parentesco_outros')
        or ''
    )
    parentesco, erro_par = normalizar_parentesco_form(parentesco_raw, parentesco_outros)
    if erro_par:
        return None, erro_par
    dn_raw = (form.get('ac_data_nascimento') or form.get('data_nascimento') or '').strip()
    data_nascimento, dn_erro = validar_data_nascimento(
        dn_raw, obrigatorio=True, label='Data de nascimento do acompanhante'
    )
    if dn_erro:
        return None, dn_erro
    if rg:
        rg_fmt, rg_erro = validar_e_formatar_rg(rg, obrigatorio=False)
        if rg_erro:
            return None, rg_erro
        rg = rg_fmt
    else:
        rg = None
    if cpf:
        cpf_fmt, cpf_erro = validar_e_formatar_cpf(cpf)
        if cpf_erro:
            return None, cpf_erro
        cpf = cpf_fmt
    return {
        'nome': nome.upper(),
        'rg': rg,
        'cpf': cpf,
        'telefone': telefone,
        'data_nascimento': data_nascimento,
        'parentesco': parentesco,
    }, None


def _resolver_paciente_acompanhante(paciente_id):
    if not paciente_id:
        return None, 'Selecione o paciente. Sem paciente não há acompanhante.'
    paciente = db.session.get(Paciente, int(paciente_id))
    if not paciente or not getattr(paciente, 'ativo', True):
        return None, 'Paciente inválido ou inativo. Cadastre o paciente antes do acompanhante.'
    return paciente, None


def criar_acompanhante_de_form(paciente_id, form):
    """Cria Acompanhante a partir de form/dict. Retorna (obj|None, erro|None).
    Regra: acompanhante só existe vinculado a um paciente ativo.
    Nome pode ser desconhecido → grava 'NOME NÃO INFORMADO' (aparece no cartão).
    """
    paciente, erro = _resolver_paciente_acompanhante(paciente_id)
    if erro:
        return None, erro
    dados, erro = _extrair_dados_acompanhante_form(form)
    if erro:
        return None, erro
    ac = Acompanhante(
        paciente_id=paciente.id,
        ativo=True,
        **dados,
    )
    return ac, None


def atualizar_acompanhante_de_form(ac, form, paciente_id=None):
    """Atualiza Acompanhante existente. Retorna (obj|None, erro|None)."""
    if not ac:
        return None, 'Acompanhante não encontrado.'
    pid = paciente_id if paciente_id is not None else ac.paciente_id
    paciente, erro = _resolver_paciente_acompanhante(pid)
    if erro:
        return None, erro
    dados, erro = _extrair_dados_acompanhante_form(form)
    if erro:
        return None, erro
    ac.paciente_id = paciente.id
    for chave, valor in dados.items():
        setattr(ac, chave, valor)
    return ac, None


def aplicar_acompanhante_no_agendamento(agendamento, form, paciente_id):
    """Aplica seleção de acompanhante do formulário de agendamento."""
    paciente = db.session.get(Paciente, int(paciente_id)) if paciente_id else None
    obrigatorio = paciente_necessita_acompanhante(paciente)
    possui = bool(form.get('possui_acompanhante')) or obrigatorio
    ac_id_raw = (form.get('acompanhante_id') or '').strip()

    if obrigatorio:
        erro_cadastro = validar_acompanhantes_cadastrados_para_condicao(paciente)
        if erro_cadastro:
            return erro_cadastro
        if not ac_id_raw:
            return (
                'Este paciente necessita acompanhante. '
                'Selecione um acompanhante já cadastrado na ficha do paciente.'
            )

    if not possui:
        agendamento.possui_acompanhante = False
        agendamento.acompanhante_id = None
        return None
    if not ac_id_raw:
        return 'Selecione o acompanhante desta viagem (cadastro é feito na ficha do paciente).'
    try:
        ac_id = int(ac_id_raw)
    except (TypeError, ValueError):
        return 'Acompanhante inválido.'
    ac = db.session.get(Acompanhante, ac_id)
    if not ac or not ac.ativo or ac.paciente_id != int(paciente_id):
        return 'Acompanhante não pertence a este paciente.'
    agendamento.possui_acompanhante = True
    agendamento.acompanhante_id = ac.id
    return None


CONDICAO_NECESSITA_ACOMPANHANTE = 'Necessita acompanhante'


def paciente_necessita_acompanhante(paciente):
    """True se a condição especial do paciente exige acompanhante."""
    if not paciente:
        return False
    cond = (getattr(paciente, 'condicao_paciente', None) or '').strip()
    return cond == CONDICAO_NECESSITA_ACOMPANHANTE


def validar_acompanhantes_cadastrados_para_condicao(paciente):
    """
    Se o paciente necessita acompanhante, exige ao menos 1 cadastrado na ficha.
    Retorna mensagem de erro ou None.
    """
    if not paciente_necessita_acompanhante(paciente):
        return None
    if listar_acompanhantes_paciente(paciente.id, somente_ativos=True):
        return None
    return (
        'Paciente com condição "Necessita acompanhante" precisa ter '
        'pelo menos um acompanhante cadastrado na ficha antes do agendamento.'
    )


def html_secao_acompanhantes_paciente(paciente):
    """Bloco HTML (fora do form principal) para gerenciar acompanhantes na ficha."""
    from html import escape
    rows = []
    lista = listar_acompanhantes_paciente(paciente.id, somente_ativos=True)
    for ac in lista:
        nasc_ac = format_data_br(ac.data_nascimento) if ac.data_nascimento else '—'
        idade_txt = formatar_idade_exibir(ac.data_nascimento) if ac.data_nascimento else '—'
        rows.append(f'''
            <tr>
              {html_td_id(ac.id)}
              <td>{escape(ac.parentesco or '—')}</td>
              <td>{escape(ac.nome or '')}</td>
              <td>{escape(nasc_ac)}</td>
              <td>{escape(idade_txt)}</td>
              <td>{escape(format_rg(ac.rg) if ac.rg else '—')}</td>
              <td>{escape(ac.telefone or '—')}</td>
              <td>
                {html_acoes_toolbar(
                    html_acao_icone(
                        'ti-edit',
                        'Editar acompanhante',
                        href=url_for('acompanhantes_editar', acompanhante_id=ac.id),
                        variant='editar',
                    ),
                    html_acao_icone(
                        'ti-user-off',
                        'Desativar acompanhante',
                        href=url_for('pacientes_acompanhante_excluir', paciente_id=paciente.id, acompanhante_id=ac.id),
                        variant='excluir',
                        confirm_msg='Desativar este acompanhante?',
                    )
                )}
              </td>
            </tr>''')
    tabela = ''.join(rows) if rows else (
        '<tr><td colspan="8" style="text-align:center;color:#666;">Nenhum acompanhante cadastrado</td></tr>'
    )
    alerta = ''
    if paciente_necessita_acompanhante(paciente) and not lista:
        alerta = '''
        <div class="alert alert-warning" style="margin-bottom:0.75rem;">
          Este paciente está com condição <strong>Necessita acompanhante</strong>.
          Cadastre pelo menos um acompanhante abaixo — sem isso não será possível agendar transporte.
        </div>'''
    elif paciente_necessita_acompanhante(paciente):
        alerta = f'''
        <div class="alert alert-info" style="margin-bottom:0.75rem;">
          Condição <strong>Necessita acompanhante</strong> ativa.
          {len(lista)} acompanhante(s) cadastrado(s). No agendamento só se escolhe qual vai na viagem.
        </div>'''
    elif lista:
        alerta = f'''
        <div class="alert alert-success" style="margin-bottom:0.75rem;">
          {len(lista)} acompanhante(s) já cadastrado(s) neste paciente.
          Para alterar dados, use o ícone de editar na tabela.
          O botão <strong>Salvar</strong> acima grava só os dados do paciente.
        </div>'''

    # Com AC já cadastrado: formulário de novo fica recolhido (evita confusão com "Salvar" do paciente).
    form_aberto = not lista
    form_display = 'block' if form_aberto else 'none'
    btn_toggle = ''
    if lista:
        btn_toggle = '''
        <button type="button" class="btn btn-secondary" id="btn-mostrar-form-ac"
                onclick="document.getElementById('form-ac-novo-wrap').style.display='block'; this.style.display='none';">
          ➕ Adicionar outro acompanhante
        </button>'''

    return f'''
    <div class="card" style="margin-top:1.25rem;">
      <div class="page-header" style="margin-bottom:0.75rem;">
        <h3 style="margin:0;">👥 Acompanhantes do paciente</h3>
        <p style="margin:0.35rem 0 0;color:#555;">
          Cadastre quantos forem necessários aqui (antes do agendamento).
          Também disponível em <a href="{url_for('acompanhantes')}">Cadastros → Acompanhantes</a>.
          No agendamento apenas se escolhe qual acompanhará a viagem.
        </p>
      </div>
      {alerta}
      <div class="table-responsive">
        <table class="table">
          <thead>
            <tr>
              <th>ID</th><th>Parentesco</th><th>Nome</th><th>Nascimento</th><th>Idade</th><th>RG</th><th>Telefone</th><th></th>
            </tr>
          </thead>
          <tbody>{tabela}</tbody>
        </table>
      </div>
      <div style="margin-top:1rem;">{btn_toggle}</div>
      <div id="form-ac-novo-wrap" style="display:{form_display};margin-top:1rem;">
      <form method="POST" action="{url_for('pacientes_acompanhante_novo', paciente_id=paciente.id)}" id="form-acompanhantes-lote">
        <h4 style="margin:0 0 0.75rem;">➕ {'Cadastrar acompanhante(s)' if not lista else 'Novo acompanhante'}</h4>
        <p style="margin:0 0 0.75rem;color:#666;font-size:0.9rem;">
          Este formulário serve só para <strong>incluir novos</strong> acompanhantes.
          Não é necessário reenviar os que já aparecem na tabela.
        </p>
        <div id="ac-linhas">
          <div class="ac-linha" style="border:1px solid #ddd;border-radius:0.5rem;padding:0.75rem;margin-bottom:0.75rem;background:#fafafa;">
            <div class="form-row">
              <div class="form-group">
                <label>Parentesco</label>
                {html_select_parentesco(name='ac_parentesco', field_id='ac_parentesco_0')}
              </div>
              {html_campo_nome_acompanhante()}
            </div>
            <div class="form-row">
              {html_campo_rg(name='ac_rg', field_id='ac_rg_0')}
              <div class="form-group">
                <label>Telefone</label>
                <input type="tel" name="ac_telefone" placeholder="(00) 00000-0000" maxlength="16">
              </div>
              {html_campo_nasc_acompanhante(field_id='ac_data_nascimento_0', required=False)}
            </div>
          </div>
        </div>
        <div class="form-actions" style="display:flex;gap:0.5rem;flex-wrap:wrap;">
          <button type="button" class="btn btn-secondary" onclick="adicionarLinhaAcompanhante()">➕ Cadastrar mais um</button>
          <button type="submit" class="btn btn-success">💾 Salvar novo(s) acompanhante(s)</button>
          {('<button type="button" class="btn btn-secondary" onclick="document.getElementById(\'form-ac-novo-wrap\').style.display=\'none\'; var b=document.getElementById(\'btn-mostrar-form-ac\'); if(b) b.style.display=\'inline-block\';">Cancelar</button>') if lista else ''}
        </div>
      </form>
      </div>
      {html_assets_parentesco_select()}
      {html_script_nome_acompanhante()}
      <script>
        function adicionarLinhaAcompanhante() {{
          const wrap = document.getElementById('ac-linhas');
          const modelo = wrap.querySelector('.ac-linha');
          const clone = modelo.cloneNode(true);
          clone.querySelectorAll('input').forEach(inp => {{
            if (inp.name === 'ac_parentesco_outros') return;
            if (inp.classList.contains('stp-ac-nome-flag') || inp.classList.contains('stp-ac-nome-check')) return;
            if (inp.classList.contains('stp-ac-nome-input')) return;
            inp.value = '';
          }});
          if (window.rebuildParentescoFieldInClone) window.rebuildParentescoFieldInClone(clone);
          if (window.resetNomeAcompanhanteLinha) window.resetNomeAcompanhanteLinha(clone);
          else resetNomeAcompanhanteLinha(clone);
          const btnRem = document.createElement('button');
          btnRem.type = 'button';
          btnRem.className = 'btn btn-sm btn-danger';
          btnRem.textContent = 'Remover esta linha';
          btnRem.style.marginTop = '0.35rem';
          btnRem.onclick = function() {{ clone.remove(); }};
          clone.appendChild(btnRem);
          wrap.appendChild(clone);
          if (window.initParentescoSelects) window.initParentescoSelects(clone);
        }}
      </script>
    </div>
    '''


def parse_dados_acompanhante_cartao(observacoes):
    """Extrai acompanhante estruturado das observações (cartão do motorista)."""
    resultado = {
        'tem_acompanhante': False,
        'nome': '',
        'idade': '',
        'rg': '',
        'tel': '',
    }
    if not observacoes:
        return resultado
    texto = str(observacoes)
    upper = texto.upper()

    def _campo(marcadores):
        for marcador in marcadores:
            if marcador in upper:
                idx = upper.index(marcador)
                trecho = texto[idx + len(marcador):]
                for sep in ('|', ';', '\n', ' RG AC', ' TEL AC', ' IDADE AC', ' AC:', ' H.'):
                    # corta em próximos rótulos comuns
                    pass
                # corta em pipe/ponto-e-vírgula/nova linha
                for sep in ('|', ';', '\n'):
                    if sep in trecho:
                        trecho = trecho.split(sep)[0]
                # remove rótulos colados
                for stop in ('RG AC:', 'TEL AC:', 'IDADE AC:', 'NOME AC:', 'ACOMPANHANTE:'):
                    pos = trecho.upper().find(stop)
                    if pos > 0:
                        trecho = trecho[:pos]
                return trecho.strip()[:120]
        return ''

    nome = _campo(('NOME AC:', 'ACOMPANHANTE:', 'ACOMP.', 'ACOMP '))
    rg = _campo(('RG AC:', 'RG AC '))
    tel = _campo(('TEL AC:', 'TEL AC '))
    idade = _campo(('IDADE AC:', 'IDADE AC '))

    if nome and nome.upper() not in ('SEM ACOMPANHANTE', 'SEM ACOMP', 'NÃO CONSTA', 'NAO CONSTA', '—', '-'):
        resultado['tem_acompanhante'] = True
        resultado['nome'] = nome
        resultado['rg'] = rg
        resultado['tel'] = tel
        resultado['idade'] = idade
    elif 'SEM ACOMP' in upper or 'SEM ACOMPANHANTE' in upper:
        resultado['tem_acompanhante'] = False
    elif 'ACOMPANHANTE' in upper or 'NOME AC' in upper:
        resultado['tem_acompanhante'] = True
        resultado['nome'] = nome or 'Sim'
    return resultado


def parse_campo_observacao_cartao(observacoes, marcadores):
    """Extrai um campo rotulado das observações (ex.: PONTO:, H. CONSULTA:)."""
    if not observacoes:
        return ''
    texto = str(observacoes)
    upper = texto.upper()
    for marcador in marcadores:
        if marcador in upper:
            idx = upper.index(marcador)
            trecho = texto[idx + len(marcador):]
            for sep in ('|', '\n'):
                if sep in trecho:
                    trecho = trecho.split(sep)[0]
            return trecho.strip()[:200]
    return ''


def agendamento_tem_recurso_programado(agendamento):
    """True se há veículo ou frota definidos na programação."""
    return bool(
        agendamento
        and (getattr(agendamento, 'veiculo_id', None) or getattr(agendamento, 'frota_id', None))
    )


def agendamento_tem_programacao(agendamento):
    """True quando motorista + (veículo ou frota) já foram definidos."""
    return bool(
        agendamento
        and agendamento.motorista_id
        and agendamento_tem_recurso_programado(agendamento)
    )


def recurso_programacao_exibir(agendamento):
    """
    Texto do campo FROTA no Cartão / Folha Espelho.
    Prioridade: frota cadastrada → número de frota do veículo → placa.
    """
    if not agendamento:
        return ''
    frota = getattr(agendamento, 'frota', None)
    if frota is None and getattr(agendamento, 'frota_id', None):
        frota = db.session.get(Frota, agendamento.frota_id)
    if frota:
        txt = frota_identificacao_exibir(frota)
        return '' if txt == '—' else txt
    veiculo = getattr(agendamento, 'veiculo', None)
    if veiculo:
        nf = numero_frota_exibir(veiculo)
        if nf and nf != '—':
            return nf
        return (veiculo.placa or '').strip()
    return ''


def agendamento_esta_cancelado(agendamento):
    """True se o agendamento está cancelado."""
    return bool(agendamento) and (agendamento.status or '').lower() == 'cancelado'


def agendamento_permite_edicao_cadastro(agendamento):
    """Edição dos dados cadastrais liberada até concluir/cancelar."""
    if not agendamento:
        return False
    return (agendamento.status or '').lower() not in ('concluido', 'cancelado')


def agendamento_permite_programacao(agendamento):
    """Programar motorista/veículo: bloqueado para concluído e cancelado."""
    if not agendamento:
        return False
    return (agendamento.status or '').lower() not in ('concluido', 'cancelado')


def agendamento_permite_reativar(agendamento):
    """Somente cancelado pode ser reativado (volta para agendado)."""
    return agendamento_esta_cancelado(agendamento)


def snapshot_cadastro_agendamento(agendamento):
    """Snapshot dos campos de cadastro (para log de auditoria de alteração)."""
    if not agendamento:
        return {}
    return {
        'paciente_id': agendamento.paciente_id,
        'tipo_transporte': agendamento.tipo_transporte,
        'data': agendamento.data.isoformat() if agendamento.data else None,
        'hora': agendamento.hora.strftime('%H:%M') if agendamento.hora else None,
        'hora_consulta': agendamento.hora_consulta.strftime('%H:%M') if getattr(agendamento, 'hora_consulta', None) else None,
        'origem': agendamento.origem,
        'destino': agendamento.destino,
        'cep_origem': agendamento.cep_origem,
        'cep_destino': agendamento.cep_destino,
        'cidade_origem': agendamento.cidade_origem,
        'cidade_destino': agendamento.cidade_destino,
        'tipo_destino': agendamento.tipo_destino,
        'destino_cnes_codigo': getattr(agendamento, 'destino_cnes_codigo', None),
        'destino_cnes_nome': getattr(agendamento, 'destino_cnes_nome', None),
        'possui_acompanhante': bool(agendamento.possui_acompanhante),
        'acompanhante_id': agendamento.acompanhante_id,
        'veiculo_id': agendamento.veiculo_id,
        'frota_id': getattr(agendamento, 'frota_id', None),
        'motorista_id': agendamento.motorista_id,
        'observacoes': agendamento.observacoes,
        'status': agendamento.status,
    }


def diff_cadastro_agendamento(antes, depois):
    """Lista de (campo, valor_anterior, valor_novo) para campos que mudaram."""
    mudancas = []
    for chave in sorted(set(antes) | set(depois)):
        a = antes.get(chave)
        d = depois.get(chave)
        if a != d:
            mudancas.append((chave, a, d))
    return mudancas


def montar_endereco_paciente_de_form(form):
    """Monta endereco a partir de logradouro/número/bairro/complemento."""
    logradouro = (form.get('logradouro') or '').strip()
    numero = (form.get('numero') or '').strip()
    bairro = (form.get('bairro') or '').strip()
    complemento = (form.get('complemento') or '').strip()
    endereco = compor_endereco_paciente(logradouro, numero, bairro, complemento)
    if not endereco:
        endereco = (form.get('endereco') or '').strip()
    return logradouro, numero, bairro, complemento, endereco


def valores_cadastro_agendamento_vazios(hoje_iso=None):
    """Valores padrão do formulário de cadastro (novo)."""
    from datetime import date as _date
    return {
        'paciente_id': '',
        'tipo_transporte': None,
        'data': hoje_iso or _date.today().strftime('%Y-%m-%d'),
        'hora': '',
        'hora_consulta': '',
        'possui_acompanhante': False,
        'acompanhante_id': '',
        'cep_origem': '',
        'cidade_origem': '',
        'logradouro_origem': '',
        'numero_origem': '',
        'bairro_origem': '',
        'origem': '',
        'tipo_destino': 'cep',
        'cep_destino': '',
        'cidade_destino': '',
        'destino': '',
        'cidade_sp_select': '',
        'destino_cidade_sp': '',
        'destino_manual': '',
        'cidade_cnes': '',
        'destino_cnes_codigo': '',
        'destino_cnes_nome': '',
        'destino_cnes_livre': '',
    }


def valores_cadastro_de_agendamento(agendamento):
    """Prefill do formulário a partir de um agendamento existente."""
    tipo = (agendamento.tipo_destino or 'cep').strip() or 'cep'
    destino = agendamento.destino or ''
    cidade_sp = ''
    destino_cidade_sp = ''
    destino_manual = ''
    cidade_cnes = ''
    destino_cnes_codigo = getattr(agendamento, 'destino_cnes_codigo', None) or ''
    destino_cnes_nome = getattr(agendamento, 'destino_cnes_nome', None) or ''
    destino_cnes_livre = ''
    logradouro_origem, numero_origem, bairro_origem = partir_origem_endereco(agendamento.origem or '')
    if tipo == 'cnes':
        cidade_cnes = (agendamento.cidade_destino or '').replace(' - SP', '').strip()
        if not cidade_cnes and '/' in destino:
            cidade_cnes = destino.split('/', 1)[0].strip()
        # Sem código CNES = destino digitado manualmente na cidade
        if not destino_cnes_codigo:
            if destino_cnes_nome:
                destino_cnes_livre = destino_cnes_nome
            elif '/' in destino:
                resto = destino.split('/', 1)[1].strip()
                # remove sufixo de endereço formatado "Nome - Rua..."
                destino_cnes_livre = resto
            else:
                destino_cnes_livre = destino
    elif tipo == 'cidade' and ' - ' in destino and destino.endswith(', SP'):
        try:
            partes = destino.rsplit(' - ', 1)
            destino_cidade_sp = partes[0]
            cidade_sp = partes[1].replace(', SP', '').strip()
        except Exception:
            destino_cidade_sp = destino
            cidade_sp = (agendamento.cidade_destino or '').replace(' - SP', '').strip()
    elif tipo == 'cidade':
        cidade_sp = (agendamento.cidade_destino or '').replace(' - SP', '').strip()
        destino_cidade_sp = destino
    elif tipo == 'manual':
        destino_manual = destino
    return {
        'paciente_id': agendamento.paciente_id or '',
        'tipo_transporte': agendamento.tipo_transporte,
        'data': agendamento.data.strftime('%Y-%m-%d') if agendamento.data else '',
        'hora': agendamento.hora.strftime('%H:%M') if agendamento.hora else '',
        'hora_consulta': agendamento.hora_consulta.strftime('%H:%M') if getattr(agendamento, 'hora_consulta', None) else '',
        'possui_acompanhante': bool(agendamento.possui_acompanhante),
        'acompanhante_id': agendamento.acompanhante_id or '',
        'cep_origem': agendamento.cep_origem or '',
        'cidade_origem': agendamento.cidade_origem or '',
        'logradouro_origem': logradouro_origem,
        'numero_origem': numero_origem,
        'bairro_origem': bairro_origem,
        'origem': agendamento.origem or '',
        'tipo_destino': tipo,
        'cep_destino': agendamento.cep_destino or '',
        'cidade_destino': agendamento.cidade_destino or '',
        'destino': destino,
        'cidade_sp_select': cidade_sp,
        'destino_cidade_sp': destino_cidade_sp,
        'destino_manual': destino_manual,
        'cidade_cnes': cidade_cnes,
        'destino_cnes_codigo': destino_cnes_codigo,
        'destino_cnes_nome': destino_cnes_nome,
        'destino_cnes_livre': destino_cnes_livre,
    }


def compor_origem_endereco(logradouro, numero='', bairro=''):
    """Monta texto único de origem a partir de logradouro + número + bairro."""
    return compor_endereco_paciente(logradouro, numero, bairro, '')


def compor_endereco_paciente(logradouro, numero='', bairro='', complemento=''):
    """Monta texto único: LOGADOURO, Nº, BAIRRO[, COMPLEMENTO]."""
    logradouro = (logradouro or '').strip().upper()
    numero = (numero or '').strip().upper()
    bairro = (bairro or '').strip().upper()
    complemento = (complemento or '').strip().upper()
    partes = []
    if logradouro:
        partes.append(logradouro)
    if numero:
        partes.append(numero)
    if bairro:
        partes.append(bairro)
    if complemento:
        partes.append(complemento)
    return ', '.join(partes)


def partir_endereco_completo(texto):
    """
    Separa texto legado em (logradouro, numero, bairro, complemento).
    Exemplos:
      'PAULO FREDERICO ROGGER, 84, PQ ESTER'
        → ('PAULO FREDERICO ROGGER', '84', 'PQ ESTER', '')
      '7 DE SETEMBRO, 347, CENTRO, ATRAS DA DELEGACIA'
        → ('7 DE SETEMBRO', '347', 'CENTRO', 'ATRAS DA DELEGACIA')
      'Cosmópolis-SP'
        → ('Cosmópolis-SP', '', '', '')
    """
    import re
    texto = ' '.join(str(texto or '').strip().split())
    if not texto:
        return '', '', '', ''

    # Formato com marca explícita de número: "RUA X, Nº 123, BAIRRO[, COMPL]"
    m = re.match(
        r'^(.*?),\s*n[º°o.]?\s*([^,]+)\s*(?:,\s*(.*))?$',
        texto,
        flags=re.IGNORECASE,
    )
    if m:
        log = m.group(1).strip()
        num = m.group(2).strip()
        resto = [p.strip() for p in (m.group(3) or '').split(',') if p.strip()]
        bai = resto[0] if resto else ''
        comp = ', '.join(resto[1:]) if len(resto) > 1 else ''
        return log, num, bai, comp

    partes = [p.strip() for p in texto.split(',') if p.strip()]
    if len(partes) == 1:
        return partes[0], '', '', ''

    num_re = re.compile(
        r'^(?:n[º°o.]?\s*)?(\d+[A-Za-z0-9\-/]*)$|^(S/?N|SN|S\.N\.|SEM\s+N[UÚ]MERO)$',
        re.IGNORECASE,
    )
    num_idx = None
    num_val = ''
    for i, p in enumerate(partes):
        mnum = num_re.match(p)
        if mnum:
            num_idx = i
            num_val = (mnum.group(1) or mnum.group(2) or p).strip()
            break

    if num_idx is None:
        # Sem número: 1º = rua; 2º = bairro; demais = complemento
        log = partes[0]
        bai = partes[1] if len(partes) > 1 else ''
        comp = ', '.join(partes[2:]) if len(partes) > 2 else ''
        return log, '', bai, comp

    log = ', '.join(partes[:num_idx]).strip() if num_idx > 0 else partes[0]
    resto = partes[num_idx + 1:]
    bai = resto[0] if resto else ''
    comp = ', '.join(resto[1:]) if len(resto) > 1 else ''
    return log, num_val, bai, comp


def partir_origem_endereco(origem):
    """Tenta separar origem salva em logradouro, número e bairro."""
    log, num, bai, comp = partir_endereco_completo(origem)
    if comp:
        bai = f'{bai} - {comp}' if bai else comp
    return log, num, bai


def endereco_paciente_para_campos(paciente):
    """Extrai cep/logradouro/número/bairro/complemento (campos ou texto em endereco)."""
    if not paciente:
        return {
            'cep': '', 'logradouro': '', 'numero': '', 'bairro': '', 'complemento': '',
        }
    logradouro = (getattr(paciente, 'logradouro', None) or '').strip()
    numero = (getattr(paciente, 'numero', None) or '').strip()
    bairro = (getattr(paciente, 'bairro', None) or '').strip()
    complemento = (getattr(paciente, 'complemento', None) or '').strip()
    cep = (getattr(paciente, 'cep', None) or '').strip()

    precisa_parse = (
        not logradouro
        or not numero
        or (',' in logradouro and not numero)
    )
    if precisa_parse:
        fonte = (getattr(paciente, 'endereco', None) or '').strip() or logradouro
        log2, num2, bai2, comp2 = partir_endereco_completo(fonte)
        if not logradouro or (',' in logradouro and not numero):
            logradouro = log2 or logradouro
        if not numero:
            numero = num2
        if not bairro:
            bairro = bai2
        if not complemento:
            complemento = comp2

    return {
        'cep': cep,
        'logradouro': logradouro,
        'numero': numero,
        'bairro': bairro,
        'complemento': complemento,
    }


def ponto_embarque_do_paciente(paciente):
    """
    Ponto de embarque para impressão/cadastro.
    Prioriza ponto_embarque; fallback legado em ponto_referencia.
    """
    if not paciente:
        return ''
    pe = (getattr(paciente, 'ponto_embarque', None) or '').strip()
    if pe:
        return pe
    return (getattr(paciente, 'ponto_referencia', None) or '').strip()


def montar_origem_do_paciente(paciente):
    """Monta origem a partir do endereço cadastrado do paciente (quando origem fica em branco)."""
    if not paciente:
        return 'Não informado'
    end = endereco_paciente_para_campos(paciente)
    composto = compor_endereco_paciente(
        end['logradouro'], end['numero'], end['bairro'], end['complemento']
    )
    return composto or ((paciente.endereco or '').strip() or 'Não informado')


def extrair_payload_cadastro_agendamento(form):
    """
    Lê/valida campos do cadastro (etapa 1).
    Retorna (payload: dict|None, erro: str|None, redirect_extra: dict|None).
    redirect_extra pode ter {'paciente_id': id} para ir à ficha.
    """
    tipo_transporte, erro_esp = normalizar_especialidade_form(form)
    if erro_esp:
        return None, erro_esp, None

    paciente_id_raw = form.get('paciente_id', 0)
    try:
        paciente_id = int(paciente_id_raw or 0)
    except (TypeError, ValueError):
        paciente_id = 0

    data = form.get('data')
    hora = form.get('hora')
    hora_consulta_raw = (form.get('hora_consulta') or '').strip()
    logradouro_origem = (form.get('logradouro_origem') or '').strip()
    numero_origem = (form.get('numero_origem') or '').strip()
    bairro_origem = (form.get('bairro_origem') or '').strip()
    origem = compor_origem_endereco(logradouro_origem, numero_origem, bairro_origem)
    if not origem:
        origem = (form.get('origem') or '').strip()
    destino = (form.get('destino') or '').strip()
    cep_origem = (form.get('cep_origem') or '').strip()
    cep_destino = (form.get('cep_destino') or '').strip()
    cidade_origem = (form.get('cidade_origem') or '').strip()
    cidade_destino = (form.get('cidade_destino') or '').strip()
    tipo_destino = form.get('tipo_destino', 'cep') or 'cep'

    destino_cnes_codigo = None
    destino_cnes_nome = None

    # Cada tipo de destino é autônomo: valida e monta só a opção selecionada.
    if tipo_destino == 'cep':
        destino = (form.get('destino') or '').strip().upper()
        cidade_destino = (form.get('cidade_destino') or '').strip()
        cep_destino = (form.get('cep_destino') or '').strip()
        if not destino:
            return None, 'Informe o endereço/local de destino (opção Buscar por CEP)!', None

    elif tipo_destino == 'cidade':
        # Texto livre — aceita exatamente o digitado (ex.: "HC"), sem cruzar com CNES/CEP/manual.
        cidade_sp = (form.get('cidade_sp_select') or '').strip()
        destino_cidade_sp = (form.get('destino_cidade_sp') or '').strip()
        if not cidade_sp:
            return None, 'Selecione a cidade de destino!', None
        if not destino_cidade_sp:
            return None, 'Informe o local na cidade (ex.: HC, AME)!', None
        destino = f"{destino_cidade_sp} - {cidade_sp}, SP"
        cidade_destino = f"{cidade_sp} - SP"
        cep_destino = ''

    elif tipo_destino == 'cnes':
        cidade_cnes = (form.get('cidade_cnes') or '').strip()
        destino_cnes_codigo = (form.get('destino_cnes_codigo') or '').strip() or None
        destino_cnes_nome = (form.get('destino_cnes_nome') or '').strip() or None
        destino_cnes_livre = (form.get('destino_cnes_livre') or '').strip()
        if not cidade_cnes:
            return None, 'Selecione a cidade do Destino Predefinido!', None
        if destino_cnes_codigo:
            row = obter_estabelecimento_cache(CnesEstabelecimento, destino_cnes_codigo)
            if row:
                est = {
                    'nome_fantasia': row.nome_fantasia,
                    'razao_social': row.razao_social or '',
                    'endereco': row.endereco or '',
                    'numero': row.numero or '',
                    'bairro': row.bairro or '',
                    'municipio_nome': row.municipio_nome or cidade_cnes,
                }
                destino = formatar_destino_cnes(est, cidade_cnes or row.municipio_nome)
                destino_cnes_nome = row.nome_fantasia
                if row.cep:
                    cep_destino = (row.cep or '').strip()
            elif destino_cnes_nome:
                destino = f"{cidade_cnes}/{destino_cnes_nome}"
            else:
                return None, 'Estabelecimento CNES inválido. Selecione novamente o destino.', None
            cidade_destino = f"{cidade_cnes} - SP"
        elif destino_cnes_livre:
            # Fallback: clínica/hospital não encontrado ou desatualizado no CNES
            destino = f"{cidade_cnes}/{destino_cnes_livre}"
            destino_cnes_nome = destino_cnes_livre
            destino_cnes_codigo = None
            cidade_destino = f"{cidade_cnes} - SP"
        else:
            return None, 'Selecione um estabelecimento do CNES ou digite o nome/endereço do destino!', None

    elif tipo_destino == 'manual':
        destino_manual = (form.get('destino_manual') or '').strip()
        if not destino_manual:
            return None, 'Informe o endereço completo de destino (opção Manual)!', None
        destino = destino_manual
        # Manual não depende de CEP/cidade/CNES
        cidade_destino = cidade_destino or ''
        cep_destino = cep_destino or ''

    else:
        return None, 'Tipo de destino inválido!', None

    if not all([paciente_id, tipo_transporte, data, hora, destino]):
        return None, 'Por favor, preencha todos os campos obrigatórios!', None

    # Destino Predefinido: origem opcional (usa endereço do paciente se em branco).
    # Demais opções: origem obrigatória (logradouro + número).
    if tipo_destino != 'cnes' and not origem:
        return None, 'Informe o logradouro e o número de origem!', None

    paciente_sel = db.session.get(Paciente, paciente_id)
    if not paciente_sel or not paciente_sel.ativo:
        return None, 'Paciente inválido ou inativo!', None

    if tipo_destino == 'cnes' and not origem:
        origem = montar_origem_do_paciente(paciente_sel)

    erro_pre = validar_acompanhantes_cadastrados_para_condicao(paciente_sel)
    if erro_pre:
        return None, erro_pre, {'paciente_id': paciente_id}

    try:
        data_obj = datetime.strptime(data, '%Y-%m-%d').date()
        hora_obj = datetime.strptime(hora, '%H:%M').time()
    except ValueError:
        return None, 'Data ou hora inválida!', None

    hora_consulta_obj = None
    if hora_consulta_raw:
        try:
            hora_consulta_obj = datetime.strptime(hora_consulta_raw, '%H:%M').time()
        except ValueError:
            return None, 'Hora da consulta inválida!', None

    payload = {
        'paciente_id': paciente_id,
        'tipo_transporte': tipo_transporte,
        'data': data_obj,
        'hora': hora_obj,
        'hora_consulta': hora_consulta_obj,
        'origem': origem,
        'destino': destino,
        'cep_origem': cep_origem or None,
        'cep_destino': cep_destino or None,
        'cidade_origem': cidade_origem or None,
        'cidade_destino': cidade_destino or None,
        'tipo_destino': tipo_destino or 'cep',
        'destino_cnes_codigo': destino_cnes_codigo,
        'destino_cnes_nome': destino_cnes_nome,
    }
    return payload, None, None


def aplicar_payload_cadastro_agendamento(agendamento, payload, form):
    """
    Aplica payload + acompanhante no agendamento (não faz commit).
    Preserva veiculo/motorista/observacoes/status.
    Retorna erro_str ou None.
    """
    agendamento.paciente_id = payload['paciente_id']
    agendamento.tipo_transporte = payload['tipo_transporte']
    agendamento.data = payload['data']
    agendamento.hora = payload['hora']
    agendamento.hora_consulta = payload.get('hora_consulta')
    agendamento.origem = payload['origem']
    agendamento.destino = payload['destino']
    agendamento.cep_origem = payload['cep_origem']
    agendamento.cep_destino = payload['cep_destino']
    agendamento.cidade_origem = payload['cidade_origem']
    agendamento.cidade_destino = payload['cidade_destino']
    agendamento.tipo_destino = payload['tipo_destino']
    if payload.get('tipo_destino') == 'cnes':
        agendamento.destino_cnes_codigo = payload.get('destino_cnes_codigo')
        agendamento.destino_cnes_nome = payload.get('destino_cnes_nome')
    else:
        agendamento.destino_cnes_codigo = None
        agendamento.destino_cnes_nome = None
    return aplicar_acompanhante_no_agendamento(agendamento, form, payload['paciente_id'])




def gerar_conteudo_form_cadastro_agendamento(
    *,
    valores,
    breadcrumb_extra,
    titulo,
    subtitulo,
    banner_html,
    submit_label,
    cancel_href,
    filtro_endpoint='agendamentos_novo',
    filtro_endpoint_kwargs=None,
):
    """
    Formulário único de cadastro/correção de agendamento (etapa 1).
    Usado por /agendamentos/novo e /agendamentos/corrigir/<id>.
    """
    from html import escape
    from flask import get_flashed_messages, url_for

    LIMITE_SELECT = 300
    filtros = obter_filtros_paciente_vinculo_request()
    tem_filtro = filtros_tem_valores(filtros)
    total_ativos = Paciente.query.filter_by(ativo=True).count()

    pid_atual = valores.get('paciente_id') or ''
    try:
        pid_atual_int = int(pid_atual) if str(pid_atual).strip() else None
    except (TypeError, ValueError):
        pid_atual_int = None

    query = montar_query_paciente_vinculo(filtros)
    total_filtrado = query.count() if tem_filtro else total_ativos
    pacientes = []
    if tem_filtro:
        pacientes = query.order_by(Paciente.nome).limit(LIMITE_SELECT).all()
    elif pid_atual_int:
        p_pre = db.session.get(Paciente, pid_atual_int)
        if p_pre and p_pre.ativo:
            pacientes = [p_pre]

    if pid_atual_int and not any(p.id == pid_atual_int for p in pacientes):
        p_pre = db.session.get(Paciente, pid_atual_int)
        if p_pre and p_pre.ativo:
            pacientes = [p_pre] + list(pacientes)

    exibidos = len(pacientes)
    filtros_html = gerar_filtros_paciente_vinculo(
        filtros,
        total_filtrado,
        exibidos,
        endpoint=filtro_endpoint,
        endpoint_kwargs=filtro_endpoint_kwargs or {},
    )

    pacientes_options = ""
    auto_sel_unico = bool(tem_filtro and len(pacientes) == 1 and not pid_atual_int)
    for p in pacientes:
        nec = '1' if paciente_necessita_acompanhante(p) else '0'
        qtd_ac = len(listar_acompanhantes_paciente(p.id, somente_ativos=True))
        sel = ' selected' if (pid_atual_int == p.id or auto_sel_unico) else ''
        end_campos = endereco_paciente_para_campos(p)
        log_p = escape(end_campos['logradouro'])
        num_p = escape(end_campos['numero'])
        bai_p = escape(end_campos['bairro'])
        cep_p = escape(end_campos['cep'])
        pacientes_options += (
            f'<option value="{p.id}" data-necessita-ac="{nec}" data-qtd-ac="{qtd_ac}"'
            f' data-cep="{cep_p}" data-logradouro="{log_p}" data-numero="{num_p}" data-bairro="{bai_p}"{sel}>'
            f'ID {p.id} — {escape(p.nome)} - CPF: {escape(p.cpf or "")}</option>'
        )

    aviso_paciente = ''
    if not tem_filtro and not pid_atual_int:
        aviso_paciente = (
            '<div class="alert alert-info" style="margin-bottom:1rem;">'
            f'Há <strong>{format_numero_br(total_ativos)}</strong> pacientes ativos. '
            'Filtre por <strong>ID</strong>, nome ou CPF e clique em <strong>Filtrar</strong> '
            'para carregar o paciente no select (ex.: ID <strong>5</strong> — JOSÉ ANTONIO AMBROSIO). '
            'Ao selecionar, o endereço de origem é preenchido automaticamente.'
            '</div>'
        )
    elif tem_filtro and total_filtrado == 0 and not pacientes:
        aviso_paciente = (
            '<div class="alert alert-warning" style="margin-bottom:1rem;">'
            'Nenhum paciente ativo encontrado com os filtros informados.</div>'
        )
    elif tem_filtro and total_filtrado > LIMITE_SELECT:
        aviso_paciente = (
            f'<div class="alert alert-warning" style="margin-bottom:1rem;">'
            f'Muitos resultados ({format_numero_br(total_filtrado)}). '
            f'Exibindo os primeiros {LIMITE_SELECT} — refine os filtros.</div>'
        )

    select_disabled = ' disabled' if not pacientes else ''
    select_required = ' required' if pacientes else ''

    messages_html = ""
    for category, message in get_flashed_messages(with_categories=True):
        messages_html += f'<div class="alert alert-{category}">{message}</div>'

    v = valores
    tipo_destino = (v.get('tipo_destino') or 'cep').strip() or 'cep'
    chk_cep = 'checked' if tipo_destino == 'cep' else ''
    chk_cidade = 'checked' if tipo_destino == 'cidade' else ''
    chk_cnes = 'checked' if tipo_destino == 'cnes' else ''
    chk_manual = 'checked' if tipo_destino == 'manual' else ''
    disp_cep = 'block' if tipo_destino == 'cep' else 'none'
    disp_cidade = 'block' if tipo_destino == 'cidade' else 'none'
    disp_cnes = 'block' if tipo_destino == 'cnes' else 'none'
    disp_manual = 'block' if tipo_destino == 'manual' else 'none'
    possui_ac = bool(v.get('possui_acompanhante'))
    chk_ac = 'checked' if possui_ac else ''
    disp_ac = 'block' if possui_ac else 'none'
    ac_id = v.get('acompanhante_id') or ''
    data_val = escape(str(v.get('data') or ''))
    hora_val = escape(str(v.get('hora') or ''))
    hora_consulta_val = escape(str(v.get('hora_consulta') or ''))
    cep_origem = escape(str(v.get('cep_origem') or ''))
    cidade_origem = escape(str(v.get('cidade_origem') or ''))
    logradouro_origem = escape(str(v.get('logradouro_origem') or ''))
    numero_origem = escape(str(v.get('numero_origem') or ''))
    bairro_origem = escape(str(v.get('bairro_origem') or ''))
    origem = escape(str(v.get('origem') or ''))
    cep_destino = escape(str(v.get('cep_destino') or ''))
    cidade_destino = escape(str(v.get('cidade_destino') or ''))
    destino = escape(str(v.get('destino') or ''))
    destino_cidade_sp = escape(str(v.get('destino_cidade_sp') or ''))
    destino_manual = escape(str(v.get('destino_manual') or ''))
    cidade_sp_select = str(v.get('cidade_sp_select') or '')
    cidade_cnes_val = str(v.get('cidade_cnes') or '').strip()
    destino_cnes_codigo_val = str(v.get('destino_cnes_codigo') or '').strip()
    destino_cnes_nome_val = escape(str(v.get('destino_cnes_nome') or ''))
    destino_cnes_livre_val = escape(str(v.get('destino_cnes_livre') or ''))
    breadcrumb_esc = escape(str(breadcrumb_extra))
    especialidade_html = html_select_especialidade(valor_atual=v.get('tipo_transporte'))
    cancel = escape(cancel_href)
    submit = escape(submit_label)
    ac_id_js = escape(str(ac_id))
    cidade_sp_js = escape(cidade_sp_select)
    cidade_cnes_js = escape(cidade_cnes_val)
    destino_cnes_codigo_js = escape(destino_cnes_codigo_val)
    req_destino = 'required' if tipo_destino == 'cep' else ''
    qtd_cidades = qtd_cidades_destino_cnes()
    opcoes_cidades_cnes = '<option value="">Selecione a cidade...</option>'
    for c in listar_cidades_destino_cnes():
        sel = ' selected' if c['nome'] == cidade_cnes_val else ''
        opcoes_cidades_cnes += f'<option value="{escape(c["nome"])}"{sel}>{escape(c["nome"])}</option>'

    # Cidade de SP: opções locais (sem depender do IBGE para funcionar)
    opcoes_cidades_sp = '<option value="">Selecione uma cidade...</option>'
    nomes_sp = sorted({(c.get('nome') or '').strip() for c in listar_cidades_destino_cnes() if (c.get('nome') or '').strip()})
    for nome in nomes_sp:
        sel = ' selected' if nome == cidade_sp_select else ''
        opcoes_cidades_sp += f'<option value="{escape(nome)}"{sel}>{escape(nome)}</option>'

    return f"""
        <div class="breadcrumb">
            <a href="{url_for('dashboard')}">Início</a> >
            <a href="{url_for('agendamentos')}">Agendamentos</a> >
            {breadcrumb_esc}
        </div>

        <div class="page-header">
            <h2>{titulo}</h2>
            <p>{subtitulo}</p>
        </div>

        {messages_html}
        {banner_html}
        {filtros_html}
        {aviso_paciente}

        <div class="card">
            <form method="POST" id="form-cadastro-agendamento"
                  data-acompanhante-inicial="{ac_id_js}"
                  data-cidade-sp-inicial="{cidade_sp_js}"
                  data-cidade-cnes-inicial="{cidade_cnes_js}"
                  data-cnes-codigo-inicial="{destino_cnes_codigo_js}">
                <div class="form-row">
                    <div class="form-group">
                        <label for="paciente_id">Paciente *</label>
                        <select id="paciente_id" name="paciente_id"{select_required}{select_disabled}>
                            <option value="">Selecione o paciente...</option>
                            {pacientes_options}
                        </select>
                    </div>
                    <div class="form-group">
                        {especialidade_html}
                    </div>
                </div>

                <div class="card" style="background:var(--color-95);padding:1rem 1.25rem;margin:0 0 1rem;border-left:4px solid #6f42c1;">
                    <h4 style="margin:0 0 0.75rem;color:#6f42c1;">👥 Acompanhante nesta viagem</h4>
                    <p id="ac-ajuda" style="margin:0 0 0.75rem;color:#555;font-size:0.92rem;">
                        O cadastro do acompanhante é feito na <strong>ficha do paciente</strong>.
                        Aqui você apenas escolhe qual irá nesta viagem.
                    </p>
                    <div class="form-group" style="margin-bottom:0.75rem;">
                        <label style="display:flex;align-items:center;gap:0.5rem;font-weight:600;">
                            <input type="checkbox" id="possui_acompanhante" name="possui_acompanhante" value="1"
                                   {chk_ac} onchange="alternarAcompanhanteViagem()">
                            <span id="lbl-possui-ac">Paciente levará acompanhante nesta viagem</span>
                        </label>
                    </div>
                    <div id="bloco-ac-viagem" style="display:{disp_ac};">
                        <div class="form-row">
                            <div class="form-group" style="flex:2;">
                                <label for="acompanhante_id">Acompanhante cadastrado *</label>
                                <select id="acompanhante_id" name="acompanhante_id">
                                    <option value="">Selecione o paciente primeiro...</option>
                                </select>
                                <small id="ac-status" style="color:#666;">Os acompanhantes vêm da ficha do paciente.</small>
                            </div>
                        </div>
                        <div id="ac-alerta-cadastro" class="alert alert-warning" style="display:none;margin-top:0.5rem;">
                            Este paciente <strong>necessita acompanhante</strong>, mas ainda não tem nenhum cadastrado.
                            Vá em <strong>Cadastros → Acompanhantes</strong> ou
                            <a id="ac-link-ficha" href="{url_for('acompanhantes_novo')}">cadastre agora</a>.
                        </div>
                    </div>
                </div>

                <div class="form-row">
                    <div class="form-group">
                        <label for="data">Data *</label>
                        <input type="date" id="data" name="data" value="{data_val}" required>
                    </div>
                    <div class="form-group">
                        <label for="hora">Hora de Saída *</label>
                        <input type="time" id="hora" name="hora" value="{hora_val}" required>
                    </div>
                    <div class="form-group">
                        <label for="hora_consulta">Hora da Consulta</label>
                        <input type="time" id="hora_consulta" name="hora_consulta" value="{hora_consulta_val}">
                        <small style="color:var(--gray-color);">Usada na Folha Espelho e no Cartão do Motorista</small>
                    </div>
                </div>

                <div style="background: var(--color-95); padding: 1.5rem; border-radius: 0.5rem; margin: 1rem 0;">
                    <h4 style="color: var(--primary-color); margin-bottom: 1rem;">📍 Endereços de Origem e Destino</h4>

                    <div style="background: white; padding: 1rem; border-radius: 0.5rem; margin-bottom: 1rem; border-left: 4px solid #28a745;">
                        <h5 style="color: #28a745; margin-bottom: 0.75rem;">🏠 Local de Origem (Buscar o Paciente)</h5>
                        <div class="form-group" style="margin-bottom:0.85rem;">
                            <label style="display:flex;align-items:flex-start;gap:0.55rem;font-weight:600;cursor:pointer;">
                                <input type="checkbox" id="origem_diferente_cadastro" name="origem_diferente_cadastro" value="1"
                                       onchange="alternarOrigemDiferenteCadastro()" style="margin-top:0.2rem;">
                                <span>
                                    Local de busca diferente do endereço cadastrado
                                    <small style="display:block;font-weight:400;color:#555;margin-top:0.2rem;">
                                        Desmarcado: usa o endereço da ficha do paciente (automático).
                                        Marcado: informe o endereço onde o paciente será buscado nesta viagem.
                                    </small>
                                </span>
                            </label>
                        </div>
                        <div id="origem-ficha-aviso" class="alert alert-info" style="margin:0 0 0.85rem;padding:0.55rem 0.75rem;font-size:0.9rem;">
                            Endereço preenchido pela ficha do paciente. Marque a opção acima se o local de busca for outro.
                        </div>
                        <div id="origem-diferente-aviso" class="alert alert-warning" style="display:none;margin:0 0 0.85rem;padding:0.55rem 0.75rem;font-size:0.9rem;">
                            Informe o CEP/endereço real da busca. O endereço cadastrado do paciente não será aplicado automaticamente.
                        </div>
                        <div class="form-row">
                            <div class="form-group">
                                <label for="cep_origem">CEP de Origem</label>
                                <input type="text" id="cep_origem" name="cep_origem" value="{cep_origem}" placeholder="00000-000" maxlength="9" onblur="buscarCEPOrigemAgendamento()">
                                <small id="cep-origem-status" style="color: var(--gray-color);">Digite o CEP para preencher logradouro, bairro e cidade</small>
                            </div>
                            <div class="form-group">
                                <label for="cidade_origem">Cidade de Origem</label>
                                <input type="text" id="cidade_origem" name="cidade_origem" value="{cidade_origem}" readonly style="background: #f5f5f5;">
                            </div>
                        </div>
                        <div class="form-row">
                            <div class="form-group" style="flex:2;">
                                <label for="logradouro_origem" id="lbl-origem">Logradouro <span id="origem-obrigatorio">*</span></label>
                                <input type="text" id="logradouro_origem" name="logradouro_origem" value="{logradouro_origem}"
                                       placeholder="Rua / Avenida" required
                                       style="text-transform:uppercase;"
                                       oninput="this.value=this.value.toLocaleUpperCase('pt-BR'); montarOrigemCompleta()">
                            </div>
                            <div class="form-group" style="flex:0.7;min-width:7rem;">
                                <label for="numero_origem">Número <span id="numero-origem-obrigatorio">*</span></label>
                                <input type="text" id="numero_origem" name="numero_origem" value="{numero_origem}"
                                       placeholder="Nº" required
                                       style="text-transform:uppercase;"
                                       oninput="this.value=this.value.toLocaleUpperCase('pt-BR'); montarOrigemCompleta()">
                            </div>
                            <div class="form-group" style="flex:1.2;">
                                <label for="bairro_origem">Bairro</label>
                                <input type="text" id="bairro_origem" name="bairro_origem" value="{bairro_origem}"
                                       placeholder="Bairro"
                                       style="text-transform:uppercase;"
                                       oninput="this.value=this.value.toLocaleUpperCase('pt-BR'); montarOrigemCompleta()">
                            </div>
                        </div>
                        <input type="hidden" id="origem" name="origem" value="{origem}">
                        <small id="origem-ajuda" style="color:var(--gray-color);display:none;">
                            Com Destino Predefinido a origem é opcional — se ficar vazia, usa o endereço do paciente.
                        </small>
                    </div>

                    <div style="background: white; padding: 1rem; border-radius: 0.5rem; border-left: 4px solid #007bff;">
                        <h5 style="color: #007bff; margin-bottom: 1rem;">🏥 Local de Destino</h5>
                        <div class="form-group">
                            <label>Como informar o destino:</label>
                            <div style="display: flex; gap: 1rem; margin-top: 0.5rem; flex-wrap: wrap;">
                                <label style="display: flex; align-items: center; gap: 0.5rem;">
                                    <input type="radio" name="tipo_destino" value="cep" {chk_cep} onchange="alterarTipoDestino()">
                                    📍 Buscar por CEP
                                </label>
                                <label style="display: flex; align-items: center; gap: 0.5rem;">
                                    <input type="radio" name="tipo_destino" value="cidade" {chk_cidade} onchange="alterarTipoDestino()">
                                    🏙️ Cidade de SP
                                </label>
                                <label style="display: flex; align-items: center; gap: 0.5rem;">
                                    <input type="radio" name="tipo_destino" value="cnes" {chk_cnes} onchange="alterarTipoDestino()">
                                    🏥 Destino Predefinido
                                </label>
                                <label style="display: flex; align-items: center; gap: 0.5rem;">
                                    <input type="radio" name="tipo_destino" value="manual" {chk_manual} onchange="alterarTipoDestino()">
                                    ✏️ Manual
                                </label>
                            </div>
                        </div>

                        <div id="destino-cep" style="display:{disp_cep};">
                            <div class="form-row">
                                <div class="form-group">
                                    <label for="cep_destino">CEP de Destino</label>
                                    <input type="text" id="cep_destino" name="cep_destino" value="{cep_destino}" placeholder="00000-000" maxlength="9" onblur="buscarCEPDestinoAgendamento()">
                                    <small id="cep-destino-status" style="color: var(--gray-color);">CEP do hospital/clínica</small>
                                </div>
                                <div class="form-group">
                                    <label for="cidade_destino_cep">Cidade de Destino</label>
                                    <input type="text" id="cidade_destino_cep" name="cidade_destino" value="{cidade_destino}" readonly style="background: #f5f5f5;">
                                </div>
                            </div>
                            <div class="form-group">
                                <label for="destino">Endereço/Local de Destino *</label>
                                <input type="text" id="destino" name="destino" value="{destino}" placeholder="Hospital/Clínica" {req_destino}
                                       style="text-transform:uppercase;"
                                       oninput="this.value=this.value.toLocaleUpperCase('pt-BR')">
                            </div>
                        </div>

                        <div id="destino-cidade" style="display:{disp_cidade};">
                            <div class="form-group">
                                <label for="cidade_sp_select">Cidade de São Paulo:</label>
                                <select id="cidade_sp_select" name="cidade_sp_select" onchange="selecionarCidadeSP()">
                                    {opcoes_cidades_sp}
                                </select>
                            </div>
                            <div class="form-group">
                                <label for="destino_cidade_sp">Endereço na Cidade *</label>
                                <input type="text" id="destino_cidade_sp" name="destino_cidade_sp" value="{destino_cidade_sp}" placeholder="Ex: HC, AME (texto livre)">
                                <small style="color:var(--gray-color);">Texto livre — digite só a referência (ex.: HC). Não precisa de rua/número nem da lista CNES.</small>
                            </div>
                        </div>

                        <div id="destino-cnes" style="display:{disp_cnes};">
                            <div class="form-row">
                                <div class="form-group" style="flex:1;">
                                    <label for="cidade_cnes" style="display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap;">
                                        <span>Cidade *</span>
                                        <span id="badge-cidades-cnes" class="badge" style="background:#e7f1ff;color:#0d6efd;font-weight:600;font-size:0.75rem;padding:0.2rem 0.5rem;border-radius:999px;">{qtd_cidades} cidades</span>
                                    </label>
                                    <select id="cidade_cnes" name="cidade_cnes" onchange="onCidadeCnesChange()">
                                        {opcoes_cidades_cnes}
                                    </select>
                                    <small style="color:var(--gray-color);">Selecione o município do atendimento</small>
                                </div>
                            </div>
                            <div class="form-group">
                                <label for="destino_cnes_codigo">Destino Predefinido (CNES)</label>
                                <div style="display:flex;gap:0.5rem;flex-wrap:wrap;align-items:center;margin-bottom:0.5rem;">
                                    <input type="search" id="filtro_cnes" placeholder="Filtrar por nome, bairro ou endereço..."
                                           style="flex:1;min-width:200px;" oninput="filtrarEstabelecimentosCnes()">
                                    <button type="button" class="btn btn-secondary btn-sm" onclick="sincronizarCnesCidade(true)" title="Atualizar base CNES">
                                        🔄 Atualizar CNES
                                    </button>
                                </div>
                                <select id="destino_cnes_codigo" name="destino_cnes_codigo" onchange="onEstabelecimentoCnesChange()">
                                    <option value="">Selecione a cidade primeiro...</option>
                                </select>
                                <input type="hidden" id="destino_cnes_nome" name="destino_cnes_nome" value="{destino_cnes_nome_val}">
                                <small id="cnes-status" style="color:var(--gray-color);display:block;margin-top:0.35rem;">
                                    Fonte: CNES (Dados Abertos — Ministério da Saúde)
                                </small>
                                <div id="cnes-detalhe" style="display:none;margin-top:0.75rem;padding:0.75rem;background:var(--color-95);border-radius:0.4rem;font-size:0.9rem;color:#333;"></div>
                            </div>
                            <div class="form-group" style="margin-top:1rem;padding-top:1rem;border-top:1px dashed #ced4da;">
                                <label for="destino_cnes_livre" style="display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap;">
                                    <span>Ou informe o local em texto livre</span>
                                    <span class="badge" style="background:#d1e7dd;color:#0f5132;font-weight:600;font-size:0.72rem;padding:0.15rem 0.45rem;border-radius:999px;">válido sozinho</span>
                                </label>
                                <input type="text" id="destino_cnes_livre" name="destino_cnes_livre"
                                       value="{destino_cnes_livre_val}"
                                       placeholder="Ex: HC, AME — sem precisar escolher na lista CNES"
                                       oninput="onDestinoCnesLivreInput()">
                                <small style="color:var(--gray-color);">
                                    Com a cidade selecionada, basta digitar a referência (ex.: HC). Não é obrigatório escolher estabelecimento na lista CNES.
                                </small>
                            </div>
                        </div>

                        <div id="destino-manual" style="display:{disp_manual};">
                            <div class="form-group">
                                <label for="destino_manual">Endereço Completo *</label>
                                <textarea id="destino_manual" name="destino_manual" rows="3" placeholder="Digite o endereço completo">{destino_manual}</textarea>
                            </div>
                        </div>
                    </div>
                </div>

                <div style="margin-top: 2rem;">
                    <button type="submit" class="btn btn-success">{submit}</button>
                    <a href="{cancel}" class="btn btn-secondary" style="margin-left: 1rem;">❌ Cancelar</a>
                </div>
            </form>
        </div>

        <script>
        console.log('🔧 Destino: 4 opções independentes (CEP / Cidade SP / CNES / Manual)...');

        let _cnesLista = [];
        let _cnesFiltroTimer = null;

        function tipoDestinoAtual() {{
            const el = document.querySelector('input[name="tipo_destino"]:checked');
            return el ? el.value : 'cep';
        }}

        async function carregarCidadesSP() {{
            // Enriquece o select local com IBGE (opcional). Se falhar, as cidades locais já bastam.
            const select = document.getElementById('cidade_sp_select');
            if (!select) return;
            const inicial = (document.getElementById('form-cadastro-agendamento').dataset.cidadeSpInicial || '').trim();
            const jaTem = new Set(Array.from(select.options).map(o => o.value).filter(Boolean));
            try {{
                const response = await fetch('https://servicodados.ibge.gov.br/api/v1/localidades/estados/35/municipios');
                const cidades = await response.json();
                cidades.sort((a, b) => a.nome.localeCompare(b.nome));
                cidades.forEach(cidade => {{
                    if (jaTem.has(cidade.nome)) return;
                    const option = document.createElement('option');
                    option.value = cidade.nome;
                    option.textContent = cidade.nome;
                    select.appendChild(option);
                    jaTem.add(cidade.nome);
                }});
                if (inicial) {{
                    select.value = inicial;
                }}
            }} catch (error) {{
                console.warn('IBGE indisponível — usando cidades locais:', error);
            }}
        }}

        function setPainelDestinoAtivo(painelId, ativo) {{
            const painel = document.getElementById(painelId);
            if (!painel) return;
            painel.style.display = ativo ? 'block' : 'none';
            painel.querySelectorAll('input, select, textarea').forEach(el => {{
                el.disabled = !ativo;
                el.removeAttribute('required');
            }});
        }}

        function limparRequiredDestinos() {{
            ['destino', 'destino_cidade_sp', 'cidade_sp_select', 'cidade_cnes',
             'destino_cnes_codigo', 'destino_cnes_livre', 'destino_manual'].forEach(id => {{
                const el = document.getElementById(id);
                if (el) el.removeAttribute('required');
            }});
        }}

        function montarOrigemCompleta() {{
            const log = (document.getElementById('logradouro_origem')?.value || '').trim();
            const num = (document.getElementById('numero_origem')?.value || '').trim();
            const bai = (document.getElementById('bairro_origem')?.value || '').trim();
            const partes = [];
            if (log) partes.push(log);
            if (num) partes.push('Nº ' + num);
            if (bai) partes.push(bai);
            const el = document.getElementById('origem');
            if (el) el.value = partes.join(', ');
        }}

        function atualizarObrigatoriedadeOrigem() {{
            const logEl = document.getElementById('logradouro_origem');
            const numEl = document.getElementById('numero_origem');
            const marca = document.getElementById('origem-obrigatorio');
            const marcaNum = document.getElementById('numero-origem-obrigatorio');
            const ajuda = document.getElementById('origem-ajuda');
            if (!logEl || !numEl) return;
            const cnes = tipoDestinoAtual() === 'cnes';
            if (cnes) {{
                logEl.removeAttribute('required');
                numEl.removeAttribute('required');
                if (marca) marca.style.display = 'none';
                if (marcaNum) marcaNum.style.display = 'none';
                if (ajuda) ajuda.style.display = 'block';
            }} else {{
                logEl.setAttribute('required', 'required');
                numEl.setAttribute('required', 'required');
                if (marca) marca.style.display = 'inline';
                if (marcaNum) marcaNum.style.display = 'inline';
                if (ajuda) ajuda.style.display = 'none';
            }}
            montarOrigemCompleta();
        }}

        function alterarTipoDestino() {{
            const tipo = tipoDestinoAtual();
            setPainelDestinoAtivo('destino-cep', tipo === 'cep');
            setPainelDestinoAtivo('destino-cidade', tipo === 'cidade');
            setPainelDestinoAtivo('destino-cnes', tipo === 'cnes');
            setPainelDestinoAtivo('destino-manual', tipo === 'manual');
            limparRequiredDestinos();
            atualizarObrigatoriedadeOrigem();

            // Cada opção só exige OS PRÓPRIOS campos — nunca os das outras.
            if (tipo === 'cep') {{
                const destCep = document.getElementById('destino');
                if (destCep) destCep.setAttribute('required', 'required');
            }} else if (tipo === 'cidade') {{
                const sel = document.getElementById('cidade_sp_select');
                const txt = document.getElementById('destino_cidade_sp');
                if (sel) sel.setAttribute('required', 'required');
                if (txt) txt.setAttribute('required', 'required');
            }} else if (tipo === 'cnes') {{
                const selCid = document.getElementById('cidade_cnes');
                if (selCid) selCid.setAttribute('required', 'required');
                // Lista CNES e texto livre são alternativas — nenhum fica required no HTML5.
                // Validação de "um dos dois" ocorre no submit.
            }} else if (tipo === 'manual') {{
                const destManual = document.getElementById('destino_manual');
                if (destManual) destManual.setAttribute('required', 'required');
            }}
        }}

        function validarDestinoAtivoNoSubmit() {{
            const tipo = tipoDestinoAtual();
            limparRequiredDestinos();
            alterarTipoDestino();

            if (tipo === 'cidade') {{
                const cidade = (document.getElementById('cidade_sp_select').value || '').trim();
                const local = (document.getElementById('destino_cidade_sp').value || '').trim();
                if (!cidade) {{
                    alert('Cidade de SP: selecione a cidade.');
                    document.getElementById('cidade_sp_select').focus();
                    return false;
                }}
                if (!local) {{
                    alert('Cidade de SP: informe o local (ex.: HC, AME).');
                    document.getElementById('destino_cidade_sp').focus();
                    return false;
                }}
                return true;
            }}

            if (tipo === 'cnes') {{
                const cidade = (document.getElementById('cidade_cnes').value || '').trim();
                const codigo = (document.getElementById('destino_cnes_codigo').value || '').trim();
                const livre = (document.getElementById('destino_cnes_livre').value || '').trim();
                if (!cidade) {{
                    alert('Destino Predefinido: selecione a cidade.');
                    document.getElementById('cidade_cnes').focus();
                    return false;
                }}
                if (!codigo && !livre) {{
                    alert('Destino Predefinido: escolha um estabelecimento na lista OU digite o local (ex.: HC).');
                    document.getElementById('destino_cnes_livre').focus();
                    return false;
                }}
                // Garante que o select vazio não bloqueie quando há texto livre
                document.getElementById('destino_cnes_codigo').removeAttribute('required');
                document.getElementById('destino_cnes_livre').removeAttribute('required');
                return true;
            }}

            if (tipo === 'cep') {{
                const dest = (document.getElementById('destino').value || '').trim();
                if (!dest) {{
                    alert('Buscar por CEP: informe o endereço/local de destino.');
                    document.getElementById('destino').focus();
                    return false;
                }}
                return true;
            }}

            if (tipo === 'manual') {{
                const dest = (document.getElementById('destino_manual').value || '').trim();
                if (!dest) {{
                    alert('Manual: informe o endereço completo de destino.');
                    document.getElementById('destino_manual').focus();
                    return false;
                }}
                return true;
            }}
            return true;
        }}

        function selecionarCidadeSP() {{
            const select = document.getElementById('cidade_sp_select');
            const dest = document.getElementById('destino_cidade_sp');
            if (select && dest && select.value) {{
                dest.placeholder = `Ex: HC, AME em ${{select.value}}`;
            }}
        }}

        async function onCidadeCnesChange() {{
            const cidade = document.getElementById('cidade_cnes').value;
            document.getElementById('filtro_cnes').value = '';
            document.getElementById('destino_cnes_nome').value = '';
            document.getElementById('cnes-detalhe').style.display = 'none';
            const select = document.getElementById('destino_cnes_codigo');
            const livre = document.getElementById('destino_cnes_livre');
            if (livre) {{
                livre.placeholder = cidade
                    ? `Ex: HC, AME em ${{cidade}}`
                    : 'Ex: HC, AME — sem precisar escolher na lista CNES';
            }}
            if (!cidade) {{
                select.innerHTML = '<option value="">Selecione a cidade primeiro...</option>';
                document.getElementById('cnes-status').textContent = 'Fonte: CNES (Dados Abertos — Ministério da Saúde)';
                return;
            }}
            await carregarEstabelecimentosCnes(cidade, false);
        }}

        async function sincronizarCnesCidade(forcar) {{
            const cidade = document.getElementById('cidade_cnes').value;
            if (!cidade) {{
                alert('Selecione a cidade antes de atualizar o CNES.');
                return;
            }}
            await carregarEstabelecimentosCnes(cidade, !!forcar);
        }}

        async function carregarEstabelecimentosCnes(cidade, forcar) {{
            const select = document.getElementById('destino_cnes_codigo');
            const status = document.getElementById('cnes-status');
            const form = document.getElementById('form-cadastro-agendamento');
            const inicial = (form.dataset.cnesCodigoInicial || '').trim();
            const q = (document.getElementById('filtro_cnes').value || '').trim();
            const livreAtual = (document.getElementById('destino_cnes_livre').value || '').trim();
            select.innerHTML = '<option value="">Carregando estabelecimentos do CNES...</option>';
            status.textContent = forcar
                ? '🔄 Sincronizando com a API pública do CNES (pode levar alguns minutos)...'
                : '🔍 Carregando estabelecimentos...';
            status.style.color = '#0d6efd';
            try {{
                const params = new URLSearchParams({{
                    cidade: cidade,
                    q: q,
                    sync: forcar ? '1' : '1',
                    forcar: forcar ? '1' : '0',
                    limit: '120',
                }});
                const r = await fetch(`/transporte/api/cnes/estabelecimentos?${{params.toString()}}`);
                const data = await r.json();
                if (!data.ok) {{
                    select.innerHTML = '<option value="">Nenhum estabelecimento disponível</option>';
                    status.textContent = '❌ ' + (data.mensagem || 'Falha ao carregar CNES');
                    status.style.color = '#dc3545';
                    _cnesLista = [];
                    return;
                }}
                _cnesLista = data.estabelecimentos || [];
                // Se já há texto livre, não restaura seleção CNES automática
                preencherSelectCnes(livreAtual ? '' : inicial);
                const fonte = data.fonte || 'cache';
                const total = data.total_cache != null ? data.total_cache : _cnesLista.length;
                if (!_cnesLista.length) {{
                    status.textContent = '⚠️ Nenhum estabelecimento encontrado para esta cidade' + (q ? ' com o filtro informado' : '') +
                        '. Você pode digitar o local em texto livre (ex.: HC).';
                    status.style.color = '#856404';
                }} else {{
                    status.textContent = `✅ ${{_cnesLista.length}} exibidos` +
                        (total > _cnesLista.length ? ` (de ${{total}} no cache)` : '') +
                        ` · fonte: ${{fonte}} · CNES / Dados Abertos MS`;
                    status.style.color = '#28a745';
                }}
                if (inicial) form.dataset.cnesCodigoInicial = '';
            }} catch (err) {{
                console.error(err);
                select.innerHTML = '<option value="">Erro ao carregar</option>';
                status.textContent = '❌ Erro de rede ao consultar CNES. Use o texto livre (ex.: HC).';
                status.style.color = '#dc3545';
            }}
        }}

        function preencherSelectCnes(codigoSelecionado) {{
            const select = document.getElementById('destino_cnes_codigo');
            select.innerHTML = '<option value="">Selecione o estabelecimento...</option>';
            _cnesLista.forEach(est => {{
                const opt = document.createElement('option');
                opt.value = est.codigo_cnes;
                const end = [est.endereco, est.numero ? 'Nº' + est.numero : '', est.bairro].filter(Boolean).join(', ');
                opt.textContent = end ? `${{est.nome}} — ${{end}}` : est.nome;
                opt.dataset.nome = est.nome || '';
                opt.dataset.endereco = end;
                opt.dataset.cep = est.cep || '';
                opt.dataset.telefone = est.telefone || '';
                opt.dataset.label = est.destino_formatado || est.nome;
                if (codigoSelecionado && String(est.codigo_cnes) === String(codigoSelecionado)) {{
                    opt.selected = true;
                }}
                select.appendChild(opt);
            }});
            if (select.value) onEstabelecimentoCnesChange();
        }}

        function filtrarEstabelecimentosCnes() {{
            clearTimeout(_cnesFiltroTimer);
            _cnesFiltroTimer = setTimeout(() => {{
                const cidade = document.getElementById('cidade_cnes').value;
                if (cidade) carregarEstabelecimentosCnes(cidade, false);
            }}, 350);
        }}

        function onEstabelecimentoCnesChange() {{
            const select = document.getElementById('destino_cnes_codigo');
            const opt = select.options[select.selectedIndex];
            const detalhe = document.getElementById('cnes-detalhe');
            const livre = document.getElementById('destino_cnes_livre');
            if (!select.value || !opt) {{
                document.getElementById('destino_cnes_nome').value = '';
                detalhe.style.display = 'none';
                return;
            }}
            document.getElementById('destino_cnes_nome').value = opt.dataset.nome || opt.textContent || '';
            // Escolheu na lista: limpa texto livre (caminhos mutuamente exclusivos nesta opção)
            if (livre) livre.value = '';
            const partes = [];
            if (opt.dataset.nome) partes.push(`<strong>${{opt.dataset.nome}}</strong>`);
            partes.push(`CNES: ${{select.value}}`);
            if (opt.dataset.endereco) partes.push(opt.dataset.endereco);
            if (opt.dataset.cep) partes.push(`CEP ${{opt.dataset.cep}}`);
            if (opt.dataset.telefone) partes.push(`Tel. ${{opt.dataset.telefone}}`);
            detalhe.innerHTML = partes.join(' · ');
            detalhe.style.display = 'block';
        }}

        function onDestinoCnesLivreInput() {{
            const livre = document.getElementById('destino_cnes_livre');
            const select = document.getElementById('destino_cnes_codigo');
            const detalhe = document.getElementById('cnes-detalhe');
            if ((livre.value || '').trim()) {{
                // Texto livre tem prioridade: limpa seleção CNES
                if (select) {{
                    select.value = '';
                    select.removeAttribute('required');
                }}
                document.getElementById('destino_cnes_nome').value = '';
                if (detalhe) detalhe.style.display = 'none';
            }}
        }}

        async function buscarCEPOrigemAgendamento(opts) {{
            opts = opts || {{}};
            const preservarNumero = !!opts.preservarNumero;
            const cep = document.getElementById('cep_origem').value.replace(/\\D/g, '');
            const status = document.getElementById('cep-origem-status');
            if (cep.length === 8) {{
                status.textContent = '🔍 Buscando...';
                try {{
                    const response = await fetch(`https://viacep.com.br/ws/${{cep}}/json/`);
                    const data = await response.json();
                    if (!data.erro) {{
                        document.getElementById('cidade_origem').value = `${{data.localidade}} - ${{data.uf}}`;
                        const logEl = document.getElementById('logradouro_origem');
                        const baiEl = document.getElementById('bairro_origem');
                        const numEl = document.getElementById('numero_origem');
                        // Só completa logradouro/bairro se ainda estiverem vazios (não sobrescreve ficha do paciente)
                        if (logEl && !(logEl.value || '').trim() && (data.logradouro || '').trim()) {{
                            logEl.value = data.logradouro.toLocaleUpperCase('pt-BR');
                        }}
                        if (baiEl && !(baiEl.value || '').trim() && (data.bairro || '').trim()) {{
                            baiEl.value = data.bairro.toLocaleUpperCase('pt-BR');
                        }}
                        montarOrigemCompleta();
                        status.textContent = '✅ CEP encontrado!';
                        status.style.color = '#28a745';
                        if (numEl && !preservarNumero && !(numEl.value || '').trim()) {{
                            numEl.focus();
                        }}
                    }} else {{
                        status.textContent = '❌ CEP não encontrado';
                        status.style.color = '#dc3545';
                    }}
                }} catch (error) {{
                    status.textContent = '❌ Erro ao buscar CEP';
                    status.style.color = '#dc3545';
                }}
            }}
        }}

        async function buscarCEPDestinoAgendamento() {{
            const cep = document.getElementById('cep_destino').value.replace(/\\D/g, '');
            const status = document.getElementById('cep-destino-status');
            if (cep.length === 8) {{
                status.textContent = '🔍 Buscando...';
                try {{
                    const response = await fetch(`https://viacep.com.br/ws/${{cep}}/json/`);
                    const data = await response.json();
                    if (!data.erro) {{
                        document.getElementById('cidade_destino_cep').value = `${{data.localidade}} - ${{data.uf}}`;
                        status.textContent = '✅ CEP encontrado!';
                        status.style.color = '#28a745';
                    }} else {{
                        status.textContent = '❌ CEP não encontrado';
                        status.style.color = '#dc3545';
                    }}
                }} catch (error) {{
                    status.textContent = '❌ Erro ao buscar CEP';
                    status.style.color = '#dc3545';
                }}
            }}
        }}

        document.getElementById('cep_origem').addEventListener('input', function(e) {{
            let value = e.target.value.replace(/\\D/g, '');
            if (value.length > 5) value = value.replace(/^(\\d{{5}})(\\d+)/, '$1-$2');
            e.target.value = value;
        }});
        document.getElementById('cep_destino').addEventListener('input', function(e) {{
            let value = e.target.value.replace(/\\D/g, '');
            if (value.length > 5) value = value.replace(/^(\\d{{5}})(\\d+)/, '$1-$2');
            e.target.value = value;
        }});

        document.addEventListener('DOMContentLoaded', function() {{
            carregarCidadesSP();
            const form = document.getElementById('form-cadastro-agendamento');
            if (form) {{
                form.addEventListener('submit', function(e) {{
                    montarOrigemCompleta();
                    if (!validarDestinoAtivoNoSubmit()) {{
                        e.preventDefault();
                        e.stopPropagation();
                        return false;
                    }}
                }});
            }}
            const selPac = document.getElementById('paciente_id');
            if (selPac) {{
                selPac.addEventListener('change', onPacienteAgendamentoChange);
                if (selPac.value) onPacienteAgendamentoChange();
                else setCamposOrigemSomenteLeitura(false);
            }}
            // Estado inicial do checkbox de origem diferente
            const chkOrigDif = document.getElementById('origem_diferente_cadastro');
            if (chkOrigDif) {{
                const avisoFicha = document.getElementById('origem-ficha-aviso');
                const avisoDif = document.getElementById('origem-diferente-aviso');
                if (avisoFicha) avisoFicha.style.display = chkOrigDif.checked ? 'none' : 'block';
                if (avisoDif) avisoDif.style.display = chkOrigDif.checked ? 'block' : 'none';
            }}
            alterarTipoDestino();
            const cidadeIni = document.getElementById('cidade_cnes').value;
            if (cidadeIni && tipoDestinoAtual() === 'cnes') {{
                carregarEstabelecimentosCnes(cidadeIni, false);
            }}
        }});

        function origemUsaEnderecoDiferente() {{
            const chk = document.getElementById('origem_diferente_cadastro');
            return !!(chk && chk.checked);
        }}

        function setCamposOrigemSomenteLeitura(somenteLeitura) {{
            ['cep_origem', 'logradouro_origem', 'numero_origem', 'bairro_origem'].forEach(id => {{
                const el = document.getElementById(id);
                if (!el) return;
                el.readOnly = !!somenteLeitura;
                el.style.background = somenteLeitura ? '#f5f5f5' : '';
            }});
        }}

        function limparCamposOrigem() {{
            const cepEl = document.getElementById('cep_origem');
            const logEl = document.getElementById('logradouro_origem');
            const numEl = document.getElementById('numero_origem');
            const baiEl = document.getElementById('bairro_origem');
            const cidEl = document.getElementById('cidade_origem');
            const st = document.getElementById('cep-origem-status');
            if (cepEl) cepEl.value = '';
            if (logEl) logEl.value = '';
            if (numEl) numEl.value = '';
            if (baiEl) baiEl.value = '';
            if (cidEl) cidEl.value = '';
            if (st) {{
                st.textContent = 'Digite o CEP para preencher logradouro, bairro e cidade';
                st.style.color = '';
            }}
            montarOrigemCompleta();
        }}

        function alternarOrigemDiferenteCadastro() {{
            const diferente = origemUsaEnderecoDiferente();
            const avisoFicha = document.getElementById('origem-ficha-aviso');
            const avisoDif = document.getElementById('origem-diferente-aviso');
            if (avisoFicha) avisoFicha.style.display = diferente ? 'none' : 'block';
            if (avisoDif) avisoDif.style.display = diferente ? 'block' : 'none';

            const sel = document.getElementById('paciente_id');
            if (diferente) {{
                setCamposOrigemSomenteLeitura(false);
                limparCamposOrigem();
                const cepEl = document.getElementById('cep_origem');
                if (cepEl) cepEl.focus();
            }} else if (sel && sel.value) {{
                setCamposOrigemSomenteLeitura(true);
                preencherOrigemDoPacienteSelecionado();
            }} else {{
                setCamposOrigemSomenteLeitura(false);
            }}
        }}

        function aplicarOrigemNosCampos(dados) {{
            if (!dados) return;
            // Se o atendente marcou "endereço diferente", não sobrescreve
            if (origemUsaEnderecoDiferente()) return;
            const cepEl = document.getElementById('cep_origem');
            const logEl = document.getElementById('logradouro_origem');
            const numEl = document.getElementById('numero_origem');
            const baiEl = document.getElementById('bairro_origem');
            const cepP = (dados.cep || '').trim();
            const logP = (dados.logradouro || '').trim();
            const numP = (dados.numero || '').trim();
            const baiP = (dados.bairro || '').trim();
            if (cepEl) cepEl.value = cepP;
            if (logEl) logEl.value = logP ? logP.toLocaleUpperCase('pt-BR') : '';
            if (numEl) numEl.value = numP ? numP.toLocaleUpperCase('pt-BR') : '';
            if (baiEl) baiEl.value = baiP ? baiP.toLocaleUpperCase('pt-BR') : '';
            montarOrigemCompleta();
            setCamposOrigemSomenteLeitura(true);
            if (cepP && cepP.replace(/\\D/g, '').length === 8) {{
                buscarCEPOrigemAgendamento({{ preservarNumero: true }});
            }}
        }}

        async function preencherOrigemDoPacienteSelecionado() {{
            if (origemUsaEnderecoDiferente()) return;
            const sel = document.getElementById('paciente_id');
            if (!sel || !sel.value) return;
            const opt = sel.options[sel.selectedIndex];
            try {{
                const r = await fetch(`/transporte/api/pacientes/${{sel.value}}/resumo`);
                const data = await r.json();
                if (data && data.ok) {{
                    aplicarOrigemNosCampos(data);
                    return;
                }}
            }} catch (err) {{
                console.warn('Falha ao buscar resumo do paciente:', err);
            }}
            if (opt) {{
                aplicarOrigemNosCampos({{
                    cep: opt.dataset.cep || '',
                    logradouro: opt.dataset.logradouro || '',
                    numero: opt.dataset.numero || '',
                    bairro: opt.dataset.bairro || '',
                }});
            }}
        }}

        function onPacienteAgendamentoChange() {{
            const sel = document.getElementById('paciente_id');
            const opt = sel.options[sel.selectedIndex];
            const necessita = opt && opt.dataset.necessitaAc === '1';
            const chk = document.getElementById('possui_acompanhante');
            const lbl = document.getElementById('lbl-possui-ac');
            const alerta = document.getElementById('ac-alerta-cadastro');
            const link = document.getElementById('ac-link-ficha');

            if (necessita) {{
                chk.checked = true;
                chk.disabled = true;
                let hidden = document.getElementById('possui_acompanhante_hidden');
                if (!hidden) {{
                    hidden = document.createElement('input');
                    hidden.type = 'hidden';
                    hidden.name = 'possui_acompanhante';
                    hidden.id = 'possui_acompanhante_hidden';
                    hidden.value = '1';
                    chk.parentNode.appendChild(hidden);
                }} else {{
                    hidden.value = '1';
                }}
                lbl.textContent = 'Acompanhante obrigatório (condição do paciente)';
            }} else {{
                chk.disabled = false;
                const hidden = document.getElementById('possui_acompanhante_hidden');
                if (hidden) hidden.remove();
                if (!chk.checked) {{
                    lbl.textContent = 'Paciente levará acompanhante nesta viagem';
                }}
            }}

            if (sel.value) {{
                link.href = `/transporte/acompanhantes/novo?paciente_id=${{sel.value}}`;
                preencherOrigemDoPacienteSelecionado();
            }}
            alerta.style.display = 'none';
            alternarAcompanhanteViagem();
            carregarAcompanhantesPaciente();
        }}

        function alternarAcompanhanteViagem() {{
            const on = document.getElementById('possui_acompanhante').checked
                || document.getElementById('possui_acompanhante').disabled;
            document.getElementById('bloco-ac-viagem').style.display = on ? 'block' : 'none';
            const selAc = document.getElementById('acompanhante_id');
            if (on) selAc.setAttribute('required', 'required');
            else {{
                selAc.removeAttribute('required');
                selAc.value = '';
            }}
        }}

        async function carregarAcompanhantesPaciente() {{
            const pacienteId = document.getElementById('paciente_id').value;
            const select = document.getElementById('acompanhante_id');
            const status = document.getElementById('ac-status');
            const alerta = document.getElementById('ac-alerta-cadastro');
            const selPac = document.getElementById('paciente_id');
            const opt = selPac.options[selPac.selectedIndex];
            const necessita = opt && opt.dataset.necessitaAc === '1';
            const inicial = (document.getElementById('form-cadastro-agendamento').dataset.acompanhanteInicial || '').trim();

            select.innerHTML = '<option value="">Carregando...</option>';
            alerta.style.display = 'none';
            if (!pacienteId) {{
                select.innerHTML = '<option value="">Selecione o paciente primeiro...</option>';
                status.textContent = 'Os acompanhantes vêm da ficha do paciente.';
                return;
            }}
            try {{
                const r = await fetch(`/transporte/api/pacientes/${{pacienteId}}/acompanhantes`);
                const data = await r.json();
                const lista = data.acompanhantes || [];
                if (!lista.length) {{
                    select.innerHTML = '<option value="">Nenhum acompanhante cadastrado</option>';
                    status.textContent = 'Cadastre na ficha do paciente antes de agendar.';
                    status.style.color = '#b36b00';
                    if (necessita || data.necessita_acompanhante) alerta.style.display = 'block';
                    return;
                }}
                select.innerHTML = '<option value="">Selecione o acompanhante...</option>';
                lista.forEach(ac => {{
                    const optAc = document.createElement('option');
                    optAc.value = ac.id;
                    const extra = [ac.parentesco, ac.rg].filter(Boolean).join(' · ');
                    optAc.textContent = extra ? `${{ac.nome}} (${{extra}})` : ac.nome;
                    if (inicial && String(ac.id) === String(inicial)) optAc.selected = true;
                    select.appendChild(optAc);
                }});
                status.textContent = `${{lista.length}} acompanhante(s) disponível(is) na ficha.`;
                status.style.color = '#666';
            }} catch (e) {{
                select.innerHTML = '<option value="">Erro ao carregar</option>';
                status.textContent = 'Falha ao buscar acompanhantes.';
                status.style.color = '#dc3545';
            }}
        }}
        </script>
        {html_assets_especialidade_select()}
        """


def agendamento_elegivel_cartao_motorista(agendamento):
    """
    Cartão do Motorista / Folha Espelho: só com programação completa (veículo + motorista).
    Retorna (ok: bool, motivo: str).
    """
    if not agendamento:
        return False, 'Nenhum agendamento encontrado para esta viagem.'
    if (agendamento.status or '').lower() == 'cancelado':
        return False, 'Agendamento cancelado. Impressão indisponível.'
    if not agendamento.paciente_id:
        return False, 'Agendamento sem paciente associado.'
    if not agendamento.data or not agendamento.hora:
        return False, 'Agendamento sem data/hora de saída.'
    if not (agendamento.destino or '').strip():
        return False, 'Agendamento sem destino definido.'
    if not (agendamento.origem or '').strip():
        return False, 'Agendamento sem origem/rota definida.'
    if not agendamento.motorista_id or not agendamento_tem_recurso_programado(agendamento):
        return False, 'Disponível somente após a programação do motorista e do veículo ou da frota.'
    return True, 'OK'


def agendamento_elegivel_folha_espelho(agendamento):
    """Mesma regra de liberação da Folha Espelho (programação completa)."""
    return agendamento_elegivel_cartao_motorista(agendamento)


# Partículas ignoradas na abreviação do nome do motorista (só impressão).
_PARTICULAS_NOME_MOTORISTA = frozenset({'DE', 'DA', 'DAS', 'DO', 'DOS', 'E'})
# Larguras úteis (px) para caber em 1 linha — Arial bold na impressão.
LARGURA_MOTORISTA_FOLHA_PX = 138
LARGURA_MOTORISTA_CARTAO_PX = 200


def _partes_significativas_nome_motorista(nome):
    """Retorna tokens significativos (sem de/da/do/dos/das/e), preservando ordem."""
    partes = [p for p in str(nome or '').strip().split() if p]
    return [p for p in partes if p.upper() not in _PARTICULAS_NOME_MOTORISTA]


def candidatos_abreviacao_nome_motorista(nome):
    """
    Lista progressiva de formas do nome (menos → mais abreviado).
    Nível 0: completo; 1: meios em inicial + último completo;
    2: só iniciais após o primeiro; 3: primeiro + inicial do último.
    """
    nome_limpo = ' '.join(str(nome or '').strip().split())
    if not nome_limpo:
        return ['']

    sig = _partes_significativas_nome_motorista(nome_limpo)
    candidatos = [nome_limpo]
    if len(sig) <= 1:
        return candidatos

    primeiro = sig[0]
    ultimo = sig[-1]
    meios = sig[1:-1]

    # Nível 1 — MARCIO S. CAMARGO / RENATO F. T. MENEZES
    if meios:
        iniciais_meio = ' '.join(f'{m[0].upper()}.' for m in meios if m)
        nivel1 = f'{primeiro} {iniciais_meio} {ultimo}'.strip()
        if nivel1 not in candidatos:
            candidatos.append(nivel1)
    # Sem meios: nada a enxugar no nível 1 além do completo

    # Nível 2 — MARCIO S. C. / RENATO F. T. M.
    resto = meios + [ultimo]
    iniciais = ' '.join(f'{r[0].upper()}.' for r in resto if r)
    nivel2 = f'{primeiro} {iniciais}'.strip()
    if nivel2 not in candidatos:
        candidatos.append(nivel2)

    # Nível 3 — primeiro + inicial do último (último recurso)
    nivel3 = f'{primeiro} {ultimo[0].upper()}.'
    if nivel3 not in candidatos:
        candidatos.append(nivel3)

    return candidatos


def medir_largura_texto_impressao_px(texto, font_size_px=10, bold=True):
    """
    Largura aproximada do texto na fonte da impressão (Arial).
    Prefere métrica real via TrueType do Windows; fallback heurístico.
    """
    texto = str(texto or '')
    if not texto:
        return 0.0
    try:
        from PIL import ImageFont
        font_name = 'arialbd.ttf' if bold else 'arial.ttf'
        font_path = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts', font_name)
        if not os.path.isfile(font_path):
            font_path = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts', 'arial.ttf')
        font = ImageFont.truetype(font_path, int(font_size_px))
        if hasattr(font, 'getlength'):
            return float(font.getlength(texto))
        bbox = font.getbbox(texto)
        return float(bbox[2] - bbox[0])
    except Exception:
        # Heurística Arial uppercase bold ≈ 0.62em por caractere
        fator = 0.62 if bold else 0.55
        return float(len(texto) * font_size_px * fator)


def abreviar_nome_motorista_impressao(
    nome, max_largura_px, font_size_px=10, bold=True
):
    """
    Escolhe a forma mais completa do nome que caiba em max_largura_px.
    Não altera cadastro — uso exclusivo na renderização de impressão.
    """
    candidatos = candidatos_abreviacao_nome_motorista(nome)
    if not candidatos:
        return ''
    escolhido = candidatos[-1]
    for cand in candidatos:
        if medir_largura_texto_impressao_px(cand, font_size_px, bold) <= float(max_largura_px):
            return cand
    return escolhido


def montar_dados_cartao_motorista(
    agendamento, numero_viagem=None, max_largura_motorista_px=None
):
    """Monta dicionário com todos os campos do Cartão do Motorista (modelo oficial)."""
    from html import escape

    paciente = agendamento.paciente
    motorista = agendamento.motorista
    veiculo = agendamento.veiculo
    ac = dados_acompanhante_do_agendamento(agendamento)

    if paciente:
        cel, res = telefones_paciente_exibir(paciente)
        tels = ' / '.join(t for t in (cel if cel != '—' else '', res if res != '—' else '') if t)
    else:
        tels = ''

    rua = numero = bairro = complemento = ''
    if paciente:
        end = endereco_paciente_para_campos(paciente)
        rua = end.get('logradouro') or ''
        numero = end.get('numero') or ''
        bairro = end.get('bairro') or ''
        complemento = end.get('complemento') or ''

    ponto = ponto_embarque_do_paciente(paciente)
    if not ponto:
        ponto = parse_campo_observacao_cartao(
            agendamento.observacoes, ('OBSERVAÇÃO PONTO:', 'OBS PONTO:', 'PONTO:')
        ) or ''

    hora_consulta = ''
    if getattr(agendamento, 'hora_consulta', None):
        hora_consulta = agendamento.hora_consulta.strftime('%H:%M:%S')
    else:
        hora_consulta = parse_campo_observacao_cartao(
            agendamento.observacoes, ('H. DA CONSULTA:', 'HORA DA CONSULTA:', 'H. CONSULTA:', 'H.DA CONSULTA')
        )
    atendente = ''
    try:
        from flask_login import current_user
        if getattr(current_user, 'is_authenticated', False):
            atendente = (
                getattr(current_user, 'nome_completo', None)
                or getattr(current_user, 'username', '')
                or ''
            ).strip()
    except Exception:
        atendente = ''
    # Fallback só se não houver usuário logado (impressão sem sessão).
    if not atendente:
        atendente = parse_campo_observacao_cartao(agendamento.observacoes, ('ATENDENTE:',))

    obs_marcador = parse_campo_observacao_cartao(
        agendamento.observacoes, ('OBSERVAÇÃO:', 'OBSERVACAO:', 'OBS:')
    )
    if obs_marcador:
        obs_livre = obs_marcador
    else:
        # OBSERVAÇÃO/PONTO unificado no modelo oficial
        obs_livre = ''
        if paciente and paciente.observacoes:
            obs_livre = paciente.observacoes

    # Junta ponto + observação livre no estilo oficial "OBSERVAÇÃO/PONTO"
    partes_obs = []
    if obs_livre:
        partes_obs.append(obs_livre.strip())
    elif ponto:
        partes_obs.append(ponto.strip())
    if ponto and obs_livre and ponto.strip().upper() not in obs_livre.upper():
        partes_obs = [f'{obs_livre.strip()} - {ponto.strip()}']
    obs_ponto = ' - '.join(partes_obs) if partes_obs else (ponto or obs_livre or '')

    condicao = formatar_condicao_paciente_exibir(paciente) if paciente else ''
    if condicao == '—':
        condicao = ''

    idade = ''
    if paciente and paciente.data_nascimento:
        idade = calcular_idade(paciente.data_nascimento, agendamento.data)

    frota = recurso_programacao_exibir(agendamento)
    placa = ''
    if veiculo and getattr(veiculo, 'placa', None):
        placa = veiculo.placa
    elif getattr(agendamento, 'frota', None) or getattr(agendamento, 'frota_id', None):
        frota_obj = getattr(agendamento, 'frota', None) or db.session.get(Frota, agendamento.frota_id)
        if frota_obj:
            placa = (frota_obj.numero or '').strip()

    origem = (agendamento.origem or '').strip()
    destino = (agendamento.destino or '').strip()
    # Prioriza nome/endereço CNES para o motorista (evita destino genérico só com cidade)
    if getattr(agendamento, 'destino_cnes_nome', None) and agendamento.destino_cnes_nome.strip():
        cidade_ref = (agendamento.cidade_destino or '').replace(' - SP', '').strip()
        if destino and '/' in destino:
            pass  # já formatado (Cidade/Hospital - endereço)
        else:
            est = {
                'nome_fantasia': agendamento.destino_cnes_nome.strip(),
                'municipio_nome': cidade_ref,
            }
            row = None
            if getattr(agendamento, 'destino_cnes_codigo', None):
                row = obter_estabelecimento_cache(CnesEstabelecimento, agendamento.destino_cnes_codigo)
            if row:
                est.update({
                    'endereco': row.endereco or '',
                    'numero': row.numero or '',
                    'bairro': row.bairro or '',
                    'razao_social': row.razao_social or '',
                })
            destino = formatar_destino_cnes(est, cidade_ref) or destino
    tipo = (agendamento.tipo_transporte or '').strip()

    tem_ac = bool(ac.get('tem_acompanhante') and ac.get('nome')
                  and str(ac.get('nome')).upper() not in ('SEM ACOMPANHANTE', 'SIM', '—', '-'))

    def _v(val):
        return escape(str(val).strip()) if val not in (None, '', '—') else ''

    nome_motorista_completo = (motorista.nome if motorista else '') or ''
    limiar_px = (
        LARGURA_MOTORISTA_CARTAO_PX
        if max_largura_motorista_px is None
        else max_largura_motorista_px
    )
    nome_motorista_impressao = abreviar_nome_motorista_impressao(
        nome_motorista_completo,
        max_largura_px=limiar_px,
        font_size_px=11 if limiar_px >= LARGURA_MOTORISTA_CARTAO_PX else 10,
        bold=True,
    )

    return {
        'motorista': _v(nome_motorista_impressao),
        'motorista_completo': _v(nome_motorista_completo),
        'frota': _v(frota),
        'placa': _v(placa),
        'data_consulta': agendamento.data.strftime('%d/%m/%Y') if agendamento.data else '',
        'hora_saida': agendamento.hora.strftime('%H:%M:%S') if agendamento.hora else '',
        'origem': _v(origem),
        'destino': _v(destino),
        'tipo_transporte': _v(formatar_especialidade_exibir(tipo)),
        'paciente_nome': _v(paciente.nome if paciente else ''),
        'idade': _v(idade),
        'cpf': _v(paciente.cpf if paciente else ''),
        'rua': _v(rua),
        'numero': _v(numero),
        'bairro': _v(bairro),
        'complemento': _v(complemento),
        'tel': _v(tels),
        'condicao': _v(condicao),
        'tem_ac': tem_ac,
        'ac_flag': '1' if tem_ac else '0',
        'ac_nome': _v(ac.get('nome') if tem_ac else ''),
        'ac_rg': _v(ac.get('rg') if tem_ac else ''),
        'ac_tel': _v(ac.get('tel') if tem_ac else ''),
        'ac_idade': _v(ac.get('idade') if tem_ac else ''),
        'hora_consulta': _v(hora_consulta),
        'ponto': _v(ponto),
        'atendente': _v(atendente),
        'observacao_ponto': _v(obs_ponto),
        'agendamento_id': agendamento.id,
        'numero_viagem': numero_viagem or '',
        'status': _v(agendamento.status),
    }


def _html_um_cartao_motorista(d, indice=1):
    """
    Layout fiel a AJUSTES/cartaomotorista.jpeg — 1 cartão destacável.
    Labels em peso normal; valores em negrito; campos manuais com linha.
    """
    frota = d['frota'] or d['placa']
    ac_nome = d['ac_nome'] if d['tem_ac'] else ''
    ac_tel = d['ac_tel'] if d['tem_ac'] else ''
    ac_rg = d['ac_rg'] if d['tem_ac'] else ''
    ac_idade = d.get('ac_idade') or ''
    num_viagem = int(d.get('numero_viagem') or indice)
    ponto = d.get('ponto') or ''
    obs = d.get('observacao_ponto') or ''

    return f"""
    <article class="cartao" data-viagem="{num_viagem}">
      <div class="cut-hint no-print">— destaque / corte —</div>
      <div class="cartao-inner">

        <div class="cm-top">
          <div class="cm-top-left">
            <div class="cm-ln"><span class="lb">MOTORISTA:</span> <span class="vl vl-mot" title="{d.get('motorista_completo') or d['motorista']}">{d['motorista']}</span></div>
            <div class="cm-ln"><span class="lb">FROTA:</span> <span class="vl">{frota}</span></div>
          </div>
          <div class="cm-top-right">
            <div class="cm-ln cm-data-hora">
              <span class="cm-campo">
                <span class="lb">DATA DA CONSULTA:</span>
                <span class="vl">{d['data_consulta']}</span>
              </span>
              <span class="cm-campo cm-campo-hora">
                <span class="lb">HORA DE SAIDA:</span>
                <span class="vl">{d['hora_saida']}</span>
              </span>
            </div>
            <div class="cm-ln"><span class="lb">DESTINO:</span> <span class="vl">{d['destino']}</span></div>
          </div>
        </div>

        <div class="cm-sep"></div>

        <div class="cm-ln cm-ln-spread">
          <span><span class="lb">NOME DO PACIENTE:</span> <span class="vl vl-pac">{d['paciente_nome']}</span></span>
          <span><span class="lb">IDADE</span> <span class="vl">{d['idade']}</span></span>
          <span><span class="lb">CPF:</span> <span class="vl">{d['cpf']}</span></span>
        </div>

        <div class="cm-ln cm-ln-spread">
          <span><span class="lb">RUA:</span> <span class="vl">{d['rua']}</span></span>
          <span><span class="lb">Nº:</span> <span class="vl">{d['numero']}</span></span>
          <span><span class="lb">BAIRRO</span> <span class="vl">{d['bairro']}</span></span>
        </div>

        <div class="cm-ln cm-ln-spread">
          <span><span class="lb">TEL</span> <span class="vl">{d['tel']}</span></span>
          <span><span class="lb">COND DO PACIENTE</span> <span class="vl">{d['condicao']}</span></span>
          <span><span class="lb">H.chegada:</span> <span class="man"></span></span>
        </div>

        <div class="cm-ln cm-ln-spread">
          <span><span class="lb">AC:</span> <span class="vl">{d['ac_flag']}</span>
            <span class="lb">NOME AC:</span> <span class="vl">{ac_nome}</span></span>
          <span><span class="lb">IDADE</span> <span class="vl">{ac_idade}</span></span>
          <span><span class="lb">KM CHEGADA</span> <span class="man"></span></span>
        </div>

        <div class="cm-ln cm-ln-spread">
          <span><span class="lb">RG AC:</span> <span class="vl">{ac_rg}</span>
            <span class="lb">TEL AC</span> <span class="vl">{ac_tel}</span></span>
          <span><span class="lb">H.DA CONSULTA</span> <span class="vl">{d['hora_consulta']}</span></span>
          <span><span class="lb">KM SAIDA</span> <span class="man"></span></span>
        </div>

        <div class="cm-sep"></div>

        <div class="cm-ln cm-ln-spread cm-ln-rodape">
          <span class="cm-rodape-item"><span class="lb">OBSERVACAO:</span></span>
          <span class="cm-rodape-item"><span class="lb">PONTO:</span> <span class="vl">{ponto}</span></span>
          <span class="cm-rodape-item cm-rodape-dir"><span class="lb">ATENDENTE:</span> <span class="vl">{d['atendente']}</span></span>
        </div>

        <div class="cm-obs-bloco">
          <span class="vl vl-obs">{obs}</span>
        </div>

      </div>
    </article>"""


def css_cartoes_motorista():
    """CSS fiel a cartaomotorista.jpeg · A4 paisagem · 4 cartões por folha."""
    return """
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 12px;
    font-family: "Courier New", Courier, monospace;
    color: #000; background: #c8c8c8;
  }
  .toolbar {
    max-width: 297mm; margin: 0 auto 12px;
    display: flex; gap: 8px; flex-wrap: wrap; align-items: center;
    font-family: Arial, Helvetica, sans-serif;
  }
  .toolbar a, .toolbar button {
    border: 0; border-radius: 6px; padding: 9px 14px; cursor: pointer;
    font-size: 13px; text-decoration: none; color: #fff;
  }
  .btn-print { background: #2e7d32; }
  .btn-back { background: #546e7a; }
  .toolbar .info { font-size: 12.5px; color: #222; }

  .folha {
    max-width: 297mm; margin: 0 auto;
    display: flex; flex-direction: column; gap: 8px;
  }
  .cartao {
    background: #fff;
    page-break-inside: avoid;
    break-inside: avoid;
  }
  .cut-hint {
    text-align: center; font-size: 10px; color: #777;
    border-top: 1px dashed #999; margin-bottom: 3px; padding-top: 2px;
    font-family: Arial, Helvetica, sans-serif;
  }
  .cartao:first-child .cut-hint { display: none; }

  .cartao-inner {
    border: 1.5px solid #000;
    padding: 5px 8px 6px;
  }

  .cm-top {
    display: flex; gap: 10px; align-items: flex-start;
  }
  .cm-top-left { flex: 0 0 32%; min-width: 0; }
  .cm-top-right { flex: 1; min-width: 0; }

  .cm-ln {
    display: flex; flex-wrap: wrap; align-items: baseline;
    gap: 3px 8px; margin: 0; line-height: 1.2;
    font-size: 11px;
  }
  .cm-ln-inline { flex-wrap: nowrap; }
  .cm-data-hora {
    display: flex;
    flex-wrap: nowrap;
    align-items: baseline;
    justify-content: space-between;
    width: 100%;
    gap: 10px 16px;
  }
  .cm-campo {
    display: inline-flex;
    flex-wrap: nowrap;
    align-items: baseline;
    gap: 4px;
    white-space: nowrap;
  }
  .cm-campo-hora {
    margin-left: auto;
    justify-content: flex-end;
  }
  .cm-ln-spread {
    justify-content: space-between;
    gap: 6px 12px;
    margin-top: 1px;
  }
  .cm-ln-spread > span { min-width: 0; }
  .cm-ln-rodape {
    align-items: baseline;
    gap: 8px 16px;
  }
  .cm-rodape-item {
    flex: 1 1 0;
    min-width: 0;
    display: inline-flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 4px;
  }
  .cm-rodape-dir {
    justify-content: flex-end;
    text-align: right;
  }

  .sp { display: inline-block; width: 14px; }

  .cm-sep {
    border-top: 1px solid #bbb;
    margin: 3px 0 2px;
  }

  .lb {
    font-weight: 400;
    text-transform: uppercase;
    font-size: 10.5px;
  }
  .vl {
    font-weight: 700;
    text-transform: uppercase;
    word-break: break-word;
    font-size: 11.5px;
  }
  .vl-mot {
    white-space: nowrap;
    overflow: hidden;
    word-break: normal;
  }
  .vl-pac { font-size: 12px; font-weight: 800; }

  .man {
    display: inline-block;
    min-width: 48px;
    border-bottom: 1px solid #000;
    height: 11px;
    vertical-align: baseline;
    margin-left: 2px;
  }

  .cm-obs-bloco {
    margin-top: 2px;
    min-height: 1.4em;
  }
  .vl-obs {
    display: block;
    font-size: 12px;
    font-weight: 800;
    text-transform: uppercase;
    line-height: 1.25;
  }

  @media screen {
    .cartao-inner { box-shadow: 0 1px 2px rgba(0,0,0,.14); }
  }

  @media print {
    body { background: #fff; padding: 0; margin: 0; }
    .toolbar, .no-print, .cut-hint { display: none !important; }
    .folha { max-width: none; margin: 0; gap: 0; }

    @page {
      size: A4 landscape;
      margin: 5mm 7mm;
    }

    /* A4 paisagem (~200mm úteis) → 4 cartões ≈ 46,5mm cada */
    .cartao {
      width: 100%;
      height: 46.5mm;
      max-height: 46.5mm;
      overflow: hidden;
      margin: 0 0 1.5mm 0;
      page-break-inside: avoid;
      break-inside: avoid;
    }
    .cartao:nth-child(4n) {
      margin-bottom: 0;
      page-break-after: always;
      break-after: page;
    }
    .cartao:nth-child(4n):last-child {
      page-break-after: auto;
      break-after: auto;
    }
    .cartao-inner {
      height: 100%;
      border-width: 1.2px;
      padding: 1.5px 4px 2px;
    }
    .cm-sep { margin: 1.5px 0 1px; }
    .cm-ln { font-size: 8.5px; line-height: 1.12; gap: 2px 6px; }
    .lb { font-size: 8px; }
    .vl { font-size: 9px; }
    .vl-pac { font-size: 9.5px; }
    .vl-obs { font-size: 9px; line-height: 1.15; }
    .man { min-width: 36px; height: 8px; }
    .cm-obs-bloco { min-height: 1.1em; margin-top: 1px; }
  }
"""


def gerar_html_lote_cartoes_motorista(agendamentos, titulo_extra=''):
    """
    Página de impressão: um cartão por viagem, empilhados.
    A4 paisagem · 4 cartões por folha · destacáveis.
    Com 5+ viagens: folha 1 = 4 cartões, folha 2 = demais (também 4/folha).
    """
    try:
        from flask import url_for, has_request_context
        href_voltar = url_for('agendamentos') if has_request_context() else '/transporte/agendamentos'
    except Exception:
        href_voltar = '/transporte/agendamentos'

    cards = []
    for i, ag in enumerate(agendamentos, start=1):
        d = montar_dados_cartao_motorista(ag, numero_viagem=i)
        cards.append(_html_um_cartao_motorista(d, indice=i))

    cards_html = '\n'.join(cards) if cards else '<p>Nenhuma viagem elegível.</p>'
    qtd = len(agendamentos)
    motorista_nome = ''
    data_ref = ''
    if agendamentos:
        nomes_mot = []
        vistos = set()
        for a in agendamentos:
            n = (a.motorista.nome if a.motorista else '') or ''
            if n and n not in vistos:
                vistos.add(n)
                nomes_mot.append(n)
        if len(nomes_mot) == 1:
            motorista_nome = nomes_mot[0]
        elif len(nomes_mot) > 1:
            motorista_nome = f'{len(nomes_mot)} motoristas'
        datas = {a.data for a in agendamentos if a.data}
        if len(datas) == 1:
            data_ref = next(iter(datas)).strftime('%d/%m/%Y')
        elif len(datas) > 1:
            data_ref = f'{len(datas)} datas'

    info = f'{qtd} viagem(ns)'
    if motorista_nome:
        info += f' · Motorista: {motorista_nome}'
    if data_ref:
        info += f' · Data: {data_ref}'
    if titulo_extra:
        info += f' · {titulo_extra}'

    return f'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cartões do Motorista — {qtd} viagem(ns)</title>
<style>{css_cartoes_motorista()}</style>
</head>
<body>
  <div class="toolbar no-print">
    <button class="btn-print" type="button" onclick="window.print()">Imprimir cartões (A4 paisagem · 4/folha)</button>
    <a class="btn-back" href="{href_voltar}">Voltar aos Agendamentos</a>
    <span class="info">{info} — A4 paisagem · 4 cartões por folha · destaque/corte</span>
  </div>
  <div class="folha">
    {cards_html}
  </div>
</body>
</html>'''


def gerar_html_cartao_motorista(agendamento):
    """Compat: um único agendamento → lote com 1 cartão (mesmo layout oficial)."""
    return gerar_html_lote_cartoes_motorista([agendamento])


def listar_agendamentos_cartoes_do_dia(motorista_id, data_ref, excluir_cancelados=True):
    """Todas as viagens do motorista na data, ordenadas por hora (cada uma = 1 cartão)."""
    q = Agendamento.query.filter(
        Agendamento.motorista_id == motorista_id,
        Agendamento.data == data_ref,
    )
    if excluir_cancelados:
        q = q.filter(Agendamento.status != 'cancelado')
    return q.order_by(Agendamento.hora.asc(), Agendamento.id.asc()).all()


def garantir_agendamento_demo_cartao_motorista():
    """
    Cria/atualiza várias viagens no mesmo dia para o mesmo motorista
    (demonstra 1 cartão por viagem · 4 por folha A4 paisagem).
    Retorna lista de Agendamentos.
    """
    from datetime import time as time_cls

    motorista = Motorista.query.filter_by(status='ativo').order_by(Motorista.id).first()
    if not motorista:
        motorista = Motorista(
            nome='DANIEL',
            cpf='529.982.247-25',
            telefone='19999990000',
            data_nascimento=date(1985, 1, 1),
            cnh='99887766554',
            categoria_cnh='D',
            vencimento_cnh=date.today().replace(year=date.today().year + 2),
            status='ativo',
        )
        db.session.add(motorista)
        db.session.flush()

    veiculo = Veiculo.query.filter_by(ativo=True).order_by(Veiculo.id).first()
    if not veiculo:
        veiculo = Veiculo(
            placa='FROTA010',
            numero_frota='10',
            marca='MERCEDES',
            modelo='SPRINTER',
            ano=2020,
            tipo='van',
            capacidade=15,
            adaptado=False,
            ativo=True,
        )
        db.session.add(veiculo)
        db.session.flush()

    data_ref = date(2026, 7, 21)

    viagens = [
        {
            'cpf': '567.276.268-98',
            'nome': 'SAMUEL DOS SANTOS BARBOSA',
            'nasc': date(2019, 3, 15),
            'rua': 'ARMANDO MOURA', 'num': '62', 'bairro': 'CONDOMINIO PQ ESTHER',
            'tel': '983201356', 'tel2': '981554513',
            'cond': 'Pediátrico',
            'hora': time_cls(8, 0, 0),
            'destino': 'HOSPITAL REGIONAL / AV. CENTRAL, 100',
            'origem': 'COSMÓPOLIS/SP — POSTO COSMÓPOLIS',
            'tipo': 'consulta',
            'obs': (
                'NOME AC: SANDRA FERNANDES DOS SANTOS | RG AC: 30750225865 | TEL AC: 983201356 | '
                'H. DA CONSULTA: 09:00:00 | ATENDENTE: JULIANA | '
                'OBSERVAÇÃO: CONSULTA PEDIATRICA - RESIDENCIA'
            ),
        },
        {
            'cpf': '390.533.447-05',
            'nome': 'LUCAS VINICIOS SOUZA RIBEIRO',
            'nasc': date(2006, 5, 10),
            'rua': 'ALBINO GIOVANONI', 'num': '13', 'bairro': 'RESIDENCIAL LARANJEIRAS',
            'tel': '991516936', 'tel2': '',
            'cond': '',
            'hora': time_cls(8, 2, 0),
            'destino': 'LIMEIRA/RUA CEARA, 842, VILA CRISTOVAM',
            'origem': 'COSMÓPOLIS/SP — RESIDÊNCIA',
            'tipo': 'tratamento',
            'obs': (
                'ACOMPANHANTE: SEM ACOMPANHANTE | H. DA CONSULTA: 09:00:00 | ATENDENTE: JULIANA | '
                'OBSERVAÇÃO: TRATAMENTO TERAPEUTICO TODA SEXTA DAS 09:00 AS 12H - RESIDÊNCIA CARRO BAIXO'
            ),
        },
        {
            'cpf': '111.444.777-35',
            'nome': 'MARIA APARECIDA FERREIRA',
            'nasc': date(1958, 11, 2),
            'rua': 'RUA DAS FLORES', 'num': '200', 'bairro': 'CENTRO',
            'tel': '19988887777', 'tel2': '',
            'cond': 'Cadeirante',
            'hora': time_cls(10, 30, 0),
            'destino': 'SANTA CASA / RUA HOSPITAL, 50',
            'origem': 'COSMÓPOLIS/SP — POSTO COSMÓPOLIS',
            'tipo': 'exame',
            'obs': (
                'NOME AC: JOSE FERREIRA | TEL AC: 19977776666 | '
                'H. DA CONSULTA: 11:30:00 | ATENDENTE: JULIANA | '
                'OBSERVAÇÃO: NECESSITA CADEIRA DE RODAS - ENTRADA PELA RAMPA'
            ),
        },
        {
            'cpf': '153.509.460-56',
            'nome': 'ANTONIO CARLOS MENDES',
            'nasc': date(1972, 8, 20),
            'rua': 'AV. BRASIL', 'num': '890', 'bairro': 'JARDIM NOVO',
            'tel': '19966665555', 'tel2': '',
            'cond': 'Uso de oxigênio (O₂)',
            'hora': time_cls(13, 0, 0),
            'destino': 'CLINICA DE HEMODIALISE / ROD. SP-340 KM 12',
            'origem': 'COSMÓPOLIS/SP — RESIDÊNCIA',
            'tipo': 'tratamento',
            'obs': (
                'ACOMPANHANTE: SEM ACOMPANHANTE | H. DA CONSULTA: 14:00:00 | '
                'OBSERVAÇÃO: HEMODIALISE - PACIENTE COM O2 PORTATIL'
            ),
        },
        {
            'cpf': '086.176.970-44',
            'nome': 'ANA PAULA COSTA',
            'nasc': date(1990, 1, 15),
            'rua': 'RUA XV DE NOVEMBRO', 'num': '45', 'bairro': 'VILA NOVA',
            'tel': '19955554444', 'tel2': '',
            'cond': '',
            'hora': time_cls(15, 30, 0),
            'destino': 'CAPS / RUA SAUDE MENTAL, 12',
            'origem': 'COSMÓPOLIS/SP — POSTO COSMÓPOLIS',
            'tipo': 'consulta',
            'obs': (
                'NOME AC: PAULO COSTA | TEL AC: 19944443333 | '
                'H. DA CONSULTA: 16:00:00 | ATENDENTE: JULIANA | '
                'OBSERVAÇÃO: RETORNO CAPS - AGUARDAR NA RECEPCAO'
            ),
        },
    ]

    agendamentos = []
    for v in viagens:
        pac = Paciente.query.filter_by(cpf=v['cpf']).first()
        if not pac:
            # CPF demo inválido em alguns casos — tenta por nome
            pac = Paciente.query.filter(Paciente.nome == v['nome']).first()
        if not pac:
            pac = Paciente(
                nome=v['nome'],
                cpf=v['cpf'],
                telefone=v['tel'][:15],
                data_nascimento=v['nasc'],
                endereco=f"RUA {v['rua']}, {v['num']} - {v['bairro']}",
                logradouro=v['rua'],
                numero=v['num'],
                bairro=v['bairro'],
                ponto_referencia='POSTO COSMÓPOLIS',
                ponto_embarque='POSTO COSMÓPOLIS',
                ativo=True,
                condicao_especial=bool(v['cond']),
                condicao_paciente=v['cond'] or None,
            )
            aplicar_telefones_paciente(pac, v['tel'], v.get('tel2') or '')
            db.session.add(pac)
            db.session.flush()
        else:
            pac.logradouro = v['rua']
            pac.numero = v['num']
            pac.bairro = v['bairro']
            if v['cond']:
                pac.condicao_especial = True
                pac.condicao_paciente = v['cond']
            aplicar_telefones_paciente(pac, v['tel'], v.get('tel2') or '')

        ag = Agendamento.query.filter_by(
            paciente_id=pac.id, data=data_ref, hora=v['hora']
        ).first()
        if not ag:
            ag = Agendamento(
                paciente_id=pac.id,
                motorista_id=motorista.id,
                veiculo_id=veiculo.id,
                tipo_transporte=v['tipo'],
                data=data_ref,
                hora=v['hora'],
                origem=v['origem'],
                destino=v['destino'],
                observacoes=v['obs'],
                status='confirmado',
            )
            db.session.add(ag)
        else:
            ag.motorista_id = motorista.id
            ag.veiculo_id = veiculo.id
            ag.origem = v['origem']
            ag.destino = v['destino']
            ag.observacoes = v['obs']
            ag.status = 'confirmado'
            ag.tipo_transporte = v['tipo']
        agendamentos.append(ag)

    db.session.commit()
    # reordena por hora
    return sorted(agendamentos, key=lambda a: (a.hora, a.id))


def buscar_lista_impressao(query, page, per_page, paginas, *order_by):
    """Busca registros paginados para impressão."""
    total = query.order_by(None).count()
    total_pages = max(1, (total + per_page - 1) // per_page)
    ini, fim = obter_intervalo_paginas_impressao(paginas, page, total_pages)
    offset = (ini - 1) * per_page
    limit = (fim - ini + 1) * per_page
    q = query
    if order_by:
        q = q.order_by(*order_by)
    lista = q.offset(offset).limit(limit).all()
    return lista, total, total_pages, ini, fim


def buscar_agendamentos_impressao(filtros, page, per_page, paginas):
    query = montar_query_agendamentos(filtros)
    return buscar_lista_impressao(
        query, page, per_page, paginas,
        Agendamento.data.desc(), Agendamento.hora.desc()
    )


def buscar_agendamentos_cartoes_impressao(filtros, page, per_page, paginas):
    """Programados do filtro para impressão em lote dos Cartões do Motorista."""
    query = query_agendamentos_programados(filtros)
    return buscar_lista_impressao(
        query, page, per_page, paginas,
        Agendamento.data.asc(), Agendamento.hora.asc(), Agendamento.id.asc()
    )


def gerar_botoes_impressao(route_name, filtros_url, page, per_page):
    """Botões de impressão reutilizáveis nas listagens."""
    from flask import url_for
    from urllib.parse import urlencode

    base = {**filtros_url, 'page': page, 'per_page': per_page}

    def href(paginas):
        return url_for(route_name) + '?' + urlencode({**base, 'paginas': paginas})

    return f'''
    <div class="no-print" style="display:flex; flex-wrap:wrap; gap:0.5rem; align-items:center;">
        <span style="font-size:0.85rem; color:var(--gray-color);">Imprimir:</span>
        <a href="{href('atual')}" target="_blank" class="btn print-btn" style="padding:0.4rem 0.75rem; font-size:0.8rem;">Página atual</a>
        <a href="{href('1-2')}" target="_blank" class="btn print-btn" style="padding:0.4rem 0.75rem; font-size:0.8rem;">Pág. 1–2</a>
        <a href="{href('1-3')}" target="_blank" class="btn print-btn" style="padding:0.4rem 0.75rem; font-size:0.8rem;">Pág. 1–3</a>
        <a href="{href('todas')}" target="_blank" class="btn print-btn" style="padding:0.4rem 0.75rem; font-size:0.8rem;">Todas</a>
    </div>
    '''



def gerar_botoes_folha_espelho(filtros_url, page, per_page, qtd_programados=0, contexto=''):
    """
    Painel de impressão na listagem — Folha Espelho + Cartões do Motorista
    do filtro atual (só viagens já programadas).
    """
    from flask import url_for
    from html import escape
    from urllib.parse import urlencode

    base = {**filtros_url, 'page': page, 'per_page': per_page}
    contexto_txt = escape(contexto or 'Filtro atual')
    qtd = int(qtd_programados or 0)
    tip_off = (
        'Nenhuma viagem programada neste filtro. '
        'Use Programar (motorista + veículo/frota) e tente de novo.'
    )

    def href_folha(paginas):
        return url_for('agendamentos_imprimir') + '?' + urlencode({**base, 'paginas': paginas})

    def href_cartoes(paginas):
        return (
            url_for('agendamentos_cartoes_motorista')
            + '?'
            + urlencode({**base, 'paginas': paginas})
        )

    if qtd <= 0:
        return f'''
    <div class="card no-print" style="margin-bottom:1rem;border-left:4px solid #adb5bd;background:#f8f9fa;">
      <div style="display:flex;flex-wrap:wrap;gap:0.75rem;align-items:flex-start;justify-content:space-between;">
        <div style="min-width:220px;flex:1;">
          <div style="font-weight:700;color:#495057;font-size:1rem;">📄 Impressão — Folha Espelho e Cartões</div>
          <div style="margin-top:0.35rem;color:#6c757d;font-size:0.9rem;">
            Recorte: <strong>{contexto_txt}</strong>
          </div>
          <div style="margin-top:0.35rem;color:#6c757d;font-size:0.88rem;">{escape(tip_off)}</div>
        </div>
        <div style="display:flex;flex-wrap:wrap;gap:0.45rem;align-items:center;">
          <span class="btn" style="padding:0.55rem 0.9rem;opacity:0.45;pointer-events:none;cursor:not-allowed;"
                aria-disabled="true">Folha Espelho (0)</span>
          <span class="btn" style="padding:0.55rem 0.9rem;opacity:0.45;pointer-events:none;cursor:not-allowed;"
                aria-disabled="true">Cartões (0)</span>
        </div>
      </div>
    </div>
    '''

    return f'''
    <div class="card no-print" style="margin-bottom:1rem;border-left:4px solid #0d6efd;background:#f0f7ff;">
      <div style="display:flex;flex-wrap:wrap;gap:0.85rem;align-items:flex-start;justify-content:space-between;">
        <div style="min-width:240px;flex:1;">
          <div style="font-weight:700;color:#0d47a1;font-size:1.05rem;">📄 Impressão — Folha Espelho e Cartões</div>
          <div style="margin-top:0.4rem;color:#334;font-size:0.92rem;">
            Recorte: <strong>{contexto_txt}</strong>
            · <strong style="color:#0d6efd;">{qtd}</strong> viagem(ns) programada(s) pronta(s) para impressão
          </div>
          <div style="margin-top:0.35rem;color:#5a6a7a;font-size:0.85rem;">
            Inclui só quem já tem <strong>motorista + veículo/frota</strong>. Cancelados e “Aguardando” ficam de fora.
            Folha Espelho = lista (10/página). Cartões = 1 cartão por viagem (4/folha A4 paisagem).
          </div>
        </div>
        <div style="display:flex;flex-wrap:wrap;gap:0.45rem;align-items:center;">
          <a href="{href_folha('todas')}" target="_blank" class="btn"
             style="padding:0.55rem 1rem;background:#0d6efd;color:#fff;font-weight:700;"
             title="Imprimir Folha Espelho de todas as viagens programadas neste filtro">
            🖨️ Folha Espelho — todas ({qtd})
          </a>
          <a href="{href_cartoes('todas')}" target="_blank" class="btn"
             style="padding:0.55rem 1rem;background:#2e7d32;color:#fff;font-weight:700;"
             title="Imprimir Cartão do Motorista de todas as viagens programadas neste filtro">
            🪪 Cartões — todos ({qtd})
          </a>
          <a href="{href_folha('atual')}" target="_blank" class="btn print-btn"
             style="padding:0.5rem 0.85rem;font-size:0.85rem;"
             title="Folha Espelho só da página atual">Folha · pág. atual</a>
          <a href="{href_cartoes('atual')}" target="_blank" class="btn print-btn"
             style="padding:0.5rem 0.85rem;font-size:0.85rem;"
             title="Cartões só da página atual">Cartões · pág. atual</a>
        </div>
      </div>
    </div>
    '''


def gerar_botoes_impressao_programacao(agendamento):
    """
    Botões Folha Espelho + Cartão na tela Programar.
    Liberados somente com programação completa (motorista + veículo/frota).
    """
    from flask import url_for
    from html import escape as esc

    ok, motivo = agendamento_elegivel_cartao_motorista(agendamento)
    tip = motivo or (
        'Disponível somente após salvar a programação do motorista e do veículo ou da frota.'
    )
    estilo_btn = 'padding:0.45rem 0.85rem; font-size:0.875rem;'
    estilo_off = (
        f'{estilo_btn} opacity:0.45; pointer-events:none; cursor:not-allowed;'
    )

    if not ok:
        tip_esc = esc(tip)
        return f'''
    <div class="card no-print" style="margin-bottom:1rem; border-left:4px solid var(--gray-color);">
      <div style="display:flex;flex-wrap:wrap;gap:0.65rem;align-items:center;" title="{tip_esc}">
        <span style="font-size:0.9rem;color:var(--gray-color);font-weight:600;">Impressão:</span>
        <span class="btn print-btn" style="{estilo_off}" aria-disabled="true">📄 Folha Espelho</span>
        <span class="btn print-btn" style="{estilo_off}" aria-disabled="true">🪪 Cartão do Motorista</span>
        <small style="color:var(--gray-color);">{tip_esc}</small>
      </div>
    </div>
    '''

    href_folha = url_for('folha_espelho_agendamento', agendamento_id=agendamento.id)
    href_cartao = url_for(
        'cartao_motorista', agendamento_id=agendamento.id, somente=1
    )
    href_cartao_dia = url_for('cartao_motorista', agendamento_id=agendamento.id)
    return f'''
    <div class="card no-print" style="margin-bottom:1rem; border-left:4px solid var(--info-color);">
      <div style="display:flex;flex-wrap:wrap;gap:0.65rem;align-items:center;">
        <span style="font-size:0.9rem;color:var(--gray-color);font-weight:600;">Impressão:</span>
        <a href="{href_folha}" target="_blank" class="btn print-btn" style="{estilo_btn}"
           title="Abrir Folha Espelho desta viagem">📄 Folha Espelho</a>
        <a href="{href_cartao}" target="_blank" class="btn print-btn" style="{estilo_btn}"
           title="Abrir Cartão do Motorista somente desta viagem">🪪 Cartão (esta viagem)</a>
        <a href="{href_cartao_dia}" target="_blank" class="btn print-btn" style="{estilo_btn}"
           title="Abrir todos os cartões do mesmo motorista nesta data">🪪 Cartões do dia</a>
        <small style="color:var(--gray-color);">Programação concluída — liberado para impressão.</small>
      </div>
    </div>
    '''


def montar_shell_impressao(titulo_doc, rota_voltar, paginas_html):
    """HTML base para impressão em paisagem A4."""
    from flask import url_for

    hoje = date.today()
    data_extenso = format_data_extenso_pt(hoje)
    data_curta = hoje.strftime('%d/%m/%Y')

    return f'''
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <title>{titulo_doc}</title>
        <style>
            @page {{ size: A4 landscape; margin: 10mm 8mm 14mm 8mm; }}
            * {{ box-sizing: border-box; }}
            body {{ font-family: Arial, sans-serif; margin: 0; color: #222; font-size: 9pt; }}
            .print-sheet {{
                page-break-after: always;
                min-height: 185mm;
                position: relative;
                padding-bottom: 12mm;
            }}
            .print-sheet:last-child {{ page-break-after: auto; }}
            .print-header h1 {{ margin: 0 0 4px; font-size: 14pt; color: #43aca7; }}
            .print-header p {{ margin: 2px 0; color: #666; font-size: 8pt; }}
            .print-table {{ width: 100%; border-collapse: collapse; margin-top: 8px; }}
            .print-table th {{
                background: #43aca7; color: white; padding: 5px 4px; text-align: left; font-size: 7.5pt;
            }}
            .print-table td {{
                padding: 4px; border-bottom: 1px solid #ddd; vertical-align: top; font-size: 7.5pt;
                word-break: break-word;
            }}
            .print-footer {{
                position: absolute;
                bottom: 0;
                left: 0;
                right: 0;
                display: flex;
                justify-content: space-between;
                align-items: center;
                border-top: 1px solid #ccc;
                padding-top: 4px;
                font-size: 8pt;
                color: #444;
            }}
            .no-print-bar {{
                background: #f5f5f5; padding: 12px 16px; border-bottom: 1px solid #ddd;
                display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
            }}
            .no-print-bar button, .no-print-bar a {{
                padding: 8px 14px; background: #43aca7; color: white; border: none;
                border-radius: 6px; cursor: pointer; text-decoration: none; font-size: 14px;
            }}
            .no-print-bar a.sec {{ background: #6d7a8c; }}
            @media print {{
                .no-print-bar {{ display: none !important; }}
            }}
        </style>
    </head>
    <body>
        <div class="no-print-bar">
            <button onclick="window.print()">🖨️ Imprimir</button>
            <a href="{url_for(rota_voltar)}" class="sec">← Voltar</a>
        </div>
        {paginas_html}
    </body>
    </html>
    '''


def gerar_folhas_tabela(registros, linhas_por_pagina, titulo, resumo, cabecalhos, gerar_linha):
    """Monta folhas de impressão com tabela e rodapé."""
    from html import escape

    hoje = date.today()
    data_extenso = format_data_extenso_pt(hoje)
    data_curta = hoje.strftime('%d/%m/%Y')
    chunks = [
        registros[i:i + linhas_por_pagina]
        for i in range(0, max(len(registros), 1), linhas_por_pagina)
    ] or [[]]
    total_folhas = len(chunks)
    ths = ''.join(f'<th>{escape(h)}</th>' for h in cabecalhos)
    paginas_html = ''

    for idx, chunk in enumerate(chunks, start=1):
        rows = ''.join(gerar_linha(item) for item in chunk)
        paginas_html += f'''
        <div class="print-sheet">
            <div class="print-header">
                <h1>{escape(titulo)}</h1>
                <p>{escape(resumo)}</p>
                <p>{format_numero_br(len(registros))} registro(s) nesta impressão</p>
            </div>
            <table class="print-table">
                <thead><tr>{ths}</tr></thead>
                <tbody>{rows}</tbody>
            </table>
            <div class="print-footer">
                <span>{data_extenso}</span>
                <span>{data_curta}</span>
                <span>Página {idx} de {total_folhas}</span>
            </div>
        </div>
        '''
    return paginas_html


def resumo_filtros_agendamentos(filtros):
    partes = []
    periodo = (filtros.get('periodo') or '').strip()
    if periodo == 'hoje':
        partes.append(f'Hoje ({format_data_br(date.today())})')
    elif periodo == 'amanha':
        partes.append(f'Amanhã ({format_data_br(date.today() + timedelta(days=1))})')
    elif periodo == 'semana':
        partes.append('Esta semana')
    elif periodo == 'mes':
        partes.append('Este mês')
    if filtros.get('id'):
        partes.append(f"ID: {filtros['id']}")
    if filtros.get('paciente'):
        partes.append(f"Paciente: {filtros['paciente']}")
    if filtros.get('data'):
        partes.append(f"Data: {format_data_br(filtros['data'])}")
    if filtros.get('data_inicio') or filtros.get('data_fim'):
        partes.append(f"Período: {format_data_br(filtros.get('data_inicio'))} a {format_data_br(filtros.get('data_fim'))}")
    if filtros.get('status'):
        partes.append(f"Status: {filtros['status'].replace('_', ' ').title()}")
    if filtros.get('motorista'):
        partes.append(f"Motorista: {filtros['motorista']}")
    if filtros.get('frota'):
        partes.append(f"Frota: {filtros['frota']}")
    if filtros.get('destino'):
        partes.append(f"Destino: {filtros['destino']}")
    return ' · '.join(partes) if partes else 'Todos os registros (conforme filtros ativos)'


def rotulo_contexto_folha_espelho(filtros):
    """Rótulo curto do recorte atual para o painel Folha Espelho."""
    f = filtros or {}
    periodo = (f.get('periodo') or '').strip()
    if periodo == 'hoje':
        return f'Hoje — {format_data_br(date.today())}'
    if periodo == 'amanha':
        return f'Amanhã — {format_data_br(date.today() + timedelta(days=1))}'
    if periodo == 'semana':
        return 'Esta semana'
    if periodo == 'mes':
        return 'Este mês'
    if f.get('data'):
        return f"Data {format_data_br(f['data'])}"
    if f.get('data_inicio') or f.get('data_fim'):
        ini = format_data_br(f.get('data_inicio')) or '…'
        fim = format_data_br(f.get('data_fim')) or '…'
        return f'Período {ini} a {fim}'
    if (f.get('status') or '').lower() == 'cancelado':
        return 'Cancelados (impressão não inclui cancelados)'
    if f.get('status'):
        return f"Status: {f['status'].replace('_', ' ').title()}"
    if f.get('motorista') or f.get('frota') or f.get('paciente') or f.get('destino'):
        return 'Filtros personalizados'
    return 'Filtro atual (ativos)'


def query_agendamentos_programados(filtros):
    """Agendamentos do filtro com programação completa (Folha Espelho)."""
    return montar_query_agendamentos(filtros).filter(
        Agendamento.motorista_id.isnot(None),
        db.or_(
            Agendamento.veiculo_id.isnot(None),
            Agendamento.frota_id.isnot(None),
        ),
        Agendamento.status != 'cancelado',
    )


FOLHA_ESPELHO_REGISTROS_POR_PAGINA = 10
_DIAS_CURTO_FOLHA = (
    'SEGUNDA', 'TERÇA', 'QUARTA', 'QUINTA', 'SEXTA', 'SÁBADO', 'DOMINGO',
)


def formatar_data_lista_controle(data_ref):
    """Retorna (dd/mm/aaaa, dia curto SEXTA, data por extenso)."""
    if not data_ref:
        return '', '', ''
    dia_curto = _DIAS_CURTO_FOLHA[data_ref.weekday()]
    data_br = data_ref.strftime('%d/%m/%Y')
    data_extenso = format_data_extenso_pt(data_ref)
    return data_br, dia_curto, data_extenso


def data_referencia_folha_espelho(agendamentos):
    """Data dos agendamentos impressos (única ou a mais frequente)."""
    datas = [a.data for a in (agendamentos or []) if getattr(a, 'data', None)]
    if not datas:
        return None
    if all(d == datas[0] for d in datas):
        return datas[0]
    from collections import Counter
    contagem = Counter(datas)
    mais = contagem.most_common()
    max_n = mais[0][1]
    candidatas = sorted(d for d, n in mais if n == max_n)
    return candidatas[0]


def montar_dados_folha_espelho(agendamento):
    """Campos da Folha Espelho (AJUSTES/DoJeitoQuePreciso.jpg)."""
    from html import escape
    d = montar_dados_cartao_motorista(
        agendamento, max_largura_motorista_px=LARGURA_MOTORISTA_FOLHA_PX
    )
    paciente = agendamento.paciente
    rua = d.get('rua') or ''
    numero = d.get('numero') or ''
    bairro = d.get('bairro') or ''
    partes_rua = [p for p in (rua, numero, bairro) if p]
    rua_completa = ' '.join(partes_rua)
    especialidade = d.get('tipo_transporte') or ''
    obs = d.get('observacao_ponto') or ''
    ponto = d.get('ponto') or ''
    tratamento = ' - '.join(p for p in (especialidade, obs) if p)
    if not tratamento and paciente and paciente.observacoes:
        tratamento = escape(str(paciente.observacoes).strip().upper())
    tem_ac = bool(d.get('tem_ac'))
    return {
        **d,
        'rua_completa': rua_completa,
        'tratamento': tratamento,
        'ac_nome_exibir': d['ac_nome'] if tem_ac else 'SEM ACOMP',
        'ac_idade_exibir': d.get('ac_idade') or '',
        'ac_tel_exibir': d.get('ac_tel') or '',
        'ponto_exibir': ponto or 'RESIDÊNCIA',
    }


def _html_cabecalho_colunas_folha_espelho():
    """Subtítulos oficiais — idênticos a DoJeitoQuePreciso.jpg."""
    return """
          <div class="fe-cab">
            <span>MOTORISTA LEVA</span>
            <span>FROTA:</span>
            <span>H. SAIDA:</span>
            <span>DESTINO:</span>
            <span>NOME DO PACIENTE:</span>
            <span>IDADE:</span>
            <span>AC:</span>
            <span>H. CONSULTA</span>
            <span>PONTO:</span>
          </div>"""


def _html_bloco_folha_espelho(d):
    """
    Registro em 3 linhas sob as colunas do modelo oficial.
    Linha 1 = só valores (alinhados aos subtítulos).
    Linha 2 = TEL / RUA / tratamento.
    Linha 3 = ATENDENTE / NOME AC / IDADE AC / TEL AC.
    Negrito nos valores: Motorista, Frota, H. Saída, Nome Paciente,
    H. Consulta, Atendente, Nome Ac., Idade Ac., Telefone Ac.
    """
    frota = d.get('frota') or d.get('placa') or ''
    return f"""
    <div class="fe-bloco">
      <div class="fe-l1">
        <span class="fe-c fe-mot"><strong class="fe-b" title="{d.get('motorista_completo') or d.get('motorista') or ''}">{d.get('motorista') or ''}</strong></span>
        <span class="fe-c"><strong class="fe-b">{frota}</strong></span>
        <span class="fe-c"><strong class="fe-b">{d.get('hora_saida') or ''}</strong></span>
        <span class="fe-c"><span class="fe-v">{d.get('destino') or ''}</span></span>
        <span class="fe-c"><strong class="fe-b">{d.get('paciente_nome') or ''}</strong></span>
        <span class="fe-c"><span class="fe-v">{d.get('idade') or ''}</span></span>
        <span class="fe-c"><span class="fe-v">{d.get('ac_flag') or '0'}</span></span>
        <span class="fe-c"><strong class="fe-b">{d.get('hora_consulta') or ''}</strong></span>
        <span class="fe-c"><span class="fe-v">{d.get('ponto_exibir') or ''}</span></span>
      </div>
      <div class="fe-l2">
        <span class="fe-l2-tel"><strong class="fe-lab">TEL</strong> <span class="fe-v">{d.get('tel') or ''}</span></span>
        <span class="fe-l2-rua"><strong class="fe-lab">RUA:</strong> <span class="fe-v">{d.get('rua_completa') or ''}</span></span>
        <span class="fe-l2-trat"><span class="fe-v">{d.get('tratamento') or ''}</span></span>
      </div>
      <div class="fe-l3">
        <span class="fe-l3-at"><strong class="fe-lab">ATENDENTE</strong> <strong class="fe-b">{d.get('atendente') or ''}</strong></span>
        <span class="fe-l3-ac">
          <span><strong class="fe-lab">NOME AC:</strong> <strong class="fe-b">{d.get('ac_nome_exibir') or ''}</strong></span>
          <span><strong class="fe-lab">IDADE AC:</strong> <strong class="fe-b">{d.get('ac_idade_exibir') or ''}</strong></span>
          <span><strong class="fe-lab">TEL AC:</strong> <strong class="fe-b">{d.get('ac_tel_exibir') or ''}</strong></span>
        </span>
      </div>
    </div>
    """


def css_folha_espelho():
    """CSS fiel a AJUSTES/DoJeitoQuePreciso.jpg — A4 paisagem, 10/página."""
    cols = '1.15fr 0.55fr 0.7fr 1.55fr 1.7fr 0.4fr 0.3fr 0.75fr 0.7fr'
    return f"""
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 10px;
    font-family: Arial, Helvetica, sans-serif;
    color: #000; background: #d0d0d0; font-size: 10px;
  }}
  .toolbar {{
    max-width: 297mm; margin: 0 auto 10px;
    display: flex; gap: 8px; flex-wrap: wrap; align-items: center;
  }}
  .toolbar a, .toolbar button {{
    border: 0; border-radius: 6px; padding: 9px 14px; cursor: pointer;
    font-size: 13px; text-decoration: none; color: #fff;
  }}
  .btn-print {{ background: #2e7d32; }}
  .btn-back {{ background: #546e7a; }}
  .toolbar .info {{ font-size: 12.5px; color: #222; }}

  .fe-pagina {{
    max-width: 297mm; margin: 0 auto 12px; background: #fff;
    padding: 5mm 5mm 4mm;
    display: flex; flex-direction: column;
  }}
  .fe-topo {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 16px;
    border-bottom: 1px solid #000;
    padding-bottom: 2px;
    margin-bottom: 3px;
  }}
  .fe-titulo {{
    margin: 0;
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 0.02em;
    text-transform: uppercase;
    flex: 1 1 auto;
    text-align: left;
  }}
  .fe-topo-data {{
    font-weight: 700;
    font-size: 12px;
    text-transform: uppercase;
    white-space: nowrap;
    flex: 0 0 auto;
    text-align: right;
  }}
  .fe-cab {{
    display: grid;
    grid-template-columns: {cols};
    gap: 2px 4px;
    font-weight: 700;
    text-transform: uppercase;
    font-size: 9px;
    border-bottom: 1px solid #000;
    padding-bottom: 2px;
    margin-bottom: 1px;
  }}
  .fe-registros {{ flex: 1 1 auto; }}
  .fe-bloco {{
    border-bottom: 1px solid #000;
    padding: 2px 0 3px;
    page-break-inside: avoid;
    break-inside: avoid;
  }}
  .fe-l1 {{
    display: grid;
    grid-template-columns: {cols};
    gap: 2px 4px;
    align-items: start;
  }}
  .fe-mot {{
    white-space: nowrap;
    overflow: hidden;
  }}
  .fe-mot .fe-b {{
    white-space: nowrap;
  }}
  .fe-l2 {{
    display: grid;
    grid-template-columns: {cols};
    gap: 2px 4px;
    margin-top: 1px;
    align-items: baseline;
  }}
  .fe-l2-tel {{ grid-column: 1 / 4; }}
  .fe-l2-rua {{ grid-column: 4 / 6; }}
  .fe-l2-trat {{ grid-column: 6 / 10; }}
  .fe-l3 {{
    display: grid;
    grid-template-columns: {cols};
    gap: 2px 4px;
    margin-top: 1px;
    align-items: baseline;
  }}
  .fe-l3-at {{ grid-column: 1 / 4; }}
  .fe-l3-ac {{
    grid-column: 5 / 10;
    display: flex;
    flex-wrap: wrap;
    gap: 2px 14px;
    align-items: baseline;
  }}
  .fe-lab {{
    font-weight: 700 !important;
    text-transform: uppercase;
    font-size: 9px;
  }}
  .fe-v {{
    font-weight: 400 !important;
    text-transform: uppercase;
    font-size: 10px;
    word-break: break-word;
  }}
  .fe-b {{
    font-weight: 700 !important;
    text-transform: uppercase;
    font-size: 10px;
    word-break: break-word;
  }}
  .fe-rodape {{
    margin-top: 4px;
    padding-top: 3px;
    border-top: 1px solid #000;
    font-size: 9px;
    color: #222;
    display: flex;
    justify-content: space-between;
    gap: 12px;
  }}
  .fe-rodape-dir {{ white-space: nowrap; }}
  .fe-vazio {{
    text-align: center; padding: 40px 16px; color: #444;
    background: #fff; max-width: 297mm; margin: 0 auto;
  }}

  @media print {{
    body {{ background: #fff; padding: 0; margin: 0; }}
    .toolbar, .no-print {{ display: none !important; }}
    .fe-pagina {{
      max-width: none; margin: 0; padding: 0;
      page-break-after: always;
      break-after: page;
    }}
    .fe-pagina:last-child {{
      page-break-after: auto;
      break-after: auto;
    }}
    @page {{ size: A4 landscape; margin: 6mm 5mm; }}
    .fe-bloco {{ page-break-inside: avoid; break-inside: avoid; }}
  }}
"""


def _html_cabecalho_folha_espelho(data_br, dia_semana):
    data_txt = ''
    if data_br:
        data_txt = f'DATA {data_br}'
        if dia_semana:
            data_txt += f'  {dia_semana}'
    return f"""
    <div class="fe-topo">
      <h1 class="fe-titulo">LISTA DE CONTROLE DE PACIENTES</h1>
      <div class="fe-topo-data">{data_txt}</div>
    </div>
    {_html_cabecalho_colunas_folha_espelho()}
    """


def _html_rodape_folha_espelho(data_extenso, pagina_atual, total_paginas):
    from html import escape
    meta = escape(data_extenso or '')
    return f"""
    <footer class="fe-rodape">
      <span>{meta}</span>
      <span>Página {pagina_atual} de {total_paginas}</span>
      <span class="fe-rodape-dir">HORARIO <span class="fe-horario-impressao">--:--:--</span></span>
    </footer>
    """


def gerar_html_impressao_agendamentos(
    agendamentos_lista, filtros, pagina_ini, pagina_fim, per_page, href_voltar=None
):
    """
    Folha Espelho oficial (AJUSTES/DoJeitoQuePreciso.jpg).
    10 registros por página; grade de colunas; 3 linhas por registro.
    """
    try:
        from flask import url_for, has_request_context
        if not href_voltar:
            href_voltar = (
                url_for('agendamentos') if has_request_context() else '/transporte/agendamentos'
            )
    except Exception:
        href_voltar = href_voltar or '/transporte/agendamentos'

    elegiveis = [a for a in agendamentos_lista if agendamento_elegivel_folha_espelho(a)[0]]
    resumo = resumo_filtros_agendamentos(filtros)
    if pagina_ini != pagina_fim:
        resumo += f' · Páginas: {pagina_ini}–{pagina_fim}'

    qtd = len(elegiveis)
    data_ref = data_referencia_folha_espelho(elegiveis)
    data_br, dia_semana, data_extenso = formatar_data_lista_controle(data_ref)

    if not elegiveis:
        corpo = """
        <div class="fe-vazio">
          <h2>Folha Espelho indisponível</h2>
          <p>Nenhum agendamento com motorista e veículo programados nesta seleção.</p>
          <p>Conclua a programação (Programar) e tente novamente.</p>
        </div>"""
    else:
        por_pagina = FOLHA_ESPELHO_REGISTROS_POR_PAGINA
        total_paginas = max(1, (qtd + por_pagina - 1) // por_pagina)
        paginas_html = []
        for i in range(total_paginas):
            fatia = elegiveis[i * por_pagina:(i + 1) * por_pagina]
            blocos = ''.join(
                _html_bloco_folha_espelho(montar_dados_folha_espelho(a)) for a in fatia
            )
            paginas_html.append(f"""
        <section class="fe-pagina">
          {_html_cabecalho_folha_espelho(data_br, dia_semana)}
          <div class="fe-registros">{blocos}</div>
          {_html_rodape_folha_espelho(data_extenso, i + 1, total_paginas)}
        </section>""")
        corpo = '\n'.join(paginas_html)

    rotulo_voltar = 'Voltar'
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Folha Espelho — {qtd} registro(s)</title>
<style>{css_folha_espelho()}</style>
</head>
<body>
  <div class="toolbar no-print">
    <button class="btn-print" type="button" onclick="window.print()">Imprimir Folha Espelho (A4 paisagem)</button>
    <a class="btn-back" href="{href_voltar}">{rotulo_voltar}</a>
    <span class="info">{qtd} programado(s) · 10/página · {resumo}</span>
  </div>
  {corpo}
  <script>
  (function () {{
    function pad(n) {{ return String(n).padStart(2, '0'); }}
    function atualizarHorarioImpressao() {{
      var agora = new Date();
      var txt = pad(agora.getHours()) + ':' + pad(agora.getMinutes()) + ':' + pad(agora.getSeconds());
      document.querySelectorAll('.fe-horario-impressao').forEach(function (el) {{
        el.textContent = txt;
      }});
    }}
    atualizarHorarioImpressao();
    window.addEventListener('beforeprint', atualizarHorarioImpressao);
    setInterval(atualizarHorarioImpressao, 15000);
  }})();
  </script>
</body>
</html>"""


def gerar_html_impressao_pacientes(pacientes_lista, filtros):
    from html import escape

    resumo = ' · '.join(
        f'{k}: {v}' for k, v in filtros.items() if v
    ) or 'Todos os pacientes ativos (conforme filtros)'

    cabecalhos = ('Nome', 'Idade', 'CPF', 'Tel Cel', 'Tel Resi', 'Condição', 'Nascimento', 'Endereço', 'Ponto de Embarque')

    def linha(p):
        cel, res = telefones_paciente_form(p)
        condicao = formatar_condicao_paciente_exibir(p)
        idade_txt = formatar_idade_exibir(p.data_nascimento) if p.data_nascimento else '—'
        nasc = p.data_nascimento.strftime('%d/%m/%Y') if p.data_nascimento else '—'
        ponto = ponto_embarque_do_paciente(p) or '—'
        return f'''
        <tr>
            <td>{escape(p.nome)}</td>
            <td>{escape(idade_txt)}</td>
            <td>{escape(p.cpf)}</td>
            <td>{escape(cel or '—')}</td>
            <td>{escape(res or '—')}</td>
            <td>{escape(condicao)}</td>
            <td>{nasc}</td>
            <td>{escape(p.endereco or '—')}</td>
            <td>{escape(ponto)}</td>
        </tr>
        '''

    paginas = gerar_folhas_tabela(pacientes_lista, 20, 'Pacientes — Transporte', resumo, cabecalhos, linha)
    return montar_shell_impressao('Impressão — Pacientes', 'pacientes', paginas)


def gerar_html_impressao_acompanhantes(acompanhantes_lista, filtros):
    from html import escape

    resumo = ' · '.join(
        f'{k}: {v}' for k, v in filtros.items() if v
    ) or 'Todos os acompanhantes ativos (conforme filtros)'

    cabecalhos = (
        'Parentesco', 'Acompanhante', 'Idade', 'Paciente', 'Idade Pac.', 'RG', 'Telefone'
    )

    def linha(ac):
        pac = ac.paciente
        idade_ac = formatar_idade_exibir(ac.data_nascimento) if ac.data_nascimento else '—'
        idade_pac = (
            formatar_idade_exibir(pac.data_nascimento)
            if pac and pac.data_nascimento else '—'
        )
        pac_nome = pac.nome if pac else '—'
        return f'''
        <tr>
            <td>{escape(ac.parentesco or '—')}</td>
            <td>{escape(ac.nome or '—')}</td>
            <td>{escape(idade_ac)}</td>
            <td>{escape(pac_nome)}</td>
            <td>{escape(idade_pac)}</td>
            <td>{escape(format_rg(ac.rg) if ac.rg else '—')}</td>
            <td>{escape(ac.telefone or '—')}</td>
        </tr>
        '''

    paginas = gerar_folhas_tabela(
        acompanhantes_lista, 22, 'Acompanhantes — Transporte', resumo, cabecalhos, linha
    )
    return montar_shell_impressao('Impressão — Acompanhantes', 'acompanhantes', paginas)


def gerar_html_impressao_motoristas(motoristas_lista, filtros):
    from html import escape

    resumo = ' · '.join(
        f'{k}: {v}' for k, v in filtros.items() if v
    ) or 'Todos os motoristas (conforme filtros)'

    cabecalhos = ('Nome', 'CPF', 'CNH', 'Categoria', 'Telefone', 'Status', 'Venc. CNH')

    def linha(m):
        return f'''
        <tr>
            <td>{escape(m.nome)}</td>
            <td>{escape(m.cpf)}</td>
            <td>{escape(m.cnh)}</td>
            <td>{escape(m.categoria_cnh)}</td>
            <td>{escape(m.telefone)}</td>
            <td>{escape(m.status.title())}</td>
            <td>{m.vencimento_cnh.strftime('%d/%m/%Y')}</td>
        </tr>
        '''

    paginas = gerar_folhas_tabela(motoristas_lista, 20, 'Motoristas — Transporte', resumo, cabecalhos, linha)
    return montar_shell_impressao('Impressão — Motoristas', 'motoristas', paginas)


def gerar_html_impressao_veiculos(veiculos_lista, filtros):
    from html import escape

    resumo = ' · '.join(
        f'{k}: {v}' for k, v in filtros.items() if v
    ) or 'Todos os veículos ativos (conforme filtros)'

    cabecalhos = ('Placa/Frota', 'Marca', 'Modelo', 'Ano', 'Cor', 'Tipo', 'Capacidade', 'PCD')

    def linha(v):
        return f'''
        <tr>
            <td>{escape(v.placa)}</td>
            <td>{escape(v.marca)}</td>
            <td>{escape(v.modelo)}</td>
            <td>{v.ano}</td>
            <td>{escape(v.cor or '—')}</td>
            <td>{escape(v.tipo.replace('_', ' ').title())}</td>
            <td>{v.capacidade or '—'}</td>
            <td>{'Sim' if v.adaptado else 'Não'}</td>
        </tr>
        '''

    paginas = gerar_folhas_tabela(veiculos_lista, 20, 'Veículos — Frota', resumo, cabecalhos, linha)
    return montar_shell_impressao('Impressão — Veículos', 'veiculos', paginas)


def html_paleta_cores(input_id='cor'):
    """Paleta de cores clicável para cadastro de veículos."""
    cores = (
        ('Branco', '#FFFFFF'), ('Prata', '#C0C0C0'), ('Cinza', '#9E9E9E'), ('Preto', '#212121'),
        ('Vermelho', '#D32F2F'), ('Vinho', '#880E4F'), ('Laranja', '#F57C00'), ('Amarelo', '#FBC02D'),
        ('Verde', '#388E3C'), ('Azul', '#1976D2'), ('Azul Escuro', '#0D47A1'), ('Bege', '#D7CCC8'),
        ('Marrom', '#6D4C41'), ('Roxo', '#7B1FA2'), ('Rosa', '#EC407A'),
    )
    botoes = ''
    for nome, hex_cor in cores:
        borda = '1px solid #ccc' if nome == 'Branco' else '1px solid transparent'
        botoes += (
            f'<button type="button" class="cor-swatch" data-cor="{nome}" title="{nome}" '
            f'style="width:28px;height:28px;border-radius:50%;border:{borda};'
            f'background:{hex_cor};cursor:pointer;padding:0;"></button>'
        )
    return f'''
    <div class="form-group">
        <label for="{input_id}">Cor</label>
        <input type="text" id="{input_id}" name="{input_id}" placeholder="Clique na cor ou digite" maxlength="30">
        <div id="paleta_{input_id}" style="display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;">{botoes}</div>
        <small style="color:var(--gray-color);">Clique em uma cor da paleta ou digite manualmente.</small>
    </div>
    '''


def script_paleta_cores(input_id='cor'):
    return f'''
    <script>
    (function() {{
        const input = document.getElementById('{input_id}');
        document.querySelectorAll('#paleta_{input_id} .cor-swatch').forEach(function(btn) {{
            btn.addEventListener('click', function() {{
                input.value = btn.getAttribute('data-cor');
                document.querySelectorAll('#paleta_{input_id} .cor-swatch').forEach(function(b) {{
                    b.style.outline = 'none';
                }});
                btn.style.outline = '2px solid var(--primary-color)';
            }});
        }});
    }})();
    </script>
    '''


def inferir_capacidade_passageiros(marca, modelo, tipo=None):
    """Estima capacidade de passageiros conforme marca/modelo do veículo."""
    texto = f'{marca or ""} {modelo or ""}'.upper()
    regras = (
        (('MICRO', 'VOLARE', 'RODOVIAR', 'ONIBUS', 'ÔNIBUS', 'BUS', 'THUNDER', 'PARADISO'), 26),
        (('SPRINTER', 'DUCATO', 'MASTER', 'HIACE', 'H1', 'JUMPY', 'EXPERT', 'BOXER', 'VITO', 'TRANSIT'), 15),
        (('KOMBI', 'MULTIVAN', 'ZAFIRA', 'SPACEFOX', 'DOBLO', 'SPIN'), 8),
        (('AMBUL', 'UTI'), 4),
        (('FIORINO', 'SAVEIRO', 'STRADA', 'TORO', 'RANGER', 'S10', 'HILUX', 'AMAROK', 'FURG'), 3),
        (('SUV', 'PAJERO', 'SW4', 'CAPTIVA', 'CRETA', 'TRACKER', 'RENEGADE'), 7),
    )
    for chaves, capacidade in regras:
        if any(chave in texto for chave in chaves):
            return capacidade
    fallback = {'ambulancia': 4, 'van': 15, 'micro_onibus': 26, 'carro': 5}
    if tipo and tipo in fallback:
        return fallback[tipo]
    return 5


def gerar_filtros_agendamentos(filtros, total, exibidos, per_page):
    """Painel completo de filtros para agendamentos."""
    from html import escape
    from flask import url_for
    from urllib.parse import urlencode

    def sel_opt(valor, atual):
        return 'selected' if valor == atual else ''

    def esc(val):
        return escape(val or '')

    f = filtros
    tem_filtro = filtros_agendamentos_ativos(f)

    def pill_href(**params):
        merged = {k: v for k, v in {**f, **params}.items() if v}
        merged.pop('page', None)
        if 'periodo' in params and params['periodo'] == '':
            merged.pop('periodo', None)
        if 'status' in params and params['status'] == '':
            merged.pop('status', None)
        return url_for('agendamentos') + '?' + urlencode(merged)

    def pill_class(ativo):
        base = 'padding: 0.4rem 0.85rem; border-radius: 999px; text-decoration: none; font-size: 0.875rem; margin-right: 0.5rem; display: inline-block;'
        if ativo:
            return base + ' background: var(--primary-color); color: white;'
        return base + ' background: var(--color-95); color: var(--text-color); border: 1px solid var(--border-color);'

    hidden_per_page = f'<input type="hidden" name="per_page" value="{per_page}">'

    return f'''
    <div class="filters" style="background: var(--color-95); padding: 1.25rem; border-radius: 0.5rem; margin-bottom: 1rem; border: 1px solid var(--border-color);">
        <form method="GET" action="{url_for('agendamentos')}">
            {hidden_per_page}
            <div class="filters-row" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 0.75rem; align-items: end;">
                <div class="form-group">
                    <label style="display:block; font-size:0.85rem; margin-bottom:0.25rem;">ID</label>
                    <input type="text" name="id" value="{esc(f.get('id'))}" placeholder="Ex: 16983" inputmode="numeric"
                           style="width:100%; padding:0.55rem 0.65rem; border:1px solid var(--border-color); border-radius:6px;">
                </div>
                <div class="form-group">
                    <label style="display:block; font-size:0.85rem; margin-bottom:0.25rem;">Busca geral</label>
                    <input type="text" name="q" value="{esc(f.get('q'))}" placeholder="Paciente, destino, motorista..."
                           style="width:100%; padding:0.55rem 0.65rem; border:1px solid var(--border-color); border-radius:6px;">
                </div>
                <div class="form-group">
                    <label style="display:block; font-size:0.85rem; margin-bottom:0.25rem;">Nome do paciente</label>
                    <input type="text" name="paciente" value="{esc(f.get('paciente'))}" placeholder="Ex: CRISTINA"
                           style="width:100%; padding:0.55rem 0.65rem; border:1px solid var(--border-color); border-radius:6px;">
                </div>
                <div class="form-group">
                    <label style="display:block; font-size:0.85rem; margin-bottom:0.25rem;">Data específica</label>
                    <input type="text" class="data-br" name="data" value="{esc(format_data_br(f.get('data')))}"
                           placeholder="dd/mm/aaaa" maxlength="10" inputmode="numeric"
                           style="width:100%; padding:0.55rem 0.65rem; border:1px solid var(--border-color); border-radius:6px;">
                </div>
                <div class="form-group">
                    <label style="display:block; font-size:0.85rem; margin-bottom:0.25rem;">Período de</label>
                    <input type="text" class="data-br" name="data_inicio" value="{esc(format_data_br(f.get('data_inicio')))}"
                           placeholder="dd/mm/aaaa" maxlength="10" inputmode="numeric"
                           style="width:100%; padding:0.55rem 0.65rem; border:1px solid var(--border-color); border-radius:6px;">
                </div>
                <div class="form-group">
                    <label style="display:block; font-size:0.85rem; margin-bottom:0.25rem;">Período até</label>
                    <input type="text" class="data-br" name="data_fim" value="{esc(format_data_br(f.get('data_fim')))}"
                           placeholder="dd/mm/aaaa" maxlength="10" inputmode="numeric"
                           style="width:100%; padding:0.55rem 0.65rem; border:1px solid var(--border-color); border-radius:6px;">
                </div>
                <div class="form-group">
                    <label style="display:block; font-size:0.85rem; margin-bottom:0.25rem;">Status</label>
                    <select name="status" style="width:100%; padding:0.55rem 0.65rem; border:1px solid var(--border-color); border-radius:6px;">
                        <option value="">Ativos (oculta cancelados)</option>
                        <option value="agendado" {sel_opt('agendado', f.get('status'))}>Agendado</option>
                        <option value="confirmado" {sel_opt('confirmado', f.get('status'))}>Confirmado</option>
                        <option value="em_andamento" {sel_opt('em_andamento', f.get('status'))}>Em andamento</option>
                        <option value="concluido" {sel_opt('concluido', f.get('status'))}>Concluído</option>
                        <option value="cancelado" {sel_opt('cancelado', f.get('status'))}>Cancelado</option>
                    </select>
                </div>
                <div class="form-group">
                    <label style="display:block; font-size:0.85rem; margin-bottom:0.25rem;">Motorista</label>
                    <input type="text" name="motorista" value="{esc(f.get('motorista'))}" placeholder="Nome ou ID (ex: 1)"
                           style="width:100%; padding:0.55rem 0.65rem; border:1px solid var(--border-color); border-radius:6px;">
                </div>
                <div class="form-group">
                    <label style="display:block; font-size:0.85rem; margin-bottom:0.25rem;">Frota</label>
                    <input type="text" name="frota" value="{esc(f.get('frota'))}" placeholder="Nome, número ou ID"
                           style="width:100%; padding:0.55rem 0.65rem; border:1px solid var(--border-color); border-radius:6px;">
                </div>
                <div class="form-group">
                    <label style="display:block; font-size:0.85rem; margin-bottom:0.25rem;">Destino</label>
                    <input type="text" name="destino" value="{esc(f.get('destino'))}" placeholder="Ex: CAMPINAS"
                           style="width:100%; padding:0.55rem 0.65rem; border:1px solid var(--border-color); border-radius:6px;">
                </div>
                <div class="form-group">
                    <label style="display:block; font-size:0.85rem; margin-bottom:0.25rem;">Origem</label>
                    <input type="text" name="origem" value="{esc(f.get('origem'))}" placeholder="Ex: Cosmópolis"
                           style="width:100%; padding:0.55rem 0.65rem; border:1px solid var(--border-color); border-radius:6px;">
                </div>
                <div class="form-group">
                    <label style="display:block; font-size:0.85rem; margin-bottom:0.25rem;">Especialidade</label>
                    <input type="text" name="tipo_transporte" value="{esc(f.get('tipo_transporte'))}" placeholder="Ex: Cardiologia"
                           style="width:100%; padding:0.55rem 0.65rem; border:1px solid var(--border-color); border-radius:6px;">
                </div>
                <div class="form-group">
                    <label style="display:block; font-size:0.85rem; margin-bottom:0.25rem;">Placa</label>
                    <input type="text" name="placa" value="{esc(f.get('placa'))}" placeholder="Ex: F00313"
                           style="width:100%; padding:0.55rem 0.65rem; border:1px solid var(--border-color); border-radius:6px;">
                </div>
                <div class="form-group" style="display:flex; gap:0.5rem; flex-wrap:wrap;">
                    <button type="submit" class="btn">🔍 Filtrar</button>
                    {'<a href="' + url_for('agendamentos') + '" class="btn" style="background:var(--gray-color);">Limpar filtros</a>' if tem_filtro else ''}
                </div>
            </div>
        </form>
        <div style="margin-top: 0.85rem; display: flex; flex-wrap: wrap; align-items: center; gap: 0.35rem;">
            <span style="font-size:0.85rem; color:var(--gray-color); margin-right:0.25rem;">Atalhos:</span>
            <a href="{url_for('agendamentos')}" style="{pill_class(not f.get('periodo') and not f.get('status') and not tem_filtro)}">Ativos</a>
            <a href="{pill_href(periodo='hoje', status='')}" style="{pill_class(f.get('periodo') == 'hoje')}">Hoje</a>
            <a href="{pill_href(periodo='amanha', status='')}" style="{pill_class(f.get('periodo') == 'amanha')}">Amanhã</a>
            <a href="{pill_href(periodo='semana', status='')}" style="{pill_class(f.get('periodo') == 'semana')}">Esta semana</a>
            <a href="{pill_href(periodo='mes', status='')}" style="{pill_class(f.get('periodo') == 'mes')}">Este mês</a>
            <a href="{pill_href(status='agendado', periodo='')}" style="{pill_class(f.get('status') == 'agendado' and not f.get('periodo'))}">Agendados</a>
            <a href="{pill_href(status='cancelado', periodo='')}" style="{pill_class(f.get('status') == 'cancelado' and not f.get('periodo'))}">Cancelados</a>
        </div>
        <p style="margin: 0.85rem 0 0; color: var(--gray-color); font-size: 0.95rem;">
            Exibindo <strong style="color: var(--primary-color);">{format_numero_br(exibidos)}</strong>
            de <strong>{format_numero_br(total)}</strong> registros
            {' (filtros ativos)' if tem_filtro else ' (50 mais recentes por página)'}
            · Use <strong>Folha Espelho</strong> abaixo para imprimir a programação deste recorte
        </p>
    </div>
    '''


def obter_filtros_pacientes_request():
    from flask import request
    return {
        'id': (request.args.get('id') or '').strip(),
        'q': request.args.get('q', '').strip(),
        'nome': request.args.get('nome', '').strip(),
        'cpf': request.args.get('cpf', '').strip(),
        'cep': request.args.get('cep', '').strip(),
        'telefone': request.args.get('telefone', '').strip(),
        'cadastro_de': request.args.get('cadastro_de', '').strip(),
        'cadastro_ate': request.args.get('cadastro_ate', '').strip(),
        'faixa_etaria': request.args.get('faixa_etaria', '').strip(),
        'ordenar': request.args.get('ordenar', '').strip(),
    }


def montar_query_pacientes(filtros):
    query = Paciente.query.filter_by(ativo=True)
    id_raw = (filtros.get('id') or '').strip()
    if id_raw.isdigit():
        query = query.filter(Paciente.id == int(id_raw))
    if filtros.get('nome'):
        query = query.filter(Paciente.nome.ilike(f"%{filtros['nome']}%"))
    if filtros.get('cpf'):
        query = query.filter(Paciente.cpf.ilike(f"%{filtros['cpf']}%"))
    if filtros.get('cep'):
        cep_raw = (filtros.get('cep') or '').strip()
        cep_digitos = re.sub(r'\D', '', cep_raw)
        if cep_digitos:
            from sqlalchemy import or_
            clausulas_cep = [
                Paciente.cep.ilike(f'%{cep_raw}%'),
                Paciente.cep.ilike(f'%{cep_digitos}%'),
            ]
            if len(cep_digitos) >= 8:
                mascarado = f'{cep_digitos[:5]}-{cep_digitos[5:8]}'
                clausulas_cep.append(Paciente.cep.ilike(f'%{mascarado}%'))
            query = query.filter(or_(*clausulas_cep))
    if filtros.get('telefone'):
        from sqlalchemy import or_
        termo = f"%{filtros['telefone']}%"
        query = query.filter(
            or_(
                Paciente.tel_cel.ilike(termo),
                Paciente.tel_res.ilike(termo),
                Paciente.telefone.ilike(termo),
            )
        )
    if filtros.get('bairro'):
        query = query.filter(Paciente.bairro.ilike(f"%{filtros['bairro']}%"))
    condicao = (filtros.get('condicao') or '').strip()
    if condicao == 'especial':
        query = query.filter(Paciente.condicao_especial.is_(True))
    elif condicao == 'necessita':
        query = query.filter(Paciente.condicao_paciente == CONDICAO_NECESSITA_ACOMPANHANTE)
    d_ini = parse_data_br(filtros.get('cadastro_de'))
    d_fim = parse_data_br(filtros.get('cadastro_ate'))
    if d_ini:
        query = query.filter(Paciente.data_cadastro >= datetime.combine(d_ini, datetime.min.time()))
    if d_fim:
        query = query.filter(Paciente.data_cadastro <= datetime.combine(d_fim, datetime.max.time()))
    if filtros.get('q'):
        from sqlalchemy import or_
        termo = (filtros['q'] or '').strip()
        if termo.isdigit():
            # Busca geral só com dígitos = ID do paciente (use o campo CPF/CEP para documento)
            query = query.filter(Paciente.id == int(termo))
        else:
            like = f'%{termo}%'
            clausulas = [
                Paciente.nome.ilike(like),
                Paciente.cpf.ilike(like),
                Paciente.cep.ilike(like),
                Paciente.tel_cel.ilike(like),
                Paciente.tel_res.ilike(like),
                Paciente.telefone.ilike(like),
                Paciente.endereco.ilike(like),
                Paciente.bairro.ilike(like),
            ]
            cep_q = re.sub(r'\D', '', termo)
            if len(cep_q) >= 5:
                clausulas.append(Paciente.cep.ilike(f'%{cep_q}%'))
            query = query.filter(or_(*clausulas))
    query = aplicar_filtro_faixa_etaria(query, Paciente.data_nascimento, filtros.get('faixa_etaria'))
    return query


def html_select_faixa_etaria(valor_atual='', name='faixa_etaria'):
    """Select de faixa etária para filtros de listagem."""
    from html import escape
    opcoes = [
        ('', 'Todas'),
        ('0-5', '0–5 anos'),
        ('6-12', '6–12 anos'),
        ('13-17', '13–17 anos'),
        ('18-59', '18–59 anos'),
        ('60+', '60+ anos'),
    ]
    atual = valor_atual or ''
    opts = []
    for v, rot in opcoes:
        sel = ' selected' if v == atual else ''
        opts.append(f'<option value="{escape(v)}"{sel}>{escape(rot)}</option>')
    return f'''
    <div class="form-group">
        <label style="display:block; font-size:0.85rem; margin-bottom:0.25rem;">Faixa etária</label>
        <select name="{escape(name)}" style="width:100%; padding:0.55rem 0.65rem; border:1px solid var(--border-color); border-radius:6px;">
            {''.join(opts)}
        </select>
    </div>
    '''


def gerar_filtros_pacientes(filtros, total, exibidos, per_page=50):
    from flask import url_for
    f = filtros
    tem_filtro = filtros_tem_valores(f, ignorar={'ordenar'})
    return f'''
    <div class="filters" style="{estilo_painel_filtros()}">
        <form method="GET" action="{url_for('pacientes')}">
            <input type="hidden" name="per_page" value="{per_page}">
            <input type="hidden" name="ordenar" value="{f.get('ordenar') or ''}">
            <div class="filters-row" style="{estilo_grid_filtros()}">
                {input_texto_filtro('id', f.get('id'), 'ID', 'Ex: 5')}
                {input_texto_filtro('q', f.get('q'), 'Busca geral', 'Nome, CPF, CEP, telefone...')}
                {input_texto_filtro('nome', f.get('nome'), 'Nome', 'Ex: CRISTINA')}
                {input_texto_filtro('cpf', f.get('cpf'), 'CPF', 'Ex: 123.456.789-00')}
                {input_texto_filtro('cep', f.get('cep'), 'CEP', 'Ex: 13152-336')}
                {input_texto_filtro('telefone', f.get('telefone'), 'Telefone', 'Celular ou fixo')}
                {input_data_br('cadastro_de', f.get('cadastro_de'), 'Cadastro de')}
                {input_data_br('cadastro_ate', f.get('cadastro_ate'), 'Cadastro até')}
                {html_select_faixa_etaria(f.get('faixa_etaria'))}
                {botoes_filtro('pacientes', tem_filtro)}
            </div>
        </form>
        {contador_filtros(exibidos, total, tem_filtro)}
    </div>
    '''


def obter_filtros_paciente_vinculo_request():
    """Filtros comuns para localizar paciente ao vincular acompanhante / agendar."""
    from flask import request
    return {
        'id': (request.args.get('id') or '').strip(),
        'q': request.args.get('q', '').strip(),
        'nome': request.args.get('nome', '').strip(),
        'cpf': request.args.get('cpf', '').strip(),
        'telefone': request.args.get('telefone', '').strip(),
        'bairro': request.args.get('bairro', '').strip(),
        'condicao': request.args.get('condicao', '').strip(),
        'acompanhante': request.args.get('acompanhante', '').strip(),
    }


def montar_query_paciente_vinculo(filtros):
    """Query de pacientes ativos para select de vínculo (acompanhante / agendamento)."""
    from sqlalchemy import exists

    query = montar_query_pacientes(filtros)
    acomp = (filtros.get('acompanhante') or '').strip()
    if acomp in ('com', 'sem'):
        tem_acomp = exists().where(
            Acompanhante.paciente_id == Paciente.id,
            Acompanhante.ativo.is_(True),
        )
        if acomp == 'com':
            query = query.filter(tem_acomp)
        else:
            query = query.filter(~tem_acomp)
    return query


def gerar_filtros_paciente_vinculo(filtros, total, exibidos, endpoint='acompanhantes_novo', endpoint_kwargs=None):
    """Painel de filtros no padrão STP para select de paciente existente."""
    from flask import url_for

    f = filtros
    tem_filtro = filtros_tem_valores(f)
    kw = endpoint_kwargs or {}

    def sel_opt(valor, atual):
        return 'selected' if valor == atual else ''

    def url_ep(**extra):
        params = dict(kw)
        params.update(extra)
        return url_for(endpoint, **params)

    limpar = (
        f'<a href="{url_ep()}" class="btn" style="background:var(--gray-color);">Limpar filtros</a>'
        if tem_filtro else ''
    )
    botoes = f'''
    <div class="form-group" style="display:flex; gap:0.5rem; flex-wrap:wrap;">
        <button type="submit" class="btn">🔍 Filtrar</button>
        {limpar}
    </div>
    '''

    return f'''
    <div class="filters" style="{estilo_painel_filtros()}">
        <form method="GET" action="{url_ep()}" id="form-filtro-paciente-vinculo">
            <div class="filters-row" style="{estilo_grid_filtros()}">
                {input_texto_filtro('id', f.get('id'), 'ID', 'Ex: 5')}
                {input_texto_filtro('q', f.get('q'), 'Busca geral', 'Nome, CPF, telefone, ID...')}
                {input_texto_filtro('nome', f.get('nome'), 'Nome', 'Ex: JOSÉ ANTONIO')}
                {input_texto_filtro('cpf', f.get('cpf'), 'CPF', 'Ex: 567.276.268-98')}
                {input_texto_filtro('telefone', f.get('telefone'), 'Telefone', 'Celular ou fixo')}
                {input_texto_filtro('bairro', f.get('bairro'), 'Bairro', 'Ex: CENTRO')}
                <div class="form-group">
                    <label style="display:block; font-size:0.85rem; margin-bottom:0.25rem;">Condição</label>
                    <select name="condicao" style="width:100%; padding:0.55rem 0.65rem; border:1px solid var(--border-color); border-radius:6px;">
                        <option value="">Todas</option>
                        <option value="especial" {sel_opt('especial', f.get('condicao'))}>Com condição especial</option>
                        <option value="necessita" {sel_opt('necessita', f.get('condicao'))}>Necessita acompanhante</option>
                    </select>
                </div>
                <div class="form-group">
                    <label style="display:block; font-size:0.85rem; margin-bottom:0.25rem;">Acompanhante na ficha</label>
                    <select name="acompanhante" style="width:100%; padding:0.55rem 0.65rem; border:1px solid var(--border-color); border-radius:6px;">
                        <option value="">Todos</option>
                        <option value="sem" {sel_opt('sem', f.get('acompanhante'))}>Sem acompanhante</option>
                        <option value="com" {sel_opt('com', f.get('acompanhante'))}>Já tem acompanhante</option>
                    </select>
                </div>
                {botoes}
            </div>
        </form>
        <div style="margin-top:0.85rem; display:flex; flex-wrap:wrap; gap:0.5rem;">
            <a href="{url_ep(condicao='necessita')}" class="btn btn-small"
               style="padding:0.35rem 0.75rem; font-size:0.875rem;">★ Necessita acompanhante</a>
            <a href="{url_ep(acompanhante='sem')}" class="btn btn-small"
               style="padding:0.35rem 0.75rem; font-size:0.875rem; background:var(--gray-color);">Sem acompanhante</a>
            <a href="{url_ep(acompanhante='com')}" class="btn btn-small"
               style="padding:0.35rem 0.75rem; font-size:0.875rem; background:var(--gray-color);">Já tem acompanhante</a>
            <a href="{url_ep(condicao='especial')}" class="btn btn-small"
               style="padding:0.35rem 0.75rem; font-size:0.875rem; background:var(--gray-color);">Condição especial</a>
        </div>
        {contador_filtros(exibidos, total, tem_filtro)}
        {'' if tem_filtro else '<p style="margin:0.5rem 0 0; color:var(--gray-color); font-size:0.9rem;">Use os filtros para localizar o paciente entre os cadastrados (somente ativos). Com muitos registros, a lista só aparece após filtrar.</p>'}
    </div>
    '''


def obter_filtros_acompanhantes_request():
    from flask import request
    return {
        'q': request.args.get('q', '').strip(),
        'nome': request.args.get('nome', '').strip(),
        'paciente': request.args.get('paciente', '').strip(),
        'parentesco': request.args.get('parentesco', '').strip(),
        'rg': request.args.get('rg', '').strip(),
        'telefone': request.args.get('telefone', '').strip(),
        'bairro': request.args.get('bairro', '').strip(),
        'condicao': request.args.get('condicao', '').strip(),
        'paciente_id': (request.args.get('paciente_id') or '').strip(),
        'faixa_etaria': request.args.get('faixa_etaria', '').strip(),
        'ordenar': request.args.get('ordenar', '').strip(),
    }


def montar_query_acompanhantes(filtros):
    from sqlalchemy import or_

    query = (
        Acompanhante.query
        .join(Paciente, Acompanhante.paciente_id == Paciente.id)
        .filter(Acompanhante.ativo.is_(True), Paciente.ativo.is_(True))
    )
    if filtros.get('paciente_id'):
        try:
            query = query.filter(Acompanhante.paciente_id == int(filtros['paciente_id']))
        except (TypeError, ValueError):
            pass
    if filtros.get('nome'):
        query = query.filter(Acompanhante.nome.ilike(f"%{filtros['nome']}%"))
    if filtros.get('paciente'):
        query = query.filter(Paciente.nome.ilike(f"%{filtros['paciente']}%"))
    if filtros.get('parentesco'):
        query = query.filter(Acompanhante.parentesco.ilike(f"%{filtros['parentesco']}%"))
    if filtros.get('rg'):
        termo_rg = sanitizar_rg(filtros['rg']) or filtros['rg']
        query = query.filter(Acompanhante.rg.ilike(f"%{termo_rg}%"))
    if filtros.get('telefone'):
        query = query.filter(Acompanhante.telefone.ilike(f"%{filtros['telefone']}%"))
    if filtros.get('bairro'):
        query = query.filter(Paciente.bairro.ilike(f"%{filtros['bairro']}%"))
    condicao = (filtros.get('condicao') or '').strip()
    if condicao == 'necessita':
        query = query.filter(Paciente.condicao_paciente == CONDICAO_NECESSITA_ACOMPANHANTE)
    elif condicao == 'especial':
        query = query.filter(Paciente.condicao_especial.is_(True))
    elif condicao == 'nao_informado':
        query = query.filter(Acompanhante.nome == NOME_ACOMPANHANTE_NAO_INFORMADO)
    if filtros.get('q'):
        like = f"%{filtros['q']}%"
        query = query.filter(
            or_(
                Acompanhante.nome.ilike(like),
                Paciente.nome.ilike(like),
                Acompanhante.rg.ilike(like),
                Acompanhante.telefone.ilike(like),
                Acompanhante.parentesco.ilike(like),
                Paciente.bairro.ilike(like),
                Paciente.cpf.ilike(like),
            )
        )
    return query


def gerar_filtros_acompanhantes(filtros, total, exibidos, per_page=50):
    from html import escape
    from flask import url_for

    f = filtros
    tem_filtro = filtros_tem_valores(f)

    def sel_opt(valor, atual):
        return 'selected' if valor == atual else ''

    return f'''
    <div class="filters" style="{estilo_painel_filtros()}">
        <form method="GET" action="{url_for('acompanhantes')}">
            <input type="hidden" name="per_page" value="{per_page}">
            <div class="filters-row" style="{estilo_grid_filtros()}">
                {input_texto_filtro('q', f.get('q'), 'Busca geral', 'Acompanhante, paciente, RG...')}
                {input_texto_filtro('nome', f.get('nome'), 'Acompanhante', 'Ex: SANDRA')}
                {input_texto_filtro('paciente', f.get('paciente'), 'Paciente', 'Nome do paciente')}
                {input_texto_filtro('parentesco', f.get('parentesco'), 'Parentesco', 'Ex: Mãe')}
                <div class="form-group">
                    <label style="display:block; font-size:0.85rem; margin-bottom:0.25rem;">RG</label>
                    <input type="text" name="rg" value="{escape(f.get('rg') or '')}" placeholder="{escape(RG_PLACEHOLDER)}"
                           data-mask="rg" maxlength="12" inputmode="text"
                           style="width:100%; padding:0.55rem 0.65rem; border:1px solid var(--border-color); border-radius:6px;">
                </div>
                {input_texto_filtro('telefone', f.get('telefone'), 'Telefone', '')}
                {input_texto_filtro('bairro', f.get('bairro'), 'Bairro do paciente', 'Ex: CENTRO')}
                <div class="form-group">
                    <label style="display:block; font-size:0.85rem; margin-bottom:0.25rem;">Condição / tipo</label>
                    <select name="condicao" style="width:100%; padding:0.55rem 0.65rem; border:1px solid var(--border-color); border-radius:6px;">
                        <option value="">Todos</option>
                        <option value="necessita" {sel_opt('necessita', f.get('condicao'))}>Paciente necessita acompanhante</option>
                        <option value="especial" {sel_opt('especial', f.get('condicao'))}>Paciente com condição especial</option>
                        <option value="nao_informado" {sel_opt('nao_informado', f.get('condicao'))}>Nome não informado</option>
                    </select>
                </div>
                {botoes_filtro('acompanhantes', tem_filtro)}
            </div>
        </form>
        <div style="margin-top:0.85rem; display:flex; flex-wrap:wrap; gap:0.5rem;">
            <a href="{url_for('acompanhantes', condicao='necessita')}" class="btn btn-small"
               style="padding:0.35rem 0.75rem; font-size:0.875rem;">★ Necessita acompanhante</a>
            <a href="{url_for('acompanhantes', condicao='nao_informado')}" class="btn btn-small"
               style="padding:0.35rem 0.75rem; font-size:0.875rem; background:var(--gray-color);">Nome não informado</a>
            <a href="{url_for('acompanhantes', condicao='especial')}" class="btn btn-small"
               style="padding:0.35rem 0.75rem; font-size:0.875rem; background:var(--gray-color);">Condição especial</a>
        </div>
        {contador_filtros(exibidos, total, tem_filtro)}
    </div>
    '''


def obter_filtros_usuarios_request():
    from flask import request
    return {
        'q': request.args.get('q', '').strip(),
        'nome': request.args.get('nome', '').strip(),
        'username': request.args.get('username', '').strip(),
        'tipo': request.args.get('tipo', '').strip(),
        'status': request.args.get('status', '').strip(),
    }


def montar_query_usuarios(filtros):
    query = Usuario.query
    if filtros.get('nome'):
        query = query.filter(Usuario.nome_completo.ilike(f"%{filtros['nome']}%"))
    if filtros.get('username'):
        query = query.filter(Usuario.username.ilike(f"%{filtros['username']}%"))
    if filtros.get('tipo'):
        query = query.filter(Usuario.tipo_usuario == filtros['tipo'])
    if filtros.get('status') == 'ativo':
        query = query.filter(Usuario.ativo.is_(True))
    elif filtros.get('status') == 'inativo':
        query = query.filter(Usuario.ativo.is_(False))
    if filtros.get('q'):
        query = aplicar_filtro_busca(
            query, filtros['q'], Usuario.nome_completo, Usuario.username, Usuario.email, Usuario.tipo_usuario
        )
    return query


def gerar_filtros_usuarios(filtros, total, exibidos, per_page=50):
    from flask import url_for

    f = filtros
    tem_filtro = filtros_tem_valores(f)

    def sel_opt(valor, atual):
        return 'selected' if valor == atual else ''

    return f'''
    <div class="filters" style="{estilo_painel_filtros()}">
        <form method="GET" action="{url_for('usuarios')}">
            <input type="hidden" name="per_page" value="{per_page}">
            <div class="filters-row" style="{estilo_grid_filtros()}">
                {input_texto_filtro('q', f.get('q'), 'Busca geral', 'Nome, username, e-mail...')}
                {input_texto_filtro('nome', f.get('nome'), 'Nome', '')}
                {input_texto_filtro('username', f.get('username'), 'Username', '')}
                <div class="form-group">
                    <label style="display:block; font-size:0.85rem; margin-bottom:0.25rem;">Tipo</label>
                    <select name="tipo" style="width:100%; padding:0.55rem 0.65rem; border:1px solid var(--border-color); border-radius:6px;">
                        <option value="">Todos</option>
                        <option value="administrador" {sel_opt('administrador', f.get('tipo'))}>Administrador</option>
                        <option value="supervisor" {sel_opt('supervisor', f.get('tipo'))}>Supervisor</option>
                        <option value="contador" {sel_opt('contador', f.get('tipo'))}>Contador</option>
                        <option value="atendente" {sel_opt('atendente', f.get('tipo'))}>Atendente</option>
                    </select>
                </div>
                <div class="form-group">
                    <label style="display:block; font-size:0.85rem; margin-bottom:0.25rem;">Status</label>
                    <select name="status" style="width:100%; padding:0.55rem 0.65rem; border:1px solid var(--border-color); border-radius:6px;">
                        <option value="">Todos</option>
                        <option value="ativo" {sel_opt('ativo', f.get('status'))}>Ativo</option>
                        <option value="inativo" {sel_opt('inativo', f.get('status'))}>Inativo</option>
                    </select>
                </div>
                {botoes_filtro('usuarios', tem_filtro)}
            </div>
        </form>
        <div style="margin-top:0.85rem; display:flex; flex-wrap:wrap; gap:0.5rem;">
            <a href="{url_for('usuarios', status='ativo')}" class="btn btn-small"
               style="padding:0.35rem 0.75rem; font-size:0.875rem;">Ativos</a>
            <a href="{url_for('usuarios', status='inativo')}" class="btn btn-small"
               style="padding:0.35rem 0.75rem; font-size:0.875rem; background:var(--gray-color);">Inativos</a>
        </div>
        {contador_filtros(exibidos, total, tem_filtro)}
    </div>
    '''


def obter_filtros_motoristas_request():
    from flask import request
    return {
        'id': (request.args.get('id') or '').strip(),
        'q': request.args.get('q', '').strip(),
        'nome': request.args.get('nome', '').strip(),
        'cpf': request.args.get('cpf', '').strip(),
        'cnh': request.args.get('cnh', '').strip(),
        'telefone': request.args.get('telefone', '').strip(),
        'status': request.args.get('status', '').strip(),
        'cnh_vence_de': request.args.get('cnh_vence_de', '').strip(),
        'cnh_vence_ate': request.args.get('cnh_vence_ate', '').strip(),
    }


def montar_query_motoristas(filtros):
    from sqlalchemy import or_
    query = Motorista.query
    id_raw = (filtros.get('id') or '').strip()
    if id_raw.isdigit():
        query = query.filter(Motorista.id == int(id_raw))
    if filtros.get('nome'):
        query = query.filter(Motorista.nome.ilike(f"%{filtros['nome']}%"))
    if filtros.get('cpf'):
        query = query.filter(Motorista.cpf.ilike(f"%{filtros['cpf']}%"))
    if filtros.get('cnh'):
        query = query.filter(Motorista.cnh.ilike(f"%{filtros['cnh']}%"))
    if filtros.get('telefone'):
        query = query.filter(Motorista.telefone.ilike(f"%{filtros['telefone']}%"))
    if filtros.get('status'):
        query = query.filter(Motorista.status == filtros['status'])
    d_ini = parse_data_br(filtros.get('cnh_vence_de'))
    d_fim = parse_data_br(filtros.get('cnh_vence_ate'))
    if d_ini:
        query = query.filter(Motorista.vencimento_cnh >= d_ini)
    if d_fim:
        query = query.filter(Motorista.vencimento_cnh <= d_fim)
    if filtros.get('q'):
        termo = (filtros['q'] or '').strip()
        if termo.isdigit():
            query = query.filter(Motorista.id == int(termo))
        else:
            like = f'%{termo}%'
            query = query.filter(
                or_(
                    Motorista.nome.ilike(like),
                    Motorista.cpf.ilike(like),
                    Motorista.cnh.ilike(like),
                    Motorista.status.ilike(like),
                    Motorista.telefone.ilike(like),
                )
            )
    return query


def gerar_filtros_motoristas(filtros, total, exibidos, per_page=50):
    from html import escape
    from flask import url_for
    f = filtros
    tem_filtro = filtros_tem_valores(f)

    def sel_opt(valor, atual):
        return 'selected' if valor == atual else ''

    return f'''
    <div class="filters" style="{estilo_painel_filtros()}">
        <form method="GET" action="{url_for('motoristas')}">
            <input type="hidden" name="per_page" value="{per_page}">
            <div class="filters-row" style="{estilo_grid_filtros()}">
                {input_texto_filtro('id', f.get('id'), 'ID', 'Ex: 1')}
                {input_texto_filtro('q', f.get('q'), 'Busca geral', 'Nome, CPF, CNH ou ID...')}
                {input_texto_filtro('nome', f.get('nome'), 'Nome', 'Ex: MARCIO')}
                {input_texto_filtro('cpf', f.get('cpf'), 'CPF', '')}
                {input_texto_filtro('cnh', f.get('cnh'), 'CNH', '')}
                {input_texto_filtro('telefone', f.get('telefone'), 'Telefone', '')}
                <div class="form-group">
                    <label style="display:block; font-size:0.85rem; margin-bottom:0.25rem;">Status</label>
                    <select name="status" style="width:100%; padding:0.55rem 0.65rem; border:1px solid var(--border-color); border-radius:6px;">
                        <option value="">Todos</option>
                        <option value="ativo" {sel_opt('ativo', f.get('status'))}>Ativo</option>
                        <option value="inativo" {sel_opt('inativo', f.get('status'))}>Inativo</option>
                        <option value="ferias" {sel_opt('ferias', f.get('status'))}>Férias</option>
                        <option value="licenca" {sel_opt('licenca', f.get('status'))}>Licença</option>
                    </select>
                </div>
                {input_data_br('cnh_vence_de', f.get('cnh_vence_de'), 'CNH vence de')}
                {input_data_br('cnh_vence_ate', f.get('cnh_vence_ate'), 'CNH vence até')}
                {botoes_filtro('motoristas', tem_filtro)}
            </div>
        </form>
        <div style="margin-top:0.85rem;">
            <a href="{url_for('motoristas', status='ativo')}" class="btn btn-small" style="padding:0.35rem 0.75rem; font-size:0.875rem; margin-right:0.5rem;">Ativos</a>
            <a href="{url_for('motoristas', status='inativo')}" class="btn btn-small" style="padding:0.35rem 0.75rem; font-size:0.875rem; background:var(--gray-color);">Inativos</a>
        </div>
        {contador_filtros(exibidos, total, tem_filtro)}
    </div>
    '''


def obter_filtros_veiculos_request():
    from flask import request
    return {
        'q': request.args.get('q', '').strip(),
        'placa': request.args.get('placa', '').strip(),
        'marca': request.args.get('marca', '').strip(),
        'modelo': request.args.get('modelo', '').strip(),
        'tipo': request.args.get('tipo', '').strip(),
        'adaptado': request.args.get('adaptado', '').strip(),
        'cadastro_de': request.args.get('cadastro_de', '').strip(),
        'cadastro_ate': request.args.get('cadastro_ate', '').strip(),
    }


def montar_query_veiculos(filtros):
    query = Veiculo.query.filter_by(ativo=True)
    if filtros.get('placa'):
        query = query.filter(Veiculo.placa.ilike(f"%{filtros['placa']}%"))
    if filtros.get('marca'):
        query = query.filter(Veiculo.marca.ilike(f"%{filtros['marca']}%"))
    if filtros.get('modelo'):
        query = query.filter(Veiculo.modelo.ilike(f"%{filtros['modelo']}%"))
    if filtros.get('tipo'):
        query = query.filter(Veiculo.tipo.ilike(f"%{filtros['tipo']}%"))
    if filtros.get('adaptado') == 'sim':
        query = query.filter(Veiculo.adaptado.is_(True))
    elif filtros.get('adaptado') == 'nao':
        query = query.filter(Veiculo.adaptado.is_(False))
    d_ini = parse_data_br(filtros.get('cadastro_de'))
    d_fim = parse_data_br(filtros.get('cadastro_ate'))
    if d_ini:
        query = query.filter(Veiculo.data_cadastro >= datetime.combine(d_ini, datetime.min.time()))
    if d_fim:
        query = query.filter(Veiculo.data_cadastro <= datetime.combine(d_fim, datetime.max.time()))
    if filtros.get('q'):
        query = aplicar_filtro_busca(
            query, filtros['q'], Veiculo.placa, Veiculo.marca, Veiculo.modelo, Veiculo.tipo, Veiculo.observacoes
        )
    return query


def gerar_filtros_veiculos(filtros, total, exibidos, per_page=50):
    from flask import url_for
    f = filtros
    tem_filtro = filtros_tem_valores(f)

    def sel_opt(valor, atual):
        return 'selected' if valor == atual else ''

    return f'''
    <div class="filters" style="{estilo_painel_filtros()}">
        <form method="GET" action="{url_for('veiculos')}">
            <input type="hidden" name="aba" value="veiculo">
            <input type="hidden" name="per_page" value="{per_page}">
            <div class="filters-row" style="{estilo_grid_filtros()}">
                {input_texto_filtro('q', f.get('q'), 'Busca geral', 'Placa, marca, modelo...')}
                {input_texto_filtro('placa', f.get('placa'), 'Placa', 'Ex: F00299')}
                {input_texto_filtro('marca', f.get('marca'), 'Marca', '')}
                {input_texto_filtro('modelo', f.get('modelo'), 'Modelo', 'Ex: Frota 299')}
                {input_texto_filtro('tipo', f.get('tipo'), 'Tipo', 'Ex: van')}
                <div class="form-group">
                    <label style="display:block; font-size:0.85rem; margin-bottom:0.25rem;">Adaptado PCD</label>
                    <select name="adaptado" style="width:100%; padding:0.55rem 0.65rem; border:1px solid var(--border-color); border-radius:6px;">
                        <option value="">Todos</option>
                        <option value="sim" {sel_opt('sim', f.get('adaptado'))}>Sim</option>
                        <option value="nao" {sel_opt('nao', f.get('adaptado'))}>Não</option>
                    </select>
                </div>
                {input_data_br('cadastro_de', f.get('cadastro_de'), 'Cadastro de')}
                {input_data_br('cadastro_ate', f.get('cadastro_ate'), 'Cadastro até')}
                {botoes_filtro('veiculos', tem_filtro, limpar_params={'aba': 'veiculo'})}
            </div>
        </form>
        {contador_filtros(exibidos, total, tem_filtro)}
    </div>
    '''


def obter_filtros_frotas_request():
    from flask import request
    return {
        'id': (request.args.get('id') or '').strip(),
        'q': request.args.get('q', '').strip(),
        'numero': request.args.get('numero', '').strip(),
        'nome': request.args.get('nome', '').strip(),
        'cadastro_de': request.args.get('cadastro_de', '').strip(),
        'cadastro_ate': request.args.get('cadastro_ate', '').strip(),
    }


def montar_query_frotas(filtros):
    from sqlalchemy import or_
    query = Frota.query.filter_by(ativo=True)
    id_raw = (filtros.get('id') or '').strip()
    if id_raw.isdigit():
        query = query.filter(Frota.id == int(id_raw))
    if filtros.get('numero'):
        query = query.filter(Frota.numero.ilike(f"%{filtros['numero']}%"))
    if filtros.get('nome'):
        query = query.filter(Frota.nome.ilike(f"%{filtros['nome']}%"))
    d_ini = parse_data_br(filtros.get('cadastro_de'))
    d_fim = parse_data_br(filtros.get('cadastro_ate'))
    if d_ini:
        query = query.filter(Frota.data_cadastro >= datetime.combine(d_ini, datetime.min.time()))
    if d_fim:
        query = query.filter(Frota.data_cadastro <= datetime.combine(d_fim, datetime.max.time()))
    if filtros.get('q'):
        termo = (filtros['q'] or '').strip()
        if termo.isdigit():
            query = query.filter(Frota.id == int(termo))
        else:
            query = query.filter(
                or_(
                    Frota.numero.ilike(f'%{termo}%'),
                    Frota.nome.ilike(f'%{termo}%'),
                    Frota.observacoes.ilike(f'%{termo}%'),
                )
            )
    return query


def gerar_filtros_frotas(filtros, total, exibidos, per_page=50):
    from flask import url_for
    f = filtros
    tem_filtro = filtros_tem_valores(f)
    return f'''
    <div class="filters" style="{estilo_painel_filtros()}">
        <form method="GET" action="{url_for('veiculos')}">
            <input type="hidden" name="aba" value="frota">
            <input type="hidden" name="per_page" value="{per_page}">
            <div class="filters-row" style="{estilo_grid_filtros()}">
                {input_texto_filtro('id', f.get('id'), 'ID', 'Ex: 3')}
                {input_texto_filtro('q', f.get('q'), 'Busca geral', 'Número, nome ou ID...')}
                {input_texto_filtro('numero', f.get('numero'), 'Número', 'Ex: F00267')}
                {input_texto_filtro('nome', f.get('nome'), 'Nome', 'Ex: NI Frota 267')}
                {input_data_br('cadastro_de', f.get('cadastro_de'), 'Cadastro de')}
                {input_data_br('cadastro_ate', f.get('cadastro_ate'), 'Cadastro até')}
                {botoes_filtro('veiculos', tem_filtro, limpar_params={'aba': 'frota'})}
            </div>
        </form>
        {contador_filtros(exibidos, total, tem_filtro)}
    </div>
    '''


def html_abas_listagem_veiculos(aba_ativa='veiculo'):
    """Abas Veículos | Frota na listagem (mesmo padrão do cadastro)."""
    from flask import url_for
    aba = (aba_ativa or 'veiculo').strip().lower()
    if aba not in ('veiculo', 'frota'):
        aba = 'veiculo'
    cls_v = 'active' if aba == 'veiculo' else ''
    cls_f = 'active' if aba == 'frota' else ''
    return f'''
    <div class="tabs" role="tablist" aria-label="Listagem de veículos e frotas" style="margin-bottom:1.25rem;">
      <a href="{url_for('veiculos', aba='veiculo')}" class="tab {cls_v}" role="tab"
         aria-selected="{'true' if aba == 'veiculo' else 'false'}">🚗 Veículos</a>
      <a href="{url_for('veiculos', aba='frota')}" class="tab {cls_f}" role="tab"
         aria-selected="{'true' if aba == 'frota' else 'false'}">🚌 Frota</a>
    </div>
    '''


def qtd_veiculos_da_frota(frota_id):
    return Veiculo.query.filter_by(frota_id=frota_id, ativo=True).count()


def svg_van_sutil():
    """Van decorativa sutil para a sidebar."""
    return '''
    <svg class="stp-van-art" viewBox="0 0 240 90" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
        <path d="M18 52h148a10 10 0 0 1 10 10v8H18v-18z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>
        <path d="M166 52h34l14 18v10h-48V52z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>
        <rect x="28" y="40" width="52" height="20" rx="4" stroke="currentColor" stroke-width="1.2" opacity="0.55"/>
        <rect x="88" y="40" width="52" height="20" rx="4" stroke="currentColor" stroke-width="1.2" opacity="0.55"/>
        <circle cx="52" cy="74" r="11" stroke="currentColor" stroke-width="1.5"/>
        <circle cx="52" cy="74" r="4" fill="currentColor" opacity="0.35"/>
        <circle cx="168" cy="74" r="11" stroke="currentColor" stroke-width="1.5"/>
        <circle cx="168" cy="74" r="4" fill="currentColor" opacity="0.35"/>
        <path d="M186 58h8M190 54v8" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" opacity="0.5"/>
        <path d="M8 62h10M6 68h14" stroke="currentColor" stroke-width="1" stroke-linecap="round" opacity="0.25"/>
    </svg>
    '''


def gerar_sidebar_nav(ativo=""):
    """Sidebar vertical moderna com grupos de menu."""
    from flask import url_for

    def item(route, label, icon, key=None):
        key = key or route
        cls = 'stp-nav-link active' if ativo == key else 'stp-nav-link'
        return (
            f'<a href="{url_for(route)}" class="{cls}">'
            f'<span class="stp-nav-icon">{icon}</span><span>{label}</span></a>'
        )

    ag_cls = 'stp-nav-link stp-nav-destaque active' if ativo == 'agendamentos' else 'stp-nav-link stp-nav-destaque'
    ag_link = (
        f'<a href="{url_for("agendamentos")}" class="{ag_cls}">'
        f'<span class="stp-nav-icon">📅</span><span>Agendamentos</span></a>'
    )

    admin_extra = ''
    if current_user.is_authenticated:
        if hasattr(current_user, 'can_view_finances') and current_user.can_view_finances():
            admin_extra += item('faturamento', 'Faturamento', '💰', 'faturamento')
        if hasattr(current_user, 'tipo_usuario') and current_user.tipo_usuario == 'administrador':
            admin_extra += item('usuarios', 'Usuários', '👤', 'usuarios')
            admin_extra += item('whatsapp_dashboard', 'WhatsApp', '📱', 'whatsapp')

    sistema_section = f'''
        <div class="stp-nav-section">Sistema</div>
        {item('backup_dashboard', 'Backup', '💾', 'backup')}
        {admin_extra}
    '''

    return f'''
    <aside class="stp-sidebar no-print" id="stpSidebar">
        <div class="stp-sidebar-brand">
            <div class="stp-brand-icon">🚑</div>
            <div>
                <strong>STP</strong>
                <span>Transporte de Pacientes</span>
            </div>
        </div>

        <nav class="stp-sidebar-nav">
            {ag_link}

            <div class="stp-nav-section">Operação</div>
            {item('dashboard', 'Início', '🏠', 'dashboard')}

            <div class="stp-nav-section">Cadastros</div>
            {item('pacientes', 'Pacientes', '👥', 'pacientes')}
            {item('acompanhantes', 'Acompanhantes', '🧑‍🤝‍🧑', 'acompanhantes')}
            {item('motoristas', 'Motoristas', '👨‍💼', 'motoristas')}
            {item('veiculos', 'Veículos', '🚐', 'veiculos')}

            <div class="stp-nav-section">Frota</div>
            {item('uso_veiculos', 'Controle de Uso', '📋', 'uso_veiculos')}
            {item('combustivel_dashboard', 'Combustível', '⛽', 'combustivel')}

            <div class="stp-nav-section">Relatórios</div>
            {item('relatorios', 'Relatórios', '📊', 'relatorios')}

            {sistema_section}
        </nav>

        <div class="stp-sidebar-footer">
            {svg_van_sutil()}
        </div>
    </aside>
    '''


def css_app_shell():
    """Estilos compartilhados do layout com sidebar (desktop + mobile)."""
    return '''
            .stp-app { display: flex; min-height: 100vh; min-height: 100dvh; }
            .stp-sidebar {
                width: 250px; min-width: 250px; background: linear-gradient(180deg, #ffffff 0%, #eefaf9 100%);
                border-right: 1px solid var(--border-color); display: flex; flex-direction: column;
                position: fixed; top: 0; left: 0; bottom: 0; z-index: 200; overflow: hidden;
                padding-top: env(safe-area-inset-top, 0px);
                padding-bottom: env(safe-area-inset-bottom, 0px);
            }
            .stp-sidebar-brand {
                display: flex; align-items: center; gap: 0.75rem; padding: 1.25rem 1rem 1rem;
                border-bottom: 1px solid var(--border-color); background: rgba(255,255,255,0.85);
            }
            .stp-brand-icon {
                width: 42px; height: 42px; border-radius: 10px;
                background: linear-gradient(135deg, var(--primary-color), var(--primary-dark));
                display: flex; align-items: center; justify-content: center; font-size: 1.25rem;
                box-shadow: 0 4px 12px rgba(67, 172, 167, 0.25); flex-shrink: 0;
            }
            .stp-sidebar-brand strong { display: block; color: var(--primary-dark); font-size: 1.05rem; line-height: 1.2; }
            .stp-sidebar-brand span { display: block; color: var(--gray-color); font-size: 0.72rem; line-height: 1.3; }
            .stp-sidebar-nav { flex: 1; overflow-y: auto; -webkit-overflow-scrolling: touch; padding: 0.75rem 0.65rem 1rem; }
            .stp-nav-section {
                font-size: 0.68rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
                color: var(--gray-color); padding: 0.85rem 0.75rem 0.35rem; opacity: 0.85;
            }
            .stp-nav-link {
                display: flex; align-items: center; gap: 0.65rem;
                min-height: 44px; padding: 0.55rem 0.75rem; margin-bottom: 0.15rem;
                border-radius: 0.5rem; color: var(--text-color); text-decoration: none; font-size: 0.9rem;
                transition: all 0.2s ease; box-sizing: border-box;
            }
            .stp-nav-link:hover { background: var(--color-95); color: var(--primary-dark); }
            .stp-nav-link.active {
                background: linear-gradient(90deg, rgba(79,201,196,0.18), rgba(79,201,196,0.06));
                color: var(--primary-dark); font-weight: 600; border-left: 3px solid var(--primary-color);
                padding-left: calc(0.75rem - 3px);
            }
            .stp-nav-destaque {
                margin-bottom: 0.5rem; background: rgba(79, 201, 196, 0.08);
                border: 1px solid rgba(79, 201, 196, 0.25);
            }
            .stp-nav-destaque.active {
                background: linear-gradient(90deg, var(--primary-color), var(--primary-dark));
                color: #fff; border-left: none; padding-left: 0.75rem; box-shadow: 0 4px 12px rgba(67,172,167,0.3);
            }
            .stp-nav-icon { width: 1.35rem; text-align: center; flex-shrink: 0; font-size: 1rem; }
            .stp-sidebar-footer {
                padding: 0.5rem 1rem 1rem; color: var(--primary-color); pointer-events: none;
            }
            .stp-van-art { width: 100%; height: auto; opacity: 0.14; display: block; }
            .stp-main {
                flex: 1; margin-left: 250px; min-height: 100vh; min-height: 100dvh;
                display: flex; flex-direction: column; min-width: 0; width: 100%;
            }
            .stp-topbar {
                background: linear-gradient(135deg, var(--primary-color), var(--primary-dark));
                color: var(--color-100);
                padding: max(0.85rem, env(safe-area-inset-top, 0px)) max(1.5rem, env(safe-area-inset-right, 0px)) 0.85rem max(1.5rem, env(safe-area-inset-left, 0px));
                display: flex; justify-content: space-between; align-items: center; gap: 0.75rem; flex-wrap: wrap;
                box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            }
            .stp-topbar h1 {
                margin: 0; font-weight: 600;
                font-size: clamp(0.95rem, 2.8vw, 1.05rem);
                line-height: 1.25; min-width: 0;
            }
            .stp-topbar-user {
                display: flex; align-items: center; gap: 0.75rem;
                font-size: 0.9rem; min-width: 0; flex-wrap: wrap; justify-content: flex-end;
            }
            .stp-menu-toggle {
                display: none; background: rgba(255,255,255,0.2); border: none; color: #fff;
                width: 44px; height: 44px; min-width: 44px; min-height: 44px;
                border-radius: 0.5rem; cursor: pointer; font-size: 1.25rem;
                align-items: center; justify-content: center; padding: 0; flex-shrink: 0;
            }
            .stp-menu-toggle:focus-visible { outline: 2px solid #fff; outline-offset: 2px; }
            .stp-content {
                flex: 1; padding: 1.5rem 2rem;
                padding-bottom: max(1.5rem, env(safe-area-inset-bottom, 0px));
                max-width: 100%; min-width: 0; box-sizing: border-box;
            }
            .stp-sidebar-overlay {
                display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.35); z-index: 150;
            }
            @media (max-width: 992px) {
                .stp-sidebar { transform: translateX(-100%); transition: transform 0.25s ease; width: min(280px, 86vw); min-width: 0; }
                .stp-sidebar.open { transform: translateX(0); box-shadow: 8px 0 24px rgba(0,0,0,0.18); }
                .stp-sidebar-overlay.open { display: block; }
                .stp-main { margin-left: 0; }
                .stp-menu-toggle { display: inline-flex; }
                .stp-content { padding: 1rem; padding-bottom: max(1rem, env(safe-area-inset-bottom, 0px)); }
                .stp-topbar { padding-left: max(0.85rem, env(safe-area-inset-left, 0px)); padding-right: max(0.85rem, env(safe-area-inset-right, 0px)); }
            }
            @media (max-width: 480px) {
                .stp-topbar-user > span { display: none; }
                .stp-content { padding: 0.75rem; }
            }
    '''


def gerar_layout_base(titulo, conteudo, ativo="", extra_head="", extra_scripts="", body_class=""):
    """Gera o layout base com sidebar vertical moderna."""
    nome_usuario = current_user.nome_completo if current_user.is_authenticated else ''
    sidebar = gerar_sidebar_nav(ativo)
    body_cls = f'stp-app-body {body_class}'.strip()

    return f'''
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
        <title>{titulo} - Sistema de Transporte</title>
        <link rel="icon" href="/static/img/favicon.ico" type="image/x-icon">
        <link rel="shortcut icon" href="/static/img/favicon.ico">
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@3.34.1/dist/tabler-icons.min.css">
        {extra_head}
        <style>
            :root {{
                --color-100: #ffffff;
                --color-95: #ebf9f9;
                --primary-color: #4fc9c4;
                --primary-dark: #43aca7;
                --primary-hover: #3c9b96;
                --secondary-color: #6d7a8c;
                --text-color: #3f485d;
                --border-color: #e5e5e5;
                --success-color: #79b24a;
                --warning-color: #f2823c;
                --danger-color: #e81d51;
                --info-color: #91ceff;
                --gray-color: #6d7a8c;
                --input-focus: #4fc9c4;
                --input-focus-shadow: rgba(79, 201, 196, 0.25);
                --bp-xs: 320px;
                --bp-sm: 480px;
                --bp-md: 768px;
                --bp-lg: 992px;
                --bp-xl: 1200px;
                --touch-min: 44px;
            }}
            *, *::before, *::after {{ box-sizing: border-box; }}
            html {{ -webkit-text-size-adjust: 100%; }}
            body.stp-app-body {{
                font-family: Arial, sans-serif; margin: 0; padding: 0; background: var(--color-95);
                color: var(--text-color); overflow-x: hidden; min-width: 0;
            }}
            {css_app_shell()}
            .container {{ padding: 0; max-width: 1400px; margin: 0 auto; width: 100%; min-width: 0; }}
            .page-header {{ margin-bottom: 1.5rem; }}
            .page-header h2 {{
                color: var(--primary-color); margin: 0 0 0.5rem 0;
                font-size: clamp(1.25rem, 4vw, 1.75rem); line-height: 1.25;
            }}
            .page-header p {{ color: var(--gray-color); margin: 0; font-size: clamp(0.875rem, 2.5vw, 1rem); }}
            .page-header .btn {{ margin-top: 0.35rem; }}
            .card {{
                background: var(--color-100); padding: clamp(1rem, 3vw, 2rem); border-radius: 1rem;
                box-shadow: 0 0.125rem 0.25rem rgba(0,0,0,0.075); border-left: 4px solid var(--primary-color);
                margin-bottom: 1rem; min-width: 0; overflow: hidden;
            }}
            .btn {{
                padding: 0.75rem 1.5rem; min-height: var(--touch-min); background: var(--primary-color);
                color: var(--color-100); border: none; border-radius: 0.5rem; cursor: pointer;
                text-decoration: none; display: inline-flex; align-items: center; justify-content: center;
                gap: 0.4rem; transition: background-color 0.2s ease; font-size: 1rem; line-height: 1.25;
                box-sizing: border-box;
            }}
            .btn:hover {{ background: var(--primary-dark); }}
            .btn:active {{ background: var(--primary-hover); }}
            .btn:disabled, .btn[aria-disabled="true"] {{ opacity: 0.65; cursor: not-allowed; pointer-events: none; }}
            .btn-secondary {{ background: var(--secondary-color); }}
            .btn-secondary:hover {{ background: var(--gray-color); }}
            .btn-success {{ background: var(--success-color); }}
            .btn-success:hover {{ background: #6a9d3e; }}
            .btn-warning {{ background: var(--warning-color); }}
            .btn-warning:hover {{ background: #e6762f; }}
            .logout {{
                background: var(--danger-color); color: var(--color-100); padding: 0.5rem 1rem;
                min-height: var(--touch-min); border: none; border-radius: 0.5rem; cursor: pointer;
                text-decoration: none; transition: background-color 0.3s ease; font-size: 0.875rem;
                display: inline-flex; align-items: center; justify-content: center;
            }}
            .logout:hover {{ background: #c81841; }}
            .coming-soon {{ text-align: center; padding: 4rem 2rem; }}
            .coming-soon .icon {{ font-size: 4rem; margin-bottom: 1rem; color: var(--primary-color); }}
            .coming-soon h3 {{ color: var(--text-color); margin-bottom: 1rem; }}
            .coming-soon p {{ color: var(--gray-color); }}
            .form-group {{ margin-bottom: 1rem; min-width: 0; }}
            .form-group label {{ display: block; margin-bottom: 0.5rem; color: var(--text-color); font-weight: 600; }}
            .form-group .field-hint, .form-group small {{ display: block; margin-top: 0.35rem; color: var(--gray-color); font-size: 0.875rem; }}
            .form-group .field-error {{ color: var(--danger-color); }}
            .form-group .field-success {{ color: var(--success-color); }}
            .form-group input, .form-group select, .form-group textarea {{
                width: 100%; max-width: 100%; padding: 0.75rem; min-height: var(--touch-min);
                border: 2px solid var(--border-color); border-radius: 0.5rem;
                font-size: 1rem; line-height: 1.5; box-sizing: border-box; background: var(--color-100); color: var(--text-color);
                transition: border-color 0.2s ease, box-shadow 0.2s ease, background-color 0.2s ease;
            }}
            .form-group textarea {{ min-height: 6rem; }}
            .form-group input:hover:not(:disabled):not([readonly]),
            .form-group select:hover:not(:disabled),
            .form-group textarea:hover:not(:disabled):not([readonly]) {{ border-color: var(--primary-dark); }}
            .form-group input:focus, .form-group select:focus, .form-group textarea:focus {{
                border-color: var(--input-focus); outline: none; box-shadow: 0 0 0 3px var(--input-focus-shadow);
            }}
            .form-group input:focus-visible, .form-group select:focus-visible, .form-group textarea:focus-visible,
            .btn:focus-visible, .password-toggle:focus-visible {{
                outline: 2px solid var(--primary-color); outline-offset: 2px;
            }}
            .form-group input.is-invalid, .form-group select.is-invalid, .form-group textarea.is-invalid {{
                border-color: var(--danger-color); box-shadow: 0 0 0 3px rgba(232, 29, 81, 0.15);
            }}
            .form-group input.is-valid, .form-group select.is-valid, .form-group textarea.is-valid {{
                border-color: var(--success-color); box-shadow: 0 0 0 3px rgba(121, 178, 74, 0.15);
            }}
            .form-group input:disabled, .form-group select:disabled, .form-group textarea:disabled {{
                background: #f3f4f6; color: var(--gray-color); cursor: not-allowed; opacity: 0.85;
            }}
            .form-group input[readonly], .form-group textarea[readonly] {{
                background: #f5f5f5; color: var(--text-color); cursor: default;
            }}
            .form-group textarea {{ min-height: 6rem; resize: vertical; }}
            .form-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; min-width: 0; }}
            .form-actions {{ display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: center; margin-top: 2rem; }}
            .form-section {{ background: var(--color-95); padding: 1.5rem; border-radius: 0.5rem; margin: 1rem 0; min-width: 0; }}
            .form-section h4 {{ color: var(--primary-color); margin: 0 0 1rem 0; }}
            .password-field {{ position: relative; }}
            .password-field input {{ padding-right: 2.75rem; }}
            .password-toggle {{
                position: absolute; right: 0.35rem; top: 50%; transform: translateY(-50%);
                width: var(--touch-min); height: var(--touch-min); border: none; background: transparent; color: var(--gray-color);
                cursor: pointer; border-radius: 0.35rem; display: inline-flex; align-items: center; justify-content: center;
                padding: 0;
            }}
            .password-toggle:hover {{ color: var(--primary-dark); background: rgba(79, 201, 196, 0.12); }}
            .password-toggle svg {{ width: 1.15rem; height: 1.15rem; display: block; pointer-events: none; }}
            .checkbox-row {{ display: flex; align-items: center; gap: 0.6rem; min-height: var(--touch-min); }}
            .checkbox-row input[type="checkbox"], .checkbox-row input[type="radio"] {{
                width: 1.25rem; height: 1.25rem; margin: 0; flex-shrink: 0; accent-color: var(--primary-color); cursor: pointer;
            }}
            .checkbox-row label {{ margin: 0; font-weight: 500; cursor: pointer; }}
            .required-mark {{ color: var(--danger-color); font-weight: 700; margin-left: 0.15rem; }}
            .breadcrumb {{ margin-bottom: 1rem; color: var(--gray-color); font-size: 0.9rem; word-break: break-word; }}
            .breadcrumb a {{ color: var(--primary-color); text-decoration: none; }}
            .breadcrumb a:hover {{ text-decoration: underline; }}
            .alert {{ padding: 0.75rem; margin-bottom: 1rem; border-radius: 0.5rem; word-break: break-word; }}
            .alert-error {{ background: rgba(232, 29, 81, 0.1); color: var(--danger-color); border: 1px solid var(--danger-color); }}
            .alert-success {{ background: rgba(121, 178, 74, 0.1); color: var(--success-color); border: 1px solid var(--success-color); }}
            .alert-warning {{ background: rgba(242, 130, 60, 0.1); color: var(--warning-color); border: 1px solid var(--warning-color); }}
            .tabs {{ display: flex; border-bottom: 2px solid var(--border-color); margin-bottom: 2rem; overflow-x: auto; -webkit-overflow-scrolling: touch; }}
            .tab {{
                padding: 0.85rem 1.25rem; min-height: var(--touch-min); background: transparent; border: none;
                cursor: pointer; color: var(--gray-color); font-weight: 600; transition: all 0.3s ease; white-space: nowrap;
                text-decoration: none; display: inline-flex; align-items: center;
            }}
            a.tab {{ color: var(--gray-color); }}
            .tab.active {{ color: var(--primary-color); border-bottom: 2px solid var(--primary-color); }}
            .tab:hover {{ color: var(--primary-color); }}
            .tab-content {{ display: none; }}
            .tab-content.active {{ display: block; }}
            .filters {{ background: var(--color-95); padding: clamp(1rem, 3vw, 1.5rem); border-radius: 0.5rem; margin-bottom: 1.5rem; min-width: 0; }}
            .filters-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 180px), 1fr)); gap: 1rem; align-items: end; }}
            .table-container {{ overflow-x: auto; -webkit-overflow-scrolling: touch; max-width: 100%; }}
            .report-table {{ width: 100%; border-collapse: collapse; margin-bottom: 2rem; }}
            .report-table th {{ background: var(--primary-color); color: var(--color-100); padding: 1rem; text-align: left; }}
            .report-table td {{ padding: 0.75rem; border-bottom: 1px solid var(--border-color); }}
            .report-table tr:hover {{ background: var(--color-95); }}
            .print-btn {{ background: var(--info-color); }}
            .print-btn:hover {{ background: #7bb8ff; }}
            .stp-tooltip {{ cursor: help; border-bottom: 1px dotted var(--gray-color); }}
            /* ⓘ discreto — cadastros */
            .stp-ajuda-title-row {{
                display: flex; align-items: center; gap: 0.35rem; flex-wrap: wrap;
            }}
            .stp-ajuda-title-row h2 {{ margin: 0; }}
            .stp-ajuda-btn {{
                width: 1.5rem; height: 1.5rem; padding: 0; border: none; background: transparent;
                color: #94a3b8; cursor: pointer; display: inline-flex; align-items: center;
                justify-content: center; border-radius: 50%; flex-shrink: 0;
            }}
            .stp-ajuda-btn i {{ font-size: 0.95rem; line-height: 1; pointer-events: none; }}
            .stp-ajuda-btn:hover {{ color: #0d6efd; background: rgba(13, 110, 253, 0.08); }}
            .stp-ajuda-btn[aria-expanded="true"] {{ color: #0d6efd; }}
            .stp-ajuda-painel {{
                margin: 0.5rem 0 0; padding: 0.75rem 0.9rem; border-radius: 0.4rem;
                background: #f8fafc; border: 1px solid #e2e8f0; max-width: 36rem;
                color: #475569; font-size: 0.88rem; line-height: 1.45;
            }}
            .stp-ajuda-painel[hidden] {{ display: none !important; }}
            /* Toolbar de ações (ícones) — listagens */
            .stp-acoes {{
                display: inline-flex; align-items: center; justify-content: flex-start;
                flex-wrap: wrap; gap: 0.5rem; white-space: normal;
            }}
            .stp-acao {{
                width: var(--touch-min); height: var(--touch-min); min-width: var(--touch-min); min-height: var(--touch-min);
                display: inline-flex; align-items: center; justify-content: center;
                border-radius: 0.45rem; border: 1px solid transparent;
                background: #f1f5f7; color: #445560; text-decoration: none;
                font-size: 1.05rem; line-height: 1; cursor: pointer;
                transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease,
                            box-shadow 0.15s ease, transform 0.12s ease;
                padding: 0; box-sizing: border-box; vertical-align: middle;
            }}
            .stp-acao i {{ pointer-events: none; font-size: 1.2rem; line-height: 1; }}
            .ti {{
                font-size: 1.15rem; line-height: 1; vertical-align: -0.125em;
                speak: never; font-style: normal; font-weight: normal;
                font-variant: normal; text-transform: none;
                -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale;
            }}
            .stp-acao:hover {{
                background: #e4eef2; color: #1f2d36;
                box-shadow: 0 1px 4px rgba(20,40,60,0.10); transform: translateY(-1px);
            }}
            .stp-acao:focus {{ outline: none; }}
            .stp-acao:focus-visible {{
                box-shadow: 0 0 0 3px rgba(79, 201, 196, 0.35);
                border-color: var(--primary-color);
            }}
            .stp-acao:active {{ transform: translateY(0); box-shadow: none; }}
            .stp-acao.is-disabled,
            .stp-acao:disabled {{
                opacity: 0.45; cursor: not-allowed;
                background: #eceff1; color: #8a969e; box-shadow: none; transform: none;
            }}
            .stp-acao.is-disabled:hover,
            .stp-acao:disabled:hover {{
                background: #eceff1; color: #8a969e; box-shadow: none; transform: none;
            }}
            .stp-acao--programar {{ background: rgba(33, 150, 243, 0.12); color: #1565c0; }}
            .stp-acao--programar:hover {{ background: rgba(33, 150, 243, 0.22); color: #0d47a1; }}
            .stp-acao--confirmar {{ background: rgba(121, 178, 74, 0.16); color: #3d7a1f; }}
            .stp-acao--confirmar:hover {{ background: rgba(121, 178, 74, 0.28); color: #2e5c16; }}
            .stp-acao--iniciar {{ background: rgba(33, 150, 243, 0.12); color: #1565c0; }}
            .stp-acao--iniciar:hover {{ background: rgba(33, 150, 243, 0.22); color: #0d47a1; }}
            .stp-acao--concluir {{ background: rgba(109, 122, 140, 0.14); color: #455066; }}
            .stp-acao--concluir:hover {{ background: rgba(109, 122, 140, 0.24); color: #2f3a4a; }}
            .stp-acao--cancelar {{ background: rgba(232, 29, 81, 0.10); color: #c2183a; }}
            .stp-acao--cancelar:hover {{ background: rgba(232, 29, 81, 0.18); color: #9e1430; }}
            .stp-acao--cartao {{ background: rgba(67, 172, 167, 0.18); color: #2a8f8a; }}
            .stp-acao--cartao:hover {{ background: rgba(67, 172, 167, 0.30); color: #1f6e6a; }}
            .stp-acao--cartao.is-disabled,
            .stp-acao--cartao.is-disabled:hover {{
                background: rgba(109, 122, 140, 0.10); color: #9aa3ad;
            }}
            .stp-acao--editar {{ background: rgba(242, 130, 60, 0.14); color: #c45f18; }}
            .stp-acao--editar:hover {{ background: rgba(242, 130, 60, 0.26); color: #9a4a12; }}
            .stp-acao--excluir {{ background: rgba(232, 29, 81, 0.10); color: #c2183a; }}
            .stp-acao--excluir:hover {{ background: rgba(232, 29, 81, 0.18); color: #9e1430; }}
            .stp-acao--ver {{ background: rgba(79, 201, 196, 0.14); color: #2a8f8a; }}
            .stp-acao--ver:hover {{ background: rgba(79, 201, 196, 0.26); color: #1f6e6a; }}
            .stp-acao--pagar {{ background: rgba(121, 178, 74, 0.16); color: #3d7a1f; }}
            .stp-acao--pagar:hover {{ background: rgba(121, 178, 74, 0.28); color: #2e5c16; }}
            .stp-acao--download {{ background: rgba(33, 150, 243, 0.12); color: #1565c0; }}
            .stp-acao--download:hover {{ background: rgba(33, 150, 243, 0.22); color: #0d47a1; }}
            /* Listagens: tabela desktop / cards mobile */
            .stp-list-desktop {{ display: block; }}
            .stp-list-mobile {{ display: none; }}
            .stp-mobile-card {{
                background: #fff; border: 1px solid var(--border-color); border-radius: 0.75rem;
                padding: 0.9rem 1rem; margin-bottom: 0.75rem; box-shadow: 0 1px 3px rgba(20,40,60,0.06);
            }}
            .stp-mobile-card__top {{
                display: flex; justify-content: space-between; align-items: flex-start; gap: 0.75rem; margin-bottom: 0.55rem;
            }}
            .stp-mobile-card__title {{ font-weight: 700; color: var(--text-color); font-size: 1rem; line-height: 1.3; min-width: 0; word-break: break-word; }}
            .stp-mobile-card__meta {{ color: var(--gray-color); font-size: 0.85rem; margin-top: 0.15rem; }}
            .stp-mobile-card__status {{ font-weight: 700; font-size: 0.82rem; white-space: nowrap; flex-shrink: 0; }}
            .stp-mobile-card__row {{
                display: grid; grid-template-columns: 5.5rem 1fr; gap: 0.35rem 0.5rem;
                font-size: 0.88rem; padding: 0.2rem 0; border-top: 1px solid #eef2f4;
            }}
            .stp-mobile-card__row:first-of-type {{ border-top: none; }}
            .stp-mobile-card__label {{ color: #6a7a86; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.02em; padding-top: 0.15rem; }}
            .stp-mobile-card__value {{ color: var(--text-color); word-break: break-word; min-width: 0; }}
            .stp-mobile-card__acoes {{ margin-top: 0.75rem; padding-top: 0.65rem; border-top: 1px solid #e8eef2; }}
            @media (max-width: 768px) {{
                .form-row {{ grid-template-columns: 1fr; }}
                .form-actions {{ flex-direction: column; align-items: stretch; }}
                .form-actions .btn {{ width: 100%; text-align: center; }}
                .filters-row {{ grid-template-columns: 1fr; }}
                .page-header > div {{ display: flex; flex-direction: column; align-items: stretch; gap: 0.5rem; }}
                .page-header .btn {{ width: 100%; margin-left: 0 !important; }}
                .card {{ padding: 1rem; }}
                .stp-list-desktop {{ display: none !important; }}
                .stp-list-mobile {{ display: block !important; }}
                .filters [style*="min-width"],
                .form-group[style*="min-width"],
                input[style*="min-width"],
                select[style*="min-width"] {{
                    min-width: 0 !important; width: 100% !important; flex: 1 1 100% !important;
                }}
            }}
            @media (max-width: 480px) {{
                .form-section {{ padding: 1rem; }}
                .coming-soon {{ padding: 2rem 1rem; }}
                .coming-soon .icon {{ font-size: 2.75rem; }}
            }}
            @media print {{
                .no-print {{ display: none !important; }}
                .stp-sidebar, .stp-topbar, .stp-sidebar-overlay, .filters {{ display: none !important; }}
                .stp-main {{ margin-left: 0 !important; }}
                .stp-content {{ padding: 0; }}
                .container {{ max-width: none; }}
                .stp-list-desktop {{ display: block !important; }}
                .stp-list-mobile {{ display: none !important; }}
            }}
        </style>
    </head>
    <body class="{body_cls}">
        <div class="stp-app">
            {sidebar}
            <div class="stp-sidebar-overlay no-print" id="stpOverlay"></div>
            <div class="stp-main">
                <header class="stp-topbar no-print">
                    <div style="display:flex;align-items:center;gap:0.75rem;">
                        <button type="button" class="stp-menu-toggle" id="stpMenuToggle"
                                aria-label="Abrir menu" aria-controls="stpSidebar" aria-expanded="false">☰</button>
                        <h1>{titulo}</h1>
                    </div>
                    <div class="stp-topbar-user">
                        <span>Bem-vindo, {nome_usuario}!</span>
                        <a href="{url_for('logout')}" class="logout">Sair</a>
                    </div>
                </header>
                <div class="stp-content">
                    <div class="container">
                        {conteudo}
                    </div>
                </div>
            </div>
        </div>
        <script>
        document.addEventListener('DOMContentLoaded', function() {{
            var sidebar = document.getElementById('stpSidebar');
            var overlay = document.getElementById('stpOverlay');
            var toggle = document.getElementById('stpMenuToggle');
            function setSidebarOpen(open) {{
                if (sidebar) sidebar.classList.toggle('open', open);
                if (overlay) overlay.classList.toggle('open', open);
                if (toggle) {{
                    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
                    toggle.setAttribute('aria-label', open ? 'Fechar menu' : 'Abrir menu');
                }}
                document.body.style.overflow = open ? 'hidden' : '';
            }}
            function closeSidebar() {{ setSidebarOpen(false); }}
            if (toggle) toggle.addEventListener('click', function() {{
                var open = !(sidebar && sidebar.classList.contains('open'));
                setSidebarOpen(open);
            }});
            if (overlay) overlay.addEventListener('click', closeSidebar);
            document.querySelectorAll('.stp-nav-link').forEach(function(link) {{
                link.addEventListener('click', function() {{ if (window.innerWidth <= 992) closeSidebar(); }});
            }});
            document.addEventListener('keydown', function(e) {{
                if (e.key === 'Escape') closeSidebar();
            }});
            // Teclado mobile: mantém campo focado visível
            document.querySelectorAll('input, select, textarea').forEach(function(el) {{
                el.addEventListener('focus', function() {{
                    setTimeout(function() {{
                        try {{ el.scrollIntoView({{ block: 'center', behavior: 'smooth' }}); }} catch (err) {{}}
                    }}, 280);
                }});
            }});

            document.addEventListener('input', function(e) {{
                if (!e.target || !e.target.classList || !e.target.classList.contains('data-br')) return;
                let v = e.target.value.replace(/\\D/g, '').slice(0, 8);
                if (v.length >= 5) {{
                    v = v.slice(0, 2) + '/' + v.slice(2, 4) + '/' + v.slice(4);
                }} else if (v.length >= 3) {{
                    v = v.slice(0, 2) + '/' + v.slice(2);
                }}
                e.target.value = v;
            }});

            // Toggle mostrar/ocultar senha (padrão único)
            var eyeShow = '{_SVG_EYE_SHOW}';
            var eyeHide = '{_SVG_EYE_HIDE}';
            document.querySelectorAll('[data-password-toggle]').forEach(function(btn) {{
                btn.addEventListener('click', function() {{
                    var id = btn.getAttribute('data-password-toggle');
                    var input = document.getElementById(id);
                    if (!input) return;
                    var showing = input.type === 'text';
                    input.type = showing ? 'password' : 'text';
                    btn.setAttribute('aria-pressed', showing ? 'false' : 'true');
                    btn.setAttribute('aria-label', showing ? 'Mostrar senha' : 'Ocultar senha');
                    btn.setAttribute('title', showing ? 'Mostrar senha' : 'Ocultar senha');
                    btn.innerHTML = showing ? eyeShow : eyeHide;
                    input.focus();
                }});
            }});

            // Máscaras reutilizáveis via data-mask
            function onlyDigits(v) {{ return (v || '').replace(/\\D/g, ''); }}
            function maskPhone(v) {{
                var d = onlyDigits(v).slice(0, 11);
                if (d.length <= 10) {{
                    return d.replace(/(\\d{{0,2}})(\\d{{0,4}})(\\d{{0,4}})/, function(_, a, b, c) {{
                        var out = '';
                        if (a) out += '(' + a;
                        if (a.length === 2) out += ') ';
                        if (b) out += b;
                        if (c) out += '-' + c;
                        return out;
                    }});
                }}
                return d.replace(/(\\d{{0,2}})(\\d{{0,5}})(\\d{{0,4}})/, function(_, a, b, c) {{
                    var out = '';
                    if (a) out += '(' + a;
                    if (a.length === 2) out += ') ';
                    if (b) out += b;
                    if (c) out += '-' + c;
                    return out;
                }});
            }}
            function maskCep(v) {{
                var d = onlyDigits(v).slice(0, 8);
                return d.length > 5 ? d.slice(0, 5) + '-' + d.slice(5) : d;
            }}
            function rgSanitizar(v) {{
                var s = (v || '').toUpperCase().replace(/[^0-9X]/g, '');
                var out = '';
                for (var i = 0; i < s.length && out.length < 9; i++) {{
                    var ch = s[i];
                    if (ch === 'X') {{
                        if (out.length === 8) out += 'X';
                    }} else {{
                        out += ch;
                    }}
                }}
                return out;
            }}
            function maskRg(v) {{
                var s = rgSanitizar(v);
                if (s.length <= 2) return s;
                if (s.length <= 5) return s.slice(0, 2) + '.' + s.slice(2);
                if (s.length <= 8) return s.slice(0, 2) + '.' + s.slice(2, 5) + '.' + s.slice(5);
                return s.slice(0, 2) + '.' + s.slice(2, 5) + '.' + s.slice(5, 8) + '-' + s.slice(8);
            }}
            var RG_SEQ_OBVIAS = {{
                '0000000':1,'1111111':1,'2222222':1,'3333333':1,'4444444':1,
                '5555555':1,'6666666':1,'7777777':1,'8888888':1,'9999999':1,
                '00000000':1,'11111111':1,'22222222':1,'33333333':1,'44444444':1,
                '55555555':1,'66666666':1,'77777777':1,'88888888':1,'99999999':1,
                '000000000':1,'111111111':1,'222222222':1,'333333333':1,'444444444':1,
                '555555555':1,'666666666':1,'777777777':1,'888888888':1,'999999999':1,
                '123456789':1,'987654321':1,'012345678':1,'876543210':1,
                '1234567':1,'12345678':1,'7654321':1,'87654321':1
            }};
            function rgEstruturalValido(s) {{
                if (!s || s.length < 7 || s.length > 9) return false;
                var corpo = s.slice(0, -1), dv = s.slice(-1);
                if (!/^\\d+$/.test(corpo)) return false;
                if (!(/^\\d$/.test(dv) || dv === 'X')) return false;
                if (corpo && corpo === corpo[0].repeat(corpo.length)) return false;
                if (RG_SEQ_OBVIAS[s] || RG_SEQ_OBVIAS[s.replace('X','0')] || RG_SEQ_OBVIAS[corpo]) return false;
                return true;
            }}
            function setStatusRg(input, tipo, texto) {{
                var status = input.parentElement
                    ? input.parentElement.querySelector('.stp-rg-status')
                    : null;
                input.classList.remove('is-invalid', 'is-valid');
                if (tipo === 'invalido') input.classList.add('is-invalid');
                if (tipo === 'valido') input.classList.add('is-valid');
                if (!status) return;
                status.classList.remove('stp-rg-valido', 'stp-rg-invalido', 'stp-rg-pendente');
                status.style.color = '';
                if (tipo === 'valido') {{
                    status.classList.add('stp-rg-valido');
                    status.style.color = 'var(--success-color)';
                }} else if (tipo === 'invalido') {{
                    status.classList.add('stp-rg-invalido');
                    status.style.color = 'var(--danger-color)';
                    status.style.fontWeight = '600';
                }} else if (tipo === 'pendente') {{
                    status.classList.add('stp-rg-pendente');
                    status.style.color = 'var(--warning-color)';
                }}
                status.textContent = texto || '';
            }}
            function atualizarStatusRg(input) {{
                if (!input || !input.classList.contains('stp-rg')) return true;
                var s = rgSanitizar(input.value);
                var obrigatorio = input.getAttribute('data-rg-required') === '1';
                if (!s.length) {{
                    setStatusRg(input, null, '');
                    return !obrigatorio;
                }}
                if (s.length < 7) {{
                    setStatusRg(input, 'pendente', 'Digite o RG completo');
                    return false;
                }}
                if (rgEstruturalValido(s)) {{
                    setStatusRg(input, 'valido', 'RG válido');
                    return true;
                }}
                setStatusRg(input, 'invalido', 'RG inválido.');
                return false;
            }}
            document.addEventListener('input', function(e) {{
                var input = e.target;
                if (!input || input.getAttribute('data-mask') !== 'rg') return;
                input.value = maskRg(input.value);
                if (input.classList.contains('stp-rg')) atualizarStatusRg(input);
            }});
            document.addEventListener('blur', function(e) {{
                var input = e.target;
                if (!input || !input.classList || !input.classList.contains('stp-rg')) return;
                atualizarStatusRg(input);
            }}, true);
            document.addEventListener('submit', function(e) {{
                var form = e.target;
                if (!form || !form.querySelectorAll) return;
                var inputs = form.querySelectorAll('input.stp-rg');
                for (var i = 0; i < inputs.length; i++) {{
                    if (!atualizarStatusRg(inputs[i])) {{
                        e.preventDefault();
                        setStatusRg(inputs[i], 'invalido', 'Informe um RG válido.');
                        inputs[i].focus();
                        return;
                    }}
                }}
            }}, true);
            document.querySelectorAll('input[data-mask="phone"]').forEach(function(input) {{
                input.addEventListener('input', function() {{ input.value = maskPhone(input.value); }});
            }});
            document.querySelectorAll('input[data-mask="cep"]').forEach(function(input) {{
                input.addEventListener('input', function() {{ input.value = maskCep(input.value); }});
            }});
            document.querySelectorAll('input[data-mask="rg"]').forEach(function(input) {{
                if (input.value) input.value = maskRg(input.value);
                if (input.classList.contains('stp-rg') && rgSanitizar(input.value).length >= 7) {{
                    atualizarStatusRg(input);
                }}
            }});
        }});
        </script>
        <script>
        (function() {{
            document.addEventListener('click', function(ev) {{
                var btn = ev.target.closest('.stp-ajuda-btn');
                if (!btn) return;
                var id = btn.getAttribute('data-stp-ajuda');
                var painel = document.getElementById('stp-ajuda-painel-' + id);
                if (!painel) return;
                var abrir = painel.hasAttribute('hidden');
                if (abrir) {{
                    painel.removeAttribute('hidden');
                    btn.setAttribute('aria-expanded', 'true');
                }} else {{
                    painel.setAttribute('hidden', 'hidden');
                    btn.setAttribute('aria-expanded', 'false');
                }}
            }});
        }})();
        </script>
        {extra_scripts}
    </body>
    </html>
    '''

def create_app():
    # global app
    global sistema_backup, whatsapp_service, notificacao_agendamento, agendador_lembretes
    
    # Configuração com caminho absoluto
    basedir = os.path.abspath(os.path.dirname(__file__))
    
    # Configurar Flask para usar as pastas do sistema
    app = Flask(__name__, 
                static_folder='sistema/static',
                template_folder='sistema/templates')

    app.wsgi_app = PrefixMiddleware(app.wsgi_app, prefix='/transporte')

    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=1,
        x_proto=1,
        x_host=1,
        x_prefix=1
    )

    db_path = os.path.join(basedir, 'db', 'transporte_pacientes.db')
    
    app.config['SECRET_KEY'] = 'cosmopolis_sistema_transporte_2024'
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['WTF_CSRF_ENABLED'] = False
    # SCRIPT_NAME definido pelo PrefixMiddleware já cuida do path do cookie
    
    # Criar outros diretórios necessários
    for dir_name in ['uploads', 'relatorios', 'static/css', 'static/js', 'static/img']:
        dir_path = os.path.join(basedir, dir_name)
        os.makedirs(dir_path, exist_ok=True)
    
    # Inicializar extensões
    db.init_app(app)
    login_manager.init_app(app)
    
    # Configurar Login Manager
    login_manager.login_view = 'login'
    login_manager.login_message = 'Por favor, faça login para acessar esta página.'
    login_manager.login_message_category = 'info'
    
    # Verificar e criar banco dentro do contexto da aplicação
    with app.app_context():
        verificar_e_criar_banco()
        
        # ===== INICIALIZAR SISTEMA DE BACKUP =====
        global sistema_backup
        sistema_backup = SistemaBackup(app, db)

        # ===== INICIALIZAR SISTEMA WHATSAPP =====
        global whatsapp_service, notificacao_agendamento, agendador_lembretes
        whatsapp_service = WhatsAppNotificacao(app, db)
        notificacao_agendamento = NotificacaoAgendamento(whatsapp_service)
        agendador_lembretes = AgendadorLembretes(whatsapp_service, db, flask_app=app)

        # Iniciar serviços (só uma vez, verificar se já estão ativos para evitar duplicação com reloader)
        if not getattr(sistema_backup, 'ativo', False):
            sistema_backup.iniciar_agendamento()
        if whatsapp_bloqueado_por_simulacao():
            print('🔇 STP_BLOQUEAR_WHATSAPP=1 — WhatsApp e lembretes NÃO iniciados (simulação).')
        else:
            if not getattr(whatsapp_service, 'ativo', False):
                whatsapp_service.iniciar_servico()
            if not getattr(agendador_lembretes, 'ativo', False):
                agendador_lembretes.iniciar_agendador()
    

    # ===== ROTAS =====
    @app.route('/')
    def index():
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))
        return redirect(url_for('login'))
    
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            
            if not username or not password:
                flash('Por favor, preencha usuário e senha!', 'error')
                return redirect(url_for('login'))
            
            try:
                user = Usuario.query.filter_by(username=username).first()
                print(f"🔍 Usuário encontrado: {user is not None}")
                
                if user:
                    print(f"🔐 Verificando senha para usuário: {user.username}")
                    
                    if user.check_password(password):
                        login_user(user)
                        session.pop('_flashes', None)
                        flash('Login realizado com sucesso!', 'success')
                        print(f"✅ Login bem-sucedido para: {user.username}")
                        return redirect(url_for('dashboard'))
                    else:
                        flash('Senha incorreta!', 'error')
                        print(f"❌ Senha incorreta para: {user.username}")
                else:
                    flash('Usuário não encontrado!', 'error')
                    print(f"❌ Usuário não encontrado: {username}")
                    
            except Exception as e:
                flash(f'Erro ao fazer login: {str(e)}', 'error')
                print(f"❌ Erro de login: {e}")
        
        # Gerar alertas de mensagens flash
        messages_html = ""
        for category, message in get_flashed_messages(with_categories=True):
            alert_class = "alert-error" if category == "error" else "alert-success"
            messages_html += f'<div class="alert {alert_class}">{message}</div>'
        
        hero_url = url_for('static', filename='img/ambulancia.png')
        return f'''
        <!DOCTYPE html>
        <html lang="pt-BR">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Login - Sistema de Transporte</title>
            <link rel="icon" href="{url_for('static', filename='img/favicon.ico')}" type="image/x-icon">
            <link rel="shortcut icon" href="{url_for('static', filename='img/favicon.ico')}">
            <style>
                :root {{
                    --color-100: #ffffff;
                    --primary-color: #4fc9c4;
                    --primary-dark: #43aca7;
                    --primary-hover: #3c9b96;
                    --text-color: #3f485d;
                    --border-color: #e5e5e5;
                    --success-color: #79b24a;
                    --danger-color: #e81d51;
                    --gray-color: #6d7a8c;
                    --input-focus: #4fc9c4;
                    --input-focus-shadow: rgba(79, 201, 196, 0.25);
                }}
                * {{ box-sizing: border-box; }}
                html, body {{ margin: 0; padding: 0; height: 100%; }}
                body {{
                    font-family: Arial, Helvetica, sans-serif;
                    color: var(--text-color);
                    background: linear-gradient(135deg, var(--primary-color), var(--primary-dark));
                    overflow: hidden;
                }}
                .login-split {{
                    display: flex;
                    width: 100%;
                    height: 100vh;
                    min-height: 100vh;
                }}
                .login-panel {{
                    width: 480px;
                    min-width: 420px;
                    max-width: 520px;
                    flex: 0 0 auto;
                    height: 100%;
                    background: linear-gradient(160deg, var(--primary-color) 0%, var(--primary-dark) 55%, var(--primary-hover) 100%);
                    box-shadow: 4px 0 28px rgba(0, 0, 0, 0.18);
                    z-index: 2;
                    display: flex;
                    flex-direction: column;
                    overflow-y: auto;
                }}
                .login-panel-inner {{
                    width: 100%;
                    max-width: 400px;
                    margin: auto;
                    padding: 2.5rem 2rem;
                }}
                .login-card {{
                    background: var(--color-100);
                    border-radius: 1rem;
                    padding: 1.75rem 1.5rem;
                    box-shadow: 0 0.5rem 2rem rgba(0, 0, 0, 0.18);
                }}
                .login-brand {{ text-align: center; margin-bottom: 1.5rem; }}
                .login-brand .logo {{
                    width: 72px; height: 72px; border-radius: 1rem;
                    display: inline-flex; align-items: center; justify-content: center;
                    font-size: 2rem; margin-bottom: 1rem;
                    background: linear-gradient(135deg, var(--primary-color), var(--primary-dark));
                    color: #fff; box-shadow: 0 8px 20px rgba(79, 201, 196, 0.35);
                }}
                .login-brand h1 {{
                    margin: 0; font-size: 1.35rem; font-weight: 700;
                    color: var(--primary-color); line-height: 1.3;
                }}
                .login-brand p {{
                    margin: 0.4rem 0 0; font-size: 0.95rem; color: var(--gray-color);
                }}
                .login-messages {{ margin-bottom: 0.75rem; }}
                .form-group {{ margin-bottom: 1rem; }}
                .form-group label {{
                    display: block; margin-bottom: 0.5rem;
                    color: var(--text-color); font-weight: 600;
                }}
                .form-group input {{
                    width: 100%; padding: 0.75rem;
                    border: 2px solid var(--border-color); border-radius: 0.5rem;
                    font-size: 1rem; background: #fff; color: var(--text-color);
                }}
                .form-group input:hover:not(:disabled) {{ border-color: var(--primary-dark); }}
                .form-group input:focus {{
                    border-color: var(--input-focus); outline: none;
                    box-shadow: 0 0 0 3px var(--input-focus-shadow);
                }}
                .form-group input:focus-visible,
                .btn:focus-visible,
                .password-toggle:focus-visible {{
                    outline: 2px solid var(--primary-color); outline-offset: 2px;
                }}
                .password-field {{ position: relative; }}
                .password-field input {{ padding-right: 2.75rem; }}
                .password-toggle {{
                    position: absolute; right: 0.55rem; top: 50%; transform: translateY(-50%);
                    width: 2rem; height: 2rem; border: none; background: transparent;
                    color: var(--gray-color); cursor: pointer; border-radius: 0.35rem;
                    display: inline-flex; align-items: center; justify-content: center; padding: 0;
                }}
                .password-toggle:hover {{
                    color: var(--primary-dark); background: rgba(79, 201, 196, 0.12);
                }}
                .password-toggle svg {{
                    width: 1.15rem; height: 1.15rem; display: block; pointer-events: none;
                }}
                .required-mark {{
                    color: var(--danger-color); font-weight: 700; margin-left: 0.15rem;
                }}
                .btn {{
                    width: 100%; padding: 0.85rem; margin-top: 0.35rem;
                    background: var(--primary-color); color: var(--color-100);
                    border: none; border-radius: 0.5rem; font-size: 1rem;
                    font-weight: 600; cursor: pointer;
                    transition: background-color 0.2s ease, box-shadow 0.2s ease;
                }}
                .btn:hover {{
                    background: var(--primary-dark);
                    box-shadow: 0 8px 18px rgba(79, 201, 196, 0.28);
                }}
                .btn:active {{ background: var(--primary-hover); }}
                .alert {{ padding: 0.75rem; margin-bottom: 1rem; border-radius: 0.5rem; }}
                .alert-error {{
                    background: rgba(232, 29, 81, 0.1); color: var(--danger-color);
                    border: 1px solid var(--danger-color);
                }}
                .alert-success {{
                    background: rgba(121, 178, 74, 0.1); color: var(--success-color);
                    border: 1px solid var(--success-color);
                }}
                .login-hero {{
                    flex: 1 1 auto;
                    min-width: 0;
                    height: 100%;
                    background-color: var(--primary-color);
                    background-image: url("{hero_url}?v=8");
                    background-position: center center;
                    background-repeat: no-repeat;
                    background-size: contain;
                }}
                @media (max-width: 992px) {{
                    .login-panel {{
                        width: 420px; min-width: 420px; max-width: 420px;
                    }}
                    .login-panel-inner {{ padding: 2rem 1.5rem; }}
                }}
                @media (max-width: 768px) {{
                    body {{ overflow: auto; }}
                    .login-split {{
                        flex-direction: column; height: auto; min-height: 100vh;
                    }}
                    .login-panel {{
                        width: 100%; min-width: 0; max-width: none;
                        min-height: 100vh; box-shadow: none;
                    }}
                    .login-hero {{ display: none; }}
                }}
            </style>
        </head>
        <body>
            <div class="login-split">
                <aside class="login-panel" aria-label="Área de autenticação">
                    <div class="login-panel-inner">
                        <div class="login-card">
                            <div class="login-brand">
                                <div class="logo" aria-hidden="true">🚑</div>
                                <h1>Sistema de Transporte</h1>
                                <p>Prefeitura Municipal de Cosmópolis</p>
                            </div>

                            <div class="login-messages">{messages_html}</div>

                            <form method="POST" novalidate>
                                <div class="form-group">
                                    <label for="username">Usuário <span class="required-mark" aria-hidden="true">*</span></label>
                                    <input type="text" id="username" name="username" required
                                           placeholder="Digite seu usuário" autocomplete="username" autofocus>
                                </div>

                                {html_campo_senha(
                                    input_id='password',
                                    name='password',
                                    label='Senha',
                                    required=True,
                                    placeholder='Digite sua senha',
                                    autocomplete='current-password',
                                )}

                                <button type="submit" class="btn">Entrar</button>
                            </form>
                        </div>
                    </div>
                </aside>
                <div class="login-hero"
                     role="img"
                     aria-label="Ambulância do serviço de transporte de pacientes"></div>
            </div>
            <script>
            (function() {{
                var eyeShow = '{_SVG_EYE_SHOW}';
                var eyeHide = '{_SVG_EYE_HIDE}';
                document.querySelectorAll('[data-password-toggle]').forEach(function(btn) {{
                    btn.addEventListener('click', function() {{
                        var id = btn.getAttribute('data-password-toggle');
                        var input = document.getElementById(id);
                        if (!input) return;
                        var showing = input.type === 'text';
                        input.type = showing ? 'password' : 'text';
                        btn.setAttribute('aria-pressed', showing ? 'false' : 'true');
                        btn.setAttribute('aria-label', showing ? 'Mostrar senha' : 'Ocultar senha');
                        btn.setAttribute('title', showing ? 'Mostrar senha' : 'Ocultar senha');
                        btn.innerHTML = showing ? eyeShow : eyeHide;
                        input.focus();
                    }});
                }});
            }})();
            </script>
        </body>
        </html>
        '''
    
    # ===== DASHBOARD =====
    @app.route('/dashboard')
    @login_required
    def dashboard():
        # Buscar dados reais do banco
        hoje = date.today()
        total_pacientes = Paciente.query.filter_by(ativo=True).count()
        total_veiculos = Veiculo.query.filter_by(ativo=True).count()
        total_motoristas = Motorista.query.filter_by(status='ativo').count()
        agendamentos_hoje = Agendamento.query.filter_by(data=hoje).count()
        
        # Agendamentos de hoje para exibir
        agendamentos_lista = Agendamento.query.filter_by(data=hoje).order_by(Agendamento.hora).all()
        
        # Preparar dados para JavaScript
        agendamentos_js_data = []
        for ag in agendamentos_lista:
            status_class = {
                'confirmado': 'success',
                'agendado': 'warning', 
                'em_andamento': 'primary',
                'concluido': 'secondary'
            }.get(ag.status, 'secondary')
            
            agendamentos_js_data.append({
                'id': ag.id,
                'horario_saida': ag.hora.strftime('%H:%M'),
                'paciente_nome': escape_js_string(ag.paciente.nome),
                'paciente_telefone': escape_js_string(ag.paciente.telefone),
                'destino_nome': escape_js_string(ag.destino[:50]),
                'status': ag.status,
                'status_nome': escape_js_string(ag.status.replace('_', ' ').title()),
                'status_class': status_class
            })
        
        # Converter para JSON seguro
        agendamentos_json = json.dumps(agendamentos_js_data)

        dashboard_head = '''
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
            <link href="https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@3.34.1/dist/tabler-icons.min.css" rel="stylesheet">
            <style>
                .stp-dashboard .card { border-left: none; padding: 0; }
                .stats-card {
                    background: linear-gradient(135deg, #ffffff 0%, #f8f9fa 100%);
                    border: none; border-radius: 1rem;
                    box-shadow: 0 0.125rem 0.25rem rgba(0,0,0,0.075);
                    transition: all 0.3s ease; position: relative; overflow: hidden; cursor: pointer;
                }
                .stats-card:hover { transform: translateY(-5px); box-shadow: 0 0.5rem 1rem rgba(0,0,0,0.15); }
                .stats-card::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 4px; }
                .card-primary::before { background: var(--primary-color); }
                .card-success::before { background: #28a745; }
                .card-warning::before { background: #ffc107; }
                .card-info::before { background: #17a2b8; }
                .stats-icon {
                    width: 60px; height: 60px; border-radius: 50%; display: flex;
                    align-items: center; justify-content: center; font-size: 1.5rem;
                    color: white; margin-right: 1rem;
                }
                .icon-primary { background: linear-gradient(135deg, var(--primary-color), #4a49c4); }
                .icon-success { background: linear-gradient(135deg, #28a745, #1e7e34); }
                .icon-warning { background: linear-gradient(135deg, #ffc107, #e0a800); }
                .icon-info { background: linear-gradient(135deg, #17a2b8, #138496); }
                .stats-number { font-size: 2.5rem; font-weight: 700; color: #333; margin: 0; line-height: 1; }
                .stats-label { color: #6c757d; font-weight: 500; font-size: 0.875rem; margin-bottom: 0.5rem; }
                .quick-action {
                    background: white; border: 2px solid #e9ecef; border-radius: 0.75rem; padding: 1.5rem;
                    text-decoration: none; color: #333; transition: all 0.3s ease; display: block; text-align: center;
                }
                .quick-action:hover {
                    border-color: var(--primary-color); transform: translateY(-3px);
                    box-shadow: 0 0.25rem 0.5rem rgba(0,0,0,0.1); color: var(--primary-color); text-decoration: none;
                }
                .quick-action i { font-size: 2rem; margin-bottom: 0.5rem; display: block; color: var(--primary-color); }
                .welcome-banner {
                    background: linear-gradient(135deg, var(--primary-color), #4a49c4);
                    color: white; border-radius: 1rem; padding: 2rem; margin-bottom: 2rem;
                    position: relative; overflow: hidden;
                }
                .schedule-item {
                    border: 1px solid #dee2e6; border-radius: 0.5rem; padding: 1rem; margin-bottom: 0.75rem;
                    background: white; transition: all 0.3s ease;
                }
                .schedule-item:hover { border-color: var(--primary-color); box-shadow: 0 0.125rem 0.25rem rgba(0,0,0,0.075); }
                .schedule-time { font-weight: 600; color: var(--primary-color); font-size: 1.1rem; }
                .fade-in-up { animation: fadeInUp 0.6s ease-out; }
                @keyframes fadeInUp {
                    from { opacity: 0; transform: translateY(20px); }
                    to { opacity: 1; transform: translateY(0); }
                }
                @media (max-width: 768px) {
                    .stats-number { font-size: clamp(1.5rem, 7vw, 2rem); }
                    .stats-icon { width: 50px; height: 50px; font-size: 1.25rem; }
                    .welcome-banner { padding: 1.25rem; }
                    .welcome-banner .text-end { text-align: left !important; margin-top: 0.75rem; }
                    .stp-dashboard .row.g-4 > [class*="col-"] { margin-bottom: 0.5rem; }
                }
                @media (max-width: 480px) {
                    .stp-dashboard .btn, .stp-dashboard .quick-action {
                        width: 100%; justify-content: center;
                    }
                }
            </style>
        '''

        dashboard_conteudo = f'''
            <div class="stp-dashboard">
                <!-- Welcome Banner -->
                <div class="welcome-banner fade-in-up">
                    <div class="row align-items-center">
                        <div class="col-md-8">
                            <h1 class="h3 mb-2">{obter_saudacao()}</h1>
                            <p class="mb-0 opacity-90">Sistema de Transporte de Pacientes - Cosmópolis/SP</p>
                        </div>
                        <div class="col-md-4 text-end">
                            <span class="h4" id="currentTime">{datetime.now().strftime('%H:%M')}</span>
                            <br /><br /><small class="opacity-75">Última atualização</small>
                        </div>
                    </div>
                </div>
                
                <!-- Statistics Cards -->
                <div class="row g-4 mb-4">
                    <div class="col-xl-3 col-md-6">
                        <div class="card stats-card card-primary fade-in-up" onclick="window.location.href='{url_for('agendamentos')}'">
                            <div class="card-body">
                                <div class="d-flex align-items-center">
                                    <div class="stats-icon icon-primary">
                                        <i class="ti ti-calendar-check"></i>
                                    </div>
                                    <div class="flex-grow-1">
                                        <div class="stats-label">Agendamentos Hoje</div>
                                        <div class="stats-number" id="agendamentosHoje">{agendamentos_hoje}</div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    <div class="col-xl-3 col-md-6">
                        <div class="card stats-card card-success fade-in-up" onclick="window.location.href='{url_for('pacientes')}'" style="animation-delay: 0.1s">
                            <div class="card-body">
                                <div class="d-flex align-items-center">
                                    <div class="stats-icon icon-success">
                                        <i class="ti ti-users"></i>
                                    </div>
                                    <div class="flex-grow-1">
                                        <div class="stats-label">Pacientes Ativos</div>
                                        <div class="stats-number" id="pacientesAtivos">{total_pacientes}</div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    <div class="col-xl-3 col-md-6">
                        <div class="card stats-card card-info fade-in-up" onclick="window.location.href='{url_for('motoristas')}'" style="animation-delay: 0.2s">
                            <div class="card-body">
                                <div class="d-flex align-items-center">
                                    <div class="stats-icon icon-info">
                                        <i class="ti ti-id-badge-2"></i>
                                    </div>
                                    <div class="flex-grow-1">
                                        <div class="stats-label">Motoristas Disponíveis</div>
                                        <div class="stats-number" id="motoristasDisponiveis">{total_motoristas}</div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    <div class="col-xl-3 col-md-6">
                        <div class="card stats-card card-warning fade-in-up" onclick="window.location.href='{url_for('veiculos')}'" style="animation-delay: 0.3s">
                            <div class="card-body">
                                <div class="d-flex align-items-center">
                                    <div class="stats-icon icon-warning">
                                        <i class="ti ti-truck"></i>
                                    </div>
                                    <div class="flex-grow-1">
                                        <div class="stats-label">Veículos Disponíveis</div>
                                        <div class="stats-number" id="veiculosDisponiveis">{total_veiculos}</div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                
                <div class="row g-4">
                    <!-- Main Content -->
                    <div class="col-xl-8">
                        
                        <!-- Quick Actions -->
                        <div class="card mb-4 fade-in-up" style="animation-delay: 0.4s">
                            <div class="card-header">
                                <h5 class="card-title mb-0">
                                    <i class="ti ti-bolt me-2"></i>
                                    Ações Rápidas
                                </h5>
                            </div>
                            <div class="card-body">
                                <div class="row g-3">
                                    <div class="col-md-3 col-6">
                                        <a href="{url_for('agendamentos_novo')}" class="quick-action">
                                            <i class="ti ti-circle-plus"></i>
                                            <div class="fw-semibold">Novo Agendamento</div>
                                        </a>
                                    </div>
                                    <div class="col-md-3 col-6">
                                        <a href="{url_for('pacientes_cadastrar')}" class="quick-action">
                                            <i class="ti ti-user-plus"></i>
                                            <div class="fw-semibold">Novo Paciente</div>
                                        </a>
                                    </div>
                                    <div class="col-md-3 col-6">
                                        <a href="{url_for('relatorios')}" class="quick-action">
                                            <i class="ti ti-file-text"></i>
                                            <div class="fw-semibold">Relatórios</div>
                                        </a>
                                    </div>
                                    <div class="col-md-3 col-6">
                                        <a href="#" class="quick-action" onclick="refreshDashboard(); return false;">
                                            <i class="ti ti-refresh"></i>
                                            <div class="fw-semibold">Atualizar</div>
                                        </a>
                                    </div>
                                </div>
                            </div>
                        </div>
                        
                        <!-- Today's Schedule -->
                        <div class="card fade-in-up" style="animation-delay: 0.5s">
                            <div class="card-header d-flex justify-content-between align-items-center">
                                <h5 class="card-title mb-0">
                                    <i class="ti ti-calendar me-2"></i>
                                    Agendamentos de Hoje
                                </h5>
                                <a href="{url_for('agendamentos')}" class="btn btn-sm btn-outline-primary">Ver Todos</a>
                            </div>
                            <div class="card-body">
                                <div id="todaySchedule">
                                    <!-- Conteúdo será carregado via JavaScript -->
                                </div>
                            </div>
                        </div>
                        
                    </div>
                    
                    <!-- Status lateral -->
                    <div class="col-xl-4">
                        <div class="card fade-in-up" style="animation-delay: 0.6s">
                            <div class="card-header">
                                <h5 class="card-title mb-0">
                                    <i class="ti ti-info-circle me-2"></i>
                                    Status do Sistema
                                </h5>
                            </div>
                            <div class="card-body">
                                <div class="d-flex justify-content-between align-items-center mb-2">
                                    <span>Sistema:</span>
                                    <span class="badge bg-success">Online</span>
                                </div>
                                <div class="d-flex justify-content-between align-items-center mb-2">
                                    <span>Banco de Dados:</span>
                                    <span class="badge bg-success">Conectado</span>
                                </div>
                                <div class="d-flex justify-content-between align-items-center">
                                    <span>Última Atualização:</span>
                                    <span class="text-muted small" id="lastUpdate">{datetime.now().strftime('%H:%M:%S')}</span>
                                </div>
                            </div>
                        </div>
                        
                    </div>
                </div>
            </div>
        '''

        dashboard_scripts = f'''
            <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
            <script>
                var agendamentosIniciais = {agendamentos_json};
                function updateTime() {{
                    const now = new Date();
                    const timeString = now.toLocaleTimeString('pt-BR', {{ hour: '2-digit', minute: '2-digit' }});
                    const timeElement = document.getElementById('currentTime');
                    const updateElement = document.getElementById('lastUpdate');
                    if (timeElement) timeElement.textContent = timeString;
                    if (updateElement) updateElement.textContent = now.toLocaleTimeString('pt-BR');
                }}
                function refreshDashboard() {{
                    fetch('/transporte/dashboard_api')
                        .then(response => {{
                            if (!response.ok) throw new Error('HTTP error! status: ' + response.status);
                            return response.json();
                        }})
                        .then(data => {{
                            const stats = data.stats;
                            if (stats) {{
                                animateCounter('agendamentosHoje', stats.agendamentos_hoje);
                                animateCounter('pacientesAtivos', stats.pacientes_ativos);
                                animateCounter('motoristasDisponiveis', stats.motoristas_disponiveis);
                                animateCounter('veiculosDisponiveis', stats.veiculos_disponiveis);
                            }}
                            updateTodaySchedule(data.agendamentos_hoje);
                            updateTime();
                        }})
                        .catch(error => console.error('Erro ao atualizar dashboard:', error));
                }}
                function animateCounter(elementId, newValue) {{
                    const element = document.getElementById(elementId);
                    if (!element) return;
                    const currentValue = parseInt(element.textContent) || 0;
                    if (currentValue === newValue) return;
                    const duration = 1000, steps = 20, stepTime = duration / steps;
                    const stepValue = (newValue - currentValue) / steps;
                    let step = 0;
                    const timer = setInterval(function() {{
                        step++;
                        element.textContent = Math.round(currentValue + (stepValue * step));
                        if (step >= steps) {{ clearInterval(timer); element.textContent = newValue; }}
                    }}, stepTime);
                }}
                function updateTodaySchedule(agendamentos) {{
                    const container = document.getElementById('todaySchedule');
                    if (!container) return;
                    if (!agendamentos || agendamentos.length === 0) {{
                        container.innerHTML = '<div class="text-center py-4">' +
                            '<i class="ti ti-calendar-x text-muted" style="font-size: 3rem;"></i>' +
                            '<p class="text-muted mt-3 mb-0">Nenhum agendamento para hoje</p>' +
                            '<a href="{url_for('agendamentos_novo')}" class="btn btn-primary mt-2">' +
                            '<i class="ti ti-circle-plus me-1"></i> Criar Agendamento</a></div>';
                        return;
                    }}
                    var html = '';
                    agendamentos.forEach(function(ag) {{
                        const statusClass = {{ 'confirmado': 'success', 'agendado': 'warning', 'em_andamento': 'primary', 'concluido': 'secondary' }}[ag.status] || 'secondary';
                        html += '<div class="schedule-item"><div class="row align-items-center">' +
                            '<div class="col-md-2"><div class="schedule-time">' + ag.horario_saida + '</div></div>' +
                            '<div class="col-md-4"><div class="fw-semibold">' + ag.paciente_nome + '</div>' +
                            '<div class="text-muted small">' + ag.paciente_telefone + '</div></div>' +
                            '<div class="col-md-4"><div class="text-muted small"><strong>Destino:</strong><br />' + ag.destino_nome + '</div></div>' +
                            '<div class="col-md-2"><span class="badge bg-' + statusClass + '">' + ag.status_nome + '</span></div>' +
                            '</div></div>';
                    }});
                    container.innerHTML = html;
                }}
                document.addEventListener('DOMContentLoaded', function() {{
                    updateTodaySchedule(agendamentosIniciais);
                    updateTime();
                    setInterval(updateTime, 60000);
                    setInterval(refreshDashboard, 2 * 60 * 1000);
                    setTimeout(refreshDashboard, 3000);
                }});
            </script>
        '''

        return gerar_layout_base(
            'Início',
            dashboard_conteudo,
            'dashboard',
            extra_head=dashboard_head,
            extra_scripts=dashboard_scripts,
            body_class='stp-dashboard',
        )
    
    @app.route('/dashboard_api')
    @login_required
    def dashboard_api():
        try:
            print("🔄 API Dashboard chamada!")
            
            # Buscar dados reais do banco
            hoje = date.today()
            
            stats = {
                'agendamentos_hoje': Agendamento.query.filter_by(data=hoje).count(),
                'pacientes_ativos': Paciente.query.filter_by(ativo=True).count(),
                'motoristas_disponiveis': Motorista.query.filter_by(status='ativo').count(),
                'veiculos_disponiveis': Veiculo.query.filter_by(ativo=True).count()
            }
            
            print(f"📊 Stats calculadas: {stats}")
            
            # Agendamentos de hoje
            agendamentos_hoje = []
            agendamentos = Agendamento.query.filter_by(data=hoje).order_by(Agendamento.hora).all()
            
            for ag in agendamentos:
                agendamentos_hoje.append({
                    'id': ag.id,
                    'horario_saida': ag.hora.strftime('%H:%M'),
                    'paciente_nome': ag.paciente.nome,
                    'paciente_telefone': ag.paciente.telefone,
                    'destino_nome': ag.destino[:50],
                    'status': ag.status,
                    'status_nome': ag.status.replace('_', ' ').title()
                })
            
            print(f"📅 Agendamentos encontrados: {len(agendamentos_hoje)}")
            
            response_data = {
                'stats': stats,
                'agendamentos_hoje': agendamentos_hoje,
                'timestamp': datetime.now().isoformat()
            }
            
            print("✅ API Dashboard respondendo com sucesso!")
            return jsonify(response_data)
            
        except Exception as e:
            print(f"❌ Erro na API Dashboard: {e}")
            return jsonify({'error': str(e)}), 500
    
    # ===== PACIENTES =====
    @app.route('/pacientes')
    @login_required
    def pacientes():
        filtros = obter_filtros_pacientes_request()
        page, per_page = obter_paginacao_request()
        total_cadastro = Paciente.query.filter_by(ativo=True).count()
        query = montar_query_pacientes(filtros)
        pacientes_lista, total, page = listar_paginado(
            query, page, per_page, Paciente.data_cadastro.desc()
        )
        exibidos = len(pacientes_lista)
        tem_filtro = filtros_tem_valores(filtros)
        filtros_url = {k: v for k, v in filtros.items() if v}

        filtros_html = gerar_filtros_pacientes(filtros, total, exibidos, per_page)
        paginacao_html = gerar_paginacao('pacientes', page, per_page, total, filtros_url)
        botoes_impressao = gerar_botoes_impressao('pacientes_imprimir', filtros_url, page, per_page)
        
        pacientes_html = ""
        if pacientes_lista:
            from html import escape as esc_html
            cards_mobile = ""
            pacientes_html = '''
            <div class="card">
                <div style="display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:0.75rem; margin-bottom:1rem;">
                    <h3 style="color: var(--primary-color); margin: 0;">📋 Pacientes Cadastrados</h3>
                    ''' + botoes_impressao + '''
                </div>
                <div class="stp-list-desktop table-container">
                    <table style="width: 100%; border-collapse: collapse;">
                        <thead>
                            <tr style="background: var(--color-95);">
                                ''' + html_th_id() + '''
                                <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Nome</th>
                                <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Idade</th>
                                <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">CPF</th>
                                <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Tel Cel</th>
                                <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Tel Resi</th>
                                <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Condição</th>
                                <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Data Cadastro</th>
                                <th style="padding: 0.75rem; text-align: center; border-bottom: 2px solid var(--primary-color);">Ações</th>
                            </tr>
                        </thead>
                        <tbody>
            '''
            for paciente in pacientes_lista:
                tel_cel, tel_res = telefones_paciente_exibir(paciente)
                condicao_html = html_badge_condicao_paciente(paciente)
                idade_txt = formatar_idade_exibir(paciente.data_nascimento)
                acoes = html_acoes_toolbar(
                    html_acao_icone('ti-edit', 'Editar paciente', href=url_for('pacientes_editar', paciente_id=paciente.id), variant='editar'),
                    html_acao_icone('ti-trash', 'Excluir paciente', href=url_for('pacientes_excluir', paciente_id=paciente.id), variant='excluir', confirm_msg='Tem certeza que deseja excluir este paciente?'),
                )
                data_cad = paciente.data_cadastro.strftime('%d/%m/%Y') if paciente.data_cadastro else '—'
                pacientes_html += f'''
                            <tr>
                                {html_td_id(paciente.id)}
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{esc_html(paciente.nome)}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{esc_html(idade_txt)}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{esc_html(paciente.cpf)}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{esc_html(tel_cel)}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{esc_html(tel_res)}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{condicao_html}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{data_cad}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color); text-align: center;">{acoes}</td>
                            </tr>
                '''
                cards_mobile += html_mobile_card(
                    title=f'#{paciente.id} {paciente.nome or "—"}',
                    meta=esc_html(paciente.cpf or '—'),
                    rows=[
                        ('ID', f'<strong>{paciente.id}</strong>'),
                        ('Idade', esc_html(idade_txt)),
                        ('Tel. Cel', esc_html(tel_cel)),
                        ('Tel. Res', esc_html(tel_res)),
                        ('Condição', condicao_html),
                        ('Ponto de Embarque', esc_html(ponto_embarque_do_paciente(paciente) or '—')),
                        ('Cadastro', data_cad),
                    ],
                    acoes_html=acoes,
                )
            pacientes_html += f'''
                        </tbody>
                    </table>
                </div>
                <div class="stp-list-mobile">{cards_mobile}</div>
            </div>
            '''
        elif tem_filtro:
            pacientes_html = '''
            <div class="card">
                <p style="margin: 0; color: var(--gray-color);">
                    Nenhum paciente encontrado com os filtros selecionados.
                </p>
            </div>
            '''
        
        conteudo = f'''
        <div class="page-header">
            <h2>👥 Gerenciamento de Pacientes</h2>
            <p>Cadastro e controle de pacientes do sistema de transporte</p>
            <div style="margin-top: 1rem;">
                <a href="{url_for('pacientes_cadastrar')}" class="btn">📋 Cadastrar Novo Paciente</a>
            </div>
        </div>
        
        {filtros_html}
        {pacientes_html}
        {paginacao_html}
        
        {f'<div class="card"><div class="coming-soon"><div class="icon">👥</div><h3>Nenhum paciente cadastrado</h3><p>Comece cadastrando o primeiro paciente do sistema!</p></div></div>' if not total_cadastro and not tem_filtro else ''}
        '''
        return gerar_layout_base("Pacientes", conteudo, "pacientes")

    @app.route('/pacientes/imprimir')
    @login_required
    def pacientes_imprimir():
        filtros = obter_filtros_pacientes_request()
        page, per_page = obter_paginacao_request()
        paginas = request.args.get('paginas', 'atual')
        query = montar_query_pacientes(filtros)
        lista, total, total_pages, pag_ini, pag_fim = buscar_lista_impressao(
            query, page, per_page, paginas, Paciente.data_cadastro.desc()
        )
        return gerar_html_impressao_pacientes(lista, filtros)
    
    
    # ===== CADASTAR PACIENTES =====
    @app.route('/pacientes/cadastrar', methods=['GET', 'POST'])
    @login_required
    def pacientes_cadastrar():
            if request.method == 'POST':
                try:
                    # Extrair dados do formulário
                    nome = request.form.get('nome', '').strip()
                    cpf = request.form.get('cpf', '').strip()
                    tel_cel = request.form.get('tel_cel', '').strip()
                    tel_res = request.form.get('tel_res', '').strip()
                    data_nascimento = request.form.get('data_nascimento')
                    cep = request.form.get('cep', '').strip()
                    logradouro, numero, bairro, complemento, endereco = montar_endereco_paciente_de_form(request.form)
                    ponto_embarque = (
                        request.form.get('ponto_embarque', '').strip()
                        or request.form.get('ponto_referencia', '').strip()
                    )
                    cartao_sus = request.form.get('cns', '').strip()
                    observacoes = request.form.get('observacoes', '').strip()
                    ok_cond, erro_cond, dados_cond = extrair_condicao_paciente_form(request.form)
                    
                    # Validação básica
                    if not all([nome, cpf, data_nascimento, logradouro, numero, ponto_embarque]):
                        flash('Por favor, preencha todos os campos obrigatórios (inclui logradouro, número e ponto de embarque)!', 'error')
                        return redirect(url_for('pacientes_cadastrar'))
                    if not tel_cel and not tel_res:
                        flash('Informe pelo menos um telefone (celular ou residencial)!', 'error')
                        return redirect(url_for('pacientes_cadastrar'))
                    if not ok_cond:
                        flash(erro_cond, 'error')
                        return redirect(url_for('pacientes_cadastrar'))
                    
                    # Validar CPF
                    cpf_fmt, cpf_erro = validar_e_formatar_cpf(cpf)
                    if cpf_erro:
                        flash(cpf_erro, 'error')
                        return redirect(url_for('pacientes_cadastrar'))
                    cpf = cpf_fmt
                    
                    # Verificar se CPF já existe
                    if Paciente.query.filter_by(cpf=cpf).first():
                        flash('CPF já cadastrado no sistema!', 'error')
                        return redirect(url_for('pacientes_cadastrar'))
                    
                    # Validar CNS se informado
                    if cartao_sus:
                        cns_fmt, cns_erro = validar_e_formatar_cns(cartao_sus)
                        if cns_erro:
                            flash(cns_erro, 'error')
                            return redirect(url_for('pacientes_cadastrar'))
                        cartao_sus = cns_fmt
                    
                    # Converter/validar data de nascimento
                    data_nascimento, dn_erro = validar_data_nascimento(data_nascimento, obrigatorio=True)
                    if dn_erro:
                        flash(dn_erro, 'error')
                        return redirect(url_for('pacientes_cadastrar'))
                    
                    # Criar novo paciente
                    paciente = Paciente(
                        nome=nome,
                        cpf=cpf,
                        telefone='',
                        data_nascimento=data_nascimento,
                        endereco=endereco,
                        cep=cep if cep else None,
                        logradouro=logradouro if logradouro else None,
                        numero=numero if numero else None,
                        bairro=bairro if bairro else None,
                        complemento=complemento if complemento else None,
                        ponto_embarque=ponto_embarque,
                        cartao_sus=cartao_sus if cartao_sus else None,
                        observacoes=observacoes if observacoes else None
                    )
                    aplicar_telefones_paciente(paciente, tel_cel, tel_res)
                    aplicar_condicao_paciente(paciente, dados_cond)
                    
                    db.session.add(paciente)
                    db.session.commit()
                    
                    flash(f'Paciente "{nome}" cadastrado com sucesso! Se precisar, cadastre o acompanhante abaixo.', 'success')
                    if paciente_necessita_acompanhante(paciente):
                        flash(
                            'Condição "Necessita acompanhante": cadastre pelo menos um acompanhante antes de agendar.',
                            'warning',
                        )
                    return redirect(url_for('pacientes_editar', paciente_id=paciente.id))
                    
                except Exception as e:
                    db.session.rollback()
                    flash(f'Erro ao cadastrar paciente: {str(e)}', 'error')
                    print(f"❌ Erro ao cadastrar paciente: {e}")
            
            # Gerar alertas de mensagens flash
            messages_html = ""
            for category, message in get_flashed_messages(with_categories=True):
                alert_class = f"alert-{category}"
                messages_html += f'<div class="alert {alert_class}">{message}</div>'
            
            # ===== FORMULÁRIO MELHORADO =====
            conteudo = f'''
            <div class="breadcrumb">
                <a href="{url_for('dashboard')}">Início</a> > 
                <a href="{url_for('pacientes')}">Pacientes</a> > 
                Cadastrar Novo Paciente
            </div>
            
            {html_page_header_ajuda(
                '📋 Cadastrar Novo Paciente',
                'Preencha os dados do paciente que será atendido pelo sistema de transporte',
                'paciente',
                AJUDA_PACIENTE,
                title_curto='Ajuda sobre o cadastro de paciente',
            )}
            
            {messages_html}
            
            <div class="card">
                <form method="POST">
                    <div class="form-row">
                        <div class="form-group">
                            <label for="nome">Nome Completo <span class="required-mark" aria-hidden="true">*</span></label>
                            <input type="text" id="nome" name="nome" required
                                   placeholder="Digite o nome completo" autocomplete="name">
                        </div>
                        <div class="form-group">
                            <label for="cpf">CPF <span class="required-mark" aria-hidden="true">*</span></label>
                            <input type="text" id="cpf" name="cpf" placeholder="000.000.000-00" maxlength="14" required
                                   inputmode="numeric" autocomplete="off">
                            <small id="cpf-status"></small>
                        </div>
                    </div>
                    
                    <div class="form-row">
                        <div class="form-group">
                            <label for="tel_cel">Telefone Celular</label>
                            <input type="tel" id="tel_cel" name="tel_cel" placeholder="(00) 00000-0000" maxlength="16"
                                   data-mask="phone" autocomplete="tel">
                        </div>
                        <div class="form-group">
                            <label for="tel_res">Telefone Residencial</label>
                            <input type="tel" id="tel_res" name="tel_res" placeholder="(00) 0000-0000" maxlength="15"
                                   data-mask="phone" autocomplete="tel">
                        </div>
                    </div>
                    <p class="field-hint" style="margin: -0.5rem 0 1rem;">
                        Informe pelo menos um telefone (celular ou residencial).
                    </p>
                    
                    <div class="form-row">
                        {html_campo_data_nascimento(name='data_nascimento', required=True)}
                        {html_campos_condicao_paciente()}
                    </div>
                    
                    <!-- SEÇÃO DE ENDEREÇO COM VIACEP -->
                    <div class="form-section">
                        <h4>🗺️ Endereço</h4>
                        
                        <div class="form-row">
                            <div class="form-group">
                                <label for="cep">CEP <span class="required-mark" aria-hidden="true">*</span></label>
                                <input type="text" id="cep" name="cep" placeholder="00000-000" maxlength="9"
                                       data-mask="cep" inputmode="numeric" onblur="buscarCEP()">
                                <small id="cep-status">Digite o CEP para buscar o endereço automaticamente</small>
                            </div>
                            <div class="form-group">
                                <label for="cidade">Cidade</label>
                                <input type="text" id="cidade" name="cidade" readonly placeholder="Preenchido pelo CEP">
                                <small>Preenchido automaticamente pelo CEP</small>
                            </div>
                        </div>
                        
                        <div class="form-row">
                            <div class="form-group">
                                <label for="logradouro">Logradouro <span class="required-mark" aria-hidden="true">*</span></label>
                                <input type="text" id="logradouro" name="logradouro" required
                                       placeholder="Rua, avenida, praça..."
                                       style="text-transform:uppercase;"
                                       oninput="this.value=this.value.toLocaleUpperCase('pt-BR'); montarEnderecoCompletoPaciente()">
                            </div>
                            <div class="form-group">
                                <label for="numero">Número <span class="required-mark" aria-hidden="true">*</span></label>
                                <input type="text" id="numero" name="numero" placeholder="Nº" required
                                       style="text-transform:uppercase;"
                                       oninput="this.value=this.value.toLocaleUpperCase('pt-BR'); montarEnderecoCompletoPaciente()">
                            </div>
                        </div>
                        
                        <div class="form-row">
                            <div class="form-group">
                                <label for="bairro">Bairro <span class="required-mark" aria-hidden="true">*</span></label>
                                <input type="text" id="bairro" name="bairro" required placeholder="Digite o bairro"
                                       style="text-transform:uppercase;"
                                       oninput="this.value=this.value.toLocaleUpperCase('pt-BR'); montarEnderecoCompletoPaciente()">
                            </div>
                            <div class="form-group">
                                <label for="complemento">Complemento</label>
                                <input type="text" id="complemento" name="complemento" placeholder="Ex: ATRÁS DA DELEGACIA, APTO 12..."
                                       style="text-transform:uppercase;"
                                       oninput="this.value=this.value.toLocaleUpperCase('pt-BR'); montarEnderecoCompletoPaciente()">
                            </div>
                        </div>
                        <div class="form-row">
                            <div class="form-group">
                                <label for="ponto_embarque">Ponto de Embarque <span class="required-mark" aria-hidden="true">*</span></label>
                                <input type="text" id="ponto_embarque" name="ponto_embarque" required
                                       placeholder="Informe o ponto de embarque do paciente"
                                       style="text-transform:uppercase;"
                                       oninput="this.value=this.value.toLocaleUpperCase('pt-BR')">
                            </div>
                        </div>
                        <input type="hidden" id="endereco" name="endereco" value="">
                        <small style="color:var(--gray-color);display:block;margin:-0.25rem 0 1rem;">
                            O endereço completo é montado automaticamente com logradouro, número, bairro e complemento.
                        </small>
                    </div>
                    
                    <div class="form-group">
                        <label for="cns">Cartão SUS</label>
                        <input type="text" id="cns" name="cns" placeholder="000 0000 0000 0000" maxlength="18" inputmode="numeric">
                        <small id="cns-status"></small>
                    </div>
                    
                    <div class="form-group">
                        <label for="observacoes">Necessidades Especiais / Observações</label>
                        <textarea id="observacoes" name="observacoes" rows="4" placeholder="Ex: Cadeirante, necessita maca, etc."></textarea>
                        <small>Após salvar, a ficha abre para cadastrar acompanhante (se o paciente precisar).</small>
                    </div>
                    
                    <div class="form-actions">
                        <button type="submit" class="btn btn-success">💾 Salvar Paciente</button>
                        <a href="{url_for('pacientes')}" class="btn btn-secondary">❌ Cancelar</a>
                    </div>
                </form>
            </div>
            
            {html_script_cpf_validacao()}
            {html_validacao_cns()}
            {html_script_condicao_paciente()}
            
            <script>
                function montarEnderecoCompletoPaciente() {{
                    const log = (document.getElementById('logradouro')?.value || '').trim();
                    const num = (document.getElementById('numero')?.value || '').trim();
                    const bai = (document.getElementById('bairro')?.value || '').trim();
                    const comp = (document.getElementById('complemento')?.value || '').trim();
                    const partes = [];
                    if (log) partes.push(log);
                    if (num) partes.push(num);
                    if (bai) partes.push(bai);
                    if (comp) partes.push(comp);
                    const el = document.getElementById('endereco');
                    if (el) el.value = partes.join(', ');
                }}

                // Máscara para CEP
                document.getElementById('cep').addEventListener('input', function(e) {{
                    let value = e.target.value.replace(/\\D/g, '');
                    if (value.length > 5) {{
                        value = value.replace(/^(\\d{{5}})(\\d+)/, '$1-$2');
                    }}
                    e.target.value = value;
                }});
                
                // Função para buscar CEP via ViaCEP
                async function buscarCEP() {{
                    const cepInput = document.getElementById('cep');
                    const statusElement = document.getElementById('cep-status');
                    const cep = cepInput.value.replace(/\\D/g, '');
                    
                    // Resetar campos preenchidos pelo CEP (mantém o número digitado)
                    document.getElementById('logradouro').value = '';
                    document.getElementById('bairro').value = '';
                    document.getElementById('cidade').value = '';
                    
                    if (cep.length !== 8) {{
                        statusElement.textContent = 'CEP deve ter 8 dígitos';
                        statusElement.style.color = 'var(--danger-color)';
                        return;
                    }}
                    
                    statusElement.textContent = '🔍 Buscando CEP...';
                    statusElement.style.color = 'var(--primary-color)';
                    
                    try {{
                        const response = await fetch(`https://viacep.com.br/ws/${{cep}}/json/`);
                        const data = await response.json();
                        
                        if (data.erro) {{
                            statusElement.textContent = '❌ CEP não encontrado';
                            statusElement.style.color = 'var(--danger-color)';
                            return;
                        }}
                        
                        const logEl = document.getElementById('logradouro');
                        const baiEl = document.getElementById('bairro');
                        if (logEl) logEl.value = (data.logradouro || '').toLocaleUpperCase('pt-BR');
                        if (baiEl) baiEl.value = (data.bairro || '').toLocaleUpperCase('pt-BR');
                        document.getElementById('cidade').value = `${{data.localidade}} - ${{data.uf}}` || '';
                        montarEnderecoCompletoPaciente();
                        
                        statusElement.textContent = '✅ CEP encontrado! Preencha o número.';
                        statusElement.style.color = 'var(--success-color)';
                        document.getElementById('numero').focus();
                        
                    }} catch (error) {{
                        console.error('Erro ao buscar CEP:', error);
                        statusElement.textContent = '❌ Erro ao buscar CEP. Verifique sua conexão.';
                        statusElement.style.color = 'var(--danger-color)';
                    }}
                }}

                document.querySelector('form').addEventListener('submit', function() {{
                    montarEnderecoCompletoPaciente();
                }});
                
                // Máscara para Celular
                document.getElementById('tel_cel').addEventListener('input', function(e) {{
                    let value = e.target.value.replace(/\\D/g, '').slice(0, 11);
                    if (value.length <= 2) {{
                        value = value ? '(' + value : '';
                    }} else if (value.length <= 7) {{
                        value = '(' + value.slice(0, 2) + ') ' + value.slice(2);
                    }} else {{
                        value = '(' + value.slice(0, 2) + ') ' + value.slice(2, 7) + '-' + value.slice(7);
                    }}
                    e.target.value = value;
                }});
                
                // Máscara para Telefone Fixo
                document.getElementById('tel_res').addEventListener('input', function(e) {{
                    let value = e.target.value.replace(/\\D/g, '').slice(0, 10);
                    if (value.length <= 2) {{
                        value = value ? '(' + value : '';
                    }} else if (value.length <= 6) {{
                        value = '(' + value.slice(0, 2) + ') ' + value.slice(2);
                    }} else {{
                        value = '(' + value.slice(0, 2) + ') ' + value.slice(2, 6) + '-' + value.slice(6);
                    }}
                    e.target.value = value;
                }});
            </script>
            
            '''
            
            return gerar_layout_base("Cadastrar Paciente", conteudo, "pacientes")
    
    @app.route('/pacientes/editar/<int:paciente_id>', methods=['GET', 'POST'])
    @login_required
    def pacientes_editar(paciente_id):
        paciente = db.session.get(Paciente, paciente_id)
        if not paciente:
            flash('Paciente não encontrado!', 'error')
            return redirect(url_for('pacientes'))
        
        if request.method == 'POST':
            try:
                nome = request.form.get('nome', '').strip()
                cpf = request.form.get('cpf', '').strip()
                tel_cel = request.form.get('tel_cel', '').strip()
                tel_res = request.form.get('tel_res', '').strip()
                data_nascimento = request.form.get('data_nascimento')
                cep = request.form.get('cep', '').strip()
                logradouro, numero, bairro, complemento, endereco = montar_endereco_paciente_de_form(request.form)
                ponto_embarque = (
                    request.form.get('ponto_embarque', '').strip()
                    or request.form.get('ponto_referencia', '').strip()
                )
                cartao_sus = request.form.get('cns', '').strip()
                observacoes = request.form.get('observacoes', '').strip()
                ok_cond, erro_cond, dados_cond = extrair_condicao_paciente_form(request.form)
                
                if not all([nome, cpf, data_nascimento, logradouro, numero, ponto_embarque]):
                    flash('Por favor, preencha todos os campos obrigatórios (inclui logradouro, número e ponto de embarque)!', 'error')
                    return redirect(url_for('pacientes_editar', paciente_id=paciente_id))
                if not tel_cel and not tel_res:
                    flash('Informe pelo menos um telefone (celular ou residencial)!', 'error')
                    return redirect(url_for('pacientes_editar', paciente_id=paciente_id))
                if not ok_cond:
                    flash(erro_cond, 'error')
                    return redirect(url_for('pacientes_editar', paciente_id=paciente_id))
                
                # Validar CPF
                cpf_fmt, cpf_erro = validar_e_formatar_cpf(cpf)
                if cpf_erro:
                    flash(cpf_erro, 'error')
                    return redirect(url_for('pacientes_editar', paciente_id=paciente_id))
                cpf = cpf_fmt
                
                paciente_existente = Paciente.query.filter_by(cpf=cpf).first()
                if paciente_existente and paciente_existente.id != paciente_id:
                    flash('CPF já cadastrado para outro paciente!', 'error')
                    return redirect(url_for('pacientes_editar', paciente_id=paciente_id))
                
                # Validar CNS se informado
                if cartao_sus:
                    cns_fmt, cns_erro = validar_e_formatar_cns(cartao_sus)
                    if cns_erro:
                        flash(cns_erro, 'error')
                        return redirect(url_for('pacientes_editar', paciente_id=paciente_id))
                    cartao_sus = cns_fmt
                
                data_nasc, dn_erro = validar_data_nascimento(data_nascimento, obrigatorio=True)
                if dn_erro:
                    flash(dn_erro, 'error')
                    return redirect(url_for('pacientes_editar', paciente_id=paciente_id))
                
                paciente.nome = nome
                paciente.cpf = cpf
                aplicar_telefones_paciente(paciente, tel_cel, tel_res)
                paciente.data_nascimento = data_nasc
                paciente.endereco = endereco
                paciente.cep = cep if cep else None
                paciente.logradouro = logradouro if logradouro else None
                paciente.numero = numero if numero else None
                paciente.bairro = bairro if bairro else None
                paciente.complemento = complemento if complemento else None
                paciente.ponto_embarque = ponto_embarque
                paciente.cartao_sus = cartao_sus if cartao_sus else None
                paciente.observacoes = observacoes if observacoes else None
                aplicar_condicao_paciente(paciente, dados_cond)
                
                db.session.commit()
                flash(f'Paciente "{nome}" atualizado com sucesso!', 'success')
                if paciente_necessita_acompanhante(paciente):
                    aviso = validar_acompanhantes_cadastrados_para_condicao(paciente)
                    if aviso:
                        flash(aviso + ' Cadastre abaixo.', 'warning')
                        return redirect(url_for('pacientes_editar', paciente_id=paciente_id))
                return redirect(url_for('pacientes'))
                
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao atualizar paciente: {str(e)}', 'error')
        
        messages_html = ""
        for category, message in get_flashed_messages(with_categories=True):
            alert_class = f"alert-{category}"
            messages_html += f'<div class="alert {alert_class}">{message}</div>'
        
        tel_cel_val, tel_res_val = telefones_paciente_form(paciente)
        
        conteudo = f'''
        <div class="breadcrumb">
            <a href="{url_for('dashboard')}">Início</a> > 
            <a href="{url_for('pacientes')}">Pacientes</a> > Editar
        </div>
        
        <div class="page-header">
            <h2>✏️ Editar Paciente {html_id_badge(paciente.id)}</h2>
            <p>Atualize as informações do paciente {paciente.nome}</p>
        </div>
        
        {messages_html}
        
        <div class="card">
            <form method="POST">
                <div class="form-row">
                    <div class="form-group">
                        <label for="nome">Nome Completo <span class="required-mark" aria-hidden="true">*</span></label>
                        <input type="text" id="nome" name="nome" value="{paciente.nome}" required
                               placeholder="Digite o nome completo" autocomplete="name">
                    </div>
                    <div class="form-group">
                        <label for="cpf">CPF <span class="required-mark" aria-hidden="true">*</span></label>
                        <input type="text" id="cpf" name="cpf" value="{paciente.cpf}" maxlength="14" required
                               placeholder="000.000.000-00" inputmode="numeric" autocomplete="off">
                        <small id="cpf-status"></small>
                    </div>
                </div>
                
                <div class="form-row">
                    <div class="form-group">
                        <label for="tel_cel">Telefone Celular</label>
                        <input type="tel" id="tel_cel" name="tel_cel" value="{tel_cel_val}" placeholder="(00) 00000-0000" maxlength="16"
                               data-mask="phone" autocomplete="tel">
                    </div>
                    <div class="form-group">
                        <label for="tel_res">Telefone Residencial</label>
                        <input type="tel" id="tel_res" name="tel_res" value="{tel_res_val}" placeholder="(00) 0000-0000" maxlength="15"
                               data-mask="phone" autocomplete="tel">
                    </div>
                </div>
                
                <div class="form-row">
                    {html_campo_data_nascimento(
                        name='data_nascimento',
                        valor=paciente.data_nascimento,
                        required=True,
                    )}
                    {html_campos_condicao_paciente(paciente)}
                </div>
                
                <!-- SEÇÃO DE ENDEREÇO -->
                <div class="form-section">
                    <h4>🗺️ Endereço</h4>
                    
                    <div class="form-row">
                        <div class="form-group">
                            <label for="cep">CEP</label>
                            <input type="text" id="cep" name="cep" value="{paciente.cep or ''}" maxlength="9"
                                   placeholder="00000-000" data-mask="cep" inputmode="numeric" onblur="buscarCEP()">
                            <small id="cep-status">Digite o CEP para buscar o endereço</small>
                        </div>
                        <div class="form-group">
                            <label for="cidade">Cidade</label>
                            <input type="text" id="cidade" name="cidade" readonly placeholder="Preenchido pelo CEP" value="">
                        </div>
                    </div>
                    
                    <div class="form-row">
                        <div class="form-group">
                            <label for="logradouro">Logradouro <span class="required-mark" aria-hidden="true">*</span></label>
                            <input type="text" id="logradouro" name="logradouro" value="{paciente.logradouro or ''}" required
                                   placeholder="Rua, avenida, praça..."
                                   style="text-transform:uppercase;"
                                   oninput="this.value=this.value.toLocaleUpperCase('pt-BR'); montarEnderecoCompletoPaciente()">
                        </div>
                        <div class="form-group">
                            <label for="numero">Número <span class="required-mark" aria-hidden="true">*</span></label>
                            <input type="text" id="numero" name="numero" value="{paciente.numero or ''}" placeholder="Nº" required
                                   style="text-transform:uppercase;"
                                   oninput="this.value=this.value.toLocaleUpperCase('pt-BR'); montarEnderecoCompletoPaciente()">
                        </div>
                    </div>
                    
                    <div class="form-row">
                        <div class="form-group">
                            <label for="bairro">Bairro <span class="required-mark" aria-hidden="true">*</span></label>
                            <input type="text" id="bairro" name="bairro" value="{paciente.bairro or ''}" required placeholder="Digite o bairro"
                                   style="text-transform:uppercase;"
                                   oninput="this.value=this.value.toLocaleUpperCase('pt-BR'); montarEnderecoCompletoPaciente()">
                        </div>
                        <div class="form-group">
                            <label for="complemento">Complemento</label>
                            <input type="text" id="complemento" name="complemento" value="{paciente.complemento or ''}"
                                   placeholder="Ex: ATRÁS DA DELEGACIA, APTO 12..."
                                   style="text-transform:uppercase;"
                                   oninput="this.value=this.value.toLocaleUpperCase('pt-BR'); montarEnderecoCompletoPaciente()">
                        </div>
                    </div>
                    <div class="form-row">
                        <div class="form-group">
                            <label for="ponto_embarque">Ponto de Embarque <span class="required-mark" aria-hidden="true">*</span></label>
                            <input type="text" id="ponto_embarque" name="ponto_embarque" required
                                   value="{html_esc(ponto_embarque_do_paciente(paciente))}"
                                   placeholder="Informe o ponto de embarque do paciente"
                                   style="text-transform:uppercase;"
                                   oninput="this.value=this.value.toLocaleUpperCase('pt-BR')">
                        </div>
                    </div>
                    <input type="hidden" id="endereco" name="endereco" value="{paciente.endereco or ''}">
                    <small style="color:var(--gray-color);display:block;margin:-0.25rem 0 1rem;">
                        O endereço completo é montado automaticamente com logradouro, número, bairro e complemento.
                    </small>
                </div>
                
                <div class="form-row">
                    <div class="form-group">
                        <label for="cns">Cartão SUS</label>
                        <input type="text" id="cns" name="cns" value="{paciente.cartao_sus or ''}" maxlength="18"
                               placeholder="000 0000 0000 0000" inputmode="numeric">
                        <small id="cns-status"></small>
                    </div>
                </div>
                
                <div class="form-group">
                    <label for="observacoes">Necessidades Especiais / Observações</label>
                    <textarea id="observacoes" name="observacoes" rows="3" placeholder="Ex: Cadeirante, necessita maca, acompanhante, etc.">{paciente.observacoes or ''}</textarea>
                </div>
                
                <div class="form-actions">
                    <button type="submit" class="btn btn-success">💾 Salvar</button>
                    <a href="{url_for('pacientes')}" class="btn btn-secondary">❌ Cancelar</a>
                </div>
            </form>
        </div>
        
        {html_secao_acompanhantes_paciente(paciente)}
        
        {html_script_cpf_validacao()}
        {html_validacao_cns()}
        {html_script_condicao_paciente()}
        
        <script>
            function montarEnderecoCompletoPaciente() {{
                const log = (document.getElementById('logradouro')?.value || '').trim();
                const num = (document.getElementById('numero')?.value || '').trim();
                const bai = (document.getElementById('bairro')?.value || '').trim();
                const comp = (document.getElementById('complemento')?.value || '').trim();
                const partes = [];
                if (log) partes.push(log);
                if (num) partes.push(num);
                if (bai) partes.push(bai);
                if (comp) partes.push(comp);
                const el = document.getElementById('endereco');
                if (el) el.value = partes.join(', ');
            }}

            async function buscarCEP() {{
                const cepInput = document.getElementById('cep');
                const statusElement = document.getElementById('cep-status');
                const cep = cepInput.value.replace(/\\D/g, '');
                
                document.getElementById('logradouro').value = '';
                document.getElementById('bairro').value = '';
                document.getElementById('cidade').value = '';
                
                if (cep.length !== 8) return;
                
                statusElement.textContent = '🔍 Buscando CEP...';
                statusElement.style.color = 'var(--primary-color)';
                
                try {{
                    const response = await fetch(`https://viacep.com.br/ws/${{cep}}/json/`);
                    const data = await response.json();
                    
                    if (data.erro) {{
                        statusElement.textContent = '❌ CEP não encontrado';
                        statusElement.style.color = 'var(--danger-color)';
                        return;
                    }}
                    
                    document.getElementById('logradouro').value = (data.logradouro || '').toLocaleUpperCase('pt-BR');
                    document.getElementById('bairro').value = (data.bairro || '').toLocaleUpperCase('pt-BR');
                    document.getElementById('cidade').value = `${{data.localidade}} - ${{data.uf}}` || '';
                    montarEnderecoCompletoPaciente();
                    
                    statusElement.textContent = '✅ CEP encontrado! Preencha o número.';
                    statusElement.style.color = 'var(--success-color)';
                    document.getElementById('numero').focus();
                    
                }} catch (error) {{
                    statusElement.textContent = '❌ Erro ao buscar CEP';
                    statusElement.style.color = 'var(--danger-color)';
                }}
            }}

            document.querySelector('form').addEventListener('submit', function() {{
                montarEnderecoCompletoPaciente();
            }});
            montarEnderecoCompletoPaciente();
            
            document.getElementById('cep').addEventListener('input', function(e) {{
                let value = e.target.value.replace(/\\D/g, '');
                if (value.length > 5) {{
                    value = value.replace(/^(\\d{{5}})(\\d+)/, '$1-$2');
                }}
                e.target.value = value;
            }});
            
            document.getElementById('tel_cel').addEventListener('input', function(e) {{
                let value = e.target.value.replace(/\\D/g, '').slice(0, 11);
                if (value.length <= 2) {{
                    value = value ? '(' + value : '';
                }} else if (value.length <= 7) {{
                    value = '(' + value.slice(0, 2) + ') ' + value.slice(2);
                }} else {{
                    value = '(' + value.slice(0, 2) + ') ' + value.slice(2, 7) + '-' + value.slice(7);
                }}
                e.target.value = value;
            }});
            
            document.getElementById('tel_res').addEventListener('input', function(e) {{
                let value = e.target.value.replace(/\\D/g, '').slice(0, 10);
                if (value.length <= 2) {{
                    value = value ? '(' + value : '';
                }} else if (value.length <= 6) {{
                    value = '(' + value.slice(0, 2) + ') ' + value.slice(2);
                }} else {{
                    value = '(' + value.slice(0, 2) + ') ' + value.slice(2, 6) + '-' + value.slice(6);
                }}
                e.target.value = value;
            }});
        </script>
        '''
        return gerar_layout_base("Editar Paciente", conteudo, "pacientes")
    
    @app.route('/pacientes/<int:paciente_id>/acompanhantes/novo', methods=['POST'])
    @login_required
    def pacientes_acompanhante_novo(paciente_id):
        paciente = db.session.get(Paciente, paciente_id)
        if not paciente:
            flash('Paciente não encontrado!', 'error')
            return redirect(url_for('pacientes'))

        nomes = request.form.getlist('ac_nome')
        parentescos = request.form.getlist('ac_parentesco')
        parentescos_outros = request.form.getlist('ac_parentesco_outros')
        nomes_nao_info = request.form.getlist('ac_nome_nao_informado')
        rgs = request.form.getlist('ac_rg')
        telefones = request.form.getlist('ac_telefone')
        nascimentos = request.form.getlist('ac_data_nascimento')

        # Compat: um único envio sem listas
        if not nomes and request.form.get('ac_nome'):
            nomes = [request.form.get('ac_nome')]
            parentescos = [request.form.get('ac_parentesco', '')]
            parentescos_outros = [request.form.get('ac_parentesco_outros', '')]
            nomes_nao_info = [request.form.get('ac_nome_nao_informado', '0')]
            rgs = [request.form.get('ac_rg', '')]
            telefones = [request.form.get('ac_telefone', '')]
            nascimentos = [request.form.get('ac_data_nascimento', '')]

        salvos = []
        erros = []
        for i, nome in enumerate(nomes):
            flag = nomes_nao_info[i] if i < len(nomes_nao_info) else '0'
            if not (nome or '').strip() and str(flag).strip() not in ('1', 'true', 'on', 'yes', 'sim'):
                continue
            form_i = {
                'ac_nome': nome,
                'ac_nome_nao_informado': flag,
                'ac_parentesco': parentescos[i] if i < len(parentescos) else '',
                'ac_parentesco_outros': parentescos_outros[i] if i < len(parentescos_outros) else '',
                'ac_rg': rgs[i] if i < len(rgs) else '',
                'ac_telefone': telefones[i] if i < len(telefones) else '',
                'ac_data_nascimento': nascimentos[i] if i < len(nascimentos) else '',
            }
            ac, erro = criar_acompanhante_de_form(paciente_id, form_i)
            if erro:
                erros.append(erro)
                continue
            db.session.add(ac)
            salvos.append(ac.nome)

        if not salvos and not erros:
            ja_tem = listar_acompanhantes_paciente(paciente_id, somente_ativos=True)
            if ja_tem:
                flash(
                    'Nenhum novo acompanhante foi informado. '
                    'Os já cadastrados na ficha permanecem — use Editar na tabela para alterá-los.',
                    'info',
                )
            elif paciente_necessita_acompanhante(paciente):
                flash('Informe ao menos o nome de um acompanhante.', 'error')
            else:
                flash(
                    'Preencha nome e data de nascimento para cadastrar um acompanhante.',
                    'warning',
                )
            return redirect(url_for('pacientes_editar', paciente_id=paciente_id))

        try:
            if salvos:
                db.session.commit()
                if len(salvos) == 1:
                    flash(f'Acompanhante "{salvos[0]}" cadastrado!', 'success')
                else:
                    flash(f'{len(salvos)} acompanhantes cadastrados: {", ".join(salvos)}.', 'success')
            else:
                db.session.rollback()
            for e in erros:
                flash(e, 'error')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao salvar acompanhante(s): {e}', 'error')
        return redirect(url_for('pacientes_editar', paciente_id=paciente_id))

    @app.route('/pacientes/<int:paciente_id>/acompanhantes/<int:acompanhante_id>/excluir')
    @login_required
    def pacientes_acompanhante_excluir(paciente_id, acompanhante_id):
        ac = db.session.get(Acompanhante, acompanhante_id)
        if not ac or ac.paciente_id != paciente_id:
            flash('Acompanhante não encontrado!', 'error')
            return redirect(url_for('pacientes_editar', paciente_id=paciente_id))
        try:
            # Não permite desativar o último se a condição exige acompanhante
            restantes = [
                a for a in listar_acompanhantes_paciente(paciente_id, somente_ativos=True)
                if a.id != ac.id
            ]
            if paciente_necessita_acompanhante(
                db.session.get(Paciente, paciente_id)
            ) and not restantes:
                flash(
                    'Não é possível desativar o único acompanhante enquanto a condição '
                    'do paciente for "Necessita acompanhante".',
                    'error',
                )
                return redirect(url_for('pacientes_editar', paciente_id=paciente_id))
            ac.ativo = False
            db.session.commit()
            flash(f'Acompanhante "{ac.nome}" desativado.', 'warning')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro: {e}', 'error')
        return redirect(url_for('pacientes_editar', paciente_id=paciente_id))

    @app.route('/api/pacientes/<int:paciente_id>/resumo', methods=['GET'])
    @login_required
    def api_paciente_resumo(paciente_id):
        """Dados essenciais do paciente para preencher agendamento (origem)."""
        paciente = db.session.get(Paciente, paciente_id)
        if not paciente or not paciente.ativo:
            return jsonify({'ok': False, 'erro': 'Paciente não encontrado'}), 404
        end = endereco_paciente_para_campos(paciente)
        return jsonify({
            'ok': True,
            'id': paciente.id,
            'nome': paciente.nome,
            'cpf': paciente.cpf,
            'cep': end['cep'],
            'logradouro': end['logradouro'],
            'numero': end['numero'],
            'bairro': end['bairro'],
            'endereco': paciente.endereco or '',
            'ponto_embarque': ponto_embarque_do_paciente(paciente),
            'necessita_acompanhante': paciente_necessita_acompanhante(paciente),
        })

    @app.route('/api/pacientes/<int:paciente_id>/acompanhantes', methods=['GET'])
    @login_required
    def api_paciente_acompanhantes(paciente_id):
        paciente = db.session.get(Paciente, paciente_id)
        if not paciente:
            return jsonify({'erro': 'Paciente não encontrado'}), 404
        lista = [acompanhante_para_dict(ac) for ac in listar_acompanhantes_paciente(paciente_id, somente_ativos=True)]
        return jsonify({
            'paciente_id': paciente_id,
            'necessita_acompanhante': paciente_necessita_acompanhante(paciente),
            'acompanhantes': lista,
        })

    @app.route('/api/cnes/cidades', methods=['GET'])
    @login_required
    def api_cnes_cidades():
        cidades = listar_cidades_destino_cnes()
        return jsonify({
            'ok': True,
            'cidades': cidades,
            'total': qtd_cidades_destino_cnes(),
        })

    @app.route('/api/cnes/estabelecimentos', methods=['GET'])
    @login_required
    def api_cnes_estabelecimentos():
        cidade = (request.args.get('cidade') or '').strip()
        q = (request.args.get('q') or '').strip()
        sync = (request.args.get('sync') or '1') == '1'
        forcar = (request.args.get('forcar') or '0') == '1'
        try:
            limit = min(int(request.args.get('limit') or 120), 300)
        except (TypeError, ValueError):
            limit = 120
        if not cidade:
            return jsonify({'ok': False, 'mensagem': 'Informe a cidade.', 'estabelecimentos': []}), 400
        if not cidade_cnes_por_nome(cidade):
            return jsonify({'ok': False, 'mensagem': 'Cidade não está na lista predefinida.', 'estabelecimentos': []}), 400

        sync_info = {'ok': True, 'fonte': 'cache', 'mensagem': ''}
        if sync:
            sync_info = sincronizar_cnes_cidade(db, CnesEstabelecimento, cidade, forcar=forcar)
            if not sync_info.get('ok'):
                # ainda tenta listar o que houver no cache
                items = listar_estabelecimentos_cache(CnesEstabelecimento, cidade, q=q, limit=limit)
                if not items:
                    return jsonify({
                        'ok': False,
                        'mensagem': sync_info.get('mensagem') or 'Falha ao consultar CNES',
                        'estabelecimentos': [],
                        'fonte': 'erro',
                    })
                return jsonify({
                    'ok': True,
                    'estabelecimentos': items,
                    'total': len(items),
                    'total_cache': sync_info.get('sincronizados'),
                    'fonte': 'cache_parcial',
                    'mensagem': sync_info.get('mensagem'),
                })

        info = cidade_cnes_por_nome(cidade)
        total_cache = CnesEstabelecimento.query.filter_by(codigo_municipio=info['ibge6']).count()
        items = listar_estabelecimentos_cache(CnesEstabelecimento, cidade, q=q, limit=limit)
        return jsonify({
            'ok': True,
            'estabelecimentos': items,
            'total': len(items),
            'total_cache': total_cache,
            'fonte': sync_info.get('fonte') or 'cache',
            'mensagem': sync_info.get('mensagem') or '',
            'cidade': cidade,
        })

    @app.route('/api/cnes/sincronizar', methods=['POST'])
    @login_required
    def api_cnes_sincronizar():
        data = request.get_json(silent=True) or {}
        cidade = (data.get('cidade') or request.form.get('cidade') or '').strip()
        forcar = bool(data.get('forcar') or request.form.get('forcar'))
        if not cidade:
            return jsonify({'ok': False, 'mensagem': 'Informe a cidade.'}), 400
        resultado = sincronizar_cnes_cidade(db, CnesEstabelecimento, cidade, forcar=forcar)
        status = 200 if resultado.get('ok') else 502
        return jsonify(resultado), status

    @app.route('/pacientes/excluir/<int:paciente_id>')
    @login_required
    def pacientes_excluir(paciente_id):
        try:
            paciente = db.session.get(Paciente, paciente_id)
            if not paciente:
                flash('Paciente não encontrado!', 'error')
                return redirect(url_for('pacientes'))
            nome = paciente.nome
            agendamentos_count = Agendamento.query.filter_by(paciente_id=paciente_id).count()
            
            if agendamentos_count > 0:
                paciente.ativo = False
                db.session.commit()
                flash(f'Paciente "{nome}" desativado (possui {agendamentos_count} agendamento(s)).', 'warning')
            else:
                db.session.delete(paciente)
                db.session.commit()
                flash(f'Paciente "{nome}" excluído!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro: {str(e)}', 'error')
        
        return redirect(url_for('pacientes'))
            
    # ===== ACOMPANHANTES (menu Cadastros) =====
    @app.route('/acompanhantes')
    @login_required
    def acompanhantes():
        from html import escape

        filtros = obter_filtros_acompanhantes_request()
        page, per_page = obter_paginacao_request()
        query = montar_query_acompanhantes(filtros)
        lista, total, page = listar_paginado(
            query, page, per_page, Paciente.nome, Acompanhante.nome
        )
        exibidos = len(lista)
        filtros_url = {k: v for k, v in filtros.items() if v}
        filtros_html = gerar_filtros_acompanhantes(filtros, total, exibidos, per_page)
        paginacao_html = gerar_paginacao('acompanhantes', page, per_page, total, filtros_url)
        botoes_impressao = gerar_botoes_impressao(
            'acompanhantes_imprimir', filtros_url, page, per_page
        )

        messages_html = ""
        for category, message in get_flashed_messages(with_categories=True):
            messages_html += f'<div class="alert alert-{category}">{message}</div>'

        rows = ""
        cards_mobile = ""
        for ac in lista:
            pac = ac.paciente
            idade_ac = formatar_idade_exibir(ac.data_nascimento) if ac.data_nascimento else '—'
            idade_pac = (
                formatar_idade_exibir(pac.data_nascimento)
                if pac and pac.data_nascimento else '—'
            )
            acoes = html_acoes_toolbar(
                html_acao_icone(
                    'ti-edit',
                    'Editar acompanhante',
                    href=url_for('acompanhantes_editar', acompanhante_id=ac.id),
                    variant='editar',
                ),
                html_acao_icone(
                    'ti-user-off',
                    'Desativar acompanhante',
                    href=url_for('acompanhantes_excluir', acompanhante_id=ac.id),
                    variant='excluir',
                    confirm_msg='Desativar este acompanhante?',
                )
            )
            pac_nome = pac.nome if pac else '—'
            pac_link = (
                f'<a href="{url_for("pacientes_editar", paciente_id=pac.id)}">{escape(pac_nome)}</a>'
                if pac else escape(pac_nome)
            )
            rows += f'''
            <tr>
              {html_td_id(ac.id)}
              <td style="padding:0.75rem;border-bottom:1px solid var(--border-color);">{escape(ac.parentesco or '—')}</td>
              <td style="padding:0.75rem;border-bottom:1px solid var(--border-color);">{escape(ac.nome or '')}</td>
              <td style="padding:0.75rem;border-bottom:1px solid var(--border-color);">{escape(idade_ac)}</td>
              <td style="padding:0.75rem;border-bottom:1px solid var(--border-color);">{pac_link}</td>
              <td style="padding:0.75rem;border-bottom:1px solid var(--border-color);">{escape(idade_pac)}</td>
              <td style="padding:0.75rem;border-bottom:1px solid var(--border-color);">{escape(format_rg(ac.rg) if ac.rg else '—')}</td>
              <td style="padding:0.75rem;border-bottom:1px solid var(--border-color);">{escape(ac.telefone or '—')}</td>
              <td style="padding:0.75rem;border-bottom:1px solid var(--border-color);text-align:center;">{acoes}</td>
            </tr>'''
            cards_mobile += html_mobile_card(
                title=f'#{ac.id} {ac.nome or "—"}',
                meta=escape(ac.parentesco or '—'),
                rows=[
                    ('ID', f'<strong>{ac.id}</strong>'),
                    ('Idade', escape(idade_ac)),
                    ('Paciente', pac_link),
                    ('Idade paciente', escape(idade_pac)),
                    ('RG', escape(format_rg(ac.rg) if ac.rg else '—')),
                    ('Telefone', escape(ac.telefone or '—')),
                ],
                acoes_html=acoes,
            )

        tabela = f'''
        <div class="card">
          <div style="display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:0.75rem;margin-bottom:1rem;">
            <h3 style="color:var(--primary-color);margin:0;">📋 Acompanhantes cadastrados ({format_numero_br(total)})</h3>
            {botoes_impressao}
          </div>
          <div class="stp-list-desktop table-container">
            <table style="width:100%;border-collapse:collapse;">
              <thead>
                <tr style="background:var(--color-95);">
                  {html_th_id()}
                  <th style="padding:0.75rem;text-align:left;border-bottom:2px solid var(--primary-color);">Parentesco</th>
                  <th style="padding:0.75rem;text-align:left;border-bottom:2px solid var(--primary-color);">Acompanhante</th>
                  <th style="padding:0.75rem;text-align:left;border-bottom:2px solid var(--primary-color);">Idade</th>
                  <th style="padding:0.75rem;text-align:left;border-bottom:2px solid var(--primary-color);">Paciente</th>
                  <th style="padding:0.75rem;text-align:left;border-bottom:2px solid var(--primary-color);">Idade Pac.</th>
                  <th style="padding:0.75rem;text-align:left;border-bottom:2px solid var(--primary-color);">RG</th>
                  <th style="padding:0.75rem;text-align:left;border-bottom:2px solid var(--primary-color);">Telefone</th>
                  <th style="padding:0.75rem;text-align:center;border-bottom:2px solid var(--primary-color);">Ações</th>
                </tr>
              </thead>
              <tbody>
                {rows if rows else '<tr><td colspan="9" style="padding:1rem;text-align:center;color:#666;">Nenhum acompanhante encontrado</td></tr>'}
              </tbody>
            </table>
          </div>
          <div class="stp-list-mobile">{cards_mobile if cards_mobile else '<p style="color:#666;margin:0;">Nenhum acompanhante encontrado</p>'}</div>
          {paginacao_html}
        </div>
        '''

        conteudo = f'''
        <div class="page-header">
          <h2>🧑‍🤝‍🧑 Acompanhantes</h2>
          <p>Cadastro de acompanhantes vinculados aos pacientes (antes do agendamento)</p>
          <div style="margin-top:1rem;">
            <a href="{url_for('acompanhantes_novo')}" class="btn">➕ Cadastrar Acompanhante</a>
          </div>
        </div>
        {messages_html}
        {filtros_html}
        {tabela}
        '''
        return gerar_layout_base("Acompanhantes", conteudo, "acompanhantes")

    @app.route('/acompanhantes/imprimir')
    @login_required
    def acompanhantes_imprimir():
        filtros = obter_filtros_acompanhantes_request()
        page, per_page = obter_paginacao_request()
        paginas = request.args.get('paginas', 'atual')
        query = montar_query_acompanhantes(filtros)
        lista, total, total_pages, pag_ini, pag_fim = buscar_lista_impressao(
            query, page, per_page, paginas, Paciente.nome, Acompanhante.nome
        )
        return gerar_html_impressao_acompanhantes(lista, filtros)

    @app.route('/acompanhantes/novo', methods=['GET', 'POST'])
    @login_required
    def acompanhantes_novo():
        from html import escape

        paciente_pre = request.args.get('paciente_id', type=int) or request.form.get('paciente_id', type=int)
        filtros = obter_filtros_paciente_vinculo_request()
        tem_filtro = filtros_tem_valores(filtros)
        total_ativos = Paciente.query.filter_by(ativo=True).count()
        LIMITE_SELECT = 300

        if request.method == 'POST':
            paciente_id = request.form.get('paciente_id', type=int)
            if not paciente_id:
                flash('Selecione o paciente ao qual o acompanhante pertence.', 'error')
                return redirect(url_for('acompanhantes_novo'))
            paciente = db.session.get(Paciente, paciente_id)
            if not paciente or not paciente.ativo:
                flash('Paciente inválido.', 'error')
                return redirect(url_for('acompanhantes_novo'))

            nomes = request.form.getlist('ac_nome')
            parentescos = request.form.getlist('ac_parentesco')
            parentescos_outros = request.form.getlist('ac_parentesco_outros')
            nomes_nao_info = request.form.getlist('ac_nome_nao_informado')
            rgs = request.form.getlist('ac_rg')
            telefones = request.form.getlist('ac_telefone')
            nascimentos = request.form.getlist('ac_data_nascimento')

            salvos = []
            erros = []
            for i, nome in enumerate(nomes):
                flag = nomes_nao_info[i] if i < len(nomes_nao_info) else '0'
                if not (nome or '').strip() and str(flag).strip() not in ('1', 'true', 'on', 'yes', 'sim'):
                    continue
                form_i = {
                    'ac_nome': nome,
                    'ac_nome_nao_informado': flag,
                    'ac_parentesco': parentescos[i] if i < len(parentescos) else '',
                    'ac_parentesco_outros': parentescos_outros[i] if i < len(parentescos_outros) else '',
                    'ac_rg': rgs[i] if i < len(rgs) else '',
                    'ac_telefone': telefones[i] if i < len(telefones) else '',
                    'ac_data_nascimento': nascimentos[i] if i < len(nascimentos) else '',
                }
                ac, erro = criar_acompanhante_de_form(paciente_id, form_i)
                if erro:
                    erros.append(erro)
                    continue
                db.session.add(ac)
                salvos.append(ac.nome)

            if not salvos and not erros:
                flash('Informe ao menos o nome de um acompanhante.', 'error')
                return redirect(url_for('acompanhantes_novo', paciente_id=paciente_id))

            try:
                if salvos:
                    db.session.commit()
                    if len(salvos) == 1:
                        flash(f'Acompanhante "{salvos[0]}" cadastrado para {paciente.nome}!', 'success')
                    else:
                        flash(f'{len(salvos)} acompanhantes cadastrados para {paciente.nome}.', 'success')
                else:
                    db.session.rollback()
                for e in erros:
                    flash(e, 'error')
                if salvos:
                    return redirect(url_for('acompanhantes'))
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao salvar: {e}', 'error')
            return redirect(url_for('acompanhantes_novo', paciente_id=paciente_id))

        messages_html = ""
        for category, message in get_flashed_messages(with_categories=True):
            messages_html += f'<div class="alert alert-{category}">{message}</div>'

        if not total_ativos:
            conteudo = f'''
            <div class="breadcrumb">
              <a href="{url_for('dashboard')}">Início</a> >
              <a href="{url_for('acompanhantes')}">Acompanhantes</a> > Novo
            </div>
            <div class="page-header">
              <div class="stp-ajuda-title-row">
                <h2>➕ Cadastrar Acompanhante</h2>
                {html_ajuda_botao('acompanhante-vazio', title='Ajuda sobre o cadastro de acompanhante')}
              </div>
              {html_ajuda_painel('acompanhante-vazio', AJUDA_ACOMPANHANTE)}
            </div>
            {messages_html}
            <div class="card">
              <div class="alert alert-warning">
                <strong>Sem paciente não há acompanhante.</strong><br>
                Cadastre primeiro o paciente em
                <a href="{url_for('pacientes_cadastrar')}">Cadastros → Pacientes</a>,
                depois volte aqui para vincular o acompanhante.
              </div>
              <a href="{url_for('pacientes_cadastrar')}" class="btn">📋 Cadastrar Paciente</a>
              <a href="{url_for('acompanhantes')}" class="btn btn-secondary">Voltar</a>
            </div>
            '''
            return gerar_layout_base("Cadastrar Acompanhante", conteudo, "acompanhantes")

        query = montar_query_paciente_vinculo(filtros)
        total_filtrado = query.count() if tem_filtro else total_ativos
        pacientes = []
        if tem_filtro:
            pacientes = query.order_by(Paciente.nome).limit(LIMITE_SELECT).all()
        elif paciente_pre:
            p_pre = db.session.get(Paciente, paciente_pre)
            if p_pre and p_pre.ativo:
                pacientes = [p_pre]

        if paciente_pre and tem_filtro and not any(p.id == paciente_pre for p in pacientes):
            p_pre = db.session.get(Paciente, paciente_pre)
            if p_pre and p_pre.ativo:
                pacientes = [p_pre] + pacientes

        exibidos = len(pacientes)
        filtros_html = gerar_filtros_paciente_vinculo(filtros, total_filtrado, exibidos)

        options = '<option value="">Selecione o paciente...</option>'
        for p in pacientes:
            sel = ' selected' if paciente_pre and p.id == paciente_pre else ''
            nec = ' ★ necessita acompanhante' if paciente_necessita_acompanhante(p) else ''
            bairro = f' — {escape(p.bairro)}' if (p.bairro or '').strip() else ''
            nasc_pac = format_data_br(p.data_nascimento) if p.data_nascimento else ''
            nasc_attr = f' data-nasc="{escape(nasc_pac)}"' if nasc_pac else ' data-nasc=""'
            options += (
                f'<option value="{p.id}"{sel}{nasc_attr}>{escape(p.nome)} - CPF: {escape(p.cpf)}'
                f'{bairro}{nec}</option>'
            )

        aviso_select = ''
        if not tem_filtro and not paciente_pre:
            aviso_select = (
                '<div class="alert alert-info" style="margin-bottom:1rem;">'
                'Filtre pelo nome, CPF, telefone, bairro ou condição e clique em '
                '<strong>Filtrar</strong> para carregar o paciente no select.</div>'
            )
        elif tem_filtro and total_filtrado == 0:
            aviso_select = (
                '<div class="alert alert-warning" style="margin-bottom:1rem;">'
                'Nenhum paciente ativo encontrado com os filtros informados.</div>'
            )
        elif tem_filtro and total_filtrado > LIMITE_SELECT:
            aviso_select = (
                f'<div class="alert alert-warning" style="margin-bottom:1rem;">'
                f'Muitos resultados ({format_numero_br(total_filtrado)}). '
                f'Exibindo os primeiros {LIMITE_SELECT} — refine os filtros.</div>'
            )

        select_disabled = ' disabled' if not pacientes else ''
        select_required = ' required' if pacientes else ''

        conteudo = f'''
        <div class="breadcrumb">
          <a href="{url_for('dashboard')}">Início</a> >
          <a href="{url_for('acompanhantes')}">Acompanhantes</a> > Novo
        </div>
        {html_page_header_ajuda(
            '➕ Cadastrar Acompanhante',
            'O acompanhante <strong>sempre</strong> fica vinculado a um paciente já cadastrado',
            'acompanhante',
            AJUDA_ACOMPANHANTE,
            title_curto='Ajuda sobre o cadastro de acompanhante',
        )}
        {messages_html}
        {filtros_html}
        {aviso_select}
        <div class="card">
          <form method="POST" id="form-acompanhantes-lote">
            <div class="form-group">
              <label for="paciente_id">Paciente *</label>
              <select id="paciente_id" name="paciente_id"{select_required}{select_disabled}>
                {options}
              </select>
              <small>Obrigatório: sem paciente não é possível cadastrar acompanhante. Somente pacientes ativos.</small>
              <p id="info-nasc-paciente" style="margin:0.45rem 0 0;color:#555;font-size:0.9rem;">
                Selecione o paciente para ver a data de nascimento.
              </p>
            </div>

            <h4 style="margin:1rem 0 0.75rem;">Acompanhante(s)</h4>
            <div id="ac-linhas">
              <div class="ac-linha" style="border:1px solid #ddd;border-radius:0.5rem;padding:0.75rem;margin-bottom:0.75rem;background:#fafafa;">
                <div class="form-row">
                  <div class="form-group">
                    <label for="ac_parentesco_novo_0">Parentesco</label>
                    {html_select_parentesco(name='ac_parentesco', field_id='ac_parentesco_novo_0')}
                  </div>
                  {html_campo_nome_acompanhante()}
                </div>
                <div class="form-row">
                  {html_campo_rg(name='ac_rg', field_id='ac_rg_novo_0')}
                  <div class="form-group">
                    <label>Telefone</label>
                    <input type="tel" name="ac_telefone" placeholder="(00) 00000-0000" maxlength="16">
                  </div>
                  {html_campo_nasc_acompanhante(field_id='ac_data_nascimento_novo_0')}
                </div>
              </div>
            </div>

            <div class="form-actions" style="display:flex;gap:0.5rem;flex-wrap:wrap;">
              <button type="button" class="btn btn-secondary" onclick="adicionarLinhaAcompanhante()">➕ Cadastrar mais um</button>
              <button type="submit" class="btn btn-success">💾 Salvar acompanhante(s)</button>
              <a href="{url_for('acompanhantes')}" class="btn btn-secondary">Cancelar</a>
            </div>
          </form>
        </div>
        {html_assets_parentesco_select()}
        {html_script_nome_acompanhante()}
        <script>
          function atualizarNascPacienteSelecionado() {{
            const sel = document.getElementById('paciente_id');
            const info = document.getElementById('info-nasc-paciente');
            if (!sel || !info) return;
            const opt = sel.options[sel.selectedIndex];
            const nasc = opt && opt.getAttribute('data-nasc') ? opt.getAttribute('data-nasc') : '';
            info.textContent = nasc
              ? ('Nascimento do paciente: ' + nasc)
              : 'Selecione o paciente para ver a data de nascimento.';
          }}
          document.addEventListener('DOMContentLoaded', function() {{
            const sel = document.getElementById('paciente_id');
            if (sel) {{
              sel.addEventListener('change', atualizarNascPacienteSelecionado);
              atualizarNascPacienteSelecionado();
            }}
          }});
          function adicionarLinhaAcompanhante() {{
            const wrap = document.getElementById('ac-linhas');
            const modelo = wrap.querySelector('.ac-linha');
            const clone = modelo.cloneNode(true);
            clone.querySelectorAll('input').forEach(inp => {{
              if (inp.name === 'ac_parentesco_outros') return;
              if (inp.classList.contains('stp-ac-nome-flag') || inp.classList.contains('stp-ac-nome-check')) return;
              if (inp.classList.contains('stp-ac-nome-input')) return;
              inp.value = '';
            }});
            if (window.rebuildParentescoFieldInClone) window.rebuildParentescoFieldInClone(clone);
            if (window.resetNomeAcompanhanteLinha) window.resetNomeAcompanhanteLinha(clone);
            const btnRem = document.createElement('button');
            btnRem.type = 'button';
            btnRem.className = 'btn btn-sm btn-danger';
            btnRem.textContent = 'Remover esta linha';
            btnRem.style.marginTop = '0.35rem';
            btnRem.onclick = function() {{ clone.remove(); }};
            clone.appendChild(btnRem);
            wrap.appendChild(clone);
            if (window.initParentescoSelects) window.initParentescoSelects(clone);
          }}
        </script>
        '''
        return gerar_layout_base("Cadastrar Acompanhante", conteudo, "acompanhantes")

    @app.route('/acompanhantes/<int:acompanhante_id>/editar', methods=['GET', 'POST'])
    @login_required
    def acompanhantes_editar(acompanhante_id):
        from html import escape

        ac = db.session.get(Acompanhante, acompanhante_id)
        if not ac or not ac.ativo:
            flash('Acompanhante não encontrado!', 'error')
            return redirect(url_for('acompanhantes'))

        filtros = obter_filtros_paciente_vinculo_request()
        tem_filtro = filtros_tem_valores(filtros)
        LIMITE_SELECT = 300
        paciente_pre = (
            request.args.get('paciente_id', type=int)
            or request.form.get('paciente_id', type=int)
            or ac.paciente_id
        )

        if request.method == 'POST':
            paciente_id = request.form.get('paciente_id', type=int)
            form_data = {
                'ac_nome': request.form.get('ac_nome', ''),
                'ac_nome_nao_informado': request.form.get('ac_nome_nao_informado', '0'),
                'ac_parentesco': request.form.get('ac_parentesco', ''),
                'ac_parentesco_outros': request.form.get('ac_parentesco_outros', ''),
                'ac_rg': request.form.get('ac_rg', ''),
                'ac_telefone': request.form.get('ac_telefone', ''),
                'ac_data_nascimento': request.form.get('ac_data_nascimento', ''),
                'ac_cpf': request.form.get('ac_cpf', ''),
            }
            atualizado, erro = atualizar_acompanhante_de_form(ac, form_data, paciente_id=paciente_id)
            if erro:
                flash(erro, 'error')
                return redirect(url_for('acompanhantes_editar', acompanhante_id=acompanhante_id))
            try:
                db.session.commit()
                flash(f'Acompanhante "{atualizado.nome}" atualizado com sucesso!', 'success')
                return redirect(url_for('acompanhantes'))
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao salvar: {e}', 'error')
                return redirect(url_for('acompanhantes_editar', acompanhante_id=acompanhante_id))

        messages_html = ""
        for category, message in get_flashed_messages(with_categories=True):
            messages_html += f'<div class="alert alert-{category}">{message}</div>'

        query = montar_query_paciente_vinculo(filtros)
        total_filtrado = query.count() if tem_filtro else Paciente.query.filter_by(ativo=True).count()
        pacientes = []
        if tem_filtro:
            pacientes = query.order_by(Paciente.nome).limit(LIMITE_SELECT).all()
        p_atual = db.session.get(Paciente, paciente_pre) if paciente_pre else None
        if p_atual and p_atual.ativo and not any(p.id == p_atual.id for p in pacientes):
            pacientes = [p_atual] + pacientes

        exibidos = len(pacientes)
        filtros_html = gerar_filtros_paciente_vinculo(
            filtros,
            total_filtrado,
            exibidos,
            endpoint='acompanhantes_editar',
            endpoint_kwargs={'acompanhante_id': acompanhante_id},
        )

        options = '<option value="">Selecione o paciente...</option>'
        for p in pacientes:
            sel = ' selected' if paciente_pre and p.id == paciente_pre else ''
            nec = ' ★ necessita acompanhante' if paciente_necessita_acompanhante(p) else ''
            bairro = f' — {escape(p.bairro)}' if (p.bairro or '').strip() else ''
            nasc_pac = format_data_br(p.data_nascimento) if p.data_nascimento else ''
            nasc_attr = f' data-nasc="{escape(nasc_pac)}"' if nasc_pac else ' data-nasc=""'
            options += (
                f'<option value="{p.id}"{sel}{nasc_attr}>{escape(p.nome)} - CPF: {escape(p.cpf)}'
                f'{bairro}{nec}</option>'
            )

        dn_val = ac.data_nascimento
        aviso_paciente = ''
        if tem_filtro and total_filtrado == 0 and not pacientes:
            aviso_paciente = (
                '<div class="alert alert-warning" style="margin-bottom:1rem;">'
                'Nenhum paciente ativo encontrado com os filtros informados.</div>'
            )
        elif not tem_filtro:
            aviso_paciente = (
                '<div class="alert alert-info" style="margin-bottom:1rem;">'
                'Paciente atual já selecionado. Use os filtros apenas se precisar '
                '<strong>trocar</strong> o vínculo para outro paciente.</div>'
            )

        conteudo = f'''
        <div class="breadcrumb">
          <a href="{url_for('dashboard')}">Início</a> >
          <a href="{url_for('acompanhantes')}">Acompanhantes</a> > Editar
        </div>
        {html_page_header_ajuda(
            f'✏️ Editar Acompanhante {html_id_badge(acompanhante.id)}',
            'Corrija nome, parentesco, telefone ou o paciente vinculado',
            'acompanhante-editar',
            AJUDA_ACOMPANHANTE,
            title_curto='Ajuda sobre o cadastro de acompanhante',
        )}
        {messages_html}
        {filtros_html}
        {aviso_paciente}
        <div class="card">
          <form method="POST" id="form-acompanhante-editar">
            <div class="form-group">
              <label for="paciente_id">Paciente *</label>
              <select id="paciente_id" name="paciente_id" required>
                {options}
              </select>
              <small>Se o vínculo estiver errado, filtre e selecione o paciente correto.</small>
              <p id="info-nasc-paciente" style="margin:0.45rem 0 0;color:#555;font-size:0.9rem;"></p>
            </div>

            <h4 style="margin:1rem 0 0.75rem;">Dados do acompanhante</h4>
            <div class="form-row">
              <div class="form-group">
                <label for="ac_parentesco_edit">Parentesco</label>
                {html_select_parentesco(
                    name='ac_parentesco',
                    valor_atual=ac.parentesco,
                    field_id='ac_parentesco_edit',
                )}
              </div>
              {html_campo_nome_acompanhante(ac.nome or '')}
            </div>
            <div class="form-row">
              {html_campo_rg(name='ac_rg', valor=ac.rg or '', field_id='ac_rg_edit')}
              <div class="form-group">
                <label>Telefone</label>
                <input type="tel" name="ac_telefone" value="{escape(ac.telefone or '')}"
                       placeholder="(00) 00000-0000" maxlength="16">
              </div>
              {html_campo_nasc_acompanhante(dn_val, field_id='ac_data_nascimento_edit')}
            </div>

            <div class="form-actions" style="display:flex;gap:0.5rem;flex-wrap:wrap;">
              <button type="submit" class="btn btn-success">💾 Salvar alterações</button>
              <a href="{url_for('acompanhantes')}" class="btn btn-secondary">Cancelar</a>
            </div>
          </form>
        </div>
        {html_assets_parentesco_select()}
        {html_script_nome_acompanhante()}
        <script>
          function atualizarNascPacienteSelecionado() {{
            const sel = document.getElementById('paciente_id');
            const info = document.getElementById('info-nasc-paciente');
            if (!sel || !info) return;
            const opt = sel.options[sel.selectedIndex];
            const nasc = opt && opt.getAttribute('data-nasc') ? opt.getAttribute('data-nasc') : '';
            info.textContent = nasc
              ? ('Nascimento do paciente: ' + nasc)
              : '';
          }}
          document.addEventListener('DOMContentLoaded', function() {{
            const sel = document.getElementById('paciente_id');
            if (sel) {{
              sel.addEventListener('change', atualizarNascPacienteSelecionado);
              atualizarNascPacienteSelecionado();
            }}
          }});
        </script>
        '''
        return gerar_layout_base("Editar Acompanhante", conteudo, "acompanhantes")

    @app.route('/acompanhantes/<int:acompanhante_id>/excluir')
    @login_required
    def acompanhantes_excluir(acompanhante_id):
        ac = db.session.get(Acompanhante, acompanhante_id)
        if not ac:
            flash('Acompanhante não encontrado!', 'error')
            return redirect(url_for('acompanhantes'))
        paciente = db.session.get(Paciente, ac.paciente_id)
        restantes = [
            a for a in listar_acompanhantes_paciente(ac.paciente_id, somente_ativos=True)
            if a.id != ac.id
        ]
        if paciente_necessita_acompanhante(paciente) and not restantes:
            flash(
                'Não é possível desativar o único acompanhante enquanto a condição '
                'do paciente for "Necessita acompanhante".',
                'error',
            )
            return redirect(url_for('acompanhantes'))
        try:
            ac.ativo = False
            db.session.commit()
            flash(f'Acompanhante "{ac.nome}" desativado.', 'warning')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro: {e}', 'error')
        return redirect(url_for('acompanhantes'))

    # ===== VEÍCULOS =====
    @app.route('/veiculos')
    @login_required
    def veiculos():
        from html import escape as html_esc

        aba = (request.args.get('aba') or 'veiculo').strip().lower()
        if aba not in ('veiculo', 'frota'):
            aba = 'veiculo'

        page, per_page = obter_paginacao_request()
        abas_html = html_abas_listagem_veiculos(aba)

        if aba == 'frota':
            filtros = obter_filtros_frotas_request()
            total_cadastro = Frota.query.filter_by(ativo=True).count()
            query = montar_query_frotas(filtros)
            frotas_lista, total, page = listar_paginado(
                query, page, per_page, Frota.numero.asc()
            )
            exibidos = len(frotas_lista)
            tem_filtro = filtros_tem_valores(filtros)
            filtros_url = {k: v for k, v in filtros.items() if v}
            filtros_url['aba'] = 'frota'
            filtros_html = gerar_filtros_frotas(filtros, total, exibidos, per_page)
            paginacao_html = gerar_paginacao('veiculos', page, per_page, total, filtros_url)

            lista_html = ''
            if frotas_lista:
                rows = ''
                cards_mobile = ''
                for frota in frotas_lista:
                    qtd = qtd_veiculos_da_frota(frota.id)
                    ident = frota_identificacao_exibir(frota)
                    data_cad = frota.data_cadastro.strftime('%d/%m/%Y') if frota.data_cadastro else '—'
                    veiculo_v = frota_veiculo_vinculado(frota.id)
                    veiculo_txt = veiculo_v.placa if veiculo_v else '—'
                    acoes = html_acoes_toolbar(
                        html_acao_icone(
                            'ti-edit',
                            'Gerenciar frota / veículo',
                            href=url_for('veiculos_cadastrar', aba='frota', frota_id=frota.id),
                            variant='editar',
                        ),
                        html_acao_icone(
                            'ti-trash',
                            'Desativar frota',
                            href=url_for('veiculos_frota_excluir', frota_id=frota.id),
                            variant='excluir',
                            confirm_msg='Desativar esta frota? O veículo vinculado permanece no sistema.',
                        ),
                    )
                    rows += f'''
                    <tr>
                      {html_td_id(frota.id)}
                      <td style="padding:0.75rem;border-bottom:1px solid var(--border-color);">{html_esc(frota.numero)}</td>
                      <td style="padding:0.75rem;border-bottom:1px solid var(--border-color);">{html_esc(frota.nome)}</td>
                      <td style="padding:0.75rem;border-bottom:1px solid var(--border-color);">{html_esc(ident)}</td>
                      <td style="padding:0.75rem;border-bottom:1px solid var(--border-color);">{html_esc(veiculo_txt)}</td>
                      <td style="padding:0.75rem;border-bottom:1px solid var(--border-color);">{'1' if veiculo_v else '0'}/1</td>
                      <td style="padding:0.75rem;border-bottom:1px solid var(--border-color);">{data_cad}</td>
                      <td style="padding:0.75rem;border-bottom:1px solid var(--border-color);text-align:center;">{acoes}</td>
                    </tr>'''
                    cards_mobile += html_mobile_card(
                        title=f'#{frota.id} {frota.numero or "—"}',
                        meta=html_esc(frota.nome or '—'),
                        rows=[
                            ('ID', f'<strong>{frota.id}</strong>'),
                            ('Identificação', html_esc(ident)),
                            ('Veículo', html_esc(veiculo_txt)),
                            ('Vínculo', '1/1' if veiculo_v else '0/1'),
                            ('Cadastro', data_cad),
                        ],
                        acoes_html=acoes,
                    )
                lista_html = f'''
                <div class="card">
                  <div style="display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:0.75rem;margin-bottom:1rem;">
                    <h3 style="color:var(--primary-color);margin:0;">🚌 Frotas cadastradas</h3>
                    <small style="color:var(--gray-color);">Regra: 1 frota = 1 veículo</small>
                  </div>
                  <div class="stp-list-desktop table-container">
                    <table style="width:100%;border-collapse:collapse;">
                      <thead>
                        <tr style="background:var(--color-95);">
                          {html_th_id()}
                          <th style="padding:0.75rem;text-align:left;border-bottom:2px solid var(--primary-color);">Número</th>
                          <th style="padding:0.75rem;text-align:left;border-bottom:2px solid var(--primary-color);">Nome</th>
                          <th style="padding:0.75rem;text-align:left;border-bottom:2px solid var(--primary-color);">Identificação</th>
                          <th style="padding:0.75rem;text-align:left;border-bottom:2px solid var(--primary-color);">Veículo</th>
                          <th style="padding:0.75rem;text-align:left;border-bottom:2px solid var(--primary-color);">Vínculo</th>
                          <th style="padding:0.75rem;text-align:left;border-bottom:2px solid var(--primary-color);">Cadastro</th>
                          <th style="padding:0.75rem;text-align:center;border-bottom:2px solid var(--primary-color);">Ações</th>
                        </tr>
                      </thead>
                      <tbody>{rows}</tbody>
                    </table>
                  </div>
                  <div class="stp-list-mobile">{cards_mobile}</div>
                </div>
                '''
            elif tem_filtro:
                lista_html = '''
                <div class="card">
                  <p style="margin:0;color:var(--gray-color);">Nenhuma frota encontrada com os filtros selecionados.</p>
                </div>
                '''

            vazio = ''
            if not total_cadastro and not tem_filtro:
                vazio = '''
                <div class="card"><div class="coming-soon">
                  <div class="icon">🚌</div>
                  <h3>Nenhuma frota cadastrada</h3>
                  <p>Cadastre a primeira frota e depois vincule o veículo (1 frota = 1 veículo).</p>
                </div></div>
                '''

            conteudo = f'''
            <div class="page-header">
              <h2>🚗 Gerenciamento de Veículos</h2>
              <p>Controle da frota municipal de transporte de pacientes</p>
              <div style="margin-top:1rem;">
                <a href="{url_for('veiculos_cadastrar', aba='frota')}" class="btn">🚌 Cadastrar Nova Frota</a>
              </div>
            </div>
            {abas_html}
            {filtros_html}
            {lista_html}
            {paginacao_html}
            {vazio}
            '''
            return gerar_layout_base("Veículos — Frotas", conteudo, "veiculos")

        # --- Aba Veículos (padrão) ---
        filtros = obter_filtros_veiculos_request()
        total_cadastro = Veiculo.query.filter_by(ativo=True).count()
        query = montar_query_veiculos(filtros)
        veiculos_lista, total, page = listar_paginado(
            query, page, per_page, Veiculo.data_cadastro.desc()
        )
        exibidos = len(veiculos_lista)
        tem_filtro = filtros_tem_valores(filtros)
        filtros_url = {k: v for k, v in filtros.items() if v}
        filtros_url['aba'] = 'veiculo'

        filtros_html = gerar_filtros_veiculos(filtros, total, exibidos, per_page)
        paginacao_html = gerar_paginacao('veiculos', page, per_page, total, filtros_url)
        botoes_impressao = gerar_botoes_impressao('veiculos_imprimir', filtros_url, page, per_page)

        veiculos_html = ""
        if veiculos_lista:
            cards_mobile = ""
            veiculos_html = '''
            <div class="card">
                <div style="display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:0.75rem; margin-bottom:1rem;">
                    <h3 style="color: var(--primary-color); margin: 0;">🚗 Veículos Cadastrados</h3>
                    ''' + botoes_impressao + '''
                </div>
                <div class="stp-list-desktop table-container">
                    <table style="width: 100%; border-collapse: collapse;">
                        <thead>
                            <tr style="background: var(--color-95);">
                                ''' + html_th_id() + '''
                                <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Placa</th>
                                <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Marca/Modelo</th>
                                <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Frota</th>
                                <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Tipo</th>
                                <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Ano</th>
                                <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Cor</th>
                                <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Adaptado PCD</th>
                                <th style="padding: 0.75rem; text-align: center; border-bottom: 2px solid var(--primary-color);">Ações</th>
                            </tr>
                        </thead>
                        <tbody>
            '''
            for veiculo in veiculos_lista:
                acoes = html_acoes_toolbar(
                    html_acao_icone('ti-edit', 'Editar veículo', href=url_for('veiculos_editar', veiculo_id=veiculo.id), variant='editar'),
                    html_acao_icone('ti-trash', 'Excluir veículo', href=url_for('veiculos_excluir', veiculo_id=veiculo.id), variant='excluir', confirm_msg='Tem certeza que deseja excluir este veículo?'),
                )
                marca_modelo = f'{veiculo.marca} {veiculo.modelo}'.strip()
                tipo_txt = (veiculo.tipo or '').replace('_', ' ').title()
                adaptado_txt = 'Sim' if veiculo.adaptado else 'Não'
                frota_obj = getattr(veiculo, 'frota', None)
                if frota_obj is None and getattr(veiculo, 'frota_id', None):
                    frota_obj = db.session.get(Frota, veiculo.frota_id)
                frota_txt = frota_identificacao_exibir(frota_obj) if frota_obj else '—'
                veiculos_html += f'''
                            <tr>
                                {html_td_id(veiculo.id)}
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{html_esc(veiculo.placa)}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{html_esc(marca_modelo)}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{html_esc(frota_txt)}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{html_esc(tipo_txt)}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{html_esc(str(veiculo.ano) if veiculo.ano is not None else '—')}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{html_esc(veiculo.cor or '—')}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{'✅ Sim' if veiculo.adaptado else '❌ Não'}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color); text-align: center;">{acoes}</td>
                            </tr>
                '''
                cards_mobile += html_mobile_card(
                    title=f'#{veiculo.id} {veiculo.placa or "—"}',
                    meta=html_esc(marca_modelo),
                    rows=[
                        ('ID', f'<strong>{veiculo.id}</strong>'),
                        ('Frota', html_esc(frota_txt)),
                        ('Tipo', html_esc(tipo_txt)),
                        ('Ano', html_esc(str(veiculo.ano) if veiculo.ano is not None else '—')),
                        ('Cor', html_esc(veiculo.cor or '—')),
                        ('PCD', html_esc(adaptado_txt)),
                    ],
                    acoes_html=acoes,
                )
            veiculos_html += f'''
                        </tbody>
                    </table>
                </div>
                <div class="stp-list-mobile">{cards_mobile}</div>
            </div>
            '''
        elif tem_filtro:
            veiculos_html = '''
            <div class="card">
                <p style="margin: 0; color: var(--gray-color);">
                    Nenhum veículo encontrado com os filtros selecionados.
                </p>
            </div>
            '''

        conteudo = f'''
        <div class="page-header">
            <h2>🚗 Gerenciamento de Veículos</h2>
            <p>Controle da frota municipal de transporte de pacientes</p>
            <div style="margin-top: 1rem;">
                <a href="{url_for('veiculos_cadastrar', aba='veiculo')}" class="btn">🚗 Cadastrar Novo Veículo</a>
            </div>
        </div>

        {abas_html}
        {filtros_html}
        {veiculos_html}
        {paginacao_html}

        {f'<div class="card"><div class="coming-soon"><div class="icon">🚗</div><h3>Nenhum veículo cadastrado</h3><p>Comece cadastrando o primeiro veículo da frota!</p></div></div>' if not total_cadastro and not tem_filtro else ''}
        '''
        return gerar_layout_base("Veículos", conteudo, "veiculos")

    @app.route('/veiculos/frotas/<int:frota_id>/excluir')
    @login_required
    def veiculos_frota_excluir(frota_id):
        frota = db.session.get(Frota, frota_id)
        if not frota:
            flash('Frota não encontrada!', 'error')
            return redirect(url_for('veiculos', aba='frota'))
        try:
            nome = frota_identificacao_exibir(frota)
            veiculo_v = frota_veiculo_vinculado(frota.id)
            frota.ativo = False
            frota.data_inativacao = datetime.utcnow()
            db.session.commit()
            extra = (
                f' O veículo "{veiculo_v.placa}" permanece no sistema.'
                if veiculo_v else ''
            )
            flash(f'Frota "{nome}" desativada.{extra}', 'warning')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao desativar frota: {e}', 'error')
        return redirect(url_for('veiculos', aba='frota'))

    @app.route('/veiculos/imprimir')
    @login_required
    def veiculos_imprimir():
        filtros = obter_filtros_veiculos_request()
        page, per_page = obter_paginacao_request()
        paginas = request.args.get('paginas', 'atual')
        query = montar_query_veiculos(filtros)
        lista, total, total_pages, pag_ini, pag_fim = buscar_lista_impressao(
            query, page, per_page, paginas, Veiculo.data_cadastro.desc()
        )
        return gerar_html_impressao_veiculos(lista, filtros)
    
    @app.route('/veiculos/cadastrar', methods=['GET', 'POST'])
    @login_required
    def veiculos_cadastrar():
        if request.method == 'POST':
            form_tipo = (request.form.get('form_tipo') or 'veiculo').strip().lower()

            if form_tipo == 'frota':
                try:
                    numero = normalizar_numero_frota_cadastro(request.form.get('frota_numero'))
                    nome = normalizar_nome_frota_cadastro(request.form.get('frota_nome'))
                    if not numero or not nome:
                        flash('Preencha o número e o nome da frota!', 'error')
                        return redirect(url_for('veiculos_cadastrar', aba='frota'))
                    if Frota.query.filter(db.func.lower(Frota.numero) == numero.lower()).first():
                        flash(f'Número de frota "{numero}" já cadastrado!', 'error')
                        return redirect(url_for('veiculos_cadastrar', aba='frota'))
                    if Frota.query.filter(db.func.lower(Frota.nome) == nome.lower()).first():
                        flash(f'Nome de frota "{nome}" já cadastrado!', 'error')
                        return redirect(url_for('veiculos_cadastrar', aba='frota'))
                    frota = Frota(numero=numero, nome=nome, ativo=True)
                    db.session.add(frota)
                    db.session.commit()
                    flash(
                        f'Frota "{frota_identificacao_exibir(frota)}" cadastrada com sucesso! '
                        'Agora vincule ou cadastre o veículo (1 frota = 1 veículo).',
                        'success',
                    )
                    return redirect(url_for('veiculos_cadastrar', aba='frota', frota_id=frota.id))
                except Exception as e:
                    db.session.rollback()
                    flash(f'Erro ao cadastrar frota: {str(e)}', 'error')
                    print(f"❌ Erro ao cadastrar frota: {e}")
                    return redirect(url_for('veiculos_cadastrar', aba='frota'))

            if form_tipo == 'vincular_veiculo_frota':
                try:
                    frota_id = int(request.form.get('frota_id') or 0)
                    veiculo_id = int(request.form.get('veiculo_id') or 0)
                    frota = db.session.get(Frota, frota_id)
                    veiculo = db.session.get(Veiculo, veiculo_id)
                    if not frota or not frota.ativo:
                        flash('Frota inválida!', 'error')
                        return redirect(url_for('veiculos_cadastrar', aba='frota'))
                    if not veiculo:
                        flash('Veículo inválido!', 'error')
                        return redirect(url_for('veiculos_cadastrar', aba='frota', frota_id=frota_id))
                    ok, erro = vincular_veiculo_a_frota(veiculo, frota)
                    if not ok:
                        flash(erro, 'error')
                        return redirect(url_for('veiculos_cadastrar', aba='frota', frota_id=frota_id))
                    db.session.commit()
                    flash(f'Veículo "{veiculo.placa}" vinculado à frota com sucesso!', 'success')
                    return redirect(url_for('veiculos_cadastrar', aba='frota', frota_id=frota_id))
                except Exception as e:
                    db.session.rollback()
                    flash(f'Erro ao vincular veículo: {str(e)}', 'error')
                    return redirect(url_for('veiculos_cadastrar', aba='frota'))

            if form_tipo == 'desvincular_veiculo_frota':
                try:
                    frota_id = int(request.form.get('frota_id') or 0)
                    veiculo_id = int(request.form.get('veiculo_id') or 0)
                    veiculo = db.session.get(Veiculo, veiculo_id)
                    if not veiculo:
                        flash('Veículo não encontrado!', 'error')
                        return redirect(url_for('veiculos_cadastrar', aba='frota', frota_id=frota_id or None))
                    desvincular_veiculo_da_frota(veiculo)
                    db.session.commit()
                    flash(f'Vínculo do veículo "{veiculo.placa}" removido da frota.', 'success')
                    return redirect(url_for('veiculos_cadastrar', aba='frota', frota_id=frota_id))
                except Exception as e:
                    db.session.rollback()
                    flash(f'Erro ao remover vínculo: {str(e)}', 'error')
                    return redirect(url_for('veiculos_cadastrar', aba='frota'))

            try:
                # Extrair dados do formulário (cadastro de veículo — lógica preservada)
                placa = request.form.get('placa', '').strip().upper()
                marca = request.form.get('marca', '').strip()
                modelo = request.form.get('modelo', '').strip()
                ano = int(request.form.get('ano', 0))
                cor = request.form.get('cor', '').strip()
                tipo = request.form.get('tipo', '').strip()
                capacidade = request.form.get('capacidade')
                adaptado = request.form.get('adaptado') == 'sim'
                observacoes = request.form.get('observacoes', '').strip()
                capacidade_manual = request.form.get('capacidade_manual') == '1'
                frota_id_ctx = (request.form.get('frota_id') or '').strip()

                if not capacidade_manual:
                    capacidade = str(inferir_capacidade_passageiros(marca, modelo, tipo))
                
                # Validação básica
                if not all([placa, marca, modelo, ano, tipo]):
                    flash('Por favor, preencha todos os campos obrigatórios!', 'error')
                    if frota_id_ctx:
                        return redirect(url_for('veiculos_cadastrar', aba='veiculo', frota_id=frota_id_ctx))
                    return redirect(url_for('veiculos_cadastrar'))
                
                # Verificar se placa já existe
                if Veiculo.query.filter_by(placa=placa).first():
                    flash('Placa já cadastrada no sistema!', 'error')
                    if frota_id_ctx:
                        return redirect(url_for('veiculos_cadastrar', aba='veiculo', frota_id=frota_id_ctx))
                    return redirect(url_for('veiculos_cadastrar'))
                
                # Criar novo veículo
                veiculo = Veiculo(
                    placa=placa,
                    marca=marca,
                    modelo=modelo,
                    ano=ano,
                    cor=cor if cor else None,
                    tipo=tipo,
                    capacidade=int(capacidade) if capacidade else None,
                    adaptado=adaptado,
                    observacoes=observacoes if observacoes else None
                )

                frota_ctx = None
                if frota_id_ctx:
                    try:
                        frota_ctx = db.session.get(Frota, int(frota_id_ctx))
                    except (TypeError, ValueError):
                        frota_ctx = None
                    if frota_ctx and frota_ctx.ativo:
                        ok, erro = vincular_veiculo_a_frota(veiculo, frota_ctx)
                        if not ok:
                            flash(erro, 'error')
                            return redirect(
                                url_for('veiculos_cadastrar', aba='frota', frota_id=frota_ctx.id)
                            )
                    else:
                        frota_ctx = None
                
                db.session.add(veiculo)
                db.session.commit()

                if frota_ctx:
                    flash(
                        f'Veículo "{placa}" cadastrado e vinculado à frota '
                        f'"{frota_identificacao_exibir(frota_ctx)}"!',
                        'success',
                    )
                    return redirect(url_for('veiculos_cadastrar', aba='frota', frota_id=frota_ctx.id))
                
                flash(f'Veículo "{placa}" cadastrado com sucesso!', 'success')
                return redirect(url_for('veiculos', aba='veiculo'))
                
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao cadastrar veículo: {str(e)}', 'error')
                print(f"❌ Erro ao cadastrar veículo: {e}")
        
        # Gerar alertas de mensagens flash
        messages_html = ""
        for category, message in get_flashed_messages(with_categories=True):
            alert_class = f"alert-{category}"
            messages_html += f'<div class="alert {alert_class}">{message}</div>'

        aba = (request.args.get('aba') or 'veiculo').strip().lower()
        if aba not in ('veiculo', 'frota'):
            aba = 'veiculo'

        frota_aberta = None
        frota_id_arg = (request.args.get('frota_id') or '').strip()
        if frota_id_arg:
            try:
                frota_aberta = db.session.get(Frota, int(frota_id_arg))
            except (TypeError, ValueError):
                frota_aberta = None
            if frota_aberta and not frota_aberta.ativo:
                frota_aberta = None

        tab_veiculo_active = 'active' if aba == 'veiculo' else ''
        tab_frota_active = 'active' if aba == 'frota' else ''
        content_veiculo_active = 'active' if aba == 'veiculo' else ''
        content_frota_active = 'active' if aba == 'frota' else ''

        banner_frota_veiculo = ''
        frota_id_hidden = ''
        if frota_aberta and aba == 'veiculo':
            from html import escape as esc
            ocupado = frota_veiculo_vinculado(frota_aberta.id)
            if ocupado:
                banner_frota_veiculo = (
                    f'<div class="alert alert-warning">'
                    f'A frota <strong>{esc(frota_identificacao_exibir(frota_aberta))}</strong> '
                    f'já está vinculada ao veículo <strong>{esc(ocupado.placa)}</strong>. '
                    f'Regra: 1 frota = 1 veículo. Remova o vínculo atual antes de cadastrar outro.'
                    f'</div>'
                )
            else:
                banner_frota_veiculo = (
                    f'<div class="alert alert-success">'
                    f'Veículo será vinculado automaticamente à frota '
                    f'<strong>{esc(frota_identificacao_exibir(frota_aberta))}</strong> '
                    f'(1 frota = 1 veículo).'
                    f'</div>'
                )
                frota_id_hidden = f'<input type="hidden" name="frota_id" value="{frota_aberta.id}">'

        # Formulário frota: novo vs frota já salva
        from html import escape as esc2
        if frota_aberta and aba == 'frota':
            frota_form_html = f'''
            <div class="alert alert-success" style="margin-bottom:1rem;">
                Frota salva: <strong>{esc2(frota_identificacao_exibir(frota_aberta))}</strong>.
                Vincule ou cadastre <strong>um</strong> veículo na seção abaixo (regra: 1 frota = 1 veículo).
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>Número da Frota</label>
                    <input type="text" value="{esc2(frota_aberta.numero)}" readonly style="background:#f5f5f5;">
                </div>
                <div class="form-group">
                    <label>Nome da Frota</label>
                    <input type="text" value="{esc2(frota_aberta.nome)}" readonly style="background:#f5f5f5;">
                </div>
            </div>
            <div style="background:var(--color-95);padding:0.9rem 1rem;border-radius:0.5rem;border-left:4px solid var(--primary-color);margin:0.5rem 0 1rem;">
                <div style="font-size:0.8rem;color:var(--gray-color);margin-bottom:0.25rem;">Identificação</div>
                <div style="font-weight:700;color:var(--primary-color);font-size:1.05rem;">{esc2(frota_identificacao_exibir(frota_aberta))}</div>
            </div>
            '''
        else:
            frota_form_html = f'''
            <form method="POST" id="form-cadastro-frota">
                <input type="hidden" name="form_tipo" value="frota">
                <div class="form-row">
                    <div class="form-group">
                        <label for="frota_numero">Número da Frota *</label>
                        <input type="text" id="frota_numero" name="frota_numero"
                               placeholder="F00{{Número da Frota}}" required
                               style="text-transform: uppercase;" maxlength="30"
                               autocomplete="off" oninput="atualizarPreviewFrota()">
                        <small style="color:var(--gray-color);">Ex.: F00267</small>
                    </div>
                    <div class="form-group">
                        <label for="frota_nome">Nome da Frota *</label>
                        <input type="text" id="frota_nome" name="frota_nome"
                               placeholder="Ex: NI Frota 267" required maxlength="120"
                               autocomplete="off" oninput="atualizarPreviewFrota()">
                    </div>
                </div>
                <div style="background:var(--color-95);padding:0.9rem 1rem;border-radius:0.5rem;border-left:4px solid var(--primary-color);margin:0.5rem 0 1rem;">
                    <div style="font-size:0.8rem;color:var(--gray-color);margin-bottom:0.25rem;">Identificação</div>
                    <div id="frota-preview" style="font-weight:700;color:var(--primary-color);font-size:1.05rem;">—</div>
                </div>
                <div style="margin-top: 2rem;">
                    <button type="submit" class="btn btn-success">💾 Salvar Frota</button>
                    <a href="{url_for('veiculos', aba='frota')}" class="btn btn-secondary" style="margin-left: 1rem;">❌ Cancelar</a>
                </div>
            </form>
            '''

        secao_veiculos_frota = html_secao_veiculos_da_frota(frota_aberta if aba == 'frota' else None)
        
        conteudo = f'''
        <div class="breadcrumb">
            <a href="{url_for('dashboard')}">Início</a> > 
            <a href="{url_for('veiculos')}">Veículos</a> > 
            Cadastro
        </div>
        
        {html_page_header_ajuda(
            '🚗 Cadastro',
            'Cadastre um veículo ou uma frota — uma operação por vez',
            'veiculo-frota',
            AJUDA_VEICULO_FROTA,
            title_curto='Ajuda sobre veículo e frota',
        )}
        
        {messages_html}
        
        <div class="card">
            <div class="tabs" role="tablist" aria-label="Tipo de cadastro">
                <button type="button" class="tab {tab_veiculo_active}" role="tab"
                        aria-selected="{'true' if aba == 'veiculo' else 'false'}"
                        onclick="showCadastroTab('veiculo', this)">🚗 Veículo</button>
                <button type="button" class="tab {tab_frota_active}" role="tab"
                        aria-selected="{'true' if aba == 'frota' else 'false'}"
                        onclick="showCadastroTab('frota', this)">🚌 Frota</button>
            </div>

            <div id="tab-veiculo" class="tab-content {content_veiculo_active}" role="tabpanel">
            {html_ajuda_titulo_veiculo()}
            {banner_frota_veiculo}
            <form method="POST" id="form-cadastro-veiculo">
                <input type="hidden" name="form_tipo" value="veiculo">
                {frota_id_hidden}
                <div class="form-row">
                    <div class="form-group">
                        <label for="placa">Placa *</label>
                        <input type="text" id="placa" name="placa" placeholder="ABC-1234" required style="text-transform: uppercase;">
                    </div>
                    <div class="form-group">
                        <label for="tipo">Tipo de Veículo *</label>
                        <select id="tipo" name="tipo" required>
                            <option value="">Selecione...</option>
                            <option value="ambulancia">Ambulância</option>
                            <option value="van">Van</option>
                            <option value="micro_onibus">Micro-ônibus</option>
                            <option value="carro">Carro</option>
                        </select>
                    </div>
                </div>
                
                <div style="background: var(--color-95); padding: 1.25rem; border-radius: 0.5rem; margin: 1rem 0; border: 1px solid var(--border-color);">
                    <h4 style="color: var(--primary-color); margin: 0 0 0.75rem;">🔍 Consulta FIPE — Carros (preenche marca, modelo e ano)</h4>
                    <input type="hidden" id="fipe_tipo" value="carros">
                    <div class="form-row">
                        <div class="form-group">
                            <label for="fipe_marca">Marca</label>
                            <select id="fipe_marca"><option value="">Carregando marcas...</option></select>
                        </div>
                        <div class="form-group">
                            <label for="fipe_modelo">Modelo</label>
                            <select id="fipe_modelo" disabled><option value="">Selecione a marca...</option></select>
                        </div>
                    </div>
                    <div class="form-row">
                        <div class="form-group">
                            <label for="fipe_ano">Ano / Combustível</label>
                            <select id="fipe_ano" disabled><option value="">Selecione o modelo...</option></select>
                        </div>
                    </div>
                    <small id="fipe-status" style="color: var(--gray-color);">Selecione marca, modelo e ano para preencher automaticamente.</small>
                </div>
                
                <div class="form-row">
                    <div class="form-group">
                        <label for="marca">Marca *</label>
                        <input type="text" id="marca" name="marca" required placeholder="Ex: Fiat, Mercedes">
                        </div>
                        <div class="form-group">
                            <label for="modelo">Modelo *</label>
                            <input type="text" id="modelo" name="modelo" required readonly
                               style="background: #f5f5f5;"
                               placeholder="Selecione o modelo na tabela FIPE acima">
                        <small id="modelo-fipe-aviso" style="display:block; margin-top:0.35rem; color:var(--gray-color); font-size:0.85rem;">
                            ℹ️ O modelo é preenchido pela seleção na tabela FIPE. Para digitar manualmente, use a opção abaixo.
                        </small>
                        <label style="display:flex; align-items:center; gap:0.5rem; margin-top:0.5rem; font-size:0.875rem; font-weight:normal; color:var(--text-color); cursor:pointer;">
                            <input type="checkbox" id="modelo_manual_toggle" style="width:auto;">
                            Liberar edição manual do modelo
                        </label>
                    </div>
                </div>
                
                <div class="form-row">
                    <div class="form-group">
                        <label for="ano">Ano *</label>
                        <input type="number" id="ano" name="ano" min="1980" max="2030" required placeholder="AAAA">
                    </div>
                    {html_paleta_cores('cor')}
                </div>
                
                <div class="form-row">
                    <div class="form-group">
                        <label for="capacidade">Capacidade de Passageiros</label>
                        <input type="number" id="capacidade" name="capacidade" min="1" max="50" readonly
                               style="background: #f5f5f5;" placeholder="Conforme modelo FIPE">
                        <input type="hidden" id="capacidade_manual" name="capacidade_manual" value="0">
                        <small id="capacidade-fipe-aviso" style="display:block; margin-top:0.35rem; color:var(--gray-color); font-size:0.85rem;">
                            ℹ️ A capacidade é calculada automaticamente conforme o modelo selecionado na FIPE.
                        </small>
                        <label style="display:flex; align-items:center; gap:0.5rem; margin-top:0.5rem; font-size:0.875rem; font-weight:normal; color:var(--text-color); cursor:pointer;">
                            <input type="checkbox" id="capacidade_manual_toggle" style="width:auto;">
                            Liberar edição manual da capacidade
                        </label>
                    </div>
                    <div class="form-group">
                        <label for="adaptado">Adaptado para PCD</label>
                        <select id="adaptado" name="adaptado">
                            <option value="nao">Não</option>
                            <option value="sim">Sim</option>
                        </select>
                    </div>
                </div>
                
                <div class="form-group">
                    <label for="observacoes">Observações</label>
                    <textarea id="observacoes" name="observacoes" rows="3" placeholder="Equipamentos especiais, restrições, etc."></textarea>
                </div>
                
                <div style="margin-top: 2rem;">
                    <button type="submit" class="btn btn-success">💾 Salvar Veículo</button>
                    <a href="{url_for('veiculos_cadastrar', aba='frota', frota_id=frota_aberta.id) if frota_aberta else url_for('veiculos')}" class="btn btn-secondary" style="margin-left: 1rem;">❌ Cancelar</a>
                </div>
            </form>
            </div>

            <div id="tab-frota" class="tab-content {content_frota_active}" role="tabpanel">
            {html_ajuda_fluxo_frota()}
            {frota_form_html}
            {secao_veiculos_frota}
            </div>
        </div>
        
        <script>
        function showCadastroTab(nome, btn) {{
            document.querySelectorAll('.tab-content').forEach(function(el) {{ el.classList.remove('active'); }});
            document.querySelectorAll('.tabs .tab').forEach(function(el) {{
                el.classList.remove('active');
                el.setAttribute('aria-selected', 'false');
            }});
            var painel = document.getElementById('tab-' + nome);
            if (painel) painel.classList.add('active');
            if (btn) {{
                btn.classList.add('active');
                btn.setAttribute('aria-selected', 'true');
            }}
            try {{
                var url = new URL(window.location.href);
                url.searchParams.set('aba', nome);
                window.history.replaceState({{}}, '', url);
            }} catch (e) {{}}
            var formVeiculo = document.getElementById('form-cadastro-veiculo');
            var formFrota = document.getElementById('form-cadastro-frota');
            if (formVeiculo) {{
                formVeiculo.querySelectorAll('[required]').forEach(function(el) {{
                    if (nome === 'veiculo') el.setAttribute('required', 'required');
                    else {{ el.dataset.wasRequired = '1'; el.removeAttribute('required'); }}
                }});
            }}
            if (formFrota) {{
                formFrota.querySelectorAll('input, textarea, select').forEach(function(el) {{
                    if (!el.dataset.reqBase) {{
                        if (el.hasAttribute('required') || el.dataset.wasRequired === '1') el.dataset.reqBase = '1';
                    }}
                }});
                formFrota.querySelectorAll('[data-req-base="1"]').forEach(function(el) {{
                    if (nome === 'frota') el.setAttribute('required', 'required');
                    else el.removeAttribute('required');
                }});
            }}
        }}

        function atualizarPreviewFrota() {{
            var numEl = document.getElementById('frota_numero');
            var nomeEl = document.getElementById('frota_nome');
            var el = document.getElementById('frota-preview');
            if (!el || !numEl || !nomeEl) return;
            var numero = (numEl.value || '').trim().toUpperCase().replace(/\\s+/g, '');
            var nome = (nomeEl.value || '').trim().replace(/\\s+/g, ' ');
            if (nome && numero) el.textContent = nome + ' - ' + numero;
            else if (nome) el.textContent = nome;
            else if (numero) el.textContent = numero;
            else el.textContent = '—';
        }}

        document.addEventListener('DOMContentLoaded', function() {{
            showCadastroTab('{aba}', document.querySelector('.tabs .tab.active'));
            atualizarPreviewFrota();
        }});
        </script>

        <script>
        (function() {{
            const FIPE_TIPO = 'carros';
            const fipeMarca = document.getElementById('fipe_marca');
            const fipeModelo = document.getElementById('fipe_modelo');
            const fipeAno = document.getElementById('fipe_ano');
            const fipeStatus = document.getElementById('fipe-status');
            const modeloInput = document.getElementById('modelo');
            const modeloManualToggle = document.getElementById('modelo_manual_toggle');
            const modeloFipeAviso = document.getElementById('modelo-fipe-aviso');
            const capacidadeInput = document.getElementById('capacidade');
            const capacidadeManual = document.getElementById('capacidade_manual');
            const capacidadeManualToggle = document.getElementById('capacidade_manual_toggle');
            const capacidadeFipeAviso = document.getElementById('capacidade-fipe-aviso');
            const tipoSelect = document.getElementById('tipo');
            const marcaInput = document.getElementById('marca');
            
            const REGRAS_CAPACIDADE = [
                {{ keys: ['MICRO', 'VOLARE', 'RODOVIAR', 'ONIBUS', 'ÔNIBUS', 'BUS', 'THUNDER', 'PARADISO'], cap: 26 }},
                {{ keys: ['SPRINTER', 'DUCATO', 'MASTER', 'HIACE', 'H1', 'JUMPY', 'EXPERT', 'BOXER', 'VITO', 'TRANSIT'], cap: 15 }},
                {{ keys: ['KOMBI', 'MULTIVAN', 'ZAFIRA', 'SPACEFOX', 'DOBLO', 'SPIN'], cap: 8 }},
                {{ keys: ['AMBUL', 'UTI'], cap: 4 }},
                {{ keys: ['FIORINO', 'SAVEIRO', 'STRADA', 'TORO', 'RANGER', 'S10', 'HILUX', 'AMAROK', 'FURG'], cap: 3 }},
                {{ keys: ['SUV', 'PAJERO', 'SW4', 'CAPTIVA', 'CRETA', 'TRACKER', 'RENEGADE'], cap: 7 }},
            ];
            
            function inferirCapacidade(marca, modelo) {{
                const texto = ((marca || '') + ' ' + (modelo || '')).toUpperCase();
                for (const regra of REGRAS_CAPACIDADE) {{
                    if (regra.keys.some(function(k) {{ return texto.includes(k); }})) {{
                        return regra.cap;
                    }}
                }}
                const porTipo = {{ ambulancia: 4, van: 15, micro_onibus: 26, carro: 5 }};
                return porTipo[tipoSelect.value] || 5;
            }}
            
            function obterMarcaAtual() {{
                return marcaInput.value.trim() ||
                    (fipeMarca.selectedIndex > 0 ? fipeMarca.options[fipeMarca.selectedIndex].textContent.trim() : '');
            }}
            
            function sincronizarCapacidadeDesdeModelo() {{
                if (capacidadeManualToggle.checked) return;
                const cap = inferirCapacidade(obterMarcaAtual(), modeloInput.value.trim());
                capacidadeInput.value = cap;
            }}
            
            function aplicarEstadoCapacidade() {{
                if (capacidadeManualToggle.checked) {{
                    capacidadeInput.readOnly = false;
                    capacidadeInput.style.background = '';
                    capacidadeFipeAviso.style.display = 'none';
                    capacidadeManual.value = '1';
                }} else {{
                    capacidadeInput.readOnly = true;
                    capacidadeInput.style.background = '#f5f5f5';
                    capacidadeFipeAviso.style.display = 'block';
                    capacidadeManual.value = '0';
                    sincronizarCapacidadeDesdeModelo();
                }}
            }}
            
            capacidadeManualToggle.addEventListener('change', aplicarEstadoCapacidade);
            tipoSelect.addEventListener('change', sincronizarCapacidadeDesdeModelo);
            aplicarEstadoCapacidade();
            
            function aplicarEstadoModelo() {{
                if (modeloManualToggle.checked) {{
                    modeloInput.readOnly = false;
                    modeloInput.style.background = '';
                    modeloFipeAviso.style.display = 'none';
                }} else {{
                    modeloInput.readOnly = true;
                    modeloInput.style.background = '#f5f5f5';
                    modeloFipeAviso.style.display = 'block';
                }}
            }}
            
            function sincronizarModeloDesdeFipe() {{
                if (modeloManualToggle.checked) return;
                const opcao = fipeModelo.options[fipeModelo.selectedIndex];
                if (fipeModelo.value && opcao) {{
                    modeloInput.value = opcao.textContent.trim();
                }} else {{
                    modeloInput.value = '';
                }}
                sincronizarCapacidadeDesdeModelo();
            }}
            
            modeloManualToggle.addEventListener('change', function() {{
                aplicarEstadoModelo();
                if (!modeloManualToggle.checked) {{
                    sincronizarModeloDesdeFipe();
                    sincronizarCapacidadeDesdeModelo();
                }}
            }});
            modeloInput.addEventListener('input', sincronizarCapacidadeDesdeModelo);
            aplicarEstadoModelo();
            
            function setSelect(sel, items, placeholder) {{
                sel.innerHTML = '<option value="">' + placeholder + '</option>';
                items.forEach(function(item) {{
                    const opt = document.createElement('option');
                    opt.value = item.codigo || item.code || item.id || '';
                    opt.textContent = item.nome || item.name || item.label || '';
                    sel.appendChild(opt);
                }});
            }}
            
            async function fipeGet(path) {{
                const r = await fetch('/transporte/api/fipe/' + path);
                if (!r.ok) throw new Error('Erro na consulta FIPE');
                return r.json();
            }}
            
            async function carregarMarcas() {{
                fipeStatus.textContent = 'Carregando marcas...';
                fipeModelo.disabled = true;
                fipeAno.disabled = true;
                setSelect(fipeModelo, [], 'Selecione a marca...');
                setSelect(fipeAno, [], 'Selecione o modelo...');
                try {{
                    const marcas = await fipeGet(FIPE_TIPO + '/marcas');
                    setSelect(fipeMarca, marcas, 'Selecione a marca...');
                    fipeStatus.textContent = 'Selecione marca, modelo e ano.';
                }} catch (e) {{
                    fipeStatus.textContent = '❌ Erro ao carregar marcas FIPE.';
                }}
            }}
            
            fipeMarca.addEventListener('change', async function() {{
                if (!fipeMarca.value) return;
                if (!modeloManualToggle.checked) {{
                    modeloInput.value = '';
                }}
                if (!capacidadeManualToggle.checked) {{
                    capacidadeInput.value = '';
                }}
                fipeStatus.textContent = 'Carregando modelos...';
                fipeAno.disabled = true;
                setSelect(fipeAno, [], 'Selecione o modelo...');
                try {{
                    const modelos = await fipeGet(FIPE_TIPO + '/marcas/' + fipeMarca.value + '/modelos');
                    setSelect(fipeModelo, modelos.modelos || modelos, 'Selecione o modelo...');
                    fipeModelo.disabled = false;
                    fipeStatus.textContent = 'Selecione o modelo.';
                }} catch (e) {{
                    fipeStatus.textContent = '❌ Erro ao carregar modelos.';
                }}
            }});
            
            fipeModelo.addEventListener('change', async function() {{
                if (!fipeModelo.value) {{
                    if (!modeloManualToggle.checked) modeloInput.value = '';
                    if (!capacidadeManualToggle.checked) capacidadeInput.value = '';
                    return;
                }}
                sincronizarModeloDesdeFipe();
                fipeStatus.textContent = 'Carregando anos...';
                try {{
                    const anos = await fipeGet(
                        FIPE_TIPO + '/marcas/' + fipeMarca.value + '/modelos/' + fipeModelo.value + '/anos'
                    );
                    setSelect(fipeAno, anos, 'Selecione o ano...');
                    fipeAno.disabled = false;
                    fipeStatus.textContent = 'Selecione o ano para preencher os campos.';
                }} catch (e) {{
                    fipeStatus.textContent = '❌ Erro ao carregar anos.';
                }}
            }});
            
            fipeAno.addEventListener('change', async function() {{
                if (!fipeAno.value) return;
                fipeStatus.textContent = 'Buscando detalhes...';
                try {{
                    const det = await fipeGet(
                        FIPE_TIPO + '/marcas/' + fipeMarca.value + '/modelos/' +
                        fipeModelo.value + '/anos/' + encodeURIComponent(fipeAno.value)
                    );
                    document.getElementById('marca').value = det.Marca || '';
                    if (!modeloManualToggle.checked) {{
                        document.getElementById('modelo').value = det.Modelo || modeloInput.value;
                    }}
                    sincronizarCapacidadeDesdeModelo();
                    const anoMatch = (det.AnoModelo || det.anoModelo || '').toString().match(/\\d{{4}}/);
                    if (anoMatch) document.getElementById('ano').value = anoMatch[0];
                    fipeStatus.textContent = '✅ Marca, modelo e ano preenchidos pela FIPE.';
                }} catch (e) {{
                    fipeStatus.textContent = '❌ Erro ao buscar detalhes do veículo.';
                }}
            }});
            
            carregarMarcas();
        }})();
        </script>
        {script_paleta_cores('cor')}
        '''
        return gerar_layout_base("Cadastro — Veículos e Frotas", conteudo, "veiculos")
    
    @app.route('/veiculos/editar/<int:veiculo_id>', methods=['GET', 'POST'])
    @login_required
    def veiculos_editar(veiculo_id):
        veiculo = db.session.get(Veiculo, veiculo_id)
        if not veiculo:
            flash('Veículo não encontrado!', 'error')
            return redirect(url_for('veiculos'))
        
        if request.method == 'POST':
            try:
                # Extrair dados do formulário
                placa = request.form.get('placa', '').strip().upper()
                marca = request.form.get('marca', '').strip()
                modelo = request.form.get('modelo', '').strip()
                ano = int(request.form.get('ano', 0))
                cor = request.form.get('cor', '').strip()
                tipo = request.form.get('tipo', '').strip()
                capacidade = request.form.get('capacidade')
                adaptado = request.form.get('adaptado') == 'sim'
                observacoes = request.form.get('observacoes', '').strip()
                
                # Validação básica
                if not all([placa, marca, modelo, ano, tipo]):
                    flash('Por favor, preencha todos os campos obrigatórios!', 'error')
                    return redirect(url_for('veiculos_editar', veiculo_id=veiculo_id))
                
                # Verificar se placa já existe em outro veículo
                veiculo_existente = Veiculo.query.filter_by(placa=placa).first()
                if veiculo_existente and veiculo_existente.id != veiculo_id:
                    flash('Placa já cadastrada para outro veículo!', 'error')
                    return redirect(url_for('veiculos_editar', veiculo_id=veiculo_id))
                
                # Atualizar veículo
                veiculo.placa = placa
                veiculo.marca = marca
                veiculo.modelo = modelo
                veiculo.ano = ano
                veiculo.cor = cor if cor else None
                veiculo.tipo = tipo
                veiculo.capacidade = int(capacidade) if capacidade else None
                veiculo.adaptado = adaptado
                veiculo.observacoes = observacoes if observacoes else None
                
                db.session.commit()
                
                flash(f'Veículo "{placa}" atualizado com sucesso!', 'success')
                return redirect(url_for('veiculos'))
                
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao atualizar veículo: {str(e)}', 'error')
                print(f"❌ Erro ao atualizar veículo: {e}")
        
        # Gerar alertas de mensagens flash
        messages_html = ""
        for category, message in get_flashed_messages(with_categories=True):
            alert_class = f"alert-{category}"
            messages_html += f'<div class="alert {alert_class}">{message}</div>'
        
        conteudo = f'''
        <div class="breadcrumb">
            <a href="{url_for('dashboard')}">Início</a> > 
            <a href="{url_for('veiculos')}">Veículos</a> > 
            Editar Veículo
        </div>
        
        <div class="page-header">
            <h2>✏️ Editar Veículo {html_id_badge(veiculo.id)}</h2>
            <p>Atualize as informações do veículo {veiculo.placa}</p>
        </div>
        
        {messages_html}
        
        <div class="card">
            <form method="POST">
                <div class="form-row">
                    <div class="form-group">
                        <label for="placa">Placa *</label>
                        <input type="text" id="placa" name="placa" value="{veiculo.placa}" placeholder="ABC-1234" required style="text-transform: uppercase;">
                    </div>
                    <div class="form-group">
                        <label for="marca">Marca *</label>
                        <input type="text" id="marca" name="marca" value="{veiculo.marca}" required placeholder="Ex: Fiat, Mercedes">
                    </div>
                </div>
                
                <div class="form-row">
                    <div class="form-group">
                        <label for="modelo">Modelo *</label>
                        <input type="text" id="modelo" name="modelo" value="{veiculo.modelo}" required placeholder="Ex: Ducato, Sprinter">
                    </div>
                    <div class="form-group">
                        <label for="ano">Ano *</label>
                        <input type="number" id="ano" name="ano" value="{veiculo.ano}" min="1980" max="2030" required placeholder="AAAA">
                    </div>
                </div>
                
                <div class="form-row">
                    <div class="form-group">
                        <label for="cor">Cor</label>
                        <input type="text" id="cor" name="cor" value="{veiculo.cor or ''}" placeholder="Ex: Branco">
                    </div>
                    <div class="form-group">
                        <label for="tipo">Tipo de Veículo *</label>
                        <select id="tipo" name="tipo" required>
                            <option value="">Selecione...</option>
                            <option value="ambulancia" {"selected" if veiculo.tipo == "ambulancia" else ""}>Ambulância</option>
                            <option value="van" {"selected" if veiculo.tipo == "van" else ""}>Van</option>
                            <option value="micro_onibus" {"selected" if veiculo.tipo == "micro_onibus" else ""}>Micro-ônibus</option>
                            <option value="carro" {"selected" if veiculo.tipo == "carro" else ""}>Carro</option>
                        </select>
                    </div>
                </div>
                
                <div class="form-row">
                    <div class="form-group">
                        <label for="capacidade">Capacidade de Passageiros</label>
                        <input type="number" id="capacidade" name="capacidade" value="{veiculo.capacidade or ''}" min="1" max="50">
                    </div>
                    <div class="form-group">
                        <label for="adaptado">Adaptado para PCD</label>
                        <select id="adaptado" name="adaptado">
                            <option value="nao" {"selected" if not veiculo.adaptado else ""}>Não</option>
                            <option value="sim" {"selected" if veiculo.adaptado else ""}>Sim</option>
                        </select>
                    </div>
                </div>
                
                <div class="form-group">
                    <label for="observacoes">Observações</label>
                    <textarea id="observacoes" name="observacoes" rows="3" placeholder="Equipamentos especiais, restrições, etc.">{veiculo.observacoes or ''}</textarea>
                </div>
                
                <div style="margin-top: 2rem;">
                    <button type="submit" class="btn btn-success">💾 Salvar Alterações</button>
                    <a href="{url_for('veiculos')}" class="btn btn-secondary" style="margin-left: 1rem;">❌ Cancelar</a>
                </div>
            </form>
        </div>
        '''
        return gerar_layout_base("Editar Veículo", conteudo, "veiculos")
    
    @app.route('/veiculos/excluir/<int:veiculo_id>')
    @login_required
    def veiculos_excluir(veiculo_id):
        try:
            veiculo = db.session.get(Veiculo, veiculo_id)
            if not veiculo:
                flash('Veículo não encontrado!', 'error')
                return redirect(url_for('veiculos'))
            
            placa = veiculo.placa
            
            # Verificar se há agendamentos vinculados
            agendamentos_count = Agendamento.query.filter_by(veiculo_id=veiculo_id).count()
            # Verificar se há abastecimentos vinculados
            abastecimentos_count = Abastecimento.query.filter_by(veiculo_id=veiculo_id).count()
            # Verificar se há usos vinculados
            usos_count = UsoVeiculo.query.filter_by(veiculo_id=veiculo_id).count()
            
            total_vinculos = agendamentos_count + abastecimentos_count + usos_count
            
            if total_vinculos > 0:
                # Desativar ao invés de excluir
                veiculo.ativo = False
                db.session.commit()
                flash(f'Veículo "{placa}" desativado (possui {total_vinculos} vínculo(s): {agendamentos_count} agendamento(s), {abastecimentos_count} abastecimento(s), {usos_count} uso(s)).', 'warning')
            else:
                # Excluir permanentemente
                db.session.delete(veiculo)
                db.session.commit()
                flash(f'Veículo "{placa}" excluído com sucesso!', 'success')
            
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao excluir veículo: {str(e)}', 'error')
            print(f"❌ Erro ao excluir veículo: {e}")
        
        return redirect(url_for('veiculos', aba='veiculo'))
    
    # ===== MOTORISTAS =====
    @app.route('/motoristas')
    @login_required
    def motoristas():
        filtros = obter_filtros_motoristas_request()
        page, per_page = obter_paginacao_request()
        total_cadastro = Motorista.query.count()
        query = montar_query_motoristas(filtros)
        motoristas_lista, total, page = listar_paginado(
            query, page, per_page, Motorista.data_cadastro.desc()
        )
        exibidos = len(motoristas_lista)
        tem_filtro = filtros_tem_valores(filtros)
        filtros_url = {k: v for k, v in filtros.items() if v}

        filtros_html = gerar_filtros_motoristas(filtros, total, exibidos, per_page)
        paginacao_html = gerar_paginacao('motoristas', page, per_page, total, filtros_url)
        botoes_impressao = gerar_botoes_impressao('motoristas_imprimir', filtros_url, page, per_page)
        
        motoristas_html = ""
        if motoristas_lista:
            cards_mobile = ""
            motoristas_html = '''
            <div class="card">
                <div style="display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:0.75rem; margin-bottom:1rem;">
                    <h3 style="color: var(--primary-color); margin: 0;">👨‍💼 Motoristas Cadastrados</h3>
                    ''' + botoes_impressao + '''
                </div>
                <div class="stp-list-desktop table-container">
                    <table style="width: 100%; border-collapse: collapse;">
                        <thead>
                            <tr style="background: var(--color-95);">
                                ''' + html_th_id() + '''
                                <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Nome</th>
                                <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">CNH</th>
                                <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Categoria</th>
                                <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Status</th>
                                <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Vencimento CNH</th>
                                <th style="padding: 0.75rem; text-align: center; border-bottom: 2px solid var(--primary-color);">Ações</th>
                            </tr>
                        </thead>
                        <tbody>
            '''
            for motorista in motoristas_lista:
                status_color = {
                    'ativo': 'color: var(--success-color);',
                    'inativo': 'color: var(--gray-color);',
                    'ferias': 'color: var(--warning-color);',
                    'licenca': 'color: var(--info-color);'
                }.get(motorista.status, '')
                acoes = html_acoes_toolbar(
                    html_acao_icone('ti-edit', 'Editar motorista', href=url_for('motoristas_editar', motorista_id=motorista.id), variant='editar'),
                    html_acao_icone('ti-trash', 'Excluir motorista', href=url_for('motoristas_excluir', motorista_id=motorista.id), variant='excluir', confirm_msg='Tem certeza que deseja excluir este motorista?'),
                )
                venc = motorista.vencimento_cnh.strftime('%d/%m/%Y') if motorista.vencimento_cnh else '—'
                status_txt = (motorista.status or '').title()
                motoristas_html += f'''
                            <tr>
                                {html_td_id(motorista.id)}
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{html_esc(motorista.nome)}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{html_esc(motorista.cnh)}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{html_esc(motorista.categoria_cnh)}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color); {status_color}">{html_esc(status_txt)}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{venc}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color); text-align: center;">{acoes}</td>
                            </tr>
                '''
                cards_mobile += html_mobile_card(
                    title=f'#{motorista.id} {motorista.nome or "—"}',
                    meta=f'CNH {html_esc(motorista.cnh)}',
                    status_html=f'<span style="{status_color}">{html_esc(status_txt)}</span>',
                    rows=[
                        ('ID', f'<strong>{motorista.id}</strong>'),
                        ('Categoria', html_esc(motorista.categoria_cnh)),
                        ('Venc. CNH', venc),
                    ],
                    acoes_html=acoes,
                )
            motoristas_html += f'''
                        </tbody>
                    </table>
                </div>
                <div class="stp-list-mobile">{cards_mobile}</div>
            </div>
            '''
        elif tem_filtro:
            motoristas_html = '''
            <div class="card">
                <p style="margin: 0; color: var(--gray-color);">
                    Nenhum motorista encontrado com os filtros selecionados.
                </p>
            </div>
            '''
        
        conteudo = f'''
        <div class="page-header">
            <h2>👨‍💼 Gerenciamento de Motoristas</h2>
            <p>Cadastro e controle dos motoristas do sistema</p>
            <div style="margin-top: 1rem;">
                <a href="{url_for('motoristas_cadastrar')}" class="btn">👨‍💼 Cadastrar Novo Motorista</a>
            </div>
        </div>
        
        {filtros_html}
        {motoristas_html}
        {paginacao_html}

        {f'<div class="card"><div class="coming-soon"><div class="icon">👨‍💼</div><h3>Nenhum motorista cadastrado</h3><p>Comece cadastrando o primeiro motorista!</p></div></div>' if not total_cadastro and not tem_filtro else ''}
        '''
        return gerar_layout_base("Motoristas", conteudo, "motoristas")

    @app.route('/motoristas/imprimir')
    @login_required
    def motoristas_imprimir():
        filtros = obter_filtros_motoristas_request()
        page, per_page = obter_paginacao_request()
        paginas = request.args.get('paginas', 'atual')
        query = montar_query_motoristas(filtros)
        lista, total, total_pages, pag_ini, pag_fim = buscar_lista_impressao(
            query, page, per_page, paginas, Motorista.data_cadastro.desc()
        )
        return gerar_html_impressao_motoristas(lista, filtros)
    
        # ✅ MOTORISTA CADASTRAR (com endereço via CEP e máscaras)

    @app.route('/motoristas/cadastrar', methods=['GET', 'POST'])
    @login_required
    def motoristas_cadastrar():
        if request.method == 'POST':
            try:
                # Extrair dados do formulário
                nome = request.form.get('nome', '').strip()
                cpf = request.form.get('cpf', '').strip()
                telefone = request.form.get('telefone', '').strip()
                data_nascimento = request.form.get('data_nascimento')
                cnh = request.form.get('cnh', '').strip()
                categoria_cnh = request.form.get('categoria_cnh', '').strip()
                vencimento_cnh = request.form.get('vencimento_cnh')
                cep = request.form.get('cep', '').strip()
                logradouro = request.form.get('logradouro', '').strip()
                numero = request.form.get('numero', '').strip()
                bairro = request.form.get('bairro', '').strip()
                ponto_referencia = request.form.get('ponto_referencia', '').strip()
                endereco = request.form.get('endereco', '').strip()
                status = request.form.get('status', 'ativo').strip()
                observacoes = request.form.get('observacoes', '').strip()
                
                # Validação básica
                if not all([nome, cpf, telefone, data_nascimento, cnh, categoria_cnh, vencimento_cnh]):
                    flash('Por favor, preencha todos os campos obrigatórios!', 'error')
                    return redirect(url_for('motoristas_cadastrar'))

                cpf_fmt, cpf_erro = validar_e_formatar_cpf(cpf)
                if cpf_erro:
                    flash(cpf_erro, 'error')
                    return redirect(url_for('motoristas_cadastrar'))
                cpf = cpf_fmt

                if buscar_motorista_por_cpf(cpf):
                    flash('CPF já cadastrado no sistema!', 'error')
                    return redirect(url_for('motoristas_cadastrar'))
                
                if Motorista.query.filter_by(cnh=cnh).first():
                    flash('CNH já cadastrada no sistema!', 'error')
                    return redirect(url_for('motoristas_cadastrar'))
                
                # Converter datas
                data_nascimento = datetime.strptime(data_nascimento, '%Y-%m-%d').date()
                vencimento_cnh = datetime.strptime(vencimento_cnh, '%Y-%m-%d').date()
                
                # Criar novo motorista
                motorista = Motorista(
                    nome=nome,
                    cpf=cpf,
                    telefone=telefone,
                    data_nascimento=data_nascimento,
                    cnh=cnh,
                    categoria_cnh=categoria_cnh,
                    vencimento_cnh=vencimento_cnh,
                    endereco=endereco if endereco else None,
                    cep=cep if cep else None,
                    logradouro=logradouro if logradouro else None,
                    numero=numero if numero else None,
                    bairro=bairro if bairro else None,
                    ponto_referencia=ponto_referencia if ponto_referencia else None,
                    status=status,
                    observacoes=observacoes if observacoes else None
                )
                
                db.session.add(motorista)
                db.session.commit()
                
                flash(f'Motorista "{nome}" cadastrado com sucesso!', 'success')
                return redirect(url_for('motoristas'))
                
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao cadastrar motorista: {str(e)}', 'error')
                print(f"❌ Erro ao cadastrar motorista: {e}")
        
        # Gerar alertas de mensagens flash
        messages_html = ""
        for category, message in get_flashed_messages(with_categories=True):
            alert_class = f"alert-{category}"
            messages_html += f'<div class="alert {alert_class}">{message}</div>'
        
        conteudo = f'''
        <div class="breadcrumb">
            <a href="{url_for('dashboard')}">Início</a> > 
            <a href="{url_for('motoristas')}">Motoristas</a> > 
            Cadastrar Novo Motorista
        </div>
        
        {html_page_header_ajuda(
            '👨‍💼 Cadastrar Novo Motorista',
            'Preencha os dados do motorista que será registrado no sistema',
            'motorista',
            AJUDA_MOTORISTA,
            title_curto='Ajuda sobre o cadastro de motorista',
        )}
        
        {messages_html}
        
        <div class="card">
            <form method="POST">
                <div class="form-row">
                    <div class="form-group">
                        <label for="nome">Nome Completo *</label>
                        <input type="text" id="nome" name="nome" required>
                    </div>
                    <div class="form-group">
                        <label for="cpf">CPF *</label>
                        <input type="text" id="cpf" name="cpf" placeholder="000.000.000-00" maxlength="14" required>
                        <small id="cpf-status"></small>
                    </div>
                </div>
                
                <div class="form-row">
                    <div class="form-group">
                        <label for="telefone">Telefone *</label>
                        <input type="tel" id="telefone" name="telefone" placeholder="(00) 00000-0000" required
                               data-mask="phone" autocomplete="tel" maxlength="16">
                    </div>
                    <div class="form-group">
                        <label for="data_nascimento">Data de Nascimento *</label>
                        <input type="date" id="data_nascimento" name="data_nascimento" required>
                    </div>
                </div>
                
                <!-- SEÇÃO DE CNH -->
                <div style="background: var(--color-95); padding: 1.5rem; border-radius: 0.5rem; margin: 1rem 0;">
                    <h4 style="color: var(--primary-color); margin-bottom: 1rem;">🚦 Dados da CNH</h4>
                    <div class="form-row">
                        <div class="form-group">
                            <label for="cnh">Número da CNH *</label>
                            <input type="text" id="cnh" name="cnh" required>
                        </div>
                        <div class="form-group">
                            <label for="categoria_cnh">Categoria CNH *</label>
                            <select id="categoria_cnh" name="categoria_cnh" required>
                                <option value="">Selecione...</option>
                                
                                <optgroup label="Categorias Simples">
                                    <option value="A">A - Motocicleta</option>
                                    <option value="B">B - Veículo de passeio (até 3.500kg)</option>
                                    <option value="C">C - Veículo de carga (+3.500kg)</option>
                                    <option value="D">D - Transporte de passageiros (+8 lugares)</option>
                                    <option value="E">E - Veículo com unidade acoplada</option>
                                </optgroup>
                                
                                <optgroup label="Categorias Combinadas">
                                    <option value="AB">AB - A + B (Moto e Carro)</option>
                                    <option value="AC">AC - A + C (Moto e Carga)</option>
                                    <option value="AD">AD - A + D (Moto e Passageiros)</option>
                                    <option value="AE">AE - A + E (Moto e Articulados)</option>
                                </optgroup>
                            </select>
                        </div>
                    </div>
                    <div class="form-group">
                        <label for="vencimento_cnh">Vencimento da CNH *</label>
                        <input type="date" id="vencimento_cnh" name="vencimento_cnh" required>
                    </div>
                </div>
                
                <!-- SEÇÃO DE ENDEREÇO COM VIACEP -->
                <div style="background: var(--color-95); padding: 1.5rem; border-radius: 0.5rem; margin: 1rem 0;">
                    <h4 style="color: var(--primary-color); margin-bottom: 1rem;">🗺️ Endereço</h4>
                    
                    <div class="form-row">
                        <div class="form-group">
                            <label for="cep">CEP *</label>
                            <input type="text" id="cep" name="cep" placeholder="00000-000" maxlength="9" onblur="buscarCEP()">
                            <small id="cep-status" style="color: var(--gray-color);">Digite o CEP para buscar o endereço automaticamente</small>
                        </div>
                        <div class="form-group">
                            <label for="cidade">Cidade</label>
                            <input type="text" id="cidade" name="cidade" readonly style="background: #f5f5f5;">
                        </div>
                    </div>
                    
                    <div class="form-row">
                        <div class="form-group">
                            <label for="logradouro">Logradouro *</label>
                            <input type="text" id="logradouro" name="logradouro" required>
                        </div>
                        <div class="form-group">
                            <label for="numero">Número *</label>
                            <input type="text" id="numero" name="numero" placeholder="Nº" required>
                        </div>
                    </div>
                    
                    <div class="form-row">
                        <div class="form-group">
                            <label for="bairro">Bairro *</label>
                            <input type="text" id="bairro" name="bairro" required>
                        </div>
                        <div class="form-group">
                            <label for="ponto_referencia">Ponto de Referência</label>
                            <input type="text" id="ponto_referencia" name="ponto_referencia" placeholder="Ex: Próximo ao hospital...">
                        </div>
                    </div>
                    
                    <div class="form-group">
                        <label for="endereco">Endereço Completo *</label>
                        <input type="text" id="endereco" name="endereco" placeholder="Rua, número, complemento" required>
                    </div>
                </div>
                
                <div class="form-row">
                    <div class="form-group">
                        <label for="status">Status *</label>
                        <select id="status" name="status" required>
                            <option value="ativo">Ativo</option>
                            <option value="inativo">Inativo</option>
                            <option value="ferias">Férias</option>
                            <option value="licenca">Licença</option>
                        </select>
                    </div>
                </div>
                
                <div class="form-group">
                    <label for="observacoes">Observações</label>
                    <textarea id="observacoes" name="observacoes" rows="3" placeholder="Especializações, restrições, etc."></textarea>
                </div>
                
                <div style="margin-top: 2rem;">
                    <button type="submit" class="btn btn-success">💾 Salvar Motorista</button>
                    <a href="{url_for('motoristas')}" class="btn btn-secondary" style="margin-left: 1rem;">❌ Cancelar</a>
                </div>
            </form>
        </div>
        
        {html_script_cpf_validacao()}
        
        <script>
            // Máscara para CEP
            document.getElementById('cep').addEventListener('input', function(e) {{
                let value = e.target.value.replace(/\\D/g, '');
                if (value.length > 5) {{
                    value = value.replace(/^(\\d{{5}})(\\d+)/, '$1-$2');
                }}
                e.target.value = value;
            }});
            
            // Função para buscar CEP via ViaCEP
            async function buscarCEP() {{
                const cepInput = document.getElementById('cep');
                const statusElement = document.getElementById('cep-status');
                const cep = cepInput.value.replace(/\\D/g, '');
                
                document.getElementById('logradouro').value = '';
                document.getElementById('bairro').value = '';
                document.getElementById('cidade').value = '';
                
                if (cep.length !== 8) {{
                    statusElement.textContent = 'CEP deve ter 8 dígitos';
                    statusElement.style.color = 'var(--danger-color)';
                    return;
                }}
                
                statusElement.textContent = '🔍 Buscando CEP...';
                statusElement.style.color = 'var(--primary-color)';
                
                try {{
                    const response = await fetch(`https://viacep.com.br/ws/${{cep}}/json/`);
                    const data = await response.json();
                    
                    if (data.erro) {{
                        statusElement.textContent = '❌ CEP não encontrado';
                        statusElement.style.color = 'var(--danger-color)';
                        return;
                    }}
                    
                    document.getElementById('logradouro').value = data.logradouro || '';
                    document.getElementById('bairro').value = data.bairro || '';
                    document.getElementById('cidade').value = `${{data.localidade}} - ${{data.uf}}` || '';
                    
                    let enderecoBase = '';
                    if (data.logradouro) {{
                        enderecoBase += data.logradouro;
                        if (data.bairro) enderecoBase += `, ${{data.bairro}}`;
                        if (data.localidade) enderecoBase += `, ${{data.localidade}}`;
                        if (data.uf) enderecoBase += ` - ${{data.uf}}`;
                        
                        const enderecoInput = document.getElementById('endereco');
                        if (!enderecoInput.value) {{
                            enderecoInput.placeholder = `${{enderecoBase}}, [NÚMERO]`;
                        }}
                    }}
                    
                    statusElement.textContent = '✅ CEP encontrado! Complete com o número.';
                    statusElement.style.color = 'var(--success-color)';
                    document.getElementById('endereco').focus();
                    
                }} catch (error) {{
                    console.error('Erro ao buscar CEP:', error);
                    statusElement.textContent = '❌ Erro ao buscar CEP. Verifique sua conexão.';
                    statusElement.style.color = 'var(--danger-color)';
                }}
            }}
            
            // Máscara para Telefone
            document.getElementById('telefone').addEventListener('input', function(e) {{
                let value = e.target.value.replace(/\\D/g, '');
                if (value.length <= 10) {{
                    value = value.replace(/(\\d{{2}})(\\d{{4}})(\\d{{4}})/, '($1) $2-$3');
                }} else {{
                    value = value.replace(/(\\d{{2}})(\\d{{5}})(\\d{{4}})/, '($1) $2-$3');
                }}
                e.target.value = value;
            }});
        </script>
        {html_script_cpf_validacao()}
        '''
        return gerar_layout_base("Cadastrar Motorista", conteudo, "motoristas")
    
    @app.route('/motoristas/editar/<int:motorista_id>', methods=['GET', 'POST'])
    @login_required
    def motoristas_editar(motorista_id):
        motorista = db.session.get(Motorista, motorista_id)
        if not motorista:
            flash('Motorista não encontrado!', 'error')
            return redirect(url_for('motoristas'))
        
        if request.method == 'POST':
            try:
                nome = request.form.get('nome', '').strip()
                cpf = request.form.get('cpf', '').strip()
                telefone = request.form.get('telefone', '').strip()
                data_nascimento = request.form.get('data_nascimento')
                cnh = request.form.get('cnh', '').strip()
                categoria_cnh = request.form.get('categoria_cnh', '').strip()
                vencimento_cnh = request.form.get('vencimento_cnh')
                endereco = request.form.get('endereco', '').strip()
                cep = request.form.get('cep', '').strip()
                logradouro = request.form.get('logradouro', '').strip()
                numero = request.form.get('numero', '').strip()
                bairro = request.form.get('bairro', '').strip()
                ponto_referencia = request.form.get('ponto_referencia', '').strip()
                status = request.form.get('status', '').strip()
                observacoes = request.form.get('observacoes', '').strip()
                
                if not all([nome, cpf, telefone, data_nascimento, cnh, categoria_cnh, vencimento_cnh]):
                    flash('Por favor, preencha todos os campos obrigatórios!', 'error')
                    return redirect(url_for('motoristas_editar', motorista_id=motorista_id))

                cpf_fmt, cpf_erro = validar_e_formatar_cpf(cpf)
                if cpf_erro:
                    flash(cpf_erro, 'error')
                    return redirect(url_for('motoristas_editar', motorista_id=motorista_id))
                cpf = cpf_fmt

                existente = buscar_motorista_por_cpf(cpf, excluir_id=motorista_id)
                if existente:
                    flash('CPF já cadastrado!', 'error')
                    return redirect(url_for('motoristas_editar', motorista_id=motorista_id))
                
                data_nasc = datetime.strptime(data_nascimento, '%Y-%m-%d').date()
                venc_cnh = datetime.strptime(vencimento_cnh, '%Y-%m-%d').date()
                
                motorista.nome = nome
                motorista.cpf = cpf
                motorista.telefone = telefone
                motorista.data_nascimento = data_nasc
                motorista.cnh = cnh
                motorista.categoria_cnh = categoria_cnh
                motorista.vencimento_cnh = venc_cnh
                motorista.endereco = endereco if endereco else None
                motorista.cep = cep if cep else None
                motorista.logradouro = logradouro if logradouro else None
                motorista.numero = numero if numero else None
                motorista.bairro = bairro if bairro else None
                motorista.ponto_referencia = ponto_referencia if ponto_referencia else None
                motorista.status = status
                motorista.observacoes = observacoes if observacoes else None
                
                db.session.commit()
                flash(f'Motorista "{nome}" atualizado!', 'success')
                return redirect(url_for('motoristas'))
                
            except Exception as e:
                db.session.rollback()
                flash(f'Erro: {str(e)}', 'error')
        
        messages_html = ""
        for category, message in get_flashed_messages(with_categories=True):
            messages_html += f'<div class="alert alert-{category}">{message}</div>'
        
        conteudo = f'''
        <div class="breadcrumb">
            <a href="{url_for('dashboard')}">Início</a> > 
            <a href="{url_for('motoristas')}">Motoristas</a> > Editar
        </div>
        
        <div class="page-header">
            <h2>✏️ Editar Motorista {html_id_badge(motorista.id)}</h2>
            <p>Atualize as informações do motorista {motorista.nome}</p>
        </div>
        
        {messages_html}
        
        <div class="card">
            <form method="POST">
                <div class="form-row">
                    <div class="form-group">
                        <label for="nome">Nome Completo *</label>
                        <input type="text" id="nome" name="nome" value="{motorista.nome}" required>
                    </div>
                    <div class="form-group">
                        <label for="cpf">CPF *</label>
                        <input type="text" id="cpf" name="cpf" value="{motorista.cpf}" maxlength="14" required>
                        <small id="cpf-status"></small>
                    </div>
                </div>
                
                <div class="form-row">
                    <div class="form-group">
                        <label for="telefone">Telefone *</label>
                        <input type="tel" id="telefone" name="telefone" value="{motorista.telefone}" maxlength="15" required
                               placeholder="(00) 00000-0000" data-mask="phone" autocomplete="tel">
                    </div>
                    <div class="form-group">
                        <label for="data_nascimento">Data de Nascimento *</label>
                        <input type="date" id="data_nascimento" name="data_nascimento" value="{motorista.data_nascimento.strftime('%Y-%m-%d')}" required>
                    </div>
                </div>
                
                <div class="form-row">
                    <div class="form-group">
                        <label for="cnh">CNH *</label>
                        <input type="text" id="cnh" name="cnh" value="{motorista.cnh}" maxlength="20" required>
                    </div>
                    <div class="form-group">
                        <label for="categoria_cnh">Categoria CNH *</label>
                        <select id="categoria_cnh" name="categoria_cnh" required>
                            <option value="">Selecione...</option>
                            <optgroup label="Categorias Simples">
                                <option value="A" {"selected" if motorista.categoria_cnh == "A" else ""}>A - Motocicleta</option>
                                <option value="B" {"selected" if motorista.categoria_cnh == "B" else ""}>B - Veículo de passeio (até 3.500kg)</option>
                                <option value="C" {"selected" if motorista.categoria_cnh == "C" else ""}>C - Veículo de carga (+3.500kg)</option>
                                <option value="D" {"selected" if motorista.categoria_cnh == "D" else ""}>D - Transporte de passageiros (+8 lugares)</option>
                                <option value="E" {"selected" if motorista.categoria_cnh == "E" else ""}>E - Veículo com unidade acoplada</option>
                            </optgroup>
                            <optgroup label="Categorias Combinadas">
                                <option value="AB" {"selected" if motorista.categoria_cnh == "AB" else ""}>AB - A + B (Moto e Carro)</option>
                                <option value="AC" {"selected" if motorista.categoria_cnh == "AC" else ""}>AC - A + C (Moto e Carga)</option>
                                <option value="AD" {"selected" if motorista.categoria_cnh == "AD" else ""}>AD - A + D (Moto e Passageiros)</option>
                                <option value="AE" {"selected" if motorista.categoria_cnh == "AE" else ""}>AE - A + E (Moto e Articulados)</option>
                            </optgroup>
                        </select>
                    </div>
                </div>
                
                <div class="form-row">
                    <div class="form-group">
                        <label for="vencimento_cnh">Vencimento CNH *</label>
                        <input type="date" id="vencimento_cnh" name="vencimento_cnh" value="{motorista.vencimento_cnh.strftime('%Y-%m-%d')}" required>
                    </div>
                    <div class="form-group">
                        <label for="status">Status *</label>
                        <select id="status" name="status" required>
                            <option value="ativo" {"selected" if motorista.status == "ativo" else ""}>Ativo</option>
                            <option value="inativo" {"selected" if motorista.status == "inativo" else ""}>Inativo</option>
                            <option value="ferias" {"selected" if motorista.status == "ferias" else ""}>Férias</option>
                            <option value="licenca" {"selected" if motorista.status == "licenca" else ""}>Licença</option>
                        </select>
                    </div>
                </div>
                
                <!-- SEÇÃO DE ENDEREÇO -->
                <div style="background: var(--color-95); padding: 1.5rem; border-radius: 0.5rem; margin: 1rem 0;">
                    <h4 style="color: var(--primary-color); margin-bottom: 1rem;">🗺️ Endereço</h4>
                    
                    <div class="form-row">
                        <div class="form-group">
                            <label for="cep">CEP</label>
                            <input type="text" id="cep" name="cep" value="{motorista.cep or ''}" maxlength="9" onblur="buscarCEP()">
                            <small id="cep-status" style="color: var(--gray-color);">Digite o CEP para buscar o endereço</small>
                        </div>
                        <div class="form-group">
                            <label for="cidade">Cidade</label>
                            <input type="text" id="cidade" name="cidade" readonly style="background: #f5f5f5;" value="">
                        </div>
                    </div>
                    
                    <div class="form-row">
                        <div class="form-group">
                            <label for="logradouro">Logradouro *</label>
                            <input type="text" id="logradouro" name="logradouro" value="{motorista.logradouro or ''}" required>
                        </div>
                        <div class="form-group">
                            <label for="numero">Número *</label>
                            <input type="text" id="numero" name="numero" value="{motorista.numero or ''}" placeholder="Nº" required>
                        </div>
                    </div>
                    
                    <div class="form-row">
                        <div class="form-group">
                            <label for="bairro">Bairro *</label>
                            <input type="text" id="bairro" name="bairro" value="{motorista.bairro or ''}" required>
                        </div>
                        <div class="form-group">
                            <label for="ponto_referencia">Ponto de Referência</label>
                            <input type="text" id="ponto_referencia" name="ponto_referencia" value="{motorista.ponto_referencia or ''}" placeholder="Ex: Próximo ao hospital...">
                        </div>
                    </div>
                    
                    <div class="form-group">
                        <label for="endereco">Endereço Completo</label>
                        <textarea id="endereco" name="endereco" rows="2">{motorista.endereco or ''}</textarea>
                    </div>
                </div>
                
                <div class="form-group">
                    <label for="observacoes">Observações</label>
                    <textarea id="observacoes" name="observacoes" rows="3">{motorista.observacoes or ''}</textarea>
                </div>
                
                <div style="margin-top: 2rem;">
                    <button type="submit" class="btn btn-success">💾 Salvar</button>
                    <a href="{url_for('motoristas')}" class="btn btn-secondary" style="margin-left: 1rem;">❌ Cancelar</a>
                </div>
            </form>
        </div>
        
        {html_script_cpf_validacao()}
        
        <script>
            async function buscarCEP() {{
                const cepInput = document.getElementById('cep');
                const statusElement = document.getElementById('cep-status');
                const cep = cepInput.value.replace(/\\D/g, '');
                
                document.getElementById('logradouro').value = '';
                document.getElementById('bairro').value = '';
                document.getElementById('cidade').value = '';
                
                if (cep.length !== 8) return;
                
                statusElement.textContent = '🔍 Buscando CEP...';
                statusElement.style.color = 'var(--primary-color)';
                
                try {{
                    const response = await fetch(`https://viacep.com.br/ws/${{cep}}/json/`);
                    const data = await response.json();
                    if (data.erro) {{
                        statusElement.textContent = '❌ CEP não encontrado';
                        statusElement.style.color = 'var(--danger-color)';
                        return;
                    }}
                    document.getElementById('logradouro').value = data.logradouro || '';
                    document.getElementById('bairro').value = data.bairro || '';
                    document.getElementById('cidade').value = `${{data.localidade}} - ${{data.uf}}` || '';
                    statusElement.textContent = '✅ CEP encontrado!';
                    statusElement.style.color = 'var(--success-color)';
                }} catch (error) {{
                    statusElement.textContent = '❌ Erro ao buscar CEP';
                    statusElement.style.color = 'var(--danger-color)';
                }}
            }}
            
            document.getElementById('cep').addEventListener('input', function(e) {{
                let value = e.target.value.replace(/\\D/g, '');
                if (value.length > 5) {{
                    value = value.replace(/^(\\d{{5}})(\\d+)/, '$1-$2');
                }}
                e.target.value = value;
            }});
        </script>
        '''
        return gerar_layout_base("Editar Motorista", conteudo, "motoristas")
    
    @app.route('/motoristas/excluir/<int:motorista_id>')
    @login_required
    def motoristas_excluir(motorista_id):
        try:
            motorista = db.session.get(Motorista, motorista_id)
            if not motorista:
                flash('Motorista não encontrado!', 'error')
                return redirect(url_for('motoristas'))
            nome = motorista.nome
            agendamentos_count = Agendamento.query.filter_by(motorista_id=motorista_id).count()
            
            if agendamentos_count > 0:
                motorista.status = 'inativo'
                db.session.commit()
                flash(f'Motorista "{nome}" desativado (possui {agendamentos_count} agendamento(s)).', 'warning')
            else:
                db.session.delete(motorista)
                db.session.commit()
                flash(f'Motorista "{nome}" excluído!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro: {str(e)}', 'error')
        
        return redirect(url_for('motoristas'))
    
     # ===== AGENDAMENTOS =====
    @app.route('/agendamentos')
    @login_required
    def agendamentos():
        filtros = obter_filtros_agendamentos_request()
        page, per_page = obter_paginacao_request()

        query = montar_query_agendamentos(filtros)
        agendamentos_lista, total, page = listar_paginado(
            query, page, per_page, Agendamento.data.desc(), Agendamento.hora.desc()
        )

        filtros_url = {k: v for k, v in filtros.items() if v}
        filtros_html = gerar_filtros_agendamentos(filtros, total, len(agendamentos_lista), per_page)
        paginacao_html = gerar_paginacao_agendamentos(page, per_page, total, filtros_url)
        qtd_programados = query_agendamentos_programados(filtros).count()
        painel_folha_espelho = gerar_botoes_folha_espelho(
            filtros_url,
            page,
            per_page,
            qtd_programados=qtd_programados,
            contexto=rotulo_contexto_folha_espelho(filtros),
        )
        
        agendamentos_html = ""
        if agendamentos_lista:
            from html import escape as esc_html
            cards_mobile = ""
            agendamentos_html = f'''
            <div class="card">
                <form method="POST" action="{url_for('agendamentos_excluir_massa')}" id="form-ag-massa"
                      onsubmit="return stpConfirmarExclusaoMassaAg();">
                <input type="hidden" name="next" value="{esc_html(request.full_path)}">
                <div style="display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:0.75rem; margin-bottom:1rem;">
                    <h3 style="color: var(--primary-color); margin: 0;">📅 Agendamentos</h3>
                    <div style="display:flex;flex-wrap:wrap;gap:0.5rem;align-items:center;">
                      <button type="submit" class="btn" style="background:#dc3545;color:#fff;" id="btn-ag-excluir-massa" disabled>
                        🗑️ Excluir selecionados (<span id="ag-massa-count">0</span>)
                      </button>
                    </div>
                </div>
                <p style="margin:0 0 0.75rem;color:var(--gray-color);font-size:0.9rem;">
                  Marque os itens desejados (ou use “selecionar página”) e exclua em massa.
                  Na lista, <strong style="color:#0f5132;">● Programado</strong> = entra na Folha Espelho;
                  <strong style="color:#6c757d;">○ Sem programação</strong> = ainda falta motorista/veículo.
                  Cancelados só podem ser <strong>reativados</strong> ou <strong>excluídos</strong>.
                </p>
                <div class="stp-list-desktop table-container">
                    <table style="width: 100%; border-collapse: collapse;">
                        <thead>
                            <tr style="background: var(--color-95);">
                                <th style="padding: 0.75rem; text-align: center; border-bottom: 2px solid var(--primary-color); width:2.5rem;">
                                  <input type="checkbox" id="ag-check-all" title="Selecionar página"
                                         onchange="stpToggleAgSelecao(this)" aria-label="Selecionar todos da página">
                                </th>
                                <th style="padding: 0.75rem; text-align: center; border-bottom: 2px solid var(--primary-color); width:4rem;">ID</th>
                                <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Data/Hora</th>
                                <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Paciente</th>
                                <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Especialidade</th>
                                <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Origem → Destino</th>
                                <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Motorista</th>
                                <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Veículo/Frota</th>
                                <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Status</th>
                                <th style="padding: 0.75rem; text-align: center; border-bottom: 2px solid var(--primary-color); width: 12rem;">Ações</th>
                            </tr>
                        </thead>
                        <tbody>
            '''
            for agendamento in agendamentos_lista:
                paciente_nome = agendamento.paciente.nome if agendamento.paciente else '—'
                programado = agendamento_tem_programacao(agendamento)
                if agendamento.motorista:
                    motorista_nome = agendamento.motorista.nome
                    motorista_card = esc_html(agendamento.motorista.nome)
                else:
                    motorista_nome = '<span style="color:#6c757d;font-weight:500;">Aguardando</span>'
                    motorista_card = '<span style="color:#6c757d;font-weight:500;">Aguardando</span>'
                if agendamento.veiculo:
                    veiculo_placa = agendamento.veiculo.placa
                    veiculo_card = esc_html(agendamento.veiculo.placa)
                elif getattr(agendamento, 'frota_id', None) or getattr(agendamento, 'frota', None):
                    recurso = recurso_programacao_exibir(agendamento) or 'Frota'
                    veiculo_placa = esc_html(recurso)
                    veiculo_card = esc_html(recurso)
                else:
                    veiculo_placa = '<span style="color:#6c757d;font-weight:500;">Aguardando</span>'
                    veiculo_card = '<span style="color:#6c757d;font-weight:500;">Aguardando</span>'
                rota_txt = f'{agendamento.origem} → {agendamento.destino}'
                status_label = (agendamento.status or '').replace('_', ' ').title()
                status_color = {
                    'agendado': 'color: #ffc107; font-weight: bold;',
                    'confirmado': 'color: #007bff; font-weight: bold;',
                    'em_andamento': 'color: #28a745; font-weight: bold;',
                    'concluido': 'color: #6c757d; font-weight: bold;',
                    'cancelado': 'color: #dc3545; font-weight: bold;'
                }.get(agendamento.status, '')

                acoes = []
                st = (agendamento.status or '').lower()

                if st == 'cancelado':
                    # Cancelado: só Reativar ou Excluir (exclusão em massa via checkbox).
                    acoes.append(html_acao_icone(
                        'ti-arrow-back-up',
                        'Reativar Agendamento (desfazer cancelamento)',
                        href=url_for('agendamentos_reativar', agendamento_id=agendamento.id),
                        variant='confirmar',
                        confirm_msg=(
                            f'Reativar o agendamento #{agendamento.id}? '
                            'O status voltará para Agendado. Depois será preciso programar novamente se necessário.'
                        ),
                    ))
                    acoes.append(html_acao_icone(
                        'ti-bus',
                        'Programar indisponível — agendamento cancelado. Reative antes.',
                        variant='programar',
                        disabled=True,
                    ))
                    acoes.append(html_acao_icone(
                        'ti-id',
                        'Impressão indisponível — agendamento cancelado',
                        variant='cartao',
                        disabled=True,
                    ))
                else:
                    if agendamento_permite_edicao_cadastro(agendamento):
                        acoes.append(html_acao_icone(
                            'ti-pencil',
                            'Editar Agendamento',
                            href=url_for('agendamentos_corrigir', agendamento_id=agendamento.id),
                            variant='editar',
                        ))
                    if agendamento_permite_programacao(agendamento):
                        acoes.append(html_acao_icone(
                            'ti-bus',
                            'Programar Transporte' if not programado else 'Alterar Programação',
                            href=url_for('agendamentos_editar', agendamento_id=agendamento.id),
                            variant='programar',
                        ))
                    else:
                        acoes.append(html_acao_icone(
                            'ti-bus',
                            'Programar indisponível para este status',
                            variant='programar',
                            disabled=True,
                        ))

                    if agendamento.status == 'agendado':
                        acoes.append(html_acao_icone(
                            'ti-circle-check',
                            'Confirmar Agendamento',
                            href=url_for('alterar_status_agendamento', agendamento_id=agendamento.id, novo_status='confirmado'),
                            variant='confirmar',
                        ))
                    elif agendamento.status == 'confirmado':
                        acoes.append(html_acao_icone(
                            'ti-player-play',
                            'Iniciar Transporte',
                            href=url_for('alterar_status_agendamento', agendamento_id=agendamento.id, novo_status='em_andamento'),
                            variant='iniciar',
                        ))
                    elif agendamento.status == 'em_andamento':
                        acoes.append(html_acao_icone(
                            'ti-flag',
                            'Concluir Transporte',
                            href=url_for('alterar_status_agendamento', agendamento_id=agendamento.id, novo_status='concluido'),
                            variant='concluir',
                        ))

                    if agendamento.status not in ['concluido', 'cancelado']:
                        acoes.append(html_acao_icone(
                            'ti-circle-x',
                            'Cancelar Agendamento',
                            href=url_for('alterar_status_agendamento', agendamento_id=agendamento.id, novo_status='cancelado'),
                            variant='cancelar',
                        ))

                    cartao_ok, cartao_motivo = agendamento_elegivel_cartao_motorista(agendamento)
                    if cartao_ok:
                        acoes.append(html_acao_icone(
                            'ti-id',
                            'Imprimir Cartão do Motorista',
                            href=url_for('cartao_motorista', agendamento_id=agendamento.id),
                            variant='cartao',
                            target='_blank',
                        ))
                    else:
                        acoes.append(html_acao_icone(
                            'ti-id',
                            cartao_motivo or 'Cartão indisponível',
                            variant='cartao',
                            disabled=True,
                        ))

                botoes = html_acoes_toolbar(*acoes)
                data_hora = f"{agendamento.data.strftime('%d/%m/%Y')} às {agendamento.hora.strftime('%H:%M')}"
                esp_txt = formatar_especialidade_exibir(agendamento.tipo_transporte)
                check = (
                    f'<input type="checkbox" class="stp-ag-check" name="ag_ids" value="{agendamento.id}" '
                    f'onchange="stpAtualizarContagemAg()" aria-label="Selecionar agendamento {agendamento.id}">'
                )
                if st == 'cancelado':
                    prog_badge = (
                        '<div style="font-size:0.72rem;margin-top:0.2rem;color:#dc3545;font-weight:600;">'
                        'Cancelado</div>'
                    )
                elif programado:
                    prog_badge = (
                        '<div style="font-size:0.72rem;margin-top:0.2rem;color:#0f5132;font-weight:700;">'
                        '● Programado</div>'
                    )
                else:
                    prog_badge = (
                        '<div style="font-size:0.72rem;margin-top:0.2rem;color:#6c757d;">'
                        '○ Sem programação</div>'
                    )

                agendamentos_html += f'''
                            <tr>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color); text-align:center;">{check}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color); text-align:center; font-weight:700; color:var(--primary-color); font-variant-numeric:tabular-nums;">{agendamento.id}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{data_hora}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{celula_truncada(paciente_nome, 28)}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{esp_txt}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color); font-size: 0.875rem;">{celula_truncada(rota_txt, 45)}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{motorista_nome if not agendamento.motorista else celula_truncada(motorista_nome, 22)}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{veiculo_placa}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color); {status_color}">{status_label}{prog_badge}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color); text-align: center;">{botoes}</td>
                            </tr>
                '''
                cards_mobile += f'''
                <article class="stp-mobile-card">
                  <div class="stp-mobile-card__top">
                    <label style="display:flex;align-items:flex-start;gap:0.5rem;min-width:0;flex:1;">
                      {check}
                      <span style="min-width:0;">
                        <div class="stp-mobile-card__title">
                          <span style="color:var(--primary-color);font-weight:700;margin-right:0.35rem;">#{agendamento.id}</span>
                          {esc_html(paciente_nome)}
                        </div>
                        <div class="stp-mobile-card__meta">{esc_html(data_hora)}</div>
                      </span>
                    </label>
                    <div class="stp-mobile-card__status" style="{status_color}">{esc_html(status_label)}{prog_badge}</div>
                  </div>
                  <div class="stp-mobile-card__row">
                    <div class="stp-mobile-card__label">ID</div>
                    <div class="stp-mobile-card__value"><strong>{agendamento.id}</strong></div>
                  </div>
                  <div class="stp-mobile-card__row">
                    <div class="stp-mobile-card__label">Especialidade</div>
                    <div class="stp-mobile-card__value">{esc_html(esp_txt)}</div>
                  </div>
                  <div class="stp-mobile-card__row">
                    <div class="stp-mobile-card__label">Rota</div>
                    <div class="stp-mobile-card__value">{esc_html(rota_txt)}</div>
                  </div>
                  <div class="stp-mobile-card__row">
                    <div class="stp-mobile-card__label">Motorista</div>
                    <div class="stp-mobile-card__value">{motorista_card}</div>
                  </div>
                  <div class="stp-mobile-card__row">
                    <div class="stp-mobile-card__label">Veículo/Frota</div>
                    <div class="stp-mobile-card__value">{veiculo_card}</div>
                  </div>
                  <div class="stp-mobile-card__acoes">{botoes}</div>
                </article>
                '''
            agendamentos_html += f'''
                        </tbody>
                    </table>
                </div>
                <div class="stp-list-mobile">{cards_mobile}</div>
                </form>
            </div>
            <script>
            function stpAgChecks() {{
              return Array.prototype.slice.call(document.querySelectorAll('.stp-ag-check'));
            }}
            function stpAgIdsSelecionados() {{
              var ids = {{}};
              stpAgChecks().forEach(function(c) {{
                if (c.checked) ids[String(c.value)] = true;
              }});
              return Object.keys(ids);
            }}
            function stpAtualizarContagemAg() {{
              var checks = stpAgChecks();
              var n = stpAgIdsSelecionados().length;
              var el = document.getElementById('ag-massa-count');
              var btn = document.getElementById('btn-ag-excluir-massa');
              if (el) el.textContent = String(n);
              if (btn) btn.disabled = n === 0;
              var master = document.getElementById('ag-check-all');
              var uniqueTotal = {{}};
              checks.forEach(function(c) {{ uniqueTotal[String(c.value)] = true; }});
              var totalUnicos = Object.keys(uniqueTotal).length;
              if (master && totalUnicos) {{
                master.checked = n === totalUnicos && n > 0;
                master.indeterminate = n > 0 && n < totalUnicos;
              }}
            }}
            function stpToggleAgSelecao(master) {{
              var on = !!master.checked;
              stpAgChecks().forEach(function(c) {{ c.checked = on; }});
              stpAtualizarContagemAg();
            }}
            function stpConfirmarExclusaoMassaAg() {{
              var n = stpAgIdsSelecionados().length;
              if (!n) {{
                alert('Selecione ao menos um agendamento.');
                return false;
              }}
              return confirm('Excluir DEFINITIVAMENTE ' + n + ' agendamento(s) selecionado(s)?\\nEsta ação não pode ser desfeita.');
            }}
            document.addEventListener('DOMContentLoaded', stpAtualizarContagemAg);
            </script>
            '''
        elif filtros_agendamentos_ativos(filtros):
            agendamentos_html = '''
            <div class="card">
                <p style="margin: 0; color: var(--gray-color);">
                    Nenhum agendamento encontrado com os filtros selecionados.
                </p>
            </div>
            '''
        
        messages_html = ""
        for category, message in get_flashed_messages(with_categories=True):
            messages_html += f'<div class="alert alert-{category}">{message}</div>'

        conteudo = f'''
        <div class="page-header">
            <h2>📅 Gerenciamento de Agendamentos</h2>
            <p>Etapa 1: cadastrar · Editar dados · Etapa 2: programar viagem (veículo, motorista e observações)</p>
            <div style="margin-top: 1rem;">
                <a href="{url_for('agendamentos_novo')}" class="btn">📅 Novo Agendamento</a>
                <a href="{url_for('demo_cartao_motorista')}" class="btn"
                   style="background:#6a1b9a;color:#fff;"
                   title="Gera várias viagens no mesmo dia e abre cartões A4 paisagem (4 por folha)">
                   🪪 Simular Cartões do Motorista
                </a>
            </div>
        </div>
        
        {messages_html}
        {filtros_html}
        {painel_folha_espelho}
        {agendamentos_html}
        {paginacao_html}
        
        {f'<div class="card"><div class="coming-soon"><div class="icon">📅</div><h3>Nenhum agendamento criado</h3><p>Comece criando o primeiro agendamento!</p></div></div>' if not total and not filtros_agendamentos_ativos(filtros) else ''}
        '''
        return gerar_layout_base("Agendamentos", conteudo, "agendamentos")

    @app.route('/agendamentos/excluir-massa', methods=['POST'])
    @login_required
    def agendamentos_excluir_massa():
        raw_ids = request.form.getlist('ag_ids')
        ids = []
        for raw in raw_ids:
            try:
                ids.append(int(raw))
            except (TypeError, ValueError):
                continue
        ids = sorted(set(ids))
        next_url = (request.form.get('next') or '').strip() or url_for('agendamentos')
        if next_url.startswith('http') or not next_url.startswith('/'):
            next_url = url_for('agendamentos')

        if not ids:
            flash('Nenhum agendamento selecionado para exclusão.', 'warning')
            return redirect(next_url)

        try:
            lista = Agendamento.query.filter(Agendamento.id.in_(ids)).all()
            achados = {a.id for a in lista}
            faltando = [i for i in ids if i not in achados]
            for ag in lista:
                db.session.delete(ag)
            db.session.commit()
            flash(f'{len(lista)} agendamento(s) excluído(s) definitivamente.', 'success')
            if faltando:
                flash(f'{len(faltando)} id(s) não encontrado(s) e foram ignorados.', 'warning')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao excluir agendamentos: {e}', 'error')
        return redirect(next_url)

    @app.route('/agendamentos/imprimir')
    @login_required
    def agendamentos_imprimir():
        filtros = obter_filtros_agendamentos_request()
        page, per_page = obter_paginacao_request()
        paginas = request.args.get('paginas', 'atual')
        lista, total, total_pages, pag_ini, pag_fim = buscar_agendamentos_impressao(
            filtros, page, per_page, paginas
        )
        html = gerar_html_impressao_agendamentos(lista, filtros, pag_ini, pag_fim, per_page)
        return html

    @app.route('/agendamentos/cartoes-motorista')
    @login_required
    def agendamentos_cartoes_motorista():
        """
        Impressão em lote dos Cartões do Motorista do filtro atual
        (todas / página atual) — 1 cartão por viagem programada.
        """
        filtros = obter_filtros_agendamentos_request()
        page, per_page = obter_paginacao_request()
        paginas = request.args.get('paginas', 'todas')
        lista, total, total_pages, pag_ini, pag_fim = buscar_agendamentos_cartoes_impressao(
            filtros, page, per_page, paginas
        )
        # Reforço: só elegíveis (mesma regra do cartão individual)
        lista = [a for a in lista if agendamento_elegivel_cartao_motorista(a)[0]]
        resumo = resumo_filtros_agendamentos(filtros)
        if paginas != 'todas':
            resumo += f' · Páginas: {pag_ini}–{pag_fim}'
        html = gerar_html_lote_cartoes_motorista(lista, titulo_extra=resumo)
        resp = app.response_class(html, mimetype='text/html')
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return resp

    @app.route('/agendamentos/<int:agendamento_id>/folha-espelho')
    @login_required
    def folha_espelho_agendamento(agendamento_id):
        """Folha Espelho de uma única viagem — liberada só com programação completa."""
        agendamento = db.session.get(Agendamento, agendamento_id)
        if not agendamento:
            flash('Agendamento não encontrado!', 'error')
            return redirect(url_for('agendamentos'))

        ok, motivo = agendamento_elegivel_folha_espelho(agendamento)
        if not ok:
            flash(f'Folha Espelho indisponível. {motivo}', 'warning')
            return redirect(url_for('agendamentos_editar', agendamento_id=agendamento_id))

        href_voltar = url_for('agendamentos_editar', agendamento_id=agendamento_id)
        html = gerar_html_impressao_agendamentos(
            [agendamento],
            {'agendamento_id': agendamento_id},
            1,
            1,
            1,
            href_voltar=href_voltar,
        )
        resp = app.response_class(html, mimetype='text/html')
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return resp

    @app.route('/agendamentos/<int:agendamento_id>/cartao-motorista')
    @login_required
    def cartao_motorista(agendamento_id):
        """
        Cartões do Motorista para impressão.
        Por padrão: todas as viagens do mesmo motorista na mesma data (1 cartão cada).
        ?somente=1 → apenas este agendamento.
        """
        agendamento = db.session.get(Agendamento, agendamento_id)
        if not agendamento:
            flash('Agendamento não encontrado!', 'error')
            return redirect(url_for('agendamentos'))

        ok, motivo = agendamento_elegivel_cartao_motorista(agendamento)
        if not ok:
            flash(f'Cartão do Motorista indisponível. {motivo}', 'warning')
            return redirect(url_for('agendamentos_editar', agendamento_id=agendamento_id))

        somente = request.args.get('somente', '').strip() in ('1', 'true', 'sim')
        if somente or not agendamento.motorista_id:
            lista = [agendamento]
        else:
            lista = listar_agendamentos_cartoes_do_dia(
                agendamento.motorista_id, agendamento.data
            )
            # garante elegibilidade
            lista = [a for a in lista if agendamento_elegivel_cartao_motorista(a)[0]]
            if not lista:
                lista = [agendamento]

        html = gerar_html_lote_cartoes_motorista(lista)
        resp = app.response_class(html, mimetype='text/html')
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return resp

    @app.route('/agendamentos/demo-cartao-motorista')
    @login_required
    def demo_cartao_motorista():
        """Simula várias viagens no mesmo dia e abre os cartões (A4 paisagem, 4/folha)."""
        try:
            lista = garantir_agendamento_demo_cartao_motorista()
            if not lista:
                flash('Não foi possível gerar viagens demo.', 'error')
                return redirect(url_for('agendamentos'))
            flash(
                f'{len(lista)} cartões gerados para o motorista (1 por viagem). '
                'Impressão A4 paisagem — 4 por folha.',
                'success',
            )
            # abre lote do dia do primeiro
            return redirect(url_for('cartao_motorista', agendamento_id=lista[0].id))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao simular cartões: {e}', 'error')
            return redirect(url_for('agendamentos'))

    # ===== ROTA PARA ALTERAR STATUS =====
    @app.route('/agendamentos/reativar/<int:agendamento_id>', methods=['GET', 'POST'])
    @login_required
    def agendamentos_reativar(agendamento_id):
        """Desfaz cancelamento: volta o status para agendado (ação explícita)."""
        try:
            agendamento = db.session.get(Agendamento, agendamento_id)
            if not agendamento:
                flash('Agendamento não encontrado!', 'error')
                return redirect(url_for('agendamentos'))
            if not agendamento_permite_reativar(agendamento):
                flash('Somente agendamentos cancelados podem ser reativados.', 'warning')
                return redirect(url_for('agendamentos'))

            agendamento.status = 'agendado'
            db.session.commit()
            flash(
                f'Agendamento #{agendamento.id} reativado com sucesso (status: Agendado). '
                'Se necessário, use Programar para definir motorista e veículo/frota.',
                'success',
            )
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao reativar agendamento: {e}', 'error')
        return redirect(url_for('agendamentos'))

    @app.route('/agendamentos/status/<int:agendamento_id>/<novo_status>')
    @login_required
    def alterar_status_agendamento(agendamento_id, novo_status):
        try:
            agendamento = db.session.get(Agendamento, agendamento_id)
            if not agendamento:
                flash('Agendamento não encontrado!', 'error')
                return redirect(url_for('agendamentos'))
            
            # Validar status
            status_validos = ['agendado', 'confirmado', 'em_andamento', 'concluido', 'cancelado']
            if novo_status not in status_validos:
                flash('Status inválido!', 'error')
                return redirect(url_for('agendamentos'))

            status_atual = (agendamento.status or '').lower()

            # Cancelado só sai via rota Reativar (não por Programar nem por URL genérica)
            if status_atual == 'cancelado' and novo_status != 'cancelado':
                flash(
                    'Agendamento cancelado. Use a ação Reativar para desfazer o cancelamento.',
                    'warning',
                )
                return redirect(url_for('agendamentos'))

            if status_atual == 'concluido' and novo_status != 'concluido':
                flash('Agendamento concluído não pode mudar de status.', 'warning')
                return redirect(url_for('agendamentos'))

            # Iniciar transporte só após programação (veículo/frota + motorista)
            if novo_status == 'em_andamento' and not agendamento_tem_programacao(agendamento):
                flash(
                    'Programe veículo ou frota e o motorista antes de iniciar o transporte '
                    '(use Programar na listagem).',
                    'warning',
                )
                return redirect(url_for('agendamentos_editar', agendamento_id=agendamento.id))
            
            # Atualizar status
            agendamento.status = novo_status
            db.session.commit()
            
            # Notificar cancelamento via WhatsApp
            if novo_status == 'cancelado':
                try:
                    global whatsapp_service, notificacao_agendamento
                    if not whatsapp_service:
                        whatsapp_service = WhatsAppNotificacao(app, db)
                    if not notificacao_agendamento:
                        notificacao_agendamento = NotificacaoAgendamento(whatsapp_service)
                    notificacao_agendamento.notificar_cancelamento(agendamento)
                except Exception as e:
                    print(f'⚠️ Notificação cancelamento WhatsApp: {e}')
            
            # Mensagens de sucesso
            mensagens = {
                'confirmado': 'Agendamento confirmado com sucesso!',
                'em_andamento': 'Transporte iniciado!',
                'concluido': 'Transporte concluído!',
                'cancelado': 'Agendamento cancelado.'
            }
            
            flash(mensagens.get(novo_status, 'Status alterado!'), 'success')
            
        except Exception as e:
            flash(f'Erro: {str(e)}', 'error')
        
        return redirect(url_for('agendamentos'))

    @app.route('/agendamentos/novo', methods=['GET', 'POST'])
    @login_required
    def agendamentos_novo():
        if request.method == 'POST':
            try:
                payload, erro, redirect_extra = extrair_payload_cadastro_agendamento(request.form)
                if erro:
                    flash(erro, 'error')
                    if redirect_extra and redirect_extra.get('paciente_id'):
                        return redirect(url_for('pacientes_editar', paciente_id=redirect_extra['paciente_id']))
                    return redirect(url_for('agendamentos_novo'))

                agendamento = Agendamento(
                    paciente_id=payload['paciente_id'],
                    tipo_transporte=payload['tipo_transporte'],
                    data=payload['data'],
                    hora=payload['hora'],
                    hora_consulta=payload.get('hora_consulta'),
                    origem=payload['origem'],
                    destino=payload['destino'],
                    cep_origem=payload['cep_origem'],
                    cep_destino=payload['cep_destino'],
                    cidade_origem=payload['cidade_origem'],
                    cidade_destino=payload['cidade_destino'],
                    tipo_destino=payload['tipo_destino'],
                    veiculo_id=None,
                    motorista_id=None,
                    observacoes=None,
                )
                erro_ac = aplicar_payload_cadastro_agendamento(agendamento, payload, request.form)
                if erro_ac:
                    flash(erro_ac, 'error')
                    return redirect(url_for('agendamentos_novo'))

                db.session.add(agendamento)
                db.session.commit()

                global whatsapp_service, notificacao_agendamento
                if not whatsapp_service:
                    whatsapp_service = WhatsAppNotificacao(app, db)
                if not notificacao_agendamento:
                    notificacao_agendamento = NotificacaoAgendamento(whatsapp_service)

                try:
                    notificacao_agendamento.notificar_confirmacao(agendamento)
                except Exception as e:
                    print(f"❌ Erro ao enviar WhatsApp: {e}")

                print(f"✅ Agendamento criado: {agendamento.id} para {payload['data']} às {payload['hora']}")
                flash(
                    'Agendamento cadastrado com sucesso! '
                    'Agora use Programar na listagem para definir veículo ou frota e o motorista.',
                    'success',
                )
                return redirect(url_for('agendamentos'))

            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao criar agendamento: {str(e)}', 'error')
                print(f"❌ Erro ao criar agendamento: {e}")

        valores = valores_cadastro_agendamento_vazios()
        conteudo = gerar_conteudo_form_cadastro_agendamento(
            valores=valores,
            breadcrumb_extra='Novo Agendamento',
            titulo='📅 Novo Agendamento',
            subtitulo='Etapa 1 — Cadastro do pedido de transporte (sem veículo/frota/motorista)',
            banner_html=(
                '<div class="alert alert-warning" style="margin-bottom:1rem;">'
                '<strong>Fluxo em 2 etapas:</strong> '
                'neste cadastro informe paciente, especialidade, data/hora e endereços. '
                'Depois, na listagem, use <strong>Programar</strong> para definir veículo ou frota, motorista e observações.'
                '</div>'
            ),
            submit_label='📅 Cadastrar Agendamento',
            cancel_href=url_for('agendamentos'),
        )
        return gerar_layout_base("Novo Agendamento", conteudo, "agendamentos")

    @app.route('/agendamentos/corrigir/<int:agendamento_id>', methods=['GET', 'POST'])
    @login_required
    def agendamentos_corrigir(agendamento_id):
        """Edição segura dos dados cadastrais (etapa 1) — não altera programação de frota."""
        agendamento = db.session.get(Agendamento, agendamento_id)
        if not agendamento:
            flash('Agendamento não encontrado!', 'error')
            return redirect(url_for('agendamentos'))
        if not agendamento_permite_edicao_cadastro(agendamento):
            flash(
                'Este agendamento não pode mais ser editado (concluído ou cancelado).',
                'warning',
            )
            return redirect(url_for('agendamentos'))

        if request.method == 'POST':
            try:
                antes = snapshot_cadastro_agendamento(agendamento)
                payload, erro, redirect_extra = extrair_payload_cadastro_agendamento(request.form)
                if erro:
                    flash(erro, 'error')
                    if redirect_extra and redirect_extra.get('paciente_id'):
                        return redirect(url_for('pacientes_editar', paciente_id=redirect_extra['paciente_id']))
                    return redirect(url_for('agendamentos_corrigir', agendamento_id=agendamento_id))

                erro_ac = aplicar_payload_cadastro_agendamento(agendamento, payload, request.form)
                if erro_ac:
                    flash(erro_ac, 'error')
                    return redirect(url_for('agendamentos_corrigir', agendamento_id=agendamento_id))

                db.session.commit()
                depois = snapshot_cadastro_agendamento(agendamento)
                mudancas = diff_cadastro_agendamento(antes, depois)
                try:
                    usuario = getattr(current_user, 'username', None) or getattr(current_user, 'id', '?')
                    print(
                        f"📝 AUDITORIA agendamento#{agendamento.id} editado por {usuario} "
                        f"em {datetime.now().isoformat(timespec='seconds')} | mudanças={mudancas}"
                    )
                except Exception as e:
                    print(f"⚠️ Falha ao registrar auditoria de edição: {e}")

                flash('Agendamento atualizado com sucesso!', 'success')
                return redirect(url_for('agendamentos'))
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao atualizar agendamento: {str(e)}', 'error')
                print(f"❌ Erro ao corrigir agendamento: {e}")

        valores = valores_cadastro_de_agendamento(agendamento)
        conteudo = gerar_conteudo_form_cadastro_agendamento(
            valores=valores,
            breadcrumb_extra=f'Editar Agendamento #{agendamento.id}',
            titulo=f'✏️ Editar Agendamento #{agendamento.id}',
            subtitulo='Corrija os dados do cadastro. Veículo, motorista e observações permanecem na Programação.',
            banner_html=(
                '<div class="alert alert-info" style="margin-bottom:1rem;">'
                'Altere apenas os dados cadastrais. Para veículo/motorista, use '
                f'<a href="{url_for("agendamentos_editar", agendamento_id=agendamento.id)}"><strong>Programar</strong></a>.'
                '</div>'
            ),
            submit_label='💾 Salvar Alterações',
            cancel_href=url_for('agendamentos'),
            filtro_endpoint='agendamentos_corrigir',
            filtro_endpoint_kwargs={'agendamento_id': agendamento.id},
        )
        return gerar_layout_base("Editar Agendamento", conteudo, "agendamentos")

    @app.route('/agendamentos/editar/<int:agendamento_id>', methods=['GET', 'POST'])
    @login_required
    def agendamentos_editar(agendamento_id):
        """Etapa 2 — Programação da viagem: veículo ou frota + motorista e observações."""
        from html import escape

        agendamento = db.session.get(Agendamento, agendamento_id)
        if not agendamento:
            flash('Agendamento não encontrado!', 'error')
            return redirect(url_for('agendamentos'))

        if not agendamento_permite_programacao(agendamento):
            if agendamento_esta_cancelado(agendamento):
                flash(
                    'Agendamento cancelado. Não é possível programar. '
                    'Use Reativar para voltar ao status Agendado, ou exclua o registro.',
                    'warning',
                )
            else:
                flash('Este agendamento não pode mais ser programado (concluído ou cancelado).', 'warning')
            return redirect(url_for('agendamentos'))

        if request.method == 'POST':
            try:
                observacoes = request.form.get('observacoes', '').strip()
                motorista_id_raw = (request.form.get('motorista_id') or '').strip()
                tipo_recurso = (request.form.get('tipo_recurso') or 'veiculo').strip().lower()
                if tipo_recurso not in ('veiculo', 'frota'):
                    tipo_recurso = 'veiculo'

                if not motorista_id_raw:
                    flash('Informe o motorista para programar a viagem.', 'error')
                    return redirect(url_for('agendamentos_editar', agendamento_id=agendamento_id))

                motorista_id = int(motorista_id_raw)
                if not db.session.get(Motorista, motorista_id):
                    flash('Motorista inválido!', 'error')
                    return redirect(url_for('agendamentos_editar', agendamento_id=agendamento_id))

                if tipo_recurso == 'frota':
                    frota_id_raw = (request.form.get('frota_id') or '').strip()
                    if not frota_id_raw:
                        flash('Selecione a frota para programar a viagem.', 'error')
                        return redirect(url_for('agendamentos_editar', agendamento_id=agendamento_id))
                    frota_id = int(frota_id_raw)
                    frota = db.session.get(Frota, frota_id)
                    if not frota or not frota.ativo:
                        flash('Frota inválida ou inativa!', 'error')
                        return redirect(url_for('agendamentos_editar', agendamento_id=agendamento_id))
                    agendamento.frota_id = frota_id
                    agendamento.veiculo_id = None
                    recurso_msg = frota_identificacao_exibir(frota)
                else:
                    veiculo_id_raw = (request.form.get('veiculo_id') or '').strip()
                    if not veiculo_id_raw:
                        flash('Selecione o veículo para programar a viagem.', 'error')
                        return redirect(url_for('agendamentos_editar', agendamento_id=agendamento_id))
                    veiculo_id = int(veiculo_id_raw)
                    if not db.session.get(Veiculo, veiculo_id):
                        flash('Veículo inválido!', 'error')
                        return redirect(url_for('agendamentos_editar', agendamento_id=agendamento_id))
                    agendamento.veiculo_id = veiculo_id
                    agendamento.frota_id = None
                    recurso_msg = 'veículo'

                agendamento.motorista_id = motorista_id
                agendamento.observacoes = observacoes if observacoes else None
                db.session.commit()
                flash(
                    f'Viagem programada com sucesso ({recurso_msg} + motorista)! '
                    'Impressão liberada: Folha Espelho e Cartão do Motorista.',
                    'success',
                )
                return redirect(url_for('agendamentos_editar', agendamento_id=agendamento_id))
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao programar viagem: {str(e)}', 'error')

        veiculos = Veiculo.query.filter_by(ativo=True).order_by(Veiculo.placa).all()
        frotas = Frota.query.filter_by(ativo=True).order_by(Frota.nome).all()
        motoristas = Motorista.query.filter_by(status='ativo').order_by(Motorista.nome).all()

        tipo_recurso_atual = 'frota' if agendamento.frota_id and not agendamento.veiculo_id else 'veiculo'
        chk_veiculo = 'checked' if tipo_recurso_atual == 'veiculo' else ''
        chk_frota = 'checked' if tipo_recurso_atual == 'frota' else ''
        disp_veiculo = 'block' if tipo_recurso_atual == 'veiculo' else 'none'
        disp_frota = 'block' if tipo_recurso_atual == 'frota' else 'none'
        req_veiculo = 'required' if tipo_recurso_atual == 'veiculo' else ''
        req_frota = 'required' if tipo_recurso_atual == 'frota' else ''

        veiculos_options = '<option value="">Selecione o veículo...</option>'
        for v in veiculos:
            sel = ' selected' if agendamento.veiculo_id == v.id else ''
            nf = numero_frota_exibir(v)
            extra = f' · Frota {escape(nf)}' if nf and nf != '—' else ''
            veiculos_options += (
                f'<option value="{v.id}"{sel}>'
                f'ID {v.id} — {escape(v.marca)} {escape(v.modelo)} - {escape(v.placa)}{extra}</option>'
            )

        frotas_options = '<option value="">Selecione a frota...</option>'
        for f in frotas:
            sel = ' selected' if agendamento.frota_id == f.id else ''
            frotas_options += (
                f'<option value="{f.id}"{sel}>'
                f'ID {f.id} — {escape(frota_identificacao_exibir(f))}</option>'
            )

        motoristas_options = '<option value="">Selecione o motorista...</option>'
        for m in motoristas:
            sel = ' selected' if agendamento.motorista_id == m.id else ''
            cat = escape(m.categoria_cnh or '')
            motoristas_options += (
                f'<option value="{m.id}"{sel}>'
                f'ID {m.id} — {escape(m.nome)} · CNH {cat}</option>'
            )

        messages_html = ""
        for category, message in get_flashed_messages(with_categories=True):
            messages_html += f'<div class="alert alert-{category}">{message}</div>'

        programado = agendamento_tem_programacao(agendamento)
        botoes_impressao_prog = gerar_botoes_impressao_programacao(agendamento)
        paciente = agendamento.paciente
        paciente_nome = escape(paciente.nome if paciente else '—')
        especialidade = escape(formatar_especialidade_exibir(agendamento.tipo_transporte) or '—')
        data_txt = agendamento.data.strftime('%d/%m/%Y') if agendamento.data else '—'
        hora_txt = agendamento.hora.strftime('%H:%M') if agendamento.hora else '—'
        origem_txt = escape(agendamento.origem or '—')
        destino_txt = escape(agendamento.destino or '—')
        obs_val = escape(agendamento.observacoes or '')
        recurso_atual = escape(recurso_programacao_exibir(agendamento) or '')

        banner_prog = (
            f'<div class="alert alert-success">Viagem já programada'
            f'{(" · " + recurso_atual) if recurso_atual else ""}. '
            f'Altere veículo/frota, motorista ou observações se necessário.</div>'
            if programado else
            '<div class="alert alert-warning">'
            'Informe <strong>veículo ou frota</strong>, <strong>motorista</strong> e '
            '<strong>observações</strong>. Esses dados vão para o Cartão e a Folha Espelho.'
            '</div>'
        )

        contexto = (
            f'<p style="margin:0 0 1rem;color:#445560;font-size:0.95rem;">'
            f'<strong>{paciente_nome}</strong> · {especialidade} · {data_txt} às {hora_txt}'
            f'<br><span style="color:#6a7a86;font-size:0.88rem;">{origem_txt} → {destino_txt}</span>'
            f'</p>'
        )

        conteudo = f'''
        <div class="breadcrumb">
            <a href="{url_for('dashboard')}">Início</a> >
            <a href="{url_for('agendamentos')}">Agendamentos</a> >
            Programar Viagem
        </div>

        <div class="page-header">
            <h2>🚌 Programar Viagem #{agendamento.id}</h2>
            <p>Etapa 2 — Defina o recurso (veículo ou frota) e o motorista</p>
        </div>

        {messages_html}
        {banner_prog}
        {botoes_impressao_prog}

        <form method="POST" id="form-programar-viagem">
            <div class="card" style="border-left:4px solid #e67e22;">
                {contexto}

                <div class="form-group">
                    <label>Recurso da viagem *</label>
                    <div style="display:flex;gap:1.25rem;flex-wrap:wrap;margin-top:0.5rem;">
                        <label style="display:flex;align-items:center;gap:0.45rem;font-weight:600;cursor:pointer;">
                            <input type="radio" name="tipo_recurso" value="veiculo" {chk_veiculo}
                                   onchange="alterarTipoRecursoProgramacao()">
                            🚗 Veículo
                        </label>
                        <label style="display:flex;align-items:center;gap:0.45rem;font-weight:600;cursor:pointer;">
                            <input type="radio" name="tipo_recurso" value="frota" {chk_frota}
                                   onchange="alterarTipoRecursoProgramacao()">
                            🚌 Frota
                        </label>
                    </div>
                    <small style="color:var(--gray-color);">
                        Escolha apenas um: o motorista usará o veículo ou a frota informados no Cartão e na Folha Espelho.
                    </small>
                </div>

                <div class="form-row">
                    <div class="form-group" id="bloco-veiculo-prog" style="display:{disp_veiculo};">
                        <label for="busca_veiculo_prog">Buscar veículo</label>
                        <input type="text" id="busca_veiculo_prog" placeholder="ID, placa, marca..."
                               autocomplete="off"
                               style="width:100%;margin-bottom:0.4rem;padding:0.5rem 0.65rem;border:1px solid var(--border-color);border-radius:6px;">
                        <label for="veiculo_id">Veículo *</label>
                        <select id="veiculo_id" name="veiculo_id" {req_veiculo}>{veiculos_options}</select>
                        <small style="color:var(--gray-color);">Opções: ID — marca/modelo - placa</small>
                    </div>
                    <div class="form-group" id="bloco-frota-prog" style="display:{disp_frota};">
                        <label for="busca_frota_prog">Buscar frota</label>
                        <input type="text" id="busca_frota_prog" placeholder="ID, número ou nome..."
                               autocomplete="off"
                               style="width:100%;margin-bottom:0.4rem;padding:0.5rem 0.65rem;border:1px solid var(--border-color);border-radius:6px;">
                        <label for="frota_id">Frota *</label>
                        <select id="frota_id" name="frota_id" {req_frota}>{frotas_options}</select>
                        <small style="color:var(--gray-color);">Opções: ID — Nome - Número (ex.: NI Frota 267 - F00267)</small>
                    </div>
                    <div class="form-group">
                        <label for="busca_motorista_prog">Buscar motorista</label>
                        <input type="text" id="busca_motorista_prog" placeholder="ID ou nome do motorista..."
                               autocomplete="off"
                               style="width:100%;margin-bottom:0.4rem;padding:0.5rem 0.65rem;border:1px solid var(--border-color);border-radius:6px;">
                        <label for="motorista_id">Motorista *</label>
                        <select id="motorista_id" name="motorista_id" required>{motoristas_options}</select>
                        <small style="color:var(--gray-color);">Opções: ID — Nome · CNH (use o ID para evitar homônimos)</small>
                    </div>
                </div>
                <div class="form-group">
                    <label for="observacoes">Observações</label>
                    <textarea id="observacoes" name="observacoes" rows="3"
                              placeholder="Ex.: ponto de encontro, horário da consulta, instruções ao motorista">{obs_val}</textarea>
                </div>
                <div style="margin-top: 1.5rem;">
                    <button type="submit" class="btn btn-success">💾 Salvar Programação</button>
                    <a href="{url_for('agendamentos')}" class="btn btn-secondary" style="margin-left: 1rem;">← Voltar</a>
                </div>
            </div>
        </form>
        <script>
        function stpAtivarBuscaSelect(inputEl, selectEl) {{
            if (!inputEl || !selectEl) return;
            var todas = Array.prototype.map.call(selectEl.options, function(o) {{
                return {{ value: o.value, text: o.text, selected: o.selected }};
            }});
            selectEl._stpTodasOpcoes = todas;
            function filtrar() {{
                var termo = (inputEl.value || '').trim().toLowerCase();
                var valorAtual = selectEl.value;
                selectEl.innerHTML = '';
                todas.forEach(function(opt) {{
                    if (!opt.value) {{
                        selectEl.add(new Option(opt.text, opt.value));
                        return;
                    }}
                    var txt = (opt.text || '').toLowerCase();
                    var idMatch = termo && String(opt.value) === termo;
                    if (!termo || idMatch || txt.indexOf(termo) !== -1) {{
                        selectEl.add(new Option(opt.text, opt.value));
                    }}
                }});
                var aindaVisivel = Array.prototype.some.call(selectEl.options, function(o) {{
                    return o.value === valorAtual;
                }});
                if (aindaVisivel) {{
                    selectEl.value = valorAtual;
                }} else if (termo && selectEl.options.length === 2 && selectEl.options[1].value) {{
                    selectEl.selectedIndex = 1;
                }}
            }}
            inputEl.addEventListener('input', filtrar);
            inputEl.addEventListener('keydown', function(ev) {{
                if (ev.key === 'Enter') {{
                    ev.preventDefault();
                    filtrar();
                    if (selectEl.options.length === 2 && selectEl.options[1].value) {{
                        selectEl.selectedIndex = 1;
                    }}
                }}
            }});
        }}
        function alterarTipoRecursoProgramacao() {{
            var tipoVeiculo = document.querySelector('input[name="tipo_recurso"][value="veiculo"]').checked;
            var blocoV = document.getElementById('bloco-veiculo-prog');
            var blocoF = document.getElementById('bloco-frota-prog');
            var selV = document.getElementById('veiculo_id');
            var selF = document.getElementById('frota_id');
            blocoV.style.display = tipoVeiculo ? 'block' : 'none';
            blocoF.style.display = tipoVeiculo ? 'none' : 'block';
            if (tipoVeiculo) {{
                selV.setAttribute('required', 'required');
                selF.removeAttribute('required');
                selF.value = '';
            }} else {{
                selF.setAttribute('required', 'required');
                selV.removeAttribute('required');
                selV.value = '';
            }}
        }}
        document.addEventListener('DOMContentLoaded', function() {{
            stpAtivarBuscaSelect(document.getElementById('busca_motorista_prog'), document.getElementById('motorista_id'));
            stpAtivarBuscaSelect(document.getElementById('busca_frota_prog'), document.getElementById('frota_id'));
            stpAtivarBuscaSelect(document.getElementById('busca_veiculo_prog'), document.getElementById('veiculo_id'));
        }});
        </script>
        '''
        return gerar_layout_base("Programar Viagem", conteudo, "agendamentos")

  # ===== RELATÓRIOS =====
    @app.route('/relatorios')
    @login_required
    def relatorios():
        # Obter parâmetros de filtro
        filtro_tipo = request.args.get('tipo', 'pacientes')
        data_inicio_raw = request.args.get('data_inicio', '').strip()
        data_fim_raw = request.args.get('data_fim', '').strip()
        status_filtro = request.args.get('status', '')
        
        d_ini = parse_data_br(data_inicio_raw) or (date.today() - timedelta(days=30))
        d_fim = parse_data_br(data_fim_raw) or date.today()
        data_inicio = format_data_br(d_ini)
        data_fim = format_data_br(d_fim)
        
        # Buscar dados
        pacientes_dados = []
        veiculos_dados = []
        motoristas_dados = []
        agendamentos_dados = []
        usuarios_dados = []
        
        try:
            # Relatório de Pacientes
            pacientes = Paciente.query.filter_by(ativo=True).order_by(Paciente.nome).all()
            for p in pacientes:
                total_agendamentos = Agendamento.query.filter_by(paciente_id=p.id).count()
                tel_cel, tel_res = telefones_paciente_exibir(p)
                pacientes_dados.append({
                    'nome': p.nome,
                    'cpf': p.cpf,
                    'tel_cel': tel_cel,
                    'tel_res': tel_res,
                    'condicao': formatar_condicao_paciente_exibir(p),
                    'endereco': p.endereco,
                    'ponto_embarque': ponto_embarque_do_paciente(p) or '-',
                    'cartao_sus': p.cartao_sus or '-',
                    'total_agendamentos': total_agendamentos,
                    'data_cadastro': p.data_cadastro.strftime('%d/%m/%Y'),
                    'observacoes': p.observacoes or '-'
                })
            
            # Relatório de Veículos
            veiculos = Veiculo.query.filter_by(ativo=True).order_by(Veiculo.placa).all()
            for v in veiculos:
                total_agendamentos = Agendamento.query.filter_by(veiculo_id=v.id).count()
                veiculos_dados.append({
                    'placa': v.placa,
                    'marca_modelo': f"{v.marca} {v.modelo}",
                    'ano': v.ano,
                    'tipo': v.tipo.replace('_', ' ').title(),
                    'capacidade': v.capacidade or '-',
                    'adaptado': 'Sim' if v.adaptado else 'Não',
                    'total_agendamentos': total_agendamentos,
                    'status': 'Ativo'
                })
            
            # Relatório de Motoristas
            motoristas = Motorista.query.order_by(Motorista.nome).all()
            for m in motoristas:
                total_agendamentos = Agendamento.query.filter_by(motorista_id=m.id).count()
                # Verificar se CNH está vencida
                cnh_status = 'Válida'
                if m.vencimento_cnh < date.today():
                    cnh_status = 'Vencida'
                elif m.vencimento_cnh <= date.today() + timedelta(days=30):
                    cnh_status = 'Vence em breve'
                
                motoristas_dados.append({
                    'nome': m.nome,
                    'cpf': m.cpf,
                    'telefone': m.telefone,
                    'cnh': m.cnh,
                    'categoria_cnh': m.categoria_cnh,
                    'vencimento_cnh': m.vencimento_cnh.strftime('%d/%m/%Y'),
                    'cnh_status': cnh_status,
                    'status': m.status.title(),
                    'total_agendamentos': total_agendamentos
                })
            
            # Relatório de Agendamentos
            query = Agendamento.query
            if d_ini and d_fim:
                query = query.filter(Agendamento.data.between(d_ini, d_fim))
            if status_filtro:
                query = query.filter_by(status=status_filtro)
            
            agendamentos = query.order_by(Agendamento.data.desc(), Agendamento.hora.desc()).all()
            for a in agendamentos:
                motorista_nome = a.motorista.nome if a.motorista else 'Não atribuído'
                veiculo_info = f"{a.veiculo.marca} {a.veiculo.modelo} - {a.veiculo.placa}" if a.veiculo else 'Não atribuído'
                
                agendamentos_dados.append({
                    'data': a.data.strftime('%d/%m/%Y'),
                    'hora': a.hora.strftime('%H:%M'),
                    'paciente': a.paciente.nome,
                    'telefone': a.paciente.telefone,
                    'tipo_transporte': formatar_especialidade_exibir(a.tipo_transporte),
                    'origem': a.origem,
                    'destino': a.destino,
                    'motorista': motorista_nome,
                    'veiculo': veiculo_info,
                    'status': a.status.replace('_', ' ').title(),
                    'observacoes': a.observacoes or '-'
                })
            
            # Relatório de Usuários
            usuarios = Usuario.query.order_by(Usuario.nome_completo).all()
            for u in usuarios:
                usuarios_dados.append({
                    'nome': u.nome_completo,
                    'username': u.username,
                    'email': u.email or '-',
                    'tipo': u.tipo_usuario.title(),
                    'status': 'Ativo' if u.ativo else 'Inativo'
                })
            
        except Exception as e:
            print(f"❌ Erro ao gerar relatórios: {e}")
            flash('Erro ao carregar dados dos relatórios.', 'error')

        cards_rel_pac = ""
        for p in pacientes_dados:
            cards_rel_pac += html_mobile_card(
                title=p["nome"],
                meta=html_esc(p["cpf"]),
                rows=[
                    ('Tel Cel', html_esc(p["tel_cel"])),
                    ('Tel Res', html_esc(p["tel_res"])),
                    ('Condição', html_esc(p["condicao"])),
                    ('Endereço', html_esc(p["endereco"])),
                    ('Ponto de Embarque', html_esc(p["ponto_embarque"])),
                    ('Cartão SUS', html_esc(p["cartao_sus"])),
                    ('Agendamentos', str(p["total_agendamentos"])),
                    ('Cadastro', html_esc(p["data_cadastro"])),
                ],
            )
        cards_rel_ag = ""
        for a in agendamentos_dados:
            cards_rel_ag += html_mobile_card(
                title=a["paciente"],
                meta=f'{html_esc(a["data"])} {html_esc(a["hora"])}',
                status_html=html_esc(a["status"]),
                rows=[
                    ('Telefone', html_esc(a["telefone"])),
                    ('Especialidade', html_esc(a["tipo_transporte"])),
                    ('Origem', html_esc(a["origem"])),
                    ('Destino', html_esc(a["destino"])),
                    ('Motorista', html_esc(a["motorista"])),
                    ('Veículo', html_esc(a["veiculo"])),
                ],
            )
        cards_rel_mot = ""
        for m in motoristas_dados:
            cards_rel_mot += html_mobile_card(
                title=m["nome"],
                meta=html_esc(m["cpf"]),
                status_html=html_esc(m["status"]),
                rows=[
                    ('Telefone', html_esc(m["telefone"])),
                    ('CNH', html_esc(m["cnh"])),
                    ('Categoria', html_esc(m["categoria_cnh"])),
                    ('Venc. CNH', html_esc(m["vencimento_cnh"])),
                    ('Status CNH', html_esc(m["cnh_status"])),
                    ('Viagens', str(m["total_agendamentos"])),
                ],
            )
        cards_rel_vei = ""
        for v in veiculos_dados:
            cards_rel_vei += html_mobile_card(
                title=v["placa"],
                meta=html_esc(v["marca_modelo"]),
                status_html=html_esc(v["status"]),
                rows=[
                    ('Ano', html_esc(str(v["ano"]))),
                    ('Especialidade', html_esc(v["tipo"])),
                    ('Capacidade', html_esc(str(v["capacidade"]))),
                    ('Adaptado PCD', html_esc(v["adaptado"])),
                    ('Transportes', str(v["total_agendamentos"])),
                ],
            )
        cards_rel_usu = ""
        for u in usuarios_dados:
            cards_rel_usu += html_mobile_card(
                title=u["nome"],
                meta=f'@{html_esc(u["username"])}',
                status_html=html_esc(u["status"]),
                rows=[
                    ('E-mail', html_esc(u["email"])),
                    ('Tipo', html_esc(u["tipo"])),
                ],
            )

        conteudo = f'''
        <div class="page-header">
            <h2>📊 Relatórios Gerenciais</h2>
            <p>Visualize e imprima relatórios completos do sistema</p>
        </div>
        
        <!-- Filtros -->
        <div class="filters no-print">
            <form method="GET" id="filtrosForm">
                <div class="filters-row">
                    <div class="form-group">
                        <label>Período de:</label>
                        <input type="text" class="data-br" name="data_inicio" value="{data_inicio}" placeholder="dd/mm/aaaa" maxlength="10">
                    </div>
                    <div class="form-group">
                        <label>Período até:</label>
                        <input type="text" class="data-br" name="data_fim" value="{data_fim}" placeholder="dd/mm/aaaa" maxlength="10">
                    </div>
                    <div class="form-group">
                        <label>Status Agendamentos:</label>
                        <select name="status">
                            <option value="">Todos</option>
                            <option value="agendado" {"selected" if status_filtro == "agendado" else ""}>Agendado</option>
                            <option value="confirmado" {"selected" if status_filtro == "confirmado" else ""}>Confirmado</option>
                            <option value="em_andamento" {"selected" if status_filtro == "em_andamento" else ""}>Em Andamento</option>
                            <option value="concluido" {"selected" if status_filtro == "concluido" else ""}>Concluído</option>
                            <option value="cancelado" {"selected" if status_filtro == "cancelado" else ""}>Cancelado</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <button type="submit" class="btn">🔍 Filtrar</button>
                        <button type="button" class="btn print-btn" onclick="window.print()">🖨️ Imprimir</button>
                    </div>
                </div>
            </form>
        </div>
        
        <!-- Abas dos Relatórios -->
        <div class="tabs no-print">
            <button class="tab active" onclick="showTab('pacientes')">👥 Pacientes ({len(pacientes_dados)})</button>
            <button class="tab" onclick="showTab('agendamentos')">📅 Agendamentos ({len(agendamentos_dados)})</button>
            <button class="tab" onclick="showTab('motoristas')">👨‍💼 Motoristas ({len(motoristas_dados)})</button>
            <button class="tab" onclick="showTab('veiculos')">🚗 Veículos ({len(veiculos_dados)})</button>
            <button class="tab" onclick="showTab('usuarios')">👤 Usuários ({len(usuarios_dados)})</button>
        </div>
        
        <!-- Conteúdo dos Relatórios -->
        
        <!-- Relatório de Pacientes -->
        <div id="pacientes" class="tab-content active">
            <div class="card">
                <h3 style="color: var(--primary-color); margin-bottom: 1rem;">📋 Relatório de Pacientes</h3>
                <p><strong>Total de pacientes ativos:</strong> {len(pacientes_dados)}</p>
                <div class="stp-list-desktop table-container">
                    <table class="report-table">
                        <thead>
                            <tr>
                                <th>Nome</th>
                                <th>CPF</th>
                                <th>Tel Cel</th>
                                <th>Tel Resi</th>
                                <th>Condição</th>
                                <th>Endereço</th>
                                <th>Ponto de Embarque</th>
                                <th>Cartão SUS</th>
                                <th>Total Agendamentos</th>
                                <th>Data Cadastro</th>
                                <th>Observações</th>
                            </tr>
                        </thead>
                        <tbody>
                            {"".join([f'''
                            <tr>
                                <td>{p["nome"]}</td>
                                <td>{p["cpf"]}</td>
                                <td>{p["tel_cel"]}</td>
                                <td>{p["tel_res"]}</td>
                                <td>{p["condicao"]}</td>
                                <td>{p["endereco"][:40]}{'...' if len(p["endereco"]) > 40 else ''}</td>
                                <td>{p["ponto_embarque"]}</td>
                                <td>{p["cartao_sus"]}</td>
                                <td>{p["total_agendamentos"]}</td>
                                <td>{p["data_cadastro"]}</td>
                                <td>{p["observacoes"][:30]}{'...' if len(p["observacoes"]) > 30 else ''}</td>
                            </tr>
                            ''' for p in pacientes_dados])}
                        </tbody>
                    </table>
                </div>
                <div class="stp-list-mobile">{cards_rel_pac if cards_rel_pac else '<p style="color:var(--gray-color);">Nenhum paciente</p>'}</div>
            </div>
        </div>
        
        <!-- Relatório de Agendamentos -->
        <div id="agendamentos" class="tab-content">
            <div class="card">
                <h3 style="color: var(--primary-color); margin-bottom: 1rem;">📅 Relatório de Agendamentos</h3>
                <p><strong>Período:</strong> {data_inicio} a {data_fim}</p>
                <p><strong>Total de agendamentos:</strong> {len(agendamentos_dados)}</p>
                <div class="stp-list-desktop table-container">
                    <table class="report-table">
                        <thead>
                            <tr>
                                <th>Data</th>
                                <th>Hora</th>
                                <th>Paciente</th>
                                <th>Telefone</th>
                                <th>Especialidade</th>
                                <th>Origem</th>
                                <th>Destino</th>
                                <th>Motorista</th>
                                <th>Veículo</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            {"".join([f'''
                            <tr>
                                <td>{a["data"]}</td>
                                <td>{a["hora"]}</td>
                                <td>{a["paciente"]}</td>
                                <td>{a["telefone"]}</td>
                                <td>{a["tipo_transporte"]}</td>
                                <td>{a["origem"][:25]}{'...' if len(a["origem"]) > 25 else ''}</td>
                                <td>{a["destino"][:25]}{'...' if len(a["destino"]) > 25 else ''}</td>
                                <td>{a["motorista"]}</td>
                                <td>{a["veiculo"][:20]}{'...' if len(a["veiculo"]) > 20 else ''}</td>
                                <td style="color: {'var(--success-color)' if a['status'] == 'Concluído' else 'var(--warning-color)' if a['status'] == 'Agendado' else 'var(--primary-color)'};">{a["status"]}</td>
                            </tr>
                            ''' for a in agendamentos_dados])}
                        </tbody>
                    </table>
                </div>
                <div class="stp-list-mobile">{cards_rel_ag if cards_rel_ag else '<p style="color:var(--gray-color);">Nenhum agendamento</p>'}</div>
            </div>
        </div>
        
        <!-- Relatório de Motoristas -->
        <div id="motoristas" class="tab-content">
            <div class="card">
                <h3 style="color: var(--primary-color); margin-bottom: 1rem;">👨‍💼 Relatório de Motoristas</h3>
                <p><strong>Total de motoristas:</strong> {len(motoristas_dados)}</p>
                <div class="stp-list-desktop table-container">
                    <table class="report-table">
                        <thead>
                            <tr>
                                <th>Nome</th>
                                <th>CPF</th>
                                <th>Telefone</th>
                                <th>CNH</th>
                                <th>Categoria</th>
                                <th>Vencimento CNH</th>
                                <th>Status CNH</th>
                                <th>Status</th>
                                <th>Total Viagens</th>
                            </tr>
                        </thead>
                        <tbody>
                            {"".join([f'''
                            <tr>
                                <td>{m["nome"]}</td>
                                <td>{m["cpf"]}</td>
                                <td>{m["telefone"]}</td>
                                <td>{m["cnh"]}</td>
                                <td>{m["categoria_cnh"]}</td>
                                <td>{m["vencimento_cnh"]}</td>
                                <td style="color: {'var(--danger-color)' if m['cnh_status'] == 'Vencida' else 'var(--warning-color)' if m['cnh_status'] == 'Vence em breve' else 'var(--success-color)'};">{m["cnh_status"]}</td>
                                <td style="color: {'var(--success-color)' if m['status'] == 'Ativo' else 'var(--gray-color)'};">{m["status"]}</td>
                                <td>{m["total_agendamentos"]}</td>
                            </tr>
                            ''' for m in motoristas_dados])}
                        </tbody>
                    </table>
                </div>
                <div class="stp-list-mobile">{cards_rel_mot if cards_rel_mot else '<p style="color:var(--gray-color);">Nenhum motorista</p>'}</div>
            </div>
        </div>
        
        <!-- Relatório de Veículos -->
        <div id="veiculos" class="tab-content">
            <div class="card">
                <h3 style="color: var(--primary-color); margin-bottom: 1rem;">🚗 Relatório de Veículos</h3>
                <p><strong>Total de veículos ativos:</strong> {len(veiculos_dados)}</p>
                <div class="stp-list-desktop table-container">
                    <table class="report-table">
                        <thead>
                            <tr>
                                <th>Placa</th>
                                <th>Marca/Modelo</th>
                                <th>Ano</th>
                                <th>Especialidade</th>
                                <th>Capacidade</th>
                                <th>Adaptado PCD</th>
                                <th>Total Transportes</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            {"".join([f'''
                            <tr>
                                <td><strong>{v["placa"]}</strong></td>
                                <td>{v["marca_modelo"]}</td>
                                <td>{v["ano"]}</td>
                                <td>{v["tipo"]}</td>
                                <td>{v["capacidade"]}</td>
                                <td style="color: {'var(--success-color)' if v['adaptado'] == 'Sim' else 'var(--gray-color)'};">{v["adaptado"]}</td>
                                <td>{v["total_agendamentos"]}</td>
                                <td style="color: var(--success-color);">{v["status"]}</td>
                            </tr>
                            ''' for v in veiculos_dados])}
                        </tbody>
                    </table>
                </div>
                <div class="stp-list-mobile">{cards_rel_vei if cards_rel_vei else '<p style="color:var(--gray-color);">Nenhum veículo</p>'}</div>
            </div>
        </div>
        
        <!-- Relatório de Usuários -->
        <div id="usuarios" class="tab-content">
            <div class="card">
                <h3 style="color: var(--primary-color); margin-bottom: 1rem;">👤 Relatório de Usuários</h3>
                <p><strong>Total de usuários:</strong> {len(usuarios_dados)}</p>
                <div class="stp-list-desktop table-container">
                    <table class="report-table">
                        <thead>
                            <tr>
                                <th>Nome Completo</th>
                                <th>Username</th>
                                <th>Email</th>
                                <th>Tipo de Usuário</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            {"".join([f'''
                            <tr>
                                <td>{u["nome"]}</td>
                                <td><strong>{u["username"]}</strong></td>
                                <td>{u["email"]}</td>
                                <td>{u["tipo"]}</td>
                                <td style="color: {'var(--success-color)' if u['status'] == 'Ativo' else 'var(--danger-color)'};">{u["status"]}</td>
                            </tr>
                            ''' for u in usuarios_dados])}
                        </tbody>
                    </table>
                </div>
                <div class="stp-list-mobile">{cards_rel_usu if cards_rel_usu else '<p style="color:var(--gray-color);">Nenhum usuário</p>'}</div>
            </div>
        </div>
        
        <script>
            function showTab(tabName) {{
                // Esconder todas as abas
                const contents = document.querySelectorAll('.tab-content');
                contents.forEach(content => content.classList.remove('active'));
                
                const tabs = document.querySelectorAll('.tab');
                tabs.forEach(tab => tab.classList.remove('active'));
                
                // Mostrar aba selecionada
                document.getElementById(tabName).classList.add('active');
                event.target.classList.add('active');
            }}
            
            // Auto-submit do formulário quando alterar filtros
            const form = document.getElementById('filtrosForm');
            const inputs = form.querySelectorAll('input, select');
            inputs.forEach(input => {{
                if (input.type !== 'submit' && !input.classList.contains('btn')) {{
                    input.addEventListener('change', function() {{
                        // Auto-submit após pequeno delay
                        setTimeout(() => form.submit(), 100);
                    }});
                }}
            }});
        </script>
        '''
        
        return gerar_layout_base("Relatórios", conteudo, "relatorios")
    
    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        session.pop('_flashes', None)
        flash('Logout realizado com sucesso!', 'success')
        return redirect(url_for('login'))
    
    # ===== GERENCIAMENTO DE USUÁRIOS =====
    def _admin_required_usuarios():
        if current_user.tipo_usuario != 'administrador':
            flash('Acesso negado! Apenas administradores podem gerenciar usuários.', 'error')
            return False
        return True

    def _opcoes_tipo_usuario_html(selecionado=''):
        opcoes = [
            ('atendente', '🎧 Atendente - Operações básicas'),
            ('supervisor', '👨‍💼 Supervisor - Pode editar dados'),
            ('contador', '💰 Contador - Controle financeiro'),
            ('administrador', '👑 Administrador - Acesso total'),
        ]
        html = ['<option value="">Selecione...</option>']
        for valor, rotulo in opcoes:
            sel = ' selected' if valor == selecionado else ''
            html.append(f'<option value="{valor}"{sel}>{rotulo}</option>')
        return ''.join(html)

    @app.route('/usuarios')
    @login_required
    def usuarios():
        if not _admin_required_usuarios():
            return redirect(url_for('dashboard'))

        filtros = obter_filtros_usuarios_request()
        page, per_page = obter_paginacao_request()
        query = montar_query_usuarios(filtros)
        usuarios_lista, total, page = listar_paginado(
            query, page, per_page, Usuario.data_cadastro.desc()
        )
        exibidos = len(usuarios_lista)
        filtros_url = {k: v for k, v in filtros.items() if v}
        filtros_html = gerar_filtros_usuarios(filtros, total, exibidos, per_page)
        paginacao_html = gerar_paginacao('usuarios', page, per_page, total, filtros_url)

        messages_html = ""
        for category, message in get_flashed_messages(with_categories=True):
            messages_html += f'<div class="alert alert-{category}">{message}</div>'

        usuarios_html = ""
        if usuarios_lista:
            cards_mobile = ""
            usuarios_html = f'''
            <div class="card">
                <h3 style="color: var(--primary-color); margin-bottom: 1rem;">👥 Usuários do Sistema ({format_numero_br(total)})</h3>
                <div class="stp-list-desktop table-container">
                    <table style="width: 100%; border-collapse: collapse;">
                        <thead>
                            <tr style="background: var(--color-95);">
                                ''' + html_th_id() + '''
                                <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Nome</th>
                                <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Username</th>
                                <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Tipo</th>
                                <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Status</th>
                                <th style="padding: 0.75rem; text-align: center; border-bottom: 2px solid var(--primary-color);">Ações</th>
                            </tr>
                        </thead>
                        <tbody>
            '''
            for usuario in usuarios_lista:
                tipo_color = {
                    'administrador': 'color: var(--danger-color); font-weight: bold;',
                    'contador': 'color: var(--success-color); font-weight: bold;',
                    'supervisor': 'color: var(--warning-color); font-weight: bold;',
                    'atendente': 'color: var(--info-color);'
                }.get(usuario.tipo_usuario, '')
                status_txt = 'Ativo' if usuario.ativo else 'Inativo'
                status_style = 'color: var(--success-color);' if usuario.ativo else 'color: var(--danger-color);'
                tipo_txt = (usuario.tipo_usuario or '').title()
                acoes = html_acoes_toolbar(
                    html_acao_icone('ti-eye', 'Visualizar usuário', href=url_for('usuarios_visualizar', usuario_id=usuario.id), variant='ver'),
                    html_acao_icone('ti-edit', 'Editar usuário', href=url_for('usuarios_editar', usuario_id=usuario.id), variant='editar'),
                    html_acao_icone('ti-trash', 'Excluir usuário', href=url_for('usuarios_excluir', usuario_id=usuario.id), variant='excluir', confirm_msg=f'Excluir o usuário {usuario.username}? Esta ação não pode ser desfeita.'),
                )
                usuarios_html += f'''
                            <tr>
                                {html_td_id(usuario.id)}
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{html_esc(usuario.nome_completo)}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);"><strong>{html_esc(usuario.username)}</strong></td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color); {tipo_color}">{html_esc(tipo_txt)}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color); {status_style}">{status_txt}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color); text-align: center; white-space: nowrap;">{acoes}</td>
                            </tr>
                '''
                cards_mobile += html_mobile_card(
                    title=f'#{usuario.id} {usuario.nome_completo or usuario.username or "—"}',
                    meta=f'@{html_esc(usuario.username)}',
                    status_html=f'<span style="{status_style}">{status_txt}</span>',
                    rows=[
                        ('ID', f'<strong>{usuario.id}</strong>'),
                        ('Tipo', f'<span style="{tipo_color}">{html_esc(tipo_txt)}</span>'),
                    ],
                    acoes_html=acoes,
                )
            usuarios_html += f'''
                        </tbody>
                    </table>
                </div>
                <div class="stp-list-mobile">{cards_mobile}</div>
                {paginacao_html}
            </div>
            '''
        else:
            usuarios_html = f'''
            <div class="card">
                <p style="margin:0; color: var(--gray-color);">Nenhum usuário encontrado.</p>
                {paginacao_html}
            </div>
            '''

        conteudo = f'''
        <div class="page-header">
            <h2>👥 Gerenciamento de Usuários</h2>
            <p>Controle de acesso e permissões do sistema</p>
            <div style="margin-top: 1rem;">
                <a href="{url_for('usuarios_novo')}" class="btn">👤 Cadastrar Novo Usuário</a>
            </div>
        </div>

        {messages_html}
        {filtros_html}
        {usuarios_html}
        '''
        return gerar_layout_base("Usuários", conteudo, "usuarios")

    @app.route('/usuarios/novo', methods=['GET', 'POST'])
    @login_required  
    def usuarios_novo():
        if not _admin_required_usuarios():
            return redirect(url_for('dashboard'))
        
        if request.method == 'POST':
            try:
                username = request.form.get('username', '').strip()
                nome_completo = request.form.get('nome_completo', '').strip()
                email = request.form.get('email', '').strip()
                password = request.form.get('password', '').strip()
                tipo_usuario = request.form.get('tipo_usuario', '').strip()
                
                if not all([username, nome_completo, password, tipo_usuario]):
                    flash('Preencha todos os campos obrigatórios!', 'error')
                    return redirect(url_for('usuarios_novo'))
                
                if Usuario.query.filter_by(username=username).first():
                    flash('Nome de usuário já existe!', 'error')
                    return redirect(url_for('usuarios_novo'))
                
                usuario = Usuario(
                    username=username,
                    nome_completo=nome_completo,
                    email=email if email else None,
                    tipo_usuario=tipo_usuario
                )
                usuario.set_password(password)
                
                db.session.add(usuario)
                db.session.commit()
                
                flash(f'Usuário "{nome_completo}" cadastrado com sucesso!', 'success')
                return redirect(url_for('usuarios'))
                
            except Exception as e:
                db.session.rollback()
                flash(f'Erro: {str(e)}', 'error')
        
        messages_html = ""
        for category, message in get_flashed_messages(with_categories=True):
            alert_class = f"alert-{category}"
            messages_html += f'<div class="alert {alert_class}">{message}</div>'
        
        conteudo = f'''
        <div class="page-header">
            <h2>👤 Cadastrar Novo Usuário</h2>
        </div>
        
        {messages_html}
        
        <div class="card">
            <form method="POST">
                <div class="form-row">
                    <div class="form-group">
                        <label for="username">Nome de Usuário <span class="required-mark" aria-hidden="true">*</span></label>
                        <input type="text" id="username" name="username" required
                               placeholder="Ex: joao.silva" autocomplete="username">
                    </div>
                    <div class="form-group">
                        <label for="nome_completo">Nome Completo <span class="required-mark" aria-hidden="true">*</span></label>
                        <input type="text" id="nome_completo" name="nome_completo" required
                               placeholder="Digite o nome completo" autocomplete="name">
                    </div>
                </div>
                
                <div class="form-row">
                    <div class="form-group">
                        <label for="email">E-mail</label>
                        <input type="email" id="email" name="email"
                               placeholder="usuario@dominio.com" autocomplete="email">
                    </div>
                    <div class="form-group">
                        <label for="tipo_usuario">Tipo de Usuário <span class="required-mark" aria-hidden="true">*</span></label>
                        <select id="tipo_usuario" name="tipo_usuario" required>
                            {_opcoes_tipo_usuario_html()}
                        </select>
                    </div>
                </div>
                
                {html_campo_senha(
                    input_id='password',
                    name='password',
                    label='Senha',
                    required=True,
                    placeholder='Digite a senha de acesso',
                    autocomplete='new-password',
                )}
                
                <div class="form-actions">
                    <button type="submit" class="btn btn-success">👤 Criar Usuário</button>
                    <a href="{url_for('usuarios')}" class="btn btn-secondary">❌ Cancelar</a>
                </div>
            </form>
        </div>
        '''
        return gerar_layout_base("Novo Usuário", conteudo, "usuarios")

    @app.route('/usuarios/visualizar/<int:usuario_id>')
    @login_required
    def usuarios_visualizar(usuario_id):
        if not _admin_required_usuarios():
            return redirect(url_for('dashboard'))

        usuario = db.session.get(Usuario, usuario_id)
        if not usuario:
            flash('Usuário não encontrado!', 'error')
            return redirect(url_for('usuarios'))

        data_cad = usuario.data_cadastro.strftime('%d/%m/%Y %H:%M') if usuario.data_cadastro else '—'
        conteudo = f'''
        <div class="breadcrumb">
            <a href="{url_for('dashboard')}">Início</a> >
            <a href="{url_for('usuarios')}">Usuários</a> > Visualizar
        </div>
        <div class="page-header">
            <h2>👁️ Visualizar Usuário {html_id_badge(usuario.id)}</h2>
            <p>Consulta dos dados de acesso</p>
        </div>
        <div class="card">
            <div class="form-row">
                <div class="form-group">
                    <label>Nome completo</label>
                    <div style="padding:0.65rem 0; font-weight:600;">{usuario.nome_completo}</div>
                </div>
                <div class="form-group">
                    <label>Username</label>
                    <div style="padding:0.65rem 0;"><strong>{usuario.username}</strong></div>
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>E-mail</label>
                    <div style="padding:0.65rem 0;">{usuario.email or '—'}</div>
                </div>
                <div class="form-group">
                    <label>Tipo</label>
                    <div style="padding:0.65rem 0;">{usuario.tipo_usuario.title()}</div>
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>Status</label>
                    <div style="padding:0.65rem 0;">{'Ativo' if usuario.ativo else 'Inativo'}</div>
                </div>
                <div class="form-group">
                    <label>Data de cadastro</label>
                    <div style="padding:0.65rem 0;">{data_cad}</div>
                </div>
            </div>
            <div style="margin-top: 1.5rem;">
                <a href="{url_for('usuarios_editar', usuario_id=usuario.id)}" class="btn" style="background: var(--warning-color);">✏️ Editar</a>
                <a href="{url_for('usuarios')}" class="btn btn-secondary" style="margin-left: 0.75rem;">⬅ Voltar</a>
            </div>
        </div>
        '''
        return gerar_layout_base("Visualizar Usuário", conteudo, "usuarios")

    @app.route('/usuarios/editar/<int:usuario_id>', methods=['GET', 'POST'])
    @login_required
    def usuarios_editar(usuario_id):
        if not _admin_required_usuarios():
            return redirect(url_for('dashboard'))

        usuario = db.session.get(Usuario, usuario_id)
        if not usuario:
            flash('Usuário não encontrado!', 'error')
            return redirect(url_for('usuarios'))

        if request.method == 'POST':
            try:
                username = request.form.get('username', '').strip()
                nome_completo = request.form.get('nome_completo', '').strip()
                email = request.form.get('email', '').strip()
                password = request.form.get('password', '').strip()
                tipo_usuario = request.form.get('tipo_usuario', '').strip()
                ativo = bool(request.form.get('ativo'))

                if not all([username, nome_completo, tipo_usuario]):
                    flash('Preencha todos os campos obrigatórios!', 'error')
                    return redirect(url_for('usuarios_editar', usuario_id=usuario_id))

                outro = Usuario.query.filter_by(username=username).first()
                if outro and outro.id != usuario.id:
                    flash('Nome de usuário já existe!', 'error')
                    return redirect(url_for('usuarios_editar', usuario_id=usuario_id))

                # Não permitir remover o próprio acesso de administrador / desativar a si mesmo
                if usuario.id == current_user.id:
                    if tipo_usuario != 'administrador':
                        flash('Você não pode alterar o próprio tipo para algo diferente de administrador.', 'error')
                        return redirect(url_for('usuarios_editar', usuario_id=usuario_id))
                    if not ativo:
                        flash('Você não pode inativar a própria conta.', 'error')
                        return redirect(url_for('usuarios_editar', usuario_id=usuario_id))

                # Garantir pelo menos 1 administrador ativo
                if usuario.tipo_usuario == 'administrador' and (tipo_usuario != 'administrador' or not ativo):
                    admins_ativos = Usuario.query.filter_by(tipo_usuario='administrador', ativo=True).count()
                    if admins_ativos <= 1:
                        flash('Não é possível remover/inativar o único administrador ativo do sistema.', 'error')
                        return redirect(url_for('usuarios_editar', usuario_id=usuario_id))

                usuario.username = username
                usuario.nome_completo = nome_completo
                usuario.email = email if email else None
                usuario.tipo_usuario = tipo_usuario
                usuario.ativo = ativo
                if password:
                    usuario.set_password(password)

                db.session.commit()
                flash(f'Usuário "{nome_completo}" atualizado com sucesso!', 'success')
                return redirect(url_for('usuarios'))
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao atualizar usuário: {str(e)}', 'error')

        messages_html = ""
        for category, message in get_flashed_messages(with_categories=True):
            messages_html += f'<div class="alert alert-{category}">{message}</div>'

        ativo_checked = 'checked' if usuario.ativo else ''
        conteudo = f'''
        <div class="breadcrumb">
            <a href="{url_for('dashboard')}">Início</a> >
            <a href="{url_for('usuarios')}">Usuários</a> > Editar
        </div>
        <div class="page-header">
            <h2>✏️ Editar Usuário {html_id_badge(usuario.id)}</h2>
            <p>Atualize dados e permissões de <strong>{usuario.username}</strong></p>
        </div>
        {messages_html}
        <div class="card">
            <form method="POST">
                <div class="form-row">
                    <div class="form-group">
                        <label for="username">Nome de Usuário <span class="required-mark" aria-hidden="true">*</span></label>
                        <input type="text" id="username" name="username" value="{usuario.username}" required
                               placeholder="Ex: joao.silva" autocomplete="username">
                    </div>
                    <div class="form-group">
                        <label for="nome_completo">Nome Completo <span class="required-mark" aria-hidden="true">*</span></label>
                        <input type="text" id="nome_completo" name="nome_completo" value="{usuario.nome_completo}" required
                               placeholder="Digite o nome completo" autocomplete="name">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label for="email">E-mail</label>
                        <input type="email" id="email" name="email" value="{usuario.email or ''}"
                               placeholder="usuario@dominio.com" autocomplete="email">
                    </div>
                    <div class="form-group">
                        <label for="tipo_usuario">Tipo de Usuário <span class="required-mark" aria-hidden="true">*</span></label>
                        <select id="tipo_usuario" name="tipo_usuario" required>
                            {_opcoes_tipo_usuario_html(usuario.tipo_usuario)}
                        </select>
                    </div>
                </div>
                <div class="form-row">
                    {html_campo_senha(
                        input_id='password',
                        name='password',
                        label='Nova senha',
                        required=False,
                        placeholder='Deixe em branco para manter a atual',
                        autocomplete='new-password',
                        hint='Preencha somente se desejar alterar a senha.',
                    )}
                    <div class="form-group">
                        <label for="ativo">Status</label>
                        <div class="checkbox-row">
                            <input type="checkbox" id="ativo" name="ativo" value="1" {ativo_checked}>
                            <label for="ativo">Usuário ativo</label>
                        </div>
                    </div>
                </div>
                <div class="form-actions">
                    <button type="submit" class="btn btn-success">💾 Salvar</button>
                    <a href="{url_for('usuarios_visualizar', usuario_id=usuario.id)}" class="btn" style="background: var(--info-color);">👁️ Visualizar</a>
                    <a href="{url_for('usuarios')}" class="btn btn-secondary">❌ Cancelar</a>
                </div>
            </form>
        </div>
        '''
        return gerar_layout_base("Editar Usuário", conteudo, "usuarios")

    @app.route('/usuarios/excluir/<int:usuario_id>')
    @login_required
    def usuarios_excluir(usuario_id):
        if not _admin_required_usuarios():
            return redirect(url_for('dashboard'))

        usuario = db.session.get(Usuario, usuario_id)
        if not usuario:
            flash('Usuário não encontrado!', 'error')
            return redirect(url_for('usuarios'))

        if usuario.id == current_user.id:
            flash('Você não pode excluir a própria conta.', 'error')
            return redirect(url_for('usuarios'))

        if usuario.tipo_usuario == 'administrador' and usuario.ativo:
            admins_ativos = Usuario.query.filter_by(tipo_usuario='administrador', ativo=True).count()
            if admins_ativos <= 1:
                flash('Não é possível excluir o único administrador ativo do sistema.', 'error')
                return redirect(url_for('usuarios'))

        try:
            nome = usuario.nome_completo
            db.session.delete(usuario)
            db.session.commit()
            flash(f'Usuário "{nome}" excluído com sucesso!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao excluir usuário: {str(e)}', 'error')

        return redirect(url_for('usuarios'))
    
    
    # ===== MÓDULO DE FATURAMENTO =====
    @app.route('/faturamento')
    @login_required
    @finance_view_required
    def faturamento():
        # Buscar faturas existentes
        faturas = FaturaTerceirizado.query.order_by(
            FaturaTerceirizado.ano_referencia.desc(),
            FaturaTerceirizado.mes_referencia.desc()
        ).all()
        
        # Buscar veículos terceirizados
        veiculos_terceirizados = Veiculo.query.filter_by(
            tipo_propriedade='terceirizado',
            ativo=True
        ).all()
        
        # Preparar dados das faturas
        faturas_dados = []
        for fatura in faturas:
            faturas_dados.append({
                'id': fatura.id,
                'veiculo_placa': fatura.veiculo.placa,
                'proprietario': fatura.veiculo.proprietario_nome or 'Não informado',
                'periodo': fatura.periodo_referencia,
                'total_km': fatura.total_km,
                'valor_total': float(fatura.valor_total) if fatura.valor_total else 0,
                'status': fatura.status,
                'data_vencimento': fatura.data_vencimento.strftime('%d/%m/%Y') if fatura.data_vencimento else '-',
                'data_pagamento': fatura.data_pagamento.strftime('%d/%m/%Y') if fatura.data_pagamento else '-'
            })

        if faturas_dados:
            rows_html = ""
            cards_mobile = ""
            for fatura in faturas_dados:
                status_bg = (
                    'var(--success-color)' if fatura['status'] == 'pago'
                    else 'var(--warning-color)' if fatura['status'] == 'pendente'
                    else 'var(--danger-color)'
                )
                status_badge = (
                    f'<span style="padding: 0.25rem 0.5rem; border-radius: 0.25rem; font-size: 0.75rem; '
                    f'font-weight: bold; background: {status_bg}; color: white;">{html_esc(fatura["status"].upper())}</span>'
                )
                acoes = html_acoes_toolbar(
                    html_acao_icone('ti-eye', 'Ver detalhes da fatura', href=url_for('faturamento_detalhes', fatura_id=fatura['id']), variant='ver'),
                    html_acao_icone('ti-cash', 'Registrar pagamento', href=url_for('faturamento_pagar', fatura_id=fatura['id']), variant='pagar') if fatura['status'] == 'pendente' else '',
                )
                rows_html += f'''
                        <tr>
                            {html_td_id(fatura["id"])}
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);"><strong>{html_esc(fatura["veiculo_placa"])}</strong></td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{html_esc(fatura["proprietario"])}</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{html_esc(fatura["periodo"])}</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{fatura["total_km"]} km</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">R$ {fatura["valor_total"]:.2f}</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{status_badge}</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{html_esc(fatura["data_vencimento"])}</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color); text-align: center;">{acoes}</td>
                        </tr>'''
                cards_mobile += html_mobile_card(
                    title=f'#{fatura["id"]} {fatura["veiculo_placa"]}',
                    meta=html_esc(fatura["proprietario"]),
                    status_html=status_badge,
                    rows=[
                        ('ID', f'<strong>{fatura["id"]}</strong>'),
                        ('Período', html_esc(fatura["periodo"])),
                        ('Total KM', f'{fatura["total_km"]} km'),
                        ('Valor', f'R$ {fatura["valor_total"]:.2f}'),
                        ('Vencimento', html_esc(fatura["data_vencimento"])),
                    ],
                    acoes_html=acoes,
                )
            lista_faturas_html = f'''
            <div class="stp-list-desktop table-container">
                <table style="width: 100%; border-collapse: collapse;">
                    <thead>
                        <tr style="background: var(--color-95);">
                            {html_th_id()}
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Veículo</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Proprietário</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Período</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Total KM</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Valor Total</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Status</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Vencimento</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Ações</th>
                        </tr>
                    </thead>
                    <tbody>{rows_html}</tbody>
                </table>
            </div>
            <div class="stp-list-mobile">{cards_mobile}</div>'''
        else:
            lista_faturas_html = f'''
            <div style="text-align: center; padding: 3rem;">
                <div style="font-size: 4rem; margin-bottom: 1rem; color: var(--primary-color);">💰</div>
                <h3 style="color: var(--text-color); margin-bottom: 1rem;">Nenhuma fatura gerada</h3>
                <p style="color: var(--gray-color); margin-bottom: 2rem;">Comece gerando a primeira fatura de terceirizados!</p>
                <a href="{url_for('faturamento_gerar')}" class="btn btn-success">📋 Gerar Nova Fatura</a>
            </div>'''
        
        conteudo = f'''
        <div class="page-header">
            <h2>💰 Módulo de Faturamento</h2>
            <p>Gestão financeira de veículos terceirizados</p>
            <div style="margin-top: 1rem;">
                <a href="{url_for('faturamento_gerar')}" class="btn btn-success">📋 Gerar Nova Fatura</a>
            </div>
        </div>

        <!-- Estatísticas -->
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 1rem; margin-bottom: 2rem;">
            <div class="card" style="text-align: center; padding: 1.5rem;">
                <h3 style="color: var(--primary-color); margin: 0 0 0.5rem 0;">📋 Total de Faturas</h3>
                <div style="font-size: 2rem; font-weight: bold; color: var(--text-color);">{len(faturas_dados)}</div>
            </div>
            <div class="card" style="text-align: center; padding: 1.5rem;">
                <h3 style="color: var(--warning-color); margin: 0 0 0.5rem 0;">⏳ Faturas Pendentes</h3>
                <div style="font-size: 2rem; font-weight: bold; color: var(--warning-color);">{len([f for f in faturas_dados if f['status'] == 'pendente'])}</div>
            </div>
            <div class="card" style="text-align: center; padding: 1.5rem;">
                <h3 style="color: var(--success-color); margin: 0 0 0.5rem 0;">✅ Faturas Pagas</h3>
                <div style="font-size: 2rem; font-weight: bold; color: var(--success-color);">{len([f for f in faturas_dados if f['status'] == 'pago'])}</div>
            </div>
            <div class="card" style="text-align: center; padding: 1.5rem;">
                <h3 style="color: var(--info-color); margin: 0 0 0.5rem 0;">🚗 Veículos Terceirizados</h3>
                <div style="font-size: 2rem; font-weight: bold; color: var(--info-color);">{len(veiculos_terceirizados)}</div>
            </div>
        </div>
        
        <!-- Lista de Faturas -->
        <div class="card">
            <h3 style="color: var(--primary-color); margin-bottom: 1.5rem;">📋 Faturas de Terceirizados</h3>
            {lista_faturas_html}
        </div>
        '''
        
        return gerar_layout_base("Faturamento", conteudo, "faturamento")
    
    @app.route('/faturamento/gerar', methods=['GET', 'POST'])
    @login_required
    @contador_required
    def faturamento_gerar():
        if request.method == 'POST':
            try:
                veiculo_id = int(request.form.get('veiculo_id', 0))
                mes_referencia = int(request.form.get('mes_referencia', 0))
                ano_referencia = int(request.form.get('ano_referencia', 0))
                data_vencimento_str = request.form.get('data_vencimento')
                
                if not all([veiculo_id, mes_referencia, ano_referencia]):
                    flash('Preencha todos os campos obrigatórios!', 'error')
                    return redirect(url_for('faturamento_gerar'))
                
                # Verificar se já existe fatura para este período
                fatura_existente = FaturaTerceirizado.query.filter_by(
                    veiculo_id=veiculo_id,
                    mes_referencia=mes_referencia,
                    ano_referencia=ano_referencia
                ).first()
                
                if fatura_existente:
                    flash('Já existe uma fatura para este veículo neste período!', 'error')
                    return redirect(url_for('faturamento_gerar'))
                
                # Buscar usos do veículo no período
                from calendar import monthrange
                primeiro_dia = date(ano_referencia, mes_referencia, 1)
                ultimo_dia_num = monthrange(ano_referencia, mes_referencia)[1]
                ultimo_dia = date(ano_referencia, mes_referencia, ultimo_dia_num)
                
                usos = UsoVeiculo.query.filter(
                    UsoVeiculo.veiculo_id == veiculo_id,
                    UsoVeiculo.data_uso.between(primeiro_dia, ultimo_dia),
                    UsoVeiculo.status == 'concluido'
                ).all()
                
                # Calcular totais
                total_km = sum([uso.km_rodados or 0 for uso in usos])
                total_diarias = len(usos)
                valor_total = sum([float(uso.valor_total or 0) for uso in usos])
                
                # Converter data de vencimento
                data_vencimento = None
                if data_vencimento_str:
                    data_vencimento = datetime.strptime(data_vencimento_str, '%Y-%m-%d').date()
                
                # Criar nova fatura
                fatura = FaturaTerceirizado(
                    veiculo_id=veiculo_id,
                    mes_referencia=mes_referencia,
                    ano_referencia=ano_referencia,
                    total_km=total_km,
                    total_diarias=total_diarias,
                    valor_total=valor_total,
                    data_vencimento=data_vencimento,
                    usuario_gerou_id=current_user.id
                )
                
                db.session.add(fatura)
                db.session.commit()
                
                flash(f'Fatura gerada com sucesso! Total: R$ {valor_total:.2f}', 'success')
                return redirect(url_for('faturamento'))
                
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao gerar fatura: {str(e)}', 'error')
        
        # Buscar veículos terceirizados
        veiculos_terceirizados = Veiculo.query.filter_by(
            tipo_propriedade='terceirizado',
            ativo=True
        ).all()
        
        # Gerar options para veículos
        veiculos_options = ""
        for v in veiculos_terceirizados:
            veiculos_options += f'<option value="{v.id}">{v.placa} - {v.proprietario_nome or "Proprietário não informado"}</option>'
        
        # Gerar options para meses
        meses_options = ""
        meses = [
            (1, 'Janeiro'), (2, 'Fevereiro'), (3, 'Março'), (4, 'Abril'),
            (5, 'Maio'), (6, 'Junho'), (7, 'Julho'), (8, 'Agosto'),
            (9, 'Setembro'), (10, 'Outubro'), (11, 'Novembro'), (12, 'Dezembro')
        ]
        for num, nome in meses:
            meses_options += f'<option value="{num}">{nome}</option>'
        
        # Gerar options para anos
        ano_atual = datetime.now().year
        anos_options = ""
        for ano in range(ano_atual - 2, ano_atual + 2):
            selected = "selected" if ano == ano_atual else ""
            anos_options += f'<option value="{ano}" {selected}>{ano}</option>'
        
        # Gerar alertas de mensagens flash
        messages_html = ""
        for category, message in get_flashed_messages(with_categories=True):
            alert_class = f"alert-{category}"
            messages_html += f'<div class="alert {alert_class}">{message}</div>'
        
        conteudo = f'''
        <div class="breadcrumb">
            <a href="{url_for('dashboard')}">Início</a> > 
            <a href="{url_for('faturamento')}">Faturamento</a> > 
            Gerar Nova Fatura
        </div>
        
        <div class="page-header">
            <h2>📋 Gerar Nova Fatura</h2>
            <p>Gere uma fatura para um veículo terceirizado baseada nos usos do período</p>
        </div>
        
        {messages_html}
        
        <div class="card">
            <form method="POST">
                <div class="form-row">
                    <div class="form-group">
                        <label for="veiculo_id">Veículo Terceirizado *</label>
                        <select id="veiculo_id" name="veiculo_id" required>
                            <option value="">Selecione o veículo...</option>
                            {veiculos_options}
                        </select>
                    </div>
                    <div class="form-group">
                        <label for="mes_referencia">Mês de Referência *</label>
                        <select id="mes_referencia" name="mes_referencia" required>
                            <option value="">Selecione o mês...</option>
                            {meses_options}
                        </select>
                    </div>
                </div>
                
                <div class="form-row">
                    <div class="form-group">
                        <label for="ano_referencia">Ano de Referência *</label>
                        <select id="ano_referencia" name="ano_referencia" required>
                            {anos_options}
                        </select>
                    </div>
                    <div class="form-group">
                        <label for="data_vencimento">Data de Vencimento</label>
                        <input type="date" id="data_vencimento" name="data_vencimento">
                    </div>
                </div>
                
                <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem; margin: 1rem 0;">
                    <h4 style="color: var(--primary-color); margin-bottom: 0.5rem;">ℹ️ Como funciona:</h4>
                    <p style="margin: 0;">O sistema irá buscar todos os usos registrados do veículo no período selecionado e calcular automaticamente:</p>
                    <ul style="margin: 0.5rem 0 0 1rem;">
                        <li>Total de quilômetros rodados</li>
                        <li>Número de diárias utilizadas</li>
                        <li>Valor total com base nos preços cadastrados</li>
                    </ul>
                </div>
                
                <div style="margin-top: 2rem;">
                    <button type="submit" class="btn btn-success">📋 Gerar Fatura</button>
                    <a href="{url_for('faturamento')}" class="btn btn-secondary" style="margin-left: 1rem;">❌ Cancelar</a>
                </div>
            </form>
        </div>
        '''
        return gerar_layout_base("Gerar Fatura", conteudo, "faturamento")
    
    @app.route('/faturamento/pagar/<int:fatura_id>')
    @login_required
    @contador_required
    def faturamento_pagar(fatura_id):
        try:
            fatura = db.session.get(FaturaTerceirizado, fatura_id)
            if not fatura:
                return jsonify({'erro': 'Fatura não encontrada'}), 404
            
            if fatura.status == 'pago':
                flash('Esta fatura já foi marcada como paga!', 'warning')
                return redirect(url_for('faturamento'))
            
            # Marcar como paga
            fatura.status = 'pago'
            fatura.data_pagamento = date.today()
            
            db.session.commit()
            
            flash(f'Fatura de {fatura.veiculo.placa} ({fatura.periodo_referencia}) marcada como paga!', 'success')
            
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao marcar fatura como paga: {str(e)}', 'error')
        
        return redirect(url_for('faturamento'))
    
    @app.route('/faturamento/detalhes/<int:fatura_id>')
    @login_required
    @finance_view_required
    def faturamento_detalhes(fatura_id):
        fatura = db.session.get(FaturaTerceirizado, fatura_id)
        if not fatura:
            flash('Fatura não encontrada!', 'error')
            return redirect(url_for('faturamento'))
        
        # Buscar usos relacionados à fatura
        usos = fatura.gerar_usos_periodo()
        
        usos_dados = []
        for uso in usos:
            usos_dados.append({
                'data': uso.data_uso.strftime('%d/%m/%Y'),
                'hora_saida': uso.hora_saida.strftime('%H:%M'),
                'hora_retorno': uso.hora_retorno.strftime('%H:%M') if uso.hora_retorno else '-',
                'origem': uso.endereco_origem,
                'destino': uso.endereco_destino,
                'km_rodados': uso.km_rodados or 0,
                'valor_total': float(uso.valor_total or 0),
                'motorista': uso.motorista.nome if uso.motorista else 'Não informado'
            })

        if usos_dados:
            rows_u = ""
            cards_u = ""
            for uso in usos_dados:
                origem = uso["origem"] or ""
                destino = uso["destino"] or ""
                origem_curta = origem[:30] + ('...' if len(origem) > 30 else '')
                destino_curta = destino[:30] + ('...' if len(destino) > 30 else '')
                rows_u += f'''
                        <tr>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{html_esc(uso["data"])}</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{html_esc(uso["hora_saida"])}</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{html_esc(uso["hora_retorno"])}</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{html_esc(origem_curta)}</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{html_esc(destino_curta)}</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{uso["km_rodados"]} km</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">R$ {uso["valor_total"]:.2f}</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{html_esc(uso["motorista"])}</td>
                        </tr>'''
                cards_u += html_mobile_card(
                    title=uso["data"],
                    meta=f'{html_esc(uso["hora_saida"])} → {html_esc(uso["hora_retorno"])}',
                    rows=[
                        ('Motorista', html_esc(uso["motorista"])),
                        ('Origem', html_esc(origem)),
                        ('Destino', html_esc(destino)),
                        ('KM', f'{uso["km_rodados"]} km'),
                        ('Valor', f'R$ {uso["valor_total"]:.2f}'),
                    ],
                )
            lista_usos_fatura_html = f'''
            <div class="stp-list-desktop table-container">
                <table style="width: 100%; border-collapse: collapse;">
                    <thead>
                        <tr style="background: var(--color-95);">
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Data</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Saída</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Retorno</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Origem</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Destino</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">KM</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Valor</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Motorista</th>
                        </tr>
                    </thead>
                    <tbody>{rows_u}</tbody>
                </table>
            </div>
            <div class="stp-list-mobile">{cards_u}</div>'''
        else:
            lista_usos_fatura_html = '''
            <div style="text-align: center; padding: 2rem;">
                <p style="color: var(--gray-color);">Nenhum uso registrado para este período.</p>
            </div>'''
        
        conteudo = f'''
        <div class="breadcrumb">
            <a href="{url_for('dashboard')}">Início</a> > 
            <a href="{url_for('faturamento')}">Faturamento</a> > 
            Detalhes da Fatura
        </div>
        
        <div class="page-header">
            <h2>📋 Detalhes da Fatura {html_id_badge(fatura.id)}</h2>
            <p>Fatura do veículo {fatura.veiculo.placa} - {fatura.periodo_referencia}</p>
        </div>
        
        <!-- Informações da Fatura -->
        <div class="card">
            <h3 style="color: var(--primary-color); margin-bottom: 1rem;">📄 Informações da Fatura</h3>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 1rem;">
                <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem;">
                    <strong>🚗 Veículo:</strong><br /><br />
                    {fatura.veiculo.placa} - {fatura.veiculo.marca} {fatura.veiculo.modelo}
                </div>
                <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem;">
                    <strong>👤 Proprietário:</strong><br /><br />
                    {fatura.veiculo.proprietario_nome or 'Não informado'}
                </div>
                <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem;">
                    <strong>📅 Período:</strong><br /><br />
                    {fatura.periodo_referencia}
                </div>
                <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem;">
                    <strong>💰 Valor Total:</strong><br /><br />
                    <span style="font-size: 1.2rem; color: var(--success-color); font-weight: bold;">R$ {float(fatura.valor_total):.2f}</span>
                </div>
                <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem;">
                    <strong>📏 Total KM:</strong><br /><br />
                    {fatura.total_km} km
                </div>
                <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem;">
                    <strong>📊 Status:</strong><br /><br />
                    <span style="padding: 0.25rem 0.5rem; border-radius: 0.25rem; 
                          background: {'var(--success-color)' if fatura.status == 'pago' else 'var(--warning-color)'}; 
                          color: white; font-weight: bold;">
                        {fatura.status.upper()}
                    </span>
                </div>
            </div>
        </div>
        
        <!-- Usos Detalhados -->
        <div class="card">
            <h3 style="color: var(--primary-color); margin-bottom: 1rem;">🚛 Usos do Veículo no Período</h3>
            {lista_usos_fatura_html}
        </div>
        
        <div style="margin-top: 2rem;">
            <a href="{url_for('faturamento')}" class="btn btn-secondary">← Voltar para Faturamento</a>
            {f'<a href="{url_for("faturamento_pagar", fatura_id=fatura.id)}" class="btn btn-success" style="margin-left: 1rem;">💰 Marcar como Paga</a>' if fatura.status == 'pendente' else ''}
        </div>
        '''
        
        return gerar_layout_base("Detalhes da Fatura", conteudo, "faturamento")
    
    # ===== SISTEMA DE CONTROLE DE USO DE VEÍCULOS =====
    @app.route('/uso-veiculos')
    @login_required
    def uso_veiculos():
        # Buscar usos em andamento e recentes
        usos_em_andamento = UsoVeiculo.query.filter_by(status='em_andamento').order_by(UsoVeiculo.data_uso.desc()).all()
        
        # Buscar usos concluídos dos últimos 30 dias
        data_limite = date.today() - timedelta(days=30)
        usos_concluidos = UsoVeiculo.query.filter(
            UsoVeiculo.status.in_(['concluido', 'cancelado']),
            UsoVeiculo.data_uso >= data_limite
        ).order_by(UsoVeiculo.data_uso.desc()).limit(50).all()
        
        # Preparar dados dos usos em andamento
        usos_andamento_dados = []
        for uso in usos_em_andamento:
            usos_andamento_dados.append({
                'id': uso.id,
                'veiculo_placa': uso.veiculo.placa,
                'motorista_nome': uso.motorista.nome,
                'data_saida': uso.data_uso.strftime('%d/%m/%Y'),
                'hora_saida': uso.hora_saida.strftime('%H:%M'),
                'origem': uso.endereco_origem,
                'destino': uso.endereco_destino,
                'km_inicial': uso.km_inicial or 0,
                'agendamento_paciente': uso.agendamento.paciente.nome if uso.agendamento else 'Sem agendamento'
            })
        
        # Preparar dados dos usos concluídos
        usos_concluidos_dados = []
        for uso in usos_concluidos:
            duracao = uso.duracao_horas if uso.hora_retorno else 0
            usos_concluidos_dados.append({
                'id': uso.id,
                'veiculo_placa': uso.veiculo.placa,
                'motorista_nome': uso.motorista.nome,
                'data_uso': uso.data_uso.strftime('%d/%m/%Y'),
                'hora_saida': uso.hora_saida.strftime('%H:%M'),
                'hora_retorno': uso.hora_retorno.strftime('%H:%M') if uso.hora_retorno else '-',
                'km_rodados': uso.km_rodados or 0,
                'duracao': f"{duracao:.1f}h" if duracao > 0 else '-',
                'valor_total': float(uso.valor_total or 0),
                'status': uso.status,
                'agendamento_paciente': uso.agendamento.paciente.nome if uso.agendamento else 'Sem agendamento'
            })

        if usos_andamento_dados:
            rows_and = ""
            cards_and = ""
            for uso in usos_andamento_dados:
                origem = uso["origem"] or ""
                destino = uso["destino"] or ""
                rota_curta = f'{origem[:25]}{"..." if len(origem) > 25 else ""} → {destino[:25]}{"..." if len(destino) > 25 else ""}'
                acoes = html_acoes_toolbar(
                    html_acao_icone('ti-flag', 'Finalizar uso do veículo', href=url_for('uso_veiculos_finalizar', uso_id=uso['id']), variant='concluir'),
                    html_acao_icone('ti-eye', 'Ver detalhes do uso', href=url_for('uso_veiculos_detalhes', uso_id=uso['id']), variant='ver'),
                )
                rows_and += f'''
                        <tr style="background: rgba(242, 130, 60, 0.1);">
                            {html_td_id(uso["id"])}
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);"><strong>{html_esc(uso["veiculo_placa"])}</strong></td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{html_esc(uso["motorista_nome"])}</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{html_esc(uso["agendamento_paciente"])}</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{html_esc(uso["data_saida"])} {html_esc(uso["hora_saida"])}</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color); font-size: 0.875rem;">{html_esc(rota_curta)}</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{uso["km_inicial"]} km</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color); text-align: center;">{acoes}</td>
                        </tr>'''
                cards_and += html_mobile_card(
                    title=f'#{uso["id"]} {uso["veiculo_placa"]}',
                    meta=html_esc(uso["agendamento_paciente"]),
                    status_html='<span style="color: var(--warning-color); font-weight: bold;">Em uso</span>',
                    rows=[
                        ('ID', f'<strong>{uso["id"]}</strong>'),
                        ('Motorista', html_esc(uso["motorista_nome"])),
                        ('Saída', f'{html_esc(uso["data_saida"])} {html_esc(uso["hora_saida"])}'),
                        ('Rota', html_esc(f'{origem} → {destino}')),
                        ('KM inicial', f'{uso["km_inicial"]} km'),
                    ],
                    acoes_html=acoes,
                )
            lista_andamento_html = f'''
            <div class="stp-list-desktop table-container">
                <table style="width: 100%; border-collapse: collapse;">
                    <thead>
                        <tr style="background: var(--color-95);">
                            {html_th_id()}
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Veículo</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Motorista</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Paciente</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Saída</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Origem → Destino</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">KM Inicial</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Ações</th>
                        </tr>
                    </thead>
                    <tbody>{rows_and}</tbody>
                </table>
            </div>
            <div class="stp-list-mobile">{cards_and}</div>'''
        else:
            lista_andamento_html = '''
            <div style="text-align: center; padding: 2rem;">
                <div style="font-size: 3rem; margin-bottom: 1rem; color: var(--success-color);">🎯</div>
                <h3 style="color: var(--text-color); margin-bottom: 1rem;">Nenhum veículo em uso</h3>
                <p style="color: var(--gray-color);">Todos os veículos estão disponíveis</p>
            </div>'''

        if usos_concluidos_dados:
            rows_conc = ""
            cards_conc = ""
            for uso in usos_concluidos_dados[:10]:
                status_bg = 'var(--success-color)' if uso['status'] == 'concluido' else 'var(--danger-color)'
                status_badge = (
                    f'<span style="padding: 0.25rem 0.5rem; border-radius: 0.25rem; font-size: 0.75rem; '
                    f'font-weight: bold; background: {status_bg}; color: white;">{html_esc(uso["status"].upper())}</span>'
                )
                rows_conc += f'''
                        <tr>
                            {html_td_id(uso["id"])}
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{html_esc(uso["data_uso"])}</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);"><strong>{html_esc(uso["veiculo_placa"])}</strong></td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{html_esc(uso["motorista_nome"])}</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{html_esc(uso["agendamento_paciente"])}</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{html_esc(uso["hora_saida"])} - {html_esc(uso["hora_retorno"])}</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{uso["km_rodados"]} km</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{html_esc(uso["duracao"])}</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">R$ {uso["valor_total"]:.2f}</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{status_badge}</td>
                        </tr>'''
                cards_conc += html_mobile_card(
                    title=f'#{uso["id"]} {uso["veiculo_placa"]}',
                    meta=html_esc(uso["data_uso"]),
                    status_html=status_badge,
                    rows=[
                        ('ID', f'<strong>{uso["id"]}</strong>'),
                        ('Motorista', html_esc(uso["motorista_nome"])),
                        ('Paciente', html_esc(uso["agendamento_paciente"])),
                        ('Horário', f'{html_esc(uso["hora_saida"])} - {html_esc(uso["hora_retorno"])}'),
                        ('KM', f'{uso["km_rodados"]} km'),
                        ('Duração', html_esc(uso["duracao"])),
                        ('Custo', f'R$ {uso["valor_total"]:.2f}'),
                    ],
                )
            lista_concluidos_html = f'''
            <div class="stp-list-desktop table-container">
                <table style="width: 100%; border-collapse: collapse;">
                    <thead>
                        <tr style="background: var(--color-95);">
                            {html_th_id()}
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Data</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Veículo</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Motorista</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Paciente</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Horário</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">KM</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Duração</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Custo</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Status</th>
                        </tr>
                    </thead>
                    <tbody>{rows_conc}</tbody>
                </table>
            </div>
            <div class="stp-list-mobile">{cards_conc}</div>'''
        else:
            lista_concluidos_html = '''
            <div style="text-align: center; padding: 2rem;">
                <p style="color: var(--gray-color);">Nenhum uso registrado nos últimos 30 dias</p>
            </div>'''
        
        conteudo = f'''
        <div class="page-header">
            <h2>🚗 Controle de Uso de Veículos</h2>
            <p>Registro e controle de saídas, retornos e custos da frota</p>
            <div style="margin-top: 1rem;">
                <a href="{url_for('uso_veiculos_iniciar')}" class="btn btn-success">🚦 Iniciar Uso de Veículo</a>
                <a href="{url_for('uso_veiculos')}" class="btn btn-secondary">📊 Relatório de Uso</a>
            </div>
        </div>
        
        <!-- Estatísticas -->
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 1rem; margin-bottom: 2rem;">
            <div class="card" style="text-align: center; padding: 1.5rem;">
                <h3 style="color: var(--warning-color); margin: 0 0 0.5rem 0;">🚦 Em Andamento</h3>
                <div style="font-size: 2rem; font-weight: bold; color: var(--warning-color);">{len(usos_andamento_dados)}</div>
            </div>
            <div class="card" style="text-align: center; padding: 1.5rem;">
                <h3 style="color: var(--success-color); margin: 0 0 0.5rem 0;">✅ Concluídos (30d)</h3>
                <div style="font-size: 2rem; font-weight: bold; color: var(--success-color);">{len([u for u in usos_concluidos_dados if u['status'] == 'concluido'])}</div>
            </div>
            <div class="card" style="text-align: center; padding: 1.5rem;">
                <h3 style="color: var(--info-color); margin: 0 0 0.5rem 0;">📏 KM Total (30d)</h3>
                <div style="font-size: 2rem; font-weight: bold; color: var(--info-color);">{sum([u['km_rodados'] for u in usos_concluidos_dados])}</div>
            </div>
            <div class="card" style="text-align: center; padding: 1.5rem;">
                <h3 style="color: var(--primary-color); margin: 0 0 0.5rem 0;">💰 Custo Total (30d)</h3>
                <div style="font-size: 2rem; font-weight: bold; color: var(--primary-color);">R$ {sum([u['valor_total'] for u in usos_concluidos_dados]):.2f}</div>
            </div>
        </div>
        
        <!-- Usos em Andamento -->
        <div class="card">
            <h3 style="color: var(--warning-color); margin-bottom: 1.5rem;">🚦 Veículos em Uso</h3>
            {lista_andamento_html}
        </div>
        
        <!-- Usos Recentes -->
        <div class="card">
            <h3 style="color: var(--primary-color); margin-bottom: 1.5rem;">📋 Usos Recentes (Últimos 30 dias)</h3>
            {lista_concluidos_html}
            
            {f'<div style="text-align: center; margin-top: 1rem;"><a href="{url_for("uso_veiculos")}" class="btn">📊 Ver Relatório Completo</a></div>' if len(usos_concluidos_dados) > 10 else ''}
        </div>
        '''
        
        return gerar_layout_base("Controle de Uso", conteudo, "uso_veiculos")
    
    @app.route('/uso-veiculos/iniciar', methods=['GET', 'POST'])
    @login_required
    def uso_veiculos_iniciar():
        if request.method == 'POST':
            try:
                agendamento_id = request.form.get('agendamento_id')
                veiculo_id = int(request.form.get('veiculo_id', 0))
                motorista_id = int(request.form.get('motorista_id', 0))
                data_uso = request.form.get('data_uso')
                hora_saida = request.form.get('hora_saida')
                endereco_origem = request.form.get('endereco_origem', '').strip()
                endereco_destino = request.form.get('endereco_destino', '').strip()
                km_inicial = request.form.get('km_inicial')
                observacoes = request.form.get('observacoes', '').strip()
                
                if not all([veiculo_id, motorista_id, data_uso, hora_saida, endereco_origem, endereco_destino]):
                    flash('Preencha todos os campos obrigatórios!', 'error')
                    return redirect(url_for('uso_veiculos_iniciar'))
                
                # Verificar se o veículo já está em uso
                uso_existente = UsoVeiculo.query.filter_by(
                    veiculo_id=veiculo_id,
                    status='em_andamento'
                ).first()
                
                if uso_existente:
                    flash('Este veículo já está em uso!', 'error')
                    return redirect(url_for('uso_veiculos_iniciar'))
                
                # Converter data e hora
                data_uso = datetime.strptime(data_uso, '%Y-%m-%d').date()
                hora_saida = datetime.strptime(hora_saida, '%H:%M').time()
                
                # Buscar valores do veículo (se terceirizado)
                veiculo = db.session.get(Veiculo, veiculo_id)
                valor_km = veiculo.valor_km if veiculo.tipo_propriedade == 'terceirizado' else None
                valor_diaria = veiculo.valor_diaria if veiculo.tipo_propriedade == 'terceirizado' else None
                
                # Criar novo uso
                uso = UsoVeiculo(
                    agendamento_id=int(agendamento_id) if agendamento_id else None,
                    veiculo_id=veiculo_id,
                    motorista_id=motorista_id,
                    data_uso=data_uso,
                    hora_saida=hora_saida,
                    endereco_origem=endereco_origem,
                    endereco_destino=endereco_destino,
                    km_inicial=int(km_inicial) if km_inicial else None,
                    valor_km=valor_km,
                    valor_diaria=valor_diaria,
                    observacoes=observacoes if observacoes else None
                )
                
                db.session.add(uso)
                db.session.commit()
                # Após db.session.commit() no sucesso do uso
                global whatsapp_service, notificacao_agendamento
                try:
                    if not whatsapp_service:
                        whatsapp_service = WhatsAppNotificacao(app, db)
                    if not notificacao_agendamento:
                        notificacao_agendamento = NotificacaoAgendamento(whatsapp_service)
                    
                    # Notificar que motorista saiu
                    notificacao_agendamento.notificar_motorista_saiu(uso)
                    print(f"✅ WhatsApp enviado: motorista saiu para {uso.agendamento.paciente.nome if uso.agendamento else 'uso avulso'}")
                    
                except Exception as e:
                    print(f"❌ Erro ao enviar WhatsApp motorista saiu: {e}")
                
                
                
                
                flash(f'Uso do veículo {veiculo.placa} iniciado com sucesso!', 'success')
                return redirect(url_for('uso_veiculos'))
                
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao iniciar uso: {str(e)}', 'error')
        
        # Buscar agendamentos de hoje sem uso registrado
        hoje = date.today()
        agendamentos_disponiveis = Agendamento.query.filter(
            Agendamento.data == hoje,
            ~Agendamento.id.in_(
                db.session.query(UsoVeiculo.agendamento_id).filter(UsoVeiculo.agendamento_id.isnot(None))
            )
        ).order_by(Agendamento.hora).all()
        
        # Buscar veículos disponíveis
        veiculos_em_uso = db.session.query(UsoVeiculo.veiculo_id).filter_by(status='em_andamento').subquery()
        veiculos_disponiveis = Veiculo.query.filter(
            Veiculo.ativo == True,
            ~Veiculo.id.in_(veiculos_em_uso)
        ).order_by(Veiculo.placa).all()
        
        # Buscar motoristas disponíveis
        motoristas_disponiveis = Motorista.query.filter_by(status='ativo').order_by(Motorista.nome).all()
        
        # Gerar options
        agendamentos_options = ""
        for ag in agendamentos_disponiveis:
            agendamentos_options += f'<option value="{ag.id}" data-origem="{ag.origem}" data-destino="{ag.destino}">{ag.hora.strftime("%H:%M")} - {ag.paciente.nome} ({ag.tipo_transporte})</option>'
        
        veiculos_options = ""
        for v in veiculos_disponiveis:
            veiculos_options += f'<option value="{v.id}">{v.placa} - {v.marca} {v.modelo}</option>'
        
        motoristas_options = ""
        for m in motoristas_disponiveis:
            motoristas_options += f'<option value="{m.id}">{m.nome}</option>'
        
        # Gerar alertas de mensagens flash
        messages_html = ""
        for category, message in get_flashed_messages(with_categories=True):
            alert_class = f"alert-{category}"
            messages_html += f'<div class="alert {alert_class}">{message}</div>'
        
        conteudo = f'''
        <div class="breadcrumb">
            <a href="{url_for('dashboard')}">Início</a> > 
            <a href="{url_for('uso_veiculos')}">Controle de Uso</a> > 
            Iniciar Uso
        </div>
        
        <div class="page-header">
            <h2>🚦 Iniciar Uso de Veículo</h2>
            <p>Registre a saída de um veículo para transporte</p>
        </div>
        
        {messages_html}
        
        <div class="card">
            <form method="POST">
                <div class="form-group">
                    <label for="agendamento_id">Agendamento (Opcional)</label>
                    <select id="agendamento_id" name="agendamento_id" onchange="preencherDadosAgendamento()">
                        <option value="">Uso avulso (sem agendamento)</option>
                        {agendamentos_options}
                    </select>
                    <small style="color: var(--gray-color);">Selecione um agendamento para preencher automaticamente origem e destino</small>
                </div>
                
                <div class="form-row">
                    <div class="form-group">
                        <label for="veiculo_id">Veículo *</label>
                        <select id="veiculo_id" name="veiculo_id" required>
                            <option value="">Selecione o veículo...</option>
                            {veiculos_options}
                        </select>
                    </div>
                    <div class="form-group">
                        <label for="motorista_id">Motorista *</label>
                        <select id="motorista_id" name="motorista_id" required>
                            <option value="">Selecione o motorista...</option>
                            {motoristas_options}
                        </select>
                    </div>
                </div>
                
                <div class="form-row">
                    <div class="form-group">
                        <label for="data_uso">Data de Uso *</label>
                        <input type="date" id="data_uso" name="data_uso" value="{hoje.strftime('%Y-%m-%d')}" required>
                    </div>
                    <div class="form-group">
                        <label for="hora_saida">Hora de Saída *</label>
                        <input type="time" id="hora_saida" name="hora_saida" value="{datetime.now().strftime('%H:%M')}" required>
                    </div>
                </div>
                
                <div class="form-group">
                    <label for="endereco_origem">Endereço de Origem *</label>
                    <input type="text" id="endereco_origem" name="endereco_origem" placeholder="De onde o veículo está saindo" required>
                </div>
                
                <div class="form-group">
                    <label for="endereco_destino">Endereço de Destino *</label>
                    <input type="text" id="endereco_destino" name="endereco_destino" placeholder="Para onde o veículo está indo" required>
                </div>
                
                <div class="form-group">
                    <label for="km_inicial">Quilometragem Inicial</label>
                    <input type="number" id="km_inicial" name="km_inicial" placeholder="Ex: 15000">
                    <small style="color: var(--gray-color);">Quilometragem do odômetro na saída</small>
                </div>
                
                <div class="form-group">
                    <label for="observacoes">Observações</label>
                    <textarea id="observacoes" name="observacoes" rows="3" placeholder="Informações adicionais sobre o uso"></textarea>
                </div>
                
                <div style="margin-top: 2rem;">
                    <button type="submit" class="btn btn-success">🚦 Iniciar Uso</button>
                    <a href="{url_for('uso_veiculos')}" class="btn btn-secondary" style="margin-left: 1rem;">❌ Cancelar</a>
                </div>
            </form>
        </div>
        
        <script>
            function preencherDadosAgendamento() {{
                const select = document.getElementById('agendamento_id');
                const option = select.options[select.selectedIndex];
                
                if (option.value) {{
                    document.getElementById('endereco_origem').value = option.dataset.origem || '';
                    document.getElementById('endereco_destino').value = option.dataset.destino || '';
                }} else {{
                    document.getElementById('endereco_origem').value = '';
                    document.getElementById('endereco_destino').value = '';
                }}
            }}
        </script>
        '''
        return gerar_layout_base("Iniciar Uso", conteudo, "uso_veiculos")
    
    @app.route('/uso-veiculos/finalizar/<int:uso_id>', methods=['GET', 'POST'])
    @login_required
    def uso_veiculos_finalizar(uso_id):
        uso = db.session.get(UsoVeiculo, uso_id)
        if not uso:
            flash('Registro de uso não encontrado!', 'error')
            return redirect(url_for('uso_veiculos'))
        
        if uso.status != 'em_andamento':
            flash('Este uso já foi finalizado!', 'warning')
            return redirect(url_for('uso_veiculos'))
        
        if request.method == 'POST':
            try:
                hora_retorno = request.form.get('hora_retorno')
                km_final = request.form.get('km_final')
                combustivel_valor = request.form.get('combustivel_valor')
                observacoes_finalizacao = request.form.get('observacoes_finalizacao', '').strip()
                
                if not hora_retorno:
                    flash('Hora de retorno é obrigatória!', 'error')
                    return redirect(url_for('uso_veiculos_finalizar', uso_id=uso_id))
                
                # Converter hora
                hora_retorno = datetime.strptime(hora_retorno, '%H:%M').time()
                
                # Atualizar uso
                uso.hora_retorno = hora_retorno
                uso.km_final = int(km_final) if km_final else None
                uso.combustivel_valor = float(combustivel_valor) if combustivel_valor else None
                uso.status = 'concluido'
                
                # Calcular KM rodados
                if uso.km_inicial and uso.km_final:
                    uso.km_rodados = uso.km_final - uso.km_inicial
                
                # Calcular valor total
                uso.calcular_valor_total()
                
                # Adicionar observações
                if observacoes_finalizacao:
                    if uso.observacoes:
                        uso.observacoes += f"\\n\\nFinalização: {observacoes_finalizacao}"
                    else:
                        uso.observacoes = f"Finalização: {observacoes_finalizacao}"
                
                db.session.commit()
                # Após db.session.commit() no sucesso da finalização
                global whatsapp_service, notificacao_agendamento
                try:
                    if not whatsapp_service:
                        whatsapp_service = WhatsAppNotificacao(app, db)
                    if not notificacao_agendamento:
                        notificacao_agendamento = NotificacaoAgendamento(whatsapp_service)
                    
                    # Notificar chegada ao destino
                    notificacao_agendamento.notificar_chegada(uso)
                    print(f"✅ WhatsApp enviado: chegada confirmada para {uso.agendamento.paciente.nome if uso.agendamento else 'uso avulso'}")
                    
                except Exception as e:
                    print(f"❌ Erro ao enviar WhatsApp chegada: {e}")
                
                
                
                flash(f'Uso do veículo {uso.veiculo.placa} finalizado com sucesso!', 'success')
                return redirect(url_for('uso_veiculos'))
                
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao finalizar uso: {str(e)}', 'error')
        
        # Gerar alertas de mensagens flash
        messages_html = ""
        for category, message in get_flashed_messages(with_categories=True):
            alert_class = f"alert-{category}"
            messages_html += f'<div class="alert {alert_class}">{message}</div>'
        
        conteudo = f'''
        <div class="breadcrumb">
            <a href="{url_for('dashboard')}">Início</a> > 
            <a href="{url_for('uso_veiculos')}">Controle de Uso</a> > 
            Finalizar Uso
        </div>
        
        <div class="page-header">
            <h2>🏁 Finalizar Uso de Veículo {html_id_badge(uso.id)}</h2>
            <p>Registre o retorno do veículo {uso.veiculo.placa}</p>
        </div>
        
        {messages_html}
        
        <!-- Informações do Uso -->
        <div class="card">
            <h3 style="color: var(--primary-color); margin-bottom: 1rem;">📄 Informações do Uso</h3>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 1rem; margin-bottom: 2rem;">
                <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem;">
                    <strong>🚗 Veículo:</strong><br /><br />
                    {uso.veiculo.placa} - {uso.veiculo.marca} {uso.veiculo.modelo}
                </div>
                <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem;">
                    <strong>👨‍💼 Motorista:</strong><br /><br />
                    {uso.motorista.nome}
                </div>
                <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem;">
                    <strong>📅 Data/Hora Saída:</strong><br /><br />
                    {uso.data_uso.strftime('%d/%m/%Y')} às {uso.hora_saida.strftime('%H:%M')}
                </div>
                <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem;">
                    <strong>📏 KM Inicial:</strong><br /><br />
                    {uso.km_inicial or 'Não informado'} km
                </div>
            </div>
            
            <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem; margin-bottom: 1rem;">
                <strong>🗺️ Trajeto:</strong><br /><br />
                <strong>Origem:</strong> {uso.endereco_origem}<br /><br />
                <strong>Destino:</strong> {uso.endereco_destino}
            </div>
        </div>
        
        <!-- Formulário de Finalização -->
        <div class="card">
            <h3 style="color: var(--success-color); margin-bottom: 1rem;">🏁 Dados de Retorno</h3>
            
            <form method="POST">
                <div class="form-row">
                    <div class="form-group">
                        <label for="hora_retorno">Hora de Retorno *</label>
                        <input type="time" id="hora_retorno" name="hora_retorno" value="{datetime.now().strftime('%H:%M')}" required>
                    </div>
                    <div class="form-group">
                        <label for="km_final">Quilometragem Final</label>
                        <input type="number" id="km_final" name="km_final" placeholder="Ex: 15050" min="{uso.km_inicial or 0}">
                        <small style="color: var(--gray-color);">Quilometragem do odômetro no retorno</small>
                    </div>
                </div>
                
                <div class="form-group">
                    <label for="combustivel_valor">Valor do Combustível (R$)</label>
                    <input type="number" id="combustivel_valor" name="combustivel_valor" step="0.01" placeholder="Ex: 50.00">
                    <small style="color: var(--gray-color);">Valor gasto com combustível durante o uso</small>
                </div>
                
                <div class="form-group">
                    <label for="observacoes_finalizacao">Observações da Finalização</label>
                    <textarea id="observacoes_finalizacao" name="observacoes_finalizacao" rows="3" placeholder="Problemas encontrados, observações sobre o retorno, etc."></textarea>
                </div>
                
                <div style="margin-top: 2rem;">
                    <button type="submit" class="btn btn-success">🏁 Finalizar Uso</button>
                    <a href="{url_for('uso_veiculos')}" class="btn btn-secondary" style="margin-left: 1rem;">❌ Cancelar</a>
                </div>
            </form>
        </div>
        '''
        return gerar_layout_base("Finalizar Uso", conteudo, "uso_veiculos")
    
    @app.route('/uso-veiculos/detalhes/<int:uso_id>')
    @login_required
    def uso_veiculos_detalhes(uso_id):
        uso = db.session.get(UsoVeiculo, uso_id)
        if not uso:
            flash('Registro de uso não encontrado!', 'error')
            return redirect(url_for('uso_veiculos'))
        
        # Calcular duração se o uso foi finalizado
        duracao_horas = uso.duracao_horas if uso.hora_retorno else None
        
        # Calcular tempo decorrido se ainda em andamento
        tempo_decorrido = None
        if uso.status == 'em_andamento':
            agora = datetime.now()
            inicio = datetime.combine(uso.data_uso, uso.hora_saida)
            
            # Se o uso começou hoje
            if uso.data_uso == date.today():
                diferenca = agora - inicio
                tempo_decorrido = diferenca.total_seconds() / 3600  # Em horas
            else:
                # Se começou em outro dia, calcular diferença
                diferenca = agora - inicio
                tempo_decorrido = diferenca.total_seconds() / 3600
        
        # Preparar dados do agendamento se existir
        agendamento_dados = None
        if uso.agendamento:
            agendamento_dados = {
                'id': uso.agendamento.id,
                'paciente_nome': uso.agendamento.paciente.nome,
                'paciente_telefone': uso.agendamento.paciente.telefone,
                'tipo_transporte': uso.agendamento.tipo_transporte,
                'data_agendamento': uso.agendamento.data.strftime('%d/%m/%Y'),
                'hora_agendamento': uso.agendamento.hora.strftime('%H:%M'),
                'status_agendamento': uso.agendamento.status,
                'observacoes_agendamento': uso.agendamento.observacoes
            }
        
        # Dados do veículo
        veiculo_dados = {
            'placa': uso.veiculo.placa,
            'marca_modelo': f"{uso.veiculo.marca} {uso.veiculo.modelo}",
            'ano': uso.veiculo.ano,
            'tipo': uso.veiculo.tipo.replace('_', ' ').title(),
            'tipo_propriedade': uso.veiculo.tipo_propriedade,
            'proprietario_nome': uso.veiculo.proprietario_nome,
            'valor_km': float(uso.veiculo.valor_km) if uso.veiculo.valor_km else None,
            'valor_diaria': float(uso.veiculo.valor_diaria) if uso.veiculo.valor_diaria else None
        }
        
        # Dados do motorista
        motorista_dados = {
            'nome': uso.motorista.nome,
            'telefone': uso.motorista.telefone,
            'cnh': uso.motorista.cnh,
            'categoria_cnh': uso.motorista.categoria_cnh
        }
        
        # Dados financeiros
        financeiro_dados = {
            'km_rodados': uso.km_rodados or 0,
            'valor_km_usado': float(uso.valor_km) if uso.valor_km else 0,
            'valor_diaria_usado': float(uso.valor_diaria) if uso.valor_diaria else 0,
            'valor_combustivel': float(uso.combustivel_valor) if uso.combustivel_valor else 0,
            'valor_total': float(uso.valor_total) if uso.valor_total else 0
        }
        
        conteudo = f'''
        <div class="breadcrumb">
            <a href="{url_for('dashboard')}">Início</a> > 
            <a href="{url_for('uso_veiculos')}">Controle de Uso</a> > 
            Detalhes do Uso #{uso.id}
        </div>
        
        <div class="page-header">
            <h2>📋 Detalhes do Uso de Veículo {html_id_badge(uso.id)}</h2>
            <p>Informações completas do uso {uso.id} - {uso.veiculo.placa}</p>
            <div style="margin-top: 1rem;">
                {f'<a href="{url_for("uso_veiculos_finalizar", uso_id=uso.id)}" class="btn btn-success">🏁 Finalizar Uso</a>' if uso.status == 'em_andamento' else ''}
                <a href="{url_for('uso_veiculos')}" class="btn btn-secondary">← Voltar</a>
            </div>
        </div>
        
        <!-- Status do Uso -->
        <div class="card">
            <div style="display: flex; justify-content: between; align-items: center; margin-bottom: 1rem;">
                <h3 style="color: var(--primary-color); margin: 0;">📊 Status do Uso</h3>
                <div>
                    <span style="padding: 0.5rem 1rem; border-radius: 0.5rem; font-size: 1rem; font-weight: bold; 
                          background: {'var(--warning-color)' if uso.status == 'em_andamento' else 'var(--success-color)' if uso.status == 'concluido' else 'var(--danger-color)'}; 
                          color: white;">
                        {'🚦 EM ANDAMENTO' if uso.status == 'em_andamento' else '✅ CONCLUÍDO' if uso.status == 'concluido' else '❌ CANCELADO'}
                    </span>
                </div>
            </div>
            
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 1rem;">
                <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem;">
                    <strong>📅 Data de Uso:</strong><br /><br />
                    {uso.data_uso.strftime('%d/%m/%Y (%A)').replace('Monday', 'Segunda').replace('Tuesday', 'Terça').replace('Wednesday', 'Quarta').replace('Thursday', 'Quinta').replace('Friday', 'Sexta').replace('Saturday', 'Sábado').replace('Sunday', 'Domingo')}
                </div>
                <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem;">
                    <strong>🚦 Hora de Saída:</strong><br /><br />
                    {uso.hora_saida.strftime('%H:%M')}
                </div>
                <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem;">
                    <strong>🏁 Hora de Retorno:</strong><br /><br />
                    {uso.hora_retorno.strftime('%H:%M') if uso.hora_retorno else 'Em andamento...'}
                </div>
                <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem;">
                    <strong>⏱️ Duração:</strong><br /><br />
                    {f'{duracao_horas:.1f} horas' if duracao_horas else f'{tempo_decorrido:.1f} horas (em andamento)' if tempo_decorrido else 'Calculando...'}
                </div>
            </div>
        </div>
        
        <!-- Informações do Veículo -->
        <div class="card">
            <h3 style="color: var(--primary-color); margin-bottom: 1rem;">🚗 Informações do Veículo</h3>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 1rem;">
                <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem;">
                    <strong>🏷️ Identificação:</strong><br /><br />
                    {veiculo_dados['placa']} - {veiculo_dados['marca_modelo']} ({veiculo_dados['ano']})
                </div>
                <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem;">
                    <strong>🚙 Tipo:</strong><br /><br />
                    {veiculo_dados['tipo']}
                </div>
                <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem;">
                    <strong>👤 Proprietário:</strong><br /><br />
                    {veiculo_dados['proprietario_nome'] if veiculo_dados['tipo_propriedade'] == 'terceirizado' else 'Prefeitura (Próprio)'}
                </div>
                <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem;">
                    <strong>💰 Tipo de Cobrança:</strong><br /><br />
                    {'Terceirizado' if veiculo_dados['tipo_propriedade'] == 'terceirizado' else 'Próprio (sem custo)'}
                </div>
            </div>
        </div>
        
        <!-- Informações do Motorista -->
        <div class="card">
            <h3 style="color: var(--primary-color); margin-bottom: 1rem;">👨‍💼 Informações do Motorista</h3>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 1rem;">
                <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem;">
                    <strong>👤 Nome:</strong><br /><br />
                    {motorista_dados['nome']}
                </div>
                <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem;">
                    <strong>📞 Telefone:</strong><br /><br />
                    {motorista_dados['telefone']}
                </div>
                <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem;">
                    <strong>🆔 CNH:</strong><br /><br />
                    {motorista_dados['cnh']} (Categoria {motorista_dados['categoria_cnh']})
                </div>
            </div>
        </div>
        
        <!-- Informações do Trajeto -->
        <div class="card">
            <h3 style="color: var(--primary-color); margin-bottom: 1rem;">🗺️ Informações do Trajeto</h3>
            
            <div style="display: grid; grid-template-columns: 1fr auto 1fr; gap: 1rem; align-items: center; margin-bottom: 2rem;">
                <div style="background: var(--success-color); color: white; padding: 1rem; border-radius: 0.5rem; text-align: center;">
                    <strong>🚦 ORIGEM</strong><br /><br />
                    {uso.endereco_origem}
                </div>
                <div style="font-size: 2rem; color: var(--primary-color);">
                    ➡️
                </div>
                <div style="background: var(--info-color); color: white; padding: 1rem; border-radius: 0.5rem; text-align: center;">
                    <strong>🏁 DESTINO</strong><br /><br />
                    {uso.endereco_destino}
                </div>
            </div>
            
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem;">
                <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem; text-align: center;">
                    <strong>📏 KM Inicial:</strong><br /><br />
                    <span style="font-size: 1.2rem; color: var(--primary-color);">{uso.km_inicial or 'Não informado'}</span>
                </div>
                <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem; text-align: center;">
                    <strong>📏 KM Final:</strong><br /><br />
                    <span style="font-size: 1.2rem; color: var(--primary-color);">{uso.km_final or 'Não finalizado' if uso.status == 'em_andamento' else 'Não informado'}</span>
                </div>
                <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem; text-align: center;">
                    <strong>🛣️ KM Rodados:</strong><br /><br />
                    <span style="font-size: 1.2rem; color: var(--success-color); font-weight: bold;">{uso.km_rodados or 0} km</span>
                </div>
            </div>
        </div>
        
        {'''
        <!-- Informações do Agendamento -->
        <div class="card">
            <h3 style="color: var(--primary-color); margin-bottom: 1rem;">📅 Agendamento Relacionado</h3>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 1rem;">
                <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem;">
                    <strong>👤 Paciente:</strong><br /><br />
                    ''' + agendamento_dados['paciente_nome'] + '''
                </div>
                <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem;">
                    <strong>📞 Telefone:</strong><br /><br />
                    ''' + agendamento_dados['paciente_telefone'] + '''
                </div>
                <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem;">
                    <strong>🏥 Tipo:</strong><br /><br />
                    ''' + agendamento_dados['tipo_transporte'].title() + '''
                </div>
                <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem;">
                    <strong>📊 Status Agendamento:</strong><br /><br />
                    <span style="padding: 0.25rem 0.5rem; border-radius: 0.25rem; background: var(--info-color); color: white; font-size: 0.875rem;">
                        ''' + agendamento_dados['status_agendamento'].replace('_', ' ').title() + '''
                    </span>
                </div>
            </div>
            ''' + (f'''
            <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem; margin-top: 1rem;">
                <strong>📝 Observações do Agendamento:</strong><br /><br />
                {agendamento_dados["observacoes_agendamento"] or "Nenhuma observação"}
            </div>
            ''' if agendamento_dados.get('observacoes_agendamento') else '') + '''
        </div>
        ''' if agendamento_dados else '''
        <!-- Sem Agendamento -->
        <div class="card">
            <h3 style="color: var(--gray-color); margin-bottom: 1rem;">📅 Uso Avulso</h3>
            <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem; text-align: center;">
                <span style="color: var(--gray-color);">Este uso não está relacionado a nenhum agendamento específico</span>
            </div>
        </div>
        '''}
        
        <!-- Informações Financeiras -->
        <div class="card">
            <h3 style="color: var(--success-color); margin-bottom: 1rem;">💰 Informações Financeiras</h3>
            
            {'''
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 1rem;">
                <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem; text-align: center;">
                    <strong>📏 Valor por KM:</strong><br /><br />
                    <span style="font-size: 1.2rem; color: var(--primary-color);">R$ ''' + f"{financeiro_dados['valor_km_usado']:.2f}" + '''</span>
                </div>
                <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem; text-align: center;">
                    <strong>📅 Valor Diária:</strong><br /><br />
                    <span style="font-size: 1.2rem; color: var(--primary-color);">R$ ''' + f"{financeiro_dados['valor_diaria_usado']:.2f}" + '''</span>
                </div>
                <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem; text-align: center;">
                    <strong>⛽ Combustível:</strong><br /><br />
                    <span style="font-size: 1.2rem; color: var(--warning-color);">R$ ''' + f"{financeiro_dados['valor_combustivel']:.2f}" + '''</span>
                </div>
            </div>
            
            <div style="background: linear-gradient(135deg, var(--success-color), #6a9d3e); color: white; padding: 1.5rem; border-radius: 0.5rem; text-align: center;">
                <h4 style="margin: 0 0 0.5rem 0;">💰 CUSTO TOTAL</h4>
                <div style="font-size: 2.5rem; font-weight: bold;">R$ ''' + f"{financeiro_dados['valor_total']:.2f}" + '''</div>
                <small>''' + ('Custo baseado em KM rodados + combustível' if financeiro_dados['km_rodados'] > 0 and financeiro_dados['valor_km_usado'] > 0 else 'Custo baseado em diária + combustível' if financeiro_dados['valor_diaria_usado'] > 0 else 'Apenas combustível' if financeiro_dados['valor_combustivel'] > 0 else 'Veículo próprio - sem custo') + '''</small>
            </div>
            ''' if veiculo_dados['tipo_propriedade'] == 'terceirizado' else '''
            <div style="background: var(--info-color); color: white; padding: 1.5rem; border-radius: 0.5rem; text-align: center;">
                <h4 style="margin: 0 0 0.5rem 0;">🏛️ VEÍCULO PRÓPRIO</h4>
                <div style="font-size: 1.5rem; font-weight: bold;">Sem custo de terceirização</div>
                <small>Apenas custos de combustível: R$ ''' + f"{financeiro_dados['valor_combustivel']:.2f}" + '''</small>
            </div>
            '''}
        </div>
        
        {'''
        <!-- Observações -->
        <div class="card">
            <h3 style="color: var(--primary-color); margin-bottom: 1rem;">📝 Observações</h3>
            <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem; white-space: pre-line;">
                ''' + (uso.observacoes or 'Nenhuma observação registrada') + '''
            </div>
        </div>
        ''' if uso.observacoes else ''}
        
        <!-- Ações -->
        <div style="margin-top: 2rem; text-align: center;">
            <a href="{url_for('uso_veiculos')}" class="btn btn-secondary">← Voltar para Controle de Uso</a>
            {f'<a href="{url_for("uso_veiculos_finalizar", uso_id=uso.id)}" class="btn btn-success" style="margin-left: 1rem;">🏁 Finalizar Este Uso</a>' if uso.status == 'em_andamento' else ''}
        </div>
        '''
        
        return gerar_layout_base(f"Detalhes do Uso #{uso.id}", conteudo, "uso_veiculos")
    
       # ====ROTAS PARA SISTEMA DE BACKUP ====INICIO
       # ===== ROTAS DE BACKUP AUTOMÁTICO =====
    @app.route('/backup')
    @login_required
    def backup_dashboard():
        global sistema_backup
        if not sistema_backup:
            sistema_backup = SistemaBackup(app, db)
        
        # Obter histórico
        historico = sistema_backup.obter_historico_backups()
        
        # Estatísticas
        total_backups = len(historico)
        backup_hoje = len([b for b in historico if b['data'].startswith(date.today().isoformat())])
        
        # Tamanho total
        tamanho_total = sum(b.get('tamanho', 0) for b in historico)
        tamanho_total_mb = round(tamanho_total / (1024*1024), 2)
        
        # Último backup
        ultimo_backup = historico[-1] if historico else None

        rows_bk = ""
        cards_bk = ""
        for backup in reversed(historico[-20:]):
            data_backup = datetime.fromisoformat(backup['data'])
            tipo_icon = '🔄' if backup['tipo'] == 'diario' else '📅' if backup['tipo'] == 'mensal' else '👤'
            tipo_color = '#17a2b8' if backup['tipo'] == 'diario' else '#28a745' if backup['tipo'] == 'mensal' else '#6c757d'
            tipo_html = f'<span style="color: {tipo_color}; font-weight: bold;">{tipo_icon} {html_esc(backup["tipo"].title())}</span>'
            acoes = html_acoes_toolbar(
                html_acao_icone(
                    'ti-download',
                    'Baixar backup',
                    variant='download',
                    as_button=True,
                    onclick=f"downloadBackup('{backup['arquivo']}');",
                )
            )
            rows_bk += f'''
                        <tr>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{data_backup.strftime('%d/%m/%Y %H:%M:%S')}</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{html_esc(backup['arquivo'])}</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{tipo_html}</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">{backup.get('tamanho_mb', 0)} MB</td>
                            <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color); text-align: center;">{acoes}</td>
                        </tr>'''
            cards_bk += html_mobile_card(
                title=backup['arquivo'],
                meta=data_backup.strftime('%d/%m/%Y %H:%M:%S'),
                status_html=tipo_html,
                rows=[('Tamanho', f"{backup.get('tamanho_mb', 0)} MB")],
                acoes_html=acoes,
            )
        if rows_bk:
            lista_backup_html = f'''
            <div class="stp-list-desktop table-container">
                <table style="width: 100%; border-collapse: collapse;">
                    <thead>
                        <tr style="background: var(--color-95);">
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Data/Hora</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Arquivo</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Tipo</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Tamanho</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Ações</th>
                        </tr>
                    </thead>
                    <tbody>{rows_bk}</tbody>
                </table>
            </div>
            <div class="stp-list-mobile">{cards_bk}</div>'''
        else:
            lista_backup_html = '<p style="color: var(--gray-color); margin: 1rem 0;">Nenhum backup registrado.</p>'
        
        conteudo = f'''
        <div class="page-header">
            <h2>💾 Sistema de Backup</h2>
            <p>Gerenciamento e automação de backups do sistema</p>
            <div style="margin-top: 1rem;">
                <button onclick="criarBackupManual()" class="btn">💾 Backup Manual</button>
                <button onclick="exportarExcel()" class="btn btn-secondary">📊 Exportar Excel</button>
                <button onclick="limparBackupsAntigos()" class="btn btn-warning">🧹 Limpeza</button>
            </div>        
        <!-- ESTATÍSTICAS -->
        <div class="row g-4 mb-4">
            <div class="col-xl-3 col-md-6">
                <div class="card stats-card card-primary fade-in-up">
                    <div class="card-body">
                        <div class="d-flex align-items-center">
                            <div class="stats-icon icon-primary">
                                <i class="ti ti-archive"></i>
                            </div>
                            <div class="flex-grow-1">
                                <div class="stats-label">Total de Backups</div>
                                <div class="stats-number">{total_backups}</div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="col-xl-3 col-md-6">
                <div class="card stats-card card-success fade-in-up" style="animation-delay: 0.1s">
                    <div class="card-body">
                        <div class="d-flex align-items-center">
                            <div class="stats-icon icon-success">
                                <i class="ti ti-calendar-check"></i>
                            </div>
                            <div class="flex-grow-1">
                                <div class="stats-label">Backups Hoje</div>
                                <div class="stats-number">{backup_hoje}</div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="col-xl-3 col-md-6">
                <div class="card stats-card card-warning fade-in-up" style="animation-delay: 0.2s">
                    <div class="card-body">
                        <div class="d-flex align-items-center">
                            <div class="stats-icon icon-warning">
                                <i class="ti ti-database"></i>
                            </div>
                            <div class="flex-grow-1">
                                <div class="stats-label">Espaço Usado</div>
                                <div class="stats-number">{tamanho_total_mb} MB</div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="col-xl-3 col-md-6">
                <div class="card stats-card card-info fade-in-up" style="animation-delay: 0.3s">
                    <div class="card-body">
                        <div class="d-flex align-items-center">
                            <div class="stats-icon icon-info">
                                <i class="ti ti-history"></i>
                            </div>
                            <div class="flex-grow-1">
                                <div class="stats-label">Último Backup</div>
                                <div class="stats-number" style="font-size: 1.2rem;">
                                    {datetime.fromisoformat(ultimo_backup['data']).strftime('%d/%m %H:%M') if ultimo_backup else 'Nunca'}
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- CONFIGURAÇÕES -->
        <div class="row g-4 mb-4">
            <div class="col-lg-6">
                <div class="card">
                    <h4>⚙️ Configurações de Backup</h4>
                    <div style="padding: 1rem; background: #f8f9fa; border-radius: 0.375rem; margin-bottom: 1rem;">
                        <h5 style="color: var(--primary-color); margin-bottom: 0.5rem;">🔄 Backup Automático</h5>
                        <p style="margin-bottom: 0.5rem;"><strong>Diário:</strong> Todo dia às 02:00</p>
                        <p style="margin-bottom: 0.5rem;"><strong>Mensal:</strong> 1º dia do mês às 03:00</p>
                        <p style="margin-bottom: 0;"><strong>Limpeza:</strong> Segundas às 04:00</p>
                    </div>
                    
                    <div style="padding: 1rem; background: #e8f4f8; border-radius: 0.375rem;">
                        <h5 style="color: var(--info-color); margin-bottom: 0.5rem;">📁 Retenção de Arquivos</h5>
                        <p style="margin-bottom: 0.5rem;"><strong>Backups Diários:</strong> 30 dias</p>
                        <p style="margin-bottom: 0.5rem;"><strong>Backups Mensais:</strong> 365 dias</p>
                        <p style="margin-bottom: 0;"><strong>Arquivos Excel:</strong> 90 dias</p>
                    </div>
                </div>
            </div>
            
            <div class="col-lg-6">
                <div class="card">
                    <h4>🚀 Ações Rápidas</h4>
                    <div style="display: flex; flex-direction: column; gap: 1rem;">
                        <button onclick="criarBackupManual()" class="btn" style="width: 100%;">
                            💾 Criar Backup Agora
                        </button>
                        <button onclick="exportarExcel()" class="btn btn-secondary" style="width: 100%;">
                            📊 Exportar para Excel
                        </button>
                        <button onclick="limparBackupsAntigos()" class="btn btn-warning" style="width: 100%;">
                            🧹 Limpeza Manual
                        </button>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- HISTÓRICO -->
        <div class="card">
            <h4>📋 Histórico de Backups</h4>
            {lista_backup_html}
        </div>
        '''

        conteudo += '''
        <script>
            async function criarBackupManual() {
                if (confirm('Criar backup manual agora?')) {
                    try {
                        const response = await fetch('/transporte/backup/manual', { method: 'POST' });
                        const result = await response.json();
                        
                        if (result.sucesso) {
                            alert('✅ Backup criado com sucesso!');
                            location.reload();
                        } else {
                            alert('❌ Erro: ' + result.erro);
                        }
                    } catch (error) {
                        alert('❌ Erro ao criar backup: ' + error);
                    }
                }
            }
            
            async function exportarExcel() {
                if (confirm('Exportar todos os dados para Excel?')) {
                    try {
                        const response = await fetch('/transporte/backup/excel', { method: 'POST' });
                        const result = await response.json();
                        
                        if (result.sucesso) {
                            alert('✅ Dados exportados para Excel!');
                            location.reload();
                        } else {
                            alert('❌ Erro: ' + result.erro);
                        }
                    } catch (error) {
                        alert('❌ Erro ao exportar: ' + error);
                    }
                }
            }
            
            async function limparBackupsAntigos() {
                if (confirm('Limpar backups antigos conforme política de retenção?')) {
                    try {
                        const response = await fetch('/transporte/backup/limpeza', { method: 'POST' });
                        const result = await response.json();
                        
                        if (result.sucesso) {
                            alert('✅ Limpeza concluída!');
                            location.reload();
                        } else {
                            alert('❌ Erro na limpeza: ' + result.erro);
                        }
                    } catch (error) {
                        alert('❌ Erro: ' + error);
                    }
                }
            }
            
            function downloadBackup(arquivo) {
                window.location.href = '/backup/download/' + arquivo;
            }
        </script>
        '''
        
        return gerar_layout_base("Sistema de Backup", conteudo, "backup")

    @app.route('/backup/manual', methods=['POST'])
    @login_required
    def backup_manual():
        global sistema_backup
        if not sistema_backup:
            sistema_backup = SistemaBackup(app, db)
        
        resultado = sistema_backup.backup_banco_dados('manual')
        return jsonify(resultado)

    @app.route('/backup/excel', methods=['POST'])
    @login_required
    def backup_excel():
        global sistema_backup
        if not sistema_backup:
            sistema_backup = SistemaBackup(app, db)
        
        resultado = sistema_backup.exportar_para_excel()
        return jsonify(resultado)

    @app.route('/backup/limpeza', methods=['POST'])
    @login_required
    def backup_limpeza():
        global sistema_backup
        if not sistema_backup:
            sistema_backup = SistemaBackup(app, db)
        
        try:
            sistema_backup.limpeza_automatica()
            return jsonify({'sucesso': True})
        except Exception as e:
            return jsonify({'sucesso': False, 'erro': str(e)})

    @app.route('/backup/download/<arquivo>')
    @login_required
    def backup_download(arquivo):
        """Download de arquivo de backup"""
        try:
            global sistema_backup
            if not sistema_backup:
                sistema_backup = SistemaBackup(app, db)
            
            import os
            from flask import send_file, abort
            
            # Verificar em todos os diretórios de backup
            subdirs = ['diarios', 'mensais', 'excel', 'manuais']
            arquivo_path = None
            
            for subdir in subdirs:
                caminho_teste = os.path.join(sistema_backup.backup_dir, subdir, arquivo)
                if os.path.exists(caminho_teste):
                    arquivo_path = caminho_teste
                    break
            
            if not arquivo_path:
                flash('Arquivo de backup não encontrado!', 'error')
                return redirect(url_for('backup_dashboard'))
            
            return send_file(arquivo_path, as_attachment=True, download_name=arquivo)
            
        except Exception as e:
            flash(f'Erro ao fazer download: {str(e)}', 'error')
            return redirect(url_for('backup_dashboard'))

    @app.route('/backup/configurar', methods=['GET', 'POST'])
    @login_required
    def backup_configurar():
        """Configurações avançadas do sistema de backup"""
        if not current_user.tipo_usuario == 'administrador':
            flash('Acesso negado! Apenas administradores podem configurar backups.', 'error')
            return redirect(url_for('backup_dashboard'))
        
        if request.method == 'POST':
            # Aqui você pode implementar salvamento de configurações
            flash('Configurações salvas com sucesso!', 'success')
            return redirect(url_for('backup_dashboard'))
        
        conteudo = f'''
        <div class="page-header">
            <h2>⚙️ Configurações de Backup</h2>
            <p>Configure os parâmetros do sistema de backup automático</p>
        </div>
        
        <div class="card">
            <h3>🔧 Configurações Avançadas</h3>
            <form method="POST">
                <div class="form-row">
                    <div class="form-group">
                        <label>Backup Diário (Hora):</label>
                        <input type="time" name="backup_diario_hora" value="02:00">
                    </div>
                    <div class="form-group">
                        <label>Backup Mensal (Dia):</label>
                        <input type="number" name="backup_mensal_dia" value="1" min="1" max="28">
                    </div>
                </div>
                
                <div class="form-row">
                    <div class="form-group">
                        <label>Retenção Backups Diários (dias):</label>
                        <input type="number" name="retencao_diarios" value="30" min="7" max="365">
                    </div>
                    <div class="form-group">
                        <label>Retenção Backups Mensais (dias):</label>
                        <input type="number" name="retencao_mensais" value="365" min="30" max="3650">
                    </div>
                </div>
                
                <div class="form-group">
                    <label>
                        <input type="checkbox" name="backup_automatico" checked>
                        Ativar backup automático
                    </label>
                </div>
                
                <div style="margin-top: 2rem;">
                    <button type="submit" class="btn btn-success">💾 Salvar Configurações</button>
                    <a href="{url_for('backup_dashboard')}" class="btn btn-secondary">❌ Cancelar</a>
                </div>
            </form>
        </div>
        '''
        
        return gerar_layout_base("Configurações de Backup", conteudo, "backup")
        # ====ROTAS PARA SISTEMA DE BACKUP ====FIM
           
    # ===== ROTAS DE NOTIFICAÇÕES WHATSAPP =====
    @app.route('/whatsapp')
    @login_required
    def whatsapp_dashboard():
        if not _whatsapp_admin_required():
            flash('Acesso restrito a administradores.', 'error')
            return redirect(url_for('dashboard'))

        global whatsapp_service
        if not whatsapp_service:
            whatsapp_service = WhatsAppNotificacao(app, db)
        
        stats = whatsapp_service.obter_estatisticas()
        logs = whatsapp_service.obter_logs_recentes(10)
        logs_html = ''
        if logs:
            for item in reversed(logs):
                cor = 'var(--success-color)' if item['tipo'] == 'sucesso' else 'var(--danger-color)'
                from html import escape as _esc
                logs_html += (
                    f'<li style="margin-bottom:0.5rem; color:{cor}; font-size:0.85rem; word-break:break-word;">'
                    f'{_esc(item["texto"])}</li>'
                )
        else:
            logs_html = '<li style="color:var(--gray-color);">Nenhum envio registrado hoje.</li>'

        status_bg = 'rgba(121, 178, 74, 0.15)' if stats['servico_ativo'] else 'rgba(232, 29, 81, 0.12)'
        status_label = 'ATIVO' if stats['servico_ativo'] else 'INATIVO'
        status_desc = 'Worker processando a fila' if stats['servico_ativo'] else 'Serviço parado'
        iniciar_url = url_for('whatsapp_iniciar')
        parar_url = url_for('whatsapp_parar')
        teste_url = url_for('whatsapp_teste')
        
        conteudo = f'''
        <div class="breadcrumb">
            <a href="{url_for('dashboard')}">Início</a> > WhatsApp
        </div>
        <div class="page-header">
            <h2>Sistema de Notificações WhatsApp</h2>
            <p>Comunicação automática com pacientes (confirmação, lembrete, saída e chegada).</p>
        </div>

        <div class="alert alert-warning" role="status">
            Integração via WhatsApp Web. Ao enviar teste, <strong>não mexa no mouse nem no teclado</strong>
            por cerca de 30 segundos — o Chrome precisa ficar em foco para confirmar o envio no celular.
            Não há confirmação oficial de entrega da Meta. Acesso restrito a administradores.
        </div>
        
        <div class="form-actions" style="margin-top:0; margin-bottom:1.25rem;">
            <button type="button" id="btnIniciarWa" class="btn btn-success" {"disabled" if stats["servico_ativo"] else ""}>Iniciar serviço</button>
            <button type="button" id="btnPararWa" class="btn btn-warning" {"disabled" if not stats["servico_ativo"] else ""}>Parar serviço</button>
            <a href="#teste-manual" class="btn btn-secondary">Ir para teste</a>
        </div>
        
        <div class="card">
            <h3 style="margin-top:0; color:var(--primary-color);">Status do serviço</h3>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem;">
                <div style="background: {status_bg}; padding: 1rem; border-radius: 0.5rem; text-align: center; border:1px solid var(--border-color);">
                    <h4 style="margin:0 0 0.35rem;">{status_label}</h4>
                    <p style="margin:0; color:var(--gray-color);">{status_desc}</p>
                </div>
                <div style="background: var(--color-95); padding: 1rem; border-radius: 0.5rem; text-align: center; border:1px solid var(--border-color);">
                    <h4 style="margin:0 0 0.35rem;">Fila</h4>
                    <p style="margin:0;"><strong>{stats['fila_pendente']}</strong> pendente(s)</p>
                </div>
                <div style="background: rgba(121, 178, 74, 0.12); padding: 1rem; border-radius: 0.5rem; text-align: center; border:1px solid var(--border-color);">
                    <h4 style="margin:0 0 0.35rem;">Sucessos</h4>
                    <p style="margin:0;"><strong>{stats['sucessos_hoje']}</strong> hoje</p>
                </div>
                <div style="background: rgba(232, 29, 81, 0.1); padding: 1rem; border-radius: 0.5rem; text-align: center; border:1px solid var(--border-color);">
                    <h4 style="margin:0 0 0.35rem;">Erros</h4>
                    <p style="margin:0;"><strong>{stats['erros_hoje']}</strong> hoje</p>
                </div>
            </div>
        </div>
        
        <div class="card" id="teste-manual">
            <h3 style="margin-top:0; color:var(--primary-color);">Teste manual</h3>
            <p class="field-hint" style="margin-top:0;">
                Envia mensagem de teste imediata (~30s). Informe celular com DDD (11 dígitos).
                Durante o envio, deixe o Chrome em primeiro plano e não use o computador.
            </p>
            <div class="form-row">
                <div class="form-group">
                    <label for="telefone_teste">Telefone celular <span class="required-mark" aria-hidden="true">*</span></label>
                    <input type="tel" id="telefone_teste" name="telefone_teste" placeholder="(00) 00000-0000"
                           maxlength="16" data-mask="phone" autocomplete="tel" aria-describedby="telefone_teste_hint">
                    <small id="telefone_teste_hint" class="field-hint">Formato: (19) 99999-9999</small>
                </div>
            </div>
            <div class="form-actions">
                <button type="button" id="btnEnviarTeste" class="btn btn-success">Enviar teste</button>
            </div>
            <div id="waFeedback" class="alert" style="display:none; margin-top:1rem;" role="status" aria-live="polite"></div>
        </div>

        <div class="card">
            <h3 style="margin-top:0; color:var(--primary-color);">Logs recentes (hoje)</h3>
            <ul style="padding-left:1.1rem; margin:0;">{logs_html}</ul>
        </div>
        
        <script>
            const WA_URLS = {{
                iniciar: {iniciar_url!r},
                parar: {parar_url!r},
                teste: {teste_url!r}
            }};

            function setBusy(btn, busy, labelBusy) {{
                if (!btn) return;
                if (busy) {{
                    btn.dataset.prev = btn.textContent;
                    btn.disabled = true;
                    btn.setAttribute('aria-busy', 'true');
                    btn.textContent = labelBusy || 'Enviando...';
                }} else {{
                    btn.disabled = false;
                    btn.removeAttribute('aria-busy');
                    if (btn.dataset.prev) btn.textContent = btn.dataset.prev;
                }}
            }}

            function showFeedback(ok, msg) {{
                const el = document.getElementById('waFeedback');
                if (!el) return;
                el.style.display = 'block';
                el.className = 'alert ' + (ok ? 'alert-success' : 'alert-error');
                el.textContent = msg;
            }}

            async function iniciarServico() {{
                const btn = document.getElementById('btnIniciarWa');
                setBusy(btn, true, 'Iniciando...');
                try {{
                    const response = await fetch(WA_URLS.iniciar, {{ method: 'POST', headers: {{ 'Accept': 'application/json' }} }});
                    const result = await response.json();
                    if (result.sucesso) {{
                        showFeedback(true, 'Serviço iniciado.');
                        location.reload();
                    }} else {{
                        showFeedback(false, result.erro || 'Falha ao iniciar.');
                        setBusy(btn, false);
                    }}
                }} catch (error) {{
                    showFeedback(false, 'Erro de rede ao iniciar serviço.');
                    setBusy(btn, false);
                }}
            }}
            
            async function pararServico() {{
                if (!confirm('Parar o serviço de WhatsApp?')) return;
                const btn = document.getElementById('btnPararWa');
                setBusy(btn, true, 'Parando...');
                try {{
                    const response = await fetch(WA_URLS.parar, {{ method: 'POST', headers: {{ 'Accept': 'application/json' }} }});
                    const result = await response.json();
                    if (result.sucesso) {{
                        showFeedback(true, 'Serviço parado.');
                        location.reload();
                    }} else {{
                        showFeedback(false, result.erro || 'Falha ao parar.');
                        setBusy(btn, false);
                    }}
                }} catch (error) {{
                    showFeedback(false, 'Erro de rede ao parar serviço.');
                    setBusy(btn, false);
                }}
            }}
            
            async function enviarTeste() {{
                const input = document.getElementById('telefone_teste');
                const telefone = (input && input.value || '').trim();
                const btn = document.getElementById('btnEnviarTeste');
                
                if (!telefone) {{
                    showFeedback(false, 'Informe o telefone celular.');
                    if (input) {{ input.classList.add('is-invalid'); input.focus(); }}
                    return;
                }}
                if (input) input.classList.remove('is-invalid');
                
                setBusy(btn, true, 'Enviando...');
                try {{
                    const response = await fetch(WA_URLS.teste, {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json', 'Accept': 'application/json' }},
                        body: JSON.stringify({{ telefone, tipo: 'teste' }})
                    }});
                    const result = await response.json();
                    if (result.sucesso) {{
                        showFeedback(true, 'Comando de envio concluído. Confira no celular ' + telefone + ' se a mensagem chegou. Se não chegou, mantenha o WhatsApp Web logado no Chrome e tente de novo sem mexer no PC.');
                        setTimeout(function() {{ location.reload(); }}, 2500);
                    }} else {{
                        showFeedback(false, result.erro || 'Falha no envio do teste.');
                        setBusy(btn, false);
                    }}
                }} catch (error) {{
                    showFeedback(false, 'Erro de rede ao enviar teste (ou o envio ainda está em andamento — aguarde o Chrome).');
                    setBusy(btn, false);
                }}
            }}

            document.getElementById('btnIniciarWa')?.addEventListener('click', iniciarServico);
            document.getElementById('btnPararWa')?.addEventListener('click', pararServico);
            document.getElementById('btnEnviarTeste')?.addEventListener('click', enviarTeste);
        </script>
        '''
        
        return gerar_layout_base("WhatsApp", conteudo, "whatsapp")

    @app.route('/whatsapp/iniciar', methods=['POST'])
    @login_required
    def whatsapp_iniciar():
        if not _whatsapp_admin_required():
            return jsonify({'sucesso': False, 'erro': 'Acesso restrito a administradores.'}), 403
        if whatsapp_bloqueado_por_simulacao():
            return jsonify({
                'sucesso': False,
                'erro': 'WhatsApp bloqueado (STP_BLOQUEAR_WHATSAPP=1). Remova a flag para liberar envios.',
            }), 403
        global whatsapp_service
        try:
            if not whatsapp_service:
                whatsapp_service = WhatsAppNotificacao(app, db)
            
            whatsapp_service.iniciar_servico()
            return jsonify({'sucesso': True})
        except Exception as e:
            return jsonify({'sucesso': False, 'erro': 'Não foi possível iniciar o serviço.'}), 500

    @app.route('/whatsapp/parar', methods=['POST'])
    @login_required
    def whatsapp_parar():
        if not _whatsapp_admin_required():
            return jsonify({'sucesso': False, 'erro': 'Acesso restrito a administradores.'}), 403
        global whatsapp_service
        try:
            if whatsapp_service:
                whatsapp_service.parar_servico()
            return jsonify({'sucesso': True})
        except Exception as e:
            return jsonify({'sucesso': False, 'erro': 'Não foi possível parar o serviço.'}), 500

    @app.route('/whatsapp/teste', methods=['POST'])
    @login_required
    def whatsapp_teste():
        if not _whatsapp_admin_required():
            return jsonify({'sucesso': False, 'erro': 'Acesso restrito a administradores.'}), 403
        if whatsapp_bloqueado_por_simulacao():
            return jsonify({
                'sucesso': False,
                'erro': 'WhatsApp bloqueado (STP_BLOQUEAR_WHATSAPP=1). Nenhum teste será enviado.',
            }), 403
        global whatsapp_service
        try:
            if not whatsapp_service:
                whatsapp_service = WhatsAppNotificacao(app, db)
            
            data = request.get_json(silent=True) or {}
            telefone = (data.get('telefone') or '').strip()
            if not telefone:
                return jsonify({'sucesso': False, 'erro': 'Telefone obrigatório.'}), 400
            if not whatsapp_service._validar_telefone(telefone):
                return jsonify({'sucesso': False, 'erro': 'Telefone inválido. Use celular com DDD (11 dígitos).'}), 422
            
            mensagem = (
                f"TESTE STP Cosmopolis\n"
                f"Enviado em {datetime.now().strftime('%d/%m/%Y as %H:%M')}\n"
                f"Operador: {current_user.username}\n"
                f"Se voce recebeu esta mensagem, o canal WhatsApp esta ok.\n"
                f"Central: {WHATSAPP_TELEFONE_CENTRAL}"
            )            
            resultado = whatsapp_service._enviar_mensagem_agora({
                'telefone': telefone,
                'mensagem': mensagem,
                'tipo': 'teste',
                'meta': {'usuario': current_user.username, 'agendamento_id': ''},
            })
            
            if resultado:
                return jsonify({'sucesso': True})
            return jsonify({'sucesso': False, 'erro': 'Falha ao enviar. Verifique WhatsApp Web / Chrome e os logs.'}), 502
            
        except Exception as e:
            return jsonify({'sucesso': False, 'erro': 'Erro interno ao enviar teste.'}), 500
    
    # ===== MÓDULO DE CONTROLE DE COMBUSTÍVEL =====
    @app.route('/combustivel')
    @login_required
    def combustivel_dashboard():
        # Estatísticas gerais
        total_abastecimentos = Abastecimento.query.count()
        gasto_total = db.session.query(db.func.sum(Abastecimento.valor_total)).scalar() or 0
        litros_total = db.session.query(db.func.sum(Abastecimento.litros_abastecidos)).scalar() or 0
        
        # Calcular preço médio
        preco_medio = 0
        if litros_total > 0:
            preco_medio = float(gasto_total) / float(litros_total)
        
        # Abastecimentos recentes (últimos 5)
        abastecimentos_recentes = Abastecimento.query.order_by(
            Abastecimento.data_abastecimento.desc(),
            Abastecimento.hora_abastecimento.desc()
        ).limit(5).all()
        
        # Preparar dados para exibição
        abastecimentos_html = ""
        cards_ab = ""
        if abastecimentos_recentes:
            for ab in abastecimentos_recentes:
                consumo_info = f"{ab.consumo_medio:.1f} km/L" if ab.consumo_medio else "N/A"
                placa = ab.veiculo.placa
                veiculo_meta = f"{ab.veiculo.marca} {ab.veiculo.modelo}"
                data_txt = ab.data_abastecimento.strftime('%d/%m/%Y')
                hora_txt = ab.hora_abastecimento.strftime('%H:%M')
                tipo_txt = ab.tipo_combustivel.title()
                litros_txt = f"{float(ab.litros_abastecidos):.1f}L"
                valor_txt = f"R$ {float(ab.valor_total):.2f}"
                abastecimentos_html += f'''
                <tr>
                    <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                        {html_esc(data_txt)}<br />
                        <small style="color: var(--gray-color);">{html_esc(hora_txt)}</small>
                    </td>
                    <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                        <strong>{html_esc(placa)}</strong><br />
                        <small style="color: var(--gray-color);">{html_esc(veiculo_meta)}</small>
                    </td>
                    <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                        {html_esc(tipo_txt)}
                    </td>
                    <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                        {litros_txt}
                    </td>
                    <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                        <strong style="color: var(--danger-color);">{valor_txt}</strong>
                    </td>
                    <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">
                        {html_esc(consumo_info)}
                    </td>
                </tr>
                '''
                cards_ab += html_mobile_card(
                    title=placa,
                    meta=f"{html_esc(data_txt)} {html_esc(hora_txt)}",
                    rows=[
                        ('Veículo', html_esc(veiculo_meta)),
                        ('Tipo', html_esc(tipo_txt)),
                        ('Litros', litros_txt),
                        ('Valor', f'<strong style="color: var(--danger-color);">{valor_txt}</strong>'),
                        ('Consumo', html_esc(consumo_info)),
                    ],
                )
        
        conteudo = f'''
        <div class="page-header">
            <h2>⛽ Controle de Combustível</h2>
            <p>Gestão completa de abastecimentos e consumo da frota</p>
            <div style="margin-top: 1rem;">
                <a href="{url_for('combustivel_abastecimento')}" class="btn btn-success">⛽ Registrar Abastecimento</a>
                <a href="{url_for('combustivel_relatorio')}" class="btn">📊 Relatórios</a>
                <a href="{url_for('combustivel_dashboard')}" class="btn btn-secondary">📈 Análises</a>
            </div>
        </div>
        
        <!-- Estatísticas Principais -->
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 1rem; margin-bottom: 2rem;">
            <div class="card" style="text-align: center; padding: 1.5rem;">
                <h3 style="color: var(--primary-color); margin: 0 0 0.5rem 0;">📊 Total Abastecimentos</h3>
                <div style="font-size: 2.5rem; font-weight: bold; color: var(--text-color);">{total_abastecimentos}</div>
                <small style="color: var(--gray-color);">Registros no sistema</small>
            </div>
            <div class="card" style="text-align: center; padding: 1.5rem;">
                <h3 style="color: var(--danger-color); margin: 0 0 0.5rem 0;">💰 Gasto Total</h3>
                <div style="font-size: 2.5rem; font-weight: bold; color: var(--danger-color);">R$ {float(gasto_total):.2f}</div>
                <small style="color: var(--gray-color);">Investimento em combustível</small>
            </div>
            <div class="card" style="text-align: center; padding: 1.5rem;">
                <h3 style="color: var(--warning-color); margin: 0 0 0.5rem 0;">⛽ Total Litros</h3>
                <div style="font-size: 2.5rem; font-weight: bold; color: var(--warning-color);">{float(litros_total):.1f}L</div>
                <small style="color: var(--gray-color);">Volume consumido</small>
            </div>
            <div class="card" style="text-align: center; padding: 1.5rem;">
                <h3 style="color: var(--success-color); margin: 0 0 0.5rem 0;">💵 Preço Médio</h3>
                <div style="font-size: 2.5rem; font-weight: bold; color: var(--success-color);">R$ {preco_medio:.2f}</div>
                <small style="color: var(--gray-color);">Por litro</small>
            </div>
        </div>
        
        <!-- Abastecimentos Recentes -->
        <div class="card">
            <h3 style="color: var(--primary-color); margin-bottom: 1.5rem;">📋 Abastecimentos Recentes</h3>
            
            {f'''
            <div class="stp-list-desktop table-container">
                <table style="width: 100%; border-collapse: collapse;">
                    <thead>
                        <tr style="background: var(--color-95);">
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Data/Hora</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Veículo</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Tipo</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Litros</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Valor</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 2px solid var(--primary-color);">Consumo</th>
                        </tr>
                    </thead>
                    <tbody>
                        {abastecimentos_html}
                    </tbody>
                </table>
            </div>
            <div class="stp-list-mobile">{cards_ab}</div>
            
            <div style="text-align: center; margin-top: 1.5rem;">
                <a href="{url_for('combustivel_relatorio')}" class="btn">📊 Ver Todos os Abastecimentos</a>
            </div>
            ''' if abastecimentos_recentes else '''
            <div style="text-align: center; padding: 4rem 2rem;">
                <div style="font-size: 4rem; margin-bottom: 1rem; color: var(--primary-color);">⛽</div>
                <h3 style="color: var(--text-color); margin-bottom: 1rem;">Nenhum abastecimento registrado</h3>
                <p style="color: var(--gray-color); margin-bottom: 2rem;">Comece registrando o primeiro abastecimento da frota!</p>
                <a href="{url_for('combustivel_abastecimento')}" class="btn btn-success">⛽ Registrar Primeiro Abastecimento</a>
            </div>
            '''}
        </div>
        
        <!-- Ações Rápidas -->
        <div class="card">
            <h3 style="color: var(--info-color); margin-bottom: 1.5rem;">⚡ Ações Rápidas</h3>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem;">
                <a href="{url_for('combustivel_abastecimento')}" class="btn btn-success" style="text-decoration: none; padding: 1rem; text-align: center;">
                    <div style="font-size: 2rem; margin-bottom: 0.5rem;">⛽</div>
                    <strong>Novo Abastecimento</strong><br />
                    <small>Registrar consumo</small>
                </a>
                <a href="{url_for('combustivel_relatorio')}" class="btn" style="text-decoration: none; padding: 1rem; text-align: center;">
                    <div style="font-size: 2rem; margin-bottom: 0.5rem;">📊</div>
                    <strong>Relatórios</strong><br />
                    <small>Análise detalhada</small>
                </a>
                <a href="{url_for('combustivel_dashboard')}" class="btn btn-secondary" style="text-decoration: none; padding: 1rem; text-align: center;">
                    <div style="font-size: 2rem; margin-bottom: 0.5rem;">📈</div>
                    <strong>Análises</strong><br />
                    <small>Tendências e insights</small>
                </a>
                <a href="{url_for('veiculos')}" class="btn" style="text-decoration: none; padding: 1rem; text-align: center;">
                    <div style="font-size: 2rem; margin-bottom: 0.5rem;">🚗</div>
                    <strong>Gerenciar Frota</strong><br />
                    <small>Veículos e motoristas</small>
                </a>
            </div>
         </div>
         '''
        
        return gerar_layout_base("Controle de Combustível", conteudo, "combustivel")    
    
    @app.route('/combustivel/abastecimento', methods=['GET', 'POST'])
    @login_required
    def combustivel_abastecimento():
        if request.method == 'POST':
            try:
                # Extrair dados do formulário
                veiculo_id = int(request.form.get('veiculo_id', 0))
                data_abastecimento = request.form.get('data_abastecimento')
                hora_abastecimento = request.form.get('hora_abastecimento')
                km_atual = int(request.form.get('km_atual', 0))
                tipo_combustivel = request.form.get('tipo_combustivel', '').strip()
                litros_abastecidos = float(request.form.get('litros_abastecidos', 0))
                valor_litro = float(request.form.get('valor_litro', 0))
                valor_total = float(request.form.get('valor_total', 0))
                posto_nome = request.form.get('posto_nome', '').strip()
                posto_endereco = request.form.get('posto_endereco', '').strip()
                motorista_id = request.form.get('motorista_id')
                tanque_cheio = request.form.get('tanque_cheio') == 'sim'
                comprovante_numero = request.form.get('comprovante_numero', '').strip()
                observacoes = request.form.get('observacoes', '').strip()
                
                # Validação básica
                if not all([veiculo_id, data_abastecimento, hora_abastecimento, km_atual, tipo_combustivel, litros_abastecidos, valor_litro]):
                    flash('Preencha todos os campos obrigatórios!', 'error')
                    return redirect(url_for('combustivel_abastecimento'))
                
                # Converter data e hora
                data_abastecimento = datetime.strptime(data_abastecimento, '%Y-%m-%d').date()
                hora_abastecimento = datetime.strptime(hora_abastecimento, '%H:%M').time()
                
                # Criar novo abastecimento
                abastecimento = Abastecimento(
                    veiculo_id=veiculo_id,
                    data_abastecimento=data_abastecimento,
                    hora_abastecimento=hora_abastecimento,
                    km_atual=km_atual,
                    tipo_combustivel=tipo_combustivel,
                    litros_abastecidos=litros_abastecidos,
                    valor_litro=valor_litro,
                    valor_total=valor_total,
                    posto_nome=posto_nome if posto_nome else None,
                    posto_endereco=posto_endereco if posto_endereco else None,
                    motorista_id=int(motorista_id) if motorista_id else None,
                    tanque_cheio=tanque_cheio,
                    comprovante_numero=comprovante_numero if comprovante_numero else None,
                    observacoes=observacoes if observacoes else None,
                    usuario_cadastro_id=current_user.id
                )
                
                db.session.add(abastecimento)
                db.session.commit()
                
                flash(f'Abastecimento registrado com sucesso! Veículo {abastecimento.veiculo.placa}', 'success')
                return redirect(url_for('combustivel_dashboard'))
                
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao registrar abastecimento: {str(e)}', 'error')
        
        # Buscar dados para selects
        veiculos = Veiculo.query.filter_by(ativo=True).order_by(Veiculo.placa).all()
        motoristas = Motorista.query.filter_by(status='ativo').order_by(Motorista.nome).all()
        
        # Gerar options
        veiculos_options = ""
        for v in veiculos:
            veiculos_options += f'<option value="{v.id}">{v.placa} - {v.marca} {v.modelo}</option>'
        
        motoristas_options = ""
        for m in motoristas:
            motoristas_options += f'<option value="{m.id}">{m.nome}</option>'
        
        # Data e hora atuais
        hoje = date.today().strftime('%Y-%m-%d')
        agora = datetime.now().strftime('%H:%M')
        
        # Gerar alertas
        messages_html = ""
        for category, message in get_flashed_messages(with_categories=True):
            alert_class = f"alert-{category}"
            messages_html += f'<div class="alert {alert_class}">{message}</div>'
        
        conteudo = f'''
        <div class="breadcrumb">
            <a href="{url_for('dashboard')}">Início</a> > 
            <a href="{url_for('combustivel_dashboard')}">Combustível</a> > 
            Registrar Abastecimento
        </div>
        
        <div class="page-header">
            <h2>⛽ Registrar Abastecimento</h2>
            <p>Registre um novo abastecimento de veículo</p>
        </div>
        
        {messages_html}
        
        <div class="card">
            <form method="POST" id="formAbastecimento">
                <!-- Dados Básicos -->
                <div class="form-row">
                    <div class="form-group">
                        <label for="veiculo_id">Veículo *</label>
                        <select id="veiculo_id" name="veiculo_id" required onchange="buscarUltimoKM()">
                            <option value="">Selecione o veículo...</option>
                            {veiculos_options}
                        </select>
                    </div>
                    <div class="form-group">
                        <label for="motorista_id">Motorista</label>
                        <select id="motorista_id" name="motorista_id">
                            <option value="">Selecione o motorista...</option>
                            {motoristas_options}
                        </select>
                    </div>
                </div>
                
                <div class="form-row">
                    <div class="form-group">
                        <label for="data_abastecimento">Data do Abastecimento *</label>
                        <input type="date" id="data_abastecimento" name="data_abastecimento" value="{hoje}" required>
                    </div>
                    <div class="form-group">
                        <label for="hora_abastecimento">Hora do Abastecimento *</label>
                        <input type="time" id="hora_abastecimento" name="hora_abastecimento" value="{agora}" required>
                    </div>
                </div>
                
                <!-- Quilometragem -->
                <div class="form-group">
                    <label for="km_atual">Quilometragem Atual *</label>
                    <input type="number" id="km_atual" name="km_atual" placeholder="Ex: 15000" required>
                    <small id="km_info" style="color: var(--gray-color);">Quilometragem no momento do abastecimento</small>
                </div>
                
                <!-- Dados do Combustível -->
                <div style="background: var(--color-95); padding: 1.5rem; border-radius: 0.5rem; margin: 1rem 0;">
                    <h4 style="color: var(--primary-color); margin-bottom: 1rem;">⛽ Dados do Combustível</h4>
                    
                    <div class="form-row">
                        <div class="form-group">
                            <label for="tipo_combustivel">Tipo de Combustível *</label>
                            <select id="tipo_combustivel" name="tipo_combustivel" required>
                                <option value="">Selecione...</option>
                                <option value="gasolina">Gasolina</option>
                                <option value="etanol">Etanol</option>
                                <option value="diesel">Diesel</option>
                                <option value="gnv">GNV</option>
                                <option value="flex">Flex (Gasolina/Etanol)</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label for="tanque_cheio">Tanque Cheio?</label>
                            <select id="tanque_cheio" name="tanque_cheio">
                                <option value="sim">Sim - Encheu o tanque</option>
                                <option value="nao">Não - Abastecimento parcial</option>
                            </select>
                            <small style="color: var(--info-color);">Importante para cálculo de consumo</small>
                        </div>
                    </div>
                    
                    <div class="form-row">
                        <div class="form-group">
                            <label for="litros_abastecidos">Litros Abastecidos *</label>
                            <input type="number" id="litros_abastecidos" name="litros_abastecidos" step="0.001" placeholder="Ex: 42.550" required onchange="calcularValorTotal()">
                        </div>
                        <div class="form-group">
                            <label for="valor_litro">Valor por Litro (R$) *</label>
                            <input type="number" id="valor_litro" name="valor_litro" step="0.001" placeholder="Ex: 5.299" required onchange="calcularValorTotal()">
                        </div>
                    </div>
                    
                    <div class="form-group">
                        <label for="valor_total">Valor Total (R$) *</label>
                        <input type="number" id="valor_total" name="valor_total" step="0.01" placeholder="Ex: 225.50" required>
                        <small style="color: var(--success-color);">Será calculado automaticamente</small>
                    </div>
                </div>
                
                <!-- Local do Abastecimento -->
                <div style="background: var(--color-95); padding: 1.5rem; border-radius: 0.5rem; margin: 1rem 0;">
                    <h4 style="color: var(--primary-color); margin-bottom: 1rem;">🏪 Local do Abastecimento</h4>
                    
                    <div class="form-group">
                        <label for="posto_nome">Nome do Posto</label>
                        <input type="text" id="posto_nome" name="posto_nome" placeholder="Ex: Posto Shell, Petrobras, etc.">
                    </div>
                    
                    <div class="form-group">
                        <label for="posto_endereco">Endereço do Posto</label>
                        <input type="text" id="posto_endereco" name="posto_endereco" placeholder="Rua, bairro, cidade">
                    </div>
                    
                    <div class="form-group">
                        <label for="comprovante_numero">Número do Comprovante</label>
                        <input type="text" id="comprovante_numero" name="comprovante_numero" placeholder="Número da nota fiscal">
                    </div>
                </div>
                
                <div class="form-group">
                    <label for="observacoes">Observações</label>
                    <textarea id="observacoes" name="observacoes" rows="3" placeholder="Informações adicionais sobre o abastecimento"></textarea>
                </div>
                
                <div style="margin-top: 2rem;">
                    <button type="submit" class="btn btn-success">⛽ Registrar Abastecimento</button>
                    <a href="{url_for('combustivel_dashboard')}" class="btn btn-secondary" style="margin-left: 1rem;">❌ Cancelar</a>
                </div>
            </form>
        </div>
        <script>
            function calcularValorTotal() {{
                const litros = parseFloat(document.getElementById('litros_abastecidos').value) || 0;
                const valorLitro = parseFloat(document.getElementById('valor_litro').value) || 0;
                
                if (litros > 0 && valorLitro > 0) {{
                    const valorTotal = litros * valorLitro;
                    document.getElementById('valor_total').value = valorTotal.toFixed(2);
                }}
            }}

            // Buscar último KM diretamente da API
            async function buscarUltimoKM() {{
                const veiculoId = document.getElementById('veiculo_id').value;
                if (!veiculoId) return;
                
                const kmInfo = document.getElementById('km_info');
                kmInfo.textContent = '🔍 Buscando último KM...';
                kmInfo.style.color = 'var(--primary-color)';
                
                try {{
                    const response = await fetch(`/transporte/api/veiculo/${{veiculoId}}/ultimo-km`);
                    const data = await response.json();
                    
                    if (data.sucesso && data.ultimo_km > 0) {{
                        document.getElementById('km_atual').value = data.ultimo_km;
                        kmInfo.textContent = `✅ ${{data.fonte}} - KM: ${{data.ultimo_km.toLocaleString()}}`;
                        kmInfo.style.color = 'var(--success-color)';
                    }} else {{
                        kmInfo.textContent = 'ℹ️ Nenhum registro anterior encontrado';
                        kmInfo.style.color = 'var(--gray-color)';
                    }}
                }} catch (error) {{
                    console.error('Erro ao buscar KM:', error);
                    kmInfo.textContent = '⚠️ Erro ao buscar último KM';
                    kmInfo.style.color = 'var(--warning-color)';
                }}
            }}

            // Auto-calcular ao digitar
            document.getElementById('litros_abastecidos').addEventListener('input', calcularValorTotal);
            document.getElementById('valor_litro').addEventListener('input', calcularValorTotal);
        </script>          
        '''
        
        return gerar_layout_base("Registrar Abastecimento", conteudo, "combustivel")
        
    @app.route('/combustivel/relatorio')
    @login_required
    def combustivel_relatorio():
        # Filtros da URL
        data_inicio_raw = request.args.get('data_inicio', '').strip()
        data_fim_raw = request.args.get('data_fim', '').strip()
        veiculo_filtro = request.args.get('veiculo', '')
        tipo_filtro = request.args.get('tipo', '')
        
        d_ini = parse_data_br(data_inicio_raw) or (date.today() - timedelta(days=30))
        d_fim = parse_data_br(data_fim_raw) or date.today()
        data_inicio = format_data_br(d_ini)
        data_fim = format_data_br(d_fim)
        
        # Query base
        query = Abastecimento.query.join(Veiculo).join(Motorista, isouter=True)
        
        # Aplicar filtros
        if d_ini and d_fim:
            query = query.filter(Abastecimento.data_abastecimento.between(d_ini, d_fim))
        
        if veiculo_filtro:
            query = query.filter(Abastecimento.veiculo_id == veiculo_filtro)
        
        if tipo_filtro:
            query = query.filter(Abastecimento.tipo_combustivel == tipo_filtro)
        
        # Buscar dados
        abastecimentos = query.order_by(
            Abastecimento.data_abastecimento.desc(),
            Abastecimento.hora_abastecimento.desc()
        ).all()
        
        # Calcular estatísticas
        total_litros = sum([float(ab.litros_abastecidos) for ab in abastecimentos])
        total_valor = sum([float(ab.valor_total) for ab in abastecimentos])
        total_abastecimentos = len(abastecimentos)
        preco_medio = total_valor / total_litros if total_litros > 0 else 0
        
        # Buscar dados para filtros
        veiculos = Veiculo.query.filter_by(ativo=True).order_by(Veiculo.placa).all()
        tipos_combustivel = db.session.query(Abastecimento.tipo_combustivel).distinct().all()
        
        # Gerar options
        veiculos_options = ""
        for v in veiculos:
            selected = "selected" if str(v.id) == veiculo_filtro else ""
            veiculos_options += f'<option value="{v.id}" {selected}>{v.placa} - {v.marca} {v.modelo}</option>'
        
        tipos_options = ""
        for tipo in tipos_combustivel:
            selected = "selected" if tipo[0] == tipo_filtro else ""
            tipos_options += f'<option value="{tipo[0]}" {selected}>{tipo[0].title()}</option>'
        
        # Gerar tabela de abastecimentos
        tabela_html = ""
        cards_rel = ""
        for ab in abastecimentos:
            consumo_txt = f"{ab.consumo_medio:.1f} km/L" if ab.consumo_medio else "-"
            tanque_txt = "Sim" if ab.tanque_cheio else "Não"
            placa = ab.veiculo.placa
            veiculo_meta = f"{ab.veiculo.marca} {ab.veiculo.modelo}"
            data_txt = ab.data_abastecimento.strftime('%d/%m/%Y')
            hora_txt = ab.hora_abastecimento.strftime('%H:%M')
            tipo_txt = ab.tipo_combustivel.title()
            posto_txt = ab.posto_nome or 'N/A'
            motorista_txt = ab.motorista.nome if ab.motorista else 'N/A'
            tabela_html += f'''
            <tr>
                <td>{html_esc(data_txt)}<br><small>{html_esc(hora_txt)}</small></td>
                <td><strong>{html_esc(placa)}</strong><br><small>{html_esc(veiculo_meta)}</small></td>
                <td>{ab.km_atual:,} km</td>
                <td>{html_esc(tipo_txt)}</td>
                <td>{float(ab.litros_abastecidos):.1f}L</td>
                <td>R$ {float(ab.valor_litro):.3f}</td>
                <td><strong>R$ {float(ab.valor_total):.2f}</strong></td>
                <td>{html_esc(posto_txt)}</td>
                <td>{html_esc(motorista_txt)}</td>
                <td>{tanque_txt}</td>
                <td>{html_esc(consumo_txt)}</td>
            </tr>
            '''
            cards_rel += html_mobile_card(
                title=placa,
                meta=f"{html_esc(data_txt)} {html_esc(hora_txt)}",
                rows=[
                    ('Veículo', html_esc(veiculo_meta)),
                    ('KM', f"{ab.km_atual:,} km"),
                    ('Tipo', html_esc(tipo_txt)),
                    ('Litros', f"{float(ab.litros_abastecidos):.1f}L"),
                    ('R$/L', f"R$ {float(ab.valor_litro):.3f}"),
                    ('Total', f"<strong>R$ {float(ab.valor_total):.2f}</strong>"),
                    ('Posto', html_esc(posto_txt)),
                    ('Motorista', html_esc(motorista_txt)),
                    ('Tanque', tanque_txt),
                    ('Consumo', html_esc(consumo_txt)),
                ],
            )
        
        # Seção condicional da tabela
        tabela_secao = ""
        if abastecimentos:
            tabela_secao = f'''
            <div class="stp-list-desktop table-container">
                <table style="width: 100%; border-collapse: collapse;">
                    <thead>
                        <tr style="background: var(--color-95);">
                            <th style="padding: 0.5rem; text-align: left;">Data/Hora</th>
                            <th style="padding: 0.5rem; text-align: left;">Veículo</th>
                            <th style="padding: 0.5rem; text-align: left;">KM</th>
                            <th style="padding: 0.5rem; text-align: left;">Tipo</th>
                            <th style="padding: 0.5rem; text-align: left;">Litros</th>
                            <th style="padding: 0.5rem; text-align: left;">R$/L</th>
                            <th style="padding: 0.5rem; text-align: left;">Total</th>
                            <th style="padding: 0.5rem; text-align: left;">Posto</th>
                            <th style="padding: 0.5rem; text-align: left;">Motorista</th>
                            <th style="padding: 0.5rem; text-align: left;">Tanque</th>
                            <th style="padding: 0.5rem; text-align: left;">Consumo</th>
                        </tr>
                    </thead>
                    <tbody>
                        {tabela_html}
                    </tbody>
                </table>
            </div>
            <div class="stp-list-mobile">{cards_rel}</div>
            '''
        else:
            tabela_secao = '''
            <div style="text-align: center; padding: 3rem;">
                <h3>Nenhum abastecimento encontrado</h3>
                <p>Ajuste os filtros para ver os dados</p>
            </div>
            '''
        
        conteudo = f'''
        <div class="page-header">
            <h2>📊 Relatórios de Combustível</h2>
            <p>Análise detalhada dos abastecimentos da frota</p>
        </div>
        
        <!-- Filtros -->
        <div class="filters no-print">
            <form method="GET">
                <div class="filters-row">
                    <div class="form-group">
                        <label>Data início:</label>
                        <input type="text" class="data-br" name="data_inicio" value="{data_inicio}" placeholder="dd/mm/aaaa" maxlength="10">
                    </div>
                    <div class="form-group">
                        <label>Data fim:</label>
                        <input type="text" class="data-br" name="data_fim" value="{data_fim}" placeholder="dd/mm/aaaa" maxlength="10">
                    </div>
                    <div class="form-group">
                        <label>Veículo:</label>
                        <select name="veiculo">
                            <option value="">Todos os veículos</option>
                            {veiculos_options}
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Tipo:</label>
                        <select name="tipo">
                            <option value="">Todos os tipos</option>
                            {tipos_options}
                        </select>
                    </div>
                    <div class="form-group">
                        <button type="submit" class="btn">🔍 Filtrar</button>
                        <button type="button" onclick="window.print()" class="btn">🖨️ Imprimir</button>
                    </div>
                </div>
            </form>
        </div>
        
        <!-- Estatísticas -->
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 2rem;">
            <div class="card" style="text-align: center; padding: 1rem;">
                <h4>📊 Total Abastecimentos</h4>
                <div style="font-size: 1.5rem; font-weight: bold;">{total_abastecimentos}</div>
            </div>
            <div class="card" style="text-align: center; padding: 1rem;">
                <h4>⛽ Total Litros</h4>
                <div style="font-size: 1.5rem; font-weight: bold;">{total_litros:.1f}L</div>
            </div>
            <div class="card" style="text-align: center; padding: 1rem;">
                <h4>💰 Total Gasto</h4>
                <div style="font-size: 1.5rem; font-weight: bold;">R$ {total_valor:.2f}</div>
            </div>
            <div class="card" style="text-align: center; padding: 1rem;">
                <h4>💵 Preço Médio</h4>
                <div style="font-size: 1.5rem; font-weight: bold;">R$ {preco_medio:.2f}/L</div>
            </div>
        </div>
        
        <!-- Tabela -->
        <div class="card">
            <h3>📋 Detalhamento dos Abastecimentos</h3>
            {tabela_secao}
        </div>
        
        <div style="margin-top: 2rem;">
            <a href="{url_for('combustivel_dashboard')}" class="btn btn-secondary">← Voltar ao Início</a>
        </div>
        '''
        
        return gerar_layout_base("Relatórios de Combustível", conteudo, "combustivel")   
            
        
        
    
    
    # ===== API AUXILIAR PARA COMBUSTÍVEL =====
    @app.route('/api/veiculo/<int:veiculo_id>/ultimo-km')
    @login_required
    def api_ultimo_km_veiculo(veiculo_id):
        try:
            # Buscar último KM registrado (abastecimento ou uso)
            ultimo_abastecimento = Abastecimento.query.filter_by(
                veiculo_id=veiculo_id
            ).order_by(Abastecimento.data_abastecimento.desc()).first()
            
            ultimo_uso = UsoVeiculo.query.filter_by(
                veiculo_id=veiculo_id
            ).order_by(UsoVeiculo.data_uso.desc()).first()
            
            ultimo_km = 0
            fonte = "Nenhum registro"
            
            # Verificar qual é o mais recente
            if ultimo_abastecimento and ultimo_uso:
                if ultimo_abastecimento.data_abastecimento >= ultimo_uso.data_uso:
                    ultimo_km = ultimo_abastecimento.km_atual
                    fonte = f"Abastecimento de {ultimo_abastecimento.data_abastecimento.strftime('%d/%m/%Y')}"
                else:
                    ultimo_km = ultimo_uso.km_final or ultimo_uso.km_inicial or 0
                    fonte = f"Uso de {ultimo_uso.data_uso.strftime('%d/%m/%Y')}"
            elif ultimo_abastecimento:
                ultimo_km = ultimo_abastecimento.km_atual
                fonte = f"Abastecimento de {ultimo_abastecimento.data_abastecimento.strftime('%d/%m/%Y')}"
            elif ultimo_uso:
                ultimo_km = ultimo_uso.km_final or ultimo_uso.km_inicial or 0
                fonte = f"Uso de {ultimo_uso.data_uso.strftime('%d/%m/%Y')}"
            
            return jsonify({
                'ultimo_km': ultimo_km,
                'fonte': fonte,
                'sucesso': True
            })
            
        except Exception as e:
            return jsonify({
                'erro': str(e),
                'sucesso': False
            }), 500

    def _fipe_fetch_api(path):
        import json
        import ssl
        import urllib.request
        url = f'https://parallelum.com.br/fipe/api/v1/{path}'
        req = urllib.request.Request(url, headers={'User-Agent': 'STP-SistemaTransporte/1.0'})
        try:
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=25, context=ctx) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception:
            ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(req, timeout=25, context=ctx) as resp:
                return json.loads(resp.read().decode('utf-8'))

    @app.route('/api/fipe/<tipo>/marcas')
    @login_required
    def api_fipe_marcas(tipo):
        if tipo not in ('carros', 'motos', 'caminhoes'):
            return jsonify({'erro': 'Tipo inválido'}), 400
        try:
            return jsonify(_fipe_fetch_api(f'{tipo}/marcas'))
        except Exception as e:
            return jsonify({'erro': str(e)}), 502

    @app.route('/api/fipe/<tipo>/marcas/<cod_marca>/modelos')
    @login_required
    def api_fipe_modelos(tipo, cod_marca):
        if tipo not in ('carros', 'motos', 'caminhoes'):
            return jsonify({'erro': 'Tipo inválido'}), 400
        try:
            return jsonify(_fipe_fetch_api(f'{tipo}/marcas/{cod_marca}/modelos'))
        except Exception as e:
            return jsonify({'erro': str(e)}), 502

    @app.route('/api/fipe/<tipo>/marcas/<cod_marca>/modelos/<cod_modelo>/anos')
    @login_required
    def api_fipe_anos(tipo, cod_marca, cod_modelo):
        if tipo not in ('carros', 'motos', 'caminhoes'):
            return jsonify({'erro': 'Tipo inválido'}), 400
        try:
            return jsonify(_fipe_fetch_api(f'{tipo}/marcas/{cod_marca}/modelos/{cod_modelo}/anos'))
        except Exception as e:
            return jsonify({'erro': str(e)}), 502

    @app.route('/api/fipe/<tipo>/marcas/<cod_marca>/modelos/<cod_modelo>/anos/<path:cod_ano>')
    @login_required
    def api_fipe_detalhe(tipo, cod_marca, cod_modelo, cod_ano):
        if tipo not in ('carros', 'motos', 'caminhoes'):
            return jsonify({'erro': 'Tipo inválido'}), 400
        try:
            from urllib.parse import quote
            cod = quote(cod_ano, safe='')
            return jsonify(_fipe_fetch_api(
                f'{tipo}/marcas/{cod_marca}/modelos/{cod_modelo}/anos/{cod}'
            ))
        except Exception as e:
            return jsonify({'erro': str(e)}), 502
    
    
    
    return app
    
if __name__ == '__main__':
    # Console Windows (cp1252) quebra em emoji sem UTF-8
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            try:
                stream.reconfigure(encoding='utf-8', errors='replace')
            except Exception:
                pass

    print("🚀 Iniciando Sistema de Transporte de Pacientes...")
    
    try:
        app = create_app()
        print("📱 Acesse: http://localhost:5022/transporte")
        print("🏥 Prefeitura Municipal de Cosmópolis")
        print("👤 Login: admin / admin123")
        print("📊 Sistema com prefixo /transporte habilitado!")
        app.run(debug=True, host='0.0.0.0', port=5022, use_reloader=False)
    except Exception as e:
        print(f"❌ Erro ao iniciar aplicação: {e}")
        sys.exit(1)
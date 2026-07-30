#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de Transporte de Pacientes
Desenvolvido para a Prefeitura Municipal de Cosmópolis
Pode ser usado por terceiros autorizados

Arquivo de configuração da aplicação
"""

import os
from datetime import timedelta
from dotenv import load_dotenv

# Carregar variáveis de ambiente do arquivo .env
load_dotenv()

class Config:
    """
    Configuração base da aplicação
    Sistema da Prefeitura Municipal de Cosmópolis
    """
    
    # === CONFIGURAÇÕES BÁSICAS ===
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'cosmopolis-transporte-pacientes-2024-chave-secreta'
    
    # Timezone da aplicação (Brasília)
    TIMEZONE = 'America/Sao_Paulo'
    
    # === CONFIGURAÇÕES DO BANCO DE DADOS ===
    # SQLite para desenvolvimento, preparado para PostgreSQL/MySQL em produção
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(os.path.abspath(os.path.dirname(__file__)), 'db', 'sistema_transporte.db')
    
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = os.environ.get('SQLALCHEMY_ECHO', 'False').lower() == 'true'
    
    # Pool de conexões (importante para PostgreSQL/MySQL)
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': int(os.environ.get('DB_POOL_SIZE', '10')),
        'pool_timeout': int(os.environ.get('DB_POOL_TIMEOUT', '20')),
        'pool_recycle': int(os.environ.get('DB_POOL_RECYCLE', '3600')),
        'max_overflow': int(os.environ.get('DB_MAX_OVERFLOW', '20'))
    }
    
    # === CONFIGURAÇÕES DE SESSÃO E AUTENTICAÇÃO ===
    SESSION_TYPE = 'filesystem'
    SESSION_PERMANENT = True
    PERMANENT_SESSION_LIFETIME = timedelta(hours=int(os.environ.get('SESSION_HOURS', '8')))
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'False').lower() == 'true'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    
    # JWT para API (futuro)
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY') or SECRET_KEY
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=int(os.environ.get('JWT_HOURS', '1')))
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=int(os.environ.get('JWT_REFRESH_DAYS', '30')))
    
    # === CONFIGURAÇÕES DE UPLOAD ===
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_UPLOAD_SIZE', '16')) * 1024 * 1024  # MB
    UPLOAD_FOLDER = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'uploads')
    ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx', 'xls', 'xlsx'}
    
    # === CONFIGURAÇÕES DE RELATÓRIOS ===
    REPORTS_FOLDER = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'relatorios')
    REPORTS_FORMATS = ['pdf', 'excel', 'csv']
    
    # === CONFIGURAÇÕES DE EMAIL (futuro) ===
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', '587'))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'True').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', 'noreply@cosmopolis.sp.gov.br')
    
    # === CONFIGURAÇÕES DE SEGURANÇA ===
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = int(os.environ.get('CSRF_TIME_LIMIT', '3600'))
    
    # === CONFIGURAÇÕES DE PAGINAÇÃO ===
    ITEMS_PER_PAGE = int(os.environ.get('ITEMS_PER_PAGE', '10'))
    MAX_ITEMS_PER_PAGE = int(os.environ.get('MAX_ITEMS_PER_PAGE', '100'))
    
    # === CONFIGURAÇÕES DO SISTEMA ===
    SISTEMA_NOME = 'Sistema de Transporte de Pacientes'
    SISTEMA_VERSAO = '1.0.0'
    MUNICIPIO = 'Cosmópolis'
    ESTADO = 'São Paulo'
    
    # === CONFIGURAÇÕES DE AGENDAMENTO ===
    # Horário de funcionamento do transporte
    HORARIO_INICIO = os.environ.get('HORARIO_INICIO', '06:00')
    HORARIO_FIM = os.environ.get('HORARIO_FIM', '18:00')
    
    # Dias da semana de funcionamento (0=Segunda, 6=Domingo)
    DIAS_FUNCIONAMENTO = [0, 1, 2, 3, 4]  # Segunda a Sexta
    
    # Antecedência mínima para agendamento (horas)
    ANTECEDENCIA_MINIMA = int(os.environ.get('ANTECEDENCIA_MINIMA', '24'))
    
    # Tempo máximo de viagem por agendamento (minutos)
    TEMPO_VIAGEM_MAXIMO = int(os.environ.get('TEMPO_VIAGEM_MAXIMO', '480'))  # 8 horas
    
    @staticmethod
    def init_app(app):
        """Inicialização específica da aplicação"""
        # Criar diretórios necessários
        os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
        os.makedirs(Config.REPORTS_FOLDER, exist_ok=True)
        os.makedirs(os.path.dirname(Config.SQLALCHEMY_DATABASE_URI.replace('sqlite:///', '')), exist_ok=True)

class DevelopmentConfig(Config):
    """
    Configuração para ambiente de desenvolvimento
    """
    DEBUG = True
    TESTING = False
    
    # Logs mais verbosos em desenvolvimento
    SQLALCHEMY_ECHO = True
    
    # Configurações menos restritivas para desenvolvimento
    SESSION_COOKIE_SECURE = False
    WTF_CSRF_ENABLED = False  # Desabilitar CSRF em desenvolvimento para facilitar testes

class ProductionConfig(Config):
    """
    Configuração para ambiente de produção
    Uso em produção pela Prefeitura Municipal de Cosmópolis
    """
    DEBUG = False
    TESTING = False
    
    # Forçar HTTPS em produção
    SESSION_COOKIE_SECURE = True
    PREFERRED_URL_SCHEME = 'https'
    
    # Configurações mais restritivas para produção
    WTF_CSRF_ENABLED = True
    
    # Log de erros em produção
    LOG_TO_STDOUT = os.environ.get('LOG_TO_STDOUT', 'True').lower() == 'true'
    
    @classmethod
    def init_app(cls, app):
        """Configurações específicas para produção"""
        Config.init_app(app)
        
        # Log de erros para arquivo em produção
        if not app.debug and not app.testing:
            import logging
            from logging.handlers import RotatingFileHandler
            
            # Criar diretório de logs
            log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
            os.makedirs(log_dir, exist_ok=True)
            
            # Configurar handler de arquivo
            file_handler = RotatingFileHandler(
                os.path.join(log_dir, 'sistema_transporte.log'),
                maxBytes=10240000,  # 10MB
                backupCount=10
            )
            file_handler.setFormatter(logging.Formatter(
                '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
            ))
            file_handler.setLevel(logging.INFO)
            app.logger.addHandler(file_handler)
            
            app.logger.setLevel(logging.INFO)
            app.logger.info(f'{Config.SISTEMA_NOME} - {Config.MUNICIPIO} iniciado')

class TestingConfig(Config):
    """
    Configuração para ambiente de testes
    """
    TESTING = True
    DEBUG = True
    
    # Banco em memória para testes
    SQLALCHEMY_DATABASE_URI = 'sqlite:///db/transporte_pacientes.db'
    
    # Desabilitar CSRF para testes
    WTF_CSRF_ENABLED = False
    
    # Configurações para testes mais rápidos
    SQLALCHEMY_ECHO = False

# Dicionário de configurações disponíveis
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}

def get_config():
    """
    Retorna a configuração baseada na variável de ambiente FLASK_ENV
    """
    env = os.environ.get('FLASK_ENV', 'development')
    return config.get(env, config['default'])

# === CONFIGURAÇÕES ESPECÍFICAS DO NEGÓCIO ===
class BusinessConfig:
    """
    Configurações específicas das regras de negócio
    Sistema da Prefeitura Municipal de Cosmópolis
    """
    
    # Tipos de usuário do sistema
    TIPOS_USUARIO = {
        'admin': 'Administrador',
        'operador': 'Operador',
        'consulta': 'Consulta'
    }
    
    # Tipos de exame/consulta
    TIPOS_ATENDIMENTO = {
        'exame': 'Exame',
        'consulta': 'Consulta Médica',
        'procedimento': 'Procedimento',
        'retorno': 'Retorno'
    }
    
    # Status dos agendamentos
    STATUS_AGENDAMENTO = {
        'agendado': 'Agendado',
        'confirmado': 'Confirmado',
        'em_andamento': 'Em Andamento',
        'concluido': 'Concluído',
        'cancelado': 'Cancelado',
        'nao_compareceu': 'Não Compareceu'
    }
    
    # Prioridades de atendimento
    PRIORIDADES = {
        'baixa': 'Baixa',
        'normal': 'Normal',
        'alta': 'Alta',
        'urgente': 'Urgente'
    }
    
    # Tipos de veículo
    TIPOS_VEICULO = {
        'van': 'Van',
        'micro_onibus': 'Micro-ônibus',
        'ambulancia': 'Ambulância',
        'veiculo_comum': 'Veículo Comum'
    }
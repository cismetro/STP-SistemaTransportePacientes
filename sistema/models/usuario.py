#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de Transporte de Pacientes
Desenvolvido para a Prefeitura Municipal de Cosmópolis
Pode ser usado por terceiros autorizados

Modelo: Usuario
Representa os usuários do sistema (autenticação e autorização)
"""

from datetime import datetime, date, timedelta
from sqlalchemy import Column, Integer, String, Text, Date, DateTime, Boolean
from sqlalchemy.orm import validates
from sqlalchemy.ext.hybrid import hybrid_property
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
import re
import secrets

from db.database import db

class Usuario(UserMixin, db.Model):
    """
    Modelo de Usuário
    Sistema da Prefeitura Municipal de Cosmópolis
    
    Representa um usuário do sistema com autenticação e autorização
    """
    
    __tablename__ = 'usuarios'
    
    # === CAMPOS PRINCIPAIS ===
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Dados pessoais
    nome = Column(String(200), nullable=False, index=True)
    cpf = Column(String(14), unique=True, nullable=False, index=True)
    email = Column(String(120), unique=True, nullable=True, index=True)
    telefone = Column(String(20), nullable=True)
    
    # Dados de autenticação
    login = Column(String(50), unique=True, nullable=False, index=True)
    senha_hash = Column(String(255), nullable=False)
    
    # Controle de acesso
    tipo_usuario = Column(String(20), nullable=False, default='consulta', index=True)
    # admin, operador, consulta
    
    # Permissões específicas
    pode_criar_agendamentos = Column(Boolean, default=True, nullable=False)
    pode_editar_agendamentos = Column(Boolean, default=True, nullable=False)
    pode_cancelar_agendamentos = Column(Boolean, default=True, nullable=False)
    pode_gerenciar_pacientes = Column(Boolean, default=True, nullable=False)
    pode_gerenciar_motoristas = Column(Boolean, default=False, nullable=False)
    pode_gerenciar_veiculos = Column(Boolean, default=False, nullable=False)
    pode_gerenciar_usuarios = Column(Boolean, default=False, nullable=False)
    pode_gerar_relatorios = Column(Boolean, default=True, nullable=False)
    pode_visualizar_dashboard = Column(Boolean, default=True, nullable=False)
    
    # Informações profissionais
    cargo = Column(String(100), nullable=True)
    setor = Column(String(100), nullable=True)
    departamento = Column(String(100), nullable=True, default='Secretaria de Saúde')
    
    # Controle de sessão
    ultimo_login = Column(DateTime, nullable=True)
    ultimo_ip = Column(String(45), nullable=True)  # IPv6
    tentativas_login = Column(Integer, default=0, nullable=False)
    bloqueado_ate = Column(DateTime, nullable=True)
    
    # Segurança
    token_recuperacao = Column(String(100), nullable=True)
    token_expiracao = Column(DateTime, nullable=True)
    deve_trocar_senha = Column(Boolean, default=True, nullable=False)
    data_troca_senha = Column(DateTime, nullable=True)
    
    # Status
    ativo = Column(Boolean, default=True, nullable=False, index=True)
    primeiro_acesso = Column(Boolean, default=True, nullable=False)
    observacoes = Column(Text, nullable=True)
    
    # Timestamps
    data_cadastro = Column(DateTime, default=datetime.utcnow, nullable=False)
    data_atualizacao = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # === PROPRIEDADES CALCULADAS ===
    @hybrid_property
    def cpf_formatado(self):
        """Retorna o CPF formatado"""
        if self.cpf and len(self.cpf) == 11:
            return f"{self.cpf[:3]}.{self.cpf[3:6]}.{self.cpf[6:9]}-{self.cpf[9:]}"
        return self.cpf
    
    @hybrid_property
    def telefone_formatado(self):
        """Retorna o telefone formatado"""
        if self.telefone:
            numeros = re.sub(r'\D', '', self.telefone)
            if len(numeros) == 11:  # Celular
                return f"({numeros[:2]}) {numeros[2:7]}-{numeros[7:]}"
            elif len(numeros) == 10:  # Fixo
                return f"({numeros[:2]}) {numeros[2:6]}-{numeros[6:]}"
        return self.telefone
    
    @hybrid_property
    def eh_admin(self):
        """Verifica se é administrador"""
        return self.tipo_usuario == 'admin'
    
    @hybrid_property
    def eh_operador(self):
        """Verifica se é operador"""
        return self.tipo_usuario == 'operador'
    
    @hybrid_property
    def pode_administrar(self):
        """Verifica se tem privilégios administrativos"""
        return self.eh_admin or self.pode_gerenciar_usuarios
    
    @hybrid_property
    def esta_bloqueado(self):
        """Verifica se a conta está bloqueada"""
        if self.bloqueado_ate:
            return datetime.utcnow() < self.bloqueado_ate
        return False
    
    @hybrid_property
    def senha_vencida(self):
        """Verifica se a senha está vencida (90 dias)"""
        if not self.data_troca_senha:
            return True
        
        dias_senha = (datetime.utcnow() - self.data_troca_senha).days
        return dias_senha > 90
    
    @hybrid_property
    def descricao_completa(self):
        """Retorna descrição completa do usuário"""
        desc = f"{self.nome} ({self.login})"
        if self.cargo:
            desc += f" - {self.cargo}"
        return desc
    
    # === VALIDAÇÕES ===
    @validates('cpf')
    def validate_cpf(self, key, cpf):
        """Valida o CPF do usuário"""
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
    
    @validates('nome')
    def validate_nome(self, key, nome):
        """Valida o nome do usuário"""
        if not nome:
            raise ValueError("Nome é obrigatório")
        
        nome = nome.strip()
        if len(nome) < 3:
            raise ValueError("Nome deve ter pelo menos 3 caracteres")
        
        if len(nome) > 200:
            raise ValueError("Nome não pode ter mais de 200 caracteres")
        
        return nome.title()
    
    @validates('login')
    def validate_login(self, key, login):
        """Valida o login do usuário"""
        if not login:
            raise ValueError("Login é obrigatório")
        
        login = login.lower().strip()
        
        if len(login) < 3:
            raise ValueError("Login deve ter pelo menos 3 caracteres")
        
        if len(login) > 50:
            raise ValueError("Login não pode ter mais de 50 caracteres")
        
        # Verificar caracteres válidos
        if not re.match(r'^[a-z0-9._-]+$', login):
            raise ValueError("Login pode conter apenas letras minúsculas, números, pontos, traços e sublinhados")
        
        return login
    
    @validates('email')
    def validate_email(self, key, email):
        """Valida o email do usuário"""
        if not email:
            return email
        
        email = email.strip().lower()
        
        # Validação básica de email
        padrao_email = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(padrao_email, email):
            raise ValueError("Email inválido")
        
        return email
    
    @validates('telefone')
    def validate_telefone(self, key, telefone):
        """Valida telefone"""
        if not telefone:
            return telefone
        
        numeros = re.sub(r'\D', '', telefone)
        
        if len(numeros) not in [10, 11]:
            raise ValueError("Telefone deve ter 10 ou 11 dígitos")
        
        return numeros
    
    @validates('tipo_usuario')
    def validate_tipo_usuario(self, key, tipo):
        """Valida o tipo de usuário"""
        if not tipo:
            return 'consulta'
        
        tipos_validos = ['admin', 'operador', 'consulta']
        tipo = tipo.lower()
        
        if tipo not in tipos_validos:
            raise ValueError(f"Tipo de usuário deve ser: {', '.join(tipos_validos)}")
        
        return tipo
    
    # === MÉTODOS DE AUTENTICAÇÃO ===
    def set_password(self, senha):
        """Define a senha do usuário"""
        if not senha:
            raise ValueError("Senha é obrigatória")
        
        if len(senha) < 6:
            raise ValueError("Senha deve ter pelo menos 6 caracteres")
        
        # Verificar complexidade da senha
        if not self._validar_complexidade_senha(senha):
            raise ValueError("Senha deve conter pelo menos uma letra maiúscula, uma minúscula e um número")
        
        self.senha_hash = generate_password_hash(senha)
        self.data_troca_senha = datetime.utcnow()
        self.deve_trocar_senha = False
    
    def check_password(self, senha):
        """Verifica se a senha está correta"""
        return check_password_hash(self.senha_hash, senha)
    
    def gerar_token_recuperacao(self):
        """Gera token para recuperação de senha"""
        self.token_recuperacao = secrets.token_urlsafe(32)
        self.token_expiracao = datetime.utcnow() + timedelta(hours=24)
        return self.token_recuperacao
    
    def validar_token_recuperacao(self, token):
        """Valida token de recuperação de senha"""
        if not self.token_recuperacao or not self.token_expiracao:
            return False
        
        if datetime.utcnow() > self.token_expiracao:
            return False
        
        return self.token_recuperacao == token
    
    def resetar_senha_com_token(self, token, nova_senha):
        """Reseta senha usando token de recuperação"""
        if not self.validar_token_recuperacao(token):
            raise ValueError("Token inválido ou expirado")
        
        self.set_password(nova_senha)
        self.token_recuperacao = None
        self.token_expiracao = None
        self.tentativas_login = 0
        self.bloqueado_ate = None
    
    # === MÉTODOS DE CONTROLE DE ACESSO ===
    def registrar_login(self, ip_address=None):
        """Registra login bem-sucedido"""
        self.ultimo_login = datetime.utcnow()
        self.ultimo_ip = ip_address
        self.tentativas_login = 0
        self.bloqueado_ate = None
        self.primeiro_acesso = False
    
    def registrar_tentativa_login_falha(self):
        """Registra tentativa de login falhada"""
        self.tentativas_login += 1
        
        # Bloquear após 5 tentativas
        if self.tentativas_login >= 5:
            self.bloqueado_ate = datetime.utcnow() + timedelta(minutes=30)
    
    def desbloquear_conta(self):
        """Desbloqueia a conta do usuário"""
        self.tentativas_login = 0
        self.bloqueado_ate = None
    
    def definir_permissoes_por_tipo(self):
        """Define permissões baseadas no tipo de usuário"""
        if self.tipo_usuario == 'admin':
            # Administrador tem todas as permissões
            self.pode_criar_agendamentos = True
            self.pode_editar_agendamentos = True
            self.pode_cancelar_agendamentos = True
            self.pode_gerenciar_pacientes = True
            self.pode_gerenciar_motoristas = True
            self.pode_gerenciar_veiculos = True
            self.pode_gerenciar_usuarios = True
            self.pode_gerar_relatorios = True
            self.pode_visualizar_dashboard = True
            
        elif self.tipo_usuario == 'operador':
            # Operador tem permissões operacionais
            self.pode_criar_agendamentos = True
            self.pode_editar_agendamentos = True
            self.pode_cancelar_agendamentos = True
            self.pode_gerenciar_pacientes = True
            self.pode_gerenciar_motoristas = False
            self.pode_gerenciar_veiculos = False
            self.pode_gerenciar_usuarios = False
            self.pode_gerar_relatorios = True
            self.pode_visualizar_dashboard = True
            
        elif self.tipo_usuario == 'consulta':
            # Usuário de consulta tem permissões limitadas
            self.pode_criar_agendamentos = False
            self.pode_editar_agendamentos = False
            self.pode_cancelar_agendamentos = False
            self.pode_gerenciar_pacientes = False
            self.pode_gerenciar_motoristas = False
            self.pode_gerenciar_veiculos = False
            self.pode_gerenciar_usuarios = False
            self.pode_gerar_relatorios = True
            self.pode_visualizar_dashboard = True
    
    # === MÉTODOS DE VERIFICAÇÃO DE PERMISSÃO ===
    def pode_acessar_modulo(self, modulo):
        """Verifica se pode acessar determinado módulo"""
        if not self.ativo or self.esta_bloqueado:
            return False
        
        permissoes = {
            'agendamentos': self.pode_criar_agendamentos or self.pode_editar_agendamentos,
            'pacientes': self.pode_gerenciar_pacientes,
            'motoristas': self.pode_gerenciar_motoristas,
            'veiculos': self.pode_gerenciar_veiculos,
            'usuarios': self.pode_gerenciar_usuarios,
            'relatorios': self.pode_gerar_relatorios,
            'dashboard': self.pode_visualizar_dashboard
        }
        
        return permissoes.get(modulo, False)
    
    def pode_realizar_acao(self, acao, modulo=None):
        """Verifica se pode realizar determinada ação"""
        if not self.ativo or self.esta_bloqueado:
            return False
        
        if self.eh_admin:
            return True
        
        acoes_permissoes = {
            'criar_agendamento': self.pode_criar_agendamentos,
            'editar_agendamento': self.pode_editar_agendamentos,
            'cancelar_agendamento': self.pode_cancelar_agendamentos,
            'gerenciar_pacientes': self.pode_gerenciar_pacientes,
            'gerenciar_motoristas': self.pode_gerenciar_motoristas,
            'gerenciar_veiculos': self.pode_gerenciar_veiculos,
            'gerenciar_usuarios': self.pode_gerenciar_usuarios,
            'gerar_relatorios': self.pode_gerar_relatorios
        }
        
        return acoes_permissoes.get(acao, False)
    
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
    
    def _validar_complexidade_senha(self, senha):
        """Valida complexidade da senha"""
        # Pelo menos uma letra maiúscula
        if not re.search(r'[A-Z]', senha):
            return False
        
        # Pelo menos uma letra minúscula
        if not re.search(r'[a-z]', senha):
            return False
        
        # Pelo menos um número
        if not re.search(r'\d', senha):
            return False
        
        return True
    
    # === MÉTODOS DO MODELO ===
    def to_dict(self, incluir_sensivel=False):
        """Converte o modelo para dicionário"""
        dados = {
            'id': self.id,
            'nome': self.nome,
            'cpf': self.cpf_formatado,
            'email': self.email,
            'telefone': self.telefone_formatado,
            'login': self.login,
            'tipo_usuario': self.tipo_usuario.title(),
            'cargo': self.cargo,
            'setor': self.setor,
            'departamento': self.departamento,
            'ultimo_login': self.ultimo_login.strftime('%d/%m/%Y %H:%M') if self.ultimo_login else 'Nunca',
            'ativo': self.ativo,
            'primeiro_acesso': self.primeiro_acesso,
            'deve_trocar_senha': self.deve_trocar_senha,
            'senha_vencida': self.senha_vencida,
            'esta_bloqueado': self.esta_bloqueado,
            'permissoes': {
                'pode_criar_agendamentos': self.pode_criar_agendamentos,
                'pode_editar_agendamentos': self.pode_editar_agendamentos,
                'pode_cancelar_agendamentos': self.pode_cancelar_agendamentos,
                'pode_gerenciar_pacientes': self.pode_gerenciar_pacientes,
                'pode_gerenciar_motoristas': self.pode_gerenciar_motoristas,
                'pode_gerenciar_veiculos': self.pode_gerenciar_veiculos,
                'pode_gerenciar_usuarios': self.pode_gerenciar_usuarios,
                'pode_gerar_relatorios': self.pode_gerar_relatorios,
                'pode_visualizar_dashboard': self.pode_visualizar_dashboard
            },
            'data_cadastro': self.data_cadastro.strftime('%d/%m/%Y %H:%M') if self.data_cadastro else None
        }
        
        if incluir_sensivel:
            dados.update({
                'tentativas_login': self.tentativas_login,
                'bloqueado_ate': self.bloqueado_ate.strftime('%d/%m/%Y %H:%M') if self.bloqueado_ate else None,
                'ultimo_ip': self.ultimo_ip,
                'token_recuperacao': bool(self.token_recuperacao),
                'observacoes': self.observacoes
            })
        
        return dados
    
    def __repr__(self):
        """Representação string do modelo"""
        return f'<Usuario {self.login} - {self.nome}>'
    
    def __str__(self):
        """String amigável do modelo"""
        return self.descricao_completa
    
    # === MÉTODOS DE CLASSE ===
    @classmethod
    def buscar_por_login(cls, login):
        """Busca usuário pelo login"""
        return cls.query.filter_by(login=login.lower()).first()
    
    @classmethod
    def buscar_por_email(cls, email):
        """Busca usuário pelo email"""
        return cls.query.filter_by(email=email.lower()).first()
    
    @classmethod
    def buscar_por_cpf(cls, cpf):
        """Busca usuário pelo CPF"""
        cpf_numeros = re.sub(r'\D', '', cpf)
        return cls.query.filter_by(cpf=cpf_numeros).first()
    
    @classmethod
    def usuarios_ativos(cls):
        """Retorna query de usuários ativos"""
        return cls.query.filter_by(ativo=True)
    
    @classmethod
    def administradores(cls):
        """Retorna usuários administradores"""
        return cls.query.filter_by(tipo_usuario='admin', ativo=True)
    
    @classmethod
    def usuarios_bloqueados(cls):
        """Retorna usuários bloqueados"""
        agora = datetime.utcnow()
        return cls.query.filter(
            cls.bloqueado_ate != None,
            cls.bloqueado_ate > agora
        )
    
    @classmethod
    def senhas_vencidas(cls):
        """Retorna usuários com senhas vencidas"""
        data_limite = datetime.utcnow() - timedelta(days=90)
        return cls.query.filter(
            cls.ativo == True,
            db.or_(
                cls.data_troca_senha == None,
                cls.data_troca_senha < data_limite
            )
        )
    
    @classmethod
    def criar_usuario_admin(cls, nome, login, senha, cpf, email=None):
        """Cria um usuário administrador"""
        usuario = cls(
            nome=nome,
            login=login,
            cpf=cpf,
            email=email,
            tipo_usuario='admin'
        )
        usuario.set_password(senha)
        usuario.definir_permissoes_por_tipo()
        usuario.deve_trocar_senha = False
        usuario.primeiro_acesso = False
        
        return usuario
    
    @classmethod
    def estatisticas(cls):
        """Retorna estatísticas dos usuários"""
        total = cls.query.count()
        ativos = cls.usuarios_ativos().count()
        bloqueados = cls.usuarios_bloqueados().count()
        senhas_vencidas = cls.senhas_vencidas().count()
        admins = cls.administradores().count()
        primeiro_acesso = cls.query.filter_by(primeiro_acesso=True, ativo=True).count()
        
        return {
            'total': total,
            'ativos': ativos,
            'bloqueados': bloqueados,
            'senhas_vencidas': senhas_vencidas,
            'administradores': admins,
            'primeiro_acesso': primeiro_acesso
        }

# Configuração do Flask-Login
def load_user(user_id):
    """Função para carregar usuário para Flask-Login"""
    return Usuario.query.get(int(user_id))
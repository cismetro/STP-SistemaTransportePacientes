#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de Transporte de Pacientes
Desenvolvido para a Prefeitura Municipal de Cosmópolis
Pode ser usado por terceiros autorizados

Utilitários de Autenticação
Funções auxiliares para autenticação e autorização
"""

from functools import wraps
from flask import session, request, redirect, url_for, flash, jsonify, current_app
from flask_login import current_user, login_required
from datetime import datetime, timedelta
import jwt
import secrets
import hashlib
import re
from werkzeug.security import generate_password_hash

def require_permission(permission):
    """
    Decorador para verificar permissões específicas
    Uso: @require_permission('pode_gerenciar_usuarios')
    """
    def decorator(f):
        @wraps(f)
        @login_required
        def decorated_function(*args, **kwargs):
            # Verificar se usuário está ativo
            if not current_user.ativo:
                flash('Sua conta está inativa. Entre em contato com o administrador.', 'error')
                return redirect(url_for('auth.login'))
            
            # Verificar se conta está bloqueada
            if current_user.esta_bloqueado:
                flash('Sua conta está temporariamente bloqueada devido a tentativas de login falhadas.', 'error')
                return redirect(url_for('auth.login'))
            
            # Verificar se deve trocar senha
            if current_user.deve_trocar_senha:
                flash('Você deve trocar sua senha antes de continuar.', 'warning')
                return redirect(url_for('auth.trocar_senha'))
            
            # Verificar se senha está vencida
            if current_user.senha_vencida:
                flash('Sua senha está vencida. É necessário trocar a senha.', 'warning')
                return redirect(url_for('auth.trocar_senha'))
            
            # Verificar permissão específica
            if not hasattr(current_user, permission) or not getattr(current_user, permission):
                flash('Você não tem permissão para acessar esta funcionalidade.', 'error')
                return redirect(url_for('dashboard'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def require_admin():
    """
    Decorador para exigir privilégios de administrador
    """
    def decorator(f):
        @wraps(f)
        @require_permission('pode_gerenciar_usuarios')
        def decorated_function(*args, **kwargs):
            if not current_user.eh_admin:
                flash('Acesso restrito a administradores.', 'error')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def require_module_access(module):
    """
    Decorador para verificar acesso a módulos específicos
    Uso: @require_module_access('pacientes')
    """
    def decorator(f):
        @wraps(f)
        @login_required
        def decorated_function(*args, **kwargs):
            if not current_user.pode_acessar_modulo(module):
                flash(f'Você não tem permissão para acessar o módulo {module}.', 'error')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def api_key_required(f):
    """
    Decorador para rotas de API que exigem chave de API
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        
        if not api_key:
            return jsonify({'error': 'Chave de API é obrigatória'}), 401
        
        # Verificar se a chave é válida (implementar conforme necessário)
        if not validar_api_key(api_key):
            return jsonify({'error': 'Chave de API inválida'}), 401
        
        return f(*args, **kwargs)
    return decorated_function

def jwt_required(f):
    """
    Decorador para rotas que exigem token JWT
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = None
        
        # Verificar header Authorization
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]  # Bearer TOKEN
            except IndexError:
                return jsonify({'error': 'Formato de token inválido'}), 401
        
        if not token:
            return jsonify({'error': 'Token é obrigatório'}), 401
        
        try:
            # Decodificar token
            data = jwt.decode(token, current_app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
            user_id = data['user_id']
            
            # Buscar usuário
            from sistema.models.usuario import Usuario
            current_jwt_user = Usuario.query.get(user_id)
            
            if not current_jwt_user or not current_jwt_user.ativo:
                return jsonify({'error': 'Usuário inválido ou inativo'}), 401
            
            # Adicionar usuário ao contexto da requisição
            request.current_jwt_user = current_jwt_user
            
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token expirado'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Token inválido'}), 401
        
        return f(*args, **kwargs)
    return decorated_function

def gerar_jwt_token(usuario, expiration_hours=1):
    """
    Gera token JWT para usuário
    """
    payload = {
        'user_id': usuario.id,
        'login': usuario.login,
        'tipo_usuario': usuario.tipo_usuario,
        'exp': datetime.utcnow() + timedelta(hours=expiration_hours),
        'iat': datetime.utcnow()
    }
    
    token = jwt.encode(payload, current_app.config['JWT_SECRET_KEY'], algorithm='HS256')
    return token

def gerar_refresh_token(usuario):
    """
    Gera token de refresh JWT
    """
    payload = {
        'user_id': usuario.id,
        'type': 'refresh',
        'exp': datetime.utcnow() + timedelta(days=30),
        'iat': datetime.utcnow()
    }
    
    token = jwt.encode(payload, current_app.config['JWT_SECRET_KEY'], algorithm='HS256')
    return token

def validar_api_key(api_key):
    """
    Valida chave de API (implementar conforme necessidade)
    """
    # Por enquanto, apenas verificar se existe
    # Em produção, implementar verificação em banco de dados
    chaves_validas = [
        current_app.config.get('API_KEY_MASTER', 'cosmopolis-api-key-2024')
    ]
    
    return api_key in chaves_validas

def gerar_senha_temporaria():
    """
    Gera senha temporária segura
    """
    # Gerar senha com 8 caracteres: 4 letras + 4 números
    import random
    import string
    
    letras = ''.join(random.choices(string.ascii_uppercase, k=4))
    numeros = ''.join(random.choices(string.digits, k=4))
    
    # Misturar caracteres
    senha_lista = list(letras + numeros)
    random.shuffle(senha_lista)
    senha = ''.join(senha_lista)
    
    return senha

def validar_senha_forte(senha):
    """
    Valida se a senha atende aos critérios de segurança
    """
    erros = []
    
    if len(senha) < 8:
        erros.append("Senha deve ter pelo menos 8 caracteres")
    
    if not re.search(r'[A-Z]', senha):
        erros.append("Senha deve conter pelo menos uma letra maiúscula")
    
    if not re.search(r'[a-z]', senha):
        erros.append("Senha deve conter pelo menos uma letra minúscula")
    
    if not re.search(r'\d', senha):
        erros.append("Senha deve conter pelo menos um número")
    
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', senha):
        erros.append("Senha deve conter pelo menos um caractere especial")
    
    # Verificar senhas comuns
    senhas_fracas = [
        '123456', 'password', '123456789', '12345678', '12345',
        '1234567', '1234567890', 'qwerty', 'abc123', 'password123',
        'admin', 'administrador', 'cosmopolis', '000000'
    ]
    
    if senha.lower() in senhas_fracas:
        erros.append("Senha muito comum. Escolha uma senha mais segura")
    
    return len(erros) == 0, erros

def hash_password_with_salt(password, salt=None):
    """
    Gera hash da senha com salt personalizado
    """
    if salt is None:
        salt = secrets.token_hex(16)
    
    # Combinar senha com salt
    salted_password = password + salt
    
    # Gerar hash SHA-256
    hash_object = hashlib.sha256(salted_password.encode())
    password_hash = hash_object.hexdigest()
    
    return password_hash, salt

def verificar_senha_com_salt(password, stored_hash, salt):
    """
    Verifica senha usando hash com salt
    """
    password_hash, _ = hash_password_with_salt(password, salt)
    return password_hash == stored_hash

def registrar_tentativa_login(usuario, sucesso, ip_address=None, user_agent=None):
    """
    Registra tentativa de login no sistema
    """
    from sistema.models.usuario import Usuario
    from db.database import db
    
    try:
        if sucesso:
            usuario.registrar_login(ip_address)
        else:
            usuario.registrar_tentativa_login_falha()
        
        db.session.commit()
        
        # Log da tentativa
        status = "SUCESSO" if sucesso else "FALHA"
        current_app.logger.info(
            f"Login {status} - Usuário: {usuario.login} - IP: {ip_address} - "
            f"Tentativas: {usuario.tentativas_login}"
        )
        
    except Exception as e:
        current_app.logger.error(f"Erro ao registrar tentativa de login: {e}")
        db.session.rollback()

def verificar_taxa_limite_login(ip_address, limite_tentativas=10, janela_minutos=15):
    """
    Verifica se IP não está fazendo muitas tentativas de login
    """
    # Esta é uma implementação básica
    # Em produção, usar Redis ou banco de dados para controle mais robusto
    
    if not hasattr(verificar_taxa_limite_login, 'tentativas'):
        verificar_taxa_limite_login.tentativas = {}
    
    agora = datetime.utcnow()
    
    # Limpar tentativas antigas
    for ip, dados in list(verificar_taxa_limite_login.tentativas.items()):
        if agora - dados['primeira_tentativa'] > timedelta(minutes=janela_minutos):
            del verificar_taxa_limite_login.tentativas[ip]
    
    # Verificar tentativas do IP atual
    if ip_address in verificar_taxa_limite_login.tentativas:
        dados = verificar_taxa_limite_login.tentativas[ip_address]
        if dados['count'] >= limite_tentativas:
            return False, f"Muitas tentativas de login. Tente novamente em {janela_minutos} minutos."
        
        dados['count'] += 1
        dados['ultima_tentativa'] = agora
    else:
        verificar_taxa_limite_login.tentativas[ip_address] = {
            'count': 1,
            'primeira_tentativa': agora,
            'ultima_tentativa': agora
        }
    
    return True, "OK"

def gerar_codigo_verificacao():
    """
    Gera código de verificação numérico de 6 dígitos
    """
    import random
    return ''.join([str(random.randint(0, 9)) for _ in range(6)])

def enviar_email_recuperacao(usuario, token):
    """
    Envia email de recuperação de senha
    (Implementação futura - por enquanto apenas log)
    """
    # TODO: Implementar envio real de email
    link_recuperacao = url_for('auth.resetar_senha', token=token, _external=True)
    
    current_app.logger.info(
        f"Email de recuperação enviado para {usuario.email} - "
        f"Token: {token} - Link: {link_recuperacao}"
    )
    
    return True

def validar_sessao_ativa():
    """
    Valida se a sessão atual ainda é válida
    """
    if 'user_id' not in session:
        return False
    
    # Verificar se sessão não expirou
    if 'login_time' in session:
        login_time = datetime.fromisoformat(session['login_time'])
        if datetime.utcnow() - login_time > timedelta(hours=8):
            return False
    
    # Verificar se usuário ainda está ativo
    from sistema.models.usuario import Usuario
    usuario = Usuario.query.get(session['user_id'])
    
    if not usuario or not usuario.ativo or usuario.esta_bloqueado:
        return False
    
    return True

def limpar_sessao():
    """
    Limpa dados da sessão de forma segura
    """
    keys_to_remove = ['user_id', 'login_time', 'user_type', 'permissions']
    
    for key in keys_to_remove:
        session.pop(key, None)

def obter_ip_cliente():
    """
    Obtém IP real do cliente considerando proxies
    """
    # Verificar headers de proxy
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    elif request.headers.get('X-Real-IP'):
        return request.headers.get('X-Real-IP')
    else:
        return request.remote_addr

def is_safe_url(target):
    """
    Verifica se URL de redirecionamento é segura
    """
    from urllib.parse import urlparse, urljoin
    
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc

def criar_log_auditoria(acao, detalhes=None, usuario=None):
    """
    Cria log de auditoria para ações importantes
    """
    if usuario is None and current_user.is_authenticated:
        usuario = current_user
    
    log_entry = {
        'timestamp': datetime.utcnow().isoformat(),
        'usuario_id': usuario.id if usuario else None,
        'usuario_login': usuario.login if usuario else 'Anônimo',
        'acao': acao,
        'detalhes': detalhes,
        'ip_address': obter_ip_cliente(),
        'user_agent': request.headers.get('User-Agent', 'Desconhecido')
    }
    
    current_app.logger.info(f"AUDITORIA: {log_entry}")
    
    # TODO: Implementar salvamento em tabela de auditoria
    return log_entry

def verificar_permissao_ajax(permission):
    """
    Verifica permissão para requisições AJAX
    """
    if not current_user.is_authenticated:
        return {'error': 'Usuário não autenticado'}, 401
    
    if not current_user.ativo:
        return {'error': 'Conta inativa'}, 403
    
    if current_user.esta_bloqueado:
        return {'error': 'Conta bloqueada'}, 403
    
    if not hasattr(current_user, permission) or not getattr(current_user, permission):
        return {'error': 'Permissão insuficiente'}, 403
    
    return None, 200

def formatar_permissoes_usuario(usuario):
    """
    Retorna lista formatada de permissões do usuário
    """
    permissoes = []
    
    if usuario.pode_criar_agendamentos:
        permissoes.append('Criar Agendamentos')
    if usuario.pode_editar_agendamentos:
        permissoes.append('Editar Agendamentos')
    if usuario.pode_cancelar_agendamentos:
        permissoes.append('Cancelar Agendamentos')
    if usuario.pode_gerenciar_pacientes:
        permissoes.append('Gerenciar Pacientes')
    if usuario.pode_gerenciar_motoristas:
        permissoes.append('Gerenciar Motoristas')
    if usuario.pode_gerenciar_veiculos:
        permissoes.append('Gerenciar Veículos')
    if usuario.pode_gerenciar_usuarios:
        permissoes.append('Gerenciar Usuários')
    if usuario.pode_gerar_relatorios:
        permissoes.append('Gerar Relatórios')
    if usuario.pode_visualizar_dashboard:
        permissoes.append('Visualizar Início')
    
    return permissoes

def criptografar_dados_sensiveis(dados):
    """
    Criptografa dados sensíveis para armazenamento
    """
    from cryptography.fernet import Fernet
    import base64
    
    # Usar chave da configuração ou gerar uma
    key = current_app.config.get('ENCRYPTION_KEY')
    if not key:
        key = Fernet.generate_key()
        current_app.logger.warning("Chave de criptografia não configurada. Usando chave temporária.")
    
    fernet = Fernet(key)
    dados_bytes = dados.encode() if isinstance(dados, str) else dados
    dados_criptografados = fernet.encrypt(dados_bytes)
    
    return base64.b64encode(dados_criptografados).decode()

def descriptografar_dados_sensiveis(dados_criptografados):
    """
    Descriptografa dados sensíveis
    """
    from cryptography.fernet import Fernet
    import base64
    
    try:
        key = current_app.config.get('ENCRYPTION_KEY')
        if not key:
            return dados_criptografados  # Retorna sem descriptografar se não há chave
        
        fernet = Fernet(key)
        dados_bytes = base64.b64decode(dados_criptografados.encode())
        dados_descriptografados = fernet.decrypt(dados_bytes)
        
        return dados_descriptografados.decode()
    except Exception as e:
        current_app.logger.error(f"Erro ao descriptografar dados: {e}")
        return dados_criptografados
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de Transporte de Pacientes
Desenvolvido para a Prefeitura Municipal de Cosmópolis
Pode ser usado por terceiros autorizados

Rotas de Autenticação
Endpoints para login, logout, recuperação de senha, etc.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, current_app
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash
from datetime import datetime, timedelta
import re

from sistema.models.usuario import Usuario
from sistema.auth.utils import (
    gerar_jwt_token, gerar_refresh_token, validar_senha_forte, 
    gerar_senha_temporaria, registrar_tentativa_login, 
    verificar_taxa_limite_login, obter_ip_cliente, is_safe_url,
    criar_log_auditoria, enviar_email_recuperacao, require_admin
)
from db.database import db

# Criar blueprint para autenticação
auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """
    Página de login do sistema
    Sistema da Prefeitura Municipal de Cosmópolis
    """
    # Se usuário já está logado, redirecionar para dashboard
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'GET':
        return render_template('login.html')
    
    # Processar formulário de login
    login_input = request.form.get('login', '').strip()
    senha = request.form.get('senha', '')
    lembrar = bool(request.form.get('lembrar'))
    next_page = request.form.get('next')
    
    # Validações básicas
    if not login_input or not senha:
        flash('Login e senha são obrigatórios.', 'error')
        return render_template('login.html')
    
    # Obter IP do cliente
    ip_address = obter_ip_cliente()
    
    # Verificar rate limiting
    pode_tentar, mensagem = verificar_taxa_limite_login(ip_address)
    if not pode_tentar:
        flash(mensagem, 'error')
        return render_template('login.html')
    
    # Buscar usuário (pode ser login ou email)
    usuario = None
    if '@' in login_input:
        usuario = Usuario.buscar_por_email(login_input)
    else:
        usuario = Usuario.buscar_por_login(login_input)
    
    # Verificar se usuário existe
    if not usuario:
        flash('Login ou senha incorretos.', 'error')
        criar_log_auditoria('TENTATIVA_LOGIN_USUARIO_INEXISTENTE', {
            'login_tentativa': login_input,
            'ip': ip_address
        })
        return render_template('login.html')
    
    # Verificar se conta está ativa
    if not usuario.ativo:
        flash('Sua conta está inativa. Entre em contato com o administrador.', 'error')
        registrar_tentativa_login(usuario, False, ip_address)
        return render_template('login.html')
    
    # Verificar se conta está bloqueada
    if usuario.esta_bloqueado:
        tempo_restante = usuario.bloqueado_ate - datetime.utcnow()
        minutos = int(tempo_restante.total_seconds() / 60)
        flash(f'Conta bloqueada por {minutos} minutos devido a tentativas de login falhadas.', 'error')
        return render_template('login.html')
    
    # Verificar senha
    if not usuario.check_password(senha):
        flash('Login ou senha incorretos.', 'error')
        registrar_tentativa_login(usuario, False, ip_address)
        criar_log_auditoria('TENTATIVA_LOGIN_SENHA_INCORRETA', {
            'usuario_id': usuario.id,
            'login': usuario.login,
            'ip': ip_address
        })
        return render_template('login.html')
    
    # Login bem-sucedido
    try:
        # Fazer login
        login_user(usuario, remember=lembrar, duration=timedelta(hours=8))
        
        # Registrar login no banco
        registrar_tentativa_login(usuario, True, ip_address)
        
        # Criar sessão personalizada
        session['user_id'] = usuario.id
        session['login_time'] = datetime.utcnow().isoformat()
        session['user_type'] = usuario.tipo_usuario
        session['permissions'] = {
            'admin': usuario.eh_admin,
            'operador': usuario.eh_operador,
            'pode_gerenciar_usuarios': usuario.pode_gerenciar_usuarios
        }
        
        # Log de auditoria
        criar_log_auditoria('LOGIN_SUCESSO', {
            'usuario_id': usuario.id,
            'login': usuario.login,
            'ip': ip_address,
            'primeiro_acesso': usuario.primeiro_acesso
        })
        
        # Mensagem de boas-vindas
        if usuario.primeiro_acesso:
            flash(f'Bem-vindo ao Sistema de Transporte de Pacientes, {usuario.nome}! Este é seu primeiro acesso.', 'info')
        else:
            flash(f'Bem-vindo de volta, {usuario.nome}!', 'success')
        
        # Verificar se deve trocar senha
        if usuario.deve_trocar_senha or usuario.senha_vencida:
            flash('Você deve trocar sua senha antes de continuar.', 'warning')
            return redirect(url_for('auth.trocar_senha'))
        
        # Redirecionar para página solicitada ou dashboard
        if next_page and is_safe_url(next_page):
            return redirect(next_page)
        
        return redirect(url_for('dashboard'))
        
    except Exception as e:
        current_app.logger.error(f"Erro durante login: {e}")
        flash('Erro interno do sistema. Tente novamente.', 'error')
        return render_template('login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    """
    Logout do usuário
    """
    # Log de auditoria
    criar_log_auditoria('LOGOUT', {
        'usuario_id': current_user.id,
        'login': current_user.login
    })
    
    # Limpar sessão
    session.clear()
    
    # Fazer logout
    logout_user()
    
    flash('Você foi desconectado com sucesso.', 'info')
    return redirect(url_for('auth.login'))

@auth_bp.route('/trocar-senha', methods=['GET', 'POST'])
@login_required
def trocar_senha():
    """
    Página para trocar senha
    """
    if request.method == 'GET':
        return render_template('trocar_senha.html', 
                             deve_trocar=current_user.deve_trocar_senha,
                             senha_vencida=current_user.senha_vencida)
    
    # Processar troca de senha
    senha_atual = request.form.get('senha_atual', '')
    nova_senha = request.form.get('nova_senha', '')
    confirmar_senha = request.form.get('confirmar_senha', '')
    
    # Validações
    if not senha_atual or not nova_senha or not confirmar_senha:
        flash('Todos os campos são obrigatórios.', 'error')
        return render_template('trocar_senha.html')
    
    # Verificar senha atual
    if not current_user.check_password(senha_atual):
        flash('Senha atual incorreta.', 'error')
        return render_template('trocar_senha.html')
    
    # Verificar se novas senhas coincidem
    if nova_senha != confirmar_senha:
        flash('A nova senha e a confirmação não coincidem.', 'error')
        return render_template('trocar_senha.html')
    
    # Verificar se nova senha é diferente da atual
    if current_user.check_password(nova_senha):
        flash('A nova senha deve ser diferente da senha atual.', 'error')
        return render_template('trocar_senha.html')
    
    # Validar força da senha
    senha_valida, erros = validar_senha_forte(nova_senha)
    if not senha_valida:
        for erro in erros:
            flash(erro, 'error')
        return render_template('trocar_senha.html')
    
    try:
        # Atualizar senha
        current_user.set_password(nova_senha)
        current_user.deve_trocar_senha = False
        current_user.primeiro_acesso = False
        
        db.session.commit()
        
        # Log de auditoria
        criar_log_auditoria('TROCA_SENHA', {
            'usuario_id': current_user.id,
            'login': current_user.login
        })
        
        flash('Senha alterada com sucesso!', 'success')
        return redirect(url_for('dashboard'))
        
    except Exception as e:
        current_app.logger.error(f"Erro ao trocar senha: {e}")
        db.session.rollback()
        flash('Erro ao alterar senha. Tente novamente.', 'error')
        return render_template('trocar_senha.html')

@auth_bp.route('/esqueci-senha', methods=['GET', 'POST'])
def esqueci_senha():
    """
    Página para recuperação de senha
    """
    if request.method == 'GET':
        return render_template('esqueci_senha.html')
    
    # Processar solicitação de recuperação
    email_ou_login = request.form.get('email_ou_login', '').strip()
    
    if not email_ou_login:
        flash('Email ou login é obrigatório.', 'error')
        return render_template('esqueci_senha.html')
    
    # Buscar usuário
    usuario = None
    if '@' in email_ou_login:
        usuario = Usuario.buscar_por_email(email_ou_login)
    else:
        usuario = Usuario.buscar_por_login(email_ou_login)
    
    # Por segurança, sempre mostrar mensagem de sucesso
    flash('Se o email/login estiver correto, você receberá instruções para redefinir sua senha.', 'info')
    
    if usuario and usuario.ativo:
        try:
            # Gerar token de recuperação
            token = usuario.gerar_token_recuperacao()
            db.session.commit()
            
            # Enviar email (por enquanto apenas log)
            enviar_email_recuperacao(usuario, token)
            
            # Log de auditoria
            criar_log_auditoria('SOLICITACAO_RECUPERACAO_SENHA', {
                'usuario_id': usuario.id,
                'login': usuario.login,
                'email': usuario.email
            })
            
        except Exception as e:
            current_app.logger.error(f"Erro ao gerar token de recuperação: {e}")
            db.session.rollback()
    
    return render_template('esqueci_senha.html', sucesso=True)

@auth_bp.route('/resetar-senha/<token>', methods=['GET', 'POST'])
def resetar_senha(token):
    """
    Página para resetar senha com token
    """
    # Buscar usuário pelo token
    usuario = Usuario.query.filter_by(token_recuperacao=token).first()
    
    if not usuario or not usuario.validar_token_recuperacao(token):
        flash('Token inválido ou expirado. Solicite uma nova recuperação de senha.', 'error')
        return redirect(url_for('auth.esqueci_senha'))
    
    if request.method == 'GET':
        return render_template('resetar_senha.html', token=token, usuario=usuario)
    
    # Processar reset de senha
    nova_senha = request.form.get('nova_senha', '')
    confirmar_senha = request.form.get('confirmar_senha', '')
    
    # Validações
    if not nova_senha or not confirmar_senha:
        flash('Todos os campos são obrigatórios.', 'error')
        return render_template('resetar_senha.html', token=token, usuario=usuario)
    
    if nova_senha != confirmar_senha:
        flash('A senha e a confirmação não coincidem.', 'error')
        return render_template('resetar_senha.html', token=token, usuario=usuario)
    
    # Validar força da senha
    senha_valida, erros = validar_senha_forte(nova_senha)
    if not senha_valida:
        for erro in erros:
            flash(erro, 'error')
        return render_template('resetar_senha.html', token=token, usuario=usuario)
    
    try:
        # Resetar senha
        usuario.resetar_senha_com_token(token, nova_senha)
        db.session.commit()
        
        # Log de auditoria
        criar_log_auditoria('RESET_SENHA_TOKEN', {
            'usuario_id': usuario.id,
            'login': usuario.login
        })
        
        flash('Senha redefinida com sucesso! Faça login com sua nova senha.', 'success')
        return redirect(url_for('auth.login'))
        
    except ValueError as e:
        flash(str(e), 'error')
        return render_template('resetar_senha.html', token=token, usuario=usuario)
    except Exception as e:
        current_app.logger.error(f"Erro ao resetar senha: {e}")
        db.session.rollback()
        flash('Erro ao redefinir senha. Tente novamente.', 'error')
        return render_template('resetar_senha.html', token=token, usuario=usuario)

@auth_bp.route('/perfil', methods=['GET', 'POST'])
@login_required
def perfil():
    """
    Página de perfil do usuário
    """
    if request.method == 'GET':
        return render_template('perfil.html', usuario=current_user)
    
    # Atualizar dados do perfil
    nome = request.form.get('nome', '').strip()
    email = request.form.get('email', '').strip()
    telefone = request.form.get('telefone', '').strip()
    
    # Validações
    if not nome:
        flash('Nome é obrigatório.', 'error')
        return render_template('perfil.html', usuario=current_user)
    
    if email and not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        flash('Email inválido.', 'error')
        return render_template('perfil.html', usuario=current_user)
    
    # Verificar se email já existe (se mudou)
    if email and email != current_user.email:
        usuario_existente = Usuario.buscar_por_email(email)
        if usuario_existente:
            flash('Este email já está cadastrado para outro usuário.', 'error')
            return render_template('perfil.html', usuario=current_user)
    
    try:
        # Atualizar dados
        current_user.nome = nome
        current_user.email = email.lower() if email else None
        current_user.telefone = re.sub(r'\D', '', telefone) if telefone else None
        
        db.session.commit()
        
        # Log de auditoria
        criar_log_auditoria('ATUALIZACAO_PERFIL', {
            'usuario_id': current_user.id,
            'login': current_user.login
        })
        
        flash('Perfil atualizado com sucesso!', 'success')
        return redirect(url_for('auth.perfil'))
        
    except Exception as e:
        current_app.logger.error(f"Erro ao atualizar perfil: {e}")
        db.session.rollback()
        flash('Erro ao atualizar perfil. Tente novamente.', 'error')
        return render_template('perfil.html', usuario=current_user)

# === ROTAS DE API ===

@auth_bp.route('/api/login', methods=['POST'])
def api_login():
    """
    Endpoint de login para API (retorna JWT)
    """
    try:
        data = request.get_json()
        
        if not data or not data.get('login') or not data.get('senha'):
            return jsonify({'error': 'Login e senha são obrigatórios'}), 400
        
        # Obter IP
        ip_address = obter_ip_cliente()
        
        # Verificar rate limiting
        pode_tentar, mensagem = verificar_taxa_limite_login(ip_address)
        if not pode_tentar:
            return jsonify({'error': mensagem}), 429
        
        # Buscar usuário
        login_input = data.get('login').strip()
        usuario = None
        
        if '@' in login_input:
            usuario = Usuario.buscar_por_email(login_input)
        else:
            usuario = Usuario.buscar_por_login(login_input)
        
        if not usuario or not usuario.ativo or not usuario.check_password(data.get('senha')):
            if usuario:
                registrar_tentativa_login(usuario, False, ip_address)
            return jsonify({'error': 'Credenciais inválidas'}), 401
        
        if usuario.esta_bloqueado:
            return jsonify({'error': 'Conta bloqueada temporariamente'}), 423
        
        # Gerar tokens
        access_token = gerar_jwt_token(usuario)
        refresh_token = gerar_refresh_token(usuario)
        
        # Registrar login
        registrar_tentativa_login(usuario, True, ip_address)
        
        # Log de auditoria
        criar_log_auditoria('API_LOGIN_SUCESSO', {
            'usuario_id': usuario.id,
            'login': usuario.login,
            'ip': ip_address
        }, usuario)
        
        return jsonify({
            'access_token': access_token,
            'refresh_token': refresh_token,
            'token_type': 'Bearer',
            'expires_in': 3600,  # 1 hora
            'usuario': {
                'id': usuario.id,
                'nome': usuario.nome,
                'login': usuario.login,
                'tipo': usuario.tipo_usuario
            }
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Erro no login API: {e}")
        return jsonify({'error': 'Erro interno do servidor'}), 500

@auth_bp.route('/api/refresh', methods=['POST'])
def api_refresh():
    """
    Endpoint para renovar token JWT
    """
    try:
        data = request.get_json()
        refresh_token = data.get('refresh_token') if data else None
        
        if not refresh_token:
            return jsonify({'error': 'Refresh token é obrigatório'}), 400
        
        import jwt
        
        # Decodificar refresh token
        payload = jwt.decode(refresh_token, current_app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
        
        if payload.get('type') != 'refresh':
            return jsonify({'error': 'Token inválido'}), 401
        
        # Buscar usuário
        usuario = Usuario.query.get(payload['user_id'])
        if not usuario or not usuario.ativo:
            return jsonify({'error': 'Usuário inválido'}), 401
        
        # Gerar novo access token
        access_token = gerar_jwt_token(usuario)
        
        return jsonify({
            'access_token': access_token,
            'token_type': 'Bearer',
            'expires_in': 3600
        }), 200
        
    except jwt.ExpiredSignatureError:
        return jsonify({'error': 'Refresh token expirado'}), 401
    except jwt.InvalidTokenError:
        return jsonify({'error': 'Refresh token inválido'}), 401
    except Exception as e:
        current_app.logger.error(f"Erro no refresh token: {e}")
        return jsonify({'error': 'Erro interno do servidor'}), 500

@auth_bp.route('/api/me', methods=['GET'])
def api_me():
    """
    Endpoint para obter dados do usuário autenticado via JWT
    """
    from sistema.auth.utils import jwt_required
    
    @jwt_required
    def get_user_data():
        usuario = request.current_jwt_user
        return jsonify(usuario.to_dict()), 200
    
    return get_user_data()

# === ROTAS ADMINISTRATIVAS ===

@auth_bp.route('/admin/usuarios', methods=['GET'])
@require_admin()
def listar_usuarios():
    """
    Lista todos os usuários (apenas admins)
    """
    usuarios = Usuario.query.all()
    return render_template('admin_usuarios.html', usuarios=usuarios)

@auth_bp.route('/admin/desbloquear-usuario/<int:user_id>', methods=['POST'])
@require_admin()
def desbloquear_usuario(user_id):
    """
    Desbloqueia um usuário (apenas admins)
    """
    try:
        usuario = Usuario.query.get_or_404(user_id)
        usuario.desbloquear_conta()
        db.session.commit()
        
        # Log de auditoria
        criar_log_auditoria('DESBLOQUEIO_USUARIO', {
            'usuario_desbloqueado_id': usuario.id,
            'usuario_desbloqueado_login': usuario.login
        })
        
        flash(f'Usuário {usuario.login} desbloqueado com sucesso.', 'success')
        
    except Exception as e:
        current_app.logger.error(f"Erro ao desbloquear usuário: {e}")
        db.session.rollback()
        flash('Erro ao desbloquear usuário.', 'error')
    
    return redirect(url_for('auth.listar_usuarios'))

@auth_bp.route('/admin/resetar-senha-usuario/<int:user_id>', methods=['POST'])
@require_admin()
def resetar_senha_usuario(user_id):
    """
    Reseta senha de um usuário (apenas admins)
    """
    try:
        usuario = Usuario.query.get_or_404(user_id)
        
        # Gerar senha temporária
        senha_temp = gerar_senha_temporaria()
        usuario.set_password(senha_temp)
        usuario.deve_trocar_senha = True
        
        db.session.commit()
        
        # Log de auditoria
        criar_log_auditoria('RESET_SENHA_ADMIN', {
            'usuario_resetado_id': usuario.id,
            'usuario_resetado_login': usuario.login
        })
        
        flash(f'Senha do usuário {usuario.login} resetada. Nova senha temporária: {senha_temp}', 'info')
        
    except Exception as e:
        current_app.logger.error(f"Erro ao resetar senha do usuário: {e}")
        db.session.rollback()
        flash('Erro ao resetar senha do usuário.', 'error')
    
    return redirect(url_for('auth.listar_usuarios'))

# === HANDLERS DE ERRO ===

@auth_bp.errorhandler(401)
def unauthorized(error):
    """Handler para erro 401 - Não autorizado"""
    if request.is_json:
        return jsonify({'error': 'Acesso não autorizado'}), 401
    
    flash('Você precisa estar logado para acessar esta página.', 'error')
    return redirect(url_for('auth.login'))

@auth_bp.errorhandler(403)
def forbidden(error):
    """Handler para erro 403 - Proibido"""
    if request.is_json:
        return jsonify({'error': 'Acesso proibido'}), 403
    
    flash('Você não tem permissão para acessar esta página.', 'error')
    return redirect(url_for('dashboard'))

# === CONTEXTO DE TEMPLATE ===

@auth_bp.context_processor
def inject_auth_vars():
    """
    Injeta variáveis de autenticação nos templates
    """
    return {
        'sistema_nome': 'Sistema de Transporte de Pacientes',
        'municipio': 'Cosmópolis',
        'current_user': current_user
    }
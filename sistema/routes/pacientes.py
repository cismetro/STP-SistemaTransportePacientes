#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de Transporte de Pacientes
Desenvolvido para a Prefeitura Municipal de Cosmópolis
Pode ser usado por terceiros autorizados

Rotas: Pacientes
Endpoints para gerenciamento de pacientes
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import or_, and_, desc
from datetime import datetime, date
import re

from sistema.models.paciente import Paciente
from sistema.auth.utils import require_module_access, criar_log_auditoria, verificar_permissao_ajax
from db.database import db

# Criar blueprint para pacientes
pacientes_bp = Blueprint('pacientes', __name__)

@pacientes_bp.route('/')
@require_module_access('pacientes')
def listar():
    """
    Lista todos os pacientes com paginação e filtros
    Sistema da Prefeitura Municipal de Cosmópolis
    """
    # Parâmetros de busca e filtro
    busca = request.args.get('busca', '').strip()
    status = request.args.get('status', 'todos')
    mobilidade = request.args.get('mobilidade', 'todos')
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 10, type=int), 100)
    
    # Query base
    query = Paciente.query
    
    # Aplicar filtros
    if busca:
        query = query.filter(
            or_(
                Paciente.nome_completo.contains(busca),
                Paciente.cpf.contains(re.sub(r'\D', '', busca)),
                Paciente.telefone_principal.contains(re.sub(r'\D', '', busca))
            )
        )
    
    if status == 'ativo':
        query = query.filter(Paciente.ativo == True)
    elif status == 'inativo':
        query = query.filter(Paciente.ativo == False)
    
    if mobilidade == 'reduzida':
        query = query.filter(Paciente.mobilidade_reduzida == True)
    elif mobilidade == 'cadeirante':
        query = query.filter(Paciente.usa_cadeira_rodas == True)
    
    # Ordenação
    query = query.order_by(Paciente.nome_completo)
    
    # Paginação
    pacientes = query.paginate(
        page=page, 
        per_page=per_page, 
        error_out=False
    )
    
    # Estatísticas para o template
    stats = Paciente.estatisticas()
    
    return render_template('pacientes.html', 
                         pacientes=pacientes,
                         stats=stats,
                         busca=busca,
                         status=status,
                         mobilidade=mobilidade)

@pacientes_bp.route('/novo', methods=['GET', 'POST'])
@require_module_access('pacientes')
def novo():
    """
    Cadastra novo paciente
    """
    if not current_user.pode_gerenciar_pacientes:
        flash('Você não tem permissão para cadastrar pacientes.', 'error')
        return redirect(url_for('pacientes.listar'))
    
    if request.method == 'GET':
        return render_template('paciente_form.html', paciente=None)
    
    try:
        # Coletar dados do formulário
        dados = {
            'nome_completo': request.form.get('nome_completo', '').strip(),
            'cpf': request.form.get('cpf', '').strip(),
            'rg': request.form.get('rg', '').strip(),
            'data_nascimento': request.form.get('data_nascimento'),
            'telefone_principal': request.form.get('telefone_principal', '').strip(),
            'telefone_secundario': request.form.get('telefone_secundario', '').strip(),
            'email': request.form.get('email', '').strip(),
            'cep': request.form.get('cep', '').strip(),
            'logradouro': request.form.get('logradouro', '').strip(),
            'numero': request.form.get('numero', '').strip(),
            'complemento': request.form.get('complemento', '').strip(),
            'bairro': request.form.get('bairro', '').strip(),
            'cidade': request.form.get('cidade', 'Cosmópolis').strip(),
            'uf': request.form.get('uf', 'SP').strip(),
            'observacoes_medicas': request.form.get('observacoes_medicas', '').strip(),
            'necessita_acompanhante': bool(request.form.get('necessita_acompanhante')),
            'mobilidade_reduzida': bool(request.form.get('mobilidade_reduzida')),
            'usa_cadeira_rodas': bool(request.form.get('usa_cadeira_rodas')),
            'nome_responsavel': request.form.get('nome_responsavel', '').strip(),
            'cpf_responsavel': request.form.get('cpf_responsavel', '').strip(),
            'telefone_responsavel': request.form.get('telefone_responsavel', '').strip(),
            'parentesco_responsavel': request.form.get('parentesco_responsavel', '').strip(),
            'observacoes': request.form.get('observacoes', '').strip()
        }
        
        # Validações adicionais
        if not dados['nome_completo']:
            flash('Nome completo é obrigatório.', 'error')
            return render_template('paciente_form.html', paciente=None, dados=dados)
        
        # Verificar se CPF já existe
        cpf_numeros = re.sub(r'\D', '', dados['cpf'])
        paciente_existente = Paciente.buscar_por_cpf(cpf_numeros)
        if paciente_existente:
            flash('Já existe um paciente cadastrado com este CPF.', 'error')
            return render_template('paciente_form.html', paciente=None, dados=dados)
        
        # Converter data de nascimento
        if dados['data_nascimento']:
            dados['data_nascimento'] = datetime.strptime(dados['data_nascimento'], '%Y-%m-%d').date()
        
        # Limpar campos vazios opcionais
        for campo in ['telefone_secundario', 'email', 'complemento', 'observacoes_medicas', 
                     'nome_responsavel', 'cpf_responsavel', 'telefone_responsavel', 
                     'parentesco_responsavel', 'observacoes']:
            if not dados[campo]:
                dados[campo] = None
        
        # Criar paciente
        paciente = Paciente(**dados)
        
        db.session.add(paciente)
        db.session.commit()
        
        # Log de auditoria
        criar_log_auditoria('PACIENTE_CRIADO', {
            'paciente_id': paciente.id,
            'paciente_nome': paciente.nome_completo,
            'paciente_cpf': paciente.cpf
        })
        
        flash(f'Paciente {paciente.nome_completo} cadastrado com sucesso!', 'success')
        return redirect(url_for('pacientes.visualizar', id=paciente.id))
        
    except ValueError as e:
        flash(str(e), 'error')
        return render_template('paciente_form.html', paciente=None, dados=dados)
    except Exception as e:
        current_app.logger.error(f"Erro ao criar paciente: {e}")
        db.session.rollback()
        flash('Erro ao cadastrar paciente. Verifique os dados e tente novamente.', 'error')
        return render_template('paciente_form.html', paciente=None, dados=dados)

@pacientes_bp.route('/<int:id>')
@require_module_access('pacientes')
def visualizar(id):
    """
    Visualiza detalhes de um paciente
    """
    paciente = Paciente.query.get_or_404(id)
    
    # Buscar agendamentos do paciente (últimos 10)
    agendamentos = paciente.agendamentos.order_by(desc('data_agendamento')).limit(10).all()
    
    return render_template('paciente_detalhes.html', 
                         paciente=paciente,
                         agendamentos=agendamentos)

@pacientes_bp.route('/<int:id>/editar', methods=['GET', 'POST'])
@require_module_access('pacientes')
def editar(id):
    """
    Edita dados de um paciente
    """
    if not current_user.pode_gerenciar_pacientes:
        flash('Você não tem permissão para editar pacientes.', 'error')
        return redirect(url_for('pacientes.visualizar', id=id))
    
    paciente = Paciente.query.get_or_404(id)
    
    if request.method == 'GET':
        return render_template('paciente_form.html', paciente=paciente)
    
    try:
        # Coletar dados do formulário
        dados = {
            'nome_completo': request.form.get('nome_completo', '').strip(),
            'cpf': request.form.get('cpf', '').strip(),
            'rg': request.form.get('rg', '').strip(),
            'data_nascimento': request.form.get('data_nascimento'),
            'telefone_principal': request.form.get('telefone_principal', '').strip(),
            'telefone_secundario': request.form.get('telefone_secundario', '').strip(),
            'email': request.form.get('email', '').strip(),
            'cep': request.form.get('cep', '').strip(),
            'logradouro': request.form.get('logradouro', '').strip(),
            'numero': request.form.get('numero', '').strip(),
            'complemento': request.form.get('complemento', '').strip(),
            'bairro': request.form.get('bairro', '').strip(),
            'cidade': request.form.get('cidade', 'Cosmópolis').strip(),
            'uf': request.form.get('uf', 'SP').strip(),
            'observacoes_medicas': request.form.get('observacoes_medicas', '').strip(),
            'necessita_acompanhante': bool(request.form.get('necessita_acompanhante')),
            'mobilidade_reduzida': bool(request.form.get('mobilidade_reduzida')),
            'usa_cadeira_rodas': bool(request.form.get('usa_cadeira_rodas')),
            'nome_responsavel': request.form.get('nome_responsavel', '').strip(),
            'cpf_responsavel': request.form.get('cpf_responsavel', '').strip(),
            'telefone_responsavel': request.form.get('telefone_responsavel', '').strip(),
            'parentesco_responsavel': request.form.get('parentesco_responsavel', '').strip(),
            'observacoes': request.form.get('observacoes', '').strip()
        }
        
        # Verificar se CPF mudou e se já existe
        cpf_numeros = re.sub(r'\D', '', dados['cpf'])
        if cpf_numeros != paciente.cpf:
            paciente_existente = Paciente.buscar_por_cpf(cpf_numeros)
            if paciente_existente:
                flash('Já existe outro paciente cadastrado com este CPF.', 'error')
                return render_template('paciente_form.html', paciente=paciente, dados=dados)
        
        # Converter data de nascimento
        if dados['data_nascimento']:
            dados['data_nascimento'] = datetime.strptime(dados['data_nascimento'], '%Y-%m-%d').date()
        
        # Limpar campos vazios opcionais
        for campo in ['telefone_secundario', 'email', 'complemento', 'observacoes_medicas', 
                     'nome_responsavel', 'cpf_responsavel', 'telefone_responsavel', 
                     'parentesco_responsavel', 'observacoes']:
            if not dados[campo]:
                dados[campo] = None
        
        # Atualizar dados
        for campo, valor in dados.items():
            setattr(paciente, campo, valor)
        
        db.session.commit()
        
        # Log de auditoria
        criar_log_auditoria('PACIENTE_EDITADO', {
            'paciente_id': paciente.id,
            'paciente_nome': paciente.nome_completo,
            'paciente_cpf': paciente.cpf
        })
        
        flash(f'Dados do paciente {paciente.nome_completo} atualizados com sucesso!', 'success')
        return redirect(url_for('pacientes.visualizar', id=paciente.id))
        
    except ValueError as e:
        flash(str(e), 'error')
        return render_template('paciente_form.html', paciente=paciente, dados=dados)
    except Exception as e:
        current_app.logger.error(f"Erro ao editar paciente: {e}")
        db.session.rollback()
        flash('Erro ao atualizar dados do paciente. Tente novamente.', 'error')
        return render_template('paciente_form.html', paciente=paciente, dados=dados)

@pacientes_bp.route('/<int:id>/ativar-inativar', methods=['POST'])
@require_module_access('pacientes')
def ativar_inativar(id):
    """
    Ativa ou inativa um paciente
    """
    if not current_user.pode_gerenciar_pacientes:
        return jsonify({'error': 'Sem permissão'}), 403
    
    try:
        paciente = Paciente.query.get_or_404(id)
        
        # Verificar se paciente tem agendamentos futuros
        if paciente.ativo:  # Tentando inativar
            from sistema.models.agendamento import Agendamento
            agendamentos_futuros = Agendamento.query.filter(
                Agendamento.paciente_id == paciente.id,
                Agendamento.data_agendamento >= date.today(),
                Agendamento.status.in_(['agendado', 'confirmado'])
            ).count()
            
            if agendamentos_futuros > 0:
                return jsonify({
                    'error': f'Não é possível inativar. Paciente possui {agendamentos_futuros} agendamento(s) futuro(s).'
                }), 400
        
        # Alterar status
        paciente.ativo = not paciente.ativo
        db.session.commit()
        
        # Log de auditoria
        acao = 'PACIENTE_ATIVADO' if paciente.ativo else 'PACIENTE_INATIVADO'
        criar_log_auditoria(acao, {
            'paciente_id': paciente.id,
            'paciente_nome': paciente.nome_completo
        })
        
        status_texto = 'ativado' if paciente.ativo else 'inativado'
        
        return jsonify({
            'success': True,
            'message': f'Paciente {status_texto} com sucesso!',
            'novo_status': paciente.ativo
        })
        
    except Exception as e:
        current_app.logger.error(f"Erro ao ativar/inativar paciente: {e}")
        db.session.rollback()
        return jsonify({'error': 'Erro interno do servidor'}), 500

@pacientes_bp.route('/buscar')
@require_module_access('pacientes')
def buscar_ajax():
    """
    Busca pacientes via AJAX para autocomplete
    """
    termo = request.args.get('q', '').strip()
    limite = min(request.args.get('limit', 10, type=int), 50)
    apenas_ativos = request.args.get('apenas_ativos', 'true').lower() == 'true'
    
    if len(termo) < 2:
        return jsonify([])
    
    query = Paciente.query
    
    if apenas_ativos:
        query = query.filter(Paciente.ativo == True)
    
    # Buscar por nome ou CPF
    query = query.filter(
        or_(
            Paciente.nome_completo.contains(termo),
            Paciente.cpf.contains(re.sub(r'\D', '', termo))
        )
    ).limit(limite)
    
    pacientes = query.all()
    
    resultados = []
    for paciente in pacientes:
        resultados.append({
            'id': paciente.id,
            'nome': paciente.nome_completo,
            'cpf': paciente.cpf_formatado,
            'telefone': paciente.telefone_formatado,
            'idade': paciente.idade,
            'mobilidade_reduzida': paciente.mobilidade_reduzida,
            'usa_cadeira_rodas': paciente.usa_cadeira_rodas,
            'text': f"{paciente.nome_completo} - {paciente.cpf_formatado}"  # Para Select2
        })
    
    return jsonify(resultados)

@pacientes_bp.route('/verificar-cpf')
@require_module_access('pacientes')
def verificar_cpf():
    """
    Verifica se CPF já existe (para validação em tempo real)
    """
    cpf = request.args.get('cpf', '').strip()
    paciente_id = request.args.get('id', type=int)  # Para edição
    
    if not cpf:
        return jsonify({'existe': False})
    
    cpf_numeros = re.sub(r'\D', '', cpf)
    
    query = Paciente.query.filter_by(cpf=cpf_numeros)
    
    # Excluir o próprio paciente se for edição
    if paciente_id:
        query = query.filter(Paciente.id != paciente_id)
    
    paciente_existente = query.first()
    
    return jsonify({
        'existe': paciente_existente is not None,
        'nome': paciente_existente.nome_completo if paciente_existente else None
    })

@pacientes_bp.route('/relatorio')
@require_module_access('pacientes')
def relatorio():
    """
    Gera relatório de pacientes
    """
    if not current_user.pode_gerar_relatorios:
        flash('Você não tem permissão para gerar relatórios.', 'error')
        return redirect(url_for('pacientes.listar'))
    
    formato = request.args.get('formato', 'html')
    
    # Filtros do relatório
    status = request.args.get('status', 'todos')
    mobilidade = request.args.get('mobilidade', 'todos')
    idade_min = request.args.get('idade_min', type=int)
    idade_max = request.args.get('idade_max', type=int)
    
    # Query base
    query = Paciente.query
    
    # Aplicar filtros
    if status == 'ativo':
        query = query.filter(Paciente.ativo == True)
    elif status == 'inativo':
        query = query.filter(Paciente.ativo == False)
    
    if mobilidade == 'reduzida':
        query = query.filter(Paciente.mobilidade_reduzida == True)
    elif mobilidade == 'cadeirante':
        query = query.filter(Paciente.usa_cadeira_rodas == True)
    
    # Filtro de idade (implementação simplificada)
    if idade_min or idade_max:
        hoje = date.today()
        if idade_min:
            data_max = hoje.replace(year=hoje.year - idade_min)
            query = query.filter(Paciente.data_nascimento <= data_max)
        if idade_max:
            data_min = hoje.replace(year=hoje.year - idade_max)
            query = query.filter(Paciente.data_nascimento >= data_min)
    
    pacientes = query.order_by(Paciente.nome_completo).all()
    
    if formato == 'json':
        return jsonify([p.to_dict() for p in pacientes])
    
    elif formato == 'csv':
        import csv
        from io import StringIO
        
        output = StringIO()
        writer = csv.writer(output)
        
        # Cabeçalho
        writer.writerow([
            'Nome', 'CPF', 'Data Nascimento', 'Idade', 'Telefone', 
            'Email', 'Cidade', 'Mobilidade Reduzida', 'Cadeirante', 'Status'
        ])
        
        # Dados
        for p in pacientes:
            writer.writerow([
                p.nome_completo,
                p.cpf_formatado,
                p.data_nascimento.strftime('%d/%m/%Y') if p.data_nascimento else '',
                p.idade,
                p.telefone_formatado,
                p.email or '',
                p.cidade,
                'Sim' if p.mobilidade_reduzida else 'Não',
                'Sim' if p.usa_cadeira_rodas else 'Não',
                'Ativo' if p.ativo else 'Inativo'
            ])
        
        output.seek(0)
        
        from flask import Response
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=pacientes.csv'}
        )
    
    # Formato HTML (padrão)
    stats = Paciente.estatisticas()
    return render_template('pacientes_relatorio.html', 
                         pacientes=pacientes, 
                         stats=stats,
                         filtros={
                             'status': status,
                             'mobilidade': mobilidade,
                             'idade_min': idade_min,
                             'idade_max': idade_max
                         })

# === ROTAS DE API ===

@pacientes_bp.route('/api/', methods=['GET'])
@require_module_access('pacientes')
def api_listar():
    """
    API: Lista pacientes
    """
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)
    
    pacientes = Paciente.query.filter_by(ativo=True).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    return jsonify({
        'pacientes': [p.to_dict() for p in pacientes.items],
        'total': pacientes.total,
        'pages': pacientes.pages,
        'current_page': pacientes.page,
        'per_page': pacientes.per_page
    })

@pacientes_bp.route('/api/<int:id>', methods=['GET'])
@require_module_access('pacientes')
def api_obter(id):
    """
    API: Obtém um paciente
    """
    paciente = Paciente.query.get_or_404(id)
    return jsonify(paciente.to_dict())

@pacientes_bp.route('/api/', methods=['POST'])
@require_module_access('pacientes')
def api_criar():
    """
    API: Cria novo paciente
    """
    # Verificar permissão
    erro, status = verificar_permissao_ajax('pode_gerenciar_pacientes')
    if erro:
        return jsonify(erro), status
    
    try:
        dados = request.get_json()
        
        # Validações básicas
        if not dados or not dados.get('nome_completo'):
            return jsonify({'error': 'Nome completo é obrigatório'}), 400
        
        # Verificar CPF duplicado
        cpf_numeros = re.sub(r'\D', '', dados.get('cpf', ''))
        if Paciente.buscar_por_cpf(cpf_numeros):
            return jsonify({'error': 'CPF já cadastrado'}), 400
        
        # Criar paciente
        paciente = Paciente(**dados)
        db.session.add(paciente)
        db.session.commit()
        
        # Log de auditoria
        criar_log_auditoria('PACIENTE_CRIADO_API', {
            'paciente_id': paciente.id,
            'paciente_nome': paciente.nome_completo
        })
        
        return jsonify(paciente.to_dict()), 201
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Erro API criar paciente: {e}")
        db.session.rollback()
        return jsonify({'error': 'Erro interno'}), 500

# === CONTEXTO DE TEMPLATE ===

@pacientes_bp.context_processor
def inject_pacientes_vars():
    """
    Injeta variáveis específicas dos pacientes nos templates
    """
    return {
        'modulo_atual': 'pacientes',
        'stats_pacientes': Paciente.estatisticas() if current_user.is_authenticated else {}
    }
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de Transporte de Pacientes
Desenvolvido para a Prefeitura Municipal de Cosmópolis
Pode ser usado por terceiros autorizados

Rotas: Motoristas
Endpoints para gerenciamento de motoristas
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import or_, and_, desc
from datetime import datetime, date, timedelta
import re

from sistema.models.motorista import Motorista
from sistema.auth.utils import require_module_access, criar_log_auditoria, verificar_permissao_ajax
from db.database import db

# Criar blueprint para motoristas
motoristas_bp = Blueprint('motoristas', __name__)

@motoristas_bp.route('/')
@require_module_access('motoristas')
def listar():
    """
    Lista todos os motoristas com paginação e filtros
    Sistema da Prefeitura Municipal de Cosmópolis
    """
    # Parâmetros de busca e filtro
    busca = request.args.get('busca', '').strip()
    status = request.args.get('status', 'todos')
    categoria_cnh = request.args.get('categoria_cnh', 'todas')
    situacao_cnh = request.args.get('situacao_cnh', 'todas')
    tipo_vinculo = request.args.get('tipo_vinculo', 'todos')
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 10, type=int), 100)
    
    # Query base
    query = Motorista.query
    
    # Aplicar filtros
    if busca:
        query = query.filter(
            or_(
                Motorista.nome_completo.contains(busca),
                Motorista.cpf.contains(re.sub(r'\D', '', busca)),
                Motorista.numero_cnh.contains(re.sub(r'\D', '', busca)),
                Motorista.telefone_principal.contains(re.sub(r'\D', '', busca))
            )
        )
    
    if status == 'ativo':
        query = query.filter(Motorista.ativo == True)
    elif status == 'inativo':
        query = query.filter(Motorista.ativo == False)
    elif status == 'disponivel':
        query = query.filter(and_(Motorista.ativo == True, Motorista.disponivel == True))
    elif status == 'indisponivel':
        query = query.filter(or_(Motorista.ativo == False, Motorista.disponivel == False))
    
    if categoria_cnh != 'todas':
        query = query.filter(Motorista.categoria_cnh == categoria_cnh.upper())
    
    if situacao_cnh == 'vencida':
        query = query.filter(Motorista.data_vencimento_cnh < date.today())
    elif situacao_cnh == 'vencendo':
        data_limite = date.today() + timedelta(days=30)
        query = query.filter(
            and_(
                Motorista.data_vencimento_cnh >= date.today(),
                Motorista.data_vencimento_cnh <= data_limite
            )
        )
    elif situacao_cnh == 'valida':
        query = query.filter(Motorista.data_vencimento_cnh >= date.today())
    
    if tipo_vinculo != 'todos':
        query = query.filter(Motorista.tipo_vinculo == tipo_vinculo)
    
    # Ordenação
    query = query.order_by(Motorista.nome_completo)
    
    # Paginação
    motoristas = query.paginate(
        page=page, 
        per_page=per_page, 
        error_out=False
    )
    
    # Estatísticas para o template
    stats = Motorista.estatisticas()
    
    # Alertas para CNH vencendo
    cnh_vencendo = Motorista.cnh_vencendo().all()
    
    return render_template('motoristas.html', 
                         motoristas=motoristas,
                         stats=stats,
                         cnh_vencendo=cnh_vencendo,
                         busca=busca,
                         status=status,
                         categoria_cnh=categoria_cnh,
                         situacao_cnh=situacao_cnh,
                         tipo_vinculo=tipo_vinculo)

@motoristas_bp.route('/novo', methods=['GET', 'POST'])
@require_module_access('motoristas')
def novo():
    """
    Cadastra novo motorista
    """
    if not current_user.pode_gerenciar_motoristas:
        flash('Você não tem permissão para cadastrar motoristas.', 'error')
        return redirect(url_for('motoristas.listar'))
    
    if request.method == 'GET':
        return render_template('motorista_form.html', motorista=None)
    
    try:
        # Coletar dados do formulário
        dados = {
            'nome_completo': request.form.get('nome_completo', '').strip(),
            'cpf': request.form.get('cpf', '').strip(),
            'rg': request.form.get('rg', '').strip(),
            'data_nascimento': request.form.get('data_nascimento'),
            'numero_cnh': request.form.get('numero_cnh', '').strip(),
            'categoria_cnh': request.form.get('categoria_cnh', '').strip(),
            'data_vencimento_cnh': request.form.get('data_vencimento_cnh'),
            'data_primeira_habilitacao': request.form.get('data_primeira_habilitacao'),
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
            'registro_funcional': request.form.get('registro_funcional', '').strip(),
            'tipo_vinculo': request.form.get('tipo_vinculo', 'funcionario').strip(),
            'data_admissao': request.form.get('data_admissao') or date.today(),
            'salario': request.form.get('salario', '').strip(),
            'curso_transporte_pacientes': bool(request.form.get('curso_transporte_pacientes')),
            'data_curso_transporte': request.form.get('data_curso_transporte'),
            'certificado_emergencia': bool(request.form.get('certificado_emergencia')),
            'data_certificado_emergencia': request.form.get('data_certificado_emergencia'),
            'atestado_saude': bool(request.form.get('atestado_saude')),
            'data_atestado_saude': request.form.get('data_atestado_saude'),
            'restricoes_medicas': request.form.get('restricoes_medicas', '').strip(),
            'pontuacao_cnh': request.form.get('pontuacao_cnh', 0, type=int),
            'observacoes': request.form.get('observacoes', '').strip()
        }
        
        # Validações adicionais
        if not dados['nome_completo']:
            flash('Nome completo é obrigatório.', 'error')
            return render_template('motorista_form.html', motorista=None, dados=dados)
        
        # Verificar se CPF já existe
        cpf_numeros = re.sub(r'\D', '', dados['cpf'])
        motorista_existente = Motorista.buscar_por_cpf(cpf_numeros)
        if motorista_existente:
            flash('Já existe um motorista cadastrado com este CPF.', 'error')
            return render_template('motorista_form.html', motorista=None, dados=dados)
        
        # Verificar se CNH já existe
        cnh_numeros = re.sub(r'\D', '', dados['numero_cnh'])
        cnh_existente = Motorista.buscar_por_cnh(cnh_numeros)
        if cnh_existente:
            flash('Já existe um motorista cadastrado com este número de CNH.', 'error')
            return render_template('motorista_form.html', motorista=None, dados=dados)
        
        # Converter datas
        for campo_data in ['data_nascimento', 'data_vencimento_cnh', 'data_primeira_habilitacao', 
                          'data_admissao', 'data_curso_transporte', 'data_certificado_emergencia', 
                          'data_atestado_saude']:
            if dados[campo_data]:
                if isinstance(dados[campo_data], str):
                    dados[campo_data] = datetime.strptime(dados[campo_data], '%Y-%m-%d').date()
        
        # Limpar campos vazios opcionais
        for campo in ['telefone_secundario', 'email', 'complemento', 'registro_funcional', 
                     'salario', 'data_curso_transporte', 'data_certificado_emergencia', 
                     'data_atestado_saude', 'restricoes_medicas', 'observacoes']:
            if not dados[campo]:
                dados[campo] = None
        
        # Criar motorista
        motorista = Motorista(**dados)
        
        db.session.add(motorista)
        db.session.commit()
        
        # Log de auditoria
        criar_log_auditoria('MOTORISTA_CRIADO', {
            'motorista_id': motorista.id,
            'motorista_nome': motorista.nome_completo,
            'motorista_cnh': motorista.numero_cnh
        })
        
        flash(f'Motorista {motorista.nome_completo} cadastrado com sucesso!', 'success')
        return redirect(url_for('motoristas.visualizar', id=motorista.id))
        
    except ValueError as e:
        flash(str(e), 'error')
        return render_template('motorista_form.html', motorista=None, dados=dados)
    except Exception as e:
        current_app.logger.error(f"Erro ao criar motorista: {e}")
        db.session.rollback()
        flash('Erro ao cadastrar motorista. Verifique os dados e tente novamente.', 'error')
        return render_template('motorista_form.html', motorista=None, dados=dados)

@motoristas_bp.route('/<int:id>')
@require_module_access('motoristas')
def visualizar(id):
    """
    Visualiza detalhes de um motorista
    """
    motorista = Motorista.query.get_or_404(id)
    
    # Buscar agendamentos do motorista (últimos 10)
    agendamentos = motorista.agendamentos.order_by(desc('data_agendamento')).limit(10).all()
    
    # Calcular estatísticas do motorista
    total_agendamentos = motorista.agendamentos.count()
    agendamentos_mes = motorista.agendamentos.filter(
        and_(
            db.func.extract('month', 'data_agendamento') == date.today().month,
            db.func.extract('year', 'data_agendamento') == date.today().year
        )
    ).count()
    
    return render_template('motorista_detalhes.html', 
                         motorista=motorista,
                         agendamentos=agendamentos,
                         total_agendamentos=total_agendamentos,
                         agendamentos_mes=agendamentos_mes)

@motoristas_bp.route('/<int:id>/editar', methods=['GET', 'POST'])
@require_module_access('motoristas')
def editar(id):
    """
    Edita dados de um motorista
    """
    if not current_user.pode_gerenciar_motoristas:
        flash('Você não tem permissão para editar motoristas.', 'error')
        return redirect(url_for('motoristas.visualizar', id=id))
    
    motorista = Motorista.query.get_or_404(id)
    
    if request.method == 'GET':
        return render_template('motorista_form.html', motorista=motorista)
    
    try:
        # Coletar dados do formulário
        dados = {
            'nome_completo': request.form.get('nome_completo', '').strip(),
            'cpf': request.form.get('cpf', '').strip(),
            'rg': request.form.get('rg', '').strip(),
            'data_nascimento': request.form.get('data_nascimento'),
            'numero_cnh': request.form.get('numero_cnh', '').strip(),
            'categoria_cnh': request.form.get('categoria_cnh', '').strip(),
            'data_vencimento_cnh': request.form.get('data_vencimento_cnh'),
            'data_primeira_habilitacao': request.form.get('data_primeira_habilitacao'),
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
            'registro_funcional': request.form.get('registro_funcional', '').strip(),
            'tipo_vinculo': request.form.get('tipo_vinculo', 'funcionario').strip(),
            'data_admissao': request.form.get('data_admissao'),
            'salario': request.form.get('salario', '').strip(),
            'curso_transporte_pacientes': bool(request.form.get('curso_transporte_pacientes')),
            'data_curso_transporte': request.form.get('data_curso_transporte'),
            'certificado_emergencia': bool(request.form.get('certificado_emergencia')),
            'data_certificado_emergencia': request.form.get('data_certificado_emergencia'),
            'atestado_saude': bool(request.form.get('atestado_saude')),
            'data_atestado_saude': request.form.get('data_atestado_saude'),
            'restricoes_medicas': request.form.get('restricoes_medicas', '').strip(),
            'pontuacao_cnh': request.form.get('pontuacao_cnh', 0, type=int),
            'disponivel': bool(request.form.get('disponivel')),
            'observacoes': request.form.get('observacoes', '').strip()
        }
        
        # Verificar se CPF mudou e se já existe
        cpf_numeros = re.sub(r'\D', '', dados['cpf'])
        if cpf_numeros != motorista.cpf:
            motorista_existente = Motorista.buscar_por_cpf(cpf_numeros)
            if motorista_existente:
                flash('Já existe outro motorista cadastrado com este CPF.', 'error')
                return render_template('motorista_form.html', motorista=motorista, dados=dados)
        
        # Verificar se CNH mudou e se já existe
        cnh_numeros = re.sub(r'\D', '', dados['numero_cnh'])
        if cnh_numeros != motorista.numero_cnh:
            cnh_existente = Motorista.buscar_por_cnh(cnh_numeros)
            if cnh_existente:
                flash('Já existe outro motorista cadastrado com este número de CNH.', 'error')
                return render_template('motorista_form.html', motorista=motorista, dados=dados)
        
        # Converter datas
        for campo_data in ['data_nascimento', 'data_vencimento_cnh', 'data_primeira_habilitacao', 
                          'data_admissao', 'data_curso_transporte', 'data_certificado_emergencia', 
                          'data_atestado_saude']:
            if dados[campo_data]:
                if isinstance(dados[campo_data], str):
                    dados[campo_data] = datetime.strptime(dados[campo_data], '%Y-%m-%d').date()
        
        # Limpar campos vazios opcionais
        for campo in ['telefone_secundario', 'email', 'complemento', 'registro_funcional', 
                     'salario', 'data_curso_transporte', 'data_certificado_emergencia', 
                     'data_atestado_saude', 'restricoes_medicas', 'observacoes']:
            if not dados[campo]:
                dados[campo] = None
        
        # Atualizar dados
        for campo, valor in dados.items():
            setattr(motorista, campo, valor)
        
        db.session.commit()
        
        # Log de auditoria
        criar_log_auditoria('MOTORISTA_EDITADO', {
            'motorista_id': motorista.id,
            'motorista_nome': motorista.nome_completo,
            'motorista_cnh': motorista.numero_cnh
        })
        
        flash(f'Dados do motorista {motorista.nome_completo} atualizados com sucesso!', 'success')
        return redirect(url_for('motoristas.visualizar', id=motorista.id))
        
    except ValueError as e:
        flash(str(e), 'error')
        return render_template('motorista_form.html', motorista=motorista, dados=dados)
    except Exception as e:
        current_app.logger.error(f"Erro ao editar motorista: {e}")
        db.session.rollback()
        flash('Erro ao atualizar dados do motorista. Tente novamente.', 'error')
        return render_template('motorista_form.html', motorista=motorista, dados=dados)

@motoristas_bp.route('/<int:id>/ativar-inativar', methods=['POST'])
@require_module_access('motoristas')
def ativar_inativar(id):
    """
    Ativa ou inativa um motorista
    """
    if not current_user.pode_gerenciar_motoristas:
        return jsonify({'error': 'Sem permissão'}), 403
    
    try:
        motorista = Motorista.query.get_or_404(id)
        
        # Verificar se motorista tem agendamentos futuros
        if motorista.ativo:  # Tentando inativar
            from sistema.models.agendamento import Agendamento
            agendamentos_futuros = Agendamento.query.filter(
                Agendamento.motorista_id == motorista.id,
                Agendamento.data_agendamento >= date.today(),
                Agendamento.status.in_(['agendado', 'confirmado'])
            ).count()
            
            if agendamentos_futuros > 0:
                return jsonify({
                    'error': f'Não é possível inativar. Motorista possui {agendamentos_futuros} agendamento(s) futuro(s).'
                }), 400
        
        # Alterar status
        motorista.ativo = not motorista.ativo
        
        # Se inativando, marcar como indisponível também
        if not motorista.ativo:
            motorista.disponivel = False
            motorista.motivo_inativacao = 'Inativado pelo sistema'
        else:
            motorista.disponivel = True
            motorista.motivo_inativacao = None
        
        db.session.commit()
        
        # Log de auditoria
        acao = 'MOTORISTA_ATIVADO' if motorista.ativo else 'MOTORISTA_INATIVADO'
        criar_log_auditoria(acao, {
            'motorista_id': motorista.id,
            'motorista_nome': motorista.nome_completo
        })
        
        status_texto = 'ativado' if motorista.ativo else 'inativado'
        
        return jsonify({
            'success': True,
            'message': f'Motorista {status_texto} com sucesso!',
            'novo_status': motorista.ativo
        })
        
    except Exception as e:
        current_app.logger.error(f"Erro ao ativar/inativar motorista: {e}")
        db.session.rollback()
        return jsonify({'error': 'Erro interno do servidor'}), 500

@motoristas_bp.route('/<int:id>/disponibilidade', methods=['POST'])
@require_module_access('motoristas')
def alterar_disponibilidade(id):
    """
    Altera disponibilidade de um motorista
    """
    if not current_user.pode_gerenciar_motoristas:
        return jsonify({'error': 'Sem permissão'}), 403
    
    try:
        motorista = Motorista.query.get_or_404(id)
        
        if not motorista.ativo:
            return jsonify({'error': 'Motorista inativo não pode ter disponibilidade alterada'}), 400
        
        data = request.get_json()
        disponivel = data.get('disponivel', False)
        motivo = data.get('motivo', '').strip()
        
        motorista.disponivel = disponivel
        
        if not disponivel and motivo:
            motorista.motivo_indisponibilidade = motivo
        elif disponivel:
            motorista.motivo_indisponibilidade = None
        
        db.session.commit()
        
        # Log de auditoria
        acao = 'MOTORISTA_DISPONIVEL' if disponivel else 'MOTORISTA_INDISPONIVEL'
        criar_log_auditoria(acao, {
            'motorista_id': motorista.id,
            'motorista_nome': motorista.nome_completo,
            'motivo': motivo
        })
        
        status_texto = 'disponível' if disponivel else 'indisponível'
        
        return jsonify({
            'success': True,
            'message': f'Motorista marcado como {status_texto}!',
            'disponivel': motorista.disponivel
        })
        
    except Exception as e:
        current_app.logger.error(f"Erro ao alterar disponibilidade do motorista: {e}")
        db.session.rollback()
        return jsonify({'error': 'Erro interno do servidor'}), 500

@motoristas_bp.route('/buscar')
@require_module_access('motoristas')
def buscar_ajax():
    """
    Busca motoristas via AJAX para autocomplete
    """
    termo = request.args.get('q', '').strip()
    limite = min(request.args.get('limit', 10, type=int), 50)
    apenas_habilitados = request.args.get('apenas_habilitados', 'true').lower() == 'true'
    categoria_minima = request.args.get('categoria_minima', '').strip()
    
    if len(termo) < 2:
        return jsonify([])
    
    query = Motorista.query
    
    if apenas_habilitados:
        query = Motorista.motoristas_habilitados()
    else:
        query = query.filter(Motorista.ativo == True)
    
    # Filtrar por categoria mínima se especificado
    if categoria_minima:
        categorias_aceitas = {
            'A': ['A', 'B', 'C', 'D', 'E', 'AB', 'AC', 'AD', 'AE', 'ACC'],
            'B': ['B', 'C', 'D', 'E', 'AB', 'AC', 'AD', 'AE'],
            'C': ['C', 'D', 'E', 'AC', 'AD', 'AE'],
            'D': ['D', 'E', 'AD', 'AE'],
            'E': ['E', 'AE'],
            'AB': ['B', 'C', 'D', 'E', 'AB', 'AC', 'AD', 'AE'],
            'AC': ['C', 'D', 'E', 'AC', 'AD', 'AE'],
            'AD': ['D', 'E', 'AD', 'AE'],
            'AE': ['E', 'AE']
        }
        if categoria_minima.upper() in categorias_aceitas:
            query = query.filter(Motorista.categoria_cnh.in_(categorias_aceitas[categoria_minima.upper()]))
    
    # Buscar por nome, CPF ou CNH
    query = query.filter(
        or_(
            Motorista.nome_completo.contains(termo),
            Motorista.cpf.contains(re.sub(r'\D', '', termo)),
            Motorista.numero_cnh.contains(re.sub(r'\D', '', termo))
        )
    ).limit(limite)
    
    motoristas = query.all()
    
    resultados = []
    for motorista in motoristas:
        resultados.append({
            'id': motorista.id,
            'nome': motorista.nome_completo,
            'cnh': motorista.numero_cnh,
            'categoria': motorista.categoria_cnh,
            'telefone': motorista.telefone_formatado,
            'habilitado': motorista.habilitado_para_transporte_pacientes,
            'disponivel': motorista.disponivel,
            'text': f"{motorista.nome_completo} - CNH: {motorista.numero_cnh} ({motorista.categoria_cnh})"  # Para Select2
        })
    
    return jsonify(resultados)

@motoristas_bp.route('/verificar-cnh')
@require_module_access('motoristas')
def verificar_cnh():
    """
    Verifica se CNH já existe (para validação em tempo real)
    """
    cnh = request.args.get('cnh', '').strip()
    motorista_id = request.args.get('id', type=int)  # Para edição
    
    if not cnh:
        return jsonify({'existe': False})
    
    cnh_numeros = re.sub(r'\D', '', cnh)
    
    query = Motorista.query.filter_by(numero_cnh=cnh_numeros)
    
    # Excluir o próprio motorista se for edição
    if motorista_id:
        query = query.filter(Motorista.id != motorista_id)
    
    motorista_existente = query.first()
    
    return jsonify({
        'existe': motorista_existente is not None,
        'nome': motorista_existente.nome_completo if motorista_existente else None
    })

@motoristas_bp.route('/verificar-cpf')
@require_module_access('motoristas')
def verificar_cpf():
    """
    Verifica se CPF já existe (para validação em tempo real)
    """
    cpf = request.args.get('cpf', '').strip()
    motorista_id = request.args.get('id', type=int)  # Para edição
    
    if not cpf:
        return jsonify({'existe': False})
    
    cpf_numeros = re.sub(r'\D', '', cpf)
    
    query = Motorista.query.filter_by(cpf=cpf_numeros)
    
    # Excluir o próprio motorista se for edição
    if motorista_id:
        query = query.filter(Motorista.id != motorista_id)
    
    motorista_existente = query.first()
    
    return jsonify({
        'existe': motorista_existente is not None,
        'nome': motorista_existente.nome_completo if motorista_existente else None
    })

@motoristas_bp.route('/alertas-cnh')
@require_module_access('motoristas')
def alertas_cnh():
    """
    Retorna alertas de CNH vencendo/vencida
    """
    # CNH vencendo nos próximos 30 dias
    cnh_vencendo = Motorista.cnh_vencendo(30).all()
    
    # CNH vencidas
    cnh_vencidas = Motorista.query.filter(
        Motorista.ativo == True,
        Motorista.data_vencimento_cnh < date.today()
    ).all()
    
    alertas = []
    
    for motorista in cnh_vencidas:
        dias_vencida = (date.today() - motorista.data_vencimento_cnh).days
        alertas.append({
            'tipo': 'vencida',
            'motorista': motorista.nome_completo,
            'motorista_id': motorista.id,
            'cnh': motorista.numero_cnh,
            'data_vencimento': motorista.data_vencimento_cnh.strftime('%d/%m/%Y'),
            'dias': dias_vencida,
            'urgencia': 'alta'
        })
    
    for motorista in cnh_vencendo:
        if motorista not in cnh_vencidas:  # Evitar duplicatas
            dias_para_vencer = (motorista.data_vencimento_cnh - date.today()).days
            alertas.append({
                'tipo': 'vencendo',
                'motorista': motorista.nome_completo,
                'motorista_id': motorista.id,
                'cnh': motorista.numero_cnh,
                'data_vencimento': motorista.data_vencimento_cnh.strftime('%d/%m/%Y'),
                'dias': dias_para_vencer,
                'urgencia': 'media' if dias_para_vencer <= 15 else 'baixa'
            })
    
    return jsonify(alertas)

@motoristas_bp.route('/relatorio')
@require_module_access('motoristas')
def relatorio():
    """
    Gera relatório de motoristas
    """
    if not current_user.pode_gerar_relatorios:
        flash('Você não tem permissão para gerar relatórios.', 'error')
        return redirect(url_for('motoristas.listar'))
    
    formato = request.args.get('formato', 'html')
    
    # Filtros do relatório
    status = request.args.get('status', 'todos')
    categoria_cnh = request.args.get('categoria_cnh', 'todas')
    situacao_cnh = request.args.get('situacao_cnh', 'todas')
    tipo_vinculo = request.args.get('tipo_vinculo', 'todos')
    
    # Query base
    query = Motorista.query
    
    # Aplicar filtros (mesmo código da listagem)
    if status == 'ativo':
        query = query.filter(Motorista.ativo == True)
    elif status == 'inativo':
        query = query.filter(Motorista.ativo == False)
    elif status == 'habilitados':
        query = Motorista.motoristas_habilitados()
    
    if categoria_cnh != 'todas':
        query = query.filter(Motorista.categoria_cnh == categoria_cnh.upper())
    
    if situacao_cnh == 'vencida':
        query = query.filter(Motorista.data_vencimento_cnh < date.today())
    elif situacao_cnh == 'vencendo':
        data_limite = date.today() + timedelta(days=30)
        query = query.filter(
            and_(
                Motorista.data_vencimento_cnh >= date.today(),
                Motorista.data_vencimento_cnh <= data_limite
            )
        )
    
    if tipo_vinculo != 'todos':
        query = query.filter(Motorista.tipo_vinculo == tipo_vinculo)
    
    motoristas = query.order_by(Motorista.nome_completo).all()
    
    if formato == 'json':
        return jsonify([m.to_dict() for m in motoristas])
    
    elif formato == 'csv':
        import csv
        from io import StringIO
        
        output = StringIO()
        writer = csv.writer(output)
        
        # Cabeçalho
        writer.writerow([
            'Nome', 'CPF', 'CNH', 'Categoria', 'Vencimento CNH', 'Telefone', 
            'Tipo Vínculo', 'Habilitado Transporte', 'Status', 'Disponível'
        ])
        
        # Dados
        for m in motoristas:
            writer.writerow([
                m.nome_completo,
                m.cpf_formatado,
                m.numero_cnh,
                m.categoria_cnh,
                m.data_vencimento_cnh.strftime('%d/%m/%Y') if m.data_vencimento_cnh else '',
                m.telefone_formatado,
                m.tipo_vinculo.title(),
                'Sim' if m.habilitado_para_transporte_pacientes else 'Não',
                'Ativo' if m.ativo else 'Inativo',
                'Sim' if m.disponivel else 'Não'
            ])
        
        output.seek(0)
        
        from flask import Response
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=motoristas.csv'}
        )
    
    # Formato HTML (padrão)
    stats = Motorista.estatisticas()
    return render_template('motoristas_relatorio.html', 
                         motoristas=motoristas, 
                         stats=stats,
                         filtros={
                             'status': status,
                             'categoria_cnh': categoria_cnh,
                             'situacao_cnh': situacao_cnh,
                             'tipo_vinculo': tipo_vinculo
                         })

# === ROTAS DE API ===

@motoristas_bp.route('/api/', methods=['GET'])
@require_module_access('motoristas')
def api_listar():
    """
    API: Lista motoristas
    """
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)
    apenas_habilitados = request.args.get('habilitados', 'false').lower() == 'true'
    
    if apenas_habilitados:
        query = Motorista.motoristas_habilitados()
    else:
        query = Motorista.query.filter_by(ativo=True)
    
    motoristas = query.paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    return jsonify({
        'motoristas': [m.to_dict() for m in motoristas.items],
        'total': motoristas.total,
        'pages': motoristas.pages,
        'current_page': motoristas.page,
        'per_page': motoristas.per_page
    })

@motoristas_bp.route('/api/<int:id>', methods=['GET'])
@require_module_access('motoristas')
def api_obter(id):
    """
    API: Obtém um motorista
    """
    motorista = Motorista.query.get_or_404(id)
    return jsonify(motorista.to_dict())

@motoristas_bp.route('/api/', methods=['POST'])
@require_module_access('motoristas')
def api_criar():
    """
    API: Cria novo motorista
    """
    # Verificar permissão
    erro, status = verificar_permissao_ajax('pode_gerenciar_motoristas')
    if erro:
        return jsonify(erro), status
    
    try:
        dados = request.get_json()
        
        # Validações básicas
        if not dados or not dados.get('nome_completo'):
            return jsonify({'error': 'Nome completo é obrigatório'}), 400
        
        # Verificar CPF duplicado
        cpf_numeros = re.sub(r'\D', '', dados.get('cpf', ''))
        if Motorista.buscar_por_cpf(cpf_numeros):
            return jsonify({'error': 'CPF já cadastrado'}), 400
        
        # Verificar CNH duplicada
        cnh_numeros = re.sub(r'\D', '', dados.get('numero_cnh', ''))
        if Motorista.buscar_por_cnh(cnh_numeros):
            return jsonify({'error': 'CNH já cadastrada'}), 400
        
        # Criar motorista
        motorista = Motorista(**dados)
        db.session.add(motorista)
        db.session.commit()
        
        # Log de auditoria
        criar_log_auditoria('MOTORISTA_CRIADO_API', {
            'motorista_id': motorista.id,
            'motorista_nome': motorista.nome_completo
        })
        
        return jsonify(motorista.to_dict()), 201
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Erro API criar motorista: {e}")
        db.session.rollback()
        return jsonify({'error': 'Erro interno'}), 500

# === CONTEXTO DE TEMPLATE ===

@motoristas_bp.context_processor
def inject_motoristas_vars():
    """
    Injeta variáveis específicas dos motoristas nos templates
    """
    return {
        'modulo_atual': 'motoristas',
        'stats_motoristas': Motorista.estatisticas() if current_user.is_authenticated else {}
    }
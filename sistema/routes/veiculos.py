#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de Transporte de Pacientes
Desenvolvido para a Prefeitura Municipal de Cosmópolis
Pode ser usado por terceiros autorizados

Rotas: Veículos
Endpoints para gerenciamento de veículos
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import or_, and_, desc
from datetime import datetime, date, timedelta
import re

from sistema.models.veiculo import Veiculo
from sistema.auth.utils import require_module_access, criar_log_auditoria, verificar_permissao_ajax
from db.database import db

# Criar blueprint para veículos
veiculos_bp = Blueprint('veiculos', __name__)

@veiculos_bp.route('/')
@require_module_access('veiculos')
def listar():
    """
    Lista todos os veículos com paginação e filtros
    Sistema da Prefeitura Municipal de Cosmópolis
    """
    # Parâmetros de busca e filtro
    busca = request.args.get('busca', '').strip()
    status = request.args.get('status', 'todos')
    tipo_veiculo = request.args.get('tipo_veiculo', 'todos')
    situacao_doc = request.args.get('situacao_doc', 'todas')
    acessibilidade = request.args.get('acessibilidade', 'todos')
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 10, type=int), 100)
    
    # Query base
    query = Veiculo.query
    
    # Aplicar filtros
    if busca:
        query = query.filter(
            or_(
                Veiculo.placa.contains(busca.upper()),
                Veiculo.renavam.contains(re.sub(r'\D', '', busca)),
                Veiculo.marca.contains(busca),
                Veiculo.modelo.contains(busca),
                Veiculo.numero_patrimonio.contains(busca) if busca else False
            )
        )
    
    if status == 'ativo':
        query = query.filter(Veiculo.ativo == True)
    elif status == 'inativo':
        query = query.filter(Veiculo.ativo == False)
    elif status == 'disponivel':
        query = query.filter(
            and_(
                Veiculo.ativo == True,
                Veiculo.disponivel == True,
                Veiculo.em_manutencao == False
            )
        )
    elif status == 'indisponivel':
        query = query.filter(
            or_(
                Veiculo.ativo == False,
                Veiculo.disponivel == False,
                Veiculo.em_manutencao == True
            )
        )
    elif status == 'manutencao':
        query = query.filter(Veiculo.em_manutencao == True)
    
    if tipo_veiculo != 'todos':
        query = query.filter(Veiculo.tipo_veiculo == tipo_veiculo)
    
    if situacao_doc == 'licenciamento_vencido':
        query = query.filter(Veiculo.data_vencimento_licenciamento < date.today())
    elif situacao_doc == 'licenciamento_vencendo':
        data_limite = date.today() + timedelta(days=30)
        query = query.filter(
            and_(
                Veiculo.data_vencimento_licenciamento >= date.today(),
                Veiculo.data_vencimento_licenciamento <= data_limite
            )
        )
    elif situacao_doc == 'seguro_vencido':
        query = query.filter(
            or_(
                Veiculo.seguro_vigente == False,
                and_(
                    Veiculo.data_vencimento_seguro != None,
                    Veiculo.data_vencimento_seguro < date.today()
                )
            )
        )
    
    if acessibilidade == 'cadeirante':
        query = query.filter(Veiculo.capacidade_cadeirantes > 0)
    elif acessibilidade == 'total':
        query = query.filter(Veiculo.acessibilidade_total == True)
    
    # Ordenação
    query = query.order_by(Veiculo.marca, Veiculo.modelo, Veiculo.placa)
    
    # Paginação
    veiculos = query.paginate(
        page=page, 
        per_page=per_page, 
        error_out=False
    )
    
    # Estatísticas para o template
    stats = Veiculo.estatisticas()
    
    # Alertas para documentação vencendo
    licenciamento_vencendo = Veiculo.licenciamento_vencendo().all()
    necessitam_revisao = Veiculo.necessitam_revisao().all()
    
    return render_template('veiculos.html', 
                         veiculos=veiculos,
                         stats=stats,
                         licenciamento_vencendo=licenciamento_vencendo,
                         necessitam_revisao=necessitam_revisao,
                         busca=busca,
                         status=status,
                         tipo_veiculo=tipo_veiculo,
                         situacao_doc=situacao_doc,
                         acessibilidade=acessibilidade)

@veiculos_bp.route('/novo', methods=['GET', 'POST'])
@require_module_access('veiculos')
def novo():
    """
    Cadastra novo veículo
    """
    if not current_user.pode_gerenciar_veiculos:
        flash('Você não tem permissão para cadastrar veículos.', 'error')
        return redirect(url_for('veiculos.listar'))
    
    if request.method == 'GET':
        return render_template('veiculo_form.html', veiculo=None)
    
    try:
        # Coletar dados do formulário
        dados = {
            'placa': request.form.get('placa', '').strip(),
            'renavam': request.form.get('renavam', '').strip(),
            'chassi': request.form.get('chassi', '').strip(),
            'marca': request.form.get('marca', '').strip(),
            'modelo': request.form.get('modelo', '').strip(),
            'ano_fabricacao': request.form.get('ano_fabricacao', type=int),
            'ano_modelo': request.form.get('ano_modelo', type=int),
            'cor': request.form.get('cor', '').strip(),
            'combustivel': request.form.get('combustivel', '').strip(),
            'tipo_veiculo': request.form.get('tipo_veiculo', '').strip(),
            'capacidade_passageiros': request.form.get('capacidade_passageiros', type=int),
            'capacidade_cadeirantes': request.form.get('capacidade_cadeirantes', 0, type=int),
            'ar_condicionado': bool(request.form.get('ar_condicionado')),
            'acessibilidade_total': bool(request.form.get('acessibilidade_total')),
            'elevador_cadeirante': bool(request.form.get('elevador_cadeirante')),
            'maca': bool(request.form.get('maca')),
            'data_licenciamento': request.form.get('data_licenciamento'),
            'data_vencimento_licenciamento': request.form.get('data_vencimento_licenciamento'),
            'seguro_vigente': bool(request.form.get('seguro_vigente')),
            'data_vencimento_seguro': request.form.get('data_vencimento_seguro'),
            'seguradora': request.form.get('seguradora', '').strip(),
            'numero_apolice': request.form.get('numero_apolice', '').strip(),
            'quilometragem_atual': request.form.get('quilometragem_atual', 0, type=int),
            'consumo_medio': request.form.get('consumo_medio', type=float),
            'capacidade_tanque': request.form.get('capacidade_tanque', type=float),
            'data_ultima_revisao': request.form.get('data_ultima_revisao'),
            'quilometragem_ultima_revisao': request.form.get('quilometragem_ultima_revisao', type=int),
            'numero_patrimonio': request.form.get('numero_patrimonio', '').strip(),
            'observacoes': request.form.get('observacoes', '').strip()
        }
        
        # Validações adicionais
        if not dados['placa']:
            flash('Placa é obrigatória.', 'error')
            return render_template('veiculo_form.html', veiculo=None, dados=dados)
        
        # Verificar se placa já existe
        placa_limpa = re.sub(r'[^A-Z0-9]', '', dados['placa'].upper())
        veiculo_existente = Veiculo.buscar_por_placa(placa_limpa)
        if veiculo_existente:
            flash('Já existe um veículo cadastrado com esta placa.', 'error')
            return render_template('veiculo_form.html', veiculo=None, dados=dados)
        
        # Verificar se RENAVAM já existe
        renavam_numeros = re.sub(r'\D', '', dados['renavam'])
        renavam_existente = Veiculo.buscar_por_renavam(renavam_numeros)
        if renavam_existente:
            flash('Já existe um veículo cadastrado com este RENAVAM.', 'error')
            return render_template('veiculo_form.html', veiculo=None, dados=dados)
        
        # Verificar se número de patrimônio já existe
        if dados['numero_patrimonio']:
            patrimonio_existente = Veiculo.query.filter_by(numero_patrimonio=dados['numero_patrimonio']).first()
            if patrimonio_existente:
                flash('Já existe um veículo cadastrado com este número de patrimônio.', 'error')
                return render_template('veiculo_form.html', veiculo=None, dados=dados)
        
        # Converter datas
        for campo_data in ['data_licenciamento', 'data_vencimento_licenciamento', 
                          'data_vencimento_seguro', 'data_ultima_revisao']:
            if dados[campo_data]:
                dados[campo_data] = datetime.strptime(dados[campo_data], '%Y-%m-%d').date()
        
        # Limpar campos vazios opcionais
        for campo in ['seguradora', 'numero_apolice', 'data_vencimento_seguro', 
                     'consumo_medio', 'capacidade_tanque', 'data_ultima_revisao', 
                     'quilometragem_ultima_revisao', 'numero_patrimonio', 'observacoes']:
            if not dados[campo]:
                dados[campo] = None
        
        # Configurar próxima revisão se última revisão foi informada
        if dados['data_ultima_revisao'] and dados['quilometragem_ultima_revisao']:
            dados['proxima_revisao_km'] = dados['quilometragem_ultima_revisao'] + 10000
            dados['proxima_revisao_data'] = dados['data_ultima_revisao'] + timedelta(days=180)
        
        # Criar veículo
        veiculo = Veiculo(**dados)
        
        db.session.add(veiculo)
        db.session.commit()
        
        # Log de auditoria
        criar_log_auditoria('VEICULO_CRIADO', {
            'veiculo_id': veiculo.id,
            'veiculo_placa': veiculo.placa,
            'veiculo_modelo': f"{veiculo.marca} {veiculo.modelo}"
        })
        
        flash(f'Veículo {veiculo.placa_formatada} cadastrado com sucesso!', 'success')
        return redirect(url_for('veiculos.visualizar', id=veiculo.id))
        
    except ValueError as e:
        flash(str(e), 'error')
        return render_template('veiculo_form.html', veiculo=None, dados=dados)
    except Exception as e:
        current_app.logger.error(f"Erro ao criar veículo: {e}")
        db.session.rollback()
        flash('Erro ao cadastrar veículo. Verifique os dados e tente novamente.', 'error')
        return render_template('veiculo_form.html', veiculo=None, dados=dados)

@veiculos_bp.route('/<int:id>')
@require_module_access('veiculos')
def visualizar(id):
    """
    Visualiza detalhes de um veículo
    """
    veiculo = Veiculo.query.get_or_404(id)
    
    # Buscar agendamentos do veículo (últimos 10)
    agendamentos = veiculo.agendamentos.order_by(desc('data_agendamento')).limit(10).all()
    
    # Calcular estatísticas do veículo
    total_agendamentos = veiculo.agendamentos.count()
    agendamentos_mes = veiculo.agendamentos.filter(
        and_(
            db.func.extract('month', 'data_agendamento') == date.today().month,
            db.func.extract('year', 'data_agendamento') == date.today().year
        )
    ).count()
    
    # Calcular quilometragem total dos agendamentos
    from sistema.models.agendamento import Agendamento
    km_total = db.session.query(db.func.sum(Agendamento.km_percorrido)).filter(
        Agendamento.veiculo_id == veiculo.id,
        Agendamento.km_percorrido != None
    ).scalar() or 0
    
    return render_template('veiculo_detalhes.html', 
                         veiculo=veiculo,
                         agendamentos=agendamentos,
                         total_agendamentos=total_agendamentos,
                         agendamentos_mes=agendamentos_mes,
                         km_total=km_total)

@veiculos_bp.route('/<int:id>/editar', methods=['GET', 'POST'])
@require_module_access('veiculos')
def editar(id):
    """
    Edita dados de um veículo
    """
    if not current_user.pode_gerenciar_veiculos:
        flash('Você não tem permissão para editar veículos.', 'error')
        return redirect(url_for('veiculos.visualizar', id=id))
    
    veiculo = Veiculo.query.get_or_404(id)
    
    if request.method == 'GET':
        return render_template('veiculo_form.html', veiculo=veiculo)
    
    try:
        # Coletar dados do formulário
        dados = {
            'placa': request.form.get('placa', '').strip(),
            'renavam': request.form.get('renavam', '').strip(),
            'chassi': request.form.get('chassi', '').strip(),
            'marca': request.form.get('marca', '').strip(),
            'modelo': request.form.get('modelo', '').strip(),
            'ano_fabricacao': request.form.get('ano_fabricacao', type=int),
            'ano_modelo': request.form.get('ano_modelo', type=int),
            'cor': request.form.get('cor', '').strip(),
            'combustivel': request.form.get('combustivel', '').strip(),
            'tipo_veiculo': request.form.get('tipo_veiculo', '').strip(),
            'capacidade_passageiros': request.form.get('capacidade_passageiros', type=int),
            'capacidade_cadeirantes': request.form.get('capacidade_cadeirantes', 0, type=int),
            'ar_condicionado': bool(request.form.get('ar_condicionado')),
            'acessibilidade_total': bool(request.form.get('acessibilidade_total')),
            'elevador_cadeirante': bool(request.form.get('elevador_cadeirante')),
            'maca': bool(request.form.get('maca')),
            'data_licenciamento': request.form.get('data_licenciamento'),
            'data_vencimento_licenciamento': request.form.get('data_vencimento_licenciamento'),
            'seguro_vigente': bool(request.form.get('seguro_vigente')),
            'data_vencimento_seguro': request.form.get('data_vencimento_seguro'),
            'seguradora': request.form.get('seguradora', '').strip(),
            'numero_apolice': request.form.get('numero_apolice', '').strip(),
            'quilometragem_atual': request.form.get('quilometragem_atual', 0, type=int),
            'consumo_medio': request.form.get('consumo_medio', type=float),
            'capacidade_tanque': request.form.get('capacidade_tanque', type=float),
            'data_ultima_revisao': request.form.get('data_ultima_revisao'),
            'quilometragem_ultima_revisao': request.form.get('quilometragem_ultima_revisao', type=int),
            'numero_patrimonio': request.form.get('numero_patrimonio', '').strip(),
            'disponivel': bool(request.form.get('disponivel')),
            'em_manutencao': bool(request.form.get('em_manutencao')),
            'motivo_indisponibilidade': request.form.get('motivo_indisponibilidade', '').strip(),
            'observacoes': request.form.get('observacoes', '').strip()
        }
        
        # Verificar se placa mudou e se já existe
        placa_limpa = re.sub(r'[^A-Z0-9]', '', dados['placa'].upper())
        if placa_limpa != veiculo.placa:
            veiculo_existente = Veiculo.buscar_por_placa(placa_limpa)
            if veiculo_existente:
                flash('Já existe outro veículo cadastrado com esta placa.', 'error')
                return render_template('veiculo_form.html', veiculo=veiculo, dados=dados)
        
        # Verificar se RENAVAM mudou e se já existe
        renavam_numeros = re.sub(r'\D', '', dados['renavam'])
        if renavam_numeros != veiculo.renavam:
            renavam_existente = Veiculo.buscar_por_renavam(renavam_numeros)
            if renavam_existente:
                flash('Já existe outro veículo cadastrado com este RENAVAM.', 'error')
                return render_template('veiculo_form.html', veiculo=veiculo, dados=dados)
        
        # Verificar se número de patrimônio mudou e se já existe
        if dados['numero_patrimonio'] and dados['numero_patrimonio'] != veiculo.numero_patrimonio:
            patrimonio_existente = Veiculo.query.filter(
                Veiculo.numero_patrimonio == dados['numero_patrimonio'],
                Veiculo.id != veiculo.id
            ).first()
            if patrimonio_existente:
                flash('Já existe outro veículo cadastrado com este número de patrimônio.', 'error')
                return render_template('veiculo_form.html', veiculo=veiculo, dados=dados)
        
        # Converter datas
        for campo_data in ['data_licenciamento', 'data_vencimento_licenciamento', 
                          'data_vencimento_seguro', 'data_ultima_revisao']:
            if dados[campo_data]:
                dados[campo_data] = datetime.strptime(dados[campo_data], '%Y-%m-%d').date()
        
        # Limpar campos vazios opcionais
        for campo in ['seguradora', 'numero_apolice', 'data_vencimento_seguro', 
                     'consumo_medio', 'capacidade_tanque', 'data_ultima_revisao', 
                     'quilometragem_ultima_revisao', 'numero_patrimonio', 
                     'motivo_indisponibilidade', 'observacoes']:
            if not dados[campo]:
                dados[campo] = None
        
        # Atualizar quilometragem se maior que a atual
        if dados['quilometragem_atual'] > veiculo.quilometragem_atual:
            veiculo.atualizar_quilometragem(dados['quilometragem_atual'])
        
        # Atualizar dados
        for campo, valor in dados.items():
            setattr(veiculo, campo, valor)
        
        db.session.commit()
        
        # Log de auditoria
        criar_log_auditoria('VEICULO_EDITADO', {
            'veiculo_id': veiculo.id,
            'veiculo_placa': veiculo.placa,
            'veiculo_modelo': f"{veiculo.marca} {veiculo.modelo}"
        })
        
        flash(f'Dados do veículo {veiculo.placa_formatada} atualizados com sucesso!', 'success')
        return redirect(url_for('veiculos.visualizar', id=veiculo.id))
        
    except ValueError as e:
        flash(str(e), 'error')
        return render_template('veiculo_form.html', veiculo=veiculo, dados=dados)
    except Exception as e:
        current_app.logger.error(f"Erro ao editar veículo: {e}")
        db.session.rollback()
        flash('Erro ao atualizar dados do veículo. Tente novamente.', 'error')
        return render_template('veiculo_form.html', veiculo=veiculo, dados=dados)

@veiculos_bp.route('/<int:id>/ativar-inativar', methods=['POST'])
@require_module_access('veiculos')
def ativar_inativar(id):
    """
    Ativa ou inativa um veículo
    """
    if not current_user.pode_gerenciar_veiculos:
        return jsonify({'error': 'Sem permissão'}), 403
    
    try:
        veiculo = Veiculo.query.get_or_404(id)
        
        # Verificar se veículo tem agendamentos futuros
        if veiculo.ativo:  # Tentando inativar
            from sistema.models.agendamento import Agendamento
            agendamentos_futuros = Agendamento.query.filter(
                Agendamento.veiculo_id == veiculo.id,
                Agendamento.data_agendamento >= date.today(),
                Agendamento.status.in_(['agendado', 'confirmado'])
            ).count()
            
            if agendamentos_futuros > 0:
                return jsonify({
                    'error': f'Não é possível inativar. Veículo possui {agendamentos_futuros} agendamento(s) futuro(s).'
                }), 400
        
        # Alterar status
        veiculo.ativo = not veiculo.ativo
        
        # Se inativando, marcar como indisponível também
        if not veiculo.ativo:
            veiculo.disponivel = False
            veiculo.motivo_indisponibilidade = 'Veículo inativado'
        else:
            veiculo.disponivel = True
            veiculo.motivo_indisponibilidade = None
        
        db.session.commit()
        
        # Log de auditoria
        acao = 'VEICULO_ATIVADO' if veiculo.ativo else 'VEICULO_INATIVADO'
        criar_log_auditoria(acao, {
            'veiculo_id': veiculo.id,
            'veiculo_placa': veiculo.placa
        })
        
        status_texto = 'ativado' if veiculo.ativo else 'inativado'
        
        return jsonify({
            'success': True,
            'message': f'Veículo {status_texto} com sucesso!',
            'novo_status': veiculo.ativo
        })
        
    except Exception as e:
        current_app.logger.error(f"Erro ao ativar/inativar veículo: {e}")
        db.session.rollback()
        return jsonify({'error': 'Erro interno do servidor'}), 500

@veiculos_bp.route('/<int:id>/manutencao', methods=['POST'])
@require_module_access('veiculos')
def alterar_manutencao(id):
    """
    Coloca ou retira veículo de manutenção
    """
    if not current_user.pode_gerenciar_veiculos:
        return jsonify({'error': 'Sem permissão'}), 403
    
    try:
        veiculo = Veiculo.query.get_or_404(id)
        
        if not veiculo.ativo:
            return jsonify({'error': 'Veículo inativo não pode entrar em manutenção'}), 400
        
        data = request.get_json()
        em_manutencao = data.get('em_manutencao', False)
        motivo = data.get('motivo', '').strip()
        tipo_manutencao = data.get('tipo_manutencao', '').strip()
        
        veiculo.em_manutencao = em_manutencao
        
        if em_manutencao:
            veiculo.disponivel = False
            if motivo:
                veiculo.motivo_indisponibilidade = f"Manutenção: {motivo}"
            else:
                veiculo.motivo_indisponibilidade = "Em manutenção"
        else:
            veiculo.disponivel = True
            veiculo.motivo_indisponibilidade = None
            
            # Se saindo da manutenção, registrar como manutenção realizada
            if tipo_manutencao:
                veiculo.registrar_manutencao(tipo_manutencao)
        
        db.session.commit()
        
        # Log de auditoria
        acao = 'VEICULO_MANUTENCAO_INICIO' if em_manutencao else 'VEICULO_MANUTENCAO_FIM'
        criar_log_auditoria(acao, {
            'veiculo_id': veiculo.id,
            'veiculo_placa': veiculo.placa,
            'motivo': motivo,
            'tipo_manutencao': tipo_manutencao
        })
        
        status_texto = 'em manutenção' if em_manutencao else 'disponível'
        
        return jsonify({
            'success': True,
            'message': f'Veículo marcado como {status_texto}!',
            'em_manutencao': veiculo.em_manutencao
        })
        
    except Exception as e:
        current_app.logger.error(f"Erro ao alterar manutenção do veículo: {e}")
        db.session.rollback()
        return jsonify({'error': 'Erro interno do servidor'}), 500

@veiculos_bp.route('/buscar')
@require_module_access('veiculos')
def buscar_ajax():
    """
    Busca veículos via AJAX para autocomplete
    """
    termo = request.args.get('q', '').strip()
    limite = min(request.args.get('limit', 10, type=int), 50)
    apenas_disponiveis = request.args.get('apenas_disponiveis', 'true').lower() == 'true'
    tipo_requerido = request.args.get('tipo', '').strip()
    acessivel = request.args.get('acessivel', 'false').lower() == 'true'
    
    if len(termo) < 2:
        return jsonify([])
    
    query = Veiculo.query
    
    if apenas_disponiveis:
        query = Veiculo.veiculos_disponiveis()
    else:
        query = query.filter(Veiculo.ativo == True)
    
    # Filtrar por tipo se especificado
    if tipo_requerido:
        query = query.filter(Veiculo.tipo_veiculo == tipo_requerido)
    
    # Filtrar veículos acessíveis se necessário
    if acessivel:
        query = query.filter(Veiculo.capacidade_cadeirantes > 0)
    
    # Buscar por placa, marca, modelo ou patrimônio
    query = query.filter(
        or_(
            Veiculo.placa.contains(termo.upper()),
            Veiculo.marca.contains(termo),
            Veiculo.modelo.contains(termo),
            Veiculo.numero_patrimonio.contains(termo) if termo else False
        )
    ).limit(limite)
    
    veiculos = query.all()
    
    resultados = []
    for veiculo in veiculos:
        resultados.append({
            'id': veiculo.id,
            'placa': veiculo.placa_formatada,
            'marca': veiculo.marca,
            'modelo': veiculo.modelo,
            'tipo': veiculo.tipo_veiculo,
            'capacidade_passageiros': veiculo.capacidade_passageiros,
            'capacidade_cadeirantes': veiculo.capacidade_cadeirantes,
            'acessibilidade_total': veiculo.acessibilidade_total,
            'apto_para_uso': veiculo.apto_para_uso,
            'text': f"{veiculo.placa_formatada} - {veiculo.marca} {veiculo.modelo}"  # Para Select2
        })
    
    return jsonify(resultados)

@veiculos_bp.route('/verificar-placa')
@require_module_access('veiculos')
def verificar_placa():
    """
    Verifica se placa já existe (para validação em tempo real)
    """
    placa = request.args.get('placa', '').strip()
    veiculo_id = request.args.get('id', type=int)  # Para edição
    
    if not placa:
        return jsonify({'existe': False})
    
    placa_limpa = re.sub(r'[^A-Z0-9]', '', placa.upper())
    
    query = Veiculo.query.filter_by(placa=placa_limpa)
    
    # Excluir o próprio veículo se for edição
    if veiculo_id:
        query = query.filter(Veiculo.id != veiculo_id)
    
    veiculo_existente = query.first()
    
    return jsonify({
        'existe': veiculo_existente is not None,
        'modelo': f"{veiculo_existente.marca} {veiculo_existente.modelo}" if veiculo_existente else None
    })

@veiculos_bp.route('/verificar-renavam')
@require_module_access('veiculos')
def verificar_renavam():
    """
    Verifica se RENAVAM já existe (para validação em tempo real)
    """
    renavam = request.args.get('renavam', '').strip()
    veiculo_id = request.args.get('id', type=int)  # Para edição
    
    if not renavam:
        return jsonify({'existe': False})
    
    renavam_numeros = re.sub(r'\D', '', renavam)
    
    query = Veiculo.query.filter_by(renavam=renavam_numeros)
    
    # Excluir o próprio veículo se for edição
    if veiculo_id:
        query = query.filter(Veiculo.id != veiculo_id)
    
    veiculo_existente = query.first()
    
    return jsonify({
        'existe': veiculo_existente is not None,
        'placa': veiculo_existente.placa_formatada if veiculo_existente else None
    })

@veiculos_bp.route('/alertas-documentacao')
@require_module_access('veiculos')
def alertas_documentacao():
    """
    Retorna alertas de documentação vencendo/vencida
    """
    # Licenciamento vencendo nos próximos 30 dias
    licenciamento_vencendo = Veiculo.licenciamento_vencendo(30).all()
    
    # Licenciamento vencido
    licenciamento_vencido = Veiculo.query.filter(
        Veiculo.ativo == True,
        Veiculo.data_vencimento_licenciamento < date.today()
    ).all()
    
    # Veículos que necessitam revisão
    necessitam_revisao = Veiculo.necessitam_revisao().all()
    
    alertas = []
    
    # Licenciamento vencido
    for veiculo in licenciamento_vencido:
        dias_vencido = (date.today() - veiculo.data_vencimento_licenciamento).days
        alertas.append({
            'tipo': 'licenciamento_vencido',
            'veiculo': veiculo.placa_formatada,
            'veiculo_id': veiculo.id,
            'modelo': f"{veiculo.marca} {veiculo.modelo}",
            'data_vencimento': veiculo.data_vencimento_licenciamento.strftime('%d/%m/%Y'),
            'dias': dias_vencido,
            'urgencia': 'alta'
        })
    
    # Licenciamento vencendo
    for veiculo in licenciamento_vencendo:
        if veiculo not in licenciamento_vencido:  # Evitar duplicatas
            dias_para_vencer = (veiculo.data_vencimento_licenciamento - date.today()).days
            alertas.append({
                'tipo': 'licenciamento_vencendo',
                'veiculo': veiculo.placa_formatada,
                'veiculo_id': veiculo.id,
                'modelo': f"{veiculo.marca} {veiculo.modelo}",
                'data_vencimento': veiculo.data_vencimento_licenciamento.strftime('%d/%m/%Y'),
                'dias': dias_para_vencer,
                'urgencia': 'media' if dias_para_vencer <= 15 else 'baixa'
            })
    
    # Necessitam revisão
    for veiculo in necessitam_revisao:
        alertas.append({
            'tipo': 'revisao_necessaria',
            'veiculo': veiculo.placa_formatada,
            'veiculo_id': veiculo.id,
            'modelo': f"{veiculo.marca} {veiculo.modelo}",
            'km_atual': veiculo.quilometragem_atual,
            'proxima_revisao_km': veiculo.proxima_revisao_km,
            'proxima_revisao_data': veiculo.proxima_revisao_data.strftime('%d/%m/%Y') if veiculo.proxima_revisao_data else None,
            'urgencia': 'media'
        })
    
    return jsonify(alertas)

@veiculos_bp.route('/relatorio')
@require_module_access('veiculos')
def relatorio():
    """
    Gera relatório de veículos
    """
    if not current_user.pode_gerar_relatorios:
        flash('Você não tem permissão para gerar relatórios.', 'error')
        return redirect(url_for('veiculos.listar'))
    
    formato = request.args.get('formato', 'html')
    
    # Filtros do relatório
    status = request.args.get('status', 'todos')
    tipo_veiculo = request.args.get('tipo_veiculo', 'todos')
    situacao_doc = request.args.get('situacao_doc', 'todas')
    
    # Query base
    query = Veiculo.query
    
    # Aplicar filtros (mesmo código da listagem)
    if status == 'ativo':
        query = query.filter(Veiculo.ativo == True)
    elif status == 'inativo':
        query = query.filter(Veiculo.ativo == False)
    elif status == 'disponivel':
        query = Veiculo.veiculos_disponiveis()
    
    if tipo_veiculo != 'todos':
        query = query.filter(Veiculo.tipo_veiculo == tipo_veiculo)
    
    if situacao_doc == 'licenciamento_vencido':
        query = query.filter(Veiculo.data_vencimento_licenciamento < date.today())
    elif situacao_doc == 'licenciamento_vencendo':
        data_limite = date.today() + timedelta(days=30)
        query = query.filter(
            and_(
                Veiculo.data_vencimento_licenciamento >= date.today(),
                Veiculo.data_vencimento_licenciamento <= data_limite
            )
        )
    
    veiculos = query.order_by(Veiculo.marca, Veiculo.modelo).all()
    
    if formato == 'json':
        return jsonify([v.to_dict() for v in veiculos])
    
    elif formato == 'csv':
        import csv
        from io import StringIO
        
        output = StringIO()
        writer = csv.writer(output)
        
        # Cabeçalho
        writer.writerow([
            'Placa', 'Marca', 'Modelo', 'Ano', 'Tipo', 'Capacidade', 
            'Acessível', 'Licenciamento', 'Quilometragem', 'Status'
        ])
        
        # Dados
        for v in veiculos:
            writer.writerow([
                v.placa_formatada,
                v.marca,
                v.modelo,
                v.ano_modelo,
                v.tipo_veiculo.replace('_', ' ').title(),
                v.capacidade_passageiros,
                'Sim' if v.capacidade_cadeirantes > 0 else 'Não',
                v.data_vencimento_licenciamento.strftime('%d/%m/%Y') if v.data_vencimento_licenciamento else '',
                v.quilometragem_atual,
                'Ativo' if v.ativo else 'Inativo'
            ])
        
        output.seek(0)
        
        from flask import Response
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=veiculos.csv'}
        )
    
    # Formato HTML (padrão)
    stats = Veiculo.estatisticas()
    return render_template('veiculos_relatorio.html', 
                         veiculos=veiculos, 
                         stats=stats,
                         filtros={
                             'status': status,
                             'tipo_veiculo': tipo_veiculo,
                             'situacao_doc': situacao_doc
                         })

# === ROTAS DE API ===

@veiculos_bp.route('/api/', methods=['GET'])
@require_module_access('veiculos')
def api_listar():
    """
    API: Lista veículos
    """
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)
    apenas_disponiveis = request.args.get('disponiveis', 'false').lower() == 'true'
    
    if apenas_disponiveis:
        query = Veiculo.veiculos_disponiveis()
    else:
        query = Veiculo.query.filter_by(ativo=True)
    
    veiculos = query.paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    return jsonify({
        'veiculos': [v.to_dict() for v in veiculos.items],
        'total': veiculos.total,
        'pages': veiculos.pages,
        'current_page': veiculos.page,
        'per_page': veiculos.per_page
    })

@veiculos_bp.route('/api/<int:id>', methods=['GET'])
@require_module_access('veiculos')
def api_obter(id):
    """
    API: Obtém um veículo
    """
    veiculo = Veiculo.query.get_or_404(id)
    return jsonify(veiculo.to_dict())

@veiculos_bp.route('/api/', methods=['POST'])
@require_module_access('veiculos')
def api_criar():
    """
    API: Cria novo veículo
    """
    # Verificar permissão
    erro, status = verificar_permissao_ajax('pode_gerenciar_veiculos')
    if erro:
        return jsonify(erro), status
    
    try:
        dados = request.get_json()
        
        # Validações básicas
        if not dados or not dados.get('placa'):
            return jsonify({'error': 'Placa é obrigatória'}), 400
        
        # Verificar placa duplicada
        placa_limpa = re.sub(r'[^A-Z0-9]', '', dados.get('placa', '').upper())
        if Veiculo.buscar_por_placa(placa_limpa):
            return jsonify({'error': 'Placa já cadastrada'}), 400
        
        # Criar veículo
        veiculo = Veiculo(**dados)
        db.session.add(veiculo)
        db.session.commit()
        
        # Log de auditoria
        criar_log_auditoria('VEICULO_CRIADO_API', {
            'veiculo_id': veiculo.id,
            'veiculo_placa': veiculo.placa
        })
        
        return jsonify(veiculo.to_dict()), 201
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Erro API criar veículo: {e}")
        db.session.rollback()
        return jsonify({'error': 'Erro interno'}), 500

# === CONTEXTO DE TEMPLATE ===

@veiculos_bp.context_processor
def inject_veiculos_vars():
    """
    Injeta variáveis específicas dos veículos nos templates
    """
    return {
        'modulo_atual': 'veiculos',
        'stats_veiculos': Veiculo.estatisticas() if current_user.is_authenticated else {}
    }
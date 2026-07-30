#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de Transporte de Pacientes
Desenvolvido para a Prefeitura Municipal de Cosmópolis
Pode ser usado por terceiros autorizados

Rotas: Agendamentos
Endpoints para gerenciamento de agendamentos
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import or_, and_, desc
from datetime import datetime, date, time, timedelta
import re

from sistema.models.agendamento import Agendamento
from sistema.models.paciente import Paciente
from sistema.models.motorista import Motorista
from sistema.models.veiculo import Veiculo
from sistema.auth.utils import require_module_access, criar_log_auditoria, verificar_permissao_ajax
from db.database import db

# Criar blueprint para agendamentos
agendamentos_bp = Blueprint('agendamentos', __name__)

@agendamentos_bp.route('/')
@require_module_access('agendamentos')
def listar():
    """
    Lista todos os agendamentos com paginação e filtros
    Sistema da Prefeitura Municipal de Cosmópolis
    """
    # Parâmetros de busca e filtro
    busca = request.args.get('busca', '').strip()
    status = request.args.get('status', 'todos')
    data_inicio = request.args.get('data_inicio', '')
    data_fim = request.args.get('data_fim', '')
    tipo_atendimento = request.args.get('tipo_atendimento', 'todos')
    prioridade = request.args.get('prioridade', 'todas')
    motorista_id = request.args.get('motorista_id', type=int)
    veiculo_id = request.args.get('veiculo_id', type=int)
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 15, type=int), 100)
    
    # Query base
    query = Agendamento.query
    
    # Aplicar filtros
    if busca:
        query = query.join(Paciente).filter(
            or_(
                Paciente.nome_completo.contains(busca),
                Paciente.cpf.contains(re.sub(r'\D', '', busca)),
                Agendamento.destino_nome.contains(busca),
                Agendamento.descricao_atendimento.contains(busca)
            )
        )
    
    if status != 'todos':
        query = query.filter(Agendamento.status == status)
    
    # Filtro por data
    if data_inicio:
        try:
            data_inicio_obj = datetime.strptime(data_inicio, '%Y-%m-%d').date()
            query = query.filter(Agendamento.data_agendamento >= data_inicio_obj)
        except ValueError:
            flash('Data de início inválida.', 'error')
    
    if data_fim:
        try:
            data_fim_obj = datetime.strptime(data_fim, '%Y-%m-%d').date()
            query = query.filter(Agendamento.data_agendamento <= data_fim_obj)
        except ValueError:
            flash('Data de fim inválida.', 'error')
    
    # Se não especificou datas, mostrar apenas os próximos 30 dias por padrão
    if not data_inicio and not data_fim:
        hoje = date.today()
        limite = hoje + timedelta(days=30)
        query = query.filter(
            and_(
                Agendamento.data_agendamento >= hoje - timedelta(days=7),  # Últimos 7 dias também
                Agendamento.data_agendamento <= limite
            )
        )
    
    if tipo_atendimento != 'todos':
        query = query.filter(Agendamento.tipo_atendimento == tipo_atendimento)
    
    if prioridade != 'todas':
        query = query.filter(Agendamento.prioridade == prioridade)
    
    if motorista_id:
        query = query.filter(Agendamento.motorista_id == motorista_id)
    
    if veiculo_id:
        query = query.filter(Agendamento.veiculo_id == veiculo_id)
    
    # Ordenação
    query = query.order_by(desc(Agendamento.data_agendamento), desc(Agendamento.horario_saida))
    
    # Paginação
    agendamentos = query.paginate(
        page=page, 
        per_page=per_page, 
        error_out=False
    )
    
    # Estatísticas para o template
    stats = Agendamento.estatisticas()
    
    # Agendamentos de hoje
    agendamentos_hoje = Agendamento.agendamentos_hoje().all()
    
    # Listas para filtros
    motoristas = Motorista.motoristas_ativos().all()
    veiculos = Veiculo.veiculos_ativos().all()
    
    return render_template('agendamentos.html', 
                         agendamentos=agendamentos,
                         stats=stats,
                         agendamentos_hoje=agendamentos_hoje,
                         motoristas=motoristas,
                         veiculos=veiculos,
                         busca=busca,
                         status=status,
                         data_inicio=data_inicio,
                         data_fim=data_fim,
                         tipo_atendimento=tipo_atendimento,
                         prioridade=prioridade,
                         motorista_id=motorista_id,
                         veiculo_id=veiculo_id)

@agendamentos_bp.route('/novo', methods=['GET', 'POST'])
@require_module_access('agendamentos')
def novo():
    """
    Cadastra novo agendamento
    """
    if not current_user.pode_criar_agendamentos:
        flash('Você não tem permissão para criar agendamentos.', 'error')
        return redirect(url_for('agendamentos.listar'))
    
    if request.method == 'GET':
        # Listas para os selects
        pacientes = Paciente.pacientes_ativos().all()
        motoristas = Motorista.motoristas_habilitados().all()
        veiculos = Veiculo.veiculos_disponiveis().all()
        
        return render_template('agendamento_form.html', 
                             agendamento=None,
                             pacientes=pacientes,
                             motoristas=motoristas,
                             veiculos=veiculos)
    
    try:
        # Coletar dados do formulário
        dados = {
            'paciente_id': request.form.get('paciente_id', type=int),
            'motorista_id': request.form.get('motorista_id', type=int),
            'veiculo_id': request.form.get('veiculo_id', type=int),
            'data_agendamento': request.form.get('data_agendamento'),
            'horario_saida': request.form.get('horario_saida'),
            'horario_retorno_previsto': request.form.get('horario_retorno_previsto'),
            'destino_nome': request.form.get('destino_nome', '').strip(),
            'destino_endereco': request.form.get('destino_endereco', '').strip(),
            'destino_cidade': request.form.get('destino_cidade', 'Cosmópolis').strip(),
            'destino_uf': request.form.get('destino_uf', 'SP').strip(),
            'destino_cep': request.form.get('destino_cep', '').strip(),
            'destino_telefone': request.form.get('destino_telefone', '').strip(),
            'tipo_atendimento': request.form.get('tipo_atendimento', '').strip(),
            'especialidade': request.form.get('especialidade', '').strip(),
            'medico_responsavel': request.form.get('medico_responsavel', '').strip(),
            'descricao_atendimento': request.form.get('descricao_atendimento', '').strip(),
            'possui_acompanhante': bool(request.form.get('possui_acompanhante')),
            'nome_acompanhante': request.form.get('nome_acompanhante', '').strip(),
            'telefone_acompanhante': request.form.get('telefone_acompanhante', '').strip(),
            'prioridade': request.form.get('prioridade', 'normal').strip(),
            'eh_retorno': bool(request.form.get('eh_retorno')),
            'observacoes': request.form.get('observacoes', '').strip()
        }
        
        # Validações básicas
        if not dados['paciente_id']:
            flash('Paciente é obrigatório.', 'error')
            return redirect(url_for('agendamentos.novo'))
        
        if not dados['motorista_id']:
            flash('Motorista é obrigatório.', 'error')
            return redirect(url_for('agendamentos.novo'))
        
        if not dados['veiculo_id']:
            flash('Veículo é obrigatório.', 'error')
            return redirect(url_for('agendamentos.novo'))
        
        # Converter data e horários
        if dados['data_agendamento']:
            dados['data_agendamento'] = datetime.strptime(dados['data_agendamento'], '%Y-%m-%d').date()
        
        if dados['horario_saida']:
            dados['horario_saida'] = datetime.strptime(dados['horario_saida'], '%H:%M').time()
        
        if dados['horario_retorno_previsto']:
            dados['horario_retorno_previsto'] = datetime.strptime(dados['horario_retorno_previsto'], '%H:%M').time()
        
        # Limpar campos vazios opcionais
        for campo in ['destino_cep', 'destino_telefone', 'especialidade', 'medico_responsavel', 
                     'descricao_atendimento', 'nome_acompanhante', 'telefone_acompanhante', 
                     'observacoes']:
            if not dados[campo]:
                dados[campo] = None
        
        # Criar agendamento temporário para validações
        agendamento = Agendamento(**dados)
        
        # Validar disponibilidades
        motorista_ok, msg_motorista = agendamento.validar_disponibilidade_motorista()
        if not motorista_ok:
            flash(f'Erro - Motorista: {msg_motorista}', 'error')
            return redirect(url_for('agendamentos.novo'))
        
        veiculo_ok, msg_veiculo = agendamento.validar_disponibilidade_veiculo()
        if not veiculo_ok:
            flash(f'Erro - Veículo: {msg_veiculo}', 'error')
            return redirect(url_for('agendamentos.novo'))
        
        paciente_ok, msg_paciente = agendamento.validar_disponibilidade_paciente()
        if not paciente_ok:
            flash(f'Erro - Paciente: {msg_paciente}', 'error')
            return redirect(url_for('agendamentos.novo'))
        
        capacidade_ok, msg_capacidade = agendamento.validar_capacidade_veiculo()
        if not capacidade_ok:
            flash(f'Erro - Capacidade: {msg_capacidade}', 'error')
            return redirect(url_for('agendamentos.novo'))
        
        # Salvar agendamento
        db.session.add(agendamento)
        db.session.commit()
        
        # Log de auditoria
        criar_log_auditoria('AGENDAMENTO_CRIADO', {
            'agendamento_id': agendamento.id,
            'paciente_nome': agendamento.paciente.nome_completo,
            'data_agendamento': agendamento.data_agendamento.strftime('%d/%m/%Y'),
            'horario': agendamento.horario_saida.strftime('%H:%M')
        })
        
        flash(f'Agendamento criado com sucesso para {agendamento.paciente.nome_completo}!', 'success')
        return redirect(url_for('agendamentos.visualizar', id=agendamento.id))
        
    except ValueError as e:
        flash(str(e), 'error')
        return redirect(url_for('agendamentos.novo'))
    except Exception as e:
        current_app.logger.error(f"Erro ao criar agendamento: {e}")
        db.session.rollback()
        flash('Erro ao criar agendamento. Verifique os dados e tente novamente.', 'error')
        return redirect(url_for('agendamentos.novo'))

@agendamentos_bp.route('/<int:id>')
@require_module_access('agendamentos')
def visualizar(id):
    """
    Visualiza detalhes de um agendamento
    """
    agendamento = Agendamento.query.get_or_404(id)
    
    # Histórico de agendamentos do paciente
    historico = Agendamento.query.filter(
        Agendamento.paciente_id == agendamento.paciente_id,
        Agendamento.id != agendamento.id
    ).order_by(desc(Agendamento.data_agendamento)).limit(5).all()
    
    return render_template('agendamento_detalhes.html', 
                         agendamento=agendamento,
                         historico=historico)

@agendamentos_bp.route('/<int:id>/editar', methods=['GET', 'POST'])
@require_module_access('agendamentos')
def editar(id):
    """
    Edita dados de um agendamento
    """
    if not current_user.pode_editar_agendamentos:
        flash('Você não tem permissão para editar agendamentos.', 'error')
        return redirect(url_for('agendamentos.visualizar', id=id))
    
    agendamento = Agendamento.query.get_or_404(id)
    
    # Verificar se agendamento pode ser editado
    if agendamento.status in ['concluido', 'cancelado']:
        flash('Agendamentos concluídos ou cancelados não podem ser editados.', 'error')
        return redirect(url_for('agendamentos.visualizar', id=id))
    
    if agendamento.eh_passado:
        flash('Agendamentos passados não podem ser editados.', 'error')
        return redirect(url_for('agendamentos.visualizar', id=id))
    
    if request.method == 'GET':
        # Listas para os selects
        pacientes = Paciente.pacientes_ativos().all()
        motoristas = Motorista.motoristas_habilitados().all()
        veiculos = Veiculo.veiculos_disponiveis().all()
        
        return render_template('agendamento_form.html', 
                             agendamento=agendamento,
                             pacientes=pacientes,
                             motoristas=motoristas,
                             veiculos=veiculos)
    
    try:
        # Coletar dados do formulário (mesmo código do novo)
        dados = {
            'paciente_id': request.form.get('paciente_id', type=int),
            'motorista_id': request.form.get('motorista_id', type=int),
            'veiculo_id': request.form.get('veiculo_id', type=int),
            'data_agendamento': request.form.get('data_agendamento'),
            'horario_saida': request.form.get('horario_saida'),
            'horario_retorno_previsto': request.form.get('horario_retorno_previsto'),
            'destino_nome': request.form.get('destino_nome', '').strip(),
            'destino_endereco': request.form.get('destino_endereco', '').strip(),
            'destino_cidade': request.form.get('destino_cidade', 'Cosmópolis').strip(),
            'destino_uf': request.form.get('destino_uf', 'SP').strip(),
            'destino_cep': request.form.get('destino_cep', '').strip(),
            'destino_telefone': request.form.get('destino_telefone', '').strip(),
            'tipo_atendimento': request.form.get('tipo_atendimento', '').strip(),
            'especialidade': request.form.get('especialidade', '').strip(),
            'medico_responsavel': request.form.get('medico_responsavel', '').strip(),
            'descricao_atendimento': request.form.get('descricao_atendimento', '').strip(),
            'possui_acompanhante': bool(request.form.get('possui_acompanhante')),
            'nome_acompanhante': request.form.get('nome_acompanhante', '').strip(),
            'telefone_acompanhante': request.form.get('telefone_acompanhante', '').strip(),
            'prioridade': request.form.get('prioridade', 'normal').strip(),
            'observacoes': request.form.get('observacoes', '').strip()
        }
        
        # Converter data e horários
        if dados['data_agendamento']:
            dados['data_agendamento'] = datetime.strptime(dados['data_agendamento'], '%Y-%m-%d').date()
        
        if dados['horario_saida']:
            dados['horario_saida'] = datetime.strptime(dados['horario_saida'], '%H:%M').time()
        
        if dados['horario_retorno_previsto']:
            dados['horario_retorno_previsto'] = datetime.strptime(dados['horario_retorno_previsto'], '%H:%M').time()
        
        # Limpar campos vazios opcionais
        for campo in ['destino_cep', 'destino_telefone', 'especialidade', 'medico_responsavel', 
                     'descricao_atendimento', 'nome_acompanhante', 'telefone_acompanhante', 
                     'observacoes']:
            if not dados[campo]:
                dados[campo] = None
        
        # Atualizar dados
        for campo, valor in dados.items():
            setattr(agendamento, campo, valor)
        
        # Validar disponibilidades se mudou motorista, veículo ou horário
        motorista_ok, msg_motorista = agendamento.validar_disponibilidade_motorista()
        if not motorista_ok:
            flash(f'Erro - Motorista: {msg_motorista}', 'error')
            db.session.rollback()
            return redirect(url_for('agendamentos.editar', id=id))
        
        veiculo_ok, msg_veiculo = agendamento.validar_disponibilidade_veiculo()
        if not veiculo_ok:
            flash(f'Erro - Veículo: {msg_veiculo}', 'error')
            db.session.rollback()
            return redirect(url_for('agendamentos.editar', id=id))
        
        paciente_ok, msg_paciente = agendamento.validar_disponibilidade_paciente()
        if not paciente_ok:
            flash(f'Erro - Paciente: {msg_paciente}', 'error')
            db.session.rollback()
            return redirect(url_for('agendamentos.editar', id=id))
        
        capacidade_ok, msg_capacidade = agendamento.validar_capacidade_veiculo()
        if not capacidade_ok:
            flash(f'Erro - Capacidade: {msg_capacidade}', 'error')
            db.session.rollback()
            return redirect(url_for('agendamentos.editar', id=id))
        
        db.session.commit()
        
        # Log de auditoria
        criar_log_auditoria('AGENDAMENTO_EDITADO', {
            'agendamento_id': agendamento.id,
            'paciente_nome': agendamento.paciente.nome_completo
        })
        
        flash('Agendamento atualizado com sucesso!', 'success')
        return redirect(url_for('agendamentos.visualizar', id=agendamento.id))
        
    except ValueError as e:
        flash(str(e), 'error')
        db.session.rollback()
        return redirect(url_for('agendamentos.editar', id=id))
    except Exception as e:
        current_app.logger.error(f"Erro ao editar agendamento: {e}")
        db.session.rollback()
        flash('Erro ao atualizar agendamento. Tente novamente.', 'error')
        return redirect(url_for('agendamentos.editar', id=id))

@agendamentos_bp.route('/<int:id>/confirmar', methods=['POST'])
@require_module_access('agendamentos')
def confirmar(id):
    """
    Confirma um agendamento
    """
    if not current_user.pode_editar_agendamentos:
        return jsonify({'error': 'Sem permissão'}), 403
    
    try:
        agendamento = Agendamento.query.get_or_404(id)
        
        if not agendamento.pode_confirmar:
            return jsonify({'error': 'Agendamento não pode ser confirmado'}), 400
        
        data = request.get_json() or {}
        confirmado_por = data.get('confirmado_por', current_user.nome)
        telefone = data.get('telefone_confirmacao', '')
        
        agendamento.confirmar(confirmado_por, telefone)
        db.session.commit()
        
        # Log de auditoria
        criar_log_auditoria('AGENDAMENTO_CONFIRMADO', {
            'agendamento_id': agendamento.id,
            'paciente_nome': agendamento.paciente.nome_completo,
            'confirmado_por': confirmado_por
        })
        
        return jsonify({
            'success': True,
            'message': 'Agendamento confirmado com sucesso!',
            'novo_status': agendamento.status
        })
        
    except Exception as e:
        current_app.logger.error(f"Erro ao confirmar agendamento: {e}")
        db.session.rollback()
        return jsonify({'error': 'Erro interno do servidor'}), 500

@agendamentos_bp.route('/<int:id>/cancelar', methods=['POST'])
@require_module_access('agendamentos')
def cancelar(id):
    """
    Cancela um agendamento
    """
    if not current_user.pode_cancelar_agendamentos:
        return jsonify({'error': 'Sem permissão'}), 403
    
    try:
        agendamento = Agendamento.query.get_or_404(id)
        
        if not agendamento.pode_cancelar:
            return jsonify({'error': 'Agendamento não pode ser cancelado'}), 400
        
        data = request.get_json() or {}
        motivo = data.get('motivo', '').strip()
        cancelado_por = data.get('cancelado_por', current_user.nome)
        
        if not motivo:
            return jsonify({'error': 'Motivo do cancelamento é obrigatório'}), 400
        
        agendamento.cancelar(motivo, cancelado_por)
        db.session.commit()
        
        # Log de auditoria
        criar_log_auditoria('AGENDAMENTO_CANCELADO', {
            'agendamento_id': agendamento.id,
            'paciente_nome': agendamento.paciente.nome_completo,
            'motivo': motivo,
            'cancelado_por': cancelado_por
        })
        
        return jsonify({
            'success': True,
            'message': 'Agendamento cancelado com sucesso!',
            'novo_status': agendamento.status
        })
        
    except Exception as e:
        current_app.logger.error(f"Erro ao cancelar agendamento: {e}")
        db.session.rollback()
        return jsonify({'error': 'Erro interno do servidor'}), 500

@agendamentos_bp.route('/<int:id>/iniciar-viagem', methods=['POST'])
@require_module_access('agendamentos')
def iniciar_viagem(id):
    """
    Inicia a viagem de um agendamento
    """
    if not current_user.pode_editar_agendamentos:
        return jsonify({'error': 'Sem permissão'}), 403
    
    try:
        agendamento = Agendamento.query.get_or_404(id)
        
        if agendamento.status != 'confirmado':
            return jsonify({'error': 'Apenas agendamentos confirmados podem ser iniciados'}), 400
        
        data = request.get_json() or {}
        km_inicial = data.get('km_inicial', type=int)
        
        agendamento.iniciar_viagem(km_inicial)
        db.session.commit()
        
        # Log de auditoria
        criar_log_auditoria('VIAGEM_INICIADA', {
            'agendamento_id': agendamento.id,
            'paciente_nome': agendamento.paciente.nome_completo,
            'km_inicial': km_inicial
        })
        
        return jsonify({
            'success': True,
            'message': 'Viagem iniciada com sucesso!',
            'novo_status': agendamento.status,
            'horario_saida_real': agendamento.horario_saida_real.strftime('%H:%M') if agendamento.horario_saida_real else None
        })
        
    except Exception as e:
        current_app.logger.error(f"Erro ao iniciar viagem: {e}")
        db.session.rollback()
        return jsonify({'error': 'Erro interno do servidor'}), 500

@agendamentos_bp.route('/<int:id>/finalizar-viagem', methods=['POST'])
@require_module_access('agendamentos')
def finalizar_viagem(id):
    """
    Finaliza a viagem de um agendamento
    """
    if not current_user.pode_editar_agendamentos:
        return jsonify({'error': 'Sem permissão'}), 403
    
    try:
        agendamento = Agendamento.query.get_or_404(id)
        
        if agendamento.status != 'em_andamento':
            return jsonify({'error': 'Apenas agendamentos em andamento podem ser finalizados'}), 400
        
        data = request.get_json() or {}
        km_final = data.get('km_final', type=int)
        observacoes_motorista = data.get('observacoes_motorista', '').strip()
        
        agendamento.finalizar_viagem(km_final, observacoes_motorista)
        
        # Atualizar quilometragem do veículo
        if km_final and agendamento.veiculo:
            agendamento.veiculo.atualizar_quilometragem(km_final)
        
        db.session.commit()
        
        # Log de auditoria
        criar_log_auditoria('VIAGEM_FINALIZADA', {
            'agendamento_id': agendamento.id,
            'paciente_nome': agendamento.paciente.nome_completo,
            'km_final': km_final,
            'km_percorrido': agendamento.km_percorrido
        })
        
        return jsonify({
            'success': True,
            'message': 'Viagem finalizada com sucesso!',
            'novo_status': agendamento.status,
            'horario_retorno_real': agendamento.horario_retorno_real.strftime('%H:%M') if agendamento.horario_retorno_real else None,
            'km_percorrido': agendamento.km_percorrido
        })
        
    except Exception as e:
        current_app.logger.error(f"Erro ao finalizar viagem: {e}")
        db.session.rollback()
        return jsonify({'error': 'Erro interno do servidor'}), 500

@agendamentos_bp.route('/<int:id>/nao-compareceu', methods=['POST'])
@require_module_access('agendamentos')
def nao_compareceu(id):
    """
    Marca agendamento como não compareceu
    """
    if not current_user.pode_editar_agendamentos:
        return jsonify({'error': 'Sem permissão'}), 403
    
    try:
        agendamento = Agendamento.query.get_or_404(id)
        
        if agendamento.status not in ['agendado', 'confirmado']:
            return jsonify({'error': 'Status do agendamento não permite esta ação'}), 400
        
        data = request.get_json() or {}
        motivo = data.get('motivo', '').strip()
        
        agendamento.registrar_nao_comparecimento(motivo)
        db.session.commit()
        
        # Log de auditoria
        criar_log_auditoria('AGENDAMENTO_NAO_COMPARECEU', {
            'agendamento_id': agendamento.id,
            'paciente_nome': agendamento.paciente.nome_completo,
            'motivo': motivo
        })
        
        return jsonify({
            'success': True,
            'message': 'Não comparecimento registrado!',
            'novo_status': agendamento.status
        })
        
    except Exception as e:
        current_app.logger.error(f"Erro ao registrar não comparecimento: {e}")
        db.session.rollback()
        return jsonify({'error': 'Erro interno do servidor'}), 500

@agendamentos_bp.route('/verificar-disponibilidade')
@require_module_access('agendamentos')
def verificar_disponibilidade():
    """
    Verifica disponibilidade de motorista e veículo para agendamento
    """
    motorista_id = request.args.get('motorista_id', type=int)
    veiculo_id = request.args.get('veiculo_id', type=int)
    data_agendamento = request.args.get('data_agendamento')
    horario_saida = request.args.get('horario_saida')
    horario_retorno = request.args.get('horario_retorno')
    agendamento_id = request.args.get('agendamento_id', type=int)  # Para edição
    
    if not all([motorista_id, veiculo_id, data_agendamento, horario_saida]):
        return jsonify({'error': 'Parâmetros insuficientes'}), 400
    
    try:
        # Converter data e horários
        data_obj = datetime.strptime(data_agendamento, '%Y-%m-%d').date()
        horario_saida_obj = datetime.strptime(horario_saida, '%H:%M').time()
        horario_retorno_obj = None
        
        if horario_retorno:
            horario_retorno_obj = datetime.strptime(horario_retorno, '%H:%M').time()
        
        # Verificar disponibilidade
        resultado = Agendamento.verificar_disponibilidade(
            motorista_id, veiculo_id, data_obj, horario_saida_obj, horario_retorno_obj
        )
        
        # Se for edição, excluir o próprio agendamento da verificação
        if agendamento_id:
            # Implementar lógica específica para edição se necessário
            pass
        
        return jsonify(resultado)
        
    except ValueError as e:
        return jsonify({'error': 'Formato de data/hora inválido'}), 400
    except Exception as e:
        current_app.logger.error(f"Erro ao verificar disponibilidade: {e}")
        return jsonify({'error': 'Erro interno'}), 500

@agendamentos_bp.route('/agenda')
@require_module_access('agendamentos')
def agenda():
    """
    Visualização em formato de agenda/calendário
    """
    # Parâmetros
    data_inicio = request.args.get('data_inicio')
    data_fim = request.args.get('data_fim')
    
    # Se não especificado, mostrar semana atual
    if not data_inicio:
        hoje = date.today()
        inicio_semana = hoje - timedelta(days=hoje.weekday())
        data_inicio = inicio_semana.strftime('%Y-%m-%d')
    
    if not data_fim:
        data_inicio_obj = datetime.strptime(data_inicio, '%Y-%m-%d').date()
        data_fim_obj = data_inicio_obj + timedelta(days=6)
        data_fim = data_fim_obj.strftime('%Y-%m-%d')
    
    # Buscar agendamentos do período
    agendamentos = Agendamento.buscar_por_data(
        datetime.strptime(data_inicio, '%Y-%m-%d').date(),
        datetime.strptime(data_fim, '%Y-%m-%d').date()
    ).all()
    
    # Organizar por data
    agenda = {}
    data_atual = datetime.strptime(data_inicio, '%Y-%m-%d').date()
    data_final = datetime.strptime(data_fim, '%Y-%m-%d').date()
    
    while data_atual <= data_final:
        agenda[data_atual] = []
        data_atual += timedelta(days=1)
    
    for agendamento in agendamentos:
        if agendamento.data_agendamento in agenda:
            agenda[agendamento.data_agendamento].append(agendamento)
    
    return render_template('agenda.html', 
                         agenda=agenda,
                         data_inicio=data_inicio,
                         data_fim=data_fim)

@agendamentos_bp.route('/relatorio')
@require_module_access('agendamentos')
def relatorio():
    """
    Gera relatório de agendamentos
    """
    if not current_user.pode_gerar_relatorios:
        flash('Você não tem permissão para gerar relatórios.', 'error')
        return redirect(url_for('agendamentos.listar'))
    
    formato = request.args.get('formato', 'html')
    
    # Filtros do relatório
    data_inicio = request.args.get('data_inicio', '')
    data_fim = request.args.get('data_fim', '')
    status = request.args.get('status', 'todos')
    tipo_atendimento = request.args.get('tipo_atendimento', 'todos')
    
    # Query base
    query = Agendamento.query
    
    # Aplicar filtros
    if data_inicio:
        data_inicio_obj = datetime.strptime(data_inicio, '%Y-%m-%d').date()
        query = query.filter(Agendamento.data_agendamento >= data_inicio_obj)
    
    if data_fim:
        data_fim_obj = datetime.strptime(data_fim, '%Y-%m-%d').date()
        query = query.filter(Agendamento.data_agendamento <= data_fim_obj)
    
    if status != 'todos':
        query = query.filter(Agendamento.status == status)
    
    if tipo_atendimento != 'todos':
        query = query.filter(Agendamento.tipo_atendimento == tipo_atendimento)
    
    agendamentos = query.order_by(Agendamento.data_agendamento, Agendamento.horario_saida).all()
    
    if formato == 'json':
        return jsonify([a.to_dict() for a in agendamentos])
    
    elif formato == 'csv':
        import csv
        from io import StringIO
        
        output = StringIO()
        writer = csv.writer(output)
        
        # Cabeçalho
        writer.writerow([
            'Data', 'Horário', 'Paciente', 'Motorista', 'Veículo', 
            'Destino', 'Tipo Atendimento', 'Status', 'Km Percorrido'
        ])
        
        # Dados
        for a in agendamentos:
            writer.writerow([
                a.data_agendamento.strftime('%d/%m/%Y'),
                a.horario_saida.strftime('%H:%M'),
                a.paciente.nome_completo,
                a.motorista.nome_completo,
                a.veiculo.placa_formatada,
                a.destino_nome,
                a.tipo_atendimento.title(),
                a.status.replace('_', ' ').title(),
                a.km_percorrido or ''
            ])
        
        output.seek(0)
        
        from flask import Response
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=agendamentos.csv'}
        )
    
    # Formato HTML (padrão)
    stats = Agendamento.estatisticas()
    return render_template('agendamentos_relatorio.html', 
                         agendamentos=agendamentos, 
                         stats=stats,
                         filtros={
                             'data_inicio': data_inicio,
                             'data_fim': data_fim,
                             'status': status,
                             'tipo_atendimento': tipo_atendimento
                         })

# === ROTAS DE API ===

@agendamentos_bp.route('/api/', methods=['GET'])
@require_module_access('agendamentos')
def api_listar():
    """
    API: Lista agendamentos
    """
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)
    data_inicio = request.args.get('data_inicio')
    data_fim = request.args.get('data_fim')
    status = request.args.get('status')
    
    query = Agendamento.query
    
    if data_inicio:
        data_inicio_obj = datetime.strptime(data_inicio, '%Y-%m-%d').date()
        query = query.filter(Agendamento.data_agendamento >= data_inicio_obj)
    
    if data_fim:
        data_fim_obj = datetime.strptime(data_fim, '%Y-%m-%d').date()
        query = query.filter(Agendamento.data_agendamento <= data_fim_obj)
    
    if status:
        query = query.filter(Agendamento.status == status)
    
    agendamentos = query.order_by(desc(Agendamento.data_agendamento)).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    return jsonify({
        'agendamentos': [a.to_dict() for a in agendamentos.items],
        'total': agendamentos.total,
        'pages': agendamentos.pages,
        'current_page': agendamentos.page,
        'per_page': agendamentos.per_page
    })

@agendamentos_bp.route('/api/<int:id>', methods=['GET'])
@require_module_access('agendamentos')
def api_obter(id):
    """
    API: Obtém um agendamento
    """
    agendamento = Agendamento.query.get_or_404(id)
    return jsonify(agendamento.to_dict())

@agendamentos_bp.route('/api/', methods=['POST'])
@require_module_access('agendamentos')
def api_criar():
    """
    API: Cria novo agendamento
    """
    # Verificar permissão
    erro, status_code = verificar_permissao_ajax('pode_criar_agendamentos')
    if erro:
        return jsonify(erro), status_code
    
    try:
        dados = request.get_json()
        
        # Validações básicas
        if not dados or not dados.get('paciente_id'):
            return jsonify({'error': 'Paciente é obrigatório'}), 400
        
        # Criar agendamento
        agendamento = Agendamento(**dados)
        
        # Validar disponibilidades
        motorista_ok, msg_motorista = agendamento.validar_disponibilidade_motorista()
        if not motorista_ok:
            return jsonify({'error': f'Motorista: {msg_motorista}'}), 400
        
        veiculo_ok, msg_veiculo = agendamento.validar_disponibilidade_veiculo()
        if not veiculo_ok:
            return jsonify({'error': f'Veículo: {msg_veiculo}'}), 400
        
        db.session.add(agendamento)
        db.session.commit()
        
        # Log de auditoria
        criar_log_auditoria('AGENDAMENTO_CRIADO_API', {
            'agendamento_id': agendamento.id,
            'paciente_nome': agendamento.paciente.nome_completo
        })
        
        return jsonify(agendamento.to_dict()), 201
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Erro API criar agendamento: {e}")
        db.session.rollback()
        return jsonify({'error': 'Erro interno'}), 500

# === CONTEXTO DE TEMPLATE ===

@agendamentos_bp.context_processor
def inject_agendamentos_vars():
    """
    Injeta variáveis específicas dos agendamentos nos templates
    """
    return {
        'modulo_atual': 'agendamentos',
        'stats_agendamentos': Agendamento.estatisticas() if current_user.is_authenticated else {}
    }
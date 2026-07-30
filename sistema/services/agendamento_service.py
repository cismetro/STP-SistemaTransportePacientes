#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de Transporte de Pacientes
Desenvolvido para a Prefeitura Municipal de Cosmópolis
Pode ser usado por terceiros autorizados

Serviços: Agendamento
Regras de negócio e operações complexas para agendamentos
"""

from datetime import datetime, date, time, timedelta
from typing import List, Dict, Tuple, Optional, Any
from sqlalchemy import and_, or_, func, text
from flask import current_app
import json

from sistema.models.agendamento import Agendamento
from sistema.models.paciente import Paciente
from sistema.models.motorista import Motorista
from sistema.models.veiculo import Veiculo
from sistema.status.status_enum import StatusAgendamento, PrioridadeAgendamento, ConfiguracaoSistema
from db.database import db

class AgendamentoService:
    """
    Serviço para gerenciamento de agendamentos
    Sistema da Prefeitura Municipal de Cosmópolis
    """
    
    def __init__(self):
        self.config = ConfiguracaoSistema()
    
    # === CRIAÇÃO E VALIDAÇÃO ===
    
    def criar_agendamento(self, dados: Dict[str, Any], usuario_id: int) -> Tuple[bool, str, Optional[Agendamento]]:
        """
        Cria um novo agendamento com todas as validações
        
        Args:
            dados: Dicionário com dados do agendamento
            usuario_id: ID do usuário que está criando
            
        Returns:
            Tuple (sucesso, mensagem, agendamento)
        """
        try:
            # Validações preliminares
            sucesso, mensagem = self._validar_dados_agendamento(dados)
            if not sucesso:
                return False, mensagem, None
            
            # Verificar disponibilidades
            disponibilidade = self.verificar_disponibilidade_completa(
                dados['motorista_id'],
                dados['veiculo_id'],
                dados['paciente_id'],
                dados['data_agendamento'],
                dados['horario_saida'],
                dados.get('horario_retorno_previsto')
            )
            
            if not disponibilidade['disponivel']:
                return False, disponibilidade['mensagem'], None
            
            # Criar agendamento
            agendamento = Agendamento(**dados)
            
            # Aplicar regras de negócio específicas
            self._aplicar_regras_negocio(agendamento)
            
            db.session.add(agendamento)
            db.session.commit()
            
            # Gerar agendamento de retorno se necessário
            if dados.get('gerar_retorno', False):
                self._criar_agendamento_retorno(agendamento)
            
            return True, "Agendamento criado com sucesso", agendamento
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Erro ao criar agendamento: {e}")
            return False, f"Erro interno: {str(e)}", None
    
    def _validar_dados_agendamento(self, dados: Dict[str, Any]) -> Tuple[bool, str]:
        """Valida dados básicos do agendamento"""
        
        # Campos obrigatórios
        campos_obrigatorios = ['paciente_id', 'motorista_id', 'veiculo_id', 
                              'data_agendamento', 'horario_saida', 'destino_nome']
        
        for campo in campos_obrigatorios:
            if not dados.get(campo):
                return False, f"Campo '{campo}' é obrigatório"
        
        # Validar data não seja passada
        data_agendamento = dados['data_agendamento']
        if isinstance(data_agendamento, str):
            data_agendamento = datetime.strptime(data_agendamento, '%Y-%m-%d').date()
        
        if data_agendamento < date.today():
            return False, "Não é possível agendar para datas passadas"
        
        # Validar horário de funcionamento
        horario_saida = dados['horario_saida']
        if isinstance(horario_saida, str):
            horario_saida = datetime.strptime(horario_saida, '%H:%M').time()
        
        if not self._horario_dentro_funcionamento(horario_saida):
            return False, f"Horário deve estar entre {self.config.HORARIO_INICIO_PADRAO} e {self.config.HORARIO_FIM_PADRAO}"
        
        # Validar dia de funcionamento
        if not self.config.is_dia_funcionamento(data_agendamento):
            return False, "Agendamentos só podem ser feitos em dias úteis"
        
        # Validar antecedência mínima
        agora = datetime.now()
        data_hora_agendamento = datetime.combine(data_agendamento, horario_saida)
        
        if (data_hora_agendamento - agora).total_seconds() < (self.config.ANTECEDENCIA_MINIMA * 3600):
            return False, f"Agendamento deve ser feito com pelo menos {self.config.ANTECEDENCIA_MINIMA} horas de antecedência"
        
        return True, "Dados válidos"
    
    def _aplicar_regras_negocio(self, agendamento: Agendamento):
        """Aplica regras de negócio específicas ao agendamento"""
        
        # Definir prioridade automática baseada no tipo de atendimento
        if not agendamento.prioridade or agendamento.prioridade == 'normal':
            if agendamento.tipo_atendimento in ['cirurgia', 'quimioterapia', 'radioterapia']:
                agendamento.prioridade = 'alta'
            elif agendamento.tipo_atendimento == 'hemodialise':
                agendamento.prioridade = 'urgente'
        
        # Configurar acompanhante para menores de idade automaticamente
        if agendamento.paciente and agendamento.paciente.eh_menor_idade:
            agendamento.possui_acompanhante = True
            if not agendamento.nome_acompanhante and agendamento.paciente.nome_responsavel:
                agendamento.nome_acompanhante = agendamento.paciente.nome_responsavel
                agendamento.telefone_acompanhante = agendamento.paciente.telefone_responsavel
        
        # Configurar horário de retorno padrão se não informado
        if not agendamento.horario_retorno_previsto:
            agendamento.horario_retorno_previsto = self._calcular_horario_retorno_padrao(
                agendamento.horario_saida, agendamento.tipo_atendimento
            )
    
    def _horario_dentro_funcionamento(self, horario: time) -> bool:
        """Verifica se horário está dentro do funcionamento"""
        inicio = datetime.strptime(self.config.HORARIO_INICIO_PADRAO, '%H:%M').time()
        fim = datetime.strptime(self.config.HORARIO_FIM_PADRAO, '%H:%M').time()
        return inicio <= horario <= fim
    
    def _calcular_horario_retorno_padrao(self, horario_saida: time, tipo_atendimento: str) -> time:
        """Calcula horário de retorno baseado no tipo de atendimento"""
        
        # Duração padrão por tipo (em minutos)
        duracoes = {
            'exame': 120,           # 2 horas
            'consulta': 90,         # 1h30
            'procedimento': 180,    # 3 horas
            'cirurgia': 360,        # 6 horas
            'fisioterapia': 90,     # 1h30
            'quimioterapia': 240,   # 4 horas
            'radioterapia': 120,    # 2 horas
            'hemodialise': 300,     # 5 horas
            'retorno': 60           # 1 hora
        }
        
        duracao = duracoes.get(tipo_atendimento, 120)  # Padrão 2 horas
        
        # Converter para datetime, somar duração e voltar para time
        hoje = date.today()
        dt_saida = datetime.combine(hoje, horario_saida)
        dt_retorno = dt_saida + timedelta(minutes=duracao)
        
        return dt_retorno.time()
    
    # === VERIFICAÇÃO DE DISPONIBILIDADE ===
    
    def verificar_disponibilidade_completa(self, motorista_id: int, veiculo_id: int, 
                                         paciente_id: int, data_agendamento, 
                                         horario_saida, horario_retorno=None) -> Dict[str, Any]:
        """
        Verifica disponibilidade completa para um agendamento
        
        Returns:
            Dict com resultado da verificação
        """
        resultado = {
            'disponivel': True,
            'mensagem': '',
            'conflitos': [],
            'avisos': []
        }
        
        # Verificar motorista
        motorista_ok, msg_motorista = self._verificar_disponibilidade_motorista(
            motorista_id, data_agendamento, horario_saida, horario_retorno
        )
        
        if not motorista_ok:
            resultado['disponivel'] = False
            resultado['mensagem'] = f"Motorista: {msg_motorista}"
            resultado['conflitos'].append({
                'tipo': 'motorista',
                'mensagem': msg_motorista
            })
        
        # Verificar veículo
        veiculo_ok, msg_veiculo = self._verificar_disponibilidade_veiculo(
            veiculo_id, data_agendamento, horario_saida, horario_retorno
        )
        
        if not veiculo_ok:
            resultado['disponivel'] = False
            if not resultado['mensagem']:
                resultado['mensagem'] = f"Veículo: {msg_veiculo}"
            resultado['conflitos'].append({
                'tipo': 'veiculo',
                'mensagem': msg_veiculo
            })
        
        # Verificar paciente
        paciente_ok, msg_paciente = self._verificar_disponibilidade_paciente(
            paciente_id, data_agendamento, horario_saida, horario_retorno
        )
        
        if not paciente_ok:
            resultado['disponivel'] = False
            if not resultado['mensagem']:
                resultado['mensagem'] = f"Paciente: {msg_paciente}"
            resultado['conflitos'].append({
                'tipo': 'paciente',
                'mensagem': msg_paciente
            })
        
        # Verificar compatibilidade paciente-veículo
        compatibilidade_ok, msg_compatibilidade = self._verificar_compatibilidade_paciente_veiculo(
            paciente_id, veiculo_id
        )
        
        if not compatibilidade_ok:
            resultado['disponivel'] = False
            if not resultado['mensagem']:
                resultado['mensagem'] = f"Compatibilidade: {msg_compatibilidade}"
            resultado['conflitos'].append({
                'tipo': 'compatibilidade',
                'mensagem': msg_compatibilidade
            })
        
        # Verificar avisos (não bloqueiam, mas alertam)
        avisos = self._verificar_avisos(motorista_id, veiculo_id, data_agendamento)
        resultado['avisos'] = avisos
        
        return resultado
    
    def _verificar_disponibilidade_motorista(self, motorista_id: int, data_agendamento, 
                                           horario_saida, horario_retorno=None) -> Tuple[bool, str]:
        """Verifica disponibilidade do motorista"""
        
        motorista = Motorista.query.get(motorista_id)
        if not motorista:
            return False, "Motorista não encontrado"
        
        if not motorista.ativo:
            return False, "Motorista está inativo"
        
        if not motorista.disponivel:
            return False, f"Motorista indisponível: {motorista.motivo_indisponibilidade or 'Sem motivo informado'}"
        
        if not motorista.habilitado_para_transporte_pacientes:
            return False, "Motorista não está habilitado para transporte de pacientes"
        
        # Verificar conflitos de horário
        conflitos = self._buscar_conflitos_horario(
            'motorista', motorista_id, data_agendamento, horario_saida, horario_retorno
        )
        
        if conflitos:
            horarios_conflito = [f"{c.horario_saida.strftime('%H:%M')}" for c in conflitos]
            return False, f"Motorista já possui agendamento(s) nos horários: {', '.join(horarios_conflito)}"
        
        return True, "Motorista disponível"
    
    def _verificar_disponibilidade_veiculo(self, veiculo_id: int, data_agendamento, 
                                         horario_saida, horario_retorno=None) -> Tuple[bool, str]:
        """Verifica disponibilidade do veículo"""
        
        veiculo = Veiculo.query.get(veiculo_id)
        if not veiculo:
            return False, "Veículo não encontrado"
        
        if not veiculo.apto_para_uso:
            motivos = []
            if not veiculo.ativo:
                motivos.append("inativo")
            if not veiculo.disponivel:
                motivos.append("indisponível")
            if veiculo.em_manutencao:
                motivos.append("em manutenção")
            if veiculo.licenciamento_vencido:
                motivos.append("licenciamento vencido")
            if veiculo.seguro_vencido:
                motivos.append("seguro vencido")
            
            return False, f"Veículo não apto: {', '.join(motivos)}"
        
        # Verificar conflitos de horário
        conflitos = self._buscar_conflitos_horario(
            'veiculo', veiculo_id, data_agendamento, horario_saida, horario_retorno
        )
        
        if conflitos:
            horarios_conflito = [f"{c.horario_saida.strftime('%H:%M')}" for c in conflitos]
            return False, f"Veículo já agendado nos horários: {', '.join(horarios_conflito)}"
        
        return True, "Veículo disponível"
    
    def _verificar_disponibilidade_paciente(self, paciente_id: int, data_agendamento, 
                                          horario_saida, horario_retorno=None) -> Tuple[bool, str]:
        """Verifica disponibilidade do paciente"""
        
        paciente = Paciente.query.get(paciente_id)
        if not paciente:
            return False, "Paciente não encontrado"
        
        if not paciente.ativo:
            return False, "Paciente está inativo"
        
        # Verificar conflitos de horário (mesmo dia)
        conflitos = Agendamento.query.filter(
            Agendamento.paciente_id == paciente_id,
            Agendamento.data_agendamento == data_agendamento,
            Agendamento.status.in_([
                StatusAgendamento.AGENDADO.value,
                StatusAgendamento.CONFIRMADO.value,
                StatusAgendamento.EM_ANDAMENTO.value
            ])
        ).all()
        
        if conflitos:
            horarios_conflito = [f"{c.horario_saida.strftime('%H:%M')}" for c in conflitos]
            return False, f"Paciente já possui agendamento(s) no dia nos horários: {', '.join(horarios_conflito)}"
        
        return True, "Paciente disponível"
    
    def _verificar_compatibilidade_paciente_veiculo(self, paciente_id: int, veiculo_id: int) -> Tuple[bool, str]:
        """Verifica compatibilidade entre paciente e veículo"""
        
        paciente = Paciente.query.get(paciente_id)
        veiculo = Veiculo.query.get(veiculo_id)
        
        if not paciente or not veiculo:
            return False, "Paciente ou veículo não encontrado"
        
        # Verificar acessibilidade
        if paciente.usa_cadeira_rodas and veiculo.capacidade_cadeirantes == 0:
            return False, "Veículo não possui acessibilidade para cadeirantes"
        
        if paciente.mobilidade_reduzida and not veiculo.acessibilidade_total:
            return False, "Veículo não possui acessibilidade total para pessoas com mobilidade reduzida"
        
        # Verificar se há vagas (considerando outros agendamentos do mesmo horário)
        # Esta é uma verificação simplificada - em um sistema real seria mais complexa
        
        return True, "Paciente e veículo são compatíveis"
    
    def _buscar_conflitos_horario(self, tipo: str, recurso_id: int, data_agendamento, 
                                 horario_saida, horario_retorno=None) -> List[Agendamento]:
        """Busca conflitos de horário para um recurso"""
        
        query = Agendamento.query.filter(
            Agendamento.data_agendamento == data_agendamento,
            Agendamento.status.in_([
                StatusAgendamento.AGENDADO.value,
                StatusAgendamento.CONFIRMADO.value,
                StatusAgendamento.EM_ANDAMENTO.value
            ])
        )
        
        if tipo == 'motorista':
            query = query.filter(Agendamento.motorista_id == recurso_id)
        elif tipo == 'veiculo':
            query = query.filter(Agendamento.veiculo_id == recurso_id)
        
        conflitos = []
        agendamentos_existentes = query.all()
        
        for agendamento in agendamentos_existentes:
            if self._horarios_conflitam(
                horario_saida, horario_retorno,
                agendamento.horario_saida, agendamento.horario_retorno_previsto
            ):
                conflitos.append(agendamento)
        
        return conflitos
    
    def _horarios_conflitam(self, inicio1, fim1, inicio2, fim2) -> bool:
        """Verifica se dois períodos de horário conflitam"""
        
        # Se não há horário de fim, assume 1 hora de duração
        if fim1 is None:
            if isinstance(inicio1, str):
                inicio1 = datetime.strptime(inicio1, '%H:%M').time()
            dt_inicio = datetime.combine(date.today(), inicio1)
            fim1 = (dt_inicio + timedelta(hours=1)).time()
        
        if fim2 is None:
            if isinstance(inicio2, str):
                inicio2 = datetime.strptime(inicio2, '%H:%M').time()
            dt_inicio = datetime.combine(date.today(), inicio2)
            fim2 = (dt_inicio + timedelta(hours=1)).time()
        
        # Converter strings para time se necessário
        if isinstance(inicio1, str):
            inicio1 = datetime.strptime(inicio1, '%H:%M').time()
        if isinstance(fim1, str):
            fim1 = datetime.strptime(fim1, '%H:%M').time()
        if isinstance(inicio2, str):
            inicio2 = datetime.strptime(inicio2, '%H:%M').time()
        if isinstance(fim2, str):
            fim2 = datetime.strptime(fim2, '%H:%M').time()
        
        # Verificar sobreposição
        return not (fim1 <= inicio2 or fim2 <= inicio1)
    
    def _verificar_avisos(self, motorista_id: int, veiculo_id: int, data_agendamento) -> List[Dict[str, str]]:
        """Verifica avisos não bloqueantes"""
        
        avisos = []
        
        # Verificar se motorista tem CNH vencendo
        motorista = Motorista.query.get(motorista_id)
        if motorista and motorista.cnh_vence_em_30_dias:
            avisos.append({
                'tipo': 'cnh_vencendo',
                'mensagem': f"CNH do motorista vence em {(motorista.data_vencimento_cnh - date.today()).days} dias"
            })
        
        # Verificar se veículo tem licenciamento vencendo
        veiculo = Veiculo.query.get(veiculo_id)
        if veiculo and veiculo.licenciamento_vence_em_30_dias:
            avisos.append({
                'tipo': 'licenciamento_vencendo',
                'mensagem': f"Licenciamento do veículo vence em {(veiculo.data_vencimento_licenciamento - date.today()).days} dias"
            })
        
        # Verificar se veículo precisa de revisão
        if veiculo and veiculo.necessita_revisao:
            avisos.append({
                'tipo': 'revisao_necessaria',
                'mensagem': "Veículo necessita revisão"
            })
        
        return avisos
    
    # === SUGESTÕES E OTIMIZAÇÃO ===
    
    def sugerir_horarios_disponiveis(self, motorista_id: int, veiculo_id: int, 
                                    data_agendamento, duracao_estimada: int = 120) -> List[str]:
        """
        Sugere horários disponíveis para um agendamento
        
        Args:
            motorista_id: ID do motorista
            veiculo_id: ID do veículo
            data_agendamento: Data do agendamento
            duracao_estimada: Duração estimada em minutos
            
        Returns:
            Lista de horários disponíveis no formato HH:MM
        """
        
        horarios_disponiveis = []
        horarios_funcionamento = self.config.get_horarios_disponiveis()
        
        for horario_str in horarios_funcionamento:
            horario = datetime.strptime(horario_str, '%H:%M').time()
            
            # Calcular horário de fim
            dt_inicio = datetime.combine(date.today(), horario)
            dt_fim = dt_inicio + timedelta(minutes=duracao_estimada)
            horario_fim = dt_fim.time()
            
            # Verificar se cabe no horário de funcionamento
            fim_funcionamento = datetime.strptime(self.config.HORARIO_FIM_PADRAO, '%H:%M').time()
            if horario_fim > fim_funcionamento:
                continue
            
            # Verificar disponibilidade
            disponibilidade = self.verificar_disponibilidade_completa(
                motorista_id, veiculo_id, None, data_agendamento, horario, horario_fim
            )
            
            if disponibilidade['disponivel']:
                horarios_disponiveis.append(horario_str)
        
        return horarios_disponiveis
    
    def otimizar_agendamentos_dia(self, data: date) -> Dict[str, Any]:
        """
        Otimiza agendamentos de um dia específico
        Tenta reduzir tempo ocioso e otimizar rotas
        """
        
        # Buscar agendamentos do dia
        agendamentos = Agendamento.query.filter(
            Agendamento.data_agendamento == data,
            Agendamento.status.in_([
                StatusAgendamento.AGENDADO.value,
                StatusAgendamento.CONFIRMADO.value
            ])
        ).order_by(Agendamento.horario_saida).all()
        
        if not agendamentos:
            return {
                'otimizado': False,
                'mensagem': 'Nenhum agendamento encontrado para otimização'
            }
        
        # Agrupar por motorista/veículo
        grupos = {}
        for agendamento in agendamentos:
            chave = f"{agendamento.motorista_id}_{agendamento.veiculo_id}"
            if chave not in grupos:
                grupos[chave] = []
            grupos[chave].append(agendamento)
        
        otimizacoes = []
        
        # Otimizar cada grupo
        for chave, grupo_agendamentos in grupos.items():
            if len(grupo_agendamentos) > 1:
                otimizacao = self._otimizar_grupo_agendamentos(grupo_agendamentos)
                if otimizacao['melhorado']:
                    otimizacoes.append(otimizacao)
        
        return {
            'otimizado': len(otimizacoes) > 0,
            'otimizacoes': otimizacoes,
            'economia_tempo': sum(o['economia_minutos'] for o in otimizacoes),
            'economia_km': sum(o.get('economia_km', 0) for o in otimizacoes)
        }
    
    def _otimizar_grupo_agendamentos(self, agendamentos: List[Agendamento]) -> Dict[str, Any]:
        """Otimiza um grupo de agendamentos do mesmo motorista/veículo"""
        
        # Implementação simplificada - em um sistema real seria mais complexa
        # considerando geolocalização, trânsito, etc.
        
        economia_tempo = 0
        sugestoes = []
        
        # Verificar gaps desnecessários
        for i in range(len(agendamentos) - 1):
            atual = agendamentos[i]
            proximo = agendamentos[i + 1]
            
            # Calcular gap
            fim_atual = atual.horario_retorno_previsto or atual.horario_saida
            inicio_proximo = proximo.horario_saida
            
            dt_fim = datetime.combine(date.today(), fim_atual)
            dt_inicio = datetime.combine(date.today(), inicio_proximo)
            
            gap_minutos = (dt_inicio - dt_fim).total_seconds() / 60
            
            # Se gap for maior que 30 minutos, sugerir otimização
            if gap_minutos > 30:
                novo_horario = dt_fim + timedelta(minutes=15)  # 15 min de buffer
                if novo_horario.time() < inicio_proximo:
                    economia_tempo += gap_minutos - 15
                    sugestoes.append({
                        'agendamento_id': proximo.id,
                        'horario_atual': inicio_proximo.strftime('%H:%M'),
                        'horario_sugerido': novo_horario.strftime('%H:%M'),
                        'economia_minutos': gap_minutos - 15
                    })
        
        return {
            'melhorado': len(sugestoes) > 0,
            'economia_minutos': economia_tempo,
            'sugestoes': sugestoes
        }
    
    # === AGENDAMENTOS DE RETORNO ===
    
    def _criar_agendamento_retorno(self, agendamento_origem: Agendamento) -> Optional[Agendamento]:
        """Cria agendamento de retorno automaticamente"""
        
        try:
            # Calcular data e horário de retorno
            if agendamento_origem.horario_retorno_previsto:
                horario_retorno = agendamento_origem.horario_retorno_previsto
            else:
                # Usar horário padrão baseado no tipo
                horario_retorno = self._calcular_horario_retorno_padrao(
                    agendamento_origem.horario_saida,
                    agendamento_origem.tipo_atendimento
                )
            
            # Verificar se horário de retorno não ultrapassa funcionamento
            fim_funcionamento = datetime.strptime(self.config.HORARIO_FIM_PADRAO, '%H:%M').time()
            if horario_retorno > fim_funcionamento:
                # Agendar para o próximo dia útil
                data_retorno = agendamento_origem.data_agendamento + timedelta(days=1)
                while not self.config.is_dia_funcionamento(data_retorno):
                    data_retorno += timedelta(days=1)
                horario_retorno = datetime.strptime(self.config.HORARIO_INICIO_PADRAO, '%H:%M').time()
            else:
                data_retorno = agendamento_origem.data_agendamento
            
            # Criar agendamento de retorno
            agendamento_retorno = Agendamento(
                paciente_id=agendamento_origem.paciente_id,
                motorista_id=agendamento_origem.motorista_id,
                veiculo_id=agendamento_origem.veiculo_id,
                data_agendamento=data_retorno,
                horario_saida=horario_retorno,
                destino_nome="Retorno - Residência",
                destino_endereco=agendamento_origem.paciente.endereco_completo,
                destino_cidade=agendamento_origem.paciente.cidade,
                destino_uf=agendamento_origem.paciente.uf,
                tipo_atendimento='retorno',
                eh_retorno=True,
                agendamento_origem_id=agendamento_origem.id,
                prioridade=agendamento_origem.prioridade,
                possui_acompanhante=agendamento_origem.possui_acompanhante,
                nome_acompanhante=agendamento_origem.nome_acompanhante,
                telefone_acompanhante=agendamento_origem.telefone_acompanhante
            )
            
            # Verificar disponibilidade
            disponibilidade = self.verificar_disponibilidade_completa(
                agendamento_retorno.motorista_id,
                agendamento_retorno.veiculo_id,
                agendamento_retorno.paciente_id,
                agendamento_retorno.data_agendamento,
                agendamento_retorno.horario_saida
            )
            
            if disponibilidade['disponivel']:
                db.session.add(agendamento_retorno)
                db.session.commit()
                return agendamento_retorno
            else:
                current_app.logger.warning(
                    f"Não foi possível criar agendamento de retorno automático: {disponibilidade['mensagem']}"
                )
                return None
                
        except Exception as e:
            current_app.logger.error(f"Erro ao criar agendamento de retorno: {e}")
            db.session.rollback()
            return None
    
    # === ESTATÍSTICAS E RELATÓRIOS ===
    
    def calcular_estatisticas_periodo(self, data_inicio: date, data_fim: date) -> Dict[str, Any]:
        """Calcula estatísticas de agendamentos para um período"""
        
        agendamentos = Agendamento.query.filter(
            and_(
                Agendamento.data_agendamento >= data_inicio,
                Agendamento.data_agendamento <= data_fim
            )
        ).all()
        
        if not agendamentos:
            return {
                'total': 0,
                'por_status': {},
                'por_tipo': {},
                'por_prioridade': {},
                'taxa_conclusao': 0,
                'tempo_medio_viagem': 0,
                'km_total': 0
            }
        
        # Contadores
        por_status = {}
        por_tipo = {}
        por_prioridade = {}
        tempos_viagem = []
        km_total = 0
        
        for agendamento in agendamentos:
            # Por status
            status = agendamento.status
            por_status[status] = por_status.get(status, 0) + 1
            
            # Por tipo
            tipo = agendamento.tipo_atendimento
            por_tipo[tipo] = por_tipo.get(tipo, 0) + 1
            
            # Por prioridade
            prioridade = agendamento.prioridade
            por_prioridade[prioridade] = por_prioridade.get(prioridade, 0) + 1
            
            # Tempo de viagem
            if agendamento.duracao_real:
                tempos_viagem.append(agendamento.duracao_real)
            
            # Quilometragem
            if agendamento.km_percorrido:
                km_total += agendamento.km_percorrido
        
        # Calcular taxa de conclusão
        concluidos = por_status.get(StatusAgendamento.CONCLUIDO.value, 0)
        taxa_conclusao = (concluidos / len(agendamentos)) * 100 if agendamentos else 0
        
        # Tempo médio de viagem
        tempo_medio = sum(tempos_viagem) / len(tempos_viagem) if tempos_viagem else 0
        
        return {
            'total': len(agendamentos),
            'por_status': por_status,
            'por_tipo': por_tipo,
            'por_prioridade': por_prioridade,
            'taxa_conclusao': round(taxa_conclusao, 2),
            'tempo_medio_viagem': round(tempo_medio, 0),
            'km_total': km_total,
            'periodo': {
                'inicio': data_inicio.strftime('%d/%m/%Y'),
                'fim': data_fim.strftime('%d/%m/%Y')
            }
        }
    
    def gerar_relatorio_produtividade(self, motorista_id: Optional[int] = None, 
                                     veiculo_id: Optional[int] = None,
                                     periodo_dias: int = 30) -> Dict[str, Any]:
        """Gera relatório de produtividade de motoristas/veículos"""
        
        data_fim = date.today()
        data_inicio = data_fim - timedelta(days=periodo_dias)
        
        query = Agendamento.query.filter(
            and_(
                Agendamento.data_agendamento >= data_inicio,
                Agendamento.data_agendamento <= data_fim,
                Agendamento.status == StatusAgendamento.CONCLUIDO.value
            )
        )
        
        if motorista_id:
            query = query.filter(Agendamento.motorista_id == motorista_id)
        
        if veiculo_id:
            query = query.filter(Agendamento.veiculo_id == veiculo_id)
        
        agendamentos = query.all()
        
        # Agrupar por motorista
        por_motorista = {}
        for agendamento in agendamentos:
            motorista_id = agendamento.motorista_id
            if motorista_id not in por_motorista:
                por_motorista[motorista_id] = {
                    'nome': agendamento.motorista.nome_completo,
                    'total_viagens': 0,
                    'km_total': 0,
                    'tempo_total': 0,
                    'avaliacoes': []
                }
            
            por_motorista[motorista_id]['total_viagens'] += 1
            
            if agendamento.km_percorrido:
                por_motorista[motorista_id]['km_total'] += agendamento.km_percorrido
            
            if agendamento.duracao_real:
                por_motorista[motorista_id]['tempo_total'] += agendamento.duracao_real
            
            if agendamento.avaliacao_paciente:
                por_motorista[motorista_id]['avaliacoes'].append(agendamento.avaliacao_paciente)
        
        # Calcular médias e rankings
        for dados in por_motorista.values():
            if dados['avaliacoes']:
                dados['avaliacao_media'] = sum(dados['avaliacoes']) / len(dados['avaliacoes'])
            else:
                dados['avaliacao_media'] = 0
            
            dados['km_por_viagem'] = dados['km_total'] / dados['total_viagens'] if dados['total_viagens'] else 0
            dados['tempo_por_viagem'] = dados['tempo_total'] / dados['total_viagens'] if dados['total_viagens'] else 0
        
        return {
            'periodo': f"{data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}",
            'total_agendamentos': len(agendamentos),
            'por_motorista': por_motorista,
            'ranking_viagens': sorted(por_motorista.items(), key=lambda x: x[1]['total_viagens'], reverse=True),
            'ranking_avaliacao': sorted(por_motorista.items(), key=lambda x: x[1]['avaliacao_media'], reverse=True)
        }
    
    # === NOTIFICAÇÕES E LEMBRETES ===
    
    def processar_lembretes_agendamentos(self) -> Dict[str, Any]:
        """
        Processa lembretes de agendamentos
        Identifica agendamentos que precisam de confirmação, lembrete, etc.
        """
        
        hoje = date.today()
        amanha = hoje + timedelta(days=1)
        
        # Agendamentos para confirmar (próximas 24 horas)
        para_confirmar = Agendamento.query.filter(
            and_(
                Agendamento.data_agendamento.in_([hoje, amanha]),
                Agendamento.status == StatusAgendamento.AGENDADO.value
            )
        ).all()
        
        # Agendamentos para lembrar (hoje)
        para_lembrar = Agendamento.query.filter(
            and_(
                Agendamento.data_agendamento == hoje,
                Agendamento.status == StatusAgendamento.CONFIRMADO.value
            )
        ).all()
        
        # Agendamentos atrasados
        agora = datetime.now()
        atrasados = []
        
        for agendamento in para_lembrar:
            hora_agendamento = datetime.combine(agendamento.data_agendamento, agendamento.horario_saida)
            if hora_agendamento < agora and agendamento.status != StatusAgendamento.EM_ANDAMENTO.value:
                atrasados.append(agendamento)
        
        return {
            'para_confirmar': [a.to_dict() for a in para_confirmar],
            'para_lembrar': [a.to_dict() for a in para_lembrar],
            'atrasados': [a.to_dict() for a in atrasados],
            'total_acoes': len(para_confirmar) + len(para_lembrar) + len(atrasados)
        }

# Instância global do serviço
agendamento_service = AgendamentoService()
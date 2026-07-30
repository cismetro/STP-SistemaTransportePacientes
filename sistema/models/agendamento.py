#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de Transporte de Pacientes
Desenvolvido para a Prefeitura Municipal de Cosmópolis
Pode ser usado por terceiros autorizados

Modelo: Agendamento
Representa os agendamentos de transporte no sistema
"""

from datetime import datetime, date, time, timedelta
from sqlalchemy import Column, Integer, String, Text, Date, DateTime, Boolean, Time, ForeignKey
from sqlalchemy.orm import validates, relationship
from sqlalchemy.ext.hybrid import hybrid_property
import re

from db.database import db

class Agendamento(db.Model):
    """
    Modelo de Agendamento
    Sistema da Prefeitura Municipal de Cosmópolis
    
    Representa um agendamento de transporte de paciente
    """
    
    __tablename__ = 'agendamentos'
    
    # === CAMPOS PRINCIPAIS ===
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Relacionamentos (chaves estrangeiras)
    paciente_id = Column(Integer, ForeignKey('pacientes.id'), nullable=False, index=True)
    motorista_id = Column(Integer, ForeignKey('motoristas.id'), nullable=False, index=True)
    veiculo_id = Column(Integer, ForeignKey('veiculos.id'), nullable=False, index=True)
    
    # Data e horário
    data_agendamento = Column(Date, nullable=False, index=True)
    horario_saida = Column(Time, nullable=False, index=True)
    horario_retorno_previsto = Column(Time, nullable=True)
    horario_saida_real = Column(DateTime, nullable=True)
    horario_retorno_real = Column(DateTime, nullable=True)
    
    # Informações do destino
    destino_nome = Column(String(200), nullable=False)
    destino_endereco = Column(String(300), nullable=False)
    destino_cidade = Column(String(100), nullable=False, default='Cosmópolis')
    destino_uf = Column(String(2), nullable=False, default='SP')
    destino_cep = Column(String(10), nullable=True)
    destino_telefone = Column(String(20), nullable=True)
    
    # Informações do atendimento
    tipo_atendimento = Column(String(20), nullable=False)  # exame, consulta, procedimento, retorno
    especialidade = Column(String(100), nullable=True)
    medico_responsavel = Column(String(200), nullable=True)
    descricao_atendimento = Column(Text, nullable=True)
    
    # Informações de acompanhamento
    possui_acompanhante = Column(Boolean, default=False, nullable=False)
    nome_acompanhante = Column(String(200), nullable=True)
    telefone_acompanhante = Column(String(20), nullable=True)
    
    # Prioridade e urgência
    prioridade = Column(String(10), nullable=False, default='normal')  # baixa, normal, alta, urgente
    eh_retorno = Column(Boolean, default=False, nullable=False)
    agendamento_origem_id = Column(Integer, ForeignKey('agendamentos.id'), nullable=True)
    
    # Status do agendamento
    status = Column(String(20), nullable=False, default='agendado', index=True)
    # agendado, confirmado, em_andamento, concluido, cancelado, nao_compareceu
    
    # Informações de confirmação
    data_confirmacao = Column(DateTime, nullable=True)
    confirmado_por = Column(String(200), nullable=True)
    telefone_confirmacao = Column(String(20), nullable=True)
    
    # Informações de cancelamento
    data_cancelamento = Column(DateTime, nullable=True)
    motivo_cancelamento = Column(String(200), nullable=True)
    cancelado_por = Column(String(200), nullable=True)
    
    # Avaliação e feedback
    avaliacao_paciente = Column(Integer, nullable=True)  # 1 a 5
    observacoes_paciente = Column(Text, nullable=True)
    avaliacao_servico = Column(Integer, nullable=True)  # 1 a 5
    observacoes_servico = Column(Text, nullable=True)
    
    # Controle de quilometragem
    km_inicial = Column(Integer, nullable=True)
    km_final = Column(Integer, nullable=True)
    km_percorrido = Column(Integer, nullable=True)
    
    # Observações gerais
    observacoes = Column(Text, nullable=True)
    observacoes_motorista = Column(Text, nullable=True)
    
    # Timestamps
    data_cadastro = Column(DateTime, default=datetime.utcnow, nullable=False)
    data_atualizacao = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # === RELACIONAMENTOS ===
    # Os relacionamentos já estão definidos nos outros modelos via backref
    
    # Relacionamento para agendamentos de retorno
    agendamentos_retorno = relationship('Agendamento', backref='agendamento_origem', remote_side=[id])
    
    # === PROPRIEDADES CALCULADAS ===
    @hybrid_property
    def data_hora_saida(self):
        """Combina data e horário de saída"""
        if self.data_agendamento and self.horario_saida:
            return datetime.combine(self.data_agendamento, self.horario_saida)
        return None
    
    @hybrid_property
    def data_hora_retorno_previsto(self):
        """Combina data e horário de retorno previsto"""
        if self.data_agendamento and self.horario_retorno_previsto:
            return datetime.combine(self.data_agendamento, self.horario_retorno_previsto)
        return None
    
    @hybrid_property
    def duracao_prevista(self):
        """Calcula duração prevista em minutos"""
        if self.horario_saida and self.horario_retorno_previsto:
            saida = datetime.combine(date.today(), self.horario_saida)
            retorno = datetime.combine(date.today(), self.horario_retorno_previsto)
            
            # Se retorno for no dia seguinte
            if retorno < saida:
                retorno += timedelta(days=1)
            
            duracao = retorno - saida
            return int(duracao.total_seconds() / 60)
        return None
    
    @hybrid_property
    def duracao_real(self):
        """Calcula duração real em minutos"""
        if self.horario_saida_real and self.horario_retorno_real:
            duracao = self.horario_retorno_real - self.horario_saida_real
            return int(duracao.total_seconds() / 60)
        return None
    
    @hybrid_property
    def eh_hoje(self):
        """Verifica se o agendamento é hoje"""
        return self.data_agendamento == date.today()
    
    @hybrid_property
    def eh_passado(self):
        """Verifica se o agendamento é passado"""
        if self.data_agendamento < date.today():
            return True
        if self.data_agendamento == date.today() and self.horario_saida:
            return datetime.now().time() > self.horario_saida
        return False
    
    @hybrid_property
    def pode_cancelar(self):
        """Verifica se ainda pode ser cancelado"""
        return (
            self.status in ['agendado', 'confirmado'] and 
            not self.eh_passado
        )
    
    @hybrid_property
    def pode_confirmar(self):
        """Verifica se pode ser confirmado"""
        return (
            self.status == 'agendado' and 
            not self.eh_passado
        )
    
    @hybrid_property
    def destino_completo(self):
        """Retorna endereço completo do destino"""
        endereco = f"{self.destino_nome} - {self.destino_endereco}"
        if self.destino_cidade != 'Cosmópolis':
            endereco += f" - {self.destino_cidade}/{self.destino_uf}"
        return endereco
    
    @hybrid_property
    def descricao_completa(self):
        """Retorna descrição completa do agendamento"""
        return f"{self.paciente.nome_completo} - {self.tipo_atendimento.title()} em {self.destino_nome}"
    
    # === VALIDAÇÕES ===
    @validates('data_agendamento')
    def validate_data_agendamento(self, key, data):
        """Valida a data do agendamento"""
        if not data:
            raise ValueError("Data do agendamento é obrigatória")
        
        if isinstance(data, str):
            try:
                data = datetime.strptime(data, '%Y-%m-%d').date()
            except ValueError:
                raise ValueError("Data do agendamento inválida")
        
        # Não permitir agendamento para datas passadas
        if data < date.today():
            raise ValueError("Não é possível agendar para datas passadas")
        
        # Verificar se é dia útil (dependendo da configuração)
        if data.weekday() >= 5:  # Sábado = 5, Domingo = 6
            # Permitir apenas em casos especiais
            pass  # Pode ser configurado conforme necessidade
        
        return data
    
    @validates('horario_saida')
    def validate_horario_saida(self, key, horario):
        """Valida o horário de saída"""
        if not horario:
            raise ValueError("Horário de saída é obrigatório")
        
        if isinstance(horario, str):
            try:
                horario = datetime.strptime(horario, '%H:%M').time()
            except ValueError:
                raise ValueError("Horário de saída inválido. Use o formato HH:MM")
        
        # Verificar horário de funcionamento
        from config import BusinessConfig
        horario_inicio = time(6, 0)  # 06:00
        horario_fim = time(18, 0)    # 18:00
        
        if horario < horario_inicio or horario > horario_fim:
            raise ValueError(f"Horário deve estar entre {horario_inicio.strftime('%H:%M')} e {horario_fim.strftime('%H:%M')}")
        
        return horario
    
    @validates('tipo_atendimento')
    def validate_tipo_atendimento(self, key, tipo):
        """Valida o tipo de atendimento"""
        if not tipo:
            raise ValueError("Tipo de atendimento é obrigatório")
        
        tipos_validos = ['exame', 'consulta', 'procedimento', 'retorno']
        tipo = tipo.lower()
        
        if tipo not in tipos_validos:
            raise ValueError(f"Tipo de atendimento deve ser: {', '.join(tipos_validos)}")
        
        return tipo
    
    @validates('prioridade')
    def validate_prioridade(self, key, prioridade):
        """Valida a prioridade"""
        if not prioridade:
            return 'normal'
        
        prioridades_validas = ['baixa', 'normal', 'alta', 'urgente']
        prioridade = prioridade.lower()
        
        if prioridade not in prioridades_validas:
            raise ValueError(f"Prioridade deve ser: {', '.join(prioridades_validas)}")
        
        return prioridade
    
    @validates('status')
    def validate_status(self, key, status):
        """Valida o status do agendamento"""
        if not status:
            return 'agendado'
        
        status_validos = ['agendado', 'confirmado', 'em_andamento', 'concluido', 'cancelado', 'nao_compareceu']
        status = status.lower()
        
        if status not in status_validos:
            raise ValueError(f"Status deve ser: {', '.join(status_validos)}")
        
        return status
    
    @validates('avaliacao_paciente', 'avaliacao_servico')
    def validate_avaliacao(self, key, avaliacao):
        """Valida as avaliações"""
        if avaliacao is None:
            return avaliacao
        
        if not isinstance(avaliacao, int) or avaliacao < 1 or avaliacao > 5:
            raise ValueError("Avaliação deve ser um número entre 1 e 5")
        
        return avaliacao
    
    # === VALIDAÇÕES COMPLEXAS ===
    def validar_disponibilidade_motorista(self):
        """Valida se o motorista está disponível no horário"""
        if not self.motorista_id or not self.data_agendamento or not self.horario_saida:
            return True, "Dados insuficientes para validação"
        
        # Buscar agendamentos conflitantes do motorista
        conflitos = Agendamento.query.filter(
            Agendamento.motorista_id == self.motorista_id,
            Agendamento.data_agendamento == self.data_agendamento,
            Agendamento.status.in_(['agendado', 'confirmado', 'em_andamento']),
            Agendamento.id != (self.id or 0)  # Excluir o próprio agendamento se for edição
        ).all()
        
        for conflito in conflitos:
            # Verificar sobreposição de horários
            if self._horarios_sobrepoem(conflito):
                return False, f"Motorista já possui agendamento às {conflito.horario_saida.strftime('%H:%M')}"
        
        return True, "Motorista disponível"
    
    def validar_disponibilidade_veiculo(self):
        """Valida se o veículo está disponível no horário"""
        if not self.veiculo_id or not self.data_agendamento or not self.horario_saida:
            return True, "Dados insuficientes para validação"
        
        # Verificar se veículo está apto
        veiculo = db.session.get(Veiculo, self.veiculo_id)
        if not veiculo or not veiculo.apto_para_uso:
            return False, "Veículo não está apto para uso"
        
        # Buscar agendamentos conflitantes do veículo
        conflitos = Agendamento.query.filter(
            Agendamento.veiculo_id == self.veiculo_id,
            Agendamento.data_agendamento == self.data_agendamento,
            Agendamento.status.in_(['agendado', 'confirmado', 'em_andamento']),
            Agendamento.id != (self.id or 0)
        ).all()
        
        for conflito in conflitos:
            if self._horarios_sobrepoem(conflito):
                return False, f"Veículo já agendado às {conflito.horario_saida.strftime('%H:%M')}"
        
        return True, "Veículo disponível"
    
    def validar_disponibilidade_paciente(self):
        """Valida se o paciente não tem outro agendamento no mesmo período"""
        if not self.paciente_id or not self.data_agendamento:
            return True, "Dados insuficientes para validação"
        
        # Buscar agendamentos do paciente no mesmo dia
        conflitos = Agendamento.query.filter(
            Agendamento.paciente_id == self.paciente_id,
            Agendamento.data_agendamento == self.data_agendamento,
            Agendamento.status.in_(['agendado', 'confirmado', 'em_andamento']),
            Agendamento.id != (self.id or 0)
        ).all()
        
        if conflitos:
            conflito = conflitos[0]
            return False, f"Paciente já possui agendamento às {conflito.horario_saida.strftime('%H:%M')}"
        
        return True, "Paciente disponível"
    
    def validar_capacidade_veiculo(self):
        """Valida se o veículo comporta o paciente"""
        if not self.veiculo_id or not self.paciente_id:
            return True, "Dados insuficientes para validação"
        
        veiculo = db.session.get(Veiculo, self.veiculo_id)
        paciente = db.session.get(Paciente, self.paciente_id)
        
        if not veiculo or not paciente:
            return False, "Veículo ou paciente não encontrado"
        
        # Verificar compatibilidade
        pode_transportar, motivo = veiculo.pode_transportar_paciente(paciente)
        
        return pode_transportar, motivo
    
    def _horarios_sobrepoem(self, outro_agendamento):
        """Verifica se os horários de dois agendamentos se sobrepõem"""
        # Criar datetime completos para comparação
        inicio1 = datetime.combine(self.data_agendamento, self.horario_saida)
        fim1 = datetime.combine(self.data_agendamento, 
                               self.horario_retorno_previsto or time(23, 59))
        
        inicio2 = datetime.combine(outro_agendamento.data_agendamento, 
                                  outro_agendamento.horario_saida)
        fim2 = datetime.combine(outro_agendamento.data_agendamento,
                               outro_agendamento.horario_retorno_previsto or time(23, 59))
        
        # Verificar sobreposição
        return not (fim1 <= inicio2 or fim2 <= inicio1)
    
    # === MÉTODOS DO MODELO ===
    def confirmar(self, confirmado_por=None, telefone=None):
        """Confirma o agendamento"""
        if not self.pode_confirmar:
            raise ValueError("Agendamento não pode ser confirmado")
        
        self.status = 'confirmado'
        self.data_confirmacao = datetime.utcnow()
        self.confirmado_por = confirmado_por
        self.telefone_confirmacao = telefone
    
    def cancelar(self, motivo, cancelado_por=None):
        """Cancela o agendamento"""
        if not self.pode_cancelar:
            raise ValueError("Agendamento não pode ser cancelado")
        
        self.status = 'cancelado'
        self.data_cancelamento = datetime.utcnow()
        self.motivo_cancelamento = motivo
        self.cancelado_por = cancelado_por
    
    def iniciar_viagem(self, km_inicial=None):
        """Inicia a viagem"""
        if self.status != 'confirmado':
            raise ValueError("Agendamento deve estar confirmado para iniciar")
        
        self.status = 'em_andamento'
        self.horario_saida_real = datetime.utcnow()
        if km_inicial:
            self.km_inicial = km_inicial
    
    def finalizar_viagem(self, km_final=None, observacoes_motorista=None):
        """Finaliza a viagem"""
        if self.status != 'em_andamento':
            raise ValueError("Agendamento deve estar em andamento para finalizar")
        
        self.status = 'concluido'
        self.horario_retorno_real = datetime.utcnow()
        
        if km_final:
            self.km_final = km_final
            if self.km_inicial:
                self.km_percorrido = km_final - self.km_inicial
        
        if observacoes_motorista:
            self.observacoes_motorista = observacoes_motorista
    
    def registrar_nao_comparecimento(self, motivo=None):
        """Registra não comparecimento do paciente"""
        self.status = 'nao_compareceu'
        if motivo:
            self.observacoes = f"Não compareceu: {motivo}"
    
    def avaliar_servico(self, avaliacao_paciente, observacoes_paciente=None, 
                       avaliacao_servico=None, observacoes_servico=None):
        """Registra avaliação do serviço"""
        self.avaliacao_paciente = avaliacao_paciente
        self.observacoes_paciente = observacoes_paciente
        
        if avaliacao_servico:
            self.avaliacao_servico = avaliacao_servico
        if observacoes_servico:
            self.observacoes_servico = observacoes_servico
    
    def criar_agendamento_retorno(self, data_retorno, horario_retorno):
        """Cria um agendamento de retorno"""
        if self.status != 'concluido':
            raise ValueError("Agendamento original deve estar concluído")
        
        agendamento_retorno = Agendamento(
            paciente_id=self.paciente_id,
            motorista_id=self.motorista_id,
            veiculo_id=self.veiculo_id,
            data_agendamento=data_retorno,
            horario_saida=horario_retorno,
            destino_nome="Retorno para residência",
            destino_endereco=self.paciente.endereco_completo,
            destino_cidade=self.paciente.cidade,
            destino_uf=self.paciente.uf,
            tipo_atendimento='retorno',
            eh_retorno=True,
            agendamento_origem_id=self.id,
            prioridade=self.prioridade
        )
        
        return agendamento_retorno
    
    def to_dict(self):
        """Converte o modelo para dicionário"""
        return {
            'id': self.id,
            'paciente': {
                'id': self.paciente.id,
                'nome': self.paciente.nome_completo,
                'cpf': self.paciente.cpf_formatado
            } if self.paciente else None,
            'motorista': {
                'id': self.motorista.id,
                'nome': self.motorista.nome_completo,
                'cnh': self.motorista.numero_cnh
            } if self.motorista else None,
            'veiculo': {
                'id': self.veiculo.id,
                'placa': self.veiculo.placa_formatada,
                'modelo': f"{self.veiculo.marca} {self.veiculo.modelo}"
            } if self.veiculo else None,
            'data_agendamento': self.data_agendamento.strftime('%d/%m/%Y') if self.data_agendamento else None,
            'horario_saida': self.horario_saida.strftime('%H:%M') if self.horario_saida else None,
            'horario_retorno_previsto': self.horario_retorno_previsto.strftime('%H:%M') if self.horario_retorno_previsto else None,
            'destino_completo': self.destino_completo,
            'tipo_atendimento': self.tipo_atendimento.title(),
            'especialidade': self.especialidade,
            'prioridade': self.prioridade.title(),
            'status': self.status.replace('_', ' ').title(),
            'eh_retorno': self.eh_retorno,
            'possui_acompanhante': self.possui_acompanhante,
            'nome_acompanhante': self.nome_acompanhante,
            'duracao_prevista': self.duracao_prevista,
            'duracao_real': self.duracao_real,
            'km_percorrido': self.km_percorrido,
            'avaliacao_paciente': self.avaliacao_paciente,
            'avaliacao_servico': self.avaliacao_servico,
            'pode_cancelar': self.pode_cancelar,
            'pode_confirmar': self.pode_confirmar,
            'eh_hoje': self.eh_hoje,
            'eh_passado': self.eh_passado,
            'observacoes': self.observacoes,
            'data_cadastro': self.data_cadastro.strftime('%d/%m/%Y %H:%M') if self.data_cadastro else None
        }
    
    def __repr__(self):
        """Representação string do modelo"""
        return f'<Agendamento {self.id} - {self.paciente.nome_completo if self.paciente else "N/A"} - {self.data_agendamento}>'
    
    def __str__(self):
        """String amigável do modelo"""
        return self.descricao_completa
    
    # === MÉTODOS DE CLASSE ===
    @classmethod
    def buscar_por_data(cls, data_inicio, data_fim=None):
        """Busca agendamentos por período"""
        if data_fim is None:
            data_fim = data_inicio
        
        return cls.query.filter(
            cls.data_agendamento >= data_inicio,
            cls.data_agendamento <= data_fim
        )
    
    @classmethod
    def agendamentos_hoje(cls):
        """Retorna agendamentos de hoje"""
        return cls.buscar_por_data(date.today())
    
    @classmethod
    def agendamentos_pendentes(cls):
        """Retorna agendamentos pendentes de confirmação"""
        return cls.query.filter_by(status='agendado')
    
    @classmethod
    def agendamentos_confirmados_hoje(cls):
        """Retorna agendamentos confirmados para hoje"""
        return cls.query.filter(
            cls.data_agendamento == date.today(),
            cls.status.in_(['confirmado', 'em_andamento'])
        )
    
    @classmethod
    def verificar_disponibilidade(cls, motorista_id, veiculo_id, data_agendamento, 
                                 horario_saida, horario_retorno=None):
        """Verifica disponibilidade de motorista e veículo"""
        # Criar agendamento temporário para validação
        temp_agendamento = cls(
            motorista_id=motorista_id,
            veiculo_id=veiculo_id,
            data_agendamento=data_agendamento,
            horario_saida=horario_saida,
            horario_retorno_previsto=horario_retorno
        )
        
        # Validar disponibilidades
        motorista_ok, msg_motorista = temp_agendamento.validar_disponibilidade_motorista()
        veiculo_ok, msg_veiculo = temp_agendamento.validar_disponibilidade_veiculo()
        
        return {
            'disponivel': motorista_ok and veiculo_ok,
            'motorista': {'disponivel': motorista_ok, 'mensagem': msg_motorista},
            'veiculo': {'disponivel': veiculo_ok, 'mensagem': msg_veiculo}
        }
    
    @classmethod
    def estatisticas(cls):
        """Retorna estatísticas dos agendamentos"""
        hoje = date.today()
        
        total = cls.query.count()
        hoje_total = cls.agendamentos_hoje().count()
        pendentes = cls.agendamentos_pendentes().count()
        confirmados_hoje = cls.agendamentos_confirmados_hoje().count()
        concluidos = cls.query.filter_by(status='concluido').count()
        cancelados = cls.query.filter_by(status='cancelado').count()
        
        return {
            'total': total,
            'hoje_total': hoje_total,
            'pendentes': pendentes,
            'confirmados_hoje': confirmados_hoje,
            'concluidos': concluidos,
            'cancelados': cancelados
        }

# Importações necessárias para relacionamentos
from sistema.models.paciente import Paciente
from sistema.models.motorista import Motorista
from sistema.models.veiculo import Veiculo
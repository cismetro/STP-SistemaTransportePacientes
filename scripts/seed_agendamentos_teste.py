# -*- coding: utf-8 -*-
"""Cria 5 agendamentos de teste (status agendado) para validação na listagem."""
from __future__ import annotations

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from datetime import date, datetime, time, timedelta

from app import (
    Agendamento,
    Frota,
    Motorista,
    Paciente,
    Veiculo,
    create_app,
    db,
    frota_veiculo_vinculado,
)

DATA_BASE = date(2026, 7, 28)  # hoje (contexto do projeto)


def main():
    app = create_app()
    with app.app_context():
        pacientes = (
            Paciente.query.filter_by(ativo=True)
            .order_by(Paciente.id.asc())
            .limit(12)
            .all()
        )
        if len(pacientes) < 5:
            raise SystemExit(f'Precisa de ao menos 5 pacientes ativos (achou {len(pacientes)}).')

        motorista = Motorista.query.filter_by(status='ativo').order_by(Motorista.id).first()
        veiculo = Veiculo.query.filter_by(ativo=True).order_by(Veiculo.id).first()
        frota = Frota.query.filter_by(ativo=True).order_by(Frota.id).first()
        if frota and not veiculo:
            veiculo = frota_veiculo_vinculado(frota.id)

        # 5 cenários de teste
        cenarios = [
            {
                'label': 'Aguardando programação (hoje 07:30)',
                'data': DATA_BASE,
                'hora': time(7, 30),
                'hora_consulta': time(9, 0),
                'programar': False,
                'status': 'agendado',
                'destino': 'Hospital Estadual — Campinas/SP',
                'tipo': 'Consulta',
            },
            {
                'label': 'Aguardando programação (hoje 08:00)',
                'data': DATA_BASE,
                'hora': time(8, 0),
                'hora_consulta': time(9, 30),
                'programar': False,
                'status': 'agendado',
                'destino': 'Santa Casa — Campinas/SP',
                'tipo': 'Exame',
            },
            {
                'label': 'Aguardando programação (amanhã 07:00)',
                'data': DATA_BASE + timedelta(days=1),
                'hora': time(7, 0),
                'hora_consulta': time(8, 30),
                'programar': False,
                'status': 'agendado',
                'destino': 'Hospital Regional — Campinas/SP',
                'tipo': 'Retorno',
            },
            {
                'label': 'Programado / pronto p/ cartão (amanhã 08:30)',
                'data': DATA_BASE + timedelta(days=1),
                'hora': time(8, 30),
                'hora_consulta': time(10, 0),
                'programar': True,
                'status': 'agendado',
                'destino': 'Clínica de Hemodiálise — Limeira/SP',
                'tipo': 'Tratamento',
            },
            {
                'label': 'Confirmado / pronto p/ impressão (30/07 09:00)',
                'data': DATA_BASE + timedelta(days=2),
                'hora': time(9, 0),
                'hora_consulta': time(10, 30),
                'programar': True,
                'status': 'confirmado',
                'destino': 'CAPS — Cosmópolis/SP',
                'tipo': 'Consulta',
            },
        ]

        criados = []
        for i, c in enumerate(cenarios):
            pac = pacientes[i]
            # Evita duplicar exatamente o mesmo paciente+data+hora
            existente = Agendamento.query.filter_by(
                paciente_id=pac.id,
                data=c['data'],
                hora=c['hora'],
            ).filter(Agendamento.status != 'cancelado').first()
            if existente:
                ag = existente
                ag.status = c['status']
                ag.destino = c['destino']
                ag.tipo_transporte = c['tipo']
                ag.hora_consulta = c['hora_consulta']
                ag.origem = ag.origem or 'COSMÓPOLIS/SP — POSTO / RESIDÊNCIA'
                ag.cidade_origem = ag.cidade_origem or 'Cosmópolis'
                ag.cidade_destino = ag.cidade_destino or 'Campinas'
                ag.observacoes = (
                    f'[TESTE STP] {c["label"]} | ATENDENTE: JULIANA | '
                    f'H. DA CONSULTA: {c["hora_consulta"].strftime("%H:%M")}'
                )
                acao = 'atualizado'
            else:
                ag = Agendamento(
                    paciente_id=pac.id,
                    tipo_transporte=c['tipo'],
                    data=c['data'],
                    hora=c['hora'],
                    hora_consulta=c['hora_consulta'],
                    origem='COSMÓPOLIS/SP — POSTO / RESIDÊNCIA',
                    destino=c['destino'],
                    cidade_origem='Cosmópolis',
                    cidade_destino='Campinas',
                    tipo_destino='cidade',
                    status=c['status'],
                    observacoes=(
                        f'[TESTE STP] {c["label"]} | ATENDENTE: JULIANA | '
                        f'H. DA CONSULTA: {c["hora_consulta"].strftime("%H:%M")}'
                    ),
                    data_cadastro=datetime.utcnow(),
                )
                db.session.add(ag)
                acao = 'criado'

            if c['programar']:
                if motorista:
                    ag.motorista_id = motorista.id
                if veiculo:
                    ag.veiculo_id = veiculo.id
                elif frota:
                    ag.frota_id = frota.id
            else:
                # deixa explícito aguardando programação
                ag.motorista_id = None
                ag.veiculo_id = None
                ag.frota_id = None

            db.session.flush()
            criados.append((acao, ag, pac, c['label']))

        db.session.commit()

        print('=== AGENDAMENTOS DE TESTE ===')
        for acao, ag, pac, label in criados:
            print(
                f'[{acao}] id={ag.id} | {ag.status} | {ag.data} {ag.hora} | '
                f'{pac.nome} | motorista={ag.motorista_id or "—"} | '
                f'veiculo={ag.veiculo_id or "—"} | {label}'
            )
        print('OK — filtre em /agendamentos por status Agendado / Confirmado ou período Hoje/Amanhã.')


if __name__ == '__main__':
    main()

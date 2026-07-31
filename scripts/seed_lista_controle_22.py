# -*- coding: utf-8 -*-
"""Gera 22 agendamentos PROGRAMADOS para teste da Lista de Controle (Folha Espelho).

Uso (na raiz do projeto OU em scripts/):
  $env:STP_BLOQUEAR_WHATSAPP='1'
  py scripts/seed_lista_controle_22.py
  # ou:
  cd scripts; py seed_lista_controle_22.py
"""
from __future__ import annotations

import os
import sys

# Permite rodar de dentro de scripts/ sem ModuleNotFoundError
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from datetime import date, datetime, time, timedelta

from app import (
    Agendamento,
    Acompanhante,
    Frota,
    Motorista,
    Paciente,
    Veiculo,
    create_app,
    db,
    frota_veiculo_vinculado,
    query_agendamentos_programados,
)

QTD = 22
DATA_REF = date.today()  # dia do teste real
MARCA = '[LISTA-CONTROLE-TESTE]'


def _cpf_fake(i: int) -> str:
    # CPF só para pacientes demo (não precisa ser válido matematicamente)
    base = f'{90000000000 + i:011d}'
    return f'{base[:3]}.{base[3:6]}.{base[6:9]}-{base[9:]}'


def garantir_paciente(i: int, pacientes_existentes: list) -> Paciente:
    if i < len(pacientes_existentes):
        return pacientes_existentes[i]
    pac = Paciente(
        nome=f'PACIENTE TESTE LISTA {i + 1:02d}',
        cpf=_cpf_fake(i + 1),
        telefone=f'1999{i:04d}0000'[:15],
        data_nascimento=date(1970 + (i % 40), 1 + (i % 12), 1 + (i % 27)),
        endereco=f'RUA TESTE {i + 1}, {100 + i} - CENTRO',
        logradouro=f'RUA TESTE {i + 1}',
        numero=str(100 + i),
        bairro='CENTRO',
        ponto_referencia='POSTO COSMÓPOLIS',
        ponto_embarque='POSTO COSMÓPOLIS',
        ativo=True,
    )
    db.session.add(pac)
    db.session.flush()
    return pac


def garantir_acompanhante(paciente: Paciente, i: int) -> Acompanhante | None:
    acs = Acompanhante.query.filter_by(paciente_id=paciente.id, ativo=True).all()
    if acs:
        return acs[0]
    ac = Acompanhante(
        paciente_id=paciente.id,
        nome=f'ACOMPANHANTE TESTE {i + 1:02d}',
        telefone=f'1988{i:04d}1111'[:15],
        rg=f'{1000000 + i}',
        ativo=True,
    )
    db.session.add(ac)
    db.session.flush()
    return ac


def main():
    app = create_app()
    with app.app_context():
        pacientes = (
            Paciente.query.filter_by(ativo=True).order_by(Paciente.id.asc()).limit(30).all()
        )
        motoristas = Motorista.query.filter_by(status='ativo').order_by(Motorista.id).all()
        veiculos = Veiculo.query.filter_by(ativo=True).order_by(Veiculo.id).all()
        frotas = Frota.query.filter_by(ativo=True).order_by(Frota.id).all()

        if not motoristas:
            raise SystemExit('Nenhum motorista ativo no banco.')
        if not veiculos and not frotas:
            raise SystemExit('Precisa de ao menos 1 veículo ou 1 frota ativos.')

        destinos = [
            'Hospital Estadual — Campinas/SP',
            'Santa Casa — Campinas/SP',
            'Hospital Regional — Campinas/SP',
            'HC Unicamp — Campinas/SP',
            'Clínica Hemodiálise — Limeira/SP',
            'CAPS — Cosmópolis/SP',
            'UBS Centro — Cosmópolis/SP',
            'CEAM — Americana/SP',
        ]
        especialidades = [
            'Cardiologia', 'Ortopedia', 'Pediatria', 'Neurologia',
            'Hemodiálise', 'Oftalmologia', 'Oncologia', 'Consulta',
        ]

        criados = []
        for i in range(QTD):
            pac = garantir_paciente(i, pacientes)
            mot = motoristas[i % len(motoristas)]
            hora_saida = time(6 + (i // 4), (i * 7) % 60)
            hora_consulta = time(min(8 + (i // 4), 17), (i * 11) % 60)

            usa_frota = bool(frotas) and (i % 3 == 0)
            veiculo_id = None
            frota_id = None
            if usa_frota:
                frota = frotas[i % len(frotas)]
                frota_id = frota.id
                vinc = frota_veiculo_vinculado(frota.id)
                # programação por frota (sem veiculo_id) — regra do sistema
            else:
                if veiculos:
                    veiculo_id = veiculos[i % len(veiculos)].id
                elif frotas:
                    frota_id = frotas[i % len(frotas)].id

            com_ac = (i % 2 == 0)
            ac_id = None
            possui_ac = False
            if com_ac:
                ac = garantir_acompanhante(pac, i)
                if ac:
                    ac_id = ac.id
                    possui_ac = True

            obs = (
                f'{MARCA} #{i + 1:02d} | ATENDENTE: JULIANA | '
                f'H. DA CONSULTA: {hora_consulta.strftime("%H:%M")}'
            )
            if possui_ac and ac_id:
                ac = db.session.get(Acompanhante, ac_id)
                obs += (
                    f' | NOME AC: {ac.nome} | TEL AC: {ac.telefone or ""}'
                )

            existente = (
                Agendamento.query.filter_by(
                    paciente_id=pac.id,
                    data=DATA_REF,
                    hora=hora_saida,
                )
                .filter(Agendamento.status != 'cancelado')
                .first()
            )
            if existente and existente.observacoes and MARCA in (existente.observacoes or ''):
                ag = existente
                acao = 'atualizado'
            elif existente:
                # horário ocupado por outro: desloca minutos
                hora_saida = time(hora_saida.hour, (hora_saida.minute + 1 + i) % 60)
                ag = None
                acao = 'criado'
            else:
                ag = None
                acao = 'criado'

            if ag is None:
                ag = Agendamento(
                    paciente_id=pac.id,
                    tipo_transporte=especialidades[i % len(especialidades)],
                    data=DATA_REF,
                    hora=hora_saida,
                    origem='COSMÓPOLIS/SP — POSTO / RESIDÊNCIA',
                    destino=destinos[i % len(destinos)],
                    cidade_origem='Cosmópolis',
                    cidade_destino='Campinas',
                    status='agendado',
                    data_cadastro=datetime.utcnow(),
                )
                db.session.add(ag)

            ag.status = 'agendado' if i % 5 else 'confirmado'
            ag.hora_consulta = hora_consulta
            ag.destino = destinos[i % len(destinos)]
            ag.tipo_transporte = especialidades[i % len(especialidades)]
            ag.origem = ag.origem or 'COSMÓPOLIS/SP — POSTO / RESIDÊNCIA'
            ag.motorista_id = mot.id
            ag.veiculo_id = veiculo_id
            ag.frota_id = frota_id
            ag.possui_acompanhante = possui_ac
            ag.acompanhante_id = ac_id
            ag.observacoes = obs
            criados.append((acao, ag, mot.nome, possui_ac))

        db.session.commit()

        qtd_hoje = query_agendamentos_programados({'periodo': 'hoje'}).count()
        qtd_data = query_agendamentos_programados({'data': DATA_REF.strftime('%d/%m/%Y')}).count()
        print(f'Data de referência: {DATA_REF.strftime("%d/%m/%Y")}')
        print(f'Agendamentos gerados/atualizados: {len(criados)}')
        for acao, ag, mot, com_ac in criados:
            db.session.refresh(ag)
            flag = 'COM AC' if com_ac else 'SEM AC'
            print(f'  [{acao}] #{ag.id} {ag.hora.strftime("%H:%M")} · {mot} · {flag}')
        print(f'Programados filtro Hoje: {qtd_hoje}')
        print(f'Programados na data {DATA_REF}: {qtd_data}')
        print('OK — use /agendamentos atalho Hoje → Imprimir todas do filtro')


if __name__ == '__main__':
    main()

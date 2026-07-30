#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gerenciador do Sistema WhatsApp
"""

import sys
import os
sys.path.append(os.path.dirname(__file__))

from app import create_app, WhatsAppNotificacao, NotificacaoAgendamento, Agendamento, Paciente, db
from datetime import date, datetime, timedelta
import json

def listar_agendamentos_hoje():
    """Lista agendamentos de hoje"""
    app = create_app()
    with app.app_context():
        hoje = date.today()
        agendamentos = Agendamento.query.filter_by(data=hoje).all()
        
        print(f"📅 AGENDAMENTOS DE HOJE ({hoje.strftime('%d/%m/%Y')})")
        print("=" * 50)
        
        if not agendamentos:
            print("❌ Nenhum agendamento encontrado")
            return
        
        for ag in agendamentos:
            print(f"⏰ {ag.hora.strftime('%H:%M')} - {ag.paciente.nome}")
            print(f"📱 {ag.paciente.telefone}")
            print(f"🏥 {ag.destino}")
            print(f"📊 Status: {ag.status}")
            print("-" * 30)

def enviar_confirmacoes_hoje():
    """Envia confirmações para agendamentos de hoje"""
    app = create_app()
    with app.app_context():
        whatsapp = WhatsAppNotificacao(app, db)
        notificacao = NotificacaoAgendamento(whatsapp)
        
        hoje = date.today()
        agendamentos = Agendamento.query.filter_by(data=hoje, status='agendado').all()
        
        print(f"📱 ENVIANDO CONFIRMAÇÕES - {hoje.strftime('%d/%m/%Y')}")
        print("=" * 50)
        
        enviados = 0
        for ag in agendamentos:
            if ag.paciente.telefone:
                try:
                    if notificacao.notificar_confirmacao(ag):
                        print(f"✅ {ag.paciente.nome} - {ag.paciente.telefone}")
                        enviados += 1
                    else:
                        print(f"❌ {ag.paciente.nome} - FALHA")
                except Exception as e:
                    print(f"❌ {ag.paciente.nome} - ERRO: {e}")
            else:
                print(f"⚠️ {ag.paciente.nome} - SEM TELEFONE")
        
        print(f"\n✅ Total enviado: {enviados}")

def verificar_logs():
    """Verifica logs do WhatsApp"""
    logs_dir = os.path.join(os.path.dirname(__file__), 'logs_whatsapp')
    hoje = date.today().strftime("%Y%m%d")
    
    print("📊 LOGS DO WHATSAPP")
    print("=" * 30)
    
    # Sucessos
    success_file = os.path.join(logs_dir, f'whatsapp_success_{hoje}.log')
    if os.path.exists(success_file):
        with open(success_file, 'r', encoding='utf-8') as f:
            sucessos = len(f.readlines())
        print(f"✅ Sucessos hoje: {sucessos}")
    else:
        print("✅ Sucessos hoje: 0")
    
    # Erros
    error_file = os.path.join(logs_dir, f'whatsapp_errors_{hoje}.log')
    if os.path.exists(error_file):
        with open(error_file, 'r', encoding='utf-8') as f:
            erros = f.readlines()
        print(f"❌ Erros hoje: {len(erros)}")
        
        if erros:
            print("\n🔍 ÚLTIMOS ERROS:")
            for erro in erros[-5:]:
                print(f"  {erro.strip()}")
    else:
        print("❌ Erros hoje: 0")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("USO: python whatsapp_manager.py [comando]")
        print()
        print("COMANDOS:")
        print("  listar     - Lista agendamentos de hoje")
        print("  enviar     - Envia confirmações de hoje")
        print("  logs       - Verifica logs")
        sys.exit(1)
    
    comando = sys.argv[1].lower()
    
    if comando == "listar":
        listar_agendamentos_hoje()
    elif comando == "enviar":
        enviar_confirmacoes_hoje()
    elif comando == "logs":
        verificar_logs()
    else:
        print(f"❌ Comando desconhecido: {comando}")
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Configurador do WhatsApp Web para o Sistema de Transporte
"""

import pywhatkit as kit
import time
import os
from datetime import datetime

def configurar_whatsapp_web():
    """
    Configura o WhatsApp Web para funcionar com o sistema
    """
    print("🚀 CONFIGURADOR WHATSAPP WEB")
    print("=" * 50)
    print()
    print("📱 INSTRUÇÕES IMPORTANTES:")
    print("1. Certifique-se de ter o Google Chrome instalado")
    print("2. Seu celular deve estar conectado à internet")
    print("3. O WhatsApp deve estar instalado no celular")
    print("4. Mantenha o celular próximo durante a configuração")
    print()
    
    input("Pressione ENTER para continuar...")
    
    try:
        print("🌐 Abrindo WhatsApp Web...")
        print("📱 Será aberto o Chrome com QR Code")
        print("📷 Escaneie o QR Code com seu celular")
        print()
        
        # Teste básico de conexão
        numero_teste = input("Digite um número para teste (com DDD, ex: 19999999999): ")
        
        if not numero_teste:
            print("❌ Número não informado!")
            return
        
        # Formatar número
        if len(numero_teste) == 11:
            numero_teste = f"+55{numero_teste}"
        elif not numero_teste.startswith('+'):
            numero_teste = f"+55{numero_teste}"
        
        print(f"📱 Enviando mensagem de teste para: {numero_teste}")
        
        mensagem_teste = f"""
🤖 TESTE DE CONFIGURAÇÃO 🤖

Olá! Esta é uma mensagem de teste do Sistema de Transporte de Pacientes.

⏰ Configurado em: {datetime.now().strftime('%d/%m/%Y às %H:%M')}

✅ Se você recebeu esta mensagem, a configuração foi realizada com sucesso!

_Sistema de Transporte - Cosmópolis_
        """
        
        print("⏱️ Aguarde 15 segundos para escaneamento do QR Code...")
        
        # Enviar mensagem de teste
        kit.sendwhatmsg_instantly(numero_teste, mensagem_teste, wait_time=15, tab_close=True)
        
        print("✅ CONFIGURAÇÃO CONCLUÍDA!")
        print("📱 Verifique se a mensagem foi recebida")
        print("🔄 O sistema agora pode enviar mensagens automaticamente")
        print()
        print("⚠️ IMPORTANTE:")
        print("• Mantenha o Chrome aberto em segundo plano")
        print("• Não faça logout do WhatsApp Web")
        print("• Mantenha o celular conectado à internet")
        
    except Exception as e:
        print(f"❌ ERRO na configuração: {e}")
        print()
        print("💡 DICAS PARA SOLUCIONAR:")
        print("• Verifique se o Chrome está instalado")
        print("• Certifique-se de que o número está correto")
        print("• Tente novamente em alguns minutos")

if __name__ == "__main__":
    configurar_whatsapp_web()
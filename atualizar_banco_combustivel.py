#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import shutil
from datetime import datetime

def atualizar_banco_combustivel():
    print("🚀 ATUALIZANDO BANCO - MÓDULO COMBUSTÍVEL")
    print("=" * 50)
    
    try:
        # Fazer backup do banco atual
        db_path = os.path.join('db', 'transporte_pacientes.db')
        
        if os.path.exists(db_path):
            # Criar diretório de backup
            backup_dir = os.path.join('backups', 'combustivel')
            os.makedirs(backup_dir, exist_ok=True)
            
            # Nome do backup
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_name = f'backup_antes_combustivel_{timestamp}.db'
            backup_path = os.path.join(backup_dir, backup_name)
            
            # Copiar banco atual
            shutil.copy2(db_path, backup_path)
            print(f"✅ Backup criado: {backup_name}")
            print(f"📁 Local: {backup_path}")
        
        # Importar e criar aplicação
        from app import create_app, db
        
        app = create_app()
        
        with app.app_context():
            print("\n🔄 Criando/atualizando tabelas...")
            
            # Criar todas as tabelas (só cria as que não existem)
            db.create_all()
            
            # Verificar se a tabela foi criada
            from sqlalchemy import inspect
            inspector = inspect(db.engine)
            tables = inspector.get_table_names()
            
            print("\n📋 VERIFICAÇÃO DE TABELAS:")
            
            # Verificar tabela de abastecimentos
            if 'abastecimentos' in tables:
                print("✅ Tabela 'abastecimentos' criada/encontrada!")
                
                # Verificar colunas
                columns = [col['name'] for col in inspector.get_columns('abastecimentos')]
                print(f"📊 Colunas: {len(columns)} encontradas")
                
                expected_columns = [
                    'id', 'veiculo_id', 'data_abastecimento', 'hora_abastecimento',
                    'km_atual', 'tipo_combustivel', 'litros_abastecidos', 
                    'valor_litro', 'valor_total', 'posto_nome', 'motorista_id',
                    'tanque_cheio', 'observacoes', 'data_cadastro'
                ]
                
                missing = [col for col in expected_columns if col not in columns]
                if missing:
                    print(f"⚠️  Colunas faltando: {missing}")
                else:
                    print("✅ Todas as colunas esperadas encontradas!")
                    
            else:
                print("❌ ERRO: Tabela 'abastecimentos' NÃO foi criada!")
                return False
            
            print("\n📋 TODAS AS TABELAS NO BANCO:")
            for i, table in enumerate(sorted(tables), 1):
                icon = "⛽" if table == "abastecimentos" else "📄"
                print(f"  {i:2d}. {icon} {table}")
            
            print(f"\n🎯 TOTAL: {len(tables)} tabelas no banco")
            print("\n✅ ATUALIZAÇÃO CONCLUÍDA COM SUCESSO!")
            
            return True
            
    except Exception as e:
        print(f"\n❌ ERRO DURANTE ATUALIZAÇÃO:")
        print(f"   {str(e)}")
        print(f"\n🔧 DICAS PARA RESOLVER:")
        print("   1. Verifique se o app.py tem a classe Abastecimento")
        print("   2. Certifique-se que não há erros de sintaxe")
        print("   3. Tente reiniciar o sistema")
        
        return False

if __name__ == '__main__':
    print("🚀 Iniciando atualização do banco para Controle de Combustível...")
    
    sucesso = atualizar_banco_combustivel()
    
    if sucesso:
        print("\n🎊 PRONTO! Agora você pode:")
        print("   1. Executar python app.py")
        print("   2. Acessar o menu 'Combustível'")
        print("   3. Começar a registrar abastecimentos")
    else:
        print("\n❌ Atualização falhou. Verifique os erros acima.")
        sys.exit(1)
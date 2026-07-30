#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de Transporte de Pacientes
Desenvolvido para a Prefeitura Municipal de Cosmópolis
Pode ser usado por terceiros autorizados

Arquivo de configuração do banco de dados
"""

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
import os
from datetime import datetime

# Instância global do SQLAlchemy
db = SQLAlchemy()

def init_db():
    """
    Inicializa o banco de dados
    Cria todas as tabelas se não existirem
    Sistema da Prefeitura Municipal de Cosmópolis
    """
    try:
        # Importar todos os modelos para que sejam reconhecidos pelo SQLAlchemy
        from sistema.models.usuario import Usuario
        from sistema.models.paciente import Paciente
        from sistema.models.motorista import Motorista
        from sistema.models.veiculo import Veiculo
        from sistema.models.agendamento import Agendamento
        
        # Criar todas as tabelas
        db.create_all()
        
        print("✅ Banco de dados inicializado com sucesso")
        print(f"📁 Localização: {get_database_path()}")
        
    except Exception as e:
        print(f"❌ Erro ao inicializar banco de dados: {e}")
        raise

def get_database_path():
    """
    Retorna o caminho do arquivo de banco de dados SQLite
    """
    from flask import current_app
    db_uri = current_app.config['SQLALCHEMY_DATABASE_URI']
    
    if db_uri.startswith('sqlite:///'):
        return db_uri.replace('sqlite:///', '')
    else:
        return "Banco não é SQLite (PostgreSQL/MySQL)"

def backup_database():
    """
    Cria backup do banco de dados SQLite
    Para uso pela Prefeitura Municipal de Cosmópolis
    """
    try:
        import shutil
        from datetime import datetime
        
        # Verificar se é SQLite
        db_path = get_database_path()
        if not db_path.endswith('.db'):
            print("⚠️  Backup automático disponível apenas para SQLite")
            return False
        
        # Criar diretório de backup
        backup_dir = os.path.join(os.path.dirname(db_path), 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        
        # Nome do arquivo de backup com timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f"sistema_transporte_backup_{timestamp}.db"
        backup_path = os.path.join(backup_dir, backup_filename)
        
        # Copiar arquivo
        shutil.copy2(db_path, backup_path)
        
        print(f"✅ Backup criado: {backup_path}")
        return backup_path
        
    except Exception as e:
        print(f"❌ Erro ao criar backup: {e}")
        return False

def restore_database(backup_path):
    """
    Restaura banco de dados a partir de backup
    CUIDADO: Substitui o banco atual!
    """
    try:
        import shutil
        
        # Verificar se arquivo de backup existe
        if not os.path.exists(backup_path):
            print(f"❌ Arquivo de backup não encontrado: {backup_path}")
            return False
        
        # Caminho do banco atual
        current_db_path = get_database_path()
        if not current_db_path.endswith('.db'):
            print("⚠️  Restauração disponível apenas para SQLite")
            return False
        
        # Fazer backup do banco atual antes de restaurar
        current_backup = backup_database()
        if current_backup:
            print(f"📁 Backup do banco atual salvo em: {current_backup}")
        
        # Restaurar backup
        shutil.copy2(backup_path, current_db_path)
        
        print(f"✅ Banco restaurado de: {backup_path}")
        return True
        
    except Exception as e:
        print(f"❌ Erro ao restaurar backup: {e}")
        return False

def optimize_database():
    """
    Otimiza o banco de dados SQLite
    Remove espaço não utilizado e reindexiza
    """
    try:
        # Verificar se é SQLite
        db_path = get_database_path()
        if not db_path.endswith('.db'):
            print("⚠️  Otimização automática disponível apenas para SQLite")
            return False
        
        # Executar comandos de otimização
        db.session.execute(db.text('VACUUM;'))
        db.session.execute(db.text('REINDEX;'))
        db.session.commit()
        
        print("✅ Banco de dados otimizado")
        return True
        
    except Exception as e:
        print(f"❌ Erro ao otimizar banco: {e}")
        db.session.rollback()
        return False

def get_database_stats():
    """
    Retorna estatísticas do banco de dados
    Útil para monitoramento pela Prefeitura
    """
    try:
        stats = {}
        
        # Importar modelos
        from sistema.models.usuario import Usuario
        from sistema.models.paciente import Paciente
        from sistema.models.motorista import Motorista
        from sistema.models.veiculo import Veiculo
        from sistema.models.agendamento import Agendamento
        
        # Contar registros por tabela
        stats['usuarios'] = Usuario.query.count()
        stats['pacientes'] = Paciente.query.count()
        stats['motoristas'] = Motorista.query.count()
        stats['veiculos'] = Veiculo.query.count()
        stats['agendamentos'] = Agendamento.query.count()
        
        # Estatísticas do arquivo (apenas SQLite)
        db_path = get_database_path()
        if db_path.endswith('.db') and os.path.exists(db_path):
            file_size = os.path.getsize(db_path)
            stats['tamanho_arquivo'] = f"{file_size / 1024 / 1024:.2f} MB"
            stats['ultima_modificacao'] = datetime.fromtimestamp(
                os.path.getmtime(db_path)
            ).strftime('%d/%m/%Y %H:%M:%S')
        
        return stats
        
    except Exception as e:
        print(f"❌ Erro ao obter estatísticas: {e}")
        return {}

def check_database_integrity():
    """
    Verifica integridade do banco de dados SQLite
    """
    try:
        # Verificar se é SQLite
        db_path = get_database_path()
        if not db_path.endswith('.db'):
            print("⚠️  Verificação de integridade disponível apenas para SQLite")
            return True
        
        # Executar verificação de integridade
        result = db.session.execute(db.text('PRAGMA integrity_check;')).fetchone()
        
        if result and result[0] == 'ok':
            print("✅ Integridade do banco verificada - OK")
            return True
        else:
            print(f"❌ Problemas de integridade detectados: {result}")
            return False
            
    except Exception as e:
        print(f"❌ Erro ao verificar integridade: {e}")
        return False

def migrate_to_postgresql(postgresql_uri):
    """
    Função auxiliar para migração futura do SQLite para PostgreSQL
    Sistema da Prefeitura Municipal de Cosmópolis
    """
    print("🔄 Migração para PostgreSQL")
    print("Esta função deve ser implementada quando necessário migrar para PostgreSQL")
    print("Passos recomendados:")
    print("1. Instalar psycopg2-binary")
    print("2. Configurar DATABASE_URL para PostgreSQL")
    print("3. Executar flask db init, migrate e upgrade")
    print("4. Exportar dados do SQLite e importar no PostgreSQL")
    
    # TODO: Implementar migração real quando necessário
    pass

def migrate_to_mysql(mysql_uri):
    """
    Função auxiliar para migração futura do SQLite para MySQL
    Sistema da Prefeitura Municipal de Cosmópolis
    """
    print("🔄 Migração para MySQL")
    print("Esta função deve ser implementada quando necessário migrar para MySQL")
    print("Passos recomendados:")
    print("1. Instalar PyMySQL ou mysqlclient")
    print("2. Configurar DATABASE_URL para MySQL")
    print("3. Executar flask db init, migrate e upgrade")
    print("4. Exportar dados do SQLite e importar no MySQL")
    
    # TODO: Implementar migração real quando necessário
    pass

class DatabaseManager:
    """
    Classe utilitária para gerenciamento do banco de dados
    Sistema da Prefeitura Municipal de Cosmópolis
    """
    
    @staticmethod
    def create_backup():
        """Cria backup do banco"""
        return backup_database()
    
    @staticmethod
    def restore_backup(backup_path):
        """Restaura backup"""
        return restore_database(backup_path)
    
    @staticmethod
    def optimize():
        """Otimiza banco"""
        return optimize_database()
    
    @staticmethod
    def get_stats():
        """Obtém estatísticas"""
        return get_database_stats()
    
    @staticmethod
    def check_integrity():
        """Verifica integridade"""
        return check_database_integrity()
    
    @staticmethod
    def cleanup_old_data(days=365):
        """
        Remove dados antigos do sistema
        Por padrão, remove agendamentos com mais de 1 ano
        """
        try:
            from sistema.models.agendamento import Agendamento
            from datetime import datetime, timedelta
            
            # Data limite
            limit_date = datetime.now() - timedelta(days=days)
            
            # Buscar agendamentos antigos cancelados ou concluídos
            old_appointments = Agendamento.query.filter(
                Agendamento.data_agendamento < limit_date,
                Agendamento.status.in_(['cancelado', 'concluido'])
            ).all()
            
            # Contar antes de deletar
            count = len(old_appointments)
            
            # Deletar registros
            for appointment in old_appointments:
                db.session.delete(appointment)
            
            db.session.commit()
            
            print(f"✅ Limpeza concluída: {count} agendamentos antigos removidos")
            return count
            
        except Exception as e:
            print(f"❌ Erro na limpeza de dados: {e}")
            db.session.rollback()
            return 0

# Instância do gerenciador
db_manager = DatabaseManager()

# Configurações específicas por tipo de banco
DATABASE_CONFIGS = {
    'sqlite': {
        'echo': False,
        'pool_timeout': 20,
        'pool_recycle': -1,
        'connect_args': {
            'check_same_thread': False,
            'timeout': 30
        }
    },
    'postgresql': {
        'echo': False,
        'pool_size': 10,
        'pool_timeout': 20,
        'pool_recycle': 3600,
        'max_overflow': 20
    },
    'mysql': {
        'echo': False,
        'pool_size': 10,
        'pool_timeout': 20,
        'pool_recycle': 3600,
        'max_overflow': 20,
        'connect_args': {
            'charset': 'utf8mb4'
        }
    }
}

def get_database_config(database_uri):
    """
    Retorna configuração específica baseada no tipo de banco
    """
    if 'sqlite' in database_uri:
        return DATABASE_CONFIGS['sqlite']
    elif 'postgresql' in database_uri:
        return DATABASE_CONFIGS['postgresql']
    elif 'mysql' in database_uri:
        return DATABASE_CONFIGS['mysql']
    else:
        return DATABASE_CONFIGS['sqlite']  # fallback
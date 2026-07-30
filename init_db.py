import os
import sqlite3
from datetime import datetime

def create_database():
    """Cria o banco de dados SQLite e as tabelas básicas"""
    
    # Criar pasta db se não existir
    os.makedirs('db', exist_ok=True)
    
    db_path = 'db/transporte_pacientes.db'
    
    # Conectar ao banco (cria o arquivo se não existir)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("🔧 Criando banco de dados...")
    
    # Tabela de usuários
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username VARCHAR(80) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            nome_completo VARCHAR(120) NOT NULL,
            email VARCHAR(120),
            tipo_usuario VARCHAR(20) NOT NULL DEFAULT 'operador',
            ativo BOOLEAN NOT NULL DEFAULT 1,
            data_criacao DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            ultimo_login DATETIME
        )
    ''')
    
    # Inserir usuário administrador padrão
    # Senha: admin123 (hash bcrypt)
    admin_password_hash = '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBdXwXd./.VB3a'
    
    cursor.execute('''
        INSERT OR IGNORE INTO usuarios (username, password_hash, nome_completo, email, tipo_usuario)
        VALUES (?, ?, ?, ?, ?)
    ''', ('admin', admin_password_hash, 'Administrador do Sistema', 'admin@cosmopolis.sp.gov.br', 'administrador'))
    
    print("✅ Usuário administrador criado: admin / admin123")
    
    # Commit e fechar
    conn.commit()
    conn.close()
    
    print(f"✅ Banco de dados criado: {db_path}")
    print("🎯 Sistema pronto para uso!")

if __name__ == '__main__':
    create_database()
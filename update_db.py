import sqlite3
import os

def atualizar_banco():
    try:
        # Caminho do banco
        db_path = os.path.join(os.getcwd(), 'db', 'transporte_pacientes.db')
        
        if not os.path.exists(db_path):
            print("❌ Banco de dados não encontrado!")
            return
        
        # Conectar ao banco
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Verificar se a coluna já existe
        cursor.execute("PRAGMA table_info(agendamentos)")
        colunas = [coluna[1] for coluna in cursor.fetchall()]
        
        if 'especialidade' not in colunas:
            print("🔄 Adicionando coluna 'especialidade' na tabela agendamentos...")
            cursor.execute("ALTER TABLE agendamentos ADD COLUMN especialidade TEXT")
            conn.commit()
            print("✅ Coluna 'especialidade' adicionada com sucesso!")
        else:
            print("ℹ️ Coluna 'especialidade' já existe!")
        
        conn.close()
        print("✅ Atualização do banco concluída!")
        
    except Exception as e:
        print(f"❌ Erro ao atualizar banco: {e}")

if __name__ == '__main__':
    atualizar_banco()
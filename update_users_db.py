import sqlite3
import os
from datetime import datetime

def atualizar_usuarios():
    try:
        # Caminho do banco
        db_path = os.path.join(os.getcwd(), 'db', 'transporte_pacientes.db')
        
        if not os.path.exists(db_path):
            print("❌ Banco de dados não encontrado!")
            return
        
        # Conectar ao banco
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Verificar se a coluna data_cadastro existe
        cursor.execute("PRAGMA table_info(usuarios)")
        colunas = [coluna[1] for coluna in cursor.fetchall()]
        
        if 'data_cadastro' not in colunas:
            print("🔄 Adicionando coluna 'data_cadastro' na tabela usuarios...")
            
            # Adicionar coluna sem valor padrão primeiro
            cursor.execute("ALTER TABLE usuarios ADD COLUMN data_cadastro DATETIME")
            
            # Atualizar registros existentes com a data atual
            now = datetime.now().isoformat()
            cursor.execute("UPDATE usuarios SET data_cadastro = ? WHERE data_cadastro IS NULL", (now,))
            
            conn.commit()
            print("✅ Coluna 'data_cadastro' adicionada com sucesso!")
        else:
            print("ℹ️ Coluna 'data_cadastro' já existe!")
        
        # Verificar e atualizar tipos de usuário
        print("🔄 Verificando tipos de usuário...")
        cursor.execute("SELECT id, tipo_usuario FROM usuarios")
        usuarios = cursor.fetchall()
        
        updated_count = 0
        for user_id, tipo in usuarios:
            if tipo == 'operador':
                cursor.execute("UPDATE usuarios SET tipo_usuario = 'atendente' WHERE id = ?", (user_id,))
                print(f"🔄 Usuário {user_id}: 'operador' → 'atendente'")
                updated_count += 1
        
        if updated_count > 0:
            print(f"✅ {updated_count} usuário(s) atualizado(s)")
        else:
            print("ℹ️ Nenhum tipo de usuário precisou ser atualizado")
        
        conn.commit()
        
        # Verificar se existe usuário administrador
        cursor.execute("SELECT COUNT(*) FROM usuarios WHERE tipo_usuario = 'administrador'")
        admin_count = cursor.fetchone()[0]
        
        if admin_count == 0:
            print("⚠️ Nenhum administrador encontrado! Atualizando usuário admin...")
            cursor.execute("UPDATE usuarios SET tipo_usuario = 'administrador' WHERE username = 'admin'")
            conn.commit()
            print("✅ Usuário 'admin' promovido para administrador")
        
        # Criar usuário supervisor se não existir
        cursor.execute("SELECT COUNT(*) FROM usuarios WHERE tipo_usuario = 'supervisor'")
        supervisor_count = cursor.fetchone()[0]
        
        if supervisor_count == 0:
            print("🔄 Criando usuário supervisor...")
            
            # Verificar se já existe username 'supervisor'
            cursor.execute("SELECT COUNT(*) FROM usuarios WHERE username = 'supervisor'")
            if cursor.fetchone()[0] == 0:
                # Importar aqui para evitar problemas de contexto
                try:
                    from werkzeug.security import generate_password_hash
                    
                    supervisor_hash = generate_password_hash('supervisor123')
                    now = datetime.now().isoformat()
                    
                    cursor.execute("""
                        INSERT INTO usuarios (username, password_hash, nome_completo, email, tipo_usuario, ativo, data_cadastro)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, ('supervisor', supervisor_hash, 'Supervisor do Sistema', 'supervisor@cosmopolis.sp.gov.br', 'supervisor', 1, now))
                    
                    conn.commit()
                    print("✅ Usuário supervisor criado!")
                    print("📝 Login: supervisor / supervisor123")
                    
                except ImportError:
                    print("⚠️ Não foi possível criar usuário supervisor (werkzeug não disponível)")
                    print("💡 Execute o sistema uma vez e crie manualmente")
            else:
                print("ℹ️ Username 'supervisor' já existe")
        else:
            print("ℹ️ Já existe usuário supervisor")
        
        # Mostrar resumo final
        print("\n📊 RESUMO FINAL:")
        cursor.execute("SELECT tipo_usuario, COUNT(*) FROM usuarios GROUP BY tipo_usuario")
        tipos = cursor.fetchall()
        
        for tipo, count in tipos:
            emoji = {'administrador': '👑', 'supervisor': '👨‍💼', 'atendente': '🎧'}.get(tipo, '👤')
            print(f"{emoji} {tipo.title()}: {count} usuário(s)")
        
        conn.close()
        print("\n✅ Atualização de usuários concluída com sucesso!")
        
    except Exception as e:
        print(f"❌ Erro ao atualizar usuários: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    atualizar_usuarios()
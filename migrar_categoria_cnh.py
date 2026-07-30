"""
Script de migracao: categoria_cnh VARCHAR(2) -> VARCHAR(5)
Necessario para suportar categorias combinadas (AB, AC, AD, AE)
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'db', 'transporte_pacientes.db')

def migrar():
    print(f"Conectando ao banco: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Verificar tamanho atual da coluna
    cursor.execute("PRAGMA table_info(motoristas)")
    colunas = {row[1]: row for row in cursor.fetchall()}
    col = colunas.get('categoria_cnh')
    if col:
        tipo_atual = col[2]
        print(f"Coluna categoria_cnh atual: {tipo_atual}")
        if tipo_atual.upper() in ('VARCHAR(5)', 'TEXT'):
            print("Coluna ja possui tamanho suficiente. Nada a fazer.")
            conn.close()
            return
    else:
        print("Coluna categoria_cnh nao encontrada!")
        conn.close()
        return

    # Coletar dados existentes
    cursor.execute("SELECT DISTINCT categoria_cnh FROM motoristas")
    valores = [r[0] for r in cursor.fetchall()]
    print(f"Valores existentes: {valores}")

    # Migrar usando recriacao da tabela (SQLite nao suporta ALTER COLUMN)
    print("Criando nova tabela...")
    cursor.executescript("""
        CREATE TABLE motoristas_nova (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome VARCHAR(120) NOT NULL,
            cpf VARCHAR(14) NOT NULL UNIQUE,
            telefone VARCHAR(15) NOT NULL,
            data_nascimento DATE NOT NULL,
            cnh VARCHAR(20) NOT NULL UNIQUE,
            categoria_cnh VARCHAR(5) NOT NULL,
            vencimento_cnh DATE NOT NULL,
            endereco TEXT,
            cep VARCHAR(9),
            logradouro VARCHAR(200),
            numero VARCHAR(10),
            bairro VARCHAR(100),
            ponto_referencia VARCHAR(200),
            status VARCHAR(20) NOT NULL DEFAULT 'ativo',
            observacoes TEXT,
            data_cadastro DATETIME NOT NULL
        );

        INSERT INTO motoristas_nova
            (id, nome, cpf, telefone, data_nascimento, cnh, categoria_cnh,
             vencimento_cnh, endereco, cep, logradouro, numero, bairro,
             ponto_referencia, status, observacoes, data_cadastro)
        SELECT
            id, nome, cpf, telefone, data_nascimento, cnh, categoria_cnh,
            vencimento_cnh, endereco, cep, logradouro, numero, bairro,
            ponto_referencia, status, observacoes, data_cadastro
        FROM motoristas;

        DROP TABLE motoristas;

        ALTER TABLE motoristas_nova RENAME TO motoristas;
    """)

    conn.commit()

    # Verificar resultado
    cursor.execute("PRAGMA table_info(motoristas)")
    colunas = {row[1]: row for row in cursor.fetchall()}
    col = colunas.get('categoria_cnh')
    print(f"Coluna categoria_cnh apos migracao: {col[2]}")

    cursor.execute("SELECT COUNT(*) FROM motoristas")
    total = cursor.fetchone()[0]
    print(f"Total de registros: {total}")
    print("Migracao concluida com sucesso!")

    conn.close()

if __name__ == '__main__':
    migrar()

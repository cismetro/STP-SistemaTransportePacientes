import sqlite3

DB = r"D:\Projetos\python\STP-SistemaTransportePacientes\db\transporte_pacientes.db"
c = sqlite3.connect(DB)
cur = c.cursor()

print("CONTAGENS")
for t in ("pacientes", "motoristas", "veiculos", "agendamentos"):
    cur.execute(f"SELECT COUNT(*) FROM {t}")
    print(f"  {t}: {cur.fetchone()[0]}")

print("\nPACIENTE (buscar no painel)")
for r in cur.execute(
    "SELECT id, nome, telefone, substr(endereco,1,50) FROM pacientes WHERE nome LIKE '%CRISTINA%' LIMIT 1"
):
    print(r)

print("\nMOTORISTA (buscar no painel)")
for r in cur.execute("SELECT id, nome, cpf, status FROM motoristas WHERE nome='MARCIO'"):
    print(r)

print("\nVEICULO (buscar no painel)")
for r in cur.execute("SELECT id, placa, modelo, ativo FROM veiculos WHERE placa='F00299'"):
    print(r)

print("\nAGENDAMENTO COMPLETO (com motorista)")
for r in cur.execute(
    """
    SELECT a.id, p.nome, m.nome, v.placa, a.data, a.hora, substr(a.destino,1,40), a.status
    FROM agendamentos a
    JOIN pacientes p ON p.id = a.paciente_id
    LEFT JOIN motoristas m ON m.id = a.motorista_id
    LEFT JOIN veiculos v ON v.id = a.veiculo_id
    WHERE m.nome IS NOT NULL AND v.placa IS NOT NULL
    LIMIT 1
    """
):
    print(r)

print("\nAGENDAMENTO CANCELADO")
for r in cur.execute(
    """
    SELECT a.id, p.nome, a.status, substr(a.observacoes,1,50)
    FROM agendamentos a
    JOIN pacientes p ON p.id = a.paciente_id
    WHERE a.status = 'cancelado' LIMIT 1
    """
):
    print(r)

c.close()

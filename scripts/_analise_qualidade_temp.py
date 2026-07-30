"""Análise de qualidade e relacionamentos - somente leitura."""
import re
import pyodbc

ACCESS = r"D:\Projetos\python\STP-SistemaTransportePacientes\dados\Banco-AGENDAMENTO-DE-TRANSPORTE.accdb"
conn = pyodbc.connect(
    f"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={ACCESS};",
    readonly=True,
)
cur = conn.cursor()


def validar_cpf(cpf):
    cpf = re.sub(r"\D", "", str(cpf or ""))
    if not cpf or cpf in ("0", "00"):
        return False
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    for i in range(9, 11):
        s = sum(int(cpf[n]) * ((i + 1) - n) for n in range(i))
        if (s * 10 % 11) % 10 != int(cpf[i]):
            return False
    return True


print("=" * 60)
print("MOTORISTAS (TB MOTORISTA)")
print("=" * 60)
cur.execute("SELECT [Código],[MOTORISTAS] FROM [TB MOTORISTA]")
mot = cur.fetchall()
print(f"Total cadastrados: {len(mot)}")
for r in mot[:10]:
    print(f"  ID={r[0]} | {r[1]}")
cur.execute(
    "SELECT [MOTORISTAS], COUNT(*) FROM [TB MOTORISTA] "
    "GROUP BY [MOTORISTAS] HAVING COUNT(*)>1"
)
dups = cur.fetchall()
print(f"Nomes duplicados: {dups}")

print("\n" + "=" * 60)
print("FROTAS (TB FROTAS)")
print("=" * 60)
cur.execute("SELECT [Código],[FROTAS] FROM [TB FROTAS]")
frotas_rows = cur.fetchall()
frotas = {r[1]: r[0] for r in frotas_rows}
print(f"Total cadastradas: {len(frotas)}")
print(f"Numeros: {sorted(frotas.keys())}")

print("\n" + "=" * 60)
print("TRANSPORTES (TB TRANSPORTE)")
print("=" * 60)
cur.execute("SELECT COUNT(*) FROM [TB TRANSPORTE]")
print(f"Total: {cur.fetchone()[0]}")

checks = [
    ("Paciente nulo", "SELECT COUNT(*) FROM [TB TRANSPORTE] WHERE [NOME DO PACIENTE] IS NULL"),
    ("Data consulta nula", "SELECT COUNT(*) FROM [TB TRANSPORTE] WHERE [DATA DA CONSULTA] IS NULL"),
    ("Motorista nulo", "SELECT COUNT(*) FROM [TB TRANSPORTE] WHERE [MOTORISTA] IS NULL"),
    ("Frota nula", "SELECT COUNT(*) FROM [TB TRANSPORTE] WHERE [FROTA] IS NULL"),
    ("Destino nulo", "SELECT COUNT(*) FROM [TB TRANSPORTE] WHERE [DESTINO] IS NULL"),
    ("Datas antes 2000", "SELECT COUNT(*) FROM [TB TRANSPORTE] WHERE [DATA DA CONSULTA] < #2000-01-01#"),
    ("Datas depois 2027", "SELECT COUNT(*) FROM [TB TRANSPORTE] WHERE [DATA DA CONSULTA] > #2027-01-01#"),
]
for label, sql in checks:
    cur.execute(sql)
    print(f"  {label}: {cur.fetchone()[0]}")

cur.execute(
    "SELECT DISTINCT [MOTORISTA] FROM [TB TRANSPORTE] WHERE [MOTORISTA] IS NOT NULL"
)
mot_trans = {r[0].strip().upper() for r in cur.fetchall()}
mot_cad = {r[1].strip().upper() for r in mot if r[1]}
orphan_mot = sorted(mot_trans - mot_cad)
print(f"\nMotoristas em transporte fora de TB MOTORISTA: {len(orphan_mot)}")
if orphan_mot:
    print(f"  Exemplos: {orphan_mot[:20]}")

cur.execute("SELECT DISTINCT [FROTA] FROM [TB TRANSPORTE] WHERE [FROTA] IS NOT NULL")
frota_trans = {r[0] for r in cur.fetchall()}
orphan_frota = sorted(frota_trans - set(frotas.keys()))
print(f"\nFrotas em transporte fora de TB FROTAS: {len(orphan_frota)}")
if orphan_frota:
    print(f"  Valores: {orphan_frota[:20]}")

cur.execute("SELECT [CÓDIGO DO PACIENTE],[NOME DO PACIENTE] FROM [TAB PACIENTE]")
pac_map = {r[1].strip().upper(): r[0] for r in cur.fetchall() if r[1]}
cur.execute(
    "SELECT DISTINCT [NOME DO PACIENTE] FROM [TB TRANSPORTE] WHERE [NOME DO PACIENTE] IS NOT NULL"
)
pac_trans = {r[0].strip().upper() for r in cur.fetchall()}
orphan_pac = sorted(pac_trans - set(pac_map.keys()))
print(f"\nPacientes em transporte sem cadastro em TAB PACIENTE: {len(orphan_pac)} de {len(pac_trans)}")
if orphan_pac:
    print(f"  Exemplos: {orphan_pac[:15]}")

print("\n" + "=" * 60)
print("PACIENTES (TAB PACIENTE)")
print("=" * 60)
cur.execute("SELECT [CPF] FROM [TAB PACIENTE]")
cpfs = cur.fetchall()
inv = null = valid = 0
for r in cpfs:
    if r[0] is None or str(r[0]) in ("0.0", "0", ""):
        null += 1
    elif validar_cpf(r[0]):
        valid += 1
    else:
        inv += 1
print(f"CPF: validos={valid}, invalidos={inv}, nulos/zerados={null}")

cur.execute(
    "SELECT [NOME DO PACIENTE], COUNT(*) c FROM [TAB PACIENTE] "
    "GROUP BY [NOME DO PACIENTE] HAVING COUNT(*)>1"
)
print(f"Nomes duplicados: {cur.fetchall()}")

print("\nTop 10 motoristas em transportes:")
cur.execute(
    "SELECT TOP 10 [MOTORISTA], COUNT(*) c FROM [TB TRANSPORTE] "
    "GROUP BY [MOTORISTA] ORDER BY COUNT(*) DESC"
)
for r in cur.fetchall():
    print(f"  {r[0]}: {r[1]}")

print("\nTop 10 frotas em transportes:")
cur.execute(
    "SELECT TOP 10 [FROTA], COUNT(*) c FROM [TB TRANSPORTE] "
    "GROUP BY [FROTA] ORDER BY COUNT(*) DESC"
)
for r in cur.fetchall():
    print(f"  Frota {r[0]}: {r[1]}")

print("\nAmostra transporte:")
cur.execute("SELECT TOP 3 * FROM [TB TRANSPORTE]")
cols = [d[0] for d in cur.description]
for row in cur.fetchall():
    d = dict(zip(cols, row))
    print({k: str(v)[:60] if v else None for k, v in d.items()})

conn.close()

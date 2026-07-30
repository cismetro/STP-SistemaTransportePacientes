"""Script temporário de análise do banco Access - somente leitura."""
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime

ACCESS_PATH = r"D:\Projetos\python\STP-SistemaTransportePacientes\dados\Banco-AGENDAMENTO-DE-TRANSPORTE.accdb"
SQLITE_PATH = r"D:\Projetos\python\STP-SistemaTransportePacientes\db\transporte_pacientes.db"
OUTPUT_DIR = r"D:\Projetos\python\STP-SistemaTransportePacientes\relatorios"


def validar_cpf(cpf):
    cpf = re.sub(r"\D", "", str(cpf or ""))
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    for i in range(9, 11):
        soma = sum(int(cpf[num]) * ((i + 1) - num) for num in range(0, i))
        dig = (soma * 10 % 11) % 10
        if dig != int(cpf[i]):
            return False
    return True


def validar_placa(placa):
    p = re.sub(r"[\s\-]", "", str(placa or "").upper())
    if not p:
        return False
    return bool(re.match(r"^[A-Z]{3}[0-9][A-Z0-9][0-9]{2}$", p) or re.match(r"^[A-Z]{3}[0-9]{4}$", p))


def get_access_driver():
    import pyodbc
    for d in pyodbc.drivers():
        if "Access" in d and ("*.mdb" in d or "*.accdb" in d or "ACE" in d):
            return d
    for d in pyodbc.drivers():
        if "ACE" in d or "Jet" in d:
            return d
    raise RuntimeError(f"Driver Access não encontrado. Drivers: {pyodbc.drivers()}")


def connect_access():
    import pyodbc
    driver = get_access_driver()
    conn_str = f"DRIVER={{{driver}}};DBQ={ACCESS_PATH};"
    return pyodbc.connect(conn_str, readonly=True)


def list_tables(cursor):
    tables = []
    for row in cursor.tables(tableType="TABLE"):
        name = row.table_name
        if not name.startswith("MSys") and not name.startswith("~"):
            tables.append(name)
    return sorted(set(tables))


def get_columns(cursor, table):
    cols = []
    for row in cursor.columns(table=table):
        cols.append({
            "name": row.column_name,
            "type": row.type_name,
            "size": row.column_size,
            "nullable": row.nullable == 1,
            "ordinal": row.ordinal_position,
        })
    cols.sort(key=lambda c: c["ordinal"])
    return cols


def get_pk(cursor, table):
    try:
        pks = []
        for row in cursor.primaryKeys(table=table):
            pks.append((row.key_seq, row.column_name))
        return [c for _, c in sorted(pks)]
    except Exception:
        return []


def get_indexes(cursor, table):
    idx = defaultdict(list)
    try:
        for row in cursor.statistics(table=table):
            if row.index_name and not row.index_name.startswith("PrimaryKey"):
                idx[row.index_name].append(row.column_name)
    except Exception:
        pass
    return dict(idx)


def get_fk_relations(cursor):
    relations = []
    try:
        for row in cursor.foreignKeys():
            relations.append({
                "fk_table": row.fktable_name,
                "fk_column": row.fkcolumn_name,
                "pk_table": row.pktable_name,
                "pk_column": row.pkcolumn_name,
            })
    except Exception:
        pass
    return relations


def count_rows(cursor, table):
    try:
        cursor.execute(f"SELECT COUNT(*) FROM [{table}]")
        return cursor.fetchone()[0]
    except Exception as e:
        return f"ERRO: {e}"


def sample_data(cursor, table, limit=3):
    try:
        cursor.execute(f"SELECT TOP {limit} * FROM [{table}]")
        cols = [d[0] for d in cursor.description]
        rows = []
        for r in cursor.fetchall():
            rows.append({cols[i]: (None if r[i] is None else str(r[i])[:200]) for i in range(len(cols))})
        return rows
    except Exception as e:
        return [{"erro": str(e)}]


def identify_priority_tables(tables):
    keywords = {
        "motoristas": ["motor", "condutor", "driver"],
        "veiculos": ["veic", "carro", "automo", "frota", "placa"],
        "agendamentos": ["agend", "transport", "viagem", "solicit", "marcac"],
        "pacientes": ["pacient", "usuario", "benefic"],
    }
    mapping = {k: [] for k in keywords}
    for t in tables:
        tl = t.lower()
        for cat, kws in keywords.items():
            if any(k in tl for k in kws):
                mapping[cat].append(t)
    return mapping


def analyze_duplicates(cursor, table, columns):
    results = {}
    for col in columns:
        try:
            cursor.execute(
                f"SELECT [{col}], COUNT(*) AS cnt FROM [{table}] "
                f"WHERE [{col}] IS NOT NULL GROUP BY [{col}] HAVING COUNT(*) > 1"
            )
            dups = cursor.fetchall()
            if dups:
                results[col] = len(dups)
        except Exception:
            pass
    return results


def analyze_nulls(cursor, table, columns):
    nulls = {}
    for col in columns:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM [{table}] WHERE [{col}] IS NULL OR [{col}] = ''")
            nulls[col] = cursor.fetchone()[0]
        except Exception:
            pass
    return nulls


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    report = {
        "gerado_em": datetime.now().isoformat(),
        "access_path": ACCESS_PATH,
        "sqlite_path": SQLITE_PATH,
    }

    import pyodbc
    print("Driver:", get_access_driver())
    conn = connect_access()
    cur = conn.cursor()

    tables = list_tables(cur)
    report["total_tabelas"] = len(tables)
    report["tabelas"] = {}

    all_relations = get_fk_relations(cur)
    report["relacionamentos"] = all_relations

    priority = identify_priority_tables(tables)
    report["tabelas_prioritarias"] = priority

    for table in tables:
        print(f"Analisando: {table}")
        cols = get_columns(cur, table)
        col_names = [c["name"] for c in cols]
        cnt = count_rows(cur, table)
        info = {
            "registros": cnt,
            "colunas": cols,
            "chave_primaria": get_pk(cur, table),
            "indices": get_indexes(cur, table),
            "amostra": sample_data(cur, table),
        }
        if isinstance(cnt, int) and cnt > 0:
            info["campos_nulos"] = analyze_nulls(cur, table, col_names)
            info["duplicatas"] = analyze_duplicates(cur, table, col_names)
        report["tabelas"][table] = info

    # Análises específicas nas tabelas prioritárias
    quality = {"cpfs_invalidos": [], "placas_invalidas": [], "relacionamentos_quebrados": []}

    for t in priority.get("motoristas", []):
        cols = [c["name"] for c in report["tabelas"][t]["colunas"]]
        cpf_cols = [c for c in cols if "cpf" in c.lower()]
        for cpf_col in cpf_cols:
            try:
                cur.execute(f"SELECT [{cpf_col}] FROM [{t}] WHERE [{cpf_col}] IS NOT NULL")
                invalid = 0
                total = 0
                for row in cur.fetchall():
                    total += 1
                    if not validar_cpf(row[0]):
                        invalid += 1
                        if len(quality["cpfs_invalidos"]) < 20:
                            quality["cpfs_invalidos"].append({"tabela": t, "campo": cpf_col, "valor": str(row[0])})
                quality.setdefault("resumo_cpf", {})[f"{t}.{cpf_col}"] = {"total": total, "invalidos": invalid}
            except Exception as e:
                quality.setdefault("erros", []).append(str(e))

    for t in priority.get("veiculos", []):
        cols = [c["name"] for c in report["tabelas"][t]["colunas"]]
        placa_cols = [c for c in cols if "placa" in c.lower()]
        for placa_col in placa_cols:
            try:
                cur.execute(f"SELECT [{placa_col}] FROM [{t}] WHERE [{placa_col}] IS NOT NULL")
                invalid = 0
                total = 0
                for row in cur.fetchall():
                    total += 1
                    if not validar_placa(row[0]):
                        invalid += 1
                        if len(quality["placas_invalidas"]) < 20:
                            quality["placas_invalidas"].append({"tabela": t, "campo": placa_col, "valor": str(row[0])})
                quality.setdefault("resumo_placa", {})[f"{t}.{placa_col}"] = {"total": total, "invalidos": invalid}
            except Exception:
                pass

    report["qualidade_dados"] = quality

    # SQLite atual
    sqlite_info = {}
    if os.path.exists(SQLITE_PATH):
        sconn = sqlite3.connect(SQLITE_PATH)
        scur = sconn.cursor()
        scur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        for t in [r[0] for r in scur.fetchall()]:
            scur.execute(f"SELECT COUNT(*) FROM [{t}]")
            sqlite_info[t] = scur.fetchone()[0]
        sconn.close()
    report["sqlite_atual"] = sqlite_info

    out_json = os.path.join(OUTPUT_DIR, "analise_access_raw.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    print("\n=== RESUMO ===")
    print(f"Tabelas Access: {len(tables)}")
    for t in tables:
        print(f"  {t}: {report['tabelas'][t]['registros']} registros")
    print(f"\nPrioritárias: {json.dumps(priority, ensure_ascii=False)}")
    print(f"\nSQLite atual: {sqlite_info}")
    print(f"\nJSON salvo em: {out_json}")
    conn.close()
    return report


if __name__ == "__main__":
    main()

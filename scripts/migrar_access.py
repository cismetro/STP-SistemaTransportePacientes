"""
Migração Access -> SQLite (STP)
Zera pacientes, motoristas, veículos e agendamentos e importa do Access.
Usa sqlite3 direto (sem dependência do Flask).
"""
import os
import re
import shutil
import sqlite3
from datetime import date, datetime, time

import pyodbc

BASEDIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACCESS_PATH = os.path.join(BASEDIR, "dados", "Banco-AGENDAMENTO-DE-TRANSPORTE.accdb")
DB_PATH = os.path.join(BASEDIR, "db", "transporte_pacientes.db")
LOG_PATH = os.path.join(BASEDIR, "relatorios", "migracao_log.txt")

CANCEL_KEYWORDS = ("CANCELOU", "CANC.", "CANC ", " NAO FOI", "NAO FOI", "RETORNO QUANDO")
NOW = datetime.now().isoformat(sep=" ", timespec="seconds")


def log(msg):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def norm_name(name):
    if not name:
        return ""
    n = str(name).strip().upper()
    n = re.sub(r"\s+", " ", n)
    for kw in (" - S.T", "-S.T", " S.T", "-ST", "- S.T"):
        n = n.replace(kw, "")
    n = re.sub(r"\s*-\s*CANCELOU.*", "", n)
    n = re.sub(r"\s*CANCELOU.*", "", n)
    n = re.sub(r"\s*-\s*CANC\..*", "", n)
    n = re.sub(r"\s*--.*", "", n)
    return n.strip()


def cpf_digits(value):
    if value is None:
        return ""
    s = str(value).strip()
    if s.endswith(".0"):
        s = s[:-2]
    s = re.sub(r"\D", "", s)
    if not s or s == "0":
        return ""
    return s.zfill(11) if len(s) <= 11 else s[:11]


def calc_cpf_check(digits9):
    def dv(nums, start):
        s = sum(int(n) * w for n, w in zip(nums, range(start, 1, -1)))
        r = (s * 10) % 11
        return "0" if r == 10 else str(r)

    return dv(digits9, 10) + dv(digits9 + dv(digits9, 10), 11)


def format_cpf(digits11):
    d = digits11.zfill(11)
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"


def make_placeholder_cpf(seq, series=9):
    base_str = f"{series * 10**8 + (int(seq) % 10**8):09d}"
    return format_cpf(base_str + calc_cpf_check(base_str))


def validar_cpf_digits(d):
    if len(d) != 11 or d == d[0] * 11:
        return False
    return calc_cpf_check(d[:9]) == d[9:]


def parse_access_date(val):
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date().isoformat()
    if isinstance(val, date):
        return val.isoformat()
    return None


def parse_access_time(val):
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.time().strftime("%H:%M:%S")
    if isinstance(val, time):
        return val.strftime("%H:%M:%S")
    return None


def infer_status(paciente_nome, motorista_nome, obs):
    text = " ".join(filter(None, [paciente_nome, motorista_nome, obs])).upper()
    if any(k in text for k in CANCEL_KEYWORDS):
        return "cancelado"
    return "agendado"


def frota_placa(num):
    return f"F{int(num):05d}"[:8]


def build_endereco(rua, numero, bairro, complemento):
    parts = []
    if rua:
        parts.append(str(rua).strip())
    if numero:
        parts.append(str(numero).strip())
    if bairro:
        parts.append(str(bairro).strip())
    if complemento:
        parts.append(str(complemento).strip())
    return ", ".join(parts) if parts else "Cosmópolis-SP"


def connect_access():
    return pyodbc.connect(
        f"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={ACCESS_PATH};",
        readonly=True,
    )


def backup_db():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = DB_PATH.replace(".db", f"_backup_{ts}.db")
    shutil.copy2(DB_PATH, backup)
    log(f"Backup criado: {backup}")


def clear_tables(conn):
    log("Limpando tabelas atuais...")
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = OFF")
    for t in ("uso_veiculos", "abastecimentos", "agendamentos", "motoristas", "veiculos", "pacientes"):
        cur.execute(f"DELETE FROM {t}")
    try:
        cur.execute(
            "DELETE FROM sqlite_sequence WHERE name IN "
            "('pacientes','motoristas','veiculos','agendamentos')"
        )
    except sqlite3.OperationalError:
        pass
    conn.commit()
    cur.execute("PRAGMA foreign_keys = ON")
    log("Tabelas limpas.")


def import_motoristas(conn):
    cur_acc = connect_access().cursor()
    cur_acc.execute("SELECT [Código],[MOTORISTAS] FROM [TB MOTORISTA]")
    rows = cur_acc.fetchall()
    cur_acc.close()

    cur = conn.cursor()
    mapa = {}
    seen = set()
    cpf_seq = 1

    for codigo, nome in rows:
        if not nome:
            continue
        nome_clean = str(nome).strip()[:120]
        key = norm_name(nome_clean)
        if key in seen:
            log(f"Motorista duplicado ignorado: {nome_clean}")
            continue
        seen.add(key)

        cur.execute(
            """INSERT INTO motoristas
               (nome, cpf, telefone, data_nascimento, cnh, categoria_cnh, vencimento_cnh,
                status, observacoes, data_cadastro)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                nome_clean,
                make_placeholder_cpf(cpf_seq, 9),
                "(19) 0000-0000",
                "1980-01-01",
                f"MOT{int(codigo):06d}",
                "B",
                "2030-12-31",
                "ativo",
                "Importado do Access - dados complementares pendentes",
                NOW,
            ),
        )
        cpf_seq += 1
        mid = cur.lastrowid
        mapa[key] = mid
        mapa[nome_clean.upper()] = mid

    conn.commit()
    log(f"Motoristas importados: {len(seen)}")
    return mapa


def import_veiculos(conn):
    cur_acc = connect_access().cursor()
    cur_acc.execute("SELECT [FROTAS] FROM [TB FROTAS] WHERE [FROTAS] IS NOT NULL")
    frotas_cad = {int(r[0]) for r in cur_acc.fetchall()}
    cur_acc.execute("SELECT DISTINCT [FROTA] FROM [TB TRANSPORTE] WHERE [FROTA] IS NOT NULL")
    frotas_trans = {int(r[0]) for r in cur_acc.fetchall()}
    cur_acc.close()

    cur = conn.cursor()
    mapa = {}
    for num in sorted(frotas_cad | frotas_trans):
        cur.execute(
            """INSERT INTO veiculos
               (placa, marca, modelo, ano, tipo, capacidade, adaptado, observacoes,
                ativo, data_cadastro, tipo_propriedade)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                frota_placa(num),
                "N/I",
                f"Frota {num}",
                2020,
                "van",
                4,
                0,
                f"Número de frota Access: {num}",
                1,
                NOW,
                "proprio",
            ),
        )
        mapa[num] = cur.lastrowid

    conn.commit()
    log(f"Veículos importados: {len(mapa)}")
    return mapa


def import_pacientes(conn):
    cur_acc = connect_access().cursor()
    cur_acc.execute(
        "SELECT [CÓDIGO DO PACIENTE],[NOME DO PACIENTE],[TELEFONE],[DT DE NASCIMENTO],"
        "[RUA],[NUMERO],[BAIRRO],[COMPLEMENTO],[CPF],[OBSERVAÇÃO],[PONTO],"
        "[CARACTERISTICA ESPECIAL] FROM [TAB PACIENTE]"
    )
    rows = cur_acc.fetchall()
    cur_acc.close()

    cur = conn.cursor()
    mapa_nome = {}
    cpf_usados = set()
    placeholder_seq = 1
    count = 0

    for row in rows:
        codigo, nome, telefone, dt_nasc, rua, numero, bairro, comp, cpf_raw, obs, ponto, carac = row
        if not nome:
            continue

        nome_clean = str(nome).strip()[:120]
        cpf_d = cpf_digits(cpf_raw)
        if cpf_d and validar_cpf_digits(cpf_d):
            cpf_fmt = format_cpf(cpf_d)
        else:
            while True:
                cpf_fmt = make_placeholder_cpf(placeholder_seq, 8)
                placeholder_seq += 1
                if cpf_fmt not in cpf_usados:
                    break

        while cpf_fmt in cpf_usados:
            cpf_fmt = make_placeholder_cpf(placeholder_seq, 8)
            placeholder_seq += 1
        cpf_usados.add(cpf_fmt)

        tel = str(telefone).strip()[:15] if telefone else "(19) 0000-0000"
        nasc = parse_access_date(dt_nasc) or "1900-01-01"
        endereco = build_endereco(rua, numero, bairro, comp)
        obs_parts = [x for x in [obs, ponto, carac] if x]
        observacoes = " | ".join(str(x) for x in obs_parts) if obs_parts else None

        cur.execute(
            """INSERT INTO pacientes
               (nome, cpf, telefone, data_nascimento, endereco, observacoes, ativo, data_cadastro)
               VALUES (?,?,?,?,?,?,?,?)""",
            (nome_clean, cpf_fmt, tel, nasc, endereco, observacoes, 1, NOW),
        )
        pid = cur.lastrowid
        mapa_nome[norm_name(nome_clean)] = pid
        mapa_nome[nome_clean.upper()] = pid
        count += 1

    conn.commit()
    log(f"Pacientes importados: {count}")
    return mapa_nome, cpf_usados, placeholder_seq


def get_or_create_paciente(conn, nome, mapa_nome, cpf_usados, placeholder_seq):
    if not nome:
        return None, placeholder_seq

    key = norm_name(nome)
    if key in mapa_nome:
        return mapa_nome[key], placeholder_seq

    nome_clean = str(nome).strip()[:120]
    while True:
        cpf_fmt = make_placeholder_cpf(placeholder_seq, 7)
        placeholder_seq += 1
        if cpf_fmt not in cpf_usados:
            break
    cpf_usados.add(cpf_fmt)

    cur = conn.cursor()
    cur.execute(
        """INSERT INTO pacientes
           (nome, cpf, telefone, data_nascimento, endereco, observacoes, ativo, data_cadastro)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            nome_clean,
            cpf_fmt,
            "(19) 0000-0000",
            "1900-01-01",
            "Cosmópolis-SP",
            "Criado automaticamente na migração (não estava em TAB PACIENTE)",
            1,
            NOW,
        ),
    )
    pid = cur.lastrowid
    mapa_nome[key] = pid
    mapa_nome[nome_clean.upper()] = pid
    return pid, placeholder_seq


def import_agendamentos(conn, mapa_motorista, mapa_veiculo, mapa_nome_paciente, cpf_usados, placeholder_seq):
    cur_acc = connect_access().cursor()
    cur_acc.execute(
        "SELECT [Código],[DATA DA CONSULTA],[NOME DO PACIENTE],[MOTORISTA],[FROTA],"
        "[DESTINO],[OBSERVAÇÃO],[HORA DA CONSULTA],[ESPECIALIDADE],[HORA SAIDA],"
        "[CONDIÇÃO DO PACIENTE],[DIA DA SEMANA] FROM [TB TRANSPORTE]"
    )
    rows = cur_acc.fetchall()
    cur_acc.close()

    cur = conn.cursor()
    enderecos = {r[0]: r[1] for r in conn.execute("SELECT id, endereco FROM pacientes").fetchall()}

    importados = ignorados = 0
    criados = 0

    for row in rows:
        codigo, data_cons, pac_nome, mot_nome, frota, destino, obs, hora_cons, esp, hora_saida, condicao, dia_sem = row

        if not pac_nome and not data_cons:
            ignorados += 1
            continue
        if not pac_nome:
            ignorados += 1
            continue

        data_ag = parse_access_date(data_cons)
        if not data_ag:
            ignorados += 1
            continue

        hora_ag = parse_access_time(hora_cons) or parse_access_time(hora_saida) or "08:00:00"
        destino_txt = str(destino).strip() if destino else "Não informado"

        pac_id_before = mapa_nome_paciente.get(norm_name(pac_nome))
        pac_id, placeholder_seq = get_or_create_paciente(
            conn, pac_nome, mapa_nome_paciente, cpf_usados, placeholder_seq
        )
        if pac_id_before is None:
            criados += 1
            enderecos[pac_id] = "Cosmópolis-SP"

        mot_id = None
        if mot_nome:
            mot_key = norm_name(mot_nome)
            mot_id = mapa_motorista.get(mot_key) or mapa_motorista.get(str(mot_nome).strip().upper())

        veic_id = mapa_veiculo.get(int(frota)) if frota is not None else None
        origem = enderecos.get(pac_id, "Cosmópolis-SP")

        obs_parts = [x for x in [obs, esp, condicao, dia_sem] if x]
        observacoes = " | ".join(str(x) for x in obs_parts) if obs_parts else None
        status = infer_status(pac_nome, mot_nome, observacoes)

        cur.execute(
            """INSERT INTO agendamentos
               (paciente_id, veiculo_id, motorista_id, tipo_transporte, data, hora,
                origem, destino, observacoes, status, data_cadastro)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                pac_id,
                veic_id,
                mot_id,
                "consulta",
                data_ag,
                hora_ag,
                origem,
                destino_txt,
                observacoes,
                status,
                NOW,
            ),
        )
        importados += 1
        if importados % 1000 == 0:
            conn.commit()
            log(f"  ... {importados} agendamentos processados")

    conn.commit()
    log(f"Agendamentos importados: {importados}")
    log(f"Agendamentos ignorados: {ignorados}")
    log(f"Pacientes extras criados na migração: {criados}")
    return importados


def main():
    if not os.path.exists(ACCESS_PATH):
        raise FileNotFoundError(f"Access não encontrado: {ACCESS_PATH}")
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"SQLite não encontrado: {DB_PATH}")

    open(LOG_PATH, "w", encoding="utf-8").close()
    log("=== INÍCIO DA MIGRAÇÃO ===")
    backup_db()

    conn = sqlite3.connect(DB_PATH)
    try:
        clear_tables(conn)
        mapa_motorista = import_motoristas(conn)
        mapa_veiculo = import_veiculos(conn)
        mapa_nome, cpf_usados, placeholder_seq = import_pacientes(conn)
        import_agendamentos(conn, mapa_motorista, mapa_veiculo, mapa_nome, cpf_usados, placeholder_seq)

        cur = conn.cursor()
        log("=== RESULTADO FINAL ===")
        for t in ("pacientes", "motoristas", "veiculos", "agendamentos"):
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            log(f"{t.capitalize()}: {cur.fetchone()[0]}")
        log("=== MIGRAÇÃO CONCLUÍDA ===")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

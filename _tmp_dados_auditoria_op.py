# -*- coding: utf-8 -*-
import json
import sqlite3
from pathlib import Path

con = sqlite3.connect(Path("db/transporte_pacientes.db"))
con.row_factory = sqlite3.Row


def q(sql, *a):
    return [dict(r) for r in con.execute(sql, a)]


out = {
    "pacientes": q(
        "SELECT id, nome, cpf, condicao_paciente FROM pacientes WHERE ativo=1 ORDER BY id LIMIT 25"
    ),
    "acompanhantes": q(
        "SELECT a.id, a.nome, a.paciente_id, a.parentesco, p.nome AS pac "
        "FROM acompanhantes a JOIN pacientes p ON p.id=a.paciente_id "
        "WHERE a.ativo=1 ORDER BY a.id LIMIT 20"
    ),
    "motoristas": q(
        "SELECT id, nome, status FROM motoristas WHERE status='ativo' ORDER BY id LIMIT 20"
    ),
    "veiculos": q(
        "SELECT id, placa, marca, modelo, frota_id, ativo FROM veiculos WHERE ativo=1 ORDER BY id LIMIT 20"
    ),
    "frotas": q(
        "SELECT id, numero, nome, ativo FROM frotas WHERE ativo=1 ORDER BY id LIMIT 20"
    ),
    "agendamentos": q(
        "SELECT id, paciente_id, status, data, hora, motorista_id, veiculo_id, frota_id, "
        "origem, destino, tipo_transporte FROM agendamentos "
        "WHERE status!='cancelado' ORDER BY id DESC LIMIT 15"
    ),
    "especialidades": q(
        "SELECT tipo_transporte, COUNT(*) AS c FROM agendamentos "
        "GROUP BY tipo_transporte ORDER BY c DESC LIMIT 12"
    ),
    "destinos": q(
        "SELECT destino, COUNT(*) AS c FROM agendamentos "
        "WHERE destino IS NOT NULL AND TRIM(destino)!='' "
        "GROUP BY destino ORDER BY c DESC LIMIT 10"
    ),
}
con.close()
Path("_tmp_dados_auditoria_op.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
)
print("OK", {k: len(v) for k, v in out.items()})

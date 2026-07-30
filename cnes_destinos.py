# -*- coding: utf-8 -*-
"""
Destinos predefinidos via CNES (Dados Abertos do Ministério da Saúde).
API: https://apidadosabertos.saude.gov.br/cnes/estabelecimentos
Cache local permite uso offline e busca rápida após sincronização.
"""
from __future__ import annotations

import gzip
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

# 17 cidades oficiais (ordem alfabética) + código IBGE (6 dígitos = CNES/CODUFMUN)
CIDADES_DESTINO_CNES = [
    {"nome": "Americana", "ibge6": "350160"},
    {"nome": "Amparo", "ibge6": "350190"},
    {"nome": "Artur Nogueira", "ibge6": "350380"},
    {"nome": "Atibaia", "ibge6": "350410"},
    {"nome": "Barretos", "ibge6": "350550"},
    {"nome": "Barueri", "ibge6": "350570"},
    {"nome": "Bauru", "ibge6": "350600"},
    {"nome": "Bragança Paulista", "ibge6": "350760"},
    {"nome": "Campinas", "ibge6": "350950"},
    {"nome": "Itatiba", "ibge6": "352340"},
    {"nome": "Jundiaí", "ibge6": "352590"},
    {"nome": "Paulínia", "ibge6": "353650"},
    {"nome": "Piracicaba", "ibge6": "353870"},
    {"nome": "Santa Bárbara d'Oeste", "ibge6": "354580"},
    {"nome": "São Paulo", "ibge6": "355030"},
    {"nome": "Serra Negra", "ibge6": "355160"},
    {"nome": "Sumaré", "ibge6": "355240"},
]

CNES_API_BASE = "https://apidadosabertos.saude.gov.br/cnes/estabelecimentos"
CNES_PAGE_SIZE = 20
CNES_CACHE_DIAS = 30
# Limite de segurança por sincronização (São Paulo é muito grande)
CNES_MAX_PAGINAS = 400  # até ~8000 estabelecimentos por cidade


def listar_cidades_destino_cnes():
    """Lista ordenada das cidades predefinidas."""
    return list(CIDADES_DESTINO_CNES)


def qtd_cidades_destino_cnes():
    return len(CIDADES_DESTINO_CNES)


def cidade_cnes_por_nome(nome):
    if not nome:
        return None
    alvo = str(nome).strip().upper()
    for c in CIDADES_DESTINO_CNES:
        if c["nome"].upper() == alvo:
            return c
    return None


def _ssl_context():
    # Portal MS / Windows frequentemente falha na cadeia SSL mesmo com certifi
    return ssl._create_unverified_context()


def _http_get_json(url, timeout=45):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "STP-SistemaTransportePacientes/1.0 (CNES)",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
        raw = resp.read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def buscar_cnes_api_pagina(codigo_municipio_6, offset=0, limit=CNES_PAGE_SIZE):
    """Uma página da API pública CNES."""
    qs = urllib.parse.urlencode(
        {
            "codigo_municipio": str(codigo_municipio_6),
            "limit": int(limit),
            "offset": int(offset),
        }
    )
    data = _http_get_json(f"{CNES_API_BASE}?{qs}")
    return data.get("estabelecimentos") or []


def normalizar_estabelecimento_api(item, municipio_nome, codigo_municipio_6):
    nome = (item.get("nome_fantasia") or item.get("nome_razao_social") or "").strip()
    endereco = (item.get("endereco_estabelecimento") or "").strip()
    numero = (item.get("numero_estabelecimento") or "").strip()
    bairro = (item.get("bairro_estabelecimento") or "").strip()
    cep = (item.get("codigo_cep_estabelecimento") or "").strip()
    telefone = (item.get("numero_telefone_estabelecimento") or "").strip()
    codigo = item.get("codigo_cnes")
    if codigo is None:
        return None
    return {
        "codigo_cnes": str(codigo),
        "codigo_municipio": str(codigo_municipio_6),
        "municipio_nome": municipio_nome,
        "nome_fantasia": nome,
        "razao_social": (item.get("nome_razao_social") or "").strip(),
        "endereco": endereco,
        "numero": numero,
        "bairro": bairro,
        "cep": cep,
        "telefone": telefone,
        "tipo_unidade": item.get("codigo_tipo_unidade"),
        "esfera": (item.get("descricao_esfera_administrativa") or "").strip(),
    }


def formatar_destino_cnes(est, cidade=None):
    """Texto único para campo destino / impressões (motorista precisa do local exato)."""
    cidade = cidade or est.get("municipio_nome") or ""
    nome = est.get("nome_fantasia") or est.get("razao_social") or ""
    partes_end = []
    if est.get("endereco"):
        end = est["endereco"]
        if est.get("numero"):
            end = f"{end} Nº{est['numero']}"
        partes_end.append(end)
    if est.get("bairro"):
        partes_end.append(est["bairro"])
    endereco = ", ".join(partes_end)
    if cidade and nome and endereco:
        return f"{cidade}/{nome} - {endereco}"
    if cidade and nome:
        return f"{cidade}/{nome}"
    return nome or cidade or ""


def sincronizar_cnes_cidade(db, model, cidade_nome, forcar=False):
    """
    Baixa estabelecimentos da API CNES e grava no cache local.
    Retorna dict {ok, cidade, sincronizados, mensagem, fonte}.
    """
    info = cidade_cnes_por_nome(cidade_nome)
    if not info:
        return {"ok": False, "mensagem": f"Cidade não está na lista predefinida: {cidade_nome}"}

    agora = datetime.utcnow()
    q = model.query.filter_by(codigo_municipio=info["ibge6"])
    existentes = q.count()
    if existentes and not forcar:
        mais_recente = (
            q.order_by(model.atualizado_em.desc()).first()
        )
        if mais_recente and mais_recente.atualizado_em and (
            agora - mais_recente.atualizado_em
        ) < timedelta(days=CNES_CACHE_DIAS):
            return {
                "ok": True,
                "cidade": info["nome"],
                "sincronizados": existentes,
                "mensagem": f"Cache local válido ({existentes} estabelecimentos).",
                "fonte": "cache",
            }

    total = 0
    try:
        # remove cache antigo do município antes de regravar
        if existentes:
            q.delete(synchronize_session=False)
            db.session.commit()

        offset = 0
        for _ in range(CNES_MAX_PAGINAS):
            pagina = buscar_cnes_api_pagina(info["ibge6"], offset=offset, limit=CNES_PAGE_SIZE)
            if not pagina:
                break
            for item in pagina:
                norm = normalizar_estabelecimento_api(item, info["nome"], info["ibge6"])
                if not norm or not norm["nome_fantasia"]:
                    continue
                row = model(
                    codigo_cnes=norm["codigo_cnes"],
                    codigo_municipio=norm["codigo_municipio"],
                    municipio_nome=norm["municipio_nome"],
                    nome_fantasia=norm["nome_fantasia"][:200],
                    razao_social=(norm["razao_social"] or "")[:200] or None,
                    endereco=(norm["endereco"] or "")[:200] or None,
                    numero=(norm["numero"] or "")[:20] or None,
                    bairro=(norm["bairro"] or "")[:100] or None,
                    cep=(norm["cep"] or "")[:10] or None,
                    telefone=(norm["telefone"] or "")[:40] or None,
                    tipo_unidade=norm["tipo_unidade"],
                    esfera=(norm["esfera"] or "")[:60] or None,
                    atualizado_em=agora,
                )
                db.session.merge(row)
                total += 1
            db.session.commit()
            if len(pagina) < CNES_PAGE_SIZE:
                break
            offset += CNES_PAGE_SIZE
    except Exception as e:
        db.session.rollback()
        # se falhou mas já havia cache antigo útil, avisa
        if existentes and not forcar:
            return {
                "ok": True,
                "cidade": info["nome"],
                "sincronizados": existentes,
                "mensagem": f"API indisponível; usando cache anterior ({existentes}). Erro: {e}",
                "fonte": "cache_fallback",
            }
        return {"ok": False, "mensagem": f"Falha ao consultar CNES: {e}", "cidade": info["nome"]}

    return {
        "ok": True,
        "cidade": info["nome"],
        "sincronizados": total,
        "mensagem": f"Sincronizados {total} estabelecimentos do CNES.",
        "fonte": "api",
    }


def listar_estabelecimentos_cache(model, cidade_nome, q="", limit=80):
    """Busca no cache local (após sincronização)."""
    info = cidade_cnes_por_nome(cidade_nome)
    if not info:
        return []
    query = model.query.filter_by(codigo_municipio=info["ibge6"])
    termo = (q or "").strip()
    if termo:
        like = f"%{termo}%"
        query = query.filter(
            db_or_nome(model, like)
        )
    rows = query.order_by(model.nome_fantasia.asc()).limit(max(int(limit) * 3, int(limit))).all()

    def _score(nome):
        n = (nome or "").upper()
        if n.startswith("HOSPITAL"):
            return 0
        if "HOSPITAL" in n or n.startswith("AME ") or " AME" in n:
            return 1
        if "CLINICA" in n or "CLÍNICA" in n or "UBS" in n or "UPA" in n:
            return 2
        return 3

    rows = sorted(rows, key=lambda r: (_score(r.nome_fantasia), (r.nome_fantasia or "").upper()))
    rows = rows[: int(limit)]
    out = []
    for r in rows:
        d = {
            "codigo_cnes": r.codigo_cnes,
            "nome": r.nome_fantasia,
            "nome_fantasia": r.nome_fantasia,
            "razao_social": r.razao_social or "",
            "endereco": r.endereco or "",
            "numero": r.numero or "",
            "bairro": r.bairro or "",
            "cep": r.cep or "",
            "telefone": r.telefone or "",
            "municipio_nome": r.municipio_nome or info["nome"],
            "tipo_unidade": r.tipo_unidade,
        }
        d["destino_formatado"] = formatar_destino_cnes(d, info["nome"])
        d["label"] = d["destino_formatado"]
        out.append(d)
    return out


def db_or_nome(model, like):
    from sqlalchemy import or_

    return or_(
        model.nome_fantasia.ilike(like),
        model.razao_social.ilike(like),
        model.bairro.ilike(like),
        model.endereco.ilike(like),
    )


def obter_estabelecimento_cache(model, codigo_cnes):
    if not codigo_cnes:
        return None
    return model.query.filter_by(codigo_cnes=str(codigo_cnes)).first()

# -*- coding: utf-8 -*-
"""
Trilha de Auditoria (Audit Trail) do STP.

Serviço centralizado: registro de autenticação, navegação, CRUD (via SQLAlchemy)
e acessos negados. Não armazena senhas, tokens nem outros segredos.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, date, timedelta
from functools import wraps
from typing import Any, Dict, Iterable, List, Optional, Tuple

from flask import has_request_context, request, session as flask_session, g
from sqlalchemy import event, inspect as sa_inspect
from sqlalchemy.orm import Session as SASession

# Campos que nunca devem ir para o log em claro
CAMPOS_SENSIVEIS = {
    'password', 'password_hash', 'senha', 'senha_hash', 'token', 'api_key',
    'secret', 'secret_key', 'cookie', 'csrf_token', 'authorization',
}

# Tabelas monitoradas pelo listener ORM → módulo amigável
TABELAS_AUDITADAS = {
    'usuarios': 'Usuários',
    'pacientes': 'Pacientes',
    'acompanhantes': 'Acompanhantes',
    'veiculos': 'Veículos',
    'frotas': 'Frotas',
    'motoristas': 'Motoristas',
    'agendamentos': 'Agendamentos',
    'uso_veiculos': 'Frota',
    'abastecimentos': 'Combustível',
    'faturas_terceirizados': 'Faturamento',
}

# Prefixo de rota → módulo (navegação)
ROTA_MODULO = (
    ('/auditoria', 'Auditoria'),
    ('/usuarios', 'Usuários'),
    ('/agendamentos', 'Agendamentos'),
    ('/pacientes', 'Pacientes'),
    ('/acompanhantes', 'Acompanhantes'),
    ('/motoristas', 'Motoristas'),
    ('/veiculos', 'Veículos'),
    ('/uso-veiculos', 'Frota'),
    ('/uso_veiculos', 'Frota'),
    ('/combustivel', 'Combustível'),
    ('/faturamento', 'Faturamento'),
    ('/relatorios', 'Relatórios'),
    ('/backup', 'Backup'),
    ('/whatsapp', 'WhatsApp'),
    ('/dashboard', 'Dashboard'),
)

ACOES_LABEL = {
    'LOGIN': 'Login',
    'LOGIN_FALHA': 'Login malsucedido',
    'LOGOUT': 'Logout',
    'ACESSO_PAGINA': 'Acesso à página',
    'VISUALIZACAO': 'Visualização',
    'CONSULTA': 'Consulta',
    'CRIACAO': 'Criação',
    'EDICAO': 'Edição',
    'EXCLUSAO': 'Exclusão',
    'CANCELAMENTO': 'Cancelamento',
    'IMPRESSAO': 'Impressão',
    'EXPORTACAO': 'Exportação',
    'ACESSO_NEGADO': 'Acesso negado',
    'ALTERACAO_SENHA': 'Alteração de senha',
    'ATIVACAO': 'Ativação',
    'DESATIVACAO': 'Desativação',
    'ALTERACAO_PERFIL': 'Alteração de perfil',
    'STATUS': 'Alteração de status',
}

SKIP_PATH_PREFIXES = (
    '/static/', '/favicon', '/transporte/static/',
)


def _json_dump(data: Any) -> Optional[str]:
    if data is None:
        return None
    try:
        return json.dumps(data, ensure_ascii=False, default=str)
    except Exception:
        return json.dumps({'erro': 'nao_serializavel'}, ensure_ascii=False)


def serializar_valor(valor: Any) -> Any:
    if valor is None:
        return None
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, (int, float)):
        return valor
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, bytes):
        return '[binario]'
    texto = str(valor)
    if len(texto) > 400:
        return texto[:400] + '…'
    return texto


def redigir_campo(nome: str, valor: Any) -> Any:
    chave = (nome or '').lower()
    if chave in CAMPOS_SENSIVEIS or any(s in chave for s in ('password', 'senha', 'token', 'secret')):
        if valor in (None, '', False):
            return None
        return '[alterado]'
    return serializar_valor(valor)


def diff_valores(antes: Dict[str, Any], depois: Dict[str, Any]) -> List[Dict[str, Any]]:
    mudancas = []
    for chave in sorted(set(antes or {}) | set(depois or {})):
        a = redigir_campo(chave, (antes or {}).get(chave))
        d = redigir_campo(chave, (depois or {}).get(chave))
        if a != d:
            mudancas.append({'campo': chave, 'anterior': a, 'novo': d})
    return mudancas


def modulo_da_rota(path: str) -> str:
    path = path or '/'
    # remove prefixo de deploy se presente no path bruto
    for pref in ('/transporte',):
        if path.startswith(pref):
            path = path[len(pref):] or '/'
    for prefixo, modulo in ROTA_MODULO:
        if path == prefixo or path.startswith(prefixo + '/'):
            return modulo
    if path in ('/', ''):
        return 'Sistema'
    return 'Sistema'


def inferir_acao_navegacao(path: str, method: str = 'GET') -> str:
    p = (path or '').lower()
    if 'imprimir' in p or '/print' in p:
        return 'IMPRESSAO'
    if 'export' in p or p.endswith('.csv') or p.endswith('.xlsx'):
        return 'EXPORTACAO'
    if method.upper() == 'GET' and any(x in p for x in ('/visualizar', '/ver/', '/detalhe')):
        return 'VISUALIZACAO'
    return 'ACESSO_PAGINA'


def deve_registrar_navegacao(path: str, method: str, status_code: int) -> bool:
    if method.upper() != 'GET':
        return False
    if status_code not in (200, 304):
        return False
    path = path or '/'
    for pref in SKIP_PATH_PREFIXES:
        if pref in path:
            return False
    if path.endswith(('.js', '.css', '.map', '.png', '.jpg', '.jpeg', '.webp', '.ico', '.svg', '.woff', '.woff2')):
        return False
    # evita ruído de APIs JSON puras (exceto quando forem export)
    if '/api/' in path and 'export' not in path.lower():
        return False
    return True


class AuditService:
    """API única para gravar e consultar eventos de auditoria."""

    def __init__(self, db, model):
        self.db = db
        self.Model = model
        self._hooks_registered = False

    # ----- contexto HTTP -----
    def _ctx(self) -> Dict[str, Any]:
        ctx = {
            'ip': None,
            'user_agent': None,
            'sessao_id': None,
            'rota': None,
            'endpoint': None,
            'metodo_http': None,
            'modulo': None,
        }
        if not has_request_context():
            return ctx
        try:
            ctx['ip'] = (request.headers.get('X-Forwarded-For') or request.remote_addr or '')[:64]
            if ctx['ip'] and ',' in ctx['ip']:
                ctx['ip'] = ctx['ip'].split(',')[0].strip()
            ua = request.headers.get('User-Agent') or ''
            ctx['user_agent'] = ua[:400]
            ctx['sessao_id'] = (flask_session.get('_id') or flask_session.get('csrf_token') or '')[:64] or None
            # sid do cookie de sessão Flask
            try:
                sid = getattr(flask_session, 'sid', None)
                if sid:
                    ctx['sessao_id'] = str(sid)[:64]
            except Exception:
                pass
            ctx['rota'] = (request.path or '')[:255]
            ctx['endpoint'] = (request.endpoint or '')[:120]
            ctx['metodo_http'] = (request.method or '')[:10]
            ctx['modulo'] = modulo_da_rota(request.path)
        except Exception:
            pass
        return ctx

    def _usuario_atual(self) -> Dict[str, Any]:
        dados = {
            'usuario_id': None,
            'usuario_nome': None,
            'usuario_username': None,
            'usuario_perfil': None,
        }
        try:
            from flask_login import current_user
            if current_user and getattr(current_user, 'is_authenticated', False):
                dados['usuario_id'] = getattr(current_user, 'id', None)
                dados['usuario_nome'] = (getattr(current_user, 'nome_completo', None) or '')[:120] or None
                dados['usuario_username'] = (getattr(current_user, 'username', None) or '')[:80] or None
                dados['usuario_perfil'] = (getattr(current_user, 'tipo_usuario', None) or '')[:30] or None
        except Exception:
            pass
        return dados

    def registrar(
        self,
        acao: str,
        *,
        resultado: str = 'SUCESSO',
        modulo: Optional[str] = None,
        descricao: Optional[str] = None,
        entidade: Optional[str] = None,
        entidade_id: Optional[int] = None,
        alteracoes: Optional[Any] = None,
        detalhes: Optional[Any] = None,
        usuario_id: Optional[int] = None,
        usuario_nome: Optional[str] = None,
        usuario_username: Optional[str] = None,
        usuario_perfil: Optional[str] = None,
        rota: Optional[str] = None,
        endpoint: Optional[str] = None,
        commit: bool = True,
    ):
        """Grava um evento. Nunca propaga exceção para a operação de negócio.

        Com commit=True usa sessão própria (não mistura com a transação da tela).
        """
        try:
            if has_request_context() and getattr(g, '_audit_writing', False):
                return None
            ctx = self._ctx()
            user = self._usuario_atual()
            payload = dict(
                created_at=datetime.utcnow(),
                usuario_id=usuario_id if usuario_id is not None else user['usuario_id'],
                usuario_nome=(usuario_nome or user['usuario_nome']),
                usuario_username=(usuario_username or user['usuario_username']),
                usuario_perfil=(usuario_perfil or user['usuario_perfil']),
                acao=(acao or 'ACAO')[:40],
                modulo=(modulo or ctx['modulo'] or 'Sistema')[:60],
                rota=(rota or ctx['rota']),
                endpoint=(endpoint or ctx['endpoint']),
                metodo_http=ctx['metodo_http'],
                ip=ctx['ip'],
                user_agent=ctx['user_agent'],
                sessao_id=ctx['sessao_id'],
                entidade=(entidade or None) and str(entidade)[:60],
                entidade_id=entidade_id,
                resultado=(resultado or 'SUCESSO')[:20],
                descricao=(descricao or None) and str(descricao)[:500],
                alteracoes=_json_dump(alteracoes) if not isinstance(alteracoes, str) else alteracoes,
                detalhes=_json_dump(self._redigir_detalhes(detalhes)) if detalhes is not None else None,
            )
            if commit:
                if has_request_context():
                    g._audit_writing = True
                from sqlalchemy.orm import Session as SASessionLocal
                try:
                    with SASessionLocal(self.db.engine) as sess:
                        row = self.Model(**payload)
                        sess.add(row)
                        sess.commit()
                        return row
                finally:
                    if has_request_context():
                        g._audit_writing = False
            else:
                row = self.Model(**payload)
                self.db.session.add(row)
                return row
        except Exception as exc:
            try:
                print(f'⚠️ Auditoria: falha ao registrar ({acao}): {exc}')
            except Exception:
                pass
            return None
        finally:
            try:
                if has_request_context():
                    g._audit_writing = False
            except Exception:
                pass

    def _redigir_detalhes(self, detalhes: Any) -> Any:
        if isinstance(detalhes, dict):
            return {k: redigir_campo(k, v) for k, v in detalhes.items()}
        return detalhes

    def registrar_no_session(
        self,
        session,
        acao: str,
        **kwargs,
    ):
        """Adiciona AuditLog na mesma sessão ORM (usado pelo before_flush)."""
        try:
            ctx = self._ctx()
            user = self._usuario_atual()
            row = self.Model(
                created_at=datetime.utcnow(),
                usuario_id=kwargs.get('usuario_id', user['usuario_id']),
                usuario_nome=kwargs.get('usuario_nome', user['usuario_nome']),
                usuario_username=kwargs.get('usuario_username', user['usuario_username']),
                usuario_perfil=kwargs.get('usuario_perfil', user['usuario_perfil']),
                acao=(acao or 'ACAO')[:40],
                modulo=(kwargs.get('modulo') or ctx['modulo'] or 'Sistema')[:60],
                rota=kwargs.get('rota') or ctx['rota'],
                endpoint=kwargs.get('endpoint') or ctx['endpoint'],
                metodo_http=ctx['metodo_http'],
                ip=ctx['ip'],
                user_agent=ctx['user_agent'],
                sessao_id=ctx['sessao_id'],
                entidade=kwargs.get('entidade'),
                entidade_id=kwargs.get('entidade_id'),
                resultado=(kwargs.get('resultado') or 'SUCESSO')[:20],
                descricao=(kwargs.get('descricao') or None) and str(kwargs.get('descricao'))[:500],
                alteracoes=_json_dump(kwargs.get('alteracoes')),
                detalhes=_json_dump(self._redigir_detalhes(kwargs.get('detalhes'))) if kwargs.get('detalhes') is not None else None,
            )
            session.add(row)
        except Exception as exc:
            print(f'⚠️ Auditoria (session): {exc}')

    # ----- hooks ORM -----
    def registrar_hooks(self):
        if self._hooks_registered:
            return
        service = self

        @event.listens_for(SASession, 'before_flush')
        def _audit_before_flush(session, flush_context, instances):
            if session.info.get('skip_audit'):
                return

            for obj in list(session.dirty):
                table = getattr(obj, '__tablename__', None)
                if table == 'audit_logs' or table not in TABELAS_AUDITADAS:
                    continue
                if not session.is_modified(obj, include_collections=False):
                    continue
                mudancas = _mudancas_obj(obj)
                if not mudancas:
                    continue
                acao = 'EDICAO'
                campos = {m['campo'] for m in mudancas}
                if table == 'usuarios':
                    if any(c in campos for c in ('password_hash', 'senha')):
                        acao = 'ALTERACAO_SENHA'
                        mudancas = [m for m in mudancas if m['campo'] not in ('password_hash',)]
                        if not any(m['campo'] == 'senha' for m in mudancas):
                            mudancas.append({'campo': 'senha', 'anterior': '***', 'novo': '[alterado]'})
                    if 'tipo_usuario' in campos:
                        acao = 'ALTERACAO_PERFIL'
                    if 'ativo' in campos:
                        for m in mudancas:
                            if m['campo'] == 'ativo':
                                acao = 'ATIVACAO' if m['novo'] in (True, 'True', 1, '1') else 'DESATIVACAO'
                if 'status' in campos and table == 'agendamentos':
                    acao = 'STATUS'
                    for m in mudancas:
                        if m['campo'] == 'status' and str(m['novo']).lower() == 'cancelado':
                            acao = 'CANCELAMENTO'
                eid = getattr(obj, 'id', None)
                service.registrar_no_session(
                    session,
                    acao,
                    modulo=TABELAS_AUDITADAS[table],
                    entidade=_entidade_nome(table),
                    entidade_id=eid if isinstance(eid, int) else None,
                    descricao=f'Alterou {TABELAS_AUDITADAS[table]} #{eid}' if eid else f'Alterou {TABELAS_AUDITADAS[table]}',
                    alteracoes=mudancas,
                )

            for obj in list(session.deleted):
                table = getattr(obj, '__tablename__', None)
                if table == 'audit_logs' or table not in TABELAS_AUDITADAS:
                    continue
                eid = getattr(obj, 'id', None)
                snap = _snapshot_obj(obj)
                service.registrar_no_session(
                    session,
                    'EXCLUSAO',
                    modulo=TABELAS_AUDITADAS[table],
                    entidade=_entidade_nome(table),
                    entidade_id=eid if isinstance(eid, int) else None,
                    descricao=f'Excluiu {TABELAS_AUDITADAS[table]} #{eid}' if eid else f'Excluiu {TABELAS_AUDITADAS[table]}',
                    alteracoes=[{'campo': k, 'anterior': v, 'novo': None} for k, v in snap.items()],
                )

        @event.listens_for(SASession, 'after_flush')
        def _audit_after_flush(session, flush_context):
            if session.info.get('skip_audit'):
                return
            logged = session.info.setdefault('audit_new_logged', set())
            for obj in list(session.new):
                table = getattr(obj, '__tablename__', None)
                if table == 'audit_logs' or table not in TABELAS_AUDITADAS:
                    continue
                key = (table, id(obj))
                if key in logged:
                    continue
                logged.add(key)
                eid = getattr(obj, 'id', None)
                snap = _snapshot_obj(obj)
                service.registrar_no_session(
                    session,
                    'CRIACAO',
                    modulo=TABELAS_AUDITADAS[table],
                    entidade=_entidade_nome(table),
                    entidade_id=eid if isinstance(eid, int) else None,
                    descricao=f'Criou registro em {TABELAS_AUDITADAS[table]}'
                              + (f' #{eid}' if eid else ''),
                    alteracoes=[{'campo': k, 'anterior': None, 'novo': v} for k, v in snap.items()
                                if k not in ('id', 'data_cadastro')],
                    detalhes={'valores': snap},
                )

        @event.listens_for(SASession, 'after_commit')
        def _audit_after_commit(session):
            session.info.pop('audit_new_logged', None)

        @event.listens_for(SASession, 'after_rollback')
        def _audit_after_rollback(session):
            session.info.pop('audit_new_logged', None)

        self._hooks_registered = True
        print('✅ Auditoria: hooks SQLAlchemy registrados')


def _entidade_nome(table: str) -> str:
    mapa = {
        'usuarios': 'Usuario',
        'pacientes': 'Paciente',
        'acompanhantes': 'Acompanhante',
        'veiculos': 'Veiculo',
        'frotas': 'Frota',
        'motoristas': 'Motorista',
        'agendamentos': 'Agendamento',
        'uso_veiculos': 'UsoVeiculo',
        'abastecimentos': 'Abastecimento',
        'faturas_terceirizados': 'Fatura',
    }
    return mapa.get(table, table)


def _snapshot_obj(obj) -> Dict[str, Any]:
    out = {}
    try:
        insp = sa_inspect(obj)
        for attr in insp.mapper.column_attrs:
            nome = attr.key
            try:
                valor = getattr(obj, nome, None)
            except Exception:
                continue
            out[nome] = redigir_campo(nome, valor)
    except Exception:
        pass
    return out


def _mudancas_obj(obj) -> List[Dict[str, Any]]:
    mudancas = []
    try:
        insp = sa_inspect(obj)
        rel_keys = set(insp.mapper.relationships.keys())
        for attr in insp.attrs:
            if attr.key in rel_keys:
                continue
            hist = attr.history
            if not hist.has_changes():
                continue
            nome = attr.key
            anterior = hist.deleted[0] if hist.deleted else None
            novo = hist.added[0] if hist.added else None
            if nome.lower() in CAMPOS_SENSIVEIS or 'password' in nome.lower() or 'senha' in nome.lower():
                mudancas.append({
                    'campo': 'senha' if 'password' in nome.lower() or 'senha' in nome.lower() else nome,
                    'anterior': '***' if anterior not in (None, '') else None,
                    'novo': '[alterado]' if novo not in (None, '') else None,
                })
            else:
                a = serializar_valor(anterior)
                d = serializar_valor(novo)
                if a != d:
                    mudancas.append({'campo': nome, 'anterior': a, 'novo': d})
    except Exception:
        pass
    return mudancas


# ----- consultas / export -----
def aplicar_filtros_query(query, Model, filtros: Dict[str, str]):
    if filtros.get('usuario'):
        termo = f"%{filtros['usuario'].strip()}%"
        query = query.filter(
            (Model.usuario_nome.ilike(termo)) |
            (Model.usuario_username.ilike(termo))
        )
    if filtros.get('perfil'):
        query = query.filter(Model.usuario_perfil == filtros['perfil'])
    if filtros.get('modulo'):
        query = query.filter(Model.modulo == filtros['modulo'])
    if filtros.get('acao'):
        query = query.filter(Model.acao == filtros['acao'])
    if filtros.get('resultado'):
        query = query.filter(Model.resultado == filtros['resultado'])
    if filtros.get('ip'):
        query = query.filter(Model.ip.ilike(f"%{filtros['ip'].strip()}%"))
    if filtros.get('entidade'):
        query = query.filter(Model.entidade.ilike(f"%{filtros['entidade'].strip()}%"))
    if filtros.get('entidade_id'):
        try:
            query = query.filter(Model.entidade_id == int(filtros['entidade_id']))
        except (TypeError, ValueError):
            pass
    if filtros.get('data_inicio'):
        try:
            di = datetime.strptime(filtros['data_inicio'], '%Y-%m-%d')
            query = query.filter(Model.created_at >= di)
        except ValueError:
            pass
    if filtros.get('data_fim'):
        try:
            df = datetime.strptime(filtros['data_fim'], '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(Model.created_at < df)
        except ValueError:
            pass
    return query


def indicadores_auditoria(Model, db, dias: int = 7) -> Dict[str, Any]:
    from sqlalchemy import func
    desde = datetime.utcnow() - timedelta(days=dias)
    base = Model.query.filter(Model.created_at >= desde)
    total = base.count()
    logins = base.filter(Model.acao == 'LOGIN').count()
    criacoes = base.filter(Model.acao == 'CRIACAO').count()
    edicoes = base.filter(Model.acao.in_(('EDICAO', 'ALTERACAO_PERFIL', 'ALTERACAO_SENHA', 'STATUS'))).count()
    exclusoes = base.filter(Model.acao == 'EXCLUSAO').count()
    negados = base.filter(Model.acao == 'ACESSO_NEGADO').count()
    usuarios_ativos = db.session.query(Model.usuario_id).filter(
        Model.created_at >= desde,
        Model.usuario_id.isnot(None),
    ).distinct().count()
    top = (
        db.session.query(Model.usuario_nome, func.count(Model.id))
        .filter(Model.created_at >= desde, Model.usuario_nome.isnot(None))
        .group_by(Model.usuario_nome)
        .order_by(func.count(Model.id).desc())
        .limit(5)
        .all()
    )
    ultimos_logins = (
        Model.query.filter(Model.acao == 'LOGIN')
        .order_by(Model.created_at.desc())
        .limit(5)
        .all()
    )
    return {
        'dias': dias,
        'total': total,
        'logins': logins,
        'criacoes': criacoes,
        'edicoes': edicoes,
        'exclusoes': exclusoes,
        'negados': negados,
        'usuarios_ativos': usuarios_ativos,
        'top_usuarios': top,
        'ultimos_logins': ultimos_logins,
    }


def exportar_csv(rows: Iterable) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=';')
    writer.writerow([
        'ID', 'Data/Hora', 'Usuario', 'Username', 'Perfil', 'Acao', 'Modulo',
        'Entidade', 'EntidadeID', 'Resultado', 'IP', 'Rota', 'Descricao', 'Alteracoes',
    ])
    for r in rows:
        writer.writerow([
            r.id,
            r.created_at.strftime('%d/%m/%Y %H:%M:%S') if r.created_at else '',
            r.usuario_nome or '',
            r.usuario_username or '',
            r.usuario_perfil or '',
            r.acao or '',
            r.modulo or '',
            r.entidade or '',
            r.entidade_id or '',
            r.resultado or '',
            r.ip or '',
            r.rota or '',
            r.descricao or '',
            r.alteracoes or '',
        ])
    return buf.getvalue()


def formatar_alteracoes_html(alteracoes_json: Optional[str]) -> str:
    from html import escape
    if not alteracoes_json:
        return '<p style="color:var(--gray-color);">Sem alterações registradas.</p>'
    try:
        dados = json.loads(alteracoes_json)
    except Exception:
        return f'<pre>{escape(str(alteracoes_json))}</pre>'
    if not dados:
        return '<p style="color:var(--gray-color);">Sem alterações registradas.</p>'
    linhas = []
    if isinstance(dados, list):
        for item in dados:
            if not isinstance(item, dict):
                continue
            campo = escape(str(item.get('campo', '')))
            ant = item.get('anterior')
            novo = item.get('novo')
            ant_s = escape('—' if ant is None else str(ant))
            novo_s = escape('—' if novo is None else str(novo))
            linhas.append(
                f'<tr><td style="padding:0.45rem 0.6rem;border-bottom:1px solid #eee;"><strong>{campo}</strong></td>'
                f'<td style="padding:0.45rem 0.6rem;border-bottom:1px solid #eee;">{ant_s}</td>'
                f'<td style="padding:0.45rem 0.6rem;border-bottom:1px solid #eee;">→</td>'
                f'<td style="padding:0.45rem 0.6rem;border-bottom:1px solid #eee;">{novo_s}</td></tr>'
            )
    if not linhas:
        return f'<pre>{escape(json.dumps(dados, ensure_ascii=False, indent=2))}</pre>'
    return (
        '<table style="width:100%;border-collapse:collapse;font-size:0.92rem;">'
        '<thead><tr style="background:var(--color-95);">'
        '<th style="text-align:left;padding:0.45rem 0.6rem;">Campo</th>'
        '<th style="text-align:left;padding:0.45rem 0.6rem;">Anterior</th>'
        '<th></th>'
        '<th style="text-align:left;padding:0.45rem 0.6rem;">Novo</th>'
        '</tr></thead><tbody>'
        + ''.join(linhas) +
        '</tbody></table>'
    )


def label_acao(acao: str) -> str:
    return ACOES_LABEL.get(acao, acao or '—')

# -*- coding: utf-8 -*-
"""Rotas da interface administrativa de Auditoria (STP)."""
from __future__ import annotations

from flask import (
    flash,
    g,
    make_response,
    redirect,
    request,
    url_for,
)
from flask_login import login_required

from auditoria import (
    aplicar_filtros_query,
    exportar_csv,
    formatar_alteracoes_html,
    indicadores_auditoria,
    label_acao,
)


def register_auditoria_routes(
    app,
    *,
    db,
    AuditLog,
    audit_service_getter,
    permission_required,
    obter_paginacao_request,
    listar_paginado,
    gerar_paginacao,
    gerar_layout_base,
):
    """Registra /auditoria, detalhe e exportação CSV."""

    def _filtros_auditoria_request():
        return {
            'usuario': (request.args.get('usuario') or '').strip(),
            'perfil': (request.args.get('perfil') or '').strip(),
            'modulo': (request.args.get('modulo') or '').strip(),
            'acao': (request.args.get('acao') or '').strip(),
            'resultado': (request.args.get('resultado') or '').strip(),
            'ip': (request.args.get('ip') or '').strip(),
            'entidade': (request.args.get('entidade') or '').strip(),
            'entidade_id': (request.args.get('entidade_id') or '').strip(),
            'data_inicio': (request.args.get('data_inicio') or '').strip(),
            'data_fim': (request.args.get('data_fim') or '').strip(),
        }

    @app.route('/auditoria')
    @login_required
    @permission_required('auditoria.ver')
    def auditoria():
        from html import escape

        filtros = _filtros_auditoria_request()
        page, per_page = obter_paginacao_request()
        query = aplicar_filtros_query(AuditLog.query, AuditLog, filtros)
        eventos, total, page = listar_paginado(query, page, per_page, AuditLog.created_at.desc())
        filtros_url = {k: v for k, v in filtros.items() if v}
        paginacao_html = gerar_paginacao('auditoria', page, per_page, total, filtros_url)
        ind = indicadores_auditoria(AuditLog, db, dias=7)

        def opt(name, valor, rotulo=None):
            sel = ' selected' if filtros.get(name) == valor else ''
            return f'<option value="{escape(valor)}"{sel}>{escape(rotulo or valor)}</option>'

        perfis = ['', 'atendente', 'supervisor', 'contador', 'administrador']
        acoes = [''] + sorted({
            'LOGIN', 'LOGIN_FALHA', 'LOGOUT', 'ACESSO_PAGINA', 'VISUALIZACAO', 'CONSULTA',
            'CRIACAO', 'EDICAO', 'EXCLUSAO', 'CANCELAMENTO', 'IMPRESSAO', 'EXPORTACAO',
            'ACESSO_NEGADO', 'ALTERACAO_SENHA', 'ATIVACAO', 'DESATIVACAO', 'ALTERACAO_PERFIL', 'STATUS',
        })
        modulos = [''] + sorted({
            'Autenticação', 'Dashboard', 'Agendamentos', 'Pacientes', 'Acompanhantes',
            'Motoristas', 'Veículos', 'Frotas', 'Frota', 'Combustível', 'Relatórios',
            'Faturamento', 'Usuários', 'Backup', 'WhatsApp', 'Auditoria', 'Sistema',
        })
        resultados = ['', 'SUCESSO', 'FALHA', 'NEGADO']

        cards = f'''
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:0.75rem;margin-bottom:1.25rem;">
          <div class="card" style="padding:0.9rem;"><div style="font-size:0.75rem;color:var(--gray-color);">Eventos (7d)</div><strong style="font-size:1.35rem;">{ind['total']}</strong></div>
          <div class="card" style="padding:0.9rem;"><div style="font-size:0.75rem;color:var(--gray-color);">Logins</div><strong style="font-size:1.35rem;">{ind['logins']}</strong></div>
          <div class="card" style="padding:0.9rem;"><div style="font-size:0.75rem;color:var(--gray-color);">Criações</div><strong style="font-size:1.35rem;">{ind['criacoes']}</strong></div>
          <div class="card" style="padding:0.9rem;"><div style="font-size:0.75rem;color:var(--gray-color);">Edições</div><strong style="font-size:1.35rem;">{ind['edicoes']}</strong></div>
          <div class="card" style="padding:0.9rem;"><div style="font-size:0.75rem;color:var(--gray-color);">Exclusões</div><strong style="font-size:1.35rem;">{ind['exclusoes']}</strong></div>
          <div class="card" style="padding:0.9rem;"><div style="font-size:0.75rem;color:var(--gray-color);">Acessos negados</div><strong style="font-size:1.35rem;color:var(--danger-color);">{ind['negados']}</strong></div>
          <div class="card" style="padding:0.9rem;"><div style="font-size:0.75rem;color:var(--gray-color);">Usuários ativos</div><strong style="font-size:1.35rem;">{ind['usuarios_ativos']}</strong></div>
        </div>
        '''

        top_html = ''.join(
            f'<li>{escape(n or "—")}: <strong>{c}</strong></li>' for n, c in ind['top_usuarios']
        ) or '<li>Sem dados no período</li>'
        ult_html = ''.join(
            f'<li>{escape((u.usuario_nome or u.usuario_username or "—"))} — '
            f'{(u.created_at.strftime("%d/%m %H:%M") if u.created_at else "")} '
            f'({escape(u.ip or "")})</li>'
            for u in ind['ultimos_logins']
        ) or '<li>Sem logins recentes</li>'

        filtros_html = f'''
        <div class="card" style="margin-bottom:1rem;">
          <form method="get" action="{url_for('auditoria')}" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:0.65rem;align-items:end;">
            <div><label>Usuário</label><input type="text" name="usuario" value="{escape(filtros['usuario'])}" placeholder="Nome ou login"></div>
            <div><label>Perfil</label><select name="perfil">{''.join(opt('perfil', p, p.title() if p else 'Todos') for p in perfis)}</select></div>
            <div><label>Módulo</label><select name="modulo">{''.join(opt('modulo', m, m or 'Todos') for m in modulos)}</select></div>
            <div><label>Ação</label><select name="acao">{''.join(opt('acao', a, label_acao(a) if a else 'Todas') for a in acoes)}</select></div>
            <div><label>Resultado</label><select name="resultado">{''.join(opt('resultado', r, r or 'Todos') for r in resultados)}</select></div>
            <div><label>IP</label><input type="text" name="ip" value="{escape(filtros['ip'])}"></div>
            <div><label>Registro</label><input type="text" name="entidade" value="{escape(filtros['entidade'])}" placeholder="Ex: Agendamento"></div>
            <div><label>ID registro</label><input type="text" name="entidade_id" value="{escape(filtros['entidade_id'])}"></div>
            <div><label>De</label><input type="date" name="data_inicio" value="{escape(filtros['data_inicio'])}"></div>
            <div><label>Até</label><input type="date" name="data_fim" value="{escape(filtros['data_fim'])}"></div>
            <div style="display:flex;gap:0.5rem;flex-wrap:wrap;">
              <button type="submit" class="btn">Filtrar</button>
              <a class="btn btn-secondary" href="{url_for('auditoria')}">Limpar</a>
              <a class="btn btn-secondary" href="{url_for('auditoria_exportar', **filtros_url)}">Exportar CSV</a>
            </div>
          </form>
        </div>
        '''

        rows = ''
        for ev in eventos:
            dt = ev.created_at.strftime('%d/%m/%Y %H:%M:%S') if ev.created_at else '—'
            res_color = {
                'SUCESSO': 'var(--success-color)',
                'FALHA': 'var(--warning-color)',
                'NEGADO': 'var(--danger-color)',
            }.get(ev.resultado, 'inherit')
            rows += f'''
            <tr>
              <td style="padding:0.55rem;border-bottom:1px solid #eee;white-space:nowrap;">{dt}</td>
              <td style="padding:0.55rem;border-bottom:1px solid #eee;">{escape(ev.usuario_nome or ev.usuario_username or '—')}<div style="font-size:0.75rem;color:var(--gray-color);">{escape((ev.usuario_perfil or '').title())}</div></td>
              <td style="padding:0.55rem;border-bottom:1px solid #eee;">{escape(label_acao(ev.acao))}</td>
              <td style="padding:0.55rem;border-bottom:1px solid #eee;">{escape(ev.modulo or '—')}</td>
              <td style="padding:0.55rem;border-bottom:1px solid #eee;max-width:280px;">{escape((ev.descricao or '')[:120])}</td>
              <td style="padding:0.55rem;border-bottom:1px solid #eee;">{escape(ev.ip or '—')}</td>
              <td style="padding:0.55rem;border-bottom:1px solid #eee;color:{res_color};font-weight:600;">{escape(ev.resultado or '')}</td>
              <td style="padding:0.55rem;border-bottom:1px solid #eee;text-align:center;">
                <a class="btn btn-small" href="{url_for('auditoria_detalhe', evento_id=ev.id)}">Detalhe</a>
              </td>
            </tr>'''

        if not rows:
            rows = '<tr><td colspan="8" style="padding:1.2rem;text-align:center;color:var(--gray-color);">Nenhum evento encontrado para os filtros.</td></tr>'

        conteudo = f'''
        <div class="page-header" style="margin-bottom:1rem;">
          <h1 style="margin:0;color:var(--primary-dark);">🧾 Auditoria</h1>
          <p style="margin:0.35rem 0 0;color:var(--gray-color);">Trilha de atividades dos usuários (somente leitura). Total filtrado: <strong>{total}</strong></p>
        </div>
        {cards}
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.75rem;margin-bottom:1rem;">
          <div class="card" style="padding:0.9rem;"><strong>Mais ativos (7d)</strong><ul style="margin:0.5rem 0 0;padding-left:1.1rem;">{top_html}</ul></div>
          <div class="card" style="padding:0.9rem;"><strong>Últimos logins</strong><ul style="margin:0.5rem 0 0;padding-left:1.1rem;">{ult_html}</ul></div>
        </div>
        {filtros_html}
        <div class="card">
          <div class="table-container stp-list-desktop">
            <table style="width:100%;border-collapse:collapse;font-size:0.9rem;">
              <thead>
                <tr style="background:var(--color-95);">
                  <th style="padding:0.6rem;text-align:left;">Data/Hora</th>
                  <th style="padding:0.6rem;text-align:left;">Usuário</th>
                  <th style="padding:0.6rem;text-align:left;">Ação</th>
                  <th style="padding:0.6rem;text-align:left;">Módulo</th>
                  <th style="padding:0.6rem;text-align:left;">Descrição</th>
                  <th style="padding:0.6rem;text-align:left;">IP</th>
                  <th style="padding:0.6rem;text-align:left;">Resultado</th>
                  <th style="padding:0.6rem;text-align:center;"> </th>
                </tr>
              </thead>
              <tbody>{rows}</tbody>
            </table>
          </div>
          {paginacao_html}
          <p style="margin-top:0.75rem;font-size:0.8rem;color:var(--gray-color);">Os registros de auditoria não podem ser editados nem excluídos pela interface.</p>
        </div>
        <style>@media(max-width:900px){{ .page-header + div + div {{ grid-template-columns:1fr !important; }} }}</style>
        '''
        return gerar_layout_base('Auditoria', conteudo, 'auditoria')

    @app.route('/auditoria/exportar.csv')
    @login_required
    @permission_required('auditoria.ver')
    def auditoria_exportar():
        filtros = _filtros_auditoria_request()
        query = aplicar_filtros_query(AuditLog.query, AuditLog, filtros)
        rows = query.order_by(AuditLog.created_at.desc()).limit(10000).all()
        svc = audit_service_getter()
        if svc is not None:
            svc.registrar(
                'EXPORTACAO',
                resultado='SUCESSO',
                modulo='Auditoria',
                descricao=f'Exportou CSV da auditoria ({len(rows)} eventos)',
                detalhes={'filtros': {k: v for k, v in filtros.items() if v}, 'qtd': len(rows)},
            )
        g._audit_skip_nav = True
        csv_data = exportar_csv(rows)
        resp = make_response('\ufeff' + csv_data)
        resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
        resp.headers['Content-Disposition'] = 'attachment; filename=auditoria_stp.csv'
        return resp

    @app.route('/auditoria/<int:evento_id>')
    @login_required
    @permission_required('auditoria.ver')
    def auditoria_detalhe(evento_id):
        from html import escape

        ev = db.session.get(AuditLog, evento_id)
        if not ev:
            flash('Evento de auditoria não encontrado.', 'error')
            return redirect(url_for('auditoria'))
        dt = ev.created_at.strftime('%d/%m/%Y') if ev.created_at else '—'
        hr = ev.created_at.strftime('%H:%M:%S') if ev.created_at else '—'
        reg = '—'
        if ev.entidade:
            reg = escape(ev.entidade) + (f' nº {ev.entidade_id}' if ev.entidade_id else '')
        alt_html = formatar_alteracoes_html(ev.alteracoes)
        conteudo = f'''
        <div class="page-header" style="margin-bottom:1rem;display:flex;justify-content:space-between;gap:1rem;flex-wrap:wrap;align-items:center;">
          <div>
            <h1 style="margin:0;color:var(--primary-dark);">🧾 Detalhe da Auditoria #{ev.id}</h1>
            <p style="margin:0.35rem 0 0;color:var(--gray-color);">Somente leitura</p>
          </div>
          <a class="btn btn-secondary" href="{url_for('auditoria')}">← Voltar</a>
        </div>
        <div class="card" style="margin-bottom:1rem;">
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:0.85rem;">
            <div><div style="font-size:0.75rem;color:var(--gray-color);">Usuário</div><strong>{escape(ev.usuario_nome or '—')}</strong><div style="font-size:0.85rem;">{escape(ev.usuario_username or '')}</div></div>
            <div><div style="font-size:0.75rem;color:var(--gray-color);">Perfil</div><strong>{escape((ev.usuario_perfil or '—').title())}</strong></div>
            <div><div style="font-size:0.75rem;color:var(--gray-color);">Data</div><strong>{dt}</strong></div>
            <div><div style="font-size:0.75rem;color:var(--gray-color);">Horário</div><strong>{hr}</strong></div>
            <div><div style="font-size:0.75rem;color:var(--gray-color);">Ação</div><strong>{escape(label_acao(ev.acao))}</strong></div>
            <div><div style="font-size:0.75rem;color:var(--gray-color);">Módulo</div><strong>{escape(ev.modulo or '—')}</strong></div>
            <div><div style="font-size:0.75rem;color:var(--gray-color);">Registro</div><strong>{reg}</strong></div>
            <div><div style="font-size:0.75rem;color:var(--gray-color);">Resultado</div><strong>{escape(ev.resultado or '—')}</strong></div>
            <div><div style="font-size:0.75rem;color:var(--gray-color);">IP</div><strong>{escape(ev.ip or '—')}</strong></div>
            <div><div style="font-size:0.75rem;color:var(--gray-color);">Rota</div><strong>{escape(ev.rota or '—')}</strong></div>
            <div><div style="font-size:0.75rem;color:var(--gray-color);">Endpoint</div><strong>{escape(ev.endpoint or '—')}</strong></div>
            <div><div style="font-size:0.75rem;color:var(--gray-color);">Sessão</div><strong>{escape(ev.sessao_id or '—')}</strong></div>
          </div>
          <div style="margin-top:1rem;"><div style="font-size:0.75rem;color:var(--gray-color);">Descrição</div><p style="margin:0.25rem 0 0;">{escape(ev.descricao or '—')}</p></div>
          <div style="margin-top:0.75rem;"><div style="font-size:0.75rem;color:var(--gray-color);">User-Agent</div><p style="margin:0.25rem 0 0;font-size:0.85rem;word-break:break-all;">{escape(ev.user_agent or '—')}</p></div>
        </div>
        <div class="card">
          <h3 style="margin-top:0;color:var(--primary-color);">Alterações</h3>
          {alt_html}
        </div>
        '''
        return gerar_layout_base(f'Auditoria #{ev.id}', conteudo, 'auditoria')

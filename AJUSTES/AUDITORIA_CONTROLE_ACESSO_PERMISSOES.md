# Relatório de auditoria — Controle de acesso STP

**Sistema ativo:** monólito `app.py` (não o pacote legado `sistema/`).  
**Data do relatório (chat):** 11/08/2026  
**Status:** ✅ **IMPLEMENTADO** em `app.py` (matriz `ROLE_PERMISSIONS`, `@permission_required`, menu filtrado, 403, whitelist de perfis, bloqueio de usuário inativo).  
As seções A–C abaixo descrevem o estado **antes** da mudança; a seção D é a matriz que entrou em produção no código.

---

## A. Situação atual

| Aspecto | Como está |
|--------|-----------|
| Perfis | `atendente`, `supervisor`, `contador`, `administrador` (string em `usuarios.tipo_usuario`) |
| Auth | Flask-Login + senha Werkzeug |
| Autorização real | Quase só `@login_required`. Role só em: Usuários, WhatsApp, Faturamento e config de Backup |
| Menu | Filtra Faturamento / Usuários / WhatsApp; **Backup e todo o operacional ficam para qualquer logado** |
| CRUD granular | **Não existe** no app ativo (existe só no legado `sistema/`, fora de produção) |

Em resumo: **estar autenticado ≈ acesso quase total** no operacional.

---

## B. Problemas encontrados

1. Atendente ≈ Supervisor no backend (label “editar” não é enforced).
2. Backup (dashboard, download do `.db`, limpeza, backup manual) aberto a qualquer login.
3. Exclusões e alterações destrutivas só com login (pacientes, motoristas, veículos, massa em agendamentos).
4. CSRF desligado; várias exclusões via **GET**.
5. Login não trata bem usuário `ativo=False`.
6. `SECRET_KEY` fixa no código; admin padrão `admin/admin123`.
7. Dois modelos ACL (`app.py` vs `sistema/`) — falsa sensação de segurança.
8. Menu oculto ≠ proteção: URL/API direta contorna o filtro.

---

## C. Matriz atual (código)

| Módulo | Atendente | Supervisor | Contador | Admin |
|--------|-----------|------------|----------|-------|
| Dashboard / Cadastros / Agendamentos / Frota / Relatórios | tudo\* | tudo\* | tudo\* | tudo\* |
| Backup usar/download | sim\* | sim\* | sim\* | sim\* |
| Backup configurar | — | — | — | sim |
| Faturamento ver | — | sim | sim | sim |
| Faturamento gerar/pagar | — | — | sim | sim |
| Usuários / WhatsApp | — | — | — | sim |

\* = qualquer usuário autenticado (só `@login_required`).

---

## D. Matriz recomendada

Princípio: **menor privilégio**, preservando os 4 perfis existentes.

| Módulo / ação | Atendente | Supervisor | Contador | Admin |
|---------------|-----------|------------|----------|-------|
| Dashboard | V | V | V | V |
| Agendamentos V/C/E | ✓ | ✓ | V (consulta) | ✓ |
| Agendamentos excluir / massa | ✗ | ✓ | ✗ | ✓ |
| Pacientes / Acompanhantes V/C/E | ✓ | ✓ | V | ✓ |
| Pacientes excluir | ✗ | ✓ | ✗ | ✓ |
| Motoristas / Veículos | V | V/C/E | V | ✓ |
| Frota (uso / combustível) | V (+registrar uso se operacional) | ✓ | V | ✓ |
| Relatórios operacionais | V (limitado) | V | V | V |
| Relatórios com dados de usuários | ✗ | ✗ | ✗ | ✓ |
| Faturamento | ✗ | V | V/C/E | ✓ |
| Backup | ✗ | ✗ | ✗ | ✓ |
| Usuários / WhatsApp / Sistema | ✗ | ✗ | ✗ | ✓ |

**V** = visualizar · **C** = criar · **E** = editar

---

## E–G. Arquitetura recomendada (antes de implementar)

Não criar tabela nova de ACL se não for necessário. Proposta enxuta no `app.py`:

1. **Catálogo central** `PERMISSOES` / helpers no `Usuario`:
   - `pode('modulo.acao')` — ex.: `agendamentos.excluir`, `backup.acessar`, `motoristas.editar`
2. **Decorator** `@permission_required('...')` além de `@login_required`
3. **Aplicar nas rotas** (HTML + POST/GET destrutivos) — 403 / página “Acesso não autorizado”
4. **Menu** `gerar_sidebar_nav()` só com itens cujo `pode(...)` for true
5. **Whitelist** de `tipo_usuario` no CRUD de usuários
6. **Backup** restrito a `administrador` (menu + todas as rotas)
7. Página amigável de acesso negado (sem vazar detalhes internos)

Arquivos previstos: principalmente `app.py` (decorators, `Usuario`, sidebar, rotas). Opcional depois: endurecer CSRF / exclusões GET→POST.

---

## H. Testes (após implementação)

Para cada perfil: menus visíveis, URL direta em módulos negados, POST/DELETE sensíveis, faturamento e backup.

---

### Próximo passo

A matriz e a arquitetura acima estão corretas para o STP de Cosmópolis?

Se **sim**, implemento na ordem: helpers + decorator → backend nas rotas críticas → menu → página 403 → testes por perfil.

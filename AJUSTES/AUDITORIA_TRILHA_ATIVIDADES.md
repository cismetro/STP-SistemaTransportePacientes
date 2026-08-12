# Trilha de Auditoria — Implementação STP

**Data:** 11/08/2026  
**Status:** implementado e validado (smoke)

---

## Arquivos

| Arquivo | Papel |
|---------|--------|
| `auditoria.py` | `AuditService`, redacao, diffs, hooks SQLAlchemy, filtros, indicadores, CSV |
| `auditoria_rotas.py` | UI admin: lista, detalhe, exportação |
| `app.py` | Modelo `AuditLog`, permissão, login/logout, `after_request`, menu, init |

## Banco

Tabela `audit_logs` (criada automaticamente via `garantir_tabela_auditoria()` / `db.create_all()`).

Índices: `created_at`, `usuario_id`, `usuario_username`, `usuario_perfil`, `acao`, `modulo`, `ip`, `sessao_id`, `entidade`+`entidade_id`, `resultado`, compostos `usuario_id+created_at`, `modulo+acao`.

## Permissão

- Código: `auditoria.ver`
- Concedida ao **administrador** via `ROLE_PERMISSIONS['administrador'] = {'*'}`
- Demais perfis: **sem acesso** (menu oculto + `@permission_required` no backend)

## Rotas

- `GET /auditoria` — painel + filtros + indicadores (7 dias)
- `GET /auditoria/<id>` — detalhe (alterações anterior → novo)
- `GET /auditoria/exportar.csv` — exportação (também auditada)

Sem rotas de edição/exclusão de logs.

## Eventos cobertos

| Origem | Eventos |
|--------|---------|
| Login/logout | `LOGIN`, `LOGIN_FALHA`, `LOGOUT` |
| `@permission_required` | `ACESSO_NEGADO` |
| `after_request` (GET relevante) | `ACESSO_PAGINA`, `VISUALIZACAO`, `IMPRESSAO`, `EXPORTACAO`, `CONSULTA` |
| Hooks ORM | `CRIACAO`, `EDICAO`, `EXCLUSAO`, `ALTERACAO_SENHA`, `ATIVACAO`/`DESATIVACAO`, `ALTERACAO_PERFIL`, `STATUS`/`CANCELAMENTO` |

Tabelas ORM monitoradas: usuários, pacientes, acompanhantes, veículos, frotas, motoristas, agendamentos, uso de veículos, abastecimentos, faturas.

**Não grava:** senhas, hashes, tokens, secrets (redigidos para `[alterado]` / `***`).

## Proteção dos logs

- Somente admin (`auditoria.ver`)
- UI somente leitura
- Gravação em sessão isolada para eventos explícitos (não mistura commit de negócio)
- Falhas de auditoria não derrubam a operação de negócio

## Pontos de atenção

1. Volume de `ACESSO_PAGINA` cresce com o uso — revisar retenção/expurgo administrativo no futuro.
2. Sessão expirada do Flask-Login não gera evento dedicado (apenas novo login).
3. Recuperação de senha / bloqueio automático ainda não existem no app ativo.
4. Exportação limitada a 10.000 linhas por arquivo.
5. PDF/Excel de auditoria não foram adicionados (CSV disponível).

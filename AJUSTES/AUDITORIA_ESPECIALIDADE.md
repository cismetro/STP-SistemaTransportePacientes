# Refatoração Tipo de Transporte → Especialidade Médica (2026-07-24)

## Estratégia
- Coluna `agendamentos.tipo_transporte` **reutilizada** (sem breaking change de schema).
- Modelo ampliado para `String(120)`.
- Listas em `static/data/especialidades.json`:
  - `modo_padrao`: `simples` | `completa`
  - override: env `ESPECIALIDADES_MODO=simples|completa`
- UI: Tom Select + opção **Outro** com campo livre (`tipo_transporte_outro`).
- Legados (consulta, exame…) mapeados em `formatar_especialidade_exibir`.

## Alternar lista
1. Editar `static/data/especialidades.json` → `"modo_padrao": "completa"`
2. Ou definir `ESPECIALIDADES_MODO=completa` e reiniciar o app.

## Impacto verificado
- Novo agendamento: campo Especialidade *
- Lista / filtros (texto ilike)
- Cartão motorista / WhatsApp / relatórios (via formatar_especialidade_exibir)

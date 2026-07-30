# Auditoria e implementação — Campo PARENTESCO (STP)
# Data: 2026-07-23

## Decisão de banco: Opção 1 — Tabela de domínio `parentescos`

Justificativa (saúde pública / prefeitura):
- Inclusão/alteração sem deploy de código (só seed/admin).
- Alinha com padrões SUS / e-SUS / CadÚnico (vocabulários evoluem).
- Reutilizável: Acompanhante, Responsável, Contato de emergência, etc.
- Facilita integração futura (código + descrição).
- Enum fixo (Opção 2) exige alteração de código a cada novo vínculo.

Schema:
  id INTEGER PK
  descricao VARCHAR(80) UNIQUE NOT NULL
  grupo VARCHAR(60) NOT NULL
  ativo BOOLEAN NOT NULL
  ordem INTEGER NOT NULL

Acompanhante.parentesco permanece VARCHAR com a descrição (snapshot legível);
validação no save contra o domínio ativo.

## UI: Tom Select (searchable combobox)

- Pesquisa por digitação, teclado, placeholder, limpar (X), optgroups
- Classe `.stp-parentesco-select` + CDN Tom Select 2.3.1

## Lista final (após auditoria)

Removidos (redundância):
- Marido, Mulher (≈ Esposo / Esposa)
- Parceiro, Parceira (≈ Companheiro / Companheira)
- Pessoa da Família (≈ Familiar)
- Contato genérico (mantido Contato de Emergência)
- Grupos-título soltos (Pais, Filhos…) como opções — viraram apenas optgroups

Renomeados / padronizados:
- Meio-irmão / Meio-irmã (hífen)
- Grupos: "Cônjuges / União", "Tutela / Representação", "Outros vínculos"

Mantidos (relevantes saúde/jurídico):
- Tutor(a), Curador(a), Responsável Legal, Representante Legal, Procurador
- Cuidador(a), Enfermagem, Assistente Social
- Contato de Emergência, Pessoa de Confiança

Total seed: ver PARENTESCOS_SEED em app.py (~69 itens ativos + Outro)

## Acessibilidade (WCAG)
- aria-label no select
- Navegação teclado via Tom Select
- Contraste no item ativo/selecionado
- Placeholder claro

## Performance / manutenção
- Domínio pequeno (~70): carregar completo no select (sem AJAX)
- Seed idempotente em migrar_parentescos()
- Futuro: tela admin CRUD em parentescos; FK parentesco_id opcional

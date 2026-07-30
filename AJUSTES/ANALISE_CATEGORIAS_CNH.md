# Análise Técnica — Ampliação das Categorias da CNH

**Sistema:** STP (Sistema de Transporte de Pacientes) — Prefeitura Municipal de Cosmópolis  
**Módulo:** Transporte / Motoristas  
**Versão da análise:** 1.0  
**Data:** Julho/2026  
**Tipo:** Análise apenas — sem implementação

---

## 1. Diagnóstico da Estrutura Atual

### 1.1 O problema reportado

> *"Está faltando algumas categorias de habilitação, tem motorista com 'AD' e atualmente só existem B, C, D e E."*

O sistema permite armazenar `AD` no banco (modelo Blueprint aceita), mas o formulário de **edição** no monólito (`app.py`) só exibe B, C, D, E como opções, impedindo a seleção ou alteração para `AD` e demais combinações.

### 1.2 Dual codebase — impacto crítico

O sistema possui **duas implementações paralelas** com comportamentos diferentes para CNH:

| Aspecto | `app.py` (monolítico — em produção) | `sistema/` (Blueprints — não registrado) |
|---------|--------------------------------------|------------------------------------------|
| **Modelo** | `categoria_cnh = db.String(2)` ❌ | `categoria_cnh = Column(String(5))` ✅ |
| **Validação** | Nenhuma validação de valores | `@validates` com lista de 9 categorias |
| **Formulário criar** | Oferece 10 opções (inclui `ACC`) | Usa Enum `CategoriaCNH.get_choices()` |
| **Formulário editar** | Apenas B, C, D, E ❌ | Usa Enum |
| **Em uso** | **Sim** (é o que roda) | **Não** (blueprints não registrados) |

**Conclusão:** O código "teoricamente mais moderno" (Blueprints) já suporta categorias combinadas, mas **não está em produção**. O código que realmente roda (`app.py`) tem limitações severas.

---

## 2. Arquivos Envolvidos

### 2.1 Frontend

| Arquivo | Linhas | O que faz | Status |
|---------|--------|-----------|--------|
| `app.py:5344-5362` | Formulário **criar** motorista | `<select>` com 10 opções (A, B, C, D, E, ACC, AB, AC, AD, AE) | ⚠️ Oferece `ACC` que não é válido no modelo |
| `app.py:5640-5646` | Formulário **editar** motorista | `<select>` com apenas B, C, D, E | ❌ Faltam A, AB, AC, AD, AE |
| `sistema/routes/motoristas.py:130,266` | Coleta `categoria_cnh` do form | Limpa e passa para o modelo | ✅ Adequado |
| `sistema/templates/motoristas.html:644,753` | Exibição em cards e tabela | Mostra badge com `motorista.categoria_cnh` | ✅ Já exibe qualquer valor |
| `sistema/status/status_enum.py:332-391` | Enum `CategoriaCNH` | 9 categorias + rótulos descritivos | ✅ Mas `ACC` não está aqui |
| `static/js/` | Nenhum | Sem JS específico para categoria | ✅ Sem impacto |

### 2.2 Backend — Modelos

| Arquivo | Linha | Definição | Tamanho |
|---------|-------|-----------|---------|
| `app.py:234` (Motorista legado) | `categoria_cnh = db.Column(db.String(2))` | ❌ **String(2)** — não suporta `AB`, `AC`, `AD`, `AE` |
| `sistema/models/motorista.py:41` | `categoria_cnh = Column(String(5))` | ✅ **String(5)** — suporta todas as combinações |

**⚠️ Inconsistência crítica:** O modelo em produção (`app.py`) usa `String(2)`. Se o banco de dados foi criado por este modelo, a coluna pode ter tamanho 2, o que IMPEDE fisicamente o armazenamento de `AB`, `AC`, `AD`, `AE`.

### 2.3 Backend — Validações

| Arquivo | Linhas | Valida |
|---------|--------|--------|
| `sistema/models/motorista.py:255-267` | `@validates('categoria_cnh')` | Lista fixa: `['A', 'B', 'C', 'D', 'E', 'AB', 'AC', 'AD', 'AE']` |
| `app.py` | **Nenhuma** | Sem validação no modelo legado |

### 2.4 Backend — Regras de negócio dependentes

| Arquivo | Linhas | Regra |
|---------|--------|-------|
| `sistema/models/motorista.py:139` | `habilitado_para_transporte_pacientes` | Exige `D`, `E`, `AD` ou `AE` OU curso específico |
| `sistema/models/motorista.py:372-385` | `pode_dirigir_veiculo` | Mapeia categoria → tipos de veículo permitidos |
| `sistema/status/status_enum.py:363-386` | `CategoriaCNH.can_drive_vehicle()` | Mesma lógica, implementada via Enum |
| `sistema/routes/motoristas.py:468-489` | Busca AJAX com `categoria_minima` | Filtra motoristas por categoria mínima exigida |

### 2.5 Banco de Dados

| Característica | Valor atual |
|---------------|-------------|
| **Tabela** | `motoristas` |
| **Coluna** | `categoria_cnh` |
| **Tipo** | `VARCHAR(2)` se criado pelo modelo legado; `VARCHAR(5)` se criado pelo Blueprint |
| **Nullable** | `NOT NULL` |
| **Unique** | Não |
| **Index** | Pode ter (modelo Blueprint define `index=True` para `placa`, mas categoria não) |
| **Default** | Nenhum |
| **Valores armazenados** | Possivelmente apenas B, C, D, E (dado que o formulário de edição atual só permite esses) |

### 2.6 APIs e Integrações

Nenhuma API externa (DETRAN, SENATRAN, SERPRO) está integrada atualmente. O campo `categoria_cnh` é apenas informativo e preenchido manualmente.

### 2.7 Relatórios

| Arquivo | Linhas | Uso de categoria |
|---------|--------|-----------------|
| `app.py:5160` | Listagem de motoristas | Exibe coluna `categoria_cnh` |
| `app.py:2378` | Impressão | `escape(m.categoria_cnh)` |
| `app.py:6432,6638` | Relatório de motoristas | Inclui no dicionário e na tabela |
| `sistema/routes/motoristas.py:629,644-645,685,710` | Relatório Blueprint | Filtra por `categoria_cnh`, exporta CSV |
| `sistema/services/relatorios_service.py:694-791` | Controle vencimentos | Não usa categoria, apenas datas |

### 2.8 Pesquisas e Filtros

| Arquivo | Linhas | Filtro |
|---------|--------|--------|
| `sistema/routes/motoristas.py:35,64-65` | Listagem | Filtro por `categoria_cnh` (select) |
| `sistema/templates/motoristas.html:556-561` | Template | Dropdown de filtro por situação CNH |
| `sistema/routes/motoristas.py:468-489` | Busca AJAX | Filtro por `categoria_minima` para agendamentos |

---

## 3. Componentes Impactados pela Ampliação

### 3.1 Frontend — O que precisa mudar

| Componente | Impacto | Prioridade |
|------------|---------|------------|
| `app.py:5344-5362` — Select de criar motorista | Incluir `ACC`? Remover? Sincronizar com Enum | Alta |
| `app.py:5640-5646` — Select de editar motorista | **Crítico:** só tem B, C, D, E. Precisa de todas | **Crítica** |
| `sistema/templates/motoristas.html` select filter (se existir) | Atualizar opções do filtro | Média |
| `sistema/status/status_enum.py:332-391` | Ampliar Enum com `ACC` e outras se necessário | Média |
| `sistema/routes/motoristas.py:468-489` | Mapeamento `categoria_minima` pode precisar expandir | Média |

### 3.2 Backend — O que precisa mudar

| Componente | Impacto | Prioridade |
|------------|---------|------------|
| `app.py:234` — Modelo legado `String(2)` → `String(5)` | **Necessário migração de coluna** | **Crítica** |
| `sistema/models/motorista.py:255-267` — Validator | Revisar lista de categorias válidas | Alta |
| `sistema/models/motorista.py:139` — `habilitado_para_transporte_pacientes` | Pode precisar incluir novas combinações | Média |
| `sistema/models/motorista.py:372-385` — `pode_dirigir_veiculo` | Mapeamento pode precisar expansão | Média |
| `sistema/status/status_enum.py:363-386` — `can_drive_vehicle()` | Sincronizar com `pode_dirigir_veiculo` do modelo | Média |

### 3.3 Banco de Dados

| Ação necessária | Risco |
|-----------------|-------|
| **Migração de coluna:** `VARCHAR(2)` → `VARCHAR(5)` | **Médio.** Pode quebrar se houver constraints. Dados existentes (B, C, D, E) cabem em 5 sem problema. |
| **Registros existentes:** Categorias atuais (B, C, D, E) continuam válidas | ✅ Baixo |
| **Nenhum registro será perdido** | ✅ Baixo |

### 3.4 Relatórios, Filtros, Exportações

| Componente | Impacto |
|------------|---------|
| Exibição em tabelas HTML | ✅ Baixo — já exibe o texto da categoria |
| Exportação CSV (`motoristas.py:685`) | ✅ Baixo — campo textual, aceita qualquer valor |
| Filtro de listagem (`motoristas.py:64-65`) | ⚠️ Precisa ampliar opções do dropdown |
| Filtro `categoria_minima` em busca AJAX (`motoristas.py:468-489`) | ⚠️ Precisa revisar mapeamento para incluir novas combinações |

### 3.5 Regras de Negócio — Mapeamento Completo

| Regra | Local | Depende de categoria | Impacto |
|-------|-------|---------------------|---------|
| Motorista habilitado para transporte pacientes | `sistema/models/motorista.py:139` | ✅ `D`, `E`, `AD`, `AE` | Se novas categorias forem adicionadas, revisar se alguma equivale a D/E |
| Motorista pode dirigir van | `sistema/models/motorista.py:377` | ✅ `B`, `C`, `D`, `E`, `AB`, `AC`, `AD`, `AE` | Mapeamento pode precisar de revisão |
| Motorista pode dirigir micro-ônibus | `sistema/models/motorista.py:378` | ✅ `D`, `E`, `AD`, `AE` | Mesmo caso |
| Motorista pode dirigir ambulância | `sistema/models/motorista.py:379` | ✅ `B`, `C`, `D`, `E`, `AB`, `AC`, `AD`, `AE` | Mesmo caso |
| Motorista pode dirigir veículo comum | `sistema/models/motorista.py:380` | ✅ `B`, `C`, `D`, `E`, `AB`, `AC`, `AD`, `AE` | Mesmo caso |
| Busca AJAX com `categoria_minima` | `sistema/routes/motoristas.py:468-489` | ✅ Mapeamento B→[...], C→[...], D→[...], E→[...] | Revisar para incluir AB, AC, AD, AE como entrada |
| Agendamento: verificar CNH vencendo | `sistema/services/agendamento_service.py:434-439` | ❌ Apenas data de vencimento | Nenhum |

---

## 4. Categorias Oficiais da CNH Brasileira

A legislação brasileira (CTB - Lei 9.503/97, art. 143) define as seguintes categorias:

| Categoria | Descrição | Combinações possíveis |
|-----------|-----------|----------------------|
| **A** | Motocicleta, motoneta, ciclomotor | AB, AC, AD, AE |
| **B** | Veículo de passeio (até 3.500kg) | BC, BD, BE |
| **C** | Veículo de carga (acima de 3.500kg) | CD, CE, CB |
| **D** | Transporte de passageiros (+8 lugares) | DE, DB, DC |
| **E** | Veículo com unidade acoplada (+6.000kg) | EA, EB, EC, ED |
| **ACC** | Ciclomotor (até 50cc) | — (categoria autônoma, não combina) |

**Combinações mais comuns no sistema real:** A, B, C, D, E, AB, AC, AD, AE, ACC.

### 4.1 Situação atual do sistema vs. oficial

| Categoria | No Enum atual? | No validador? | No form criar? | No form editar? |
|-----------|---------------|---------------|---------------|-----------------|
| A | ✅ | ✅ | ✅ | ❌ |
| B | ✅ | ✅ | ✅ | ✅ |
| C | ✅ | ✅ | ✅ | ✅ |
| D | ✅ | ✅ | ✅ | ✅ |
| E | ✅ | ✅ | ✅ | ✅ |
| AB | ✅ | ✅ | ✅ | ❌ |
| AC | ✅ | ✅ | ✅ | ❌ |
| AD | ✅ | ✅ | ✅ | ❌ |
| AE | ✅ | ✅ | ✅ | ❌ |
| ACC | ❌ | ❌ | ✅ (só app.py) | ❌ |
| BC | ❌ | ❌ | ❌ | ❌ |
| BD | ❌ | ❌ | ❌ | ❌ |
| BE | ❌ | ❌ | ❌ | ❌ |
| CD | ❌ | ❌ | ❌ | ❌ |
| CE | ❌ | ❌ | ❌ | ❌ |
| DE | ❌ | ❌ | ❌ | ❌ |

---

## 5. Riscos

| Risco | Probabilidade | Impacto | Mitigação |
|-------|--------------|---------|-----------|
| **Quebra de compatibilidade:** Modelo `String(2)` não aceitar gravação de `AB` | Alta | Alto | Migração de coluna obrigatória antes de permitir novas categorias |
| **Inconsistência de dados:** Registros com categoria não reconhecida pelo validador (ex: `ACC`) | Média | Médio | Mapear valores existentes no banco antes da migração |
| **Regra de negócio desatualizada:** Motorista com `AD` não ser considerado habilitado | Média | Alto | Revisar `habilitado_para_transporte_pacientes` |
| **Formulário de edição limitado:** Usuário não consegue alterar categoria para `AD` | **Já ocorre** | Alto | Correção no frontend é prioridade |
| **Dual codebase:** Alterar só o Blueprint e esquecer o monólito | Alta | Alto | Alterar ambos simultaneamente ou definir qual será descartado |
| **Impacto em usuários já cadastrados:** Dados existentes permanecem intactos | Baixo | Baixo | Nenhum registro é perdido |

---

## 6. Complexidade da Implementação

**Classificação: MÉDIA**

**Justificativa:**
- O frontend é a parte mais crítica (formulário de edição só tem 4 opções)
- O banco de dados requer migração de coluna (`VARCHAR(2)` → `VARCHAR(5)`)
- As regras de negócio já consideram `AB`, `AC`, `AD`, `AE` no modelo Blueprint
- O Enum já está preparado com `CategoriaCNH.get_choices()`
- Não há impacto em APIs externas (nenhuma integração)
- A complexidade está em **coordenar a migração do monólito para o Blueprint** ou manter ambos sincronizados

---

## 7. Plano de Implementação Futura

### 7.1 Sequência recomendada

| Fase | Descrição | Esforço estimado | Dependências |
|------|-----------|-----------------|--------------|
| **1** | **Mapear dados existentes:** Consultar `SELECT DISTINCT categoria_cnh FROM motoristas` para identificar valores reais armazenados | 1h | Banco atual |
| **2** | **Migração de BD:** ALTER COLUMN `categoria_cnh` VARCHAR(2) → VARCHAR(5) no SQLite (via migration script) | 2h | Fase 1 |
| **3** | **Atualizar modelo legado** em `app.py:234`: `String(2)` → `String(5)` | 0,5h | Fase 2 |
| **4** | **Corrigir formulário de criar** em `app.py:5344-5362`: remover `ACC`, sincronizar com Enum | 1h | Fase 3 |
| **5** | **Corrigir formulário de editar** em `app.py:5640-5646`: incluir todas as categorias | 1h | Fase 3 |
| **6** | **Revisar Enum** `CategoriaCNH` em `status_enum.py`: decidir se inclui `ACC`, `BC`, `BD`, etc. | 1h | — |
| **7** | **Sincronizar validador** em `sistema/models/motorista.py:255-267` com o Enum | 0,5h | Fase 6 |
| **8** | **Revisar regras de negócio** (`habilitado_para_transporte_pacientes`, `pode_dirigir_veiculo`, `can_drive_vehicle`) para incluir novas combinações | 2h | Fase 6 |
| **9** | **Atualizar filtro `categoria_minima`** na busca AJAX (`motoristas.py:468-489`) para aceitar AB, AC, AD, AE como entrada | 1h | Fase 6 |
| **10** | **Atualizar dropdowns de filtro** nos templates | 1h | Fase 6 |
| **11** | **Atualizar relatórios** se necessário (filtros por categoria) | 1h | Fase 6 |
| **12** | **Testes:** cadastrar motorista com cada categoria, editar, filtrar, exportar | 3h | Fases 1-11 |
| **13** | **Migração Blueprint** (opcional): registrar Blueprints em `create_app()` e deprecar monólito | 8h | Fases 1-12 |

### 7.2 Ordem de implementação

```
Fase 1 (diagnóstico) → Fase 2 (BD) → Fase 3-5 (modelo + forms críticos)
→ Fase 6-7 (Enum + validador) → Fase 8 (regras de negócio)
→ Fase 9-11 (filtros + relatórios) → Fase 12 (testes) → Fase 13 (migração)
```

### 7.3 Estratégia de testes

1. **Unitários:** Validar que cada categoria aceita pelo `@validates` é realmente persistida
2. **Unitários:** Testar `habilitado_para_transporte_pacientes` para cada categoria
3. **Unitários:** Testar `pode_dirigir_veiculo` para todas as combinações (categoria × tipo_veiculo)
4. **Integração:** Criar motorista com cada categoria via formulário (criar e editar)
5. **Regressão:** Verificar que registros antigos (B, C, D, E) continuam funcionando
6. **Filtros:** Testar filtro por categoria na listagem e na busca AJAX

### 7.4 Estratégia de rollback

1. **Banco:** Script de reversão: `ALTER COLUMN categoria_cnh VARCHAR(5) → VARCHAR(2)` (apenas se dados couberem em 2)
2. **Código:** `git revert` dos commits de alteração
3. **Validação:** Verificar que formulários voltaram ao estado anterior

---

## 8. Recomendações Técnicas

### 8.1 Recomendação primária — resolver o dual codebase

Antes de ampliar categorias, **definir qual implementação será mantida**:
- **Opção A:** Migrar tudo para os Blueprints (`sistema/`) e registrar em `create_app()`
- **Opção B:** Abandonar os Blueprints e fazer todas as alterações no monólito (`app.py`)

**Recomendação: Opção A** — os Blueprints já têm o modelo mais moderno (`String(5)`), Enum, validações e templates Jinja2. O esforço de registrar os Blueprints é pequeno comparado ao benefício.

### 8.2 Recomendações específicas

1. **Centralizar lista de categorias:** Mover para `config.py` ou um único arquivo de constantes, referenciado por modelo, Enum e templates
2. **Usar o Enum como fonte da verdade:** `CategoriaCNH.get_choices()` alimenta todos os selects
3. **Remover `ACC`** do formulário criar (a menos que seja oficialmente suportado — decidir com o usuário)
4. **Adicionar categorias combinadas adicionais** (`BC`, `BD`, `BE`, `CD`, `CE`, `DE`) se houver demanda real
5. **Criar migration script** ao invés de alterar coluna manualmente
6. **Adicionar `index=True`** na coluna `categoria_cnh` se filtros forem frequentes

---

## 9. Checklist para Implementação Futura

- [ ] **Fase 1:** Executar `SELECT DISTINCT categoria_cnh FROM motoristas` para diagnosticar valores existentes
- [ ] **Fase 2:** Criar script de migração: `ALTER TABLE motoristas ALTER COLUMN categoria_cnh TYPE VARCHAR(5)`
- [ ] **Fase 3:** Alterar `app.py:234` — `String(2)` → `String(5)`
- [ ] **Fase 4:** Remover `ACC` do select em `app.py:5357` OU adicionar ao Enum + validador
- [ ] **Fase 5:** Substituir select limitado em `app.py:5640-5646` pelo `CategoriaCNH.get_choices()`
- [ ] **Fase 6:** Revisar `sistema/status/status_enum.py` — incluir/excluir categorias
- [ ] **Fase 7:** Sincronizar `sistema/models/motorista.py:255-267` com o Enum
- [ ] **Fase 8:** Revisar `sistema/models/motorista.py:139` — `habilitado_para_transporte_pacientes`
- [ ] **Fase 9:** Revisar `sistema/models/motorista.py:372-385` — `pode_dirigir_veiculo`
- [ ] **Fase 10:** Revisar `sistema/status/status_enum.py:363-386` — `can_drive_vehicle()`
- [ ] **Fase 11:** Atualizar `sistema/routes/motoristas.py:468-489` — mapeamento `categoria_minima`
- [ ] **Fase 12:** Atualizar dropdown de filtro nos templates
- [ ] **Fase 13:** Verificar relatórios (`app.py:6432,6638`; `sistema/routes/motoristas.py:629,685`)
- [ ] **Fase 14:** Testar cadastro com cada nova categoria
- [ ] **Fase 15:** Testar edição alterando categoria
- [ ] **Fase 16:** Testar filtros e exportações
- [ ] **Fase 17:** Verificar registros antigos mantidos

---

## 10. Resumo Executivo

| Item | Status |
|------|--------|
| **Problema principal** | Formulário de edição só oferece B, C, D, E — faltam A, AB, AC, AD, AE |
| **Causa raiz** | Dual codebase: monólito (`app.py`) desatualizado vs. Blueprints modernos mas não registrados |
| **Impacto imediato** | Usuário não consegue cadastrar/editar motorista com categoria `AD` |
| **Complexidade** | Média |
| **Risco maior** | Coluna `VARCHAR(2)` no banco impede armazenamento físico de categorias combinadas |
| **Prioridade** | Fases 1-5 (diagnóstico + BD + formulários) são críticas |
| **Esforço total estimado** | ~24h (incluindo testes e migração opcional para Blueprints) |
| **Recomendação principal** | Sincronizar o monólito com os Blueprints, centralizar categorias no Enum, migrar BD |

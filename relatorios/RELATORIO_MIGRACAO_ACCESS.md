# Relatório Técnico — Análise do Banco Access para Migração

**Data:** 16/06/2026  
**Banco Access:** `dados/Banco-AGENDAMENTO-DE-TRANSPORTE.accdb`  
**Sistema destino:** Python/STP — `db/transporte_pacientes.db` (porta 5020)  
**Status:** Análise concluída — **nenhuma importação executada**

---

## 1. Estrutura do Banco Access

### 1.1 Tabelas existentes (12)

| Tabela | Registros | Função provável |
|--------|-----------|-----------------|
| **TB TRANSPORTE** | 19.262 | Agendamentos de transporte (tabela principal) |
| **TAB PACIENTE** | 2.409 | Cadastro de pacientes |
| **TB RESULTADO DE EXAME** | 1.754 | Resultados de exames |
| **TAB DESTINO** | 819 | Catálogo de destinos |
| **TAB ESPECIALIDADES** | 134 | Catálogo de especialidades médicas |
| **TAB AC** | 91 | Acompanhantes (AC) |
| **TB LOCAL DO EAXAME** | 73 | Locais de exame |
| **TB MOTORISTA** | 51 | Lista simples de motoristas |
| **TB FROTAS** | 35 | Lista simples de números de frota |
| **TAB CONDIÇÃO DO PACIENTE** | 10 | Tipos de condição (maca, cadeirante, etc.) |
| **TAB ATENDENTE** | 9 | Usuários atendentes |
| **TAB ADMINISTRADOR GERAL** | 1 | Administrador |

### 1.2 Chaves primárias

O Access usa campos **COUNTER** (auto-incremento) como PK implícita, mas **não há FKs formais declaradas** no banco (relacionamentos por ODBC retornaram vazio). Os vínculos são feitos por **texto livre** (nome do paciente, nome do motorista) ou **número de frota** (inteiro).

| Tabela | PK (COUNTER) |
|--------|--------------|
| TB TRANSPORTE | `Código` |
| TAB PACIENTE | `CÓDIGO DO PACIENTE` |
| TB MOTORISTA | `Código` |
| TB FROTAS | `Código` |
| TAB DESTINO | `Código` |
| TAB AC | `CODIGO DO AC` |

### 1.3 Índices relevantes

- `TB TRANSPORTE`: índices em `NOME DO PACIENTE`, `DESTINO`, `ATENDENTE`, `CONDIÇÃO DO PACIENTE`
- `TAB PACIENTE`: índice em `NOME DO PACIENTE`
- `TAB DESTINO`: índice em `DESTINO`

### 1.4 Relacionamentos (lógicos, não formais)

```
TAB PACIENTE ──(nome texto)──► TB TRANSPORTE.NOME DO PACIENTE
TB MOTORISTA ──(nome texto)──► TB TRANSPORTE.MOTORISTA
TB FROTAS    ──(número)──────► TB TRANSPORTE.FROTA
TAB DESTINO  ──(texto)────────► TB TRANSPORTE.DESTINO
TAB AC       ──(ID inteiro)──► TB TRANSPORTE.AC
TAB ESPECIALIDADES ─(texto)──► TB TRANSPORTE.ESPECIALIDADE
```

---

## 2. Tabelas prioritárias — Detalhamento

### 2.1 TB MOTORISTA (51 registros)

| Campo | Tipo Access | Obrigatório |
|-------|-------------|-------------|
| Código | COUNTER | NOT NULL |
| MOTORISTAS | VARCHAR(255) | NULL |

**Atenção:** Esta tabela contém **apenas o nome** do motorista. Não há CPF, CNH, categoria, validade, telefone ou status.

Exemplos: MARCIO, ROBERTO, WAGNER, CLAUDEMIR S.T

### 2.2 TB FROTAS (35 registros → 34 números únicos)

| Campo | Tipo Access | Obrigatório |
|-------|-------------|-------------|
| Código | COUNTER | NOT NULL |
| FROTAS | INTEGER | NULL |

**Atenção:** Esta tabela contém **apenas números de frota** (ex: 299, 274, 273). Não há placa, modelo, marca, ano, capacidade ou combustível.

Números cadastrados: 10, 33, 71, 90, 144, 223, 230, 238, 241, 251, 252, 253, 260, 261, 262, 263, 268, 269, 273, 274, 275, 277, 286, 299, 313, 320, 321, 2213, 2230, 3130, 3230, 3930, 8130, 8736

### 2.3 TB TRANSPORTE (19.262 registros) — Agendamentos

| Campo | Tipo Access | Nulos | Descrição |
|-------|-------------|-------|-----------|
| Código | COUNTER | 0 | PK |
| DATA DA CONSULTA | DATETIME | 2.292 | Data do agendamento |
| NOME DO PACIENTE | VARCHAR(255) | 1.167 | Nome (texto livre) |
| MOTORISTA | VARCHAR(255) | 2.618 | Nome motorista (texto livre) |
| FROTA | INTEGER | 5.222 | Número da frota |
| DESTINO | VARCHAR(255) | 2.291 | Destino (texto livre) |
| OBSERVAÇÃO | LONGCHAR | 2.294 | Observações |
| AC | INTEGER | — | ID acompanhante |
| ATENDENTE | VARCHAR(255) | 7.319 | Nome do atendente |
| HORA DA CONSULTA | DATETIME | — | Hora (base 1899-12-30) |
| ESPECIALIDADE | VARCHAR(255) | 7.167 | Especialidade médica |
| HORA SAIDA | DATETIME | — | Hora de saída |
| CONDIÇÃO DO PACIENTE | VARCHAR(255) | 14.877 | Condição do paciente |
| ADMINISTRADOR | VARCHAR(255) | 19.262 | Sempre nulo |
| DIA DA SEMANA | VARCHAR(255) | 2.307 | Dia da semana |

### 2.4 TAB PACIENTE (2.409 registros)

| Campo | Tipo Access | Nulos significativos |
|-------|-------------|---------------------|
| CÓDIGO DO PACIENTE | COUNTER | — |
| DATA DO CADASTRO | DATETIME | — |
| NOME DO PACIENTE | VARCHAR(255) | 0 |
| IDADE | INTEGER | — |
| RUA, NUMERO, BAIRRO | VARCHAR | 2–17 |
| COMPLEMENTO | VARCHAR | 2.313 |
| TELEFONE | VARCHAR | 23 |
| RG | VARCHAR | 758 |
| **CPF** | **DOUBLE** | **problema grave** |
| CARACTERISTICA ESPECIAL | VARCHAR | 2.285 |
| PONTO | VARCHAR | 870 |
| OBSERVAÇÃO | VARCHAR | 1.088 |
| DT DE NASCIMENTO | DATETIME | — |
| NOME AC, RG AC, TEL AC... | Vários | Acompanhante embutido |

---

## 3. Mapeamento Access → Python (app.py)

### 3.1 Motoristas

| Campo Python (`motoristas`) | Campo Access | Situação |
|-----------------------------|--------------|----------|
| `nome` | TB MOTORISTA.MOTORISTAS | ✅ Disponível |
| `cpf` | — | ❌ **Não existe** — obrigatório no Python |
| `telefone` | — | ❌ Não existe — obrigatório no Python |
| `data_nascimento` | — | ❌ Não existe — obrigatório no Python |
| `cnh` | — | ❌ Não existe — obrigatório no Python |
| `categoria_cnh` | — | ❌ Não existe — obrigatório no Python |
| `vencimento_cnh` | — | ❌ Não existe — obrigatório no Python |
| `status` | — | ⚠️ Default `'ativo'` |
| `observacoes` | — | ⚠️ Pode ficar vazio |

### 3.2 Veículos

| Campo Python (`veiculos`) | Campo Access | Situação |
|---------------------------|--------------|----------|
| `placa` | — | ❌ **Não existe** — obrigatório no Python |
| `marca` | — | ❌ Não existe — obrigatório no Python |
| `modelo` | — | ❌ Não existe — obrigatório no Python |
| `ano` | — | ❌ Não existe — obrigatório no Python |
| `tipo` | — | ⚠️ Default `'van'` ou similar |
| `capacidade` | — | ⚠️ Opcional |
| `observacoes` | TB FROTAS.FROTAS | ⚠️ Pode gravar "Frota Nº {número}" |
| `ativo` | — | ⚠️ Default `True` |

**Sugestão:** Criar veículos com placa fictícia `FROTA-{número}` (ex: `FROTA-299`) até obter dados reais.

### 3.3 Agendamentos

| Campo Python (`agendamentos`) | Campo Access | Situação |
|-------------------------------|--------------|----------|
| `paciente_id` | TB TRANSPORTE.NOME DO PACIENTE | ⚠️ Resolver por nome → ID (fuzzy match) |
| `motorista_id` | TB TRANSPORTE.MOTORISTA | ⚠️ Resolver por nome → ID (normalização) |
| `veiculo_id` | TB TRANSPORTE.FROTA | ⚠️ Resolver número frota → ID veículo |
| `data` | DATA DA CONSULTA | ✅ Direto |
| `hora` | HORA DA CONSULTA | ✅ Extrair time (ignorar data 1899) |
| `origem` | — | ⚠️ Usar endereço do paciente ou "Cosmópolis" |
| `destino` | DESTINO | ✅ Direto |
| `tipo_transporte` | — | ⚠️ Default `'consulta'` |
| `observacoes` | OBSERVAÇÃO + ESPECIALIDADE + CONDIÇÃO | ⚠️ Concatenar |
| `status` | — | ⚠️ Inferir de texto ("CANCELOU" → `cancelado`) |

### 3.4 Pacientes (pré-requisito para agendamentos)

| Campo Python (`pacientes`) | Campo Access | Situação |
|----------------------------|--------------|----------|
| `nome` | NOME DO PACIENTE | ✅ |
| `cpf` | CPF (DOUBLE) | ⚠️ **87% inválidos** — ver seção 4 |
| `telefone` | TELEFONE | ✅ (23 nulos) |
| `data_nascimento` | DT DE NASCIMENTO | ✅ |
| `endereco` | RUA + NUMERO + BAIRRO | ⚠️ Montar texto |
| `cep` | — | ❌ Não existe |
| `observacoes` | OBSERVAÇÃO + PONTO + CARACTERISTICA | ⚠️ Concatenar |

---

## 4. Verificações de qualidade de dados

### 4.1 Registros duplicados

| Entidade | Duplicata encontrada |
|----------|---------------------|
| TB MOTORISTA | `CLAUDEMIR S.T` (2x) |
| TAB PACIENTE | 5 nomes duplicados |
| TB FROTAS | 1 número duplicado |

### 4.2 Campos nulos (TB TRANSPORTE)

| Campo | Registros nulos | % do total |
|-------|-----------------|------------|
| ADMINISTRADOR | 19.262 | 100% |
| CONDIÇÃO DO PACIENTE | 14.877 | 77% |
| ATENDENTE | 7.319 | 38% |
| ESPECIALIDADE | 7.167 | 37% |
| FROTA | 5.222 | 27% |
| MOTORISTA | 2.618 | 14% |
| NOME DO PACIENTE | 1.167 | 6% |
| DATA DA CONSULTA | 2.292 | 12% |

**~2.292 registros parecem linhas vazias** (todos os campos nulos exceto Código).

### 4.3 CPFs inválidos (TAB PACIENTE)

| Situação | Quantidade | % |
|----------|------------|---|
| CPF válido | 296 | 12% |
| CPF inválido | 2.112 | 88% |
| Nulo/zerado | 1 | <1% |

**Causa raiz:** CPF armazenado como `DOUBLE` — perde zeros à esquerda e formatação. Ex: `519.0`, `0.0`, `2460164858.0`

### 4.4 Placas inválidas

Não aplicável — **não existem placas no Access**.

### 4.5 Datas inconsistentes

| Verificação | Resultado |
|-------------|-----------|
| Datas antes de 2000 | 0 |
| Datas depois de 2027 | 3 |
| Horas com data base 1899-12-30 | Padrão Access (normal) |

### 4.6 Relacionamentos quebrados

| Vínculo | Quebrados | Total distintos | % |
|---------|-----------|-----------------|---|
| Motorista (transporte → cadastro) | 395 nomes | — | Muitas variações ("ADILSON - S.T", "CANCELOU", etc.) |
| Frota (transporte → cadastro) | 42 números | — | Ex: 19, 21, 23, 24, 42... |
| Paciente (transporte → cadastro) | 150 nomes | 2.528 | 6% |

---

## 5. Estado atual do SQLite (produção)

| Tabela | Registros atuais |
|--------|-----------------|
| pacientes | 1 |
| motoristas | 1 |
| veiculos | 2 |
| agendamentos | 1 |
| usuarios | 1 |

O banco Python está praticamente vazio — ambiente seguro para testes de migração.

---

## 6. Estratégia de migração proposta

### Fase 0 — Preparação (antes de importar)

- [ ] Definir regras para campos obrigatórios ausentes (CPF/CNH/placa fictícios?)
- [ ] Criar tabela `migracao_id_map` (access_id → python_id)
- [ ] Backup do SQLite atual
- [ ] Modo dry-run obrigatório em todos os scripts

### Fase 1 — Motoristas ✅

1. Importar 51 nomes de `TB MOTORISTA`
2. Gerar CPF/CNH fictícios sequenciais OU solicitar dados reais antes
3. Deduplicar `CLAUDEMIR S.T`
4. Normalizar nomes para match futuro (uppercase, remover sufixos)
5. Registrar mapa: `access_codigo → motoristas.id`

**Estimativa:** 50 motoristas únicos

### Fase 2 — Veículos ✅

1. Importar 34 frotas de `TB FROTAS`
2. Criar veículos com placa `FROTA-{numero}`, marca/modelo genéricos
3. Registrar mapa: `access_frota_numero → veiculos.id`
4. Criar entradas para os 42 números órfãos encontrados em transportes

**Estimativa:** ~76 veículos

### Fase 3 — Pacientes (pré-requisito agendamentos)

1. Importar 2.409 pacientes de `TAB PACIENTE`
2. Tratar CPF: tentar reconstruir de DOUBLE, ou gerar placeholder
3. Montar endereço a partir de RUA+NUMERO+BAIRRO
4. Registrar mapa: `access_codigo_paciente → pacientes.id`
5. Criar índice auxiliar `nome_normalizado → paciente_id` para match

**Estimativa:** 2.409 pacientes

### Fase 4 — Agendamentos ⚠️ (mais complexo)

1. Filtrar registros vazios (~2.292 linhas)
2. Para cada transporte válido:
   - Resolver `paciente_id` por nome (fuzzy match 94%+)
   - Resolver `motorista_id` por nome normalizado
   - Resolver `veiculo_id` por número frota
   - Inferir `status` de texto ("CANCELOU" → cancelado)
3. Registros sem match → log de erro, não importar
4. Registrar mapa: `access_codigo_transporte → agendamentos.id`

**Estimativa importável:** ~17.000 (após filtros)

### Fase 5 — Validação ✅

- Contagem de registros importados vs Access
- Integridade referencial (FKs válidas)
- Relatório de erros/inconsistências
- Teste manual de amostra

### Fase 6 — Homologação → Produção ✅

---

## 7. Decisões necessárias (aguardando aprovação)

Antes de implementar, precisamos alinhar:

1. **CPF/CNH fictícios para motoristas?** O Python exige esses campos. Opções:
   - A) Gerar placeholders (`000.000.000-01`, `000.000.000-02`...)
   - B) Preencher manualmente depois da importação
   - C) Relaxar validação no Python temporariamente

2. **Veículos sem placa real?** Opções:
   - A) Placa fictícia `FROTA-{número}`
   - B) Você fornece planilha com placa/modelo/marca por frota

3. **CPF de pacientes inválidos (88%)?** Opções:
   - A) Gerar CPF placeholder único por paciente
   - B) Usar RG como identificador alternativo
   - C) Importar só pacientes com CPF válido (296)

4. **Importar pacientes na Fase 1 ou junto com agendamentos?** Recomendo importar pacientes antes dos agendamentos.

5. **Registros cancelados** (nomes com "CANCELOU", motoristas com anotações)? Importar com status `cancelado` ou ignorar?

6. **~2.292 linhas vazias em TB TRANSPORTE** — Ignorar automaticamente?

---

## 8. Arquivos gerados nesta análise

| Arquivo | Descrição |
|---------|-----------|
| `relatorios/analise_access_raw.json` | Dados brutos completos da análise |
| `relatorios/RELATORIO_MIGRACAO_ACCESS.md` | Este relatório |
| `scripts/_analise_access_temp.py` | Script de leitura do Access |
| `scripts/_analise_qualidade_temp.py` | Script de verificação de qualidade |

**Scripts pendentes (após aprovação):**
- `scripts/migrar_motoristas.py` (com dry-run)
- `scripts/migrar_veiculos.py` (com dry-run)
- `scripts/migrar_pacientes.py` (com dry-run)
- `scripts/migrar_agendamentos.py` (com dry-run)
- `scripts/validar_migracao.py`

---

## 9. Resumo executivo

O banco Access é um sistema legado **muito mais simples** que o Python atual:

- **Motoristas** = apenas nomes (sem documentos)
- **Veículos** = apenas números de frota (sem placas/dados)
- **Agendamentos** = vínculos por texto livre (não por ID)
- **CPFs** = 88% inválidos (tipo DOUBLE corrompe dados)

A migração é **viável**, mas exige:
1. Estratégia para campos obrigatórios ausentes
2. Normalização de nomes para match
3. Tabela de correspondência de IDs
4. Importação em fases com dry-run

**Nenhuma importação foi executada. Aguardando suas decisões sobre os itens da seção 7.**

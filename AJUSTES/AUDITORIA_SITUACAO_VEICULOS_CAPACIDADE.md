# Auditoria Profunda — Situação dos Veículos / Capacidade

**Sistema:** STP — Sistema de Transporte de Pacientes  
**URL base:** `http://localhost:5022` (produção: `https://esus.cosmopolis.sp.gov.br/transporte`)  
**Data:** 23/07/2026  
**Escopo:** Capacidade do veículo, ocupação (pacientes + acompanhantes + profissionais), conflitos de uso, UI de lotação, API, banco, concorrência, segurança  
**Código em produção auditado:** `app.py` (monólito Flask ativo)  
**Código paralelo (não operacional no monólito):** `sistema/models/*`, `sistema/routes/*`, `sistema/services/*`

---

## 1. Veredito executivo

O STP **cadastra** capacidade de passageiros no veículo, mas **não possui motor de ocupação**. Não há cálculo de vagas, não há bloqueio ao exceder a capacidade e não há indicador visual de lotação.

Na prática, é possível:

- alocar N pacientes no mesmo veículo/horário sem limite;
- ignorar acompanhantes no cálculo (não há campo estruturado de acompanhante no `Agendamento` de produção);
- reduzir a capacidade cadastral sem validar viagens futuras;
- alterar/atribuir veículo sem recalcular ocupação.

| Indicador | Valor |
|-----------|-------|
| Problemas críticos (Alta) | 8 |
| Problemas médios | 6 |
| Problemas baixos | 3 |
| Validação de ocupação no backend (produção) | **Inexistente** |
| Validação de ocupação no frontend | **Inexistente** |
| Contabilização de acompanhantes | **Não estruturada** |
| UI de lotação (X/Y, barra, vagas) | **Inexistente** |
| Lock/concorrência na capacidade | **Inexistente** |
| Conformidade com regra “nunca ultrapassar capacidade” | **0%** |

**Conclusão:** o módulo “Situação dos Veículos” no sentido de **controle de capacidade/ocupação** ainda não está implementado. O que existe hoje é cadastro de frota + atribuição livre de veículo em agendamento/uso.

---

## 2. Componentes analisados

| Papel | Local | Situação |
|-------|--------|----------|
| Modelo `Veiculo` (produção) | `app.py` L199–227 | Campo `capacidade` Integer **nullable**, sem CheckConstraint |
| Modelo `Agendamento` (produção) | `app.py` L253–275 | Sem campos de acompanhante/ocupantes |
| Modelo `UsoVeiculo` | `app.py` L280+ | Controle de uso/KM; checa “já em uso”, **não** capacidade |
| Cadastro/edição de veículos | `app.py` `/veiculos/cadastrar`, `/veiculos/editar` | Capacidade inferida/manual; edição permite null/valores fracos |
| Criação de agendamento | `app.py` `agendamentos_novo` ~L6760 | Sem validação de capacidade |
| Inferência de capacidade | `app.py` `inferir_capacidade_passageiros` L3071 | Heurística por modelo; fallback 5 |
| Modelo modular `Veiculo` | `sistema/models/veiculo.py` | Tem `@validates('capacidade_passageiros')` (1–50) — **não usado pelo monólito** |
| `validar_capacidade_veiculo` | `sistema/models/agendamento.py` L352 | Nome enganoso: valida **acessibilidade**, não assentos |
| Service | `sistema/services/agendamento_service.py` L349–368 | Comentário admite verificação de vagas “simplificada” e retorna OK |
| UI veículos | `sistema/templates/veiculos.html` | Exibe capacidade; sem ocupação |
| Menu “Frota” | `app.py` sidebar | Veículos + Controle de Uso + Combustível — **sem tela de Situação/Ocupação** |

---

## 3. Modelo mental esperado vs. atual

### Esperado (regra de negócio)

```
ocupacao = pacientes + acompanhantes + profissionais_extras
           (+ motorista, se a capacidade cadastrada incluir o assento do motorista —
              regra deve ser explícita no cadastro)

SE ocupacao > capacidade_veiculo → BLOQUEAR
```

### Atual (produção)

```
agendamento.veiculo_id = escolhido_pelo_usuário
commit()
# nenhum cálculo de ocupação
```

---

## 4. Matriz de conformidade (checklist do escopo)

| # | Regra | Status | Evidência |
|---|--------|--------|-----------|
| 1 | Nunca ultrapassar capacidade | ❌ Não conforme | Criação de agendamento sem checagem (`app.py` ~6801–6821) |
| 2 | Acompanhantes entram na capacidade | ❌ Não conforme | Sem campo `possui_acompanhante` no Agendamento de produção; só texto em observações |
| 3 | Múltiplos pacientes na mesma viagem | ❌ Não conforme | Cada agendamento é 1 paciente; vários no mesmo veículo/hora são permitidos sem soma |
| 4 | Tipos de veículo respeitam capacidade | ⚠️ Parcial | Capacidade é cadastral; tipo não força capacidade; SUV/utilitário nem existem como tipo distinto |
| 5 | Alteração de veículo recalcula | ❌ Não conforme | Não há fluxo de edição robusto com recálculo; troca livre |
| 6 | Redução de capacidade alerta viagens futuras | ❌ Não conforme | `veiculos_editar` grava capacidade sem checar agendamentos |
| 7 | Viagens simultâneas / conflito | ⚠️ Parcial | `UsoVeiculo` bloqueia 2 usos `em_andamento`; agendamentos no mesmo horário **não** bloqueiam por veículo |
| 8 | Reagendamento recalcula | ❌ Não conforme | Sem motor de ocupação |
| 9 | Cancelamento libera vaga | ❌ Não conforme | Status muda; não há indicador/contador de vagas |
| 10 | Inclusão posterior bloqueia no limite | ❌ Não conforme | Sem limite |
| UI | Indicador X/Y, barra, cores | ❌ Ausente | — |
| API | Rejeita ocupação > capacidade | ❌ Ausente no monólito | Modular API não cobre ocupação real |
| Concorrência | Lock ao reservar vaga | ❌ Ausente | — |
| Segurança | Validação só no front | N/A | Front e back **ambos** sem validação de ocupação |

---

## 5. Problemas identificados

---

### Problema P01 — Ausência total de validação de ocupação no agendamento

**Descrição detalhada**  
Ao criar um agendamento (`agendamentos_novo`), o sistema aceita qualquer `veiculo_id` ativo sem somar ocupantes já alocados no mesmo veículo/data/hora (ou janela da viagem). Não existe função do tipo `calcular_ocupacao(veiculo_id, data, hora)`.

**Criticidade:** Alta  

**Impacto**  
Permite lotar um carro de 4 lugares com 5+ pacientes (ex.: 4 pacientes + 1 acompanhante = 5). Risco operacional, de segurança e de responsabilidade da prefeitura.

**Arquivos envolvidos**  
- `app.py` — rota de criação de agendamento (~L6760–6842)  
- `app.py` — modelo `Agendamento` (L253–275)  
- `app.py` — modelo `Veiculo.capacidade` (L210)

**Fluxo afetado**  
Cadastro de agendamento → atribuição de veículo → commit.

**Como reproduzir**  
1. Cadastrar veículo com capacidade 4.  
2. Criar 5 agendamentos no mesmo dia/horário (ou horários sobrepostos) com o mesmo veículo e pacientes diferentes.  
3. Observar que todos são aceitos.

**Resultado esperado**  
Bloquear a partir do 5º ocupante (ou quando `ocupacao_atual + novos > capacidade`), com mensagem clara.

**Resultado atual**  
Todos os agendamentos são salvos com sucesso.

**Correção sugerida**  
Implementar serviço único:

```python
def calcular_ocupacao(veiculo_id, data, hora_inicio, hora_fim=None, excluir_agendamento_id=None):
    # soma pacientes + acompanhantes dos agendamentos ativos sobrepostos
    ...

def validar_capacidade(..., ocupantes_novos=1):
    cap = veiculo.capacidade
    if not cap or cap <= 0:
        raise ValidationError("Veículo sem capacidade cadastrada")
    if calcular_ocupacao(...) + ocupantes_novos > cap:
        raise ValidationError(f"Capacidade excedida ({ocupacao}/{cap})")
```

Chamar em criar, editar, reagendar e inclusão posterior.

**Prioridade:** P0 (imediata)  

**Estimativa de impacto da correção:** Alta — elimina o risco principal; esforço médio (serviço + integração nas rotas).

---

### Problema P02 — Acompanhantes não entram no cálculo (não há modelo estruturado)

**Descrição detalhada**  
No monólito de produção, `Agendamento` **não possui** `possui_acompanhante`, `nome_acompanhante` nem contagem de profissionais. A necessidade de acompanhante aparece como condição do paciente (texto/select em observações/condição), não como ocupante da viagem.  
Há helper `extrair_acompanhante_observacoes` apenas para impressão — não para validação.

**Criticidade:** Alta  

**Impacto**  
Mesmo após criar validação de “1 paciente = 1 vaga”, o sistema continuaria subcontando (paciente + acompanhante = 2). Exemplo obrigatório do escopo falha.

**Arquivos envolvidos**  
- `app.py` modelo `Agendamento`  
- `app.py` `extrair_acompanhante_observacoes` (~L2718)  
- Condição do paciente (necessita acompanhante) em formulários de paciente  
- (Referência modular, não usada): `sistema/models/agendamento.py` campos L59–62

**Fluxo afetado**  
Agendamento com acompanhante; viagem compartilhada; impressão vs. operação.

**Como reproduzir**  
1. Paciente com “Necessita acompanhante”.  
2. Agendar em veículo capacidade 1 (ou lotar até o limite só com pacientes).  
3. Sistema não exige/conta o acompanhante.

**Resultado esperado**  
`ocupacao += 1 (paciente) + 1 (acompanhante se marcado) + N profissionais`.

**Resultado atual**  
Acompanhante é informação textual, não ocupa vaga.

**Correção sugerida**  
1. Migrar colunas: `possui_acompanhante`, `nome_acompanhante`, `qtd_acompanhantes` (default 0/1), `qtd_profissionais`.  
2. Se condição do paciente = “Necessita acompanhante”, forçar `qtd_acompanhantes >= 1`.  
3. Incluir no cálculo de ocupação.

**Prioridade:** P0  

**Estimativa de impacto da correção:** Alta — depende de migração de schema + UI.

---

### Problema P03 — `validar_capacidade_veiculo` no módulo `sistema/` é falso positivo

**Descrição detalhada**  
No pacote modular, o método `Agendamento.validar_capacidade_veiculo()` **não valida capacidade de assentos**. Ele apenas chama `veiculo.pode_transportar_paciente()` (cadeirante / acessibilidade).  
O service ainda contém:

> “Verificar se há vagas … verificação simplificada …  
> return True, Paciente e veículo são compatíveis”

**Criticidade:** Alta (para quem usar o módulo modular / falsa segurança)

**Impacto**  
Desenvolvedores e auditores podem achar que a capacidade já está coberta. Em produção monólito o problema é pior (nem esse método é chamado).

**Arquivos envolvidos**  
- `sistema/models/agendamento.py` L352–366  
- `sistema/models/veiculo.py` L322–333  
- `sistema/services/agendamento_service.py` L349–368  
- `sistema/routes/agendamentos.py` L235–238, L381–385

**Fluxo afetado**  
Criação/edição de agendamento no blueprint modular.

**Como reproduzir**  
Inspecionar o código do método; ou agendar múltiplos pacientes no mesmo veículo via rotas do blueprint (se ativo).

**Resultado esperado**  
Método deve somar ocupação e comparar com `capacidade_passageiros`.

**Resultado atual**  
Só valida acessibilidade PCD.

**Correção sugerida**  
Renomear método atual para `validar_compatibilidade_acessibilidade`.  
Criar `validar_ocupacao_capacidade()` com a regra real.  
Remover o `return True` “simplificado” do service.

**Prioridade:** P0  

**Estimativa de impacto da correção:** Média — correção localizada, mas crítica.

---

### Problema P04 — Capacidade nullable / zero / inválida no cadastro de produção

**Descrição detalhada**  
Em produção: `capacidade = db.Column(db.Integer)` **sem** `nullable=False` e sem CheckConstraint.  
No POST de cadastro: `capacidade=int(capacidade) if capacidade else None`.  
Na edição: mesmo padrão; HTML tem `min="1" max="50"` (só front).  
Não há validação server-side contra 0, negativo, decimal (string “3.5” pode falhar ou truncar via `int()`), nem valores absurdos além do que o front sugere.

**Criticidade:** Alta  

**Impacto**  
Veículo sem capacidade ou com capacidade inválida torna qualquer regra futura inaplicável ou inconsistente. Bypass via DevTools/API/form POST é trivial.

**Arquivos envolvidos**  
- `app.py` L210, L5345–5371, L5728–5750, L5827–5828  
- Contraste: `sistema/models/veiculo.py` L268–277 (`@validates`)

**Fluxo afetado**  
Cadastro e edição de veículos.

**Como reproduzir**  
1. Editar veículo e limpar o campo capacidade → salva `NULL`.  
2. Ou enviar POST com `capacidade=0` / `-1` (front pode ser burlado).

**Resultado esperado**  
Rejeitar null/≤0/não-inteiro; obrigatório; faixa 1–50 (ou política definida); CHECK no banco.

**Resultado atual**  
Aceita NULL; front `min/max` não garante backend.

**Correção sugerida**  
- `nullable=False`, default sensato ou bloqueio.  
- Validação server-side espelhando o modular.  
- `CHECK (capacidade BETWEEN 1 AND 50)` no SQLite/Postgres.  
- Migration para preencher NULLs existentes via `inferir_capacidade_passageiros`.

**Prioridade:** P0  

**Estimativa de impacto da correção:** Média.

---

### Problema P05 — Redução de capacidade não valida viagens futuras

**Descrição detalhada**  
`veiculos_editar` atualiza `veiculo.capacidade` e faz `commit` sem consultar agendamentos futuros cuja ocupação projetada excederia a nova capacidade.

**Criticidade:** Alta  

**Impacto**  
Van 15 → Automóvel lógica mental: reduzir para 4 com 10 pacientes já agendados deixa dados inconsistentes e operação ilegal/insegura.

**Arquivos envolvidos**  
- `app.py` `veiculos_editar` (~L5711–5757)

**Fluxo afetado**  
Edição de cadastro de veículo.

**Como reproduzir**  
1. Veículo capacidade 15 com vários agendamentos futuros.  
2. Alterar capacidade para 4.  
3. Salvar com sucesso.

**Resultado esperado**  
Bloquear ou exigir confirmação com lista de agendamentos inconsistentes; oferecer remanejamento.

**Resultado atual**  
Salva sem alerta.

**Correção sugerida**  
Antes do commit: calcular ocupação máxima por janela futura; se alguma > nova capacidade → HTTP 400 / flash com detalhes.

**Prioridade:** P0  

**Estimativa de impacto da correção:** Média-alta.

---

### Problema P06 — Troca de veículo no agendamento sem recálculo

**Descrição detalhada**  
Não há garantia de que, ao atribuir/trocar veículo de uma solicitação existente, a ocupação do veículo destino seja recalculada. A criação já não valida; a alteração de status/atribuição também não.

**Criticidade:** Alta  

**Impacto**  
Migrar pacientes de uma van (15) para um carro (4) sem bloqueio.

**Arquivos envolvidos**  
- `app.py` criação/atribuição de `veiculo_id`  
- Fluxos de alteração de status (`alterar_status_agendamento`)

**Fluxo afetado**  
Edição/atribuição de veículo; remanejamento de frota.

**Como reproduzir**  
Atribuir o mesmo veículo pequeno a vários agendamentos já existentes (via novos cadastros ou updates).

**Resultado esperado**  
Recalcular imediatamente; bloquear se excedido.

**Resultado atual**  
Sem recálculo.

**Correção sugerida**  
Hook único `antes_salvar_agendamento` com validação de ocupação no veículo novo e liberação no antigo.

**Prioridade:** P0  

**Estimativa de impacto da correção:** Alta (centraliza regra).

---

### Problema P07 — Conflito de horário do veículo incompleto (só “em uso”)

**Descrição detalhada**  
`uso_veiculos_iniciar` impede segundo uso com `status='em_andamento'` no mesmo veículo. Porém **múltiplos agendamentos** podem ser criados para o mesmo veículo no mesmo horário sem conflito. Ou seja: a “reserva” futura não existe; só o uso operacional em andamento.

**Criticidade:** Alta  

**Impacto**  
Double-booking da frota; sobrecarga; motorista/veículo em dois lugares.

**Arquivos envolvidos**  
- `app.py` L8627–8635, L8697–8702  
- Ausência de check em `agendamentos_novo`  
- (Modular tem `validar_disponibilidade_veiculo` — não no monólito)

**Fluxo afetado**  
Agendamento × Controle de Uso.

**Como reproduzir**  
Criar 2 agendamentos mesmos veículo/data/hora; ambos ok. Só ao iniciar 2 usos simultâneos o segundo é bloqueado.

**Resultado esperado**  
Conflito na fase de agendamento (sobreposição de janelas) + ocupação ≤ capacidade (viagem compartilhada legítima).

**Resultado atual**  
Conflito só no início do uso; capacidade ignorada.

**Correção sugerida**  
Distinguir:  
- **Viagem compartilhada** (mesmo veículo, mesma janela, vários pacientes) → somar ocupação.  
- **Viagens distintas sobrepostas** (rotas/horários incompatíveis) → conflito de disponibilidade.  
Definir regra de negócio explícita (destino igual? mesma “viagem_id”?).

**Prioridade:** P0  

**Estimativa de impacto da correção:** Alta — exige conceito de “Viagem/Roteiro” ou agrupador.

---

### Problema P08 — Sem entidade “Viagem compartilhada” / agrupador de ocupação

**Descrição detalhada**  
O modelo atual é 1 Agendamento = 1 Paciente = (opcional) 1 Veículo. Não há `viagem_id` / `roteiro_id` para agrupar pacientes que vão juntos. Sem isso, “vagas restantes” e “barra 6/8” não têm âncora clara.

**Criticidade:** Alta (arquitetural)

**Impacto**  
Qualquer UI de lotação e qualquer regra de capacidade multi-paciente fica ambígua.

**Arquivos envolvidos**  
- `app.py` modelos  
- Ausência de tabela de viagem

**Fluxo afetado**  
Todos os fluxos de lotação.

**Resultado esperado**  
Modelo:

```
Viagem (veiculo, motorista, data, hora, origem/destino)
  └── PassageirosViagem (paciente, acompanhantes, profissionais)
```

ou agendamentos ligados por `viagem_id`.

**Resultado atual**  
Agendamentos isolados.

**Correção sugerida**  
Introduzir `Viagem` (ou `GrupoTransporte`) e calcular ocupação no nível da viagem.

**Prioridade:** P0 (fundação)  

**Estimativa de impacto da correção:** Alta (maior esforço; desbloqueia o restante).

---

### Problema P09 — UI sem indicador de capacidade / ocupação / vagas

**Descrição detalhada**  
Telas de veículos e agendamentos mostram no máximo a capacidade cadastral. Não há: ocupados, disponíveis, barra de progresso, cores de alerta, mensagem de vagas restantes.

**Criticidade:** Média  

**Impacto**  
Operador não enxerga risco de lotação; erro só seria percebido (se houvesse validação) após submit.

**Arquivos envolvidos**  
- `app.py` listagem `/veiculos`, formulário de agendamento  
- `sistema/templates/veiculos.html` (exibe capacidade estática)  
- `sistema/templates/agendamentos.html` (badge acompanhante modular)

**Fluxo afetado**  
UX operacional diária.

**Resultado esperado**  
Ex.: `Ocupados 6 · Disponíveis 2 · Capacidade 8` + barra `██████░░░░` + alerta amarelo/vermelho.

**Resultado atual**  
Sem indicadores.

**Correção sugerida**  
Componente reutilizável alimentado por endpoint `GET /api/viagens/{id}/ocupacao` ou cálculo server-side no formulário ao selecionar veículo/data/hora.

**Prioridade:** P1  

**Estimativa de impacto da correção:** Média (depende de P01/P08).

---

### Problema P10 — Tipos de veículo incompletos vs. escopo (SUV, utilitário, etc.)

**Descrição detalhada**  
Tipos no monólito: `ambulancia`, `van`, `micro_onibus`, `carro`.  
Escopo pede também SUV, utilitário, outros. Capacidade não é amarrada ao tipo (apenas heurística FIPE/modelo no cadastro).

**Criticidade:** Média  

**Impacto**  
Classificação inconsistente; capacidade default pode ficar errada.

**Arquivos envolvidos**  
- `app.py` selects de tipo (~L5815–5821, cadastro)  
- `inferir_capacidade_passageiros` L3071–3088  
- Modular: tipos `van, micro_onibus, ambulancia, veiculo_comum`

**Correção sugerida**  
Ampliar enum de tipos; tabela de capacidade sugerida por tipo; sempre permitir override auditado.

**Prioridade:** P2  

**Estimativa de impacto da correção:** Baixa-média.

---

### Problema P11 — Cancelamento não atualiza indicadores de ocupação

**Descrição detalhada**  
Cancelar muda `status` para `cancelado`. Como não há contador de ocupação, “liberar vaga” é só efeito colateral implícito se no futuro o cálculo filtrar status ativos. Hoje não há UI/indicador a atualizar.

**Criticidade:** Média  

**Impacto**  
Quando a validação existir, cancelados **devem** sair da soma; precisa de teste regressivo garantindo isso.

**Arquivos envolvidos**  
- `app.py` `alterar_status_agendamento` (~L6721+)

**Correção sugerida**  
Na regra de ocupação, considerar apenas `agendado|confirmado|em_andamento`. Testes automatizados de cancelamento → vaga liberada.

**Prioridade:** P1  

**Estimativa de impacto da correção:** Baixa (se o cálculo for centralizado).

---

### Problema P12 — Sem proteção a concorrência (race condition)

**Descrição detalhada**  
Dois usuários podem criar agendamentos simultâneos para as últimas vagas. Não há `SELECT … FOR UPDATE`, versão otimista, nem constraint de ocupação no banco.

**Criticidade:** Média (torna-se Alta quando P01 for implementado sem lock)

**Impacto**  
Mesmo com validação ingenua, é possível ultrapassar capacidade sob carga.

**Arquivos envolvidos**  
- `app.py` commits de agendamento  
- Sem uso de `with_for_update`

**Correção sugerida**  
Transação: lock da viagem/veículo+janela → recalcular → inserir → commit.  
Ou tabela `viagem_ocupacao` com `CHECK (ocupados <= capacidade)` atualizada atomicamente.

**Prioridade:** P1 (junto com P01)  

**Estimativa de impacto da correção:** Média.

---

### Problema P13 — Dualidade de código (`app.py` vs `sistema/`)

**Descrição detalhada**  
Existem dois mundos: monólito operacional e pacote modular com validações diferentes (e ainda incompletas). Risco de corrigir o lugar errado.

**Criticidade:** Média  

**Impacto**  
Retrabalho; bugs “já corrigidos” no modular não chegam à produção.

**Arquivos envolvidos**  
- `app.py`, `iniciar_app.py`  
- `sistema/**`

**Correção sugerida**  
Definir fonte única da verdade. Extrair serviço de capacidade para módulo compartilhado usado pelo monólito **ou** migrar rotas para blueprints e desativar lógica duplicada.

**Prioridade:** P1  

**Estimativa de impacto da correção:** Alta (organização), benefício estrutural.

---

### Problema P14 — Segurança: capacidade e veículo manipuláveis sem regra de negócio

**Descrição detalhada**  
Qualquer usuário autenticado com acesso às rotas pode POST capacidade inválida ou atribuir veículo lotado. Não há camada de autorização específica para “gestão de capacidade”. Validação de ocupação inexistente = superfície de abuso operacional.

**Criticidade:** Média  

**Impacto**  
Integridade operacional; não é RCE, mas é falha de controle de processo.

**Arquivos envolvidos**  
- Rotas `/veiculos/*`, `/agendamentos/*` em `app.py`

**Correção sugerida**  
Validação server-side obrigatória; logs de auditoria em mudança de capacidade; permissão `pode_gerenciar_capacidade` se necessário.

**Prioridade:** P1  

**Estimativa de impacto da correção:** Baixa-média.

---

### Problema P15 — Performance / N+1 potencial após correção

**Descrição detalhada**  
Hoje não há cálculo; após implementar ocupação, se feito com loops de agendamentos por formulário sem agregação SQL, haverá N+1.

**Criticidade:** Baixa (preventivo)

**Correção sugerida**  
Query agregada:

```sql
SELECT COUNT(*) + SUM(qtd_acompanhantes) ...
WHERE veiculo_id=? AND data=? AND status IN (...) AND horarios_sobrepoem(...)
```

**Prioridade:** P2  

**Estimativa de impacto da correção:** Baixa se feita na 1ª implementação.

---

### Problema P16 — Motorista / profissionais não definidos na capacidade

**Descrição detalhada**  
Não está documentado no sistema se `capacidade` inclui o assento do motorista ou só passageiros. Profissionais (técnico, enfermeiro — condições do paciente) não geram ocupantes.

**Criticidade:** Baixa/Média (regra de negócio indefinida)

**Impacto**  
Ambiguidade: carro “5 lugares” pode ser 4 passageiros + motorista ou 5 passageiros.

**Correção sugerida**  
Definir com a operação:  
- Opção A: `capacidade_passageiros` (exclui motorista) — recomendada.  
- Opção B: `capacidade_total` − 1 motorista.  
Persistir a regra em config e UI (“Capacidade de passageiros, sem contar o motorista”).

**Prioridade:** P1 (definir antes de codar P01)  

**Estimativa de impacto da correção:** Baixa (decisão + label).

---

### Problema P17 — Testes automatizados de capacidade inexistentes

**Descrição detalhada**  
Não há suíte cobrindo: capacidade exata, excedida, troca de veículo, redução cadastral, acompanhante, concorrência, cancelamento.

**Criticidade:** Baixa (hoje) / Alta (após implementação)

**Correção sugerida**  
Criar `tests/test_capacidade_veiculo.py` com os cenários obrigatórios do escopo.

**Prioridade:** P1  

**Estimativa de impacto da correção:** Média.

---

## 6. Ordem de prioridade de correção

| Ordem | ID | Ação | Criticidade |
|------:|----|------|-------------|
| 1 | P16 | Definir regra: capacidade = passageiros (com/sem motorista) | Decisão |
| 2 | P08 | Introduzir entidade Viagem/Grupo (âncora da ocupação) | Alta |
| 3 | P02 | Modelar acompanhantes/profissionais como ocupantes | Alta |
| 4 | P04 | Capacidade obrigatória + constraints DB + validação server | Alta |
| 5 | P01 | Serviço `calcular_ocupacao` + bloqueio em criar/editar | Alta |
| 6 | P06 | Recálculo na troca de veículo | Alta |
| 7 | P05 | Alerta/bloqueio ao reduzir capacidade cadastral | Alta |
| 8 | P07 | Conflito de disponibilidade × viagem compartilhada | Alta |
| 9 | P12 | Lock/transação anti race condition | Média/Alta |
| 10 | P03 | Corrigir método enganoso no módulo `sistema/` | Alta |
| 11 | P09 | UI lotação (X/Y, barra, cores, mensagens) | Média |
| 12 | P11 | Garantir cancelamento libera vaga no cálculo | Média |
| 13 | P13 | Unificar monólito × modular | Média |
| 14 | P14 | Auditoria/permissões | Média |
| 15 | P10 | Ampliar tipos de veículo | Baixa |
| 16 | P15 | Otimizar queries | Baixa |
| 17 | P17 | Testes automatizados dos cenários | Contínua |

---

## 7. Proposta de arquitetura alvo (resumo)

```
┌─────────────┐     ┌──────────────────┐     ┌────────────────────┐
│  Cadastro   │     │  Viagem/Roteiro  │     │   Validador        │
│  Veículo    │────▶│  veiculo_id      │────▶│  ocupacao <= cap   │
│  capacidade │     │  data/hora       │     │  lock transacional │
└─────────────┘     │  passageiros[]   │     └────────────────────┘
                    │  +acompanhantes  │              │
                    └──────────────────┘              ▼
                                         ┌────────────────────┐
                                         │ UI: 6/8 ██████░░   │
                                         │ API 409 se excedeu │
                                         └────────────────────┘
```

### Contrato sugerido da API

| Endpoint | Comportamento |
|----------|----------------|
| `GET /api/veiculos/{id}/ocupacao?data=&hora=` | `{capacidade, ocupados, disponiveis, detalhe[]}` |
| `POST /agendamentos` | 409 se `ocupados + novos > capacidade` |
| `PUT /veiculos/{id}` (capacidade↓) | 409 se viagens futuras inconsistentes |
| `POST /viagens/{id}/passageiros` | Bloqueia no limite; retorna `disponiveis` |

Códigos: `400` validação de campo; `409` conflito de capacidade/disponibilidade; `422` regra de negócio.

---

## 8. Cenários de teste obrigatórios (matriz)

| # | Cenário | Esperado | Atual |
|---|---------|----------|-------|
| T1 | Capacidade 4; 4 pacientes sem acompanhante | Aceita o 4º; bloqueia o 5º | Aceita todos ❌ |
| T2 | Capacidade 4; 3 pacientes + 1 acompanhante + 1 paciente | Bloqueia | Aceita ❌ |
| T3 | Paciente + acompanhante = 2 | Conta 2 | Conta 0/1 ❌ |
| T4 | Van 15 → troca para carro 4 com 6 ocupantes | Bloqueia troca | Permite ❌ |
| T5 | Capacidade 15 → 8 com 10 futuros | Alerta/bloqueia | Permite ❌ |
| T6 | Dois usos `em_andamento` mesmo veículo | Bloqueia | Bloqueia ✅ (único ok parcial) |
| T7 | Dois agendamentos mesmo veículo/hora | Depende regra viagem | Ambos ok ⚠️ |
| T8 | Cancelar paciente | Libera vaga no indicador | Sem indicador ❌ |
| T9 | Capacidade null/0/-1 | Rejeita | Aceita null ❌ |
| T10 | Bypass DevTools capacidade | Backend rejeita | Backend fraco ❌ |
| T11 | Dois users na última vaga | Um ok, um 409 | Ambos ok ❌ |
| T12 | Reagendar para veículo menor | Recalcula/bloqueia | Sem regra ❌ |

---

## 9. Evidências de código (trechos-chave)

### 9.1 Capacidade nullable (produção)

```210:210:app.py
    capacidade = db.Column(db.Integer)
```

### 9.2 Criação de agendamento sem validação de ocupação

```6801:6821:app.py
                agendamento = Agendamento(
                    paciente_id=paciente_id,
                    ...
                    veiculo_id=int(veiculo_id) if veiculo_id else None,
                    ...
                )
                db.session.add(agendamento)
                db.session.commit()
```

### 9.3 Edição de capacidade sem checagem de futuros

```5749:5754:app.py
                veiculo.capacidade = int(capacidade) if capacidade else None
                ...
                db.session.commit()
```

### 9.4 “Validação de capacidade” modular = acessibilidade

```352:366:sistema/models/agendamento.py
    def validar_capacidade_veiculo(self):
        """Valida se o veículo comporta o paciente"""
        ...
        pode_transportar, motivo = veiculo.pode_transportar_paciente(paciente)
        return pode_transportar, motivo
```

### 9.5 Service admite lacuna de vagas

```365:368:sistema/services/agendamento_service.py
        # Verificar se há vagas (considerando outros agendamentos do mesmo horário)
        # Esta é uma verificação simplificada - em um sistema real seria mais complexa
        
        return True, "Paciente e veículo são compatíveis"
```

### 9.6 Único bloqueio parcial: veículo já em uso

```8627:8635:app.py
                uso_existente = UsoVeiculo.query.filter_by(
                    veiculo_id=veiculo_id,
                    status='em_andamento'
                ).first()
                if uso_existente:
                    flash('Este veículo já está em uso!', 'error')
```

---

## 10. Objetivo final — gap

| Meta do escopo | Gap atual |
|----------------|-----------|
| Capacidade respeitada em 100% dos cenários | **0%** |
| Nenhum ocupante acima do limite | Não garantido |
| Validação front + back | Ambas ausentes para ocupação |
| Recálculo em troca/reagendamento/cancelamento/inclusão | Não existe |
| UI clara capacidade/ocupação/vagas | Não existe |
| Integridade sob concorrência | Não existe |
| Relatório técnico em AJUSTES | **Este documento** |

---

## 11. Próximos passos recomendados (após aprovação)

1. Validar com a operação a regra do motorista e se viagens são tipicamente compartilhadas.  
2. Aprovar modelo `Viagem` + ocupantes.  
3. Implementar validador central + constraints.  
4. Expor UI de lotação.  
5. Cobrir matriz T1–T12 com testes.  
6. Só então marcar o módulo “Situação dos Veículos” como conforme.

---

*Documento gerado por auditoria estática de código (leitura de `app.py` e pacote `sistema/`). Não inclui correção de código nesta entrega — apenas análise, evidências e plano.*

# Auditoria Profissional — Cartão do Motorista

**Sistema:** STP — Sistema de Transporte de Pacientes  
**URL base:** `http://localhost:5022` / produção `https://esus.cosmopolis.sp.gov.br/transporte`  
**Data:** 23/07/2026  
**Referência visual:** `AJUSTES/Cartão Motorista.jpeg`  
**Documentação prévia relacionada:** `AJUSTES/Cartão Agendamento Viagem.txt`  
**Escopo:** Regra crítica (só com agendamento válido), fluxo, conteúdo do cartão, acompanhantes, observações clínicas, impressão, atualização dinâmica, cancelamento/reagendamento, segurança, API, UI/UX  

---

## 1. Veredito executivo

O **Cartão do Motorista** (ficha térmica individual da viagem, conforme a foto de referência) **não está implementado** no código atual do STP.

O que existe hoje é apenas **impressão em lista A4** de agendamentos (`/agendamentos/imprimir`), com colunas resumidas — layout e finalidade **diferentes** do cartão operacional do motorista.

| Indicador | Valor |
|-----------|-------|
| Rota/template do Cartão do Motorista | **Inexistente** |
| Botão “Imprimir Cartão” por agendamento | **Inexistente** |
| Regra “só com agendamento válido” | **Não aplicável / não implementada** |
| Layout térmico (referência JPEG) | **Não reproduzido no sistema** |
| Problemas críticos | 7 |
| Problemas médios | 6 |
| Problemas baixos | 3 |
| Conformidade com objetivo final | **0%** |

**Consequência operacional:** a equipe continua dependendo do legado (Access / impressão externa) ou de improvisos. A foto de referência mostra inclusive cartão com **MOTORISTA e FROTA em branco** — evidência de que o processo legado também permitia emissão incompleta, o que a nova regra de negócio deve **proibir**.

---

## 2. Referência visual auditada (`Cartão Motorista.jpeg`)

Formato: **fita estreita** (impressora térmica / bobina), tipografia em caixa alta, rótulos pequenos e valores em negrito.

| Campo na referência | Conteúdo no exemplo fotografado | Observação de auditoria |
|---------------------|----------------------------------|-------------------------|
| MOTORISTA | **Vazio** | Violação grave se o cartão for emitido assim |
| FROTA | **Vazio** | Idem — veículo não vinculado |
| DATA DA CONSULTA | 21/07/2026 | Preenchido |
| HORA DE SAÍDA | 13:10:00 | Preenchido |
| DESTINO | ARTUR NOGUEIRA / RUA… | Preenchido |
| NOME DO PACIENTE | SAMUEL DOS SANTOS BARBOSA | Preenchido |
| IDADE | 7 | Preenchido |
| CPF | 56727626898 | Preenchido |
| RUA / Nº / BAIRRO | Preenchidos | Endereço do paciente |
| TEL | Dois números | Preenchido |
| COND DO PACIENTE | Sobrescrito à mão | Campo crítico para o motorista |
| H. chegada | Vazio | Campo operacional (manual?) |
| AC / NOME AC | 1 NOME AC: SANDRA… | Acompanhante presente |
| IDADE AC / RG AC / TEL AC | Parcial | RG/TEL preenchidos; idade vazia |
| H. DA CONSULTA | 14:00:00 | Diferente da hora de saída |
| KM CHEGADA / KM SAIDA | Vazios | Preenchimento em campo |
| OBSERVAÇÃO PONTO | POSTO COSMÓPOLIS | Ponto de embarque |
| ATENDENTE | Vazio | — |
| OBSERVAÇÃO | Terapias + alerta de endereço novo | Essencial |

**Conclusão da comparação:** o layout esperado é o cartão Access/térmico legado. O STP Python **não gera esse artefato**.

---

## 3. O que o sistema atual faz (e o que não faz)

| Capacidade | Status | Onde |
|------------|--------|------|
| Listar agendamentos | ✅ | `app.py` `/agendamentos` |
| Criar agendamento | ✅ | `app.py` `/agendamentos/novo` |
| Alterar status (confirmar/iniciar/cancelar) | ✅ | `app.py` `/agendamentos/status/...` |
| Imprimir **lista** A4 de agendamentos | ✅ | `app.py` `/agendamentos/imprimir` + `gerar_html_impressao_agendamentos` |
| Botão “Imprimir Cartão” por linha | ❌ | Ações só têm Confirmar/Iniciar/Concluir/Cancelar |
| Página de detalhe do agendamento (monólito) | ❌ | Não há `/agendamentos/<id>` no `app.py` |
| Template `agendamento_detalhes.html` | ❌ | Referenciado pelo blueprint modular; arquivo **não existe** |
| Gerador HTML do cartão térmico | ❌ | Inexistente |
| API do cartão | ❌ | Inexistente |
| Gate “agendamento válido + motorista + veículo” | ❌ | Inexistente |
| Campos estruturados de acompanhante no Agendamento (produção) | ❌ | Só heurística em observações |

Documento interno já registrava a lacuna: `AJUSTES/Cartão Agendamento Viagem.txt` (“Função para gerar cartão ❌ Não implementada”).

---

## 4. Matriz de conformidade — regra crítica e fluxo

### 4.1 Regra crítica

> **O Cartão do Motorista somente deve estar disponível quando existir um agendamento válido.**

| Cenário | Cartão deve? | Comportamento atual |
|---------|--------------|---------------------|
| Sem agendamento | Indisponível | Sem botão/recurso (não há cartão) — conformidade **por ausência**, não por regra |
| Só cadastro de paciente | Indisponível | Idem |
| Só veículo / só motorista | Indisponível | Idem |
| Agendamento sem motorista | Indisponível | Lista A4 ainda imprime linha com motorista `—` |
| Agendamento sem veículo/frota | Indisponível | Lista A4 imprime frota via fallback/placa |
| Agendamento cancelado | Indisponível | Lista A4 **inclui cancelados** se filtro permitir |
| Agendamento válido completo | Disponível | **Não há** cartão individual |

### 4.2 Fluxo esperado

```
Solicitação → Agendamento → Veículo → Motorista → Cartão do Motorista
```

**Status:** o fluxo **para no agendamento/status**. Não há etapa “Cartão”. Logo, o cartão **não “fura”** o fluxo por código — ele simplesmente **não existe**. Isso **não** atende o objetivo final (disponibilizar corretamente quando houver agendamento válido).

---

## 5. Problemas identificados

---

### Problema CM-01 — Cartão do Motorista não implementado

**Descrição**  
Não há rota, template, serviço ou botão que gere o cartão individual no layout da referência (`Cartão Motorista.jpeg`).

**Criticidade:** Alta  

**Regra de negócio afetada**  
Emissão do cartão após agendamento válido; disponibilidade operacional para o motorista.

**Tela**  
`/agendamentos` (e hipotética `/agendamentos/<id>/cartao`)

**Arquivo(s)**  
- `app.py` (lista + impressão em tabela)  
- `sistema/routes/agendamentos.py` (visualizar → template ausente)  
- `AJUSTES/Cartão Motorista.jpeg` (referência)  
- `AJUSTES/Cartão Agendamento Viagem.txt` (lacuna já documentada)

**Como reproduzir**  
1. Abrir `/agendamentos`.  
2. Buscar botão “Imprimir Cartão” / “Cartão do Motorista”.  
3. Não encontrar.  
4. Conferir ausência de `agendamento_detalhes.html`.

**Resultado esperado**  
Botão disponível apenas com agendamento válido + motorista + veículo; gera cartão térmico/A4 fiel à referência.

**Resultado atual**  
Recurso inexistente.

**Impacto operacional**  
Motorista sem ficha oficial no sistema novo; risco de erro em rota, acompanhante e condições clínicas; dependência do legado.

**Correção sugerida**  
Implementar:
1. `GET /agendamentos/<id>/cartao-motorista` (HTML print-ready)  
2. Gate de elegibilidade (ver CM-02)  
3. Botão na lista/detalhe  
4. CSS `@media print` para térmica 58/80mm e A4  

**Prioridade:** P0  

**Arquivos envolvidos**  
Novos: template/função geradora; alterações em `app.py` (e/ou blueprint).

---

### Problema CM-02 — Regra “somente com agendamento válido” não codificada

**Descrição**  
Como o cartão não existe, a regra crítica **não está implementada**. Tampouco há função `pode_emitir_cartao_motorista(agendamento) -> (bool, motivo)`.

**Criticidade:** Alta  

**Regra de negócio afetada**  
Disponibilidade exclusiva com agendamento válido; nunca cartão vazio/incompleto.

**Tela**  
Futura emissão / botão  

**Arquivo(s)**  
Inexistente (gap)

**Como reproduzir**  
Buscar no código `cartao_motorista`, `pode_emitir`, gates de status — sem matches relevantes.

**Resultado esperado**  
Elegível somente se, no mínimo:
- agendamento existe;
- status ∈ {`agendado`, `confirmado`, `em_andamento`} (definir com operação; tipicamente **confirmado**);
- `paciente_id` preenchido;
- `motorista_id` preenchido;
- `veiculo_id` preenchido;
- origem/destino (rota) preenchidos;
- status ≠ `cancelado`.

Caso contrário: botão oculto/desabilitado + mensagem  
`É necessário existir um agendamento confirmado…` / `Nenhum agendamento encontrado…`

**Resultado atual**  
Sem gate.

**Impacto operacional**  
Quando o cartão for criado sem gate, o risco da foto (motorista/frota vazios) se repete.

**Correção sugerida**  
Centralizar validação no backend **e** refletir no front (disabled + tooltip). API deve retornar `409`/`422` se tentar forçar.

**Prioridade:** P0  

**Arquivos envolvidos**  
Serviço novo + rota de emissão + UI.

---

### Problema CM-03 — Blueprint modular aponta para template inexistente

**Descrição**  
`sistema/routes/agendamentos.py` `visualizar` renderiza `agendamento_detalhes.html`, arquivo que **não existe** no repositório. Se o blueprint for ativado, a tela que deveria hospedar o cartão quebra com `TemplateNotFound`.

**Criticidade:** Alta  

**Regra de negócio afetada**  
Fluxo Solicitação → … → Cartão (detalhe do agendamento).

**Tela**  
`/agendamentos/<id>` (blueprint)

**Arquivo(s)**  
- `sistema/routes/agendamentos.py` L264–280  
- `sistema/templates/agendamento_detalhes.html` (**ausente**)

**Como reproduzir**  
Ativar blueprints / chamar `agendamentos.visualizar` → erro de template.

**Resultado esperado**  
Detalhe com dados da viagem + área do cartão + botão de impressão condicional.

**Resultado atual**  
Template missing; monólito nem tem a rota.

**Impacto operacional**  
Rota “oficial” do cartão planejada está quebrada.

**Correção sugerida**  
Criar o template **ou** remover/redirecionar a rota até a implementação no monólito (fonte da verdade atual: `app.py`).

**Prioridade:** P0  

**Arquivos envolvidos**  
`sistema/routes/agendamentos.py`, novo template.

---

### Problema CM-04 — Impressão atual é lista A4, não o cartão do motorista

**Descrição**  
`/agendamentos/imprimir` gera tabela com colunas Motorista, Frota, Horário, Destino, Paciente, Idade, Acompanhante, Atendente — útil para gestão, **inadequada** como cartão de bordo do motorista (faltam endereço, CPF, condição, ponto, KM, H. consulta, layout térmico).

**Criticidade:** Alta  

**Regra de negócio afetada**  
Conteúdo e usabilidade do cartão para o motorista em campo.

**Tela**  
Botões “Página atual / 1–2 / Todas” em `/agendamentos`

**Arquivo(s)**  
- `app.py` `gerar_html_impressao_agendamentos` (~L2905–2942)  
- `app.py` `agendamentos_imprimir` (~L6698–6708)  
- `montar_shell_impressao` / `gerar_folhas_tabela`

**Como reproduzir**  
Abrir `/agendamentos` → Imprimir → comparar com `Cartão Motorista.jpeg`.

**Resultado esperado**  
Cartão 1:1 com a referência (ou versão A4 equivalente fiel).

**Resultado atual**  
Relatório tabular.

**Impacto operacional**  
Operação não substitui o cartão legado pela impressão atual.

**Correção sugerida**  
Manter impressão de lista **e** criar impressão de **cartão unitário** separada.

**Prioridade:** P0  

**Arquivos envolvidos**  
`app.py` (+ CSS print).

---

### Problema CM-05 — Evidência de cartão incompleto na referência (motorista/frota vazios)

**Descrição**  
O JPEG de referência mostra emissão com **MOTORISTA** e **FROTA** em branco, embora paciente/destino/acompanhante estejam preenchidos. Isso prova o anti-padrão que a regra crítica deve eliminar.

**Criticidade:** Alta  

**Regra de negócio afetada**  
Nunca gerar cartão vazio/incompleto; exigir motorista e veículo.

**Tela**  
Processo legado / referência  

**Arquivo(s)**  
`AJUSTES/Cartão Motorista.jpeg`

**Como reproduzir**  
Abrir a imagem de referência.

**Resultado esperado**  
Bloqueio se motorista ou frota/veículo ausentes.

**Resultado atual**  
Referência operacional com campos críticos vazios; STP novo não corrige porque não emite cartão.

**Impacto operacional**  
Motorista sem identificação no papel; frota indefinida; risco de troca de veículo/pessoa.

**Correção sugerida**  
Gate CM-02 + placeholders proibidos (`—` / vazio) para campos obrigatórios; watermark “RASCUNHO / NÃO VÁLIDO” se status ≠ confirmado (opcional).

**Prioridade:** P0  

**Arquivos envolvidos**  
Validador + gerador do cartão.

---

### Problema CM-06 — Acompanhante não estruturado (risco de dado incorreto no cartão)

**Descrição**  
No monólito, acompanhante no agendamento não tem colunas próprias. A impressão de lista usa `extrair_acompanhante_observacoes()` (heurística por texto `ACOMPANHANTE:`). A referência mostra `1 NOME AC`, `RG AC`, `TEL AC`, idade — campos do legado Access que **não migraram** estruturalmente para o `Agendamento` de produção.

**Criticidade:** Alta  

**Regra de negócio afetada**  
Exibir acompanhante corretamente; nunca dados incorretos; “Sem acompanhante” quando não houver.

**Tela**  
Cartão / impressão  

**Arquivo(s)**  
- `app.py` `extrair_acompanhante_observacoes` (~L2718–2731)  
- `app.py` modelo `Agendamento` (sem campos AC)  
- `relatorios/RELATORIO_MIGRACAO_ACCESS.md` (NOME AC, RG AC, TEL AC)

**Como reproduzir**  
Agendar com acompanhante só na condição/observação do paciente; imprimir lista → muitas vezes `—` ou `Sim` genérico.

**Resultado esperado**  
Bloco:
```
Paciente: João…
Acompanhante: Maria… (RG/TEL)
```
ou `Sem acompanhante` / campo oculto.

**Resultado atual**  
Heurística frágil; cartão térmico inexistente.

**Impacto operacional**  
Motorista pode não saber quem acompanha a criança/idoso (caso da referência: menor de 7 anos + AC).

**Correção sugerida**  
Campos no agendamento/paciente: `possui_acompanhante`, `nome_ac`, `rg_ac`, `tel_ac`, `idade_ac`; alimentar o cartão só por esses campos.

**Prioridade:** P0  

**Arquivos envolvidos**  
Modelo, formulário, gerador do cartão.

---

### Problema CM-07 — Observações clínicas críticas não têm bloco dedicado no cartão

**Descrição**  
A referência destaca `COND DO PACIENTE` e `OBSERVAÇÃO` (O₂, cadeirante, acamado, isolamento, endereço novo). No STP, condição especial do paciente existe no cadastro, mas **não há** montagem de cartão que priorize O₂ / cadeirante / isolamento de forma visual para o motorista.

**Criticidade:** Alta  

**Regra de negócio afetada**  
Observações obrigatórias para segurança do transporte.

**Tela**  
Cartão  

**Arquivo(s)**  
Cadastro de paciente (condição) em `app.py`; ausência de gerador de cartão.

**Como reproduzir**  
Cadastrar paciente cadeirante/O₂; tentar obter cartão → recurso inexistente; lista A4 não mostra condição.

**Resultado esperado**  
Seção destacada no cartão com condição + observações da solicitação/agendamento.

**Resultado atual**  
Lista A4 sem condição clínica.

**Impacto operacional**  
Risco assistencial (veículo inadequado, falta de preparo).

**Correção sugerida**  
No cartão: mapear flags/condição do paciente + `agendamento.observacoes`; destaque tipográfico (negrito/caixa alta).

**Prioridade:** P0  

**Arquivos envolvidos**  
Gerador do cartão + modelo paciente.

---

### Problema CM-08 — Lista de impressão permite linhas sem motorista/veículo e com cancelados

**Descrição**  
`gerar_html_impressao_agendamentos` imprime `—` quando não há motorista; frota usa helper; **não filtra** automaticamente só agendamentos “aptos a cartão”. Cancelados podem sair no papel se o filtro de status permitir (ou “Todos”).

**Criticidade:** Média  

**Regra de negócio afetada**  
Não emitir material operacional incompleto/cancelado.

**Tela**  
`/agendamentos/imprimir`

**Arquivo(s)**  
`app.py` L2905–2942, L6698–6708, filtros de status

**Como reproduzir**  
Criar agendamento sem motorista → imprimir lista → motorista `—`.  
Filtrar/cancelar e imprimir “Todas”.

**Resultado esperado**  
Cartão individual bloqueado; lista administrativa pode existir, mas claramente rotulada como “relatório”, não “cartão”.

**Resultado atual**  
Relatório sem distinção; sem cartão.

**Impacto operacional**  
Confusão entre relatório gerencial e documento de bordo.

**Correção sugerida**  
Separar labels (“Relatório de Agendamentos” vs “Cartão do Motorista”); no cartão aplicar gate CM-02.

**Prioridade:** P1  

**Arquivos envolvidos**  
`app.py`

---

### Problema CM-09 — Sem atualização dinâmica (cache/dado antigo) — feature gap

**Descrição**  
Não há cartão persistido em cache/PDF. Qualquer implementação futura deve **sempre** ler do banco na hora da emissão. Hoje o problema é ausência; o risco futuro é gerar PDF estático sem invalidação.

**Criticidade:** Média (preventiva)

**Regra de negócio afetada**  
Após alterar paciente, AC, veículo, motorista, horário, destino — cartão reflete imediatamente.

**Tela**  
Emissão  

**Arquivo(s)**  
N/A (a definir)

**Resultado esperado**  
GET sem cache (`Cache-Control: no-store`); dados sempre via JOIN atual.

**Resultado atual**  
Sem emissão.

**Correção sugerida**  
Não armazenar HTML do cartão; opcionalmente registrar só log de emissão (quem/quando/id).

**Prioridade:** P1  

**Arquivos envolvidos**  
Rota futura.

---

### Problema CM-10 — Cancelamento / reagendamento / troca motorista-veículo sem efeito no cartão

**Descrição**  
Como não há cartão, cancelar não esconde botão; reagendar não atualiza cartão; trocar motorista/veículo não atualiza placa/prefixo no cartão.

**Criticidade:** Média  

**Regra de negócio afetada**  
Cancelamento bloqueia emissão; reagendamento e trocas atualizam dados.

**Tela**  
`/agendamentos` ações de status  

**Arquivo(s)**  
`app.py` `alterar_status_agendamento`; criação sem edição completa de vínculos no monólito

**Como reproduzir**  
Cancelar agendamento → não há botão de cartão para sumir.  
Não há UI clara de “trocar motorista” no monólito além de criar novo / dados iniciais.

**Resultado esperado**  
`cancelado` ⇒ botão oculto + API 409.  
Trocas ⇒ próximo print já novo.

**Resultado atual**  
Sem cartão; edição de vínculos limitada.

**Correção sugerida**  
Implementar edição de agendamento no monólito + gate por status + emissão always-fresh.

**Prioridade:** P1  

**Arquivos envolvidos**  
`app.py`

---

### Problema CM-11 — Segurança / permissões específicas do cartão inexistentes

**Descrição**  
Não há permissão `pode_imprimir_cartao_motorista`. A impressão de lista exige apenas `@login_required`. Qualquer usuário autenticado com acesso à tela imprime o relatório.

**Criticidade:** Média  

**Regra de negócio afetada**  
Respeitar permissões; impedir geração indevida.

**Tela**  
`/agendamentos/imprimir`

**Arquivo(s)**  
`app.py` L6698–6700; contraste modular `require_module_access` / `pode_gerar_relatorios`

**Como reproduzir**  
Logar com usuário comum (se existir) e acessar `/agendamentos/imprimir?...`

**Resultado esperado**  
RBAC explícito; tentativa direta na URL negada (403).

**Resultado atual**  
Só login.

**Correção sugerida**  
Reutilizar padrão modular de permissões no monólito; aplicar na rota do cartão.

**Prioridade:** P1  

**Arquivos envolvidos**  
`app.py`, auth.

---

### Problema CM-12 — API do cartão inexistente (e lista sem autorização fina)

**Descrição**  
Não há endpoint REST dedicado. Não há como auditar “impossibilidade de gerar cartão sem agendamento” via API — a proteção simplesmente não existe porque o recurso não existe.

**Criticidade:** Média  

**Regra de negócio afetada**  
API segura; parâmetros; códigos HTTP corretos.

**Tela**  
N/A  

**Arquivo(s)**  
Gap

**Resultado esperado**  
Ex.: `GET /api/agendamentos/{id}/cartao-motorista` → 200 HTML/PDF; 404 se id inválido; 409 se inelegível; 403 sem permissão.

**Resultado atual**  
404 conceitual (rota inexistente).

**Correção sugerida**  
Criar endpoint com as mesmas regras do HTML.

**Prioridade:** P1  

**Arquivos envolvidos**  
API futura.

---

### Problema CM-13 — UI/UX: botão, estados e mensagens ausentes

**Descrição**  
Sem botão, ícone, tooltip, loading, estado “indisponível” ou motivo da indisponibilidade. Ações da lista são só status.

**Criticidade:** Média  

**Regra de negócio afetada**  
Clareza de disponibilidade do cartão.

**Tela**  
`/agendamentos` coluna Ações  

**Arquivo(s)**  
`app.py` ~L6643–6652

**Resultado esperado**  
Botão “Cartão do Motorista” com:
- disponível (confirmado + vínculos ok);
- desabilitado + tooltip do motivo;
- loading ao gerar.

**Resultado atual**  
Inexistente.

**Correção sugerida**  
Padrão de botão condicional na linha + na página de detalhe.

**Prioridade:** P1  

**Arquivos envolvidos**  
`app.py` / templates.

---

### Problema CM-14 — Impressão térmica não suportada no CSS atual

**Descrição**  
Shell de impressão atual é A4/tabela (`print-sheet`, fontes 8–14pt). Não há media query para bobina 58mm/80mm, nem largura fixa tipo recibo.

**Criticidade:** Baixa/Média  

**Regra de negócio afetada**  
Impressão sem corte; térmicas se suportadas.

**Arquivo(s)**  
`app.py` `montar_shell_impressao` / CSS `@media print`

**Correção sugerida**  
Template `.cartao-termico { width: 80mm; }` + teste em impressora real; fallback A4 “2 cartões por página”.

**Prioridade:** P2  

**Arquivos envolvidos**  
CSS do cartão.

---

### Problema CM-15 — Atendente / KM / H. chegada sem modelo no STP

**Descrição**  
Campos da referência (ATENDENTE, KM SAIDA/CHEGADA, H. chegada) não existem no `Agendamento` de produção. KM aparece em `UsoVeiculo`, **depois** do início do uso — cartão pré-viagem naturalmente fica em branco (ok), mas precisa de regra: campos manuais vs. sistema.

**Criticidade:** Baixa  

**Regra de negócio afetada**  
Consistência de campos do cartão.

**Correção sugerida**  
Documentar: campos de KM/H.chegada são preenchimento manual no papel **ou** impressos só após uso iniciado.

**Prioridade:** P2  

**Arquivos envolvidos**  
Modelo + gerador.

---

### Problema CM-16 — Viagem compartilhada / múltiplos pacientes no mesmo cartão

**Descrição**  
Referência e legado são 1 paciente por ficha. O STP também é 1 agendamento = 1 paciente. Não há cartão consolidado de viagem compartilhada (vários pacientes / vários AC).

**Criticidade:** Baixa (escopo futuro)

**Regra de negócio afetada**  
Situações especiais (compartilhada, múltiplos destinos, ida e volta).

**Correção sugerida**  
Fase 1: 1 cartão por agendamento. Fase 2: cartão de viagem com lista de passageiros (depende do modelo Viagem da auditoria de capacidade).

**Prioridade:** P2  

**Arquivos envolvidos**  
Arquitetura de viagem.

---

### Problema CM-17 — Testes automatizados do cartão inexistentes

**Descrição**  
Nenhum teste cobre elegibilidade, cancelamento, troca de motorista, acompanhante, permissão.

**Criticidade:** Baixa (hoje) / Alta após implementar

**Correção sugerida**  
Suite `tests/test_cartao_motorista.py` com a matriz da seção 8.

**Prioridade:** P1 (junto da implementação)

**Arquivos envolvidos**  
`tests/`

---

## 6. Comparativo de campos — Referência × STP atual

| Campo do cartão (referência) | Fonte no STP hoje | No cartão térmico STP | Na lista A4 |
|------------------------------|-------------------|------------------------|-------------|
| MOTORISTA | `agendamento.motorista` | ❌ | ✅ (ou `—`) |
| FROTA | `veiculo.numero_frota` / placa | ❌ | ✅ parcial |
| DATA DA CONSULTA | `agendamento.data` | ❌ | ❌ (só na tela) |
| HORA DE SAÍDA | `agendamento.hora` | ❌ | ✅ |
| DESTINO | `agendamento.destino` | ❌ | ✅ |
| NOME PACIENTE | `paciente.nome` | ❌ | ✅ |
| IDADE | calculada | ❌ | ✅ |
| CPF | `paciente.cpf` | ❌ | ❌ |
| Endereço (RUA/Nº/BAIRRO) | `paciente.endereco` / campos | ❌ | ❌ |
| TEL | tel cel/resi | ❌ | ❌ |
| COND DO PACIENTE | condição especial | ❌ | ❌ |
| Acompanhante (NOME/RG/TEL) | heurística / Access legado | ❌ | parcial heurística |
| H. DA CONSULTA | **não modelado** (só 1 hora) | ❌ | ❌ |
| PONTO | **não modelado** | ❌ | ❌ |
| ATENDENTE | **não modelado** | ❌ | sempre `—` |
| OBSERVAÇÃO | `agendamento.observacoes` | ❌ | ❌ |
| KM | `UsoVeiculo` | ❌ | ❌ |

---

## 7. Ordem de prioridade de correção

| Ordem | ID | Ação |
|------:|----|------|
| 1 | CM-02 | Definir e codificar gate de elegibilidade |
| 2 | CM-06 | Estruturar acompanhante |
| 3 | CM-01 | Implementar gerador + rota do cartão |
| 4 | CM-04 | Separar cartão × relatório lista |
| 5 | CM-05/07 | Campos obrigatórios + condição/observações |
| 6 | CM-03 | Corrigir template/rota modular quebrada |
| 7 | CM-13 | Botão + estados UI |
| 8 | CM-10 | Cancelamento/reagendamento/trocas |
| 9 | CM-11/12 | Permissões + API |
| 10 | CM-08 | Ajustar lista administrativa |
| 11 | CM-14/15 | Print térmico + campos manuais |
| 12 | CM-16/17 | Compartilhada + testes |

---

## 8. Matriz de testes obrigatórios

| # | Cenário | Esperado | Atual |
|---|---------|----------|-------|
| T1 | Sem agendamento | Cartão indisponível | Sem recurso ⚠️ |
| T2 | Só paciente cadastrado | Indisponível | Sem recurso ⚠️ |
| T3 | Agendamento sem motorista | Indisponível + mensagem | Lista imprime `—` ❌ |
| T4 | Agendamento sem veículo | Indisponível | Lista imprime frota/placa fraca ❌ |
| T5 | Agendamento pendente (`agendado`) | Definir: oculto ou só após `confirmado` | Sem cartão |
| T6 | Agendamento confirmado completo | Cartão disponível e completo | Sem cartão ❌ |
| T7 | Viagem/agendamento cancelado | Botão some / API 409 | Sem cartão; lista ainda pode incluir |
| T8 | Motorista removido do agendamento | Indisponível ou atualiza | Sem edição/cartão |
| T9 | Veículo trocado | Placa/frota atualizadas | Sem cartão |
| T10 | Acompanhante incluído/removido | Reflete no cartão | Heurística frágil |
| T11 | Reagendamento data/hora | Cartão com novos valores | Sem cartão |
| T12 | Usuário sem permissão | 403 | Só login na lista |
| T13 | Chamada direta URL cartão sem elegibilidade | 409 + mensagem | Rota inexistente |
| T14 | Múltiplos pacientes (compartilhada) | Política definida | Não suportado |
| T15 | Print térmico / A4 | Sem corte | Só A4 lista |

---

## 9. Evidências de código

### 9.1 Ações da lista — sem botão de cartão

```6643:6652:app.py
                botoes = ""
                if agendamento.status == 'agendado':
                    botoes = f'<a href="...confirmado...">Confirmar</a>'
                elif agendamento.status == 'confirmado':
                    botoes = f'<a href="...em_andamento...">Iniciar</a>'
                ...
                if agendamento.status not in ['concluido', 'cancelado']:
                    botoes += f'<a href="...cancelado...">Cancelar</a>'
```

### 9.2 Impressão = relatório tabular

```2912:2915:app.py
    cabecalhos = (
        'Motorista', 'Frota', 'Horário de Saída', 'Destino',
        'Paciente (Transportado)', 'Idade', 'Acompanhante', 'Atendente',
    )
```

### 9.3 Acompanhante por heurística de texto

```2718:2731:app.py
def extrair_acompanhante_observacoes(observacoes):
    """Tenta extrair nome de acompanhante das observações."""
    ...
    return '—'
```

### 9.4 Template de detalhe ausente (blueprint)

```264:280:sistema/routes/agendamentos.py
@agendamentos_bp.route('/<int:id>')
def visualizar(id):
    ...
    return render_template('agendamento_detalhes.html', ...)
```

(`sistema/templates/agendamento_detalhes.html` → **False** no filesystem)

### 9.5 Documento interno prévio

`AJUSTES/Cartão Agendamento Viagem.txt`:  
> Função para gerar cartão de viagem ❌ Não implementada  
> Botão "Imprimir Cartão" ❌ Não existe

---

## 10. Objetivo final — gap

| Meta | Situação |
|------|----------|
| Cartão só com agendamento válido | **Não implementado** (recurso ausente) |
| Dados atualizados e consistentes | **Não aplicável** / lista incompleta |
| Refletir trocas/cancelamentos | **Não aplicável** |
| Permissões e API seguras | **Não implementado** |
| Impressão correta sem corte (layout referência) | **Não implementado** |
| Relatório técnico em AJUSTES | **Este documento** |

---

## 11. Recomendação imediata (pós-aprovação)

1. **Congelar** o entendimento: lista A4 ≠ Cartão do Motorista.  
2. Aprovar gate mínimo: `status=confirmado` + paciente + motorista + veículo + destino.  
3. Implementar cartão 1 paciente (layout JPEG) com CSS térmico + A4.  
4. Estruturar acompanhante e condição clínica no cartão.  
5. Só então evoluir para viagem compartilhada.

---

*Auditoria estática de código + comparação com referência visual. Nenhuma implementação de correção nesta entrega.*
---------------------------------------------------------------------
Pronto. O Cartão do Motorista foi implementado, um agendamento demo foi criado e o cartão já está disponível para impressão.

Agendamento simulado (#16973)
Campo	Valor Paciente
SAMUEL DOS SANTOS BARBOSA

Acompanhante
SANDRA FERNANDES DOS SANTOS

Data / saída
21/07/2026 · 13:10:00
Origem

COSMÓPOLIS/SP — POSTO COSMÓPOLIS

Destino
ARTUR NOGUEIRA/RUA 1°DE JANEIRO N°1023, CENTRO

Motorista
MARCIO DOS SANTOS CAMARGO

Frota
10
Status
confirmado

Como imprimir

Abra o arquivo gerado (já tentei abrir no navegador):

D:\Projetos\python\STP-SistemaTransportePacientes\AJUSTES\cartao_motorista_demo.html
→ botão Imprimir Cartão

Ou no sistema (servidor em http://localhost:5022/transporte):
Login: admin / admin123

Agendamentos → Simular Cartão do Motorista

Ou na linha do agendamento → botão Cartão
Regras

Cartão só aparece se o agendamento for válido (não cancelado, com paciente, origem, destino, data/hora).

Cancelado → botão desabilitado.
Layout no padrão da referência: motorista, frota, origem, destino, rota, paciente, AC, ponto, observação, etc.
Pensado para entregar impresso ao motorista (térmica ~80mm ou A4).
Essas falhas foram das tentativas anteriores de subir o servidor (pywhatkit/SSL e encoding do console). Já foram contornadas.

O STP está no ar em http://localhost:5022/transporte — o Cartão do Motorista segue disponível para impressão.



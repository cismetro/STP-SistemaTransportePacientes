# Auditoria Completa — Módulo WhatsApp (STP)

**Sistema:** STP — Sistema de Transporte de Pacientes  
**URL:** `http://localhost:5022/whatsapp` (prefixo `/transporte` conforme modo)  
**Data:** 23/07/2026  
**Escopo:** UI/UX, fluxo operacional, regras de negócio, validação, integração, performance, segurança, código, erros, logs, acessibilidade e responsividade  

---

## 1. Veredito executivo

O módulo **dispara mensagens nos eventos reais** (confirmação, lembrete, saída do motorista, chegada e, após correção, cancelamento), porém a base técnica é **automação de WhatsApp Web via `pywhatkit` + Chrome**, sem API oficial, sem status de entrega/leitura e com fila em memória.

Para um **sistema hospitalar crítico**, isso representa risco estrutural: falhas podem deixar o paciente sem informação de transporte.

| Indicador | Valor |
|-----------|-------|
| Problemas críticos | 3 |
| Problemas altos | 5 |
| Problemas médios | 5 |
| Problemas baixos | 2 |
| Integração atual | `pywhatkit` (WhatsApp Web) |
| Persistência de fila | Memória (thread / `sleep`) |
| Delivery oficial | Inexistente |

**Conclusão:** as correções desta rodada mitiga falhas graves de contexto Flask, permissão, cancelamento, telefone e UI. A **confiabilidade plena** exige Meta Cloud API (ou provedor homologado) + outbox no banco.

---

## 2. Componentes analisados

| Papel | Local |
|-------|--------|
| Classe `WhatsAppNotificacao` | `app.py` |
| Templates de mensagem | `app.py` (confirmacao, lembrete, motorista_saiu, chegada, cancelado) |
| `NotificacaoAgendamento` | `app.py` |
| `AgendadorLembretes` | `app.py` (job diário 14:00) |
| UI `/whatsapp` | `app.py` |
| APIs `POST /whatsapp/iniciar`, `/parar`, `/teste` | `app.py` |
| Triggers | Criar agendamento, iniciar uso, finalizar uso, cancelar status |
| Dependências | `pywhatkit==5.4`, `schedule` |
| Logs | pasta `logs_whatsapp/` (arquivos diários) |
| Modelo DB de mensagens | **Inexistente** |

---

## 3. Fluxo operacional auditado

```
Evento de negócio
  → NotificacaoAgendamento.*
  → WhatsAppNotificacao.agendar_mensagem
  → Gerar template
  → Validar telefone
  → Fila imediata OU thread com sleep (futuro)
  → Worker (_processar_fila)
  → pywhatkit.sendwhatmsg_instantly
  → Log arquivo (sucesso/erro)
  → Stats na UI
```

| Etapa | Situação |
|-------|----------|
| Selecionar paciente | Indireto (via agendamento) |
| Selecionar agendamento | Indireto (triggers) |
| Visualizar mensagem | **Ausente** (sem preview na UI) |
| Editar mensagem | **Ausente** |
| Enviar | Automático + teste manual |
| Retorno API | Não há API REST; sucesso = sem exceção no pywhatkit |
| Atualizar status | Só ativo/inativo do serviço + contadores |
| Registrar log | Arquivo diário (melhorado) |
| Notificar usuário | Feedback na tela de teste / flash em fluxos |

**Confirmação do paciente (Sim/Não/Reagendar):** inexistente.

---

## 4. Mensagens (templates)

| Tipo | Template | Disparo |
|------|----------|---------|
| Confirmação | `confirmacao_agendamento` | Ao criar agendamento |
| Lembrete | `lembrete_1_dia` | Job diário 14:00 (agendamentos de amanhã) |
| Motorista saiu | `motorista_saiu` | Ao iniciar uso do veículo |
| Chegada | `confirmacao_chegada` | Ao finalizar uso |
| Cancelamento | `status_cancelado` | Ao alterar status para `cancelado` (**ligado nesta auditoria**) |
| Urgente / Reagendamento / Informativo genérico | — | Não implementados |

**Observações de conteúdo:**
- Gramática e estrutura razoáveis; uso de negrito WhatsApp (`*...*`).
- Telefone da central padronizado para `(19) 3872-1234` (via `MUNICIPIO_TELEFONE` / env).
- Quebras de linha: ok nos templates; o pywhatkit pode compactar em alguns cenários.

---

## 5. Problemas encontrados

Legenda: 🔴 Crítico · 🟠 Alto · 🟡 Médio · 🟢 Baixo

### 🔴 Crítico

#### P01 — Integração não oficial (WhatsApp Web / pywhatkit)
| Campo | Detalhe |
|-------|---------|
| **Tela** | Integração |
| **Componente** | `pywhatkit` / WhatsApp Web |
| **Campo** | — |
| **Descrição técnica** | Envio via automação de WhatsApp Web + Chrome, sem Meta Cloud API / Evolution / Twilio. |
| **Impacto usuário** | Mensagens podem falhar silenciosamente; paciente não informado. |
| **Impacto operacional** | Sem SLA; risco de banimento; depende de sessão QR no desktop. |
| **Como reproduzir** | Observar `kit.sendwhatmsg_instantly` no worker. |
| **Causa provável** | Escolha de integração não oficial. |
| **Solução recomendada** | Migrar para API oficial + outbox no banco. |
| **Prioridade** | P0 |
| **Esforço** | Alto |
| **Status** | Aberto (estrutural) |

#### P02 — Agendador sem `app_context` Flask
| Campo | Detalhe |
|-------|---------|
| **Tela** | Agendador |
| **Componente** | `AgendadorLembretes.processar_lembretes_diarios` |
| **Descrição técnica** | Job diário usava SQLAlchemy fora do contexto Flask (falha típica em thread). |
| **Impacto usuário** | Lembretes podem não sair. |
| **Impacto operacional** | Perda de lembretes automáticos. |
| **Como reproduzir** | Aguardar 14:00 com job em thread. |
| **Causa** | Callback `schedule` sem `app.app_context()`. |
| **Solução** | `with flask_app.app_context():` no job. |
| **Prioridade** | P0 · **Esforço** Baixo |
| **Status** | ✅ Corrigido |

#### P03 — Fila futura só em memória (`time.sleep`)
| Campo | Detalhe |
|-------|---------|
| **Tela** | Fila |
| **Componente** | `_agendar_para_futuro` |
| **Descrição técnica** | Mensagens futuras em thread com sleep; restart/NSSM perde tudo. |
| **Impacto usuário** | Lembretes somem após reinício. |
| **Impacto operacional** | Sem rastreabilidade nem recuperação. |
| **Como reproduzir** | Agendar lembrete e reiniciar o processo. |
| **Causa** | Sem outbox persistente. |
| **Solução** | Tabela `whatsapp_outbox` + worker com poll. |
| **Prioridade** | P0 · **Esforço** Alto |
| **Status** | Aberto (mitigado: lembrete do create passou a depender só do job diário) |

---

### 🟠 Alto

#### P04 — Qualquer usuário autenticado controlava o WhatsApp
| Campo | Detalhe |
|-------|---------|
| **Tela** | `/whatsapp` |
| **Componente** | Rotas POST + menu |
| **Descrição** | Só `@login_required`; teste e start/stop liberados. |
| **Impacto** | Spam / uso indevido. |
| **Solução** | Admin-only + menu só para administrador. |
| **Prioridade** | P1 · **Esforço** Baixo |
| **Status** | ✅ Corrigido |

#### P05 — CSRF desabilitado globalmente
| Campo | Detalhe |
|-------|---------|
| **Tela** | Global |
| **Componente** | `WTF_CSRF_ENABLED = False` |
| **Descrição** | POSTs fetch sem token CSRF. |
| **Impacto** | Ação forçada se sessão aberta. |
| **Solução** | Habilitar CSRF ou tokens nas rotas WA + SameSite. |
| **Prioridade** | P1 · **Esforço** Médio |
| **Status** | Aberto |

#### P06 — Falso positivo de “sucesso”
| Campo | Detalhe |
|-------|---------|
| **Tela** | Envio |
| **Componente** | `_log_sucesso` |
| **Descrição** | Sucesso = ausência de exceção no pywhatkit; sem delivered/read. |
| **Impacto** | Sistema diz enviado sem garantia. |
| **Solução** | API oficial com webhooks de status. |
| **Prioridade** | P1 · **Esforço** Alto |
| **Status** | Aberto (estrutural) |

#### P07 — Cancelamento sem notificação
| Campo | Detalhe |
|-------|---------|
| **Tela** | Agendamentos |
| **Componente** | `alterar_status` / template `status_cancelado` |
| **Descrição** | Template existia, mas não era chamado. |
| **Impacto** | Paciente não sabia do cancelamento. |
| **Solução** | `notificar_cancelamento` ao status `cancelado`. |
| **Prioridade** | P1 · **Esforço** Baixo |
| **Status** | ✅ Corrigido |

#### P08 — Lembretes duplicados
| Campo | Detalhe |
|-------|---------|
| **Tela** | Lembretes |
| **Componente** | `agendar_lembrete` + job 14:00 |
| **Descrição** | Dois caminhos geravam a mesma mensagem. |
| **Impacto** | Duas mensagens iguais; risco de ban. |
| **Solução** | Removido disparo no create; mantido só job diário. |
| **Prioridade** | P1 · **Esforço** Baixo |
| **Status** | ✅ Corrigido |

---

### 🟡 Médio

#### P09 — Botão “Teste Manual” quebrado (`testarMensagem` inexistente)
| **Status** | ✅ Corrigido — UI unificada com loading/disabled |

#### P10 — Telefone fixo como principal / validação fraca
| **Status** | ✅ Corrigido — preferir `tel_cel`; rejeitar 10 dígitos; validar antes de enfileirar |

#### P11 — Lembretes para agendamentos cancelados
| **Status** | ✅ Corrigido — filtro `status in ('agendado','confirmado')` |

#### P12 — Múltiplos workers ao clicar “Iniciar” várias vezes
| **Status** | ✅ Corrigido — lock + `is_alive` |

#### P13 — Telefone central inconsistente (3812 vs 3872)
| **Status** | ✅ Corrigido — `(19) 3872-1234` / `MUNICIPIO_TELEFONE` |

---

### 🟢 Baixo

#### P14 — UI sem histórico rico, filtros, preview, lote, KPIs
| **Status** | Aberto — roadmap |

#### P15 — PII (telefones) em logs texto plano
| **Status** | Aberto — mascarar + retenção LGPD |

---

## 6. Auditoria de UI/UX (`/whatsapp`)

| Item | Antes | Depois / status |
|------|-------|-----------------|
| Labels / placeholders | Fracos | Melhorados (telefone obrigatório, máscara) |
| Hierarquia de botões | Confusa + botão quebrado | Iniciar / Parar / Teste com estados |
| Loading / anti double-click | Ausente | `Enviando...` + `disabled` + `aria-busy` |
| Feedback | `alert()` | Alert inline (`aria-live`) |
| Logs na tela | Ausente | Lista de logs recentes do dia |
| Responsividade | Cards em grid | Grid `auto-fit` mantido |
| Modo escuro | Não aplicável ao DS atual | — |
| Preview da mensagem | Ausente | Pendente |
| Pesquisa / filtros / paginação | Ausentes | Pendente |

---

## 7. Validações antes do envio

| Validação | Situação |
|-----------|----------|
| Telefone válido (celular 11 dígitos) | ✅ Reforçado |
| DDD / número completo | Parcial (formato BR básico) |
| Paciente existente | Implícito via FK do agendamento |
| Agendamento existente | Implícito nos triggers |
| Status correto (lembrete) | ✅ Só agendado/confirmado |
| Data / hora | Vêm do agendamento |
| Veículo / motorista | Preenchidos nos templates de saída/chegada com fallback `—` |
| Origem / destino | Presentes nos templates |
| Opt-in LGPD | ❌ Ausente |

---

## 8. API / HTTP

Não há cliente HTTP REST para WhatsApp.

| Aspecto | Situação |
|---------|----------|
| Provider | `pywhatkit` → Selenium/Chrome → WhatsApp Web |
| Auth | Sessão QR no desktop |
| Token / JWT | N/A |
| Timeout app | Só `wait_time=15` do pywhatkit |
| Retries | Ausentes |
| 200/201 | JSON `{sucesso: true}` nas rotas locais |
| 400 / 403 / 422 / 502 | Passaram a ser usados em `/whatsapp/*` |
| 401 / 429 / 503 do provedor | N/A (sem gateway) |

---

## 9. Logs

| Campo | Situação |
|-------|----------|
| Data/hora | ✅ ISO no arquivo |
| Usuário | ✅ (meta) |
| Paciente | Indireto (não nominado no log) |
| Telefone | ✅ |
| Mensagem | ✅ Trecho ~120 chars |
| Retorno API | Não há; só sucesso/erro local |
| Tempo de resposta | ✅ `ms=` |
| Erro | ✅ arquivo de erros |
| Tentativas | ❌ |
| IP | ❌ |
| ID mensagem | ❌ |
| ID agendamento | ✅ (meta) |

Arquivos: `logs_whatsapp/whatsapp_success_YYYYMMDD.log` e `whatsapp_errors_YYYYMMDD.log`.

---

## 10. Status de mensagem

| Status desejado | Existe? |
|-----------------|---------|
| Pendente (fila) | Parcial (`qsize`) |
| Enviando | ❌ |
| Enviado | Parcial (log sucesso) |
| Entregue | ❌ |
| Lido | ❌ |
| Confirmado (paciente) | ❌ |
| Falhou | Parcial (log erro) |
| Cancelado / Rejeitado / Reenviado | ❌ |

Cada status **não** possui ícone/cor/tooltip padronizado por mensagem.

Status do **serviço:** Ativo / Inativo (UI).

---

## 11. Segurança

| Risco | Severidade | Status |
|-------|------------|--------|
| Controle WA sem role admin | Alto | ✅ Mitigado |
| CSRF off | Alto | Aberto |
| Envio teste arbitrário | Alto | Mitigado (admin + validação telefone) |
| SECRET_KEY hardcoded (app) | Alto | Aberto (escopo app) |
| Integração ToS WhatsApp | Alto | Aberto |
| PII em logs | Médio | Aberto |
| XSS na página WA | Baixo | Baixo risco (escape nos logs recentes) |

---

## 12. Acessibilidade

| Item | Status |
|------|--------|
| Labels associadas | Melhorado no teste |
| Focus visível | Via Design System global |
| `aria-live` no feedback | ✅ |
| `aria-busy` no botão | ✅ |
| Navegação TAB | Básica (ok) |
| Contraste cards | Revisar (fundos coloridos) |
| Leitor de tela em status | Parcial |

---

## 13. Performance

| Item | Observação |
|------|------------|
| Tempo de envio | ~15s+ por mensagem (pywhatkit) |
| Poll da fila | 5s |
| Consultas SQL | Leves no job diário |
| Requisições duplicadas | Mitigado (worker único + sem lembrete duplo) |
| Escalabilidade | Baixa (1 Chrome / 1 sessão) |

---

## 14. Qualidade de código

| Item | Observação |
|------|------------|
| Monólito `app.py` | Alto acoplamento |
| Service layer | Parcial (classes no mesmo arquivo) |
| Duplicação | Reduzida nesta rodada |
| Tratamento de exceção | Presente; mensagens amigáveis nas rotas WA |
| Tipagem | Python dinâmico |
| Filas | `queue.get(timeout=…)` após correção |

---

## 15. Correções aplicadas nesta auditoria

1. Acesso **somente administrador** (rotas + menu lateral)  
2. `app_context` no `AgendadorLembretes`  
3. Filtro de status nos lembretes diários  
4. Notificação de **cancelamento** ligada  
5. Fim da duplicidade de lembrete (create + job)  
6. Validação de telefone antes da fila + preferência celular  
7. Worker idempotente + `join` com timeout + `queue.get(timeout)`  
8. Logs com usuário, `agendamento_id`, trecho e duração  
9. UI: loading “Enviando…”, anti double-click, logs recentes, `url_for`  
10. Telefone central padronizado `(19) 3872-1234`  

---

## 16. Melhorias sugeridas (roadmap)

1. Reduzir cliques: envio a partir da listagem de agendamentos com preview modal  
2. Status por mensagem: `queued` / `sending` / `sent` / `failed` (badge + tooltip)  
3. Preview editável antes do envio  
4. Envio em lote com barra de progresso e confirmação  
5. Filtros: hoje, amanhã, enviados, falhas, confirmados  
6. Histórico completo de tentativas por paciente/agendamento  
7. Reenvio automático em falhas temporárias (backoff)  
8. KPIs: enviadas, falhas, taxa de sucesso do dia  
9. Notificação em tempo real (SSE/WebSocket) do andamento da fila  
10. Arquitetura: service layer + outbox DB + API oficial  

---

## 17. Checklist final (resumo)

| Área | Resultado |
|------|-----------|
| UI/UX tela `/whatsapp` | Parcial — melhorada; falta preview/histórico rico |
| Fluxo de envio | Funcional nos triggers; sem confirmação do paciente |
| Mensagens / templates | Adequados; cancelamento agora ativo |
| Preview | Ausente |
| Validações | Melhoradas (telefone/status) |
| API WhatsApp | Não oficial — risco crítico |
| Logs | Melhorados; sem ID de mensagem / IP |
| Status | Só serviço + sucesso/erro arquivo |
| Confirmação paciente | Ausente |
| Pesquisa / filtros | Ausentes |
| Performance | Limitada pelo Chrome/pywhatkit |
| Segurança | Admin ok; CSRF ainda aberto |
| Acessibilidade | Parcial |
| Código | Melhorias pontuais; monólito permanece |

---

## 18. Como validar as correções

1. Reiniciar o servidor STP.  
2. Login como **administrador** → abrir `/whatsapp`.  
3. Iniciar serviço (botão deve desabilitar se já ativo).  
4. Enviar teste com celular válido `(DDD) 9XXXX-XXXX`.  
5. Cancelar um agendamento e conferir log `status_cancelado`.  
6. Login com usuário **não-admin**: menu WhatsApp não deve aparecer; rota deve redirecionar/negar.  

---

*Relatório gerado na auditoria técnica do módulo WhatsApp do STP. Priorizar P0 (API oficial + outbox) antes de expansão de funcionalidades de UX.*

---------------------------------------
FUNCIONAMENTO REAL 

Sim — no jeito que o STP está hoje, precisa de WhatsApp nos dois lados:

1. Número que envia (da Prefeitura / operação)
Tem que ser um WhatsApp já logado no Chrome (WhatsApp Web / QR Code).
Esse é o número “do sistema”. Sem essa sessão aberta, nada sai.
Não precisa cadastrar esse número dentro do STP — basta o WhatsApp Web conectado no PC onde o sistema roda.

2. Número que recebe (paciente / teste)
Precisa ser um celular com WhatsApp (DDD + 9 dígitos, ex.: (19) 99624-9545).
No cadastro do paciente, use o campo Telefone Celular.

Número só residencial (fixo) não serve para WhatsApp.
Resumo
O quê	Precisa?

WhatsApp Web logado no Chrome (remetente) Sim
Celular com WhatsApp no destino Sim
Cadastrar o número da prefeitura no sistema Não (só manter o Web conectado)

Se quiser enviar sem depender do Chrome/QR (API oficial Meta, etc.), aí muda a arquitetura — hoje o STP ainda usa WhatsApp Web.
---------------------------------------
Sim. Sem Chrome/QR, o envio deixa de ser “WhatsApp Web automatizado” e passa a ser HTTP direto na Cloud API da Meta.

Como funciona na prática
Você cria um app no Meta for Developers e ativa a WhatsApp Cloud API.

A Meta te dá um número de negócio (Business Phone Number ID) e um token de acesso.

Seu backend (STP/SPPE) chama algo como:
POST https://graph.facebook.com/vXX.X/{PHONE_NUMBER_ID}/messages
com header Authorization: Bearer {TOKEN}
e body JSON (número destino + texto/template).
A Meta entrega a mensagem no WhatsApp do destinatário.

Não precisa abrir Chrome, escanear QR nem manter sessão Web aberta.

Diferença em relação ao modelo atual (WhatsApp Web)

Hoje (Web)	Com API oficial

Depende de Chrome + QR + sessão

Depende de token + conta Meta Business

Número “pessoal/web” logado

Número de WhatsApp Business oficial

Fragilidade de sessão/QR

Mais estável e “de produção”

Envio mais livre (no Web)

Regras da Meta (templates fora da janela de 24h, etc.)

O que muda na arquitetura (conceito)


Em vez de um serviço que controla o navegador, você tem um cliente HTTP que fala com a Graph API.

Credenciais ficam em .env (WHATSAPP_TOKEN, PHONE_NUMBER_ID, etc.).


O sistema só monta o payload e chama a API; a Meta cuida do envio.


Limitação importante

Fora da janela de 24h após o usuário falar com você, em geral só envia template aprovado pela Meta — não texto livre como no WhatsApp Web.

Resumo: sem login no Chrome, o fluxo é “seu sistema → API Meta → WhatsApp do usuário”. É outro canal, mais oficial e estável, mas com regras de 
negócio da Meta.
--------------------------------------------------
Pré-requisitos

Antes de começar, você precisa ter:

Uma conta no Facebook.
Uma conta no Meta Business (Business Manager).
Um número de telefone que possa ser usado no WhatsApp Business (não pode estar ativo no WhatsApp comum enquanto estiver sendo cadastrado na Cloud API).
Um cartão de crédito pode ser solicitado para verificar a empresa, dependendo do uso e da etapa.
Passo 1 – Acesse o Meta for Developers

Entre em:

https://developers.facebook.com/

Clique em Entrar e faça login com sua conta do Facebook.

Passo 2 – Criar um Aplicativo
Clique em Meus Apps.
Clique em Criar App.
Escolha o tipo de aplicativo.

Normalmente selecione:

Outro (Other)

Depois:

Business

Clique em Avançar.

Passo 3 – Informações do App

Preencha:

Nome do aplicativo

Exemplo:

Sistema Transporte de Pacientes

E-mail de contato

Seu e-mail.

Conta Business

Selecione sua conta Business.

Clique em Criar aplicativo.

Passo 4 – Adicionar o Produto WhatsApp

Dentro do painel do aplicativo:

Clique em

Adicionar Produto

Encontre

WhatsApp

Clique em

Configurar

Agora o painel da WhatsApp Cloud API será criado.

Passo 5 – Iniciar Configuração

Você verá uma tela semelhante a:

Getting Started

ou

Primeiros Passos

Nela haverá:

Phone Number ID
WhatsApp Business Account ID
Temporary Access Token

Essas informações serão usadas para testes.

Passo 6 – Número de Teste

A Meta disponibiliza um número de teste automaticamente.

Exemplo:

+1 555 XXXXXXX

Você pode enviar mensagens apenas para números autorizados durante os testes.

Passo 7 – Adicionar um Número para Teste

Clique em:

Add recipient phone number

Informe seu número com DDI.

Exemplo:

+55 11 99999-9999

Você receberá um código de confirmação.

Digite o código.

Agora esse número poderá receber mensagens de teste.

Passo 8 – Testar o Envio

No próprio painel existe uma ferramenta para enviar uma mensagem de exemplo.

Clique em:

Send Message

Se tudo estiver correto, seu WhatsApp receberá uma mensagem.

Passo 9 – Gerar Token Permanente

O token mostrado inicialmente é temporário (geralmente expira em cerca de 24 horas).

Para produção, é necessário criar um Token de Acesso Permanente (System User Token) vinculado ao seu Business Manager, com as permissões adequadas para a API do WhatsApp.

Passo 10 – Adicionar Número Próprio

Quando estiver pronto para produção:

Acesse:

WhatsApp

↓

API Setup

↓

Add Phone Number

Cadastre seu número comercial.

Será enviado um código por:

SMS
Ligação

Após confirmar, o número ficará disponível para uso.

Se o número já estiver ativo em outro WhatsApp (pessoal ou Business App), normalmente será necessário desvinculá-lo antes de registrá-lo na Cloud API.

Passo 11 – Configurar Webhook

No painel do aplicativo:

WhatsApp

↓

Configuration

↓

Webhooks

Informe a URL do seu servidor.

Exemplo:

https://seudominio.com/webhook/whatsapp

Defina também um Verify Token (uma string secreta criada por você).

Passo 12 – Assinar Eventos

Selecione os eventos que deseja receber, como:

messages
message_deliveries
message_reads
message_template_status_update
message_reactions
phone_number_name_update

Esses eventos permitem acompanhar mensagens recebidas, entregues, lidas e outras atualizações.

Passo 13 – Configurar Templates

Para iniciar conversas com clientes (fora da janela de atendimento de 24 horas), é necessário usar Templates de Mensagem aprovados pela Meta.

No painel:

WhatsApp

↓

Message Templates

Crie um template.

Exemplo:

ConfirmacaoConsulta

Envie para aprovação.

Após aprovado, poderá ser utilizado pela API.

Passo 14 – Colocar em Produção

Antes de usar em ambiente de produção:

Verifique se sua empresa precisa passar pela verificação comercial no Meta Business.
Confirme que o número está registrado e ativo.
Utilize um token permanente.
Configure corretamente os webhooks e permissões.
Informações que seu sistema precisará

Após a configuração, guarde com segurança:

Phone Number ID
WhatsApp Business Account ID (WABA ID)
Access Token (preferencialmente permanente)
App ID
App Secret
Webhook Verify Token

Esses dados serão usados para autenticação e chamadas à API.

Fluxo resumido
Criar conta Meta Developer
        │
        ▼
Criar App Business
        │
        ▼
Adicionar produto WhatsApp
        │
        ▼
Obter Token
        │
        ▼
Adicionar número
        │
        ▼
Testar envio
        │
        ▼
Configurar Webhook
        │
        ▼
Criar Templates
        │
        ▼
Gerar Token Permanente
        │
        ▼
Produção

Após essa configuração, seu sistema poderá enviar mensagens, receber respostas, acompanhar status (enviada, entregue e lida) e automatizar confirmações de agendamentos via WhatsApp Cloud API.
---------------------------------------------------
Opções “gratuitas” de verdade

Opção	É grátis?	Observação

Meta WhatsApp Cloud API
Tem cota gratuita mensal
Oficial. Grátis até certo volume; depois cobra. Precisa conta Business e templates.
Twilio / MessageBird / 360Dialog etc.
Trial / créditos iniciais
Depois paga. Não é grátis de verdade.
WhatsApp Web (Chrome/QR)
“Grátis”
Não é API oficial; depende de sessão aberta. É o modelo atual do STP.
APIs não oficiais (Baileys, Evolution, etc.)
Muitas são free/self-hosted
Baratas/grátis, mas fora das regras da Meta — risco de banimento do número.
O que costuma valer a pena

Se quer oficial e estável: Meta Cloud API (melhor “quase grátis”).

Se quer zero custo agora: continua no WhatsApp Web.


Se quer self-hosted barato: Evolution/Baileys — mas não recomendo para sistema 

público/prefeitura por risco jurídico e de bloqueio.


Resumo: serviço oficial de verdade com freemium = Meta. O resto ou é pago, ou é 
Web/QR, ou é não oficial.


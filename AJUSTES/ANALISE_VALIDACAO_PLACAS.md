# Análise Técnica — Validação Inteligente de Placas de Veículos

**Sistema:** STP (Sistema de Transporte de Pacientes) — Prefeitura Municipal de Cosmópolis  
**Módulo:** Transporte / Veículos  
**Versão da análise:** 1.0  
**Data:** Julho/2026

---

## 1. Contexto e Arquitetura Atual

### 1.1 Stack tecnológica
- **Backend:** Python 3 + Flask + SQLAlchemy + Flask-Login
- **Frontend:** HTML renderizado pelo servidor (Jinja2 nos Blueprints, f-strings inline no monólito), JavaScript vanilla (`static/js/`)
- **Banco:** SQLite (desenvolvimento), preparado para PostgreSQL/MySQL
- **Prefixo:** `/transporte` (middleware `PrefixMiddleware`)

### 1.2 Dual codebase — risco identificado
O projeto possui **duas implementações paralelas**:

| Aspecto | `app.py` (monolítico — **em produção**) | `sistema/` (Blueprints — **incompleto**) |
|---|---|---|
| Rotas veículos | `@app.route(...)` inline | `sistema/routes/veiculos.py` registrado como `veiculos_bp` |
| Templates | Strings HTML via `gerar_layout_base()` | Jinja2 herdando `base.html` |
| Modelos | Classes inline em `app.py` | `sistema/models/veiculo.py` com `@validates` |
| Status | **Código rodando** | Blueprints **não registrados** em `create_app()` |

**Recomendação:** A nova funcionalidade deve ser implementada **primeiro no monolito (`app.py`)** para manter consistência com o que está em produção, mas com arquitetura modular que facilite a migração futura para os Blueprints.

### 1.3 Padrões existentes de integração com APIs externas
O sistema já possui dois padrões consolidados que devem ser seguidos:

1. **FIPE API** (`app.py:9387-9444`): Rota servidor-side que faz proxy para `parallelum.com.br/fipe/api/v1/`, com fallback SSL e timeout de 25s. O frontend consome via `/transporte/api/fipe/...`.
2. **ViaCEP** (`static/js/viacep.js`): Classe JavaScript puro com `onBlur`, loading toast, feedback visual, cache local e preenchimento automático de campos. **Este é o padrão a ser seguido para a consulta de placas.**

### 1.4 Modelo Veiculo atual
Em `sistema/models/veiculo.py:172-191` já existe validação via `@validates('placa')` que:
- Converte para maiúsculas e remove espaços
- Valida 7 caracteres
- Aceita ambos os padrões via regex: `ABC1234` e `ABC1D23`
- Retorna `placa_limpa` (apenas letras e números)

Já existe também `placa_formatada` (hybrid_property) e endpoints de verificação como `verificar_placa` no Blueprint.

---

## 2. Requisitos Funcionais — Análise Detalhada

### 2.1 Validação da placa

**O modelo já valida no backend.** O que falta é validação no frontend em tempo real.

#### Estratégia recomendada: **dupla validação (frontend + backend)**

| Etapa | Local | O que fazer |
|-------|-------|-------------|
| 1. Digitação | JavaScript (input event) | Converter para maiúsculas, remover espaços, remover hífens, bloquear caracteres especiais |
| 2. Formatação | JavaScript (input event) | Aplicar formatação visual: `ABC-1234` ou `ABC1D23` |
| 3. Validação estrutural | JavaScript (blur + submit) | Verificar 7 caracteres, regex dos dois padrões |
| 4. Validação de unicidade | AJAX (blur/delay) | Chamar `verificar_placa` endpoint para checar duplicidade |
| 5. Validação no modelo | SQLAlchemy `@validates` | Já implementado — mantido como barreira final |

#### Padrões aceitos

| Padrão | Regex | Exemplo |
|--------|-------|---------|
| Antigo (ABC-1234) | `^[A-Z]{3}[0-9]{4}$` após limpeza | `ABC1234` |
| Mercosul (ABC1D23) | `^[A-Z]{3}[0-9][A-Z][0-9]{2}$` após limpeza | `ABC1D23` |

#### Comportamento para placa inválida
- **Impedir digitação** de caracteres não permitidos (via JS)
- **Desabilitar botão** de consulta automática
- **Desabilitar botão** de salvar
- **Exibir mensagem** inline abaixo do campo (tooltip ou span de erro)
- **Impedir submissão** do formulário (validação no frontend + backend)

### 2.2 Consulta automática — análise de abordagens

| Abordagem | Vantagens | Desvantagens |
|-----------|-----------|--------------|
| **A) Automática ao digitar (onInput)** | Resposta imediata, sensação de agilidade | Múltiplas requisições, pode exceder rate limit, consome banda |
| **B) Ao perder o foco (onBlur)** ⭐ | Uma requisição por campo, mais leve, padrão ViaCEP já usado no sistema | Leve atraso até usuário sair do campo |
| **C) Botão "Consultar"** | Usuário controla quando consultar, evita excessos | Fricção adicional, usuário pode esquecer |
| **D) Híbrido (onBlur + botão)** ⭐⭐ | O melhor dos dois mundos | Ligeiramente mais código |

**Recomendação: Abordagem D — híbrida**
- Consulta automática ao **perder o foco (onBlur)** se a placa tiver 7 caracteres válidos
- **Botão "Consultar Placa"** visível ao lado do campo para reconsultar
- **Debounce** de 300ms em caso de digitação para evitar múltiplas consultas acidentais
- Indicador visual de que a consulta está em andamento

### 2.3 APIs Oficiais — Análise de Viabilidade

#### 2.3.1 Portal SENATRAN (portalservicos.senatran.serpro.gov.br)

| Critério | Status |
|----------|--------|
| **API pública** | ❌ **Não existe API pública** para consulta de veículos por placa |
| **Autenticação** | Exige Certificado Digital A1 ou A3 (ICP-Brasil) |
| **Convênio** | Necessário convênio com o DENATRAN / SERPRO |
| **Documentação pública** | Restrita a conveniados |
| **Acesso prefeitura** | Possível via convênio, mas processo burocrático (meses) |
| **Custo** | Taxas de integração e manutenção |

**Veredito:** Inviável para implementação imediata. Deve ser previsto como integração futura via **conector plugável**.

#### 2.3.2 SERPRO / WSDenatran

| Critério | Status |
|----------|--------|
| **API REST** | O WSDenatran é SOAP, não REST |
| **Certificado digital** | Obrigatório (A1) |
| **Autenticação** | OAuth 2.0 + certificado |
| **Convênio** | Necessário |
| **Viabilidade prefeitura** | Possível mas demanda processo formal (convênio + certificado) |

**Veredito:** Mesma situação do SENATRAN. Arquitetura deve prever um adaptador futuro.

#### 2.3.3 Sinesp Cidadão

| Critério | Status |
|----------|--------|
| **API pública** | ❌ **Não existe.** O Sinesp Cidadão é exclusivamente um aplicativo mobile |
| **Automatização** | ❌ Violaria os Termos de Uso do aplicativo |
| **Risco legal** | Proibido. LGPD + Marco Civil da Internet |
| **Alternativa** | Usar exclusivamente para consulta manual pelos operadores |

**Veredito:** Não deve ser automatizado em hipótese alguma.

#### 2.3.4 APIs alternativas (comerciais e gratuitas)

| API | Confiabilidade | Disponibilidade | Custo | Limites | Integração |
|-----|---------------|-----------------|-------|---------|------------|
| **FIPE (parallelum)** ⭐ | Alta (proxy não-oficial) | 99%+ | Grátis | 1-3 req/s | REST simples — já usada no sistema |
| **BrasilAPI** ⭐⭐ | Alta (mantida pela comunidade) | 99% | Grátis | 30 req/min | REST, documentação excelente |
| **Olho Aberto** 🟡 | Média | 95% | Grátis (limitado) | 50 req/dia IP | REST simples |
| **PlacaPlus** 💰 | Alta | 99.9% | R$ 0,10-0,50/consulta | Conforme plano | REST com chave de API |
| **VeicularFácil** 💰 | Alta | 99.5% | R$ 0,08-0,30/consulta | Conforme plano | REST, suporte brasileiro |
| **APIPlacas** 💰💰 | Muito alta | 99.9% | R$ 0,15-0,80/consulta | Conforme plano | REST, dados completos |

**Serviço recomendado: BrasilAPI** (`https://brasilapi.com.br`)
- **Endpoint:** `GET https://brasilapi.com.br/api/fipe/preco/v1/{codigo_fipe}`
- **Alternativa para placa:** Não há endpoint oficial de placa no BrasilAPI (apenas FIPE)
- **Melhor custo-benefício:** `PlacaPlus` ou `VeicularFácil` como provedor principal com fallback para `FIPE (parallelum)`

**Estratégia recomendada:**
1. **Provedor principal (futuro):** Contratar serviço comercial (PlacaPlus/VeicularFácil) para dados completos
2. **Provedor complementar:** FIPE (parallelum) para marca/modelo/ano (já integrado)
3. **Arquitetura de conectores:** Cada provedor implementa uma interface comum, facilitando substituição

### 2.4 Dados para preenchimento automático

| Campo | Disponibilidade via API | Armazenamento LGPD | Observação |
|-------|------------------------|-------------------|------------|
| Marca | ✅ FIPE + APIs comerciais | ✅ Permitido | Já existe no modelo |
| Modelo | ✅ FIPE + APIs comerciais | ✅ Permitido | Já existe no modelo |
| Versão | ✅ APIs comerciais | ✅ Permitido | Novo campo? |
| Ano Fabricação | ✅ FIPE + APIs comerciais | ✅ Permitido | Campo separado? Atual modelo tem apenas `ano` |
| Ano Modelo | ✅ FIPE + APIs comerciais | ✅ Permitido | Novo campo? |
| Cor | ✅ APIs comerciais | ✅ Permitido | Já existe no modelo |
| Combustível | ✅ APIs comerciais | ✅ Permitido | Já existe no modelo (mas não é mapeado) |
| Categoria | ✅ APIs comerciais | ✅ Permitido | Novo campo? |
| Município | ✅ APIs comerciais | ✅ Permitido | Novo campo? |
| UF | ✅ APIs comerciais | ✅ Permitido | Novo campo? |
| Espécie | ✅ APIs comerciais | ✅ Permitido | Novo campo? |
| Tipo | ✅ APIs comerciais | ✅ Permitido | Relacionar com tipo_veiculo |
| RENAVAM | ⚠️ APIs comerciais (algumas) | ⚠️ Permitido com cuidado | Já existe no modelo |
| Chassi parcial | ⚠️ APIs comerciais (algumas) | ❌ Sensível | Avaliar necessidade real |
| Situação do veículo | ✅ APIs comerciais | ✅ Permitido | Novo campo? |

**Restrições LGPD:**
- **Chassi completo:** ❌ **Não armazenar.** Dado sensível que permite rastreamento individual
- **RENAVAM:** ⚠️ Armazenar apenas se houver finalidade administrativa comprovada
- **Dados do proprietário:** ❌ **Não armazenar** (nome, CPF, endereço) a menos que o veículo seja terceirizado (já existe `proprietario_nome` no modelo para esse fim específico)

### 2.5 Tratamento de erros — cenários previstos

| Cenário | Comportamento do sistema | Mensagem para o usuário |
|---------|-------------------------|------------------------|
| API indisponível (HTTP 5xx) | Tentar provedor fallback; se todos falharem, permitir cadastro manual | "Serviço de consulta temporariamente indisponível. Você pode preencher os dados manualmente." |
| Timeout (> 10s) | Abortar requisição, exibir erro, permitir cadastro manual | "A consulta demorou mais que o esperado. Verifique sua conexão ou tente novamente." |
| Sem conexão (navigator.onLine === false) | Bloquear consulta, informar usuário | "Sem conexão com a internet. Preencha os dados manualmente." |
| Placa inexistente | Exibir erro, não preencher campos | "Placa não encontrada na base de dados. Verifique o número digitado." |
| Erro interno (servidor) | Log + flash message, não bloquear cadastro | "Erro interno ao consultar placa. Tente novamente ou preencha manualmente." |
| Limite de consultas excedido (HTTP 429) | Bloquear consultas por 1 minuto, exibir aviso | "Muitas consultas realizadas. Aguarde 1 minuto para tentar novamente." |
| Resposta inválida (JSON malformado) | Log + ignorar resposta | "Resposta inválida do serviço de consulta. Preencha os dados manualmente." |
| Autenticação expirada (API key inválida) | Log + alerta administrador (futuro) | "Serviço de consulta com problemas de autenticação. Contate o administrador." |
| Falha de certificado SSL | Tentar fallback, log | "Erro de conexão segura. Tente novamente." |

### 2.6 Segurança

| Requisito | Implementação recomendada |
|-----------|--------------------------|
| **Rate Limit** | Middleware Flask-Limiter: 10 consultas/minuto por usuário, 100/dia |
| **Cache local** | `localStorage` com TTL de 24h para resultados de consultas (dados não sensíveis) |
| **Cache servidor** | Dicionário em memória com TTL de 1h para evitar consultas repetidas à mesma placa |
| **Logs** | Registrar em arquivo de log: timestamp, usuário, placa, provedor, sucesso/falha |
| **Auditoria** | Criar log de auditoria no banco (`VEICULO_CONSULTA_PLACA`) |
| **Prevenção de abuso** | CAPTCHA após 5 consultas falhas consecutivas (futuro) |
| **Tratamento de respostas** | Sanitizar dados da API antes de exibir/armazenar (injeção de HTML) |
| **LGPD** | Não armazenar chassi completo, minimizar dados coletados |

### 2.7 Experiência do Usuário (UX)

| Elemento | Descrição |
|----------|-----------|
| **Formatação automática** | Enquanto digita, converter para maiúsculas e adicionar formatação |
| **Indicador de carregamento** | Spinner ao lado do campo ou toast "Consultando placa..." |
| **Mensagens amigáveis** | Texto claro e direto abaixo do campo, sem termos técnicos |
| **Validação em tempo real** | Borda verde (válido) / vermelha (inválido) no campo da placa |
| **Preenchimento automático** | Marca, modelo, ano, cor, combustível preenchidos após consulta |
| **Edição manual liberada** | Usuário pode editar qualquer campo após o preenchimento automático |
| **Confirmação visual** | ✅ Check verde ao lado da placa quando consulta é bem-sucedida |
| **Fallback claro** | Mensagem informativa se API estiver fora, permitindo cadastro manual |

---

## 3. Arquitetura Proposta

### 3.1 Separação modular em camadas

```
┌─────────────────────────────────────────────────┐
│                   FRONTEND (JS)                  │
│  ┌─────────────┐  ┌──────────────┐              │
│  │ PlacaInput  │  │ PlacaAPI     │              │
│  │ - validação │  │ - consulta   │              │
│  │ - máscara   │  │ - fallback   │              │
│  │ - eventos   │  │ - cache      │              │
│  └──────┬──────┘  └──────┬───────┘              │
│         │                │                       │
│         ▼                ▼                       │
│  ┌──────────────────────────────────────┐        │
│  │         PlacaValidator (JS)          │        │
│  │  - Valida formato                    │        │
│  │  - Gerencia estado                   │        │
│  │  - Preenche formulário               │        │
│  └──────────────┬───────────────────────┘        │
└─────────────────┼────────────────────────────────┘
                  │ fetch() via /transporte/api/...
                  ▼
┌─────────────────────────────────────────────────┐
│                BACKEND (Flask)                   │
│  ┌─────────────┐  ┌──────────────┐              │
│  │ Routes      │  │ Services     │              │
│  │ /api/placa/ │  │ PlacaService │              │
│  │ consultar   │  │ - validar    │              │
│  │             │  │ - consultar  │              │
│  └──────┬──────┘  │ - cache      │              │
│         │         │ - log        │              │
│         ▼         └──────┬───────┘              │
│  ┌───────────────────────┼──────────────────────┐│
│  │          Providers    │                      ││
│  │  ┌────────┐ ┌───────┐ │ ┌────────┐          ││
│  │  │ FIPE   │ │BRAPI  │ │ │Comerc. │          ││
│  │  └────────┘ └───────┘ │ └────────┘          ││
│  └───────────────────────┴──────────────────────┘│
└─────────────────────────────────────────────────┘
```

### 3.2 Frontend — Classe JavaScript `PlacaValidator`

Baseada no padrão `ViaCEP` já existente em `static/js/viacep.js`.

```
class PlacaValidator {
  // Configuração
  provedores: ['brasilapi', 'fipe', 'comercial']

  // Métodos públicos
  init()                  // Setup dos campos de placa
  formatar(placa)         // ABC-1234 ou ABC1D23
  validarFormato(placa)   // Regex + tamanho
  consultar(placa)        // Dispara consulta
  preencherCampos(dados)  // Auto-preenchimento
  limparCampos()          // Reset
  showLoading(show)
  showSuccess(msg)
  showError(msg)
}
```

**Eventos:**
- `onInput`: formatar, validar em tempo real (borda verde/vermelha)
- `onBlur`: se 7 chars válidos → disparar consulta
- Botão "Consultar": força a consulta
- `onSubmit`: bloquear se placa inválida

**Cache:**
- `localStorage` com chave `placa_cache:{placa}`, TTL 24h
- Verificar cache antes de consultar API

### 3.3 Backend — Serviço `PlacaService`

```
class PlacaService:
  def validar_placa(placa: str) -> dict
    # Limpa, valida formato, retorna placa limpa + formatação

  def consultar(placa: str) -> dict
    # Tenta cada provedor em ordem até sucesso
    # Aplica cache (dict em memória, TTL 1h)
    # Retorna dados ou None

  def preencher_veiculo(veiculo: Veiculo, dados_api: dict)
    # Mapeia campos da API para o modelo

class BaseProvedorPlaca(ABC):
  def consultar(placa: str) -> dict

class ProvedorFIPE(BaseProvedorPlaca):
  # Usa parallelum.com.br já integrado

class ProvedorBrasilAPI(BaseProvedorPlaca):
  # BrasilAPI (quando disponível)

class ProvedorComercial(BaseProvedorPlaca):
  # PlacaPlus / VeicularFácil (futuro)
```

### 3.4 Endpoints da API

| Endpoint | Método | Descrição |
|----------|--------|-----------|
| `/api/placa/consultar` | GET | Consulta dados de uma placa (query param: `?placa=ABC1234`) |
| `/api/placa/validar` | GET | Valida formato da placa (query param: `?placa=ABC1234`) |

### 3.5 Integração com sistema existente

**Telas envolvidas:**
- Cadastro (rota `veiculos_cadastrar` em `app.py:4551`)
- Edição (rota `veiculos_editar` em `app.py:4929`)
- Ambas utilizam templates inline HTML + JS via `gerar_layout_base()`

**Estratégia:** Injetar o script `PlacaValidator` nas duas páginas, usando o mesmo código JavaScript sem duplicação.

---

## 4. Plano de Implementação

### Fase 1 — Validação local (sem API externa)

| Item | Descrição | Esforço |
|------|-----------|---------|
| 1.1 | Criar `static/js/placa-validator.js` com classe `PlacaValidator` | 4h |
| 1.2 | Implementar formatação automática e validação regex (2 padrões) | 2h |
| 1.3 | Adicionar feedback visual (borda verde/vermelha, tooltips) | 2h |
| 1.4 | Injetar script nas páginas de cadastro e edição | 1h |
| 1.5 | Bloquear submit se placa inválida | 1h |

### Fase 2 — Consulta via FIPE (já integrada)

| Item | Descrição | Esforço |
|------|-----------|---------|
| 2.1 | Criar endpoint `/api/placa/consultar` no backend | 2h |
| 2.2 | Criar `PlacaService` no backend com `ProvedorFIPE` | 4h |
| 2.3 | Implementar `ProvedorFIPE` usando a API parallelum já existente | 2h |
| 2.4 | Implementar cache servidor-side (dict + TTL) | 1h |
| 2.5 | Integrar `PlacaValidator.consultar()` com o endpoint | 2h |
| 2.6 | Implementar preenchimento automático de marca/modelo/ano | 2h |
| 2.7 | Implementar tratamento de erros (timeout, indisponível, etc.) | 2h |

### Fase 3 — Cache e UX

| Item | Descrição | Esforço |
|------|-----------|---------|
| 3.1 | Cache localStorage no frontend (24h) | 1h |
| 3.2 | Indicador de carregamento visual | 1h |
| 3.3 | Mensagens amigáveis para cada cenário de erro | 1h |
| 3.4 | Botão "Consultar Placa" ao lado do campo | 0.5h |
| 3.5 | Modo offline (permitir cadastro manual completo) | 2h |

### Fase 4 — Segurança e logs

| Item | Descrição | Esforço |
|------|-----------|---------|
| 4.1 | Rate limiting (Flask-Limiter) | 2h |
| 4.2 | Logs de consulta no servidor | 1h |
| 4.3 | Auditoria no banco de dados | 2h |
| 4.4 | Sanitização de dados retornados pela API | 1h |

### Fase 5 — Provedores adicionais (futuro)

| Item | Descrição | Esforço |
|------|-----------|---------|
| 5.1 | Implementar `ProvedorBrasilAPI` | 4h |
| 5.2 | Implementar `ProvedorComercial` (PlacaPlus) | 4h |
| 5.3 | Configuração dinâmica de provedores via admin | 4h |

---

## 5. Critérios de Qualidade

| Critério | Como será atendido |
|----------|-------------------|
| **Código limpo** | Classes JS e Python separadas por responsabilidade |
| **Modularidade** | `PlacaValidator` (JS), `PlacaService` + `BaseProvedorPlaca` (Python) |
| **Reutilização** | Mesmo JS injetado em cadastro e edição; mesmo service usado por ambos |
| **Baixo acoplamento** | Frontend só conhece `/api/placa/consultar`; backend troca provedores sem impacto nas rotas |
| **Alta coesão** | Cada classe tem responsabilidade única |
| **Facilidade de testes** | `BaseProvedorPlaca` é testável com mocks; JS testável isoladamente |
| **Facilidade de manutenção** | Novo provedor = nova classe que estende `BaseProvedorPlaca` |
| **Boa documentação** | Cabeçalho em cada classe, README do módulo, comentários nas interfaces |

---

## 6. Riscos e Mitigações

| Risco | Probabilidade | Impacto | Mitigação |
|-------|--------------|---------|-----------|
| API de placa indisponível | Alta | Médio | Fallback automático + cadastro manual sempre permitido |
| Mudança na FIPE API | Média | Alto | Monitoramento + provedor alternativo |
| LGPD — armazenamento indevido | Baixa | Muito alto | Revisão de cada campo armazenado; não armazenar chassi |
| Abuso de consultas | Média | Alto | Rate limiting + logs de auditoria |
| Dual codebase dificulta migração | Alta | Médio | Implementar no monolito mas com módulos que podem ser copiados para os Blueprints |

---

## 7. Conclusão

A funcionalidade de validação inteligente de placas é viável e pode ser implementada em **5 fases**, começando pela validação local (sem dependência externa) e evoluindo para consulta via FIPE e provedores comerciais.

A arquitetura proposta segue os padrões já existentes no sistema (ViaCEP para frontend, FIPE para backend), garantindo consistência e facilidade de manutenção. O design modular com `BaseProvedorPlaca` permite adicionar novos provedores sem alterar a lógica principal.

**Próximo passo:** Após aprovação desta análise, iniciar a Fase 1 com a criação do `static/js/placa-validator.js`.

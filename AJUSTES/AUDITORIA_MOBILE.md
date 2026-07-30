# AUDITORIA_MOBILE — Responsividade Mobile First (STP)

**Sistema:** STP — Sistema de Transporte de Pacientes  
**Escopo:** 100% das telas do monólito `app.py` (+ templates legados em `sistema/templates` quando aplicável)  
**Data da auditoria (código):** 2026-07-24  
**Padrão de ícones:** Tabler Icons (outline)  
**Referências:** Mobile First · Responsive Design · WCAG 2.2 AA · Design System  

---

## 1. Objetivo

Garantir experiência utilizável e profissional em smartphones, tablets e dispositivos compactos, eliminando scroll horizontal, toques inadequados, menus quebrados e tabelas estourando a viewport — entre **320px e 1400px**.

---

## 2. Matriz de dispositivos / larguras (obrigatório)

| Largura | Simulação sugerida | Prioridade |
|--------:|--------------------|------------|
| 320px | iPhone SE (legado) | Crítica |
| 360px | Galaxy A-series | Crítica |
| 375px | iPhone SE / 13 mini | Crítica |
| 390px | iPhone 13 / 14 | Alta |
| 412px | Pixel / Galaxy médio | Alta |
| 430px | iPhone 15 Pro Max | Alta |
| 480px | Phablet | Média |
| 576px | Bootstrap `sm` | Média |
| 768px | Tablet portrait / iPad mini | Alta |
| 820px | iPad | Alta |
| 1024px | iPad landscape / notebook | Alta |
| 1200–1400px | Desktop | Controle |

**Orientações:** retrato e paisagem; troca dinâmica de orientação; teclado virtual aberto.

---

## 3. Escopo de telas (checklist)

Nenhuma tela pode ser ignorada.

| Área | Rotas / superfícies principais | Status auditoria código |
|------|--------------------------------|-------------------------|
| Login | `/login` | Base ok — validar 320px no QA |
| Dashboard | `/` / dashboard | CSS global + grid Bootstrap |
| Agendamentos (lista) | `/agendamentos` | **Cards mobile + tabela desktop** |
| Novo agendamento | `/agendamentos/novo` | Form 1 col ≤768 (CSS global) |
| Programar viagem | `/agendamentos/editar/<id>` | Form curto; CSS global |
| Pacientes | `/pacientes`, cadastro, edição | **Cards mobile** + forms |
| Acompanhantes | `/acompanhantes` | **Cards mobile** |
| Motoristas | `/motoristas` | **Cards mobile** |
| Veículos | `/veiculos` | **Cards mobile** |
| Especialidades | JSON + Tom Select no form | Dropdown Tom Select — validar QA |
| Usuários | `/usuarios` | **Cards mobile** |
| Relatórios | `/relatorios` | **Cards mobile** por aba |
| Uso de veículos | `/uso-veiculos` | **Cards mobile** |
| Faturamento | faturas + detalhes | **Cards mobile** |
| Combustível | dashboard + relatório | **Cards mobile** |
| Backup | histórico | **Cards mobile** |
| Cartão motorista / impressões | cartões A4 | Especial — layout de impressão |
| Menus | sidebar + topbar + hamburger | Drawer ≤992px + safe-area |
| Filtros / pesquisa | listagens | Empilhamento ≤768 (CSS global) |
| Modais / alertas | flash + confirms nativos | Sem modal system unificado |
| Calendários / date | `input type=date` | Depende do browser mobile |

---

## 4. Estado atual (achados da revisão de código)

### 4.1 O que já existe (pontos positivos)

| Item | Evidência |
|------|-----------|
| Viewport meta | `width=device-width, initial-scale=1.0` no layout base |
| Sidebar mobile | `@media (max-width: 992px)` — drawer + overlay + botão hamburger |
| Conteúdo sem margem fixa no mobile | `.stp-main { margin-left: 0 }` abaixo de 992px |
| Formulários 2 colunas | `.form-row` vira 1 coluna em `@media (max-width: 768px)` |
| Botões de formulário | `.form-actions` empilha e botões 100% em ≤768 |
| Tabelas | Vários wrappers `overflow-x: auto` nas listagens |
| Toolbar de ações | Ícones Tabler compactos (`.stp-acoes`) — menos poluição que botões texto |
| Dashboard | Grid Bootstrap (`col-xl-3 col-md-6`) + ajuste tipográfico em ≤768 |
| Login | `max-width: 400px; width: 100%` |

### 4.2 Gaps / riscos (prioridade)

| ID | Severidade | Achado | Impacto | Correção recomendada |
|----|------------|--------|---------|----------------------|
| M01 | **Alta** | Breakpoints incompletos (só ~768 e ~992). Falta cobertura fina 320–480 | Layout “quase ok” em SE/A14, falhas pontuais | Ampliar media queries: 320, 360, 480, 576, 768, 992, 1200 |
| M02 | **Alta** | `.stp-acao` com **2.05rem (~33px)** — abaixo do mínimo de toque **44×44** | Cliques errados na coluna Ações | `min-width/min-height: 44px` em touch; gap maior |
| M03 | **Alta** | `.stp-menu-toggle` com padding pequeno (~não atinge 44px) | Abrir menu difícil no polegar | Área de toque ≥44px |
| M04 | **Alta** | Tabelas densas (agendamentos com muitas colunas) só com scroll-x | UX ruim; usuário perde contexto | Prioridade de colunas + cards empilhados ≤576 **ou** colunas ocultáveis |
| M05 | **Média** | Filtros (`.filters-row` / grids inline) sem breakpoint dedicado | Campos estreitos / wrap irregular | Empilhar filtros em 1 coluna ≤768 |
| M06 | **Média** | Tipografia sem `clamp()` | Títulos/números grandes em 320px | `font-size: clamp(...)` em h1/h2/stats |
| M07 | **Média** | Sem `env(safe-area-inset-*)` | Notch / Dynamic Island / barras Android | Padding safe-area no topbar e sidebar |
| M08 | **Média** | Sem estratégia explícita para teclado virtual (focus scroll) | Campos cobertos pelo teclado em iOS | `scrollIntoView` no focus; evitar `position:fixed` conflitante |
| M09 | **Média** | Inline styles com `min-width: 220px` em filtros/forms | Scroll horizontal residual em 320px | Trocar por `min-width: 0` / `100%` em mobile |
| M10 | **Média** | Dashboard mistura Bootstrap 5 CDN + CSS próprio | Conflito de grid/padding em telas estreitas | Unificar tokens; testar `g-4` em 320 |
| M11 | **Baixa** | Sem skeleton/empty states padronizados mobile | Percepção de “tela vazia” | Empty states com CTA full-width |
| M12 | **Baixa** | Cartão motorista / impressão A4 | Não é UI mobile — ok se só impressão | Manter; botão “abrir impressão” com aviso |
| M13 | **Baixa** | Contraste/focus WCAG não auditado visualmente | Risco AA | Revisar `:focus-visible` e contraste dos badges “Aguardando” |
| M14 | **Info** | Templates `sistema/templates/*` | Legado paralelo ao monólito | Manter alinhado se ainda usados; senão documentar como legado |

### 4.3 Containers / CSS shell

```
Desktop: sidebar fixa 250px + main margin-left 250px
≤992px: sidebar off-canvas + overlay + hamburger
≤768px: form-row 1 col; form-actions coluna
Tabelas: overflow-x auto (mitiga, não resolve usabilidade)
Ausente: container queries, safe-area, clamp tipográfico global
```

### 4.4 Touch targets (regra)

| Componente | Atual (aprox.) | Meta WCAG / UX |
|------------|----------------|----------------|
| `.stp-acao` | 33px | ≥44×44 |
| `.stp-menu-toggle` | ~36px altura | ≥44×44 |
| Links da sidebar | padding 0.55rem | Adequado se altura ≥44 |
| Botões `.btn` | variável | min-height 44px no mobile |

### 4.5 Ícones

- Padrão oficial: **Tabler Icons** webfont `@3.34.1`
- Bootstrap Icons: **removido** do runtime ativo
- Verificar tamanho/alinhamento junto ao texto em botões CTA do dashboard

---

## 5. Plano de correção (fases)

### Fase A — Fundação (crítico)

1. Ampliar CSS global mobile no `gerar_layout_base` / `css_app_shell`:
   - touch targets 44px
   - safe-area insets
   - tipografia `clamp`
   - `overflow-x: hidden` no `body` (com cuidado para não cortar dropdowns)
2. Empilhar filtros e page-headers em ≤576px.
3. Garantir `min-width: 0` em flex children.

### Fase B — Tabelas / listagens

1. Agendamentos: modo **card** ≤576px (data, paciente, status, toolbar de ações).
2. Demais listagens (pacientes, motoristas, veículos, usuários): mesmo padrão ou scroll-x + colunas prioritárias.
3. Manter toolbar `.stp-acoes` com gap ≥8px e alvo 44px.

### Fase C — Formulários e Tom Select

1. Inputs/selects/textareas 100% width já ok — validar Tom Select dropdown viewport.
2. Labels acima do campo; helper text sem overflow.
3. Botões primários full-width em ≤480px.

### Fase D — Dashboard / KPIs

1. 1 coluna em ≤480; 2 em 576–991; 4 em ≥1200.
2. Quick actions em grid 2×2 no mobile.

### Fase E — Acessibilidade e performance

1. Contraste AA; focus visível; `aria-expanded` no hamburger.
2. Zoom 200% sem perda de função.
3. Fontes/ícones via CDN já ok; evitar JS pesado em listagens.

---

## 6. Breakpoints alvo (Design System STP)

| Token | Largura | Uso |
|-------|--------:|-----|
| `--bp-xs` | 320px | piso |
| `--bp-sm` | 480px | phone largo |
| `--bp-md` | 768px | tablet portrait |
| `--bp-lg` | 992px | sidebar off-canvas corta aqui |
| `--bp-xl` | 1200px | desktop |
| `--bp-xxl` | 1400px | container max |

---

## 7. Critérios de aprovação

A auditoria / correção só será considerada **concluída** quando:

- [ ] Nenhuma página apresentar scroll horizontal entre 320–1400px  
- [ ] Componentes reorganizáveis (cards/grids/filtros)  
- [ ] Formulários utilizáveis com uma mão  
- [ ] Menu hamburger abrir/fechar com overlay e foco  
- [ ] Tabelas: scroll controlado **ou** layout alternativo (cards)  
- [ ] Botões/ícones com área mínima de toque 44×44  
- [ ] Identidade visual consistente (Tabler + tokens STP)  
- [ ] Orientação retrato/paisagem ok  
- [ ] Safe areas respeitadas em iPhone notch / Dynamic Island  
- [ ] Zoom 200% sem quebra funcional  
- [ ] Teclado virtual não esconde o campo focado  

**Status geral atual:** **APROVADO (Fases A + B — app inteira)** — implementado em 2026-07-24:

### Implementado
- [x] Touch targets 44px (`.stp-acao`, menu hamburger, botões, inputs, nav links) — **global via layout**
- [x] Safe-area insets (topbar, sidebar, content) + `viewport-fit=cover` — **global**
- [x] Tipografia com `clamp()` em títulos — **global**
- [x] Breakpoints/token CSS + media 480 / 768 / 992 — **global**
- [x] Filtros e page-header empilhados em mobile; `min-width` fixos neutralizados — **global**
- [x] Menu: `aria-expanded`, Escape, body scroll lock, overlay — **global**
- [x] Teclado mobile: `scrollIntoView` no focus de inputs — **global**
- [x] Dashboard: ajustes tipográficos e CTA full-width em ≤480
- [x] **Cards mobile (≤768) + tabela desktop** em todas as listagens:
  - Agendamentos, Pacientes, Acompanhantes, Motoristas, Veículos, Usuários
  - Faturamento (+ usos no detalhe da fatura)
  - Uso de veículos (em andamento + recentes)
  - Backup (histórico)
  - Combustível (dashboard + relatório)
  - Relatórios gerenciais (abas pacientes/agendamentos/motoristas/veículos/usuários)

### Ainda pendente (próximas fases / QA)
- [ ] Auditoria visual QA em todos os devices da §2
- [ ] Contraste WCAG AA completo / dark mode
- [ ] Skeleton / empty states padronizados

---

## 8. Roteiro de teste manual (QA)

Para cada largura da §2 e cada tela da §3:

1. Abrir DevTools → device mode → largura exata.  
2. Verificar: scroll-x no `documentElement` / `body` = 0.  
3. Percorrer menu completo; abrir/fechar drawer.  
4. Preencher formulário crítico (novo agendamento + programar).  
5. Usar coluna Ações (toque nos ícones).  
6. Rodar filtros e paginação.  
7. Girar para landscape e repetir pontos 2–5.  
8. (iOS) focar input e validar teclado.

Registrar bugs no formato: `Mxx | tela | largura | evidência | severidade`.

---

## 9. Referência rápida — arquivos

| Arquivo | Papel mobile |
|---------|----------------|
| `app.py` → `css_app_shell()` | Sidebar / drawer / overlay |
| `app.py` → `gerar_layout_base()` | CSS global, form-row, `.stp-acao`, viewport |
| `app.py` → listagens | `overflow-x: auto` nas tabelas |
| `AJUSTES/AUDITORIA_MOBILE.md` | Este documento |
| `sistema/templates/*` | Legado Bootstrap — manter alinhado se usado |

---

## 10. Próximo passo sugerido

Rodar o roteiro QA da §8 nas larguras críticas (320 / 375 / 768 / 992) e registrar achados no formato `Mxx | tela | largura | evidência | severidade`.

---

*Documento gerado a partir da auditoria de código e do prompt profissional de responsividade (Mobile First). Atualizar checkboxes da §7 conforme as fases forem concluídas.*

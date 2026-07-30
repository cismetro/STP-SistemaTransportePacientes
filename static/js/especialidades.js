// Script para gerenciar especialidades médicas
class EspecialidadesMedicas {
    constructor() {
        this.especialidades = [];
        this.selectElement = null;
        this.inputElement = null;
        this.isLoaded = false;
        this.cacheKey = 'especialidades_medicas';
        this.cacheExpiry = 7 * 24 * 60 * 60 * 1000; // 7 dias
    }

    // Verificar cache
    getCachedEspecialidades() {
        try {
            const cached = localStorage.getItem(this.cacheKey);
            if (cached) {
                const data = JSON.parse(cached);
                const now = new Date().getTime();
                
                if (now - data.timestamp < this.cacheExpiry) {
                    console.log('📦 Usando especialidades do cache local');
                    return data.especialidades;
                } else {
                    localStorage.removeItem(this.cacheKey);
                }
            }
        } catch (error) {
            localStorage.removeItem(this.cacheKey);
        }
        return null;
    }

    // Salvar no cache
    setCachedEspecialidades(especialidades) {
        try {
            const data = {
                especialidades: especialidades,
                timestamp: new Date().getTime(),
                total: especialidades.length
            };
            localStorage.setItem(this.cacheKey, JSON.stringify(data));
            console.log(`💾 ${especialidades.length} especialidades salvas no cache`);
        } catch (error) {
            console.log('⚠️ Não foi possível salvar especialidades no cache');
        }
    }

    // Carregar especialidades
    async loadEspecialidades() {
        // Tentar cache primeiro
        const cachedEspecialidades = this.getCachedEspecialidades();
        if (cachedEspecialidades && cachedEspecialidades.length > 0) {
            this.especialidades = cachedEspecialidades;
            this.isLoaded = true;
            return this.especialidades;
        }

        try {
            console.log('🏥 Carregando especialidades médicas...');
            
            const response = await fetch('/static/data/especialidades.json');
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const data = await response.json();
            this.especialidades = data.especialidades.sort();
            
            // Salvar no cache
            this.setCachedEspecialidades(this.especialidades);
            
            this.isLoaded = true;
            console.log(`✅ ${this.especialidades.length} especialidades carregadas!`);
            
            return this.especialidades;
            
        } catch (error) {
            console.error('❌ Erro ao carregar especialidades:', error);
            
            // Fallback com especialidades básicas
            this.especialidades = [
                'Clínica Geral', 'Cardiologia', 'Dermatologia', 'Ginecologia',
                'Neurologia', 'Oftalmologia', 'Ortopedia', 'Pediatria',
                'Psiquiatria', 'Urologia', 'Exames Laboratoriais', 'Exames de Imagem',
                'Fisioterapia', 'Consulta de Retorno', 'Primeira Consulta'
            ];
            
            this.isLoaded = true;
            return this.especialidades;
        }
    }

    // Criar select de especialidades
    createEspecialidadeSelect(targetElementId, placeholder = 'Selecione a especialidade...') {
        const container = document.getElementById(targetElementId);
        if (!container) {
            console.error(`❌ Elemento ${targetElementId} não encontrado!`);
            return;
        }

        // Verificar se já existe
        const existingSelect = container.querySelector('.especialidade-select');
        if (existingSelect) {
            existingSelect.remove();
        }

        // Buscar input existente
        const inputElement = container.querySelector('input[name="especialidade"], input#especialidade');
        if (!inputElement) {
            console.error('❌ Input de especialidade não encontrado!');
            return;
        }

        // Criar select
        const select = document.createElement('select');
        select.id = `${targetElementId}_select`;
        select.className = 'especialidade-select';
        select.style.cssText = `
            width: 100%;
            padding: 0.75rem;
            border: 2px solid var(--border-color, #e5e5e5);
            border-radius: 0.5rem;
            font-size: 1rem;
            background: white;
            margin-bottom: 0.5rem;
            box-sizing: border-box;
        `;

        // Opção padrão
        const defaultOption = document.createElement('option');
        defaultOption.value = '';
        defaultOption.textContent = placeholder;
        select.appendChild(defaultOption);

        // Adicionar especialidades
        this.especialidades.forEach(especialidade => {
            const option = document.createElement('option');
            option.value = especialidade;
            option.textContent = especialidade;
            select.appendChild(option);
        });

        // Opção "Outra especialidade"
        const outraOption = document.createElement('option');
        outraOption.value = 'outra';
        outraOption.textContent = '🏥 Outra especialidade (digite abaixo)';
        select.appendChild(outraOption);

        // Garantir visibilidade do input
        inputElement.style.cssText = `
            width: 100%;
            padding: 0.75rem;
            border: 2px solid var(--border-color, #e5e5e5);
            border-radius: 0.5rem;
            font-size: 1rem;
            background: white;
            box-sizing: border-box;
            display: block !important;
            visibility: visible !important;
            margin-top: 0.5rem;
        `;
        
        inputElement.placeholder = 'Digite a especialidade ou selecione acima';

        // Inserir select antes do input
        container.insertBefore(select, inputElement);
        
        // Armazenar referências
        this.inputElement = inputElement;
        this.selectElement = select;
        
        // Event listener
        select.addEventListener('change', (e) => {
            const selectedValue = e.target.value;
            
            if (selectedValue && selectedValue !== 'outra') {
                // Preencher input com especialidade selecionada
                this.inputElement.value = selectedValue;
                this.inputElement.focus();
                
                setTimeout(() => {
                    const length = this.inputElement.value.length;
                    this.inputElement.setSelectionRange(length, length);
                }, 100);
                
            } else if (selectedValue === 'outra') {
                // Limpar input para digitação livre
                this.inputElement.value = '';
                this.inputElement.focus();
                this.inputElement.placeholder = 'Digite a especialidade médica';
            }
        });

        console.log('✅ Select de especialidades criado!');
    }

    // Inicializar
    async init(targetElementId, placeholder) {
        console.log('🚀 Inicializando especialidades médicas...');
        try {
            await this.loadEspecialidades();
            this.createEspecialidadeSelect(targetElementId, placeholder);
            console.log('✅ Especialidades inicializadas com sucesso!');
        } catch (error) {
            console.error('❌ Erro ao inicializar especialidades:', error);
        }
    }

    // Buscar especialidade
    searchEspecialidade(query) {
        if (!query || query.length < 2) return [];
        
        const queryLower = query.toLowerCase();
        return this.especialidades.filter(especialidade => 
            especialidade.toLowerCase().includes(queryLower)
        );
    }

    // Validar especialidade
    isValidEspecialidade(especialidade) {
        return this.especialidades.some(e => 
            e.toLowerCase() === especialidade.toLowerCase()
        );
    }
}

// Instância global
const especialidadesMedicas = new EspecialidadesMedicas();

// Inicializar quando DOM carregar
document.addEventListener('DOMContentLoaded', function() {
    console.log('📱 Verificando especialidades...');
    
    const targetElement = document.querySelector('#especialidade-container');
    if (targetElement) {
        console.log('🎯 Campo de especialidade detectado!');
        
        setTimeout(() => {
            especialidadesMedicas.init('especialidade-container', '🏥 Selecione a especialidade médica...');
        }, 600);
    }
});

// Função de validação simples
function validarEspecialidadeSimples() {
    const especialidadeInput = document.getElementById('especialidade');
    if (!especialidadeInput) return true;
    
    const valor = especialidadeInput.value.trim();
    
    if (!valor) return true;
    if (valor.length < 3) return true;
    
    // Palavras que indicam especialidade válida
    const palavrasValidas = [
        'cardiologia', 'neurologia', 'pediatria', 'ginecologia', 'ortopedia',
        'dermatologia', 'oftalmologia', 'psiquiatria', 'urologia', 'clinica',
        'clínica', 'cirurgia', 'exame', 'consulta', 'fisioterapia', 'fonoaudiologia',
        'nutrição', 'psicologia', 'terapia', 'laboratorio', 'laboratório', 'imagem'
    ];
    
    const valorLower = valor.toLowerCase();
    const temPalavraValida = palavrasValidas.some(palavra => 
        valorLower.includes(palavra)
    );
    
    if (temPalavraValida || valor.length > 5) {
        mostrarSucessoEspecialidade();
        return true;
    } else {
        mostrarAvisoEspecialidade();
        return false;
    }
}

// Mostrar aviso
function mostrarAvisoEspecialidade() {
    const input = document.getElementById('especialidade');
    if (!input) return;
    
    const avisoAnterior = input.parentElement.querySelector('.aviso-especialidade');
    if (avisoAnterior) avisoAnterior.remove();
    
    const aviso = document.createElement('div');
    aviso.className = 'aviso-especialidade';
    aviso.style.cssText = `
        color: #f2823c;
        font-size: 0.875rem;
        margin-top: 0.25rem;
        display: flex;
        align-items: center;
    `;
    aviso.innerHTML = `
        <span style="margin-right: 0.5rem;">🏥</span>
        <span>Digite uma especialidade médica (ex: Cardiologia, Clínica Geral)</span>
    `;
    
    input.parentElement.appendChild(aviso);
    input.style.borderColor = '#f2823c';
}

// Mostrar sucesso
function mostrarSucessoEspecialidade() {
    const input = document.getElementById('especialidade');
    if (!input) return;
    
    const avisoAnterior = input.parentElement.querySelector('.aviso-especialidade');
    if (avisoAnterior) avisoAnterior.remove();
    
    input.style.borderColor = '#79b24a';
    
    setTimeout(() => {
        input.style.borderColor = 'var(--border-color, #e5e5e5)';
    }, 2000);
}

console.log('🏥 Sistema de especialidades carregado!');
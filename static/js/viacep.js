// 🏠 ViaCEP - Busca automática de endereços

// https://viacep.com.br/ws/${cep}/json/ 


class ViaCEP {
    constructor() {
        this.init();
    }

    init() {
        // Aguardar o DOM carregar
        document.addEventListener('DOMContentLoaded', () => {
            this.setupCEPFields();
        });
    }

    setupCEPFields() {
        // Buscar todos os campos de CEP na página
        const cepFields = document.querySelectorAll('input[name="cep"], #cep');
        
        cepFields.forEach(field => {
            // Máscara de CEP
            field.addEventListener('input', (e) => {
                this.formatCEP(e.target);
            });

            // Buscar endereço quando CEP estiver completo
            field.addEventListener('blur', (e) => {
                this.buscarEndereco(e.target);
            });
        });
    }

    formatCEP(field) {
        // Remove tudo que não for número
        let value = field.value.replace(/\D/g, '');
        
        // Aplicar máscara 00000-000
        if (value.length >= 6) {
            value = value.replace(/(\d{5})(\d{1,3})/, '$1-$2');
        }
        
        field.value = value;
        
        // Limitar a 9 caracteres (00000-000)
        if (field.value.length > 9) {
            field.value = field.value.substring(0, 9);
        }
    }

    async buscarEndereco(cepField) {
        const cep = cepField.value.replace(/\D/g, ''); // Remove caracteres não numéricos
        
        // Validar CEP (deve ter 8 dígitos)
        if (cep.length !== 8) {
            this.limparCampos();
            return;
        }

        try {
            // Mostrar loading
            this.showLoading(true);
            
            // Fazer requisição para ViaCEP
            const response = await fetch(`https://viacep.com.br/ws/${cep}/json/`);
            const data = await response.json();
            
            if (data.erro) {
                this.showError('CEP não encontrado!');
                this.limparCampos();
                return;
            }

            // Preencher campos automaticamente
            this.preencherCampos(data);
            this.showSuccess('Endereço encontrado!');
            
        } catch (error) {
            console.error('Erro ao buscar CEP:', error);
            this.showError('Erro ao buscar CEP. Verifique sua conexão.');
        } finally {
            this.showLoading(false);
        }
    }

    preencherCampos(data) {
        // Mapear campos da API para campos do formulário
        const campos = {
            'logradouro': data.logradouro,
            'bairro': data.bairro,
            'cidade': data.localidade,
            'uf': data.uf
        };

        // Preencher cada campo encontrado
        Object.keys(campos).forEach(campo => {
            const element = document.getElementById(campo) || document.querySelector(`input[name="${campo}"]`);
            if (element && campos[campo]) {
                element.value = campos[campo];
                element.dispatchEvent(new Event('input')); // Disparar evento para validações
            }
        });

        // Focar no campo número (próximo campo a ser preenchido)
        const numeroField = document.getElementById('numero') || document.querySelector('input[name="numero"]');
        if (numeroField) {
            numeroField.focus();
        }
    }

    limparCampos() {
        const campos = ['logradouro', 'bairro', 'cidade', 'uf'];
        
        campos.forEach(campo => {
            const element = document.getElementById(campo) || document.querySelector(`input[name="${campo}"]`);
            if (element) {
                element.value = '';
            }
        });
    }

    showLoading(show) {
        const loadingId = 'viacep-loading';
        let loading = document.getElementById(loadingId);
        
        if (show) {
            if (!loading) {
                loading = document.createElement('div');
                loading.id = loadingId;
                loading.innerHTML = '🔍 Buscando endereço...';
                loading.style.cssText = `
                    position: fixed;
                    top: 20px;
                    right: 20px;
                    background: var(--info-color);
                    color: white;
                    padding: 10px 15px;
                    border-radius: 5px;
                    z-index: 1000;
                    font-size: 14px;
                `;
                document.body.appendChild(loading);
            }
        } else {
            if (loading) {
                loading.remove();
            }
        }
    }

    showSuccess(message) {
        this.showMessage(message, 'success');
    }

    showError(message) {
        this.showMessage(message, 'error');
    }

    showMessage(message, type) {
        const messageId = 'viacep-message';
        let messageEl = document.getElementById(messageId);
        
        // Remover mensagem anterior
        if (messageEl) {
            messageEl.remove();
        }

        // Criar nova mensagem
        messageEl = document.createElement('div');
        messageEl.id = messageId;
        messageEl.textContent = message;
        
        const isSuccess = type === 'success';
        messageEl.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            background: ${isSuccess ? 'var(--success-color)' : 'var(--danger-color)'};
            color: white;
            padding: 10px 15px;
            border-radius: 5px;
            z-index: 1000;
            font-size: 14px;
        `;
        
        document.body.appendChild(messageEl);
        
        // Remover após 3 segundos
        setTimeout(() => {
            if (messageEl) {
                messageEl.remove();
            }
        }, 3000);
    }
}

// 🏠 ViaCEP - Busca automática de endereços
class ViaCEP {
    constructor() {
        this.init();
    }

    init() {
        // Aguardar o DOM carregar
        document.addEventListener('DOMContentLoaded', () => {
            this.setupCEPFields();
        });
    }

    setupCEPFields() {
        // Buscar todos os campos de CEP na página
        const cepFields = document.querySelectorAll('input[name="cep"], #cep');
        
        cepFields.forEach(field => {
            // Máscara de CEP
            field.addEventListener('input', (e) => {
                this.formatCEP(e.target);
            });

            // Buscar endereço quando CEP estiver completo
            field.addEventListener('blur', (e) => {
                this.buscarEndereco(e.target);
            });

            // 🆕 VALIDAÇÃO EM TEMPO REAL
            field.addEventListener('keyup', (e) => {
                this.validarCEPTemporal(e.target);
            });
        });
    }

    formatCEP(field) {
        // Remove tudo que não for número
        let value = field.value.replace(/\D/g, '');
        
        // Aplicar máscara 00000-000
        if (value.length >= 6) {
            value = value.replace(/(\d{5})(\d{1,3})/, '$1-$2');
        }
        
        field.value = value;
        
        // Limitar a 9 caracteres (00000-000)
        if (field.value.length > 9) {
            field.value = field.value.substring(0, 9);
        }
    }

    // 🆕 VALIDAÇÃO EM TEMPO REAL
    validarCEPTemporal(field) {
        const cep = field.value.replace(/\D/g, '');
        
        // Remover classes anteriores
        field.classList.remove('cep-valido', 'cep-invalido');
        
        if (cep.length === 8) {
            if (this.validarFormatoCEP(cep)) {
                field.classList.add('cep-valido');
                this.adicionarEstilosCEP();
            } else {
                field.classList.add('cep-invalido');
                this.showError('CEP com formato inválido!');
                this.adicionarEstilosCEP();
            }
        }
    }

    // 🆕 VALIDAÇÃO DE FORMATO
    validarFormatoCEP(cep) {
        // CEP deve ter exatamente 8 dígitos
        if (!/^\d{8}$/.test(cep)) return false;
        
        // CEP não pode ser sequencial (00000000, 11111111, etc.)
        if (/^(\d)\1{7}$/.test(cep)) return false;
        
        // CEP não pode começar com 0 (exceto algumas regiões válidas)
        if (cep.startsWith('0') && !['01000', '02000', '03000', '04000', '05000', '08000', '09000'].some(prefix => cep.startsWith(prefix))) {
            return false;
        }
        
        return true;
    }

    // 🆕 ESTILOS DINÂMICOS PARA VALIDAÇÃO
    adicionarEstilosCEP() {
        if (!document.getElementById('cep-validation-styles')) {
            const style = document.createElement('style');
            style.id = 'cep-validation-styles';
            style.textContent = `
                .cep-valido {
                    border-color: var(--success-color) !important;
                    box-shadow: 0 0 0 3px rgba(121, 178, 74, 0.25) !important;
                }
                .cep-invalido {
                    border-color: var(--danger-color) !important;
                    box-shadow: 0 0 0 3px rgba(232, 29, 81, 0.25) !important;
                }
            `;
            document.head.appendChild(style);
        }
    }

    async buscarEndereco(cepField) {
        const cep = cepField.value.replace(/\D/g, ''); // Remove caracteres não numéricos
        
        // Validar CEP (deve ter 8 dígitos e formato válido)
        if (cep.length !== 8) {
            this.limparCampos();
            return;
        }

        if (!this.validarFormatoCEP(cep)) {
            this.showError('CEP com formato inválido!');
            this.limparCampos();
            return;
        }

        try {
            // Mostrar loading
            this.showLoading(true);
            
            // Fazer requisição para ViaCEP
            const response = await fetch(`https://viacep.com.br/ws/${cep}/json/`);
            const data = await response.json();
            
            if (data.erro) {
                this.showError('CEP não encontrado!');
                this.limparCampos();
                return;
            }

            // 🆕 VALIDAÇÃO ADICIONAL DOS DADOS RETORNADOS
            if (!data.logradouro || !data.localidade) {
                this.showError('CEP encontrado, mas dados incompletos!');
                return;
            }

            // Preencher campos automaticamente
            this.preencherCampos(data);
            this.showSuccess('Endereço encontrado e validado! ✅');
            
        } catch (error) {
            console.error('Erro ao buscar CEP:', error);
            this.showError('Erro ao buscar CEP. Verifique sua conexão.');
        } finally {
            this.showLoading(false);
        }
    }

    preencherCampos(data) {
        // Mapear campos da API para campos do formulário
        const campos = {
            'logradouro': data.logradouro,
            'bairro': data.bairro,
            'cidade': data.localidade,
            'uf': data.uf
        };

        // Preencher cada campo encontrado
        Object.keys(campos).forEach(campo => {
            const element = document.getElementById(campo) || document.querySelector(`input[name="${campo}"]`);
            if (element && campos[campo]) {
                element.value = campos[campo];
                element.dispatchEvent(new Event('input')); // Disparar evento para validações
            }
        });

        // Focar no campo número (próximo campo a ser preenchido)
        const numeroField = document.getElementById('numero') || document.querySelector('input[name="numero"]');
        if (numeroField) {
            numeroField.focus();
        }
    }

    limparCampos() {
        const campos = ['logradouro', 'bairro', 'cidade', 'uf'];
        
        campos.forEach(campo => {
            const element = document.getElementById(campo) || document.querySelector(`input[name="${campo}"]`);
            if (element) {
                element.value = '';
            }
        });
    }

    showLoading(show) {
        const loadingId = 'viacep-loading';
        let loading = document.getElementById(loadingId);
        
        if (show) {
            if (!loading) {
                loading = document.createElement('div');
                loading.id = loadingId;
                loading.innerHTML = '🔍 Buscando endereço...';
                loading.style.cssText = `
                    position: fixed;
                    top: 20px;
                    right: 20px;
                    background: var(--info-color);
                    color: white;
                    padding: 10px 15px;
                    border-radius: 5px;
                    z-index: 1000;
                    font-size: 14px;
                `;
                document.body.appendChild(loading);
            }
        } else {
            if (loading) {
                loading.remove();
            }
        }
    }

    showSuccess(message) {
        this.showMessage(message, 'success');
    }

    showError(message) {
        this.showMessage(message, 'error');
    }

    showMessage(message, type) {
        const messageId = 'viacep-message';
        let messageEl = document.getElementById(messageId);
        
        // Remover mensagem anterior
        if (messageEl) {
            messageEl.remove();
        }

        // Criar nova mensagem
        messageEl = document.createElement('div');
        messageEl.id = messageId;
        messageEl.textContent = message;
        
        const isSuccess = type === 'success';
        messageEl.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            background: ${isSuccess ? 'var(--success-color)' : 'var(--danger-color)'};
            color: white;
            padding: 10px 15px;
            border-radius: 5px;
            z-index: 1000;
            font-size: 14px;
        `;
        
        document.body.appendChild(messageEl);
        
        // Remover após 3 segundos
        setTimeout(() => {
            if (messageEl) {
                messageEl.remove();
            }
        }, 3000);
    }
}

// Inicializar ViaCEP
new ViaCEP();
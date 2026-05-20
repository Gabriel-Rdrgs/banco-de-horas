# Guia de Instalação — Banco de Horas OCR
**Provida Centro Médico**

> Tempo estimado: 15 a 20 minutos  
> Requisito: Windows 10 ou superior, acesso à internet durante a instalação

---

## O que você vai precisar antes de começar

- Os arquivos do sistema (pasta `banco de horas` completa)
- O arquivo `.env` com as credenciais Azure (peça ao responsável pelo sistema)
- Acesso de administrador no computador

---

## Passo 1 — Instalar o Python

1. Abra o navegador e acesse **python.org/downloads**
2. Clique no botão amarelo de download (versão mais recente)
3. Execute o instalador baixado
4. **IMPORTANTE:** na primeira tela do instalador, marque a opção  
   **"Add Python to PATH"** antes de clicar em *Install Now*

   ![Marque Add Python to PATH](https://docs.python.org/3/_images/win_installer.png)

5. Clique em *Install Now* e aguarde
6. Ao finalizar, clique em *Close*

**Verificação:** abra o Prompt de Comando (`Win + R` → digite `cmd` → Enter) e execute:
```
python --version
```
Deve aparecer algo como `Python 3.12.x`. Se aparecer, o Python está instalado corretamente.

---

## Passo 2 — Copiar os arquivos do sistema

Copie a pasta `banco de horas` para o computador. O local recomendado é:

```
C:\Users\<nome do usuário>\Desktop\banco de horas\
```

> A pasta deve conter os arquivos `app.py`, `requirements.txt`, `Iniciar Banco de Horas.bat`, entre outros.

---

## Passo 3 — Configurar as credenciais Azure

1. Dentro da pasta `banco de horas`, localize o arquivo `.env.example`
2. Faça uma cópia deste arquivo e renomeie a cópia para `.env` (sem o `.example`)
3. Abra o arquivo `.env` com o Bloco de Notas
4. Preencha as duas linhas com as credenciais do Azure:

```
AZURE_VISION_ENDPOINT=https://provida-vision.cognitiveservices.azure.com/
AZURE_VISION_KEY=cole-a-chave-aqui
```

> As credenciais são obtidas no portal Azure:  
> **portal.azure.com** → recurso `provida-vision` → *Chaves e Ponto de Extremidade*

5. Salve o arquivo (Ctrl+S) e feche o Bloco de Notas

---

## Passo 4 — Instalar as dependências Python

1. Abra o Prompt de Comando como Administrador:  
   Clique no Menu Iniciar → digite `cmd` → clique com o botão direito em *Prompt de Comando* → **Executar como administrador**

2. Navegue até a pasta do sistema. Substitua `<nome do usuário>` pelo nome da conta:
```
cd "C:\Users\<nome do usuário>\Desktop\banco de horas"
```

3. Execute o comando de instalação:
```
pip install -r requirements.txt
```

4. Aguarde o término — pode levar de 3 a 10 minutos dependendo da conexão.  
   A última linha deve mostrar algo como `Successfully installed ...`

---

## Passo 5 — Criar o atalho na área de trabalho

1. Dentro da pasta `banco de horas`, dê duplo clique em:  
   **`Criar Atalho Desktop.bat`**

2. Uma janela preta aparecerá brevemente e depois fechará sozinha
3. Um atalho chamado **"Banco de Horas"** aparecerá na área de trabalho

> Este passo precisa ser feito apenas uma vez por computador.

---

## Passo 6 — Testar o sistema

1. Dê duplo clique no atalho **"Banco de Horas"** na área de trabalho
2. O navegador abrirá automaticamente com a tela do sistema
3. Na barra de tarefas, aparecerá uma janela minimizada (pode ser expandida para ver logs)

Se o navegador não abrir sozinho, acesse manualmente: **http://localhost:8501**

---

## Solução de problemas comuns

### "Python não é reconhecido como comando"
O Python não foi adicionado ao PATH durante a instalação.  
**Solução:** Desinstale o Python (Painel de Controle → Programas) e reinstale marcando **"Add Python to PATH"** no primeiro passo do instalador.

---

### Tela de erro ao abrir o sistema / janela preta com mensagem de erro
Expanda a janela minimizada na barra de tarefas para ver a mensagem completa.  
Causas mais comuns:
- Arquivo `.env` não criado ou com credenciais erradas → refaça o Passo 3
- Dependências não instaladas → refaça o Passo 4

---

### "Planilha não encontrada"
O sistema espera a planilha em:
```
banco de horas\planilha\BancoHoras_Provida_v2.xlsm
```
Verifique se o arquivo está nessa pasta exata.

---

### O sistema abre mas diz "Azure Vision não configurado"
O arquivo `.env` está ausente ou com valores incorretos → refaça o Passo 3.

---

### Porta 8501 já está em uso
Outro programa está usando a porta.  
**Solução:** Abra o Gerenciador de Tarefas (Ctrl+Shift+Esc) → aba *Detalhes* → procure e encerre qualquer processo chamado `python.exe`.

---

## Como encerrar o sistema

Feche a janela minimizada na barra de tarefas chamada **"Banco de Horas"**.  
O navegador pode continuar aberto normalmente — apenas o servidor será encerrado.

---

## Informações técnicas (para TI)

| Item | Detalhe |
|---|---|
| Python mínimo | 3.11 |
| Porta de rede | 8501 (somente local — não exposta à rede) |
| Dependências | `pip install -r requirements.txt` |
| Credenciais | Arquivo `.env` na raiz do projeto |
| Engine OCR | Azure Computer Vision (requer chave ativa) |
| Planilha | `planilha/BancoHoras_Provida_v2.xlsm` |
| Log de erros | Janela minimizada na barra de tarefas |

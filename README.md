# OCR de Estudo

Automação em Python que transforma PDFs escaneados ou bloqueados contra cópia (e imagens) em
**texto copiável**, e opcionalmente **traduz** e **resume** o conteúdo usando uma API REST de IA.

**Vídeo de demonstração:** [LINK_DO_VIDEO](https://youtu.be/UrVCk56akrM)

## O problema

Estudantes recebem com frequência materiais em PDF em que não é possível selecionar nem copiar o
texto. Para fazer resumos, fichamentos ou pesquisar um termo, é preciso digitar tudo à mão.

## Como funciona

PDF/imagem → página renderizada como imagem (PyMuPDF) → pré-processamento (Pillow) →
OCR (Tesseract) → limpeza do texto → `.txt` → tradução e resumo via API REST (`requests`).

## Tecnologias

- Python 3.14
- PyMuPDF: renderização das páginas
- Pillow: melhoria da imagem (escala de cinza, contraste, nitidez)
- pytesseract + Tesseract OCR: reconhecimento de texto
- requests: integração com a API REST do Google Gemini (ou Anthropic)
- python-dotenv: leitura segura das chaves a partir do `.env`

## Instalação (Windows)

1. Instale o **Tesseract**: https://github.com/UB-Mannheim/tesseract/wiki
   Na instalação, em *Additional language data*, marque **Portuguese**.
2. Na pasta do projeto:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

3. (Para tradução e resumo) crie uma chave gratuita em https://aistudio.google.com/apikey,
   copie `.env.example` para `.env` e preencha `GEMINI_API_KEY` e `GEMINI_MODEL`.
   Nunca envie o `.env` ao GitHub.

## Uso

```powershell
python main.py estudo_ingles.pdf --idioma eng                       # só OCR
python main.py estudo_ingles.pdf --idioma eng --traduzir            # + tradução
python main.py estudo_ingles.pdf --idioma eng --traduzir --resumir  # + resumo e perguntas
python main.py pasta_de_pdfs\ -o resultados                         # pasta inteira
```

| Opção | Descrição |
|---|---|
| `--idioma` | Idiomas do Tesseract (`por`, `eng`, `por+eng`) |
| `--dpi` | Resolução da renderização (padrão 300) |
| `--largura` | Largura das linhas do `.txt` (padrão 90; 0 desativa) |
| `--manter-quebras` | Mantém as quebras de linha originais (bom para slides) |
| `--pdf-pesquisavel` | Também gera um PDF com camada de texto |
| `--traduzir [IDIOMA]` | Traduz via API (padrão: português do Brasil) |
| `--resumir` | Ideia central, tópicos, conceitos e perguntas de revisão |

Os resultados ficam na pasta `saida/`. O `estudo_ingles.pdf` incluído é um exemplo com o texto em imagem.

## Limitações

- A qualidade depende da nitidez do documento. Tabelas, fórmulas e colunas duplas podem sair fora de ordem.
- A busca (Ctrl+F) com acentos no PDF pesquisável pode falhar em alguns leitores; o `.txt` é o resultado principal.
- A camada gratuita da API tem limite de uso e pode ficar instável em horários de pico.

## Uso responsável

Ferramenta para uso pessoal nos estudos. O conteúdo dos materiais continua protegido por direitos
autorais e não deve ser redistribuído.

## Integrantes do grupo

- **João Pedro de Albuquerque Oliveira**: RM 551579
- **Pedro Augusto Carneiro Barone Bomfim**: RM 99781
- **Matheus Augusto Santos Rego**: RM 551466

# OCR de Estudo

Extrai texto **copiável** de PDFs escaneados, bloqueados contra cópia e imagens, usando OCR.
Opcionalmente traduz o texto e gera resumo, conceitos-chave e perguntas de revisão via API.

> Uso pessoal/estudo. O conteúdo continua protegido por direitos autorais: não redistribua.

## Como funciona

PDF/imagem → página renderizada como imagem (PyMuPDF) → pré-processamento (Pillow) →
OCR (Tesseract) → limpeza do texto → `.txt` / PDF pesquisável → tradução e resumo (API Anthropic via `requests`).

## Instalação (Windows)

1. Instale o **Tesseract**: https://github.com/UB-Mannheim/tesseract/wiki
   Durante a instalação, em *Additional language data*, marque **Portuguese**.
2. No terminal do VS Code, dentro da pasta do projeto:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

3. (Opcional, para tradução/resumo) copie `.env.example` para `.env` e coloque sua `ANTHROPIC_API_KEY`.

## Uso

```powershell
python main.py apostila.pdf                          # OCR -> saida/apostila_ocr.txt
python main.py apostila.pdf --pdf-pesquisavel        # + PDF com texto selecionável
python main.py artigo.pdf --idioma eng --traduzir    # inglês -> português
python main.py artigo.pdf --resumir                  # resumo + perguntas de revisão
python main.py pasta_de_pdfs/ -o resultados          # processa uma pasta inteira
```

| Opção | Descrição |
|---|---|
| `--idioma` | Idiomas do Tesseract (`por`, `eng`, `por+eng`) |
| `--dpi` | Resolução da renderização (padrão 300; aumente para letras pequenas) |
| `--pdf-pesquisavel` | Gera PDF com texto selecionável |
| `--manter-quebras` | Mantém as quebras de linha originais |
| `--traduzir [IDIOMA]` | Traduz via API |
| `--resumir` | Resumo, conceitos e perguntas via API |

"""Módulo de OCR: transforma PDFs (escaneados ou bloqueados) e imagens em texto.

Fluxo: página -> imagem (PyMuPDF) -> pré-processamento (Pillow) -> Tesseract.
Como o OCR "lê" a imagem renderizada da página, funciona mesmo quando o PDF
não tem texto selecionável ou tem restrição de cópia.
"""

import io
import logging
import os
import re
import shutil
import textwrap
import unicodedata
from pathlib import Path
from typing import Iterator

import pymupdf as fitz  # PyMuPDF
import pytesseract
from PIL import Image, ImageFilter, ImageOps

log = logging.getLogger(__name__)

VERSAO = "3"  # permite conferir se o arquivo certo está sendo usado

EXTENSOES_IMAGEM = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
EXTENSOES_SUPORTADAS = EXTENSOES_IMAGEM | {".pdf"}

# Locais comuns de instalação do Tesseract no Windows
CAMINHOS_TESSERACT_WINDOWS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]

# --oem 1: motor LSTM (mais preciso) | --psm 3: segmentação automática de página
CONFIG_TESSERACT = "--oem 1 --psm 3"


# --------------------------------------------------------------------------- #
# Configuração do Tesseract
# --------------------------------------------------------------------------- #
def configurar_tesseract() -> str:
    """Localiza o executável do Tesseract e o registra no pytesseract."""
    caminho = os.getenv("TESSERACT_CMD") or shutil.which("tesseract")
    if not caminho:
        caminho = next((c for c in CAMINHOS_TESSERACT_WINDOWS if Path(c).exists()), None)
    if not caminho:
        raise RuntimeError(
            "Tesseract não encontrado. Instale-o (veja o README) ou defina "
            "TESSERACT_CMD no arquivo .env com o caminho do tesseract.exe."
        )
    pytesseract.pytesseract.tesseract_cmd = caminho
    log.info("Tesseract: %s", caminho)
    return caminho


def verificar_idiomas(idiomas: str) -> None:
    """Garante que os pacotes de idioma pedidos (ex.: 'por+eng') estão instalados."""
    instalados = set(pytesseract.get_languages(config=""))
    faltando = [i for i in idiomas.split("+") if i not in instalados]
    if faltando:
        raise RuntimeError(
            f"Idioma(s) do Tesseract não instalado(s): {', '.join(faltando)}. "
            "Reinstale o Tesseract marcando 'Portuguese' em Additional language data."
        )


# --------------------------------------------------------------------------- #
# Leitura das páginas
# --------------------------------------------------------------------------- #
def contar_paginas(caminho: Path) -> int:
    """Retorna o número de páginas (imagens contam como 1)."""
    if caminho.suffix.lower() in EXTENSOES_IMAGEM:
        return 1
    with fitz.open(caminho) as doc:
        return doc.page_count


def carregar_paginas(caminho: Path, dpi: int = 300) -> Iterator[Image.Image]:
    """Gera cada página como imagem PIL, uma por vez (economiza memória)."""
    if caminho.suffix.lower() in EXTENSOES_IMAGEM:
        with Image.open(caminho) as img:
            yield img.convert("RGB")
        return

    with fitz.open(caminho) as doc:
        if doc.needs_pass:
            raise RuntimeError(f"'{caminho.name}' exige senha para ser aberto.")
        for pagina in doc:
            # Renderiza a página inteira como imagem, ignorando bloqueios de cópia
            pix = pagina.get_pixmap(dpi=dpi, alpha=False)
            yield Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


# --------------------------------------------------------------------------- #
# Pré-processamento e OCR
# --------------------------------------------------------------------------- #
def preprocessar(img: Image.Image) -> Image.Image:
    """Melhora a imagem para o OCR: escala de cinza, contraste e nitidez."""
    cinza = ImageOps.grayscale(img)
    cinza = ImageOps.autocontrast(cinza, cutoff=1)  # ignora 1% de extremos (ruído)
    return cinza.filter(ImageFilter.SHARPEN)


# Palavra reconhecida: (texto, x, y, largura, altura), em pixels da imagem
Palavra = tuple[str, int, int, int, int]

# Troca caracteres tipográficos que a fonte Helvetica (Latin-1) do PDF não possui
_SUBSTITUICOES = str.maketrans(
    {"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"',
     "\u2013": "-", "\u2014": "-", "\u2022": "*"}
)


def _montar_texto(dados: dict) -> str:
    """Reconstrói o texto (linhas e parágrafos) a partir do resultado de image_to_data."""
    partes: list[str] = []
    anterior = None  # (paragrafo, linha) da palavra anterior
    for i, palavra in enumerate(dados["text"]):
        if not palavra.strip():
            continue
        paragrafo = (dados["block_num"][i], dados["par_num"][i])
        linha = paragrafo + (dados["line_num"][i],)
        if anterior is not None:
            if paragrafo != anterior[0]:
                partes.append("\n\n")
            elif linha != anterior[1]:
                partes.append("\n")
            else:
                partes.append(" ")
        partes.append(palavra.strip())
        anterior = (paragrafo, linha)
    return "".join(partes)


def ocr_pagina(img: Image.Image, idiomas: str) -> tuple[str, list[Palavra]]:
    """Executa o OCR em uma página e devolve (texto, palavras com posição)."""
    dados = pytesseract.image_to_data(
        preprocessar(img), lang=idiomas, config=CONFIG_TESSERACT,
        output_type=pytesseract.Output.DICT,
    )
    palavras: list[Palavra] = [
        (t.strip(), dados["left"][i], dados["top"][i], dados["width"][i], dados["height"][i])
        for i, t in enumerate(dados["text"])
        if t.strip() and float(dados["conf"][i]) >= 0
    ]
    return _montar_texto(dados), palavras


def _compativel_latin1(texto: str) -> str:
    """Normaliza o texto para a fonte Latin-1 (cobre todos os acentos do português)."""
    texto = unicodedata.normalize("NFKC", texto).translate(_SUBSTITUICOES)
    return texto.encode("latin-1", errors="replace").decode("latin-1")


def _adicionar_pagina_pdf(doc: fitz.Document, img: Image.Image, palavras: list[Palavra], dpi: int) -> None:
    """Cria uma página com a imagem original e, por cima, o texto reconhecido invisível.

    Montamos o PDF com o PyMuPDF (em vez de usar o PDF do Tesseract) porque assim o texto
    usa uma fonte padrão com mapeamento Unicode correto: a busca (Ctrl+F) e a cópia
    funcionam com acentos.
    """
    escala = 72 / dpi  # pixels -> pontos do PDF
    pagina = doc.new_page(width=img.width * escala, height=img.height * escala)

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=80)
    pagina.insert_image(pagina.rect, stream=buffer.getvalue())

    for texto, x, y, w, h in palavras:
        texto = _compativel_latin1(texto)
        tamanho = max(h * escala * 0.85, 2)
        comprimento = fitz.get_text_length(texto, fontname="helv", fontsize=tamanho)
        if comprimento > 0:
            # Ajusta a fonte para a palavra ocupar a largura da palavra impressa
            tamanho *= min(max(w * escala / comprimento, 0.5), 1.5)
        baseline = (y + h * 0.8) * escala
        # render_mode=3 -> texto invisível (só a camada de busca/seleção)
        pagina.insert_text((x * escala, baseline), texto, fontname="helv",
                           fontsize=tamanho, render_mode=3)


def processar_arquivo(
    caminho: Path,
    idiomas: str = "por+eng",
    dpi: int = 300,
    pdf_saida: Path | None = None,
) -> list[str]:
    """Faz OCR de todas as páginas e devolve a lista de textos (um por página).

    Se `pdf_saida` for informado, também grava um PDF pesquisável/copiável.
    """
    total = contar_paginas(caminho)
    textos: list[str] = []
    pdf_final = fitz.open() if pdf_saida else None

    try:
        for n, img in enumerate(carregar_paginas(caminho, dpi), start=1):
            log.info("  [%s] página %d/%d", caminho.name, n, total)
            texto, palavras = ocr_pagina(img, idiomas)
            textos.append(texto)
            if pdf_final is not None:
                try:
                    _adicionar_pagina_pdf(pdf_final, img, palavras, dpi)
                except Exception:
                    # O texto extraído é o principal: seguimos só com ele
                    log.exception("  Não foi possível montar o PDF pesquisável")
                    pdf_final.close()
                    pdf_final = None

        if pdf_final is not None and pdf_saida:
            pdf_final.save(pdf_saida, garbage=3, deflate=True)
            log.info("  PDF pesquisável salvo em %s", pdf_saida)
    finally:
        if pdf_final is not None:
            pdf_final.close()

    return textos


# --------------------------------------------------------------------------- #
# Limpeza do texto
# --------------------------------------------------------------------------- #
def limpar_texto(texto: str, manter_quebras: bool = False) -> str:
    """Remove ruídos típicos de OCR para o texto ficar "colável" em outros lugares.

    - Junta palavras separadas por hífen no fim da linha ("conheci-\\nmento").
      Obs.: pode juntar indevidamente hifens legítimos (ex.: "guarda-\\nchuva").
    - Troca quebras de linha dentro de um parágrafo por espaço
      (a menos que `manter_quebras` seja True).
    - Normaliza espaços e linhas em branco repetidas.
    """
    texto = texto.replace("\r", "")
    texto = re.sub(r"(\w)-\n(\w)", r"\1\2", texto)
    if not manter_quebras:
        texto = re.sub(r"(?<!\n)\n(?!\n)", " ", texto)
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def quebrar_linhas(texto: str, largura: int = 90) -> str:
    """Quebra linhas longas em `largura` caracteres, sem cortar palavras.

    Preserva as linhas em branco (separação de parágrafos). Com largura 0, não altera nada.
    """
    if largura <= 0:
        return texto
    linhas = texto.split("\n")
    return "\n".join(textwrap.fill(l, width=largura) if l.strip() else "" for l in linhas)
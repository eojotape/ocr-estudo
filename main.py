"""OCR de Estudo: extrai texto copiável de PDFs bloqueados/escaneados e imagens.

Exemplos:
    python main.py apostila.pdf
    python main.py apostila.pdf --pdf-pesquisavel
    python main.py artigo_ingles.pdf --idioma eng --traduzir --resumir
    python main.py pasta_com_pdfs/ -o resultados
"""

import argparse
import logging
import sys
import textwrap
from pathlib import Path

from dotenv import load_dotenv

import ai_tools
import pdf_ocr

log = logging.getLogger("ocr-estudo")


def quebrar_linhas(texto: str, largura: int = 90) -> str:
    """Quebra linhas longas em `largura` caracteres, sem cortar palavras.

    Preserva as linhas em branco (separação de parágrafos). Com largura 0, não altera nada.
    """
    if largura <= 0:
        return texto
    linhas = texto.split("\n")
    return "\n".join(textwrap.fill(l, width=largura) if l.strip() else "" for l in linhas)


def coletar_arquivos(entrada: Path) -> list[Path]:
    """Aceita um arquivo ou uma pasta e devolve os arquivos suportados."""
    if entrada.is_dir():
        return sorted(
            p for p in entrada.iterdir() if p.suffix.lower() in pdf_ocr.EXTENSOES_SUPORTADAS
        )
    if entrada.suffix.lower() not in pdf_ocr.EXTENSOES_SUPORTADAS:
        raise ValueError(f"Formato não suportado: {entrada.suffix}")
    return [entrada]


def criar_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Extrai texto copiável de PDFs e imagens via OCR.")
    p.add_argument("entrada", type=Path, help="PDF, imagem ou pasta com arquivos")
    p.add_argument("-o", "--saida", type=Path, default=Path("saida"), help="pasta de saída")
    p.add_argument("-l", "--idioma", default="por+eng",
                   help="idiomas do Tesseract, ex.: por, eng, por+eng (padrão)")
    p.add_argument("--dpi", type=int, default=300, help="resolução da renderização (padrão 300)")
    p.add_argument("--pdf-pesquisavel", action="store_true",
                   help="também gera um PDF com texto selecionável")
    p.add_argument("--manter-quebras", action="store_true",
                   help="não junta as linhas de um parágrafo (útil para poemas, listas, código)")
    p.add_argument("--largura", type=int, default=90,
                   help="largura máxima das linhas nos arquivos .txt (padrão 90; 0 desativa)")
    p.add_argument("--traduzir", nargs="?", const="português do Brasil", metavar="IDIOMA",
                   help="traduz o texto via API (padrão: português do Brasil)")
    p.add_argument("--resumir", action="store_true",
                   help="gera resumo, conceitos-chave e perguntas de revisão via API")
    return p


def processar(arquivo: Path, args: argparse.Namespace) -> None:
    """Executa todo o pipeline para um único arquivo."""
    log.info("Processando %s", arquivo.name)
    pdf_saida = args.saida / f"{arquivo.stem}_pesquisavel.pdf" if args.pdf_pesquisavel else None

    paginas = pdf_ocr.processar_arquivo(arquivo, args.idioma, args.dpi, pdf_saida)
    limpas = [pdf_ocr.limpar_texto(t, args.manter_quebras) for t in paginas]

    # Arquivo principal, com marcação de página para facilitar a consulta
    com_marcas = "\n\n".join(f"[Página {i}]\n{t}" for i, t in enumerate(limpas, start=1))
    destino = args.saida / f"{arquivo.stem}_ocr.txt"
    destino.write_text(quebrar_linhas(com_marcas, args.largura), encoding="utf-8")
    log.info("  Texto salvo em %s", destino)

    # Para a IA usamos o texto sem as marcações
    texto_corrido = "\n\n".join(limpas)
    if not texto_corrido.strip():
        log.warning("  Nenhum texto reconhecido; pulando etapas de IA.")
        return

    # As etapas de IA são opcionais: uma falha aqui não perde o OCR já salvo
    try:
        if args.traduzir:
            traducao = ai_tools.traduzir(texto_corrido, args.traduzir)
            destino = args.saida / f"{arquivo.stem}_traduzido.txt"
            destino.write_text(quebrar_linhas(traducao, args.largura), encoding="utf-8")
            log.info("  Tradução salva em %s", destino)

        if args.resumir:
            resumo = ai_tools.resumir(texto_corrido)
            destino = args.saida / f"{arquivo.stem}_resumo.md"
            destino.write_text(resumo, encoding="utf-8")
            log.info("  Resumo salvo em %s", destino)
    except ai_tools.ErroAPI as e:
        log.error("  Etapa de IA falhou: %s", e)


def main() -> int:
    load_dotenv()  # carrega ANTHROPIC_API_KEY e TESSERACT_CMD do arquivo .env
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = criar_parser().parse_args()

    try:
        arquivos = coletar_arquivos(args.entrada)
        if not arquivos:
            log.error("Nenhum PDF ou imagem encontrado em %s", args.entrada)
            return 1
        pdf_ocr.configurar_tesseract()
        pdf_ocr.verificar_idiomas(args.idioma)
    except (RuntimeError, ValueError, FileNotFoundError) as e:
        log.error("Erro: %s", e)
        return 1

    args.saida.mkdir(parents=True, exist_ok=True)

    for arquivo in arquivos:
        try:
            processar(arquivo, args)
        except Exception as e:  # um arquivo com problema não derruba o lote inteiro
            log.exception("Falha em %s", arquivo.name)

    log.info("Concluído! Resultados em: %s", args.saida.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
"""Integração com APIs REST de IA (via requests): tradução e resumo de estudo.

Provedores suportados (escolhidos automaticamente pela chave presente no arquivo .env):
  - Google Gemini  (GEMINI_API_KEY)    -> possui camada gratuita, sem cartão de crédito
  - Anthropic      (ANTHROPIC_API_KEY) -> pago
Para forçar um deles, defina AI_PROVIDER=gemini ou AI_PROVIDER=anthropic.
"""

import logging
import os
import time

import requests

log = logging.getLogger(__name__)

# --- Anthropic ---
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_MODELO_PADRAO = "claude-sonnet-5-5"  # troque com ANTHROPIC_MODEL

# --- Google Gemini ---
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
# "-latest" é um alias que o Google mantém apontando para o modelo Flash atual;
# nomes de modelo mudam com frequência, então dá para trocar com GEMINI_MODEL.
GEMINI_MODELO_PADRAO = "gemini-flash-latest"

# Códigos HTTP que valem a pena tentar de novo (limite de uso / instabilidade)
STATUS_TENTAR_NOVAMENTE = {429, 500, 502, 503, 529}


class ErroAPI(Exception):
    """Falha ao consultar a API."""


def _escolher_provedor() -> str:
    """Decide qual API usar, conforme AI_PROVIDER ou as chaves disponíveis."""
    forcado = os.getenv("AI_PROVIDER", "").strip().lower()
    if forcado in ("gemini", "anthropic"):
        return forcado
    if os.getenv("GEMINI_API_KEY"):
        return "gemini"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    raise ErroAPI(
        "Nenhuma chave de IA encontrada. Defina GEMINI_API_KEY (gratuita) no arquivo .env."
    )


def _post_json(url: str, headers: dict, corpo: dict, tentativas: int = 4) -> dict:
    """POST com retentativas e espera crescente. Devolve o JSON da resposta."""
    for tentativa in range(1, tentativas + 1):
        try:
            resp = requests.post(url, headers=headers, json=corpo, timeout=120)
        except requests.RequestException as e:
            log.warning("Erro de rede (%s). Tentativa %d/%d", e, tentativa, tentativas)
            time.sleep(2**tentativa)
            continue

        if resp.status_code == 200:
            return resp.json()

        if resp.status_code in STATUS_TENTAR_NOVAMENTE:
            # 429 costuma ser o limite por minuto da camada gratuita: espera mais
            espera = 15 * tentativa if resp.status_code == 429 else 2**tentativa
            log.warning("API respondeu %d. Aguardando %ds (tentativa %d/%d)",
                        resp.status_code, espera, tentativa, tentativas)
            time.sleep(espera)
            continue

        # Erros como 400/401/403 não adianta repetir
        raise ErroAPI(f"API respondeu {resp.status_code}: {resp.text[:300]}")

    raise ErroAPI(
        "Sem resposta da API após várias tentativas. Na camada gratuita, o limite diário "
        "pode ter acabado: tente novamente mais tarde."
    )


def _chamar_gemini(prompt: str, system: str) -> str:
    chave = os.getenv("GEMINI_API_KEY")
    if not chave:
        raise ErroAPI("GEMINI_API_KEY não definida. Crie o arquivo .env (veja .env.example).")

    modelo = os.getenv("GEMINI_MODEL", GEMINI_MODELO_PADRAO)
    corpo = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        # Margem alta: modelos com "raciocínio" gastam parte do limite pensando
        "generationConfig": {"maxOutputTokens": 8192},
    }
    headers = {"x-goog-api-key": chave, "content-type": "application/json"}
    dados = _post_json(GEMINI_URL.format(modelo=modelo), headers, corpo)

    candidatos = dados.get("candidates") or []
    if not candidatos:
        raise ErroAPI(f"Resposta sem conteúdo (possível bloqueio): {dados.get('promptFeedback')}")
    partes = candidatos[0].get("content", {}).get("parts", [])
    texto = "".join(p.get("text", "") for p in partes).strip()
    if not texto:
        raise ErroAPI(f"Resposta vazia (motivo: {candidatos[0].get('finishReason')}).")
    if candidatos[0].get("finishReason") == "MAX_TOKENS":
        log.warning("A resposta foi cortada pelo limite de tamanho; reduza o trecho enviado.")
    return texto


def _chamar_anthropic(prompt: str, system: str, max_tokens: int) -> str:
    chave = os.getenv("ANTHROPIC_API_KEY")
    if not chave:
        raise ErroAPI("ANTHROPIC_API_KEY não definida. Crie o arquivo .env (veja .env.example).")

    corpo = {
        "model": os.getenv("ANTHROPIC_MODEL", ANTHROPIC_MODELO_PADRAO),
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {"x-api-key": chave, "anthropic-version": ANTHROPIC_VERSION,
               "content-type": "application/json"}
    dados = _post_json(ANTHROPIC_URL, headers, corpo)
    blocos = dados.get("content", [])
    return "".join(b.get("text", "") for b in blocos if b.get("type") == "text").strip()


def _chamar_ia(prompt: str, system: str, max_tokens: int = 4096) -> str:
    """Envia o prompt ao provedor escolhido e devolve o texto da resposta."""
    if _escolher_provedor() == "gemini":
        return _chamar_gemini(prompt, system)
    return _chamar_anthropic(prompt, system, max_tokens)


def dividir_em_blocos(texto: str, limite: int) -> list[str]:
    """Divide o texto em blocos de até `limite` caracteres, respeitando parágrafos."""
    blocos: list[str] = []
    atual = ""
    for paragrafo in texto.split("\n\n"):
        # Parágrafo gigante (OCR sem quebras): corta no limite
        while len(paragrafo) > limite:
            if atual:
                blocos.append(atual)
                atual = ""
            blocos.append(paragrafo[:limite])
            paragrafo = paragrafo[limite:]
        if len(atual) + len(paragrafo) + 2 > limite and atual:
            blocos.append(atual)
            atual = paragrafo
        else:
            atual = f"{atual}\n\n{paragrafo}" if atual else paragrafo
    if atual:
        blocos.append(atual)
    return blocos


def traduzir(texto: str, idioma_destino: str = "português do Brasil") -> str:
    """Traduz o texto, bloco a bloco, preservando os parágrafos."""
    system = (
        f"Você é um tradutor profissional para {idioma_destino}. O texto veio de OCR e pode "
        "ter pequenos erros de reconhecimento; corrija-os quando forem óbvios. Preserve os "
        "parágrafos e a terminologia técnica. Responda SOMENTE com a tradução, sem comentários."
    )
    blocos = dividir_em_blocos(texto, limite=6000)
    traduzidos = []
    for i, bloco in enumerate(blocos, start=1):
        log.info("  Traduzindo bloco %d/%d", i, len(blocos))
        traduzidos.append(_chamar_ia(bloco, system))
    return "\n\n".join(traduzidos)


def resumir(texto: str) -> str:
    """Gera um material de estudo em Markdown: ideia central, tópicos, conceitos e perguntas."""
    system_parcial = (
        "Você ajuda estudantes. Extraia as ideias principais do trecho em tópicos curtos, "
        "com suas próprias palavras, mantendo termos técnicos e dados importantes. "
        "Responda em português do Brasil."
    )
    system_final = (
        "Você é um tutor que cria material de estudo. O texto foi extraído de um PDF por OCR "
        "e pode ter pequenos erros. Sua tarefa NÃO é copiar nem reescrever o texto frase por "
        "frase: é SINTETIZAR e EXPLICAR para quem vai estudar.\n"
        "Regras:\n"
        "- Reescreva tudo com suas próprias palavras, sem copiar frases do material.\n"
        "- O resumo deve ser bem mais curto que o original.\n"
        "- Explique o porquê das coisas e as relações entre as ideias.\n"
        "- Use apenas informações do material: não invente dados, números ou fatos. Você pode "
        "explicar termos gerais para torná-los compreensíveis.\n"
        "- Se o material for curto ou só tiver tópicos, explique o sentido de cada tópico de "
        "forma didática em vez de repeti-lo.\n"
        "Responda em português do Brasil, em Markdown, exatamente com estas seções:\n"
        "## Ideia central\n(2 a 3 frases)\n"
        "## Resumo em tópicos\n(5 a 8 tópicos, cada um com uma ideia sintetizada)\n"
        "## Conceitos-chave\n(termos importantes, cada um com explicação simples de 1 a 2 frases)\n"
        "## Como tudo se conecta\n(um parágrafo curto ligando as ideias)\n"
        "## Perguntas de revisão\n(5 perguntas que exijam compreensão, não só memorização, "
        "cada uma seguida de resposta curta)"
    )

    blocos = dividir_em_blocos(texto, limite=30000)
    if len(blocos) == 1:
        return _chamar_ia(blocos[0], system_final)

    # Textos longos: resume cada parte e depois consolida (estratégia map-reduce)
    parciais = []
    for i, bloco in enumerate(blocos, start=1):
        log.info("  Resumindo parte %d/%d", i, len(blocos))
        parciais.append(_chamar_ia(bloco, system_parcial))
    return _chamar_ia("\n\n".join(parciais), system_final)
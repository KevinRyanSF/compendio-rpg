"""Baseline: um único LLM, uma chamada por página, sem agentes e sem buscar contexto.

É a "solução mais simples que serve de comparação" pedida na Sprint 0. Tudo o
que vier depois (mapeador, especialistas, busca de contexto, validador) precisa
ganhar dele no gold set — em precisão, cobertura ou custo — para se justificar.

O que ele faz de propósito:
  * vê uma página por vez: entradas que atravessam a página ficam incompletas;
  * não tem esquema por sistema: as chaves dos atributos são as que o modelo
    escolher, copiadas do livro (a avaliação traduz para as canônicas);
  * junta entradas com o mesmo nome (como o banco faria ao gravar).
"""

from __future__ import annotations

import html
import re
from typing import Callable, Literal

from pydantic import BaseModel, Field

from .avaliacao import norm
from .llm import LLM, SaidaTruncada
from .schema import canonico

INSTRUCOES = """Você extrai conteúdo MECÂNICO de páginas de livros de RPG para montar um compêndio.
Sistema: {sistema}.

Extraia TODA entrada de jogo que aparece na página: magias/rituais, armas, itens, munições,
regras, condições, criaturas com estatísticas, opções de personagem.
NÃO extraia: narrativa, lore, história, exemplos de jogo, textos introdutórios, títulos de capítulo.
Se a página não tiver nenhuma entrada de jogo, devolva a lista vazia.

Para cada entrada:
- nome: exatamente como está no livro.
- categoria_canonica: uma das opções do formato.
- categoria_no_livro: como o livro chama esse tipo de coisa (ex.: Ritual, Magia, Arma, Condição).
- atributos: cada campo de regra que o livro dá para a entrada (ex.: Alcance, Duração, Dano,
  Crítico, Círculo, Escola). Chave em snake_case sem acento (ex.: tempo_de_conjuracao);
  valor copiado do livro, sem reescrever.
- descricao: o efeito mecânico em até duas frases.

Se uma entrada começa ou termina fora da página, extraia o que estiver visível.
Escreva em português com acentos normais (UTF-8): nada de entidades HTML (&iacute;) nem apóstrofos no lugar de acento."""

MAX_TOKENS = 16_384  # páginas de tabela (ex.: 37 armas) passam fácil de 4 mil tokens de saída


def limpar(texto: str) -> str:
    """Conserta entidades HTML que o modelo às vezes devolve (F&iacute;sico -> Físico)."""
    return re.sub(r"\s+", " ", html.unescape(texto or "")).strip()


class Atributo(BaseModel):
    chave: str
    valor: str


class Entrada(BaseModel):
    nome: str
    categoria_canonica: Literal[tuple(canonico.CATEGORIAS)]  # type: ignore[valid-type]
    categoria_no_livro: str
    atributos: list[Atributo] = Field(default_factory=list)
    descricao: str = ""


class Lote(BaseModel):
    entradas: list[Entrada] = Field(default_factory=list)


def _para_saida(e: Entrada, sistema: str, pagina: int) -> dict:
    atributos: dict[str, str] = {}
    for a in e.atributos:
        chave = canonico.slug(a.chave) if a.chave.strip() else "atributo"
        valor = limpar(a.valor)
        atributos[chave] = f"{atributos[chave]}; {valor}" if chave in atributos else valor
    return {"sistema": sistema, "categoria_canonica": e.categoria_canonica, "categoria_no_livro": limpar(e.categoria_no_livro),
            "nome": limpar(e.nome), "paginas": [pagina, pagina], "atributos": atributos, "descricao": limpar(e.descricao)}


def _metades(texto: str) -> list[str]:
    linhas = texto.splitlines()
    meio = len(linhas) // 2
    return ["\n".join(linhas[:meio]), "\n".join(linhas[meio:])]


def estruturado_com_divisao(llm: LLM, *, etapa: str, instrucoes: str, prefixo: str, texto: str, schema,
                            modelo: str | None, nivel: int = 0) -> list[dict]:
    """Uma chamada estruturada; se a resposta não couber, divide o texto ao meio (até 2 vezes).

    Devolve a lista de respostas (uma por parte)."""
    try:
        r = llm.estruturado(etapa=etapa, instrucoes=instrucoes, conteudo=f"{prefixo}\n{texto}",
                            schema=schema, modelo=modelo, max_tokens=MAX_TOKENS)
    except SaidaTruncada:
        if nivel >= 2 or len(texto.splitlines()) < 4:
            raise
        return [d for parte in _metades(texto) for d in estruturado_com_divisao(
            llm, etapa=etapa, instrucoes=instrucoes, prefixo=prefixo, texto=parte, schema=schema,
            modelo=modelo, nivel=nivel + 1)]
    return [r.dados]


def juntar_mesmo_nome(entradas: list[dict]) -> list[dict]:
    """Mesma entrada vista em duas páginas (ou repetida na tabela) vira uma só."""
    juntas: dict[tuple[str, str], dict] = {}
    for e in entradas:
        k = (e["categoria_canonica"], norm(e["nome"]))
        if k not in juntas:
            juntas[k] = {**e, "atributos": dict(e["atributos"])}
            continue
        j = juntas[k]
        j["paginas"] = [min(j["paginas"][0], e["paginas"][0]), max(j["paginas"][1], e["paginas"][1])]
        for chave, valor in e["atributos"].items():
            if j["atributos"].get(chave) in (None, "", []):
                j["atributos"][chave] = valor
        if len(e.get("descricao", "")) > len(j.get("descricao", "")):
            j["descricao"] = e["descricao"]
    return list(juntas.values())


def extrair(llm: LLM, paginas: dict[int, str], *, sistema: str, modelo: str | None = None,
            ao_progresso: Callable[[int, int, int], None] | None = None) -> list[dict]:
    """`paginas`: {número da página (1-based): texto limpo}. Devolve entradas no formato de saída."""
    instrucoes = INSTRUCOES.format(sistema=sistema)
    brutas: list[dict] = []
    for i, (pagina, texto) in enumerate(sorted(paginas.items()), start=1):
        if texto.strip():
            respostas = estruturado_com_divisao(llm, etapa="baseline", instrucoes=instrucoes,
                                                prefixo=f"[Página {pagina}]", texto=texto, schema=Lote, modelo=modelo)
            entradas = [e for d in respostas for e in Lote.model_validate(d).entradas]
            brutas += [_para_saida(e, sistema, pagina) for e in entradas if e.nome.strip()]
        if ao_progresso:
            ao_progresso(i, len(paginas), len(brutas))
    return juntar_mesmo_nome(brutas)

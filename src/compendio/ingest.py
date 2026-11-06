"""PDF -> trechos (chunks) guiados pelo índice do livro.

O índice (bookmarks) é a peça mais barata do livro: poucas centenas de tokens que
dizem onde está cada coisa. Por isso cada chunk carrega o caminho da seção
("Capítulo 4 > Rituais > Sangue"), e o Mapeador pode decidir o destino de um
trecho só olhando o índice, sem ler o texto.

Funciona com qualquer objeto no formato do `pdfscope.PdfDocument`
(`toc`, `page_count`, `page_text_raw`, `title`) — os testes usam um documento falso.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import median
from typing import Iterable, Protocol


class DocumentoPdf(Protocol):
    @property
    def page_count(self) -> int: ...
    @property
    def title(self) -> str: ...
    @property
    def toc(self) -> list: ...
    def page_text_raw(self, page: int) -> str: ...


@dataclass
class Chunk:
    id: str
    livro: str
    secao: str
    caminho: list[str]
    nivel: int
    pagina_inicio: int  # 1-based, como o leitor vê
    pagina_fim: int  # 1-based, inclusivo
    texto: str
    agrupa: list[str] = field(default_factory=list)  # seções curtas que dividiam a mesma página
    parte: int = 1
    partes: int = 1

    @property
    def caracteres(self) -> int:
        return len(self.texto)

    @property
    def rotulo(self) -> str:
        sufixo = f" ({self.parte}/{self.partes})" if self.partes > 1 else ""
        return " > ".join(self.caminho) + sufixo


def _id(livro: str, caminho: list[str], inicio: int, parte: int) -> str:
    base = f"{livro}|{'>'.join(caminho)}|{inicio}|{parte}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]


def _dividir(texto: str, max_chars: int) -> list[str]:
    """Divide em pedaços <= max_chars, preferindo quebras de parágrafo e de linha."""
    if len(texto) <= max_chars:
        return [texto]
    partes: list[str] = []
    resto = texto
    while len(resto) > max_chars:
        corte = resto.rfind("\n\n", 0, max_chars)
        if corte < max_chars // 2:
            corte = resto.rfind("\n", 0, max_chars)
        if corte < max_chars // 2:
            corte = max_chars
        partes.append(resto[:corte].strip())
        resto = resto[corte:]
    if resto.strip():
        partes.append(resto.strip())
    return partes


def _secoes(doc: DocumentoPdf, paginas_sem_indice: int) -> Iterable[tuple[list[str], int, int, int, list[str]]]:
    """(caminho, nível, início 0-based, fim exclusivo, títulos agrupados)."""
    toc = list(doc.toc or [])
    if not toc:
        for ini in range(0, doc.page_count, paginas_sem_indice):
            fim = min(ini + paginas_sem_indice, doc.page_count)
            yield [f"páginas {ini + 1}–{fim}"], 1, ini, fim, []
        return

    if toc[0].page > 0:  # capa, créditos... antes da primeira entrada
        yield ["(antes do índice)"], 1, 0, toc[0].page, []

    pilha: list[tuple[int, str]] = []
    agrupados: list[str] = []
    for i, entrada in enumerate(toc):
        while pilha and pilha[-1][0] >= entrada.level:
            pilha.pop()
        pilha.append((entrada.level, entrada.title.strip()))
        fim = toc[i + 1].page if i + 1 < len(toc) else doc.page_count
        if fim <= entrada.page:
            # a próxima entrada começa na mesma página: esta não tem páginas só dela
            if i + 1 < len(toc) and toc[i + 1].level <= entrada.level:
                agrupados.append(entrada.title.strip())
            continue
        yield [t for _, t in pilha], entrada.level, entrada.page, min(fim, doc.page_count), agrupados
        agrupados = []


def chunks_por_indice(
    doc: DocumentoPdf, *, max_chars: int = 12_000, paginas_sem_indice: int = 4, livro: str | None = None
) -> list[Chunk]:
    livro = livro or doc.title
    chunks: list[Chunk] = []
    for caminho, nivel, ini, fim, agrupa in _secoes(doc, paginas_sem_indice):
        texto = "\n".join(doc.page_text_raw(p) for p in range(ini, fim)).strip()
        if not texto:
            continue
        pedacos = _dividir(texto, max_chars)
        for n, pedaco in enumerate(pedacos, start=1):
            chunks.append(
                Chunk(
                    id=_id(livro, caminho, ini, n),
                    livro=livro,
                    secao=caminho[-1],
                    caminho=caminho,
                    nivel=nivel,
                    pagina_inicio=ini + 1,
                    pagina_fim=fim,
                    texto=pedaco,
                    agrupa=list(agrupa),
                    parte=n,
                    partes=len(pedacos),
                )
            )
    return chunks


def resumo_do_indice(doc: DocumentoPdf, max_entradas: int = 400) -> str:
    """O índice em texto compacto — é isso que o Mapeador lê, não o livro."""
    toc = list(doc.toc or [])
    if not toc:
        return f"(sem índice) {doc.page_count} páginas"
    linhas = []
    for i, e in enumerate(toc[:max_entradas]):
        fim = toc[i + 1].page if i + 1 < len(toc) else doc.page_count
        linhas.append(f"{'  ' * (e.level - 1)}- {e.title.strip()} (p. {e.page + 1}–{max(fim, e.page + 1)})")
    if len(toc) > max_entradas:
        linhas.append(f"... (+{len(toc) - max_entradas} entradas)")
    return "\n".join(linhas)


def diagnostico(doc: DocumentoPdf, chunks: list[Chunk]) -> dict:
    """Responde às perguntas do passo 1: tem índice? os chunks têm tamanho razoável?"""
    tamanhos = [c.caracteres for c in chunks] or [0]
    maiores = sorted(chunks, key=lambda c: c.caracteres, reverse=True)[:5]
    return {
        "livro": doc.title,
        "paginas": doc.page_count,
        "entradas_no_indice": len(doc.toc or []),
        "niveis_do_indice": sorted({e.level for e in (doc.toc or [])}),
        "chunks": len(chunks),
        "chunks_divididos": sum(1 for c in chunks if c.partes > 1),
        "caracteres_mediana": int(median(tamanhos)),
        "caracteres_max": max(tamanhos),
        "tokens_estimados_livro": sum(tamanhos) // 4,
        "maiores": [f"{c.rotulo} — {c.caracteres} car." for c in maiores],
    }


def salvar_jsonl(chunks: list[Chunk], caminho: str | Path) -> Path:
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(asdict(c), ensure_ascii=False) + "\n")
    return caminho


def carregar_jsonl(caminho: str | Path) -> list[Chunk]:
    with Path(caminho).open(encoding="utf-8") as f:
        return [Chunk(**json.loads(linha)) for linha in f if linha.strip()]

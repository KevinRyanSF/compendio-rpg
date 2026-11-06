from dataclasses import dataclass

from compendio.ingest import carregar_jsonl, chunks_por_indice, diagnostico, resumo_do_indice, salvar_jsonl


@dataclass(frozen=True)
class Toc:
    level: int
    title: str
    page: int  # zero-based, como no pdfscope


class DocFalso:
    """Imita o pdfscope.PdfDocument sem precisar do PyMuPDF."""

    def __init__(self, paginas: list[str], toc: list[Toc], title: str = "Livro Teste"):
        self._paginas = paginas
        self.toc = toc
        self.title = title

    @property
    def page_count(self) -> int:
        return len(self._paginas)

    def page_text_raw(self, page: int) -> str:
        return self._paginas[page]


def livro():
    paginas = [
        "Capa e créditos",
        "Capítulo 1 — Regras básicas",
        "Testes e dificuldades",
        "Capítulo 2 — Rituais. Rituais de Sangue começam aqui",
        "Rituais de Morte",
        "Apêndice",
    ]
    toc = [
        Toc(1, "Regras", 1),
        Toc(1, "Rituais", 3),
        Toc(2, "Sangue", 3),  # começa na mesma página do pai
        Toc(2, "Morte", 4),
        Toc(1, "Apêndice", 5),
    ]
    return DocFalso(paginas, toc)


def test_chunks_seguem_o_indice_com_caminho():
    chunks = chunks_por_indice(livro())
    rotulos = [c.rotulo for c in chunks]
    assert rotulos == ["(antes do índice)", "Regras", "Rituais > Sangue", "Rituais > Morte", "Apêndice"]
    regras = chunks[1]
    assert (regras.pagina_inicio, regras.pagina_fim) == (2, 3)
    assert "Testes e dificuldades" in regras.texto


def test_secoes_irmas_na_mesma_pagina_sao_agrupadas():
    doc = DocFalso(["A e B na mesma página", "C"], [Toc(1, "A", 0), Toc(1, "B", 0), Toc(1, "C", 1)])
    chunks = chunks_por_indice(doc)
    assert [c.secao for c in chunks] == ["B", "C"]
    assert chunks[0].agrupa == ["A"]


def test_sem_indice_usa_janelas_de_paginas():
    doc = DocFalso([f"página {i}" for i in range(10)], [])
    chunks = chunks_por_indice(doc, paginas_sem_indice=4)
    assert [c.secao for c in chunks] == ["páginas 1–4", "páginas 5–8", "páginas 9–10"]


def test_secao_grande_e_dividida():
    texto = "\n\n".join(["parágrafo " * 50] * 10)  # ~5000 caracteres
    doc = DocFalso([texto], [Toc(1, "Grande", 0)])
    chunks = chunks_por_indice(doc, max_chars=1200)
    assert len(chunks) > 1
    assert all(c.caracteres <= 1200 for c in chunks)
    assert chunks[0].partes == len(chunks)
    assert len({c.id for c in chunks}) == len(chunks)


def test_resumo_do_indice_e_diagnostico():
    doc = livro()
    resumo = resumo_do_indice(doc)
    assert "  - Sangue (p. 4–4)" in resumo
    diag = diagnostico(doc, chunks_por_indice(doc))
    assert diag["entradas_no_indice"] == 5
    assert diag["niveis_do_indice"] == [1, 2]


def test_jsonl_ida_e_volta(tmp_path):
    chunks = chunks_por_indice(livro())
    caminho = salvar_jsonl(chunks, tmp_path / "c.jsonl")
    assert carregar_jsonl(caminho) == chunks


def test_remove_marca_dagua_e_rodape_repetidos():
    marca = "Fulano de Tal fulano@exemplo.com"
    paginas = [f"{i + 10}\nConteúdo único da página {i}\nRitual {i}{marca if i % 2 else ''}\n{marca}" for i in range(8)]
    doc = DocFalso(paginas, [Toc(1, "Tudo", 0)])
    texto = "\n".join(c.texto for c in chunks_por_indice(doc))
    assert "fulano@exemplo.com" not in texto
    assert "Conteúdo único da página 3" in texto
    assert "Ritual 3" in texto  # a marca colada no fim da linha sai, o conteúdo fica


def test_hifen_suave_some():
    doc = DocFalso(["liga￾mentos e multi­plicador"], [])
    assert chunks_por_indice(doc)[0].texto == "ligamentos e multiplicador"

"""Revisor visual do gold set e das saídas: `uv run compendio revisar`.

Servidor HTTP local (só biblioteca padrão) que mostra a página do PDF ao lado das
entradas do gabarito, confere se cada valor aparece no texto da página, permite
editar/marcar como conferido e salva de volta no `.jsonl`. Também compara uma
saída do sistema com o gabarito, com as mesmas métricas do relatório.

Roda só na sua máquina (127.0.0.1): os PDFs e o gabarito não saem dela.
"""

from __future__ import annotations

import json
import re
import threading
import webbrowser
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

from . import avaliacao
from .ingest import _limpar, linhas_repetidas

PAGINA = Path(__file__).with_name("revisor.html")


def _abrir_pdf_padrao(caminho: Path):
    from pdfscope import PdfDocument

    return PdfDocument(caminho)


class Projeto:
    """Acesso aos arquivos do projeto: recortes, gold, saídas e PDFs."""

    def __init__(self, raiz: Path, abrir_pdf: Callable[[Path], Any] = _abrir_pdf_padrao):
        self.raiz = Path(raiz)
        self.gold_dir = self.raiz / "gold"
        self._abrir_pdf = abrir_pdf
        self._docs: dict[str, Any] = {}
        self._remover: dict[str, set[str]] = {}
        self._trava = threading.Lock()

    # ------------------------------------------------------------ recortes
    def recortes(self) -> dict:
        return json.loads((self.gold_dir / "recortes.json").read_text(encoding="utf-8"))

    def livro(self, chave: str) -> dict:
        livros = self.recortes()["livros"]
        if chave not in livros:
            raise KeyError(chave)
        return livros[chave]

    def paginas_do_recorte(self, chave: str) -> set[int]:
        paginas: set[int] = set()
        for r in self.livro(chave)["recortes"]:
            paginas |= set(range(r["paginas"][0], r["paginas"][1] + 1))
        return paginas

    # ----------------------------------------------------------------- pdf
    def caminho_pdf(self, chave: str) -> Path:
        return self.raiz / "livros" / self.livro(chave)["arquivo"]

    def doc(self, chave: str):
        with self._trava:
            if chave not in self._docs:
                doc = self._abrir_pdf(self.caminho_pdf(chave))
                self._docs[chave] = doc
                self._remover[chave] = linhas_repetidas(doc)
            return self._docs[chave]

    def texto(self, chave: str, pagina: int) -> str:
        """Texto da página (1-based) já limpo, igual ao que a ingestão manda para o LLM."""
        doc = self.doc(chave)
        if not 1 <= pagina <= doc.page_count:
            return ""
        with self._trava:
            return _limpar(doc.page_text_raw(pagina - 1), self._remover[chave])

    def png(self, chave: str, pagina: int, zoom: float, grifo: str | None) -> bytes:
        from pdfscope import RenderOptions

        doc = self.doc(chave)
        with self._trava:
            return doc.render_page_png(pagina - 1, RenderOptions(zoom=zoom, highlight=grifo or None))

    # ---------------------------------------------------------------- gold
    def caminho_gold(self, chave: str) -> Path:
        return self.gold_dir / self.livro(chave)["gold"]

    def gold(self, chave: str) -> list[dict]:
        return avaliacao.ler_jsonl(self.caminho_gold(chave))

    def salvar_gold(self, chave: str, linhas: list[dict]) -> None:
        if not isinstance(linhas, list) or not all(isinstance(d, dict) and d.get("tipo") for d in linhas):
            raise ValueError("cada linha precisa ser um objeto com 'tipo'")
        avaliacao.salvar_jsonl(linhas, self.caminho_gold(chave))

    def verificacao(self, chave: str, linhas: list[dict]) -> list[dict | None]:
        if not self.caminho_pdf(chave).exists():
            return [None for _ in linhas]
        resultado = []
        for d in linhas:
            ini, fim = (d.get("paginas") or [0, 0])[0], (d.get("paginas") or [0, 0])[-1]
            if d.get("fora_do_recorte"):  # o que falta está na página vizinha
                ini, fim = max(1, ini - 1), fim + 1
            texto = "\n".join(self.texto(chave, p) for p in range(ini, fim + 1))
            resultado.append(avaliacao.verificar_no_texto(d, texto))
        return resultado

    # -------------------------------------------------------------- saídas
    def saidas(self) -> list[str]:
        achados = []
        for pasta in (self.raiz / "data" / "saidas", self.gold_dir / "exemplos"):
            if pasta.is_dir():
                achados += [str(p.relative_to(self.raiz)).replace("\\", "/") for p in sorted(pasta.glob("*.jsonl"))]
        return achados

    def comparar(self, chave: str, saida_rel: str) -> dict:
        caminho = (self.raiz / saida_rel).resolve()
        if self.raiz.resolve() not in caminho.parents or caminho.suffix != ".jsonl":
            raise ValueError("saída fora do projeto")
        sistema = self.livro(chave)["sistema"]
        linhas = [s for s in avaliacao.ler_jsonl(caminho) if s.get("sistema", sistema) == sistema]
        return avaliacao.comparar(self.gold(chave), linhas, self.paginas_do_recorte(chave)).como_dict()

    def estado(self) -> dict:
        livros = {}
        for chave, livro in self.recortes()["livros"].items():
            pdf = self.caminho_pdf(chave)
            paginas = None
            if pdf.exists():
                try:
                    paginas = self.doc(chave).page_count
                except Exception:  # noqa: BLE001 - PDF ilegível não derruba o revisor
                    paginas = None
            livros[chave] = {**livro, "pdf_existe": pdf.exists(), "paginas_total": paginas}
        return {"livros": livros, "saidas": self.saidas()}


class Handler(BaseHTTPRequestHandler):
    projeto: Projeto

    def log_message(self, *_a):  # silencioso
        pass

    def _json(self, dados: Any, status: int = 200) -> None:
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _erro(self, erro: Exception, status: int = 400) -> None:
        self._json({"erro": f"{type(erro).__name__}: {erro}"}, status)

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        partes = [unquote(p) for p in url.path.strip("/").split("/") if p]
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        p = self.projeto
        try:
            if not partes:
                corpo = PAGINA.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(corpo)))
                self.end_headers()
                self.wfile.write(corpo)
            elif partes == ["api", "estado"]:
                self._json(p.estado())
            elif partes[:2] == ["api", "gold"] and len(partes) == 3:
                linhas = p.gold(partes[2])
                self._json({"linhas": linhas, "verificacao": p.verificacao(partes[2], linhas)})
            elif partes[:2] == ["api", "texto"] and len(partes) == 4:
                self._json({"texto": p.texto(partes[2], int(partes[3]))})
            elif partes[:2] == ["api", "pagina"] and len(partes) == 4:
                n = int(re.sub(r"\.png$", "", partes[3]))
                png = p.png(partes[2], n, float(q.get("zoom", 1.6)), q.get("grifo"))
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(png)))
                self.send_header("Cache-Control", "max-age=300")
                self.end_headers()
                self.wfile.write(png)
            elif partes[:2] == ["api", "comparar"] and len(partes) == 3:
                self._json(p.comparar(partes[2], q["saida"]))
            else:
                self._json({"erro": "não encontrado"}, HTTPStatus.NOT_FOUND)
        except KeyError as e:
            self._erro(e, HTTPStatus.NOT_FOUND)
        except Exception as e:  # noqa: BLE001
            self._erro(e)

    def do_POST(self) -> None:  # noqa: N802
        partes = [unquote(p) for p in urlparse(self.path).path.strip("/").split("/") if p]
        try:
            tamanho = int(self.headers.get("Content-Length", 0))
            corpo = json.loads(self.rfile.read(tamanho) or b"{}")
            if partes[:2] == ["api", "gold"] and len(partes) == 3:
                self.projeto.salvar_gold(partes[2], corpo["linhas"])
                linhas = self.projeto.gold(partes[2])
                self._json({"ok": True, "linhas": linhas, "verificacao": self.projeto.verificacao(partes[2], linhas)})
            else:
                self._json({"erro": "não encontrado"}, HTTPStatus.NOT_FOUND)
        except Exception as e:  # noqa: BLE001
            self._erro(e)


def criar_servidor(raiz: Path, porta: int = 8765, abrir_pdf: Callable[[Path], Any] = _abrir_pdf_padrao):
    projeto = Projeto(raiz, abrir_pdf)
    handler = type("HandlerDoProjeto", (Handler,), {"projeto": projeto})
    return ThreadingHTTPServer(("127.0.0.1", porta), handler)


def rodar(raiz: Path, porta: int = 8765, abrir_navegador: bool = True) -> None:
    servidor = criar_servidor(raiz, porta)
    url = f"http://127.0.0.1:{servidor.server_address[1]}/"
    print(f"Revisor em {url}  (Ctrl+C para sair)")
    if abrir_navegador:
        threading.Timer(0.5, partial(webbrowser.open, url)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nencerrado")
    finally:
        servidor.server_close()

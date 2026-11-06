import csv
import json
import shutil
from pathlib import Path

from compendio import baseline, experimento
from compendio.config import Config
from compendio.llm import GeminiLLM, schema_para_gemini

RAIZ = Path(__file__).parent.parent


class GeminiFalso:
    """Responde por página: um ritual na 133, o mesmo ritual continuando na 134, nada no resto."""

    def __init__(self):
        self.models = self
        self.chamadas = []

    def generate_content(self, **kw):
        from types import SimpleNamespace
        self.chamadas.append(kw)
        pagina = int(kw["contents"].split("]")[0].split()[-1])
        entradas = []
        if pagina == 133:
            entradas = [{"nome": "Arma Atroz", "categoria_canonica": "efeito_sobrenatural", "categoria_no_livro": "Ritual",
                         "atributos": [{"chave": "Círculo", "valor": "1"}, {"chave": "Duração", "valor": "sustentada"}],
                         "descricao": "+2 em testes de ataque."}]
        if pagina == 134:
            entradas = [{"nome": "arma atroz", "categoria_canonica": "efeito_sobrenatural", "categoria_no_livro": "Ritual",
                         "atributos": [{"chave": "Alcance", "valor": "toque"}], "descricao": "curta"}]
        return SimpleNamespace(text=json.dumps({"entradas": entradas}),
                               usage_metadata=SimpleNamespace(prompt_token_count=500, candidates_token_count=40,
                                                              cached_content_token_count=0, thoughts_token_count=0))


def cfg():
    return Config(api_key="x", modelo_rapido="rapido-teste", modelo_forte="forte-teste", max_tokens=1000,
                  banco=":memory:", provedor="gemini")


def test_schema_do_lote_vai_para_o_gemini():
    schema = schema_para_gemini(baseline.Lote)
    item = schema["properties"]["entradas"]["items"]
    assert "efeito_sobrenatural" in item["properties"]["categoria_canonica"]["enum"]


def test_juntar_mesmo_nome_entre_paginas():
    llm = GeminiLLM(cfg(), cliente=GeminiFalso())
    saida = baseline.extrair(llm, {133: "texto", 134: "texto", 135: ""}, sistema="Ordem Paranormal")
    assert len(saida) == 1
    e = saida[0]
    assert e["paginas"] == [133, 134]
    assert e["atributos"] == {"circulo": "1", "duracao": "sustentada", "alcance": "toque"}
    assert e["descricao"] == "+2 em testes de ataque."
    assert len(llm.registro.chamadas) == 2  # página vazia não gasta chamada


def test_rodar_avaliar_e_registrar(tmp_path):
    shutil.copytree(RAIZ / "gold", tmp_path / "gold")

    class Doc:
        page_count = 330

        def page_text_raw(self, p):
            return f"{p + 1}\\nconteúdo da página {p + 1}"

    llm = GeminiLLM(cfg(), cliente=GeminiFalso())
    saida, meta = experimento.rodar(tmp_path, "ordem-paranormal", cfg(), llm=llm, abrir_pdf=lambda c: Doc())
    assert saida.name == "baseline-gemini-rapido-ordem-paranormal.jsonl"
    assert meta["paginas"] == 6 and meta["chamadas"] == 6 and meta["tokens_entrada"] == 3000

    m = experimento.avaliar(tmp_path, "ordem-paranormal", saida)
    assert m["acertos"] == 1 and m["sobraram"] == 0
    arquivo = experimento.registrar(tmp_path, meta, m, saida)
    [linha] = list(csv.DictReader(arquivo.open(encoding="utf-8")))
    assert linha["estrategia"] == "baseline" and linha["acertos"] == "1"
    assert linha["saida"] == "data/saidas/baseline-gemini-rapido-ordem-paranormal.jsonl"
    assert "Arma Atroz" not in arquivo.read_text(encoding="utf-8")  # métricas sem conteúdo do livro

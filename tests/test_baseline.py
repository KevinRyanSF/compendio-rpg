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


class GeminiQueCorta:
    """Corta a resposta quando a página é grande; responde normal com meia página."""

    def __init__(self):
        self.models = self
        self.tamanhos = []

    def generate_content(self, **kw):
        from types import SimpleNamespace
        texto = kw["contents"]
        self.tamanhos.append(len(texto.splitlines()))
        uso = SimpleNamespace(prompt_token_count=10, candidates_token_count=10, cached_content_token_count=0,
                              thoughts_token_count=0)
        if len(texto.splitlines()) > 6:
            return SimpleNamespace(text='{"entradas": [{"nome": "Ada', usage_metadata=uso,
                                   candidates=[SimpleNamespace(finish_reason="FinishReason.MAX_TOKENS")])
        nomes = [l for l in texto.splitlines()[1:] if l.strip()]
        entradas = [{"nome": n, "categoria_canonica": "equipamento", "categoria_no_livro": "Arma",
                     "atributos": [{"chave": "Preço", "valor": "2 po"}], "descricao": "F&iacute;sico"} for n in nomes]
        return SimpleNamespace(text=json.dumps({"entradas": entradas}), usage_metadata=uso, candidates=[])


def test_pagina_grande_e_dividida_quando_a_resposta_corta():
    falso = GeminiQueCorta()
    llm = GeminiLLM(cfg(), cliente=falso)
    texto = "\n".join(f"Arma {i}" for i in range(10))
    saida = baseline.extrair(llm, {150: texto}, sistema="D&D 5e")
    assert sorted(e["nome"] for e in saida) == sorted(f"Arma {i}" for i in range(10))
    assert falso.tamanhos[0] == 11  # primeira tentativa: página inteira (+ linha do cabeçalho)
    assert saida[0]["descricao"] == "Físico"  # entidade HTML consertada


def test_valor_certo_com_outro_nome_de_campo():
    from compendio import avaliacao
    gold = [{"tipo": "entrada", "nome": "Acha", "categoria_canonica": "equipamento",
             "atributos": {"tipo_dano": "C", "critico": "x3"}, "paginas": [65, 65]}]
    saida = [{"nome": "Acha", "categoria_canonica": "equipamento", "atributos": {"tipo": "C", "critico": "x2"},
              "paginas": [65, 65]}]
    r = avaliacao.comparar(gold, saida)
    tipo, crit = r.itens[0].atributos
    assert not tipo.bate and tipo.chave_obtida == "tipo"
    assert not crit.bate and crit.chave_obtida is None
    assert r.metricas["atributos_corretos"] == 0.0 and r.metricas["valor_em_outra_chave"] == 0.5


def test_registrar_atualiza_cabecalho_antigo(tmp_path):
    arq = tmp_path / "resultados" / "resultados.csv"
    arq.parent.mkdir()
    arq.write_text("data,livro,acertos\n2026-01-01,ordem-paranormal,50\n", encoding="utf-8")
    (tmp_path / "data" / "saidas").mkdir(parents=True)
    saida = tmp_path / "data" / "saidas" / "x.jsonl"
    experimento.registrar(tmp_path, {"livro": "dnd-5e"}, {"acertos": 40, "valor_em_outra_chave": 0.2}, saida)
    linhas = list(csv.DictReader(arq.open(encoding="utf-8")))
    assert [l["acertos"] for l in linhas] == ["50", "40"]
    assert linhas[1]["valor_em_outra_chave"] == "0.2"

import json
from types import SimpleNamespace

import pytest

from compendio import config as config_mod
from compendio.config import Config
from compendio.exemplo import RITUAL_ORDEM
from compendio.llm import ClaudeLLM, GeminiLLM, criar_llm, schema_para_gemini
from compendio.schema import modelo_lote


def cfg(provedor="claude"):
    modelos = config_mod.PROVEDORES[provedor]
    return Config(api_key="x", modelo_rapido=modelos["rapido"], modelo_forte=modelos["forte"],
                  max_tokens=1000, banco=":memory:", provedor=provedor)


RESPOSTA = {"entradas": [{"nome": "Chama Ancestral", "circulo": 1}], "buscar": []}


# ------------------------------------------------------------------ Claude

class ClaudeFalso:
    """Imita anthropic.Anthropic: guarda a chamada e devolve um tool_use."""

    def __init__(self, resposta: dict):
        self.resposta = resposta
        self.chamadas = []
        self.messages = self

    def create(self, **kwargs):
        self.chamadas.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="tool_use", input=self.resposta)],
            stop_reason="tool_use",
            usage=SimpleNamespace(input_tokens=120, output_tokens=40,
                                  cache_read_input_tokens=900, cache_creation_input_tokens=0),
        )


def test_claude_saida_estruturada_e_registro_de_uso():
    falso = ClaudeFalso(RESPOSTA)
    llm = ClaudeLLM(cfg("claude"), cliente=falso)
    Lote = modelo_lote(RITUAL_ORDEM)

    r = llm.estruturado(etapa="especialista_ritual", instrucoes="Extraia rituais.", conteudo="...", schema=Lote)
    lote = Lote.model_validate(r.dados)

    assert lote.entradas[0].nome == "Chama Ancestral"
    chamada = falso.chamadas[0]
    assert chamada["tool_choice"] == {"type": "tool", "name": "registrar"}
    assert chamada["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert chamada["model"] == "claude-haiku-5-5"
    assert llm.registro.por_etapa()["especialista_ritual"] == {
        "chamadas": 1, "entrada": 120, "saida": 40, "cache_lido": 900
    }


# ------------------------------------------------------------------ Gemini

class GeminiFalso:
    """Imita google.genai.Client: client.models.generate_content(...)."""

    def __init__(self, respostas: list):
        self.respostas = list(respostas)
        self.chamadas = []
        self.models = self

    def generate_content(self, **kwargs):
        self.chamadas.append(kwargs)
        proxima = self.respostas.pop(0)
        if isinstance(proxima, Exception):
            raise proxima
        return SimpleNamespace(
            text=json.dumps(proxima),
            usage_metadata=SimpleNamespace(prompt_token_count=1000, candidates_token_count=50,
                                           cached_content_token_count=800, thoughts_token_count=10),
        )


def test_gemini_saida_estruturada_e_registro_de_uso():
    falso = GeminiFalso([RESPOSTA])
    llm = GeminiLLM(cfg("gemini"), cliente=falso)
    Lote = modelo_lote(RITUAL_ORDEM)

    r = llm.estruturado(etapa="especialista_ritual", instrucoes="Extraia rituais.", conteudo="...", schema=Lote)

    assert Lote.model_validate(r.dados).entradas[0].circulo == 1
    chamada = falso.chamadas[0]
    assert chamada["model"] == "gemini-3.5-flash-lite"
    assert chamada["config"]["response_mime_type"] == "application/json"
    assert chamada["config"]["system_instruction"] == "Extraia rituais."
    # entrada exclui o que veio do cache; saída inclui tokens de raciocínio
    assert llm.registro.por_etapa()["especialista_ritual"] == {
        "chamadas": 1, "entrada": 200, "saida": 60, "cache_lido": 800
    }


def test_gemini_repete_quando_bate_no_limite_de_taxa():
    esperas = []
    falso = GeminiFalso([RuntimeError("429 RESOURCE_EXHAUSTED"), RuntimeError("429"), RESPOSTA])
    llm = GeminiLLM(cfg("gemini"), cliente=falso, dormir=esperas.append, espera_inicial=1)

    r = llm.estruturado(etapa="x", instrucoes="i", conteudo="c", schema=modelo_lote(RITUAL_ORDEM))

    assert r.uso.tentativas == 3
    assert esperas == [1, 2]


def test_erro_que_nao_e_limite_nao_repete():
    falso = GeminiFalso([ValueError("chave inválida"), RESPOSTA])
    llm = GeminiLLM(cfg("gemini"), cliente=falso, dormir=lambda s: None)
    with pytest.raises(ValueError):
        llm.estruturado(etapa="x", instrucoes="i", conteudo="c", schema=modelo_lote(RITUAL_ORDEM))


def test_schema_do_gemini_so_tem_palavras_chave_aceitas():
    schema = schema_para_gemini(modelo_lote(RITUAL_ORDEM))
    texto = json.dumps(schema)
    assert '"default"' not in texto and "$ref" not in texto and "$defs" not in texto
    item = schema["properties"]["entradas"]["items"]
    # campos chamados como palavras-chave (ex.: um atributo "type") não podem sumir
    assert "circulo" in item["properties"] and "alcance" in item["properties"]


# ------------------------------------------------------------------ config

def test_config_escolhe_modelos_pelo_provedor(monkeypatch):
    for var in ("COMPENDIO_PROVEDOR", "COMPENDIO_MODELO_RAPIDO", "COMPENDIO_MODELO_FORTE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    c = config_mod.carregar(env_file=None)
    assert (c.provedor, c.api_key) == ("gemini", "g")
    assert c.modelo_rapido.split(",")[0] == "gemini-3.5-flash-lite"

    monkeypatch.setenv("COMPENDIO_PROVEDOR", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    c = config_mod.carregar(env_file=None)
    assert (c.provedor, c.api_key, c.modelo_forte) == ("claude", "a", "claude-sonnet-5-5")


def test_factory():
    assert isinstance(criar_llm(cfg("gemini"), cliente=GeminiFalso([])), GeminiLLM)
    assert isinstance(criar_llm(cfg("claude"), cliente=ClaudeFalso({})), ClaudeLLM)


def test_timeout_conta_como_erro_temporario():
    esperas = []
    falso = GeminiFalso([TimeoutError("The read operation timed out"), RESPOSTA])
    llm = GeminiLLM(cfg("gemini"), cliente=falso, dormir=esperas.append, espera_inicial=1)
    r = llm.estruturado(etapa="x", instrucoes="i", conteudo="c", schema=modelo_lote(RITUAL_ORDEM))
    assert r.uso.tentativas == 2


def test_verificar_mostra_falha_sem_travar(monkeypatch, capsys):
    from compendio import cli, llm as llm_mod

    class Falso(llm_mod.LLM):
        def _texto(self, etapa, conteudo, modelo, max_tokens):
            if modelo == "forte":
                raise TimeoutError("timed out")
            return "ok", llm_mod.Uso(etapa=etapa, modelo=modelo, entrada=3, saida=1)

    import sys
    import types

    monkeypatch.setitem(sys.modules, "pdfscope", types.SimpleNamespace(__version__="teste"))
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("COMPENDIO_MODELO_RAPIDO", "rapido")
    monkeypatch.setenv("COMPENDIO_MODELO_FORTE", "forte")
    monkeypatch.setattr(llm_mod, "criar_llm", lambda c, **kw: Falso(c, **kw))
    codigo = cli.main(["verificar", "--api"])
    saida = capsys.readouterr().out
    assert codigo == 1
    assert "testando rápido (rapido)... ok" in saida
    assert "FALHOU: TimeoutError" in saida


def test_cadeia_de_reserva_quando_o_modelo_esta_sobrecarregado():
    falso = GeminiFalso([RuntimeError("503 UNAVAILABLE high demand"), RESPOSTA])
    llm = GeminiLLM(cfg("gemini"), cliente=falso, dormir=lambda s: None, max_tentativas=1)
    r = llm.estruturado(etapa="x", instrucoes="i", conteudo="c", schema=modelo_lote(RITUAL_ORDEM),
                        modelo="gemini-3.8-flash,gemini-3.6-flash")
    assert [c["model"] for c in falso.chamadas] == ["gemini-3.8-flash", "gemini-3.6-flash"]
    assert r.uso.modelo == "gemini-3.6-flash"
    assert r.uso.tentativas == 2


def test_erro_permanente_nao_passa_para_a_reserva():
    falso = GeminiFalso([ValueError("400 INVALID_ARGUMENT"), RESPOSTA])
    llm = GeminiLLM(cfg("gemini"), cliente=falso, dormir=lambda s: None)
    with pytest.raises(ValueError):
        llm.estruturado(etapa="x", instrucoes="i", conteudo="c", schema=modelo_lote(RITUAL_ORDEM),
                        modelo="a,b")
    assert len(falso.chamadas) == 1

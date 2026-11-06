import pytest
from pydantic import ValidationError

from compendio.exemplo import MAGIA_DND, RITUAL_ORDEM
from compendio.llm import schema_para_tool
from compendio.schema import Atributo, Categoria, atributos_extras, canonico, modelo_entrada, modelo_lote


def test_slug_e_normalizacao():
    assert canonico.slug("Tempo de Conjuração") == "tempo_de_conjuracao"
    assert canonico.categoria_por_termo("Rituais") == "efeito_sobrenatural"
    assert canonico.categoria_por_termo("Magia") == "efeito_sobrenatural"


def test_atributo_mapeia_canonico_pelo_rotulo():
    assert Atributo(nome="circulo", rotulo="Círculo").canonico == "nivel"
    assert Atributo(nome="tempo_de_conjuracao", rotulo="Tempo de Conjuração").canonico == "execucao"
    assert Atributo(nome="x", rotulo="Coisa Estranha").canonico is None


def test_atributo_nao_colide_com_colunas_fixas():
    assert Atributo(nome="nome", rotulo="Nome").nome == "attr_nome"


def test_canonica_aceita_sinonimo_e_rejeita_lixo():
    assert Categoria(sistema="X", nome="Feitiço", canonica="magia").canonica == "efeito_sobrenatural"
    with pytest.raises(ValidationError):
        Categoria(sistema="X", nome="Coisa", canonica="nada_disso")


def test_modelo_dinamico_valida_tipos():
    Ritual = modelo_entrada(RITUAL_ORDEM)
    r = Ritual(nome="Teste", circulo="2", dados="2d6 de dano")
    assert r.circulo == 2
    with pytest.raises(ValidationError):
        Ritual(nome="Teste", dados="muito dano")  # campo de dados sem expressão


def test_extras_aparecem_como_atributos_novos():
    Magia = modelo_entrada(MAGIA_DND)
    m = Magia(nome="Bola de Fogo", concentracao=False)
    assert atributos_extras(m) == {"concentracao": False}


def test_mesclar_adiciona_so_o_que_falta():
    nova = RITUAL_ORDEM.model_copy(update={"atributos": [Atributo(nome="alcance", rotulo="Alcance"),
                                                         Atributo(nome="discente", rotulo="Discente")]})
    final, novos = RITUAL_ORDEM.mesclar(nova)
    assert novos == ["discente"]
    assert final.versao == RITUAL_ORDEM.versao + 1
    assert len(final.atributos) == len(RITUAL_ORDEM.atributos) + 1


def test_schema_do_lote_vai_sem_refs():
    schema = schema_para_tool(modelo_lote(RITUAL_ORDEM))
    assert "$defs" not in schema and "$ref" not in str(schema)
    props = schema["properties"]
    assert {"entradas", "incompletas", "contexto_insuficiente", "buscar"} <= set(props)
    assert "circulo" in props["entradas"]["items"]["properties"]

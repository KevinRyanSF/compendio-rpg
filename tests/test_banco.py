import pytest
from pydantic import ValidationError

from compendio.exemplo import MAGIA_DND, RITUAL_ORDEM, popular_exemplo
from compendio.schema import Atributo
from compendio.storage import Banco


@pytest.fixture
def banco():
    b = Banco(":memory:")
    popular_exemplo(b)
    yield b
    b.fechar()


def test_view_tem_uma_coluna_por_atributo(banco):
    [ritual] = banco.entradas("Ordem Paranormal", "ritual")
    assert ritual["nome"] == "Chama Ancestral"
    assert ritual["circulo"] == 1
    assert ritual["alcance"] == "Curto"
    assert ritual["dados"] == "3d6 de dano de fogo"


def test_atributo_desconhecido_amplia_a_categoria(banco):
    cat = banco.categoria("D&D 5e", "magia")
    assert cat.atributo("em_niveis_superiores") is not None
    assert cat.versao == 2
    [magia] = banco.entradas("D&D 5e", "magia")
    assert magia["em_niveis_superiores"].startswith("+1d6")
    assert magia["componentes"] == ["V", "S", "M"]
    assert magia["pode_ser_ritual"] is False


def test_magia_e_ritual_lado_a_lado_pela_camada_canonica(banco):
    itens = {e["nome"]: e for e in banco.por_canonica("efeito_sobrenatural")}
    assert set(itens) == {"Chama Ancestral", "Bola de Fogo"}
    # 'Círculo' (Ordem) e 'Nível' (D&D) viram a mesma chave
    assert itens["Chama Ancestral"]["nivel"] == 1
    assert itens["Bola de Fogo"]["nivel"] == 3
    # 'Execução' e 'Tempo de Conjuração' também
    assert itens["Chama Ancestral"]["execucao"] == "Padrão"
    assert itens["Bola de Fogo"]["execucao"] == "1 ação"


def test_mesma_entrada_em_dois_trechos_e_mesclada(banco):
    banco.salvar_entrada("Ordem Paranormal", "ritual", {"nome": "Chama ancestral", "discente": "+2 PE: 5d6"})
    [ritual] = banco.entradas("Ordem Paranormal", "ritual")
    assert ritual["discente"] == "+2 PE: 5d6"
    assert ritual["alcance"] == "Curto"  # o que já existia continua


def test_valor_invalido_e_rejeitado(banco):
    with pytest.raises(ValidationError):
        banco.salvar_entrada("Ordem Paranormal", "ritual", {"nome": "X", "circulo": "primeiro"})


def test_sem_aceitar_novos_atributos(banco):
    with pytest.raises(ValueError):
        banco.salvar_entrada("Ordem Paranormal", "ritual", {"nome": "Y", "cor": "azul"},
                             aceitar_novos_atributos=False)


def test_glossario_registra_termos_do_sistema(banco):
    g = banco.glossario("Ordem Paranormal")
    assert g["categoria"]["ritual"] == "efeito_sobrenatural"
    assert g["atributo"]["circulo"] == "nivel"


def test_reregistrar_sem_mudanca_nao_muda_versao(banco):
    _, novos = banco.registrar_categoria(RITUAL_ORDEM)
    assert novos == []
    assert banco.categoria("Ordem Paranormal", "ritual").versao == 1


def test_contagem(banco):
    linhas = {r["categoria"]: r for r in banco.contagem()}
    assert linhas["Ritual"]["entradas"] == 1
    assert linhas["Magia"]["atributos"] == len(MAGIA_DND.atributos) + 1

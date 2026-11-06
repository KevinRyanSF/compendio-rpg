import json
from pathlib import Path

from compendio import avaliacao

GOLD = Path(__file__).parent.parent / "gold"


def test_valores_batem():
    assert avaliacao.valores_batem("Vontade parcial", "Resistência: Vontade parcial")
    assert avaliacao.valores_batem(2, "2º círculo")
    assert avaliacao.valores_batem(["V", "S", "M"], "V, S, M (um raminho de visco)")
    assert avaliacao.valores_batem(["3d8+3", "5d8+5"], ["3d8+3", "5d8+5", "7d8+7"])
    assert avaliacao.valores_batem(True, "sim")
    assert not avaliacao.valores_batem("sustentada", "cena")
    assert not avaliacao.valores_batem("x3", None)


def test_chave_do_sistema_vira_canonica():
    assert avaliacao.chave_canonica("circulo") == "nivel"
    assert avaliacao.chave_canonica("tempo_de_conjuracao") == "execucao"
    assert avaliacao.chave_canonica("discente") == "discente"


def test_comparacao_com_a_saida_de_exemplo():
    gold = avaliacao.ler_jsonl(GOLD / "ordem-paranormal.jsonl")
    saida = avaliacao.ler_jsonl(GOLD / "exemplos" / "saida-exemplo-ordem.jsonl")
    r = avaliacao.comparar(gold, saida)
    por_status = {}
    for it in r.itens:
        por_status.setdefault(it.status, []).append(it.nome)

    assert set(por_status["faltou"]) == {"Envenenado", "Capturar o Coração", "Gadanho", "Machucado"}
    assert set(por_status["sobrou"]) == {"Chamejar", "Flechas"}  # Flechas = duplicata
    assert por_status["indevido"] == ["Veritus"]
    assert por_status["opcional"] == ["Ataque desarmado"]
    assert por_status["fora"] == ["Teste de Sanidade"]

    m = r.metricas
    assert m["acertos"] == 49 and m["faltaram"] == 4 and m["sobraram"] == 2 and m["indevidos"] == 1
    assert m["precisao"] == round(49 / 52, 3)
    assert m["cobertura"] == round(49 / 53, 3)
    # 14 entradas dependem de outra página: 11 armas completas (classe "Armas Táticas" da p.64);
    # Gadanho e Envenenado faltaram; Compreensão Paranormal veio sem discente/verdadeiro
    assert m["contexto_recuperado"] == "11/14"

    atroz = next(i for i in r.itens if i.nome == "Arma Atroz")
    duracao = next(a for a in atroz.atributos if a.chave == "duracao")
    assert not duracao.bate and duracao.obtido == "cena"
    circulo = next(a for a in atroz.atributos if a.chave == "nivel")
    assert circulo.bate  # 'circulo' na saída casou com 'nivel' no gold
    lanca = next(i for i in r.itens if i.nome == "Lança-chamas")
    assert lanca.categoria_diverge


def test_verificar_no_texto():
    entrada = {"tipo": "entrada", "nome": "Arma Atroz", "atributos": {"nivel": 1, "duracao": "sustentada", "alcance": "longo",
               "ritual": True}, "descricao_contem": ["+2 em testes de ataque"]}
    texto = "Arma Atroz\n SANGUE 1\nAlcance: toque\nDuração: sustentada\nEla fornece +2 em testes de\nataque"
    v = avaliacao.verificar_no_texto(entrada, texto)
    assert v["nome"] is True
    assert v["atributos"] == {"nivel": True, "duracao": True, "alcance": False, "ritual": None}
    assert v["descricao_contem"] == [True]


def test_salvar_jsonl_e_ler(tmp_path):
    linhas = [{"tipo": "entrada", "nome": "Ação"}, {"tipo": "negativo", "trecho": "x"}]
    avaliacao.salvar_jsonl(linhas, tmp_path / "g.jsonl")
    assert avaliacao.ler_jsonl(tmp_path / "g.jsonl") == linhas
    assert json.loads((tmp_path / "g.jsonl").read_text(encoding="utf-8").splitlines()[0])["nome"] == "Ação"

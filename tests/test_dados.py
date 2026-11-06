import pytest

from compendio import dados


def test_normaliza():
    assert dados.normalizar("2D8 + 1d6") == "2d8+1d6"
    assert dados.normalizar("d20") == "1d20"
    assert dados.normalizar("3d6 − 2") == "3d6-2"


def test_extrai_de_texto():
    texto = "Causa 3d6+2 de dano de fogo, e mais 1D4 por círculo. Custa 2 PE."
    assert dados.extrair(texto) == ["3d6+2", "1d4"]


def test_texto_sem_dados():
    assert dados.extrair("alcance curto, duração cena") == []
    with pytest.raises(ValueError):
        dados.normalizar("12")


def test_faixa():
    assert dados.faixa("2d6+3") == (5, 15)
    assert dados.faixa("1d8-1") == (0, 7)
    assert dados.faixa("2d8+1d6") == (3, 22)

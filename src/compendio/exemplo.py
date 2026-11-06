"""Dados de exemplo para demonstrar o banco dinâmico.

As categorias abaixo são o que se espera que o agente descubra sozinho ao ler os
livros; aqui estão escritas à mão só para a demonstração e os testes. Os textos
são resumos curtos escritos por nós, não trechos dos livros.
"""

from __future__ import annotations

from .schema import Atributo, Categoria
from .storage import Banco

RITUAL_ORDEM = Categoria(
    sistema="Ordem Paranormal",
    nome="Ritual",
    canonica="efeito_sobrenatural",
    descricao="Rituais conjurados com Pontos de Esforço, ligados a um elemento do Outro Lado.",
    atributos=[
        Atributo(nome="elemento", rotulo="Elemento"),
        Atributo(nome="circulo", rotulo="Círculo", tipo="inteiro"),
        Atributo(nome="execucao", rotulo="Execução"),
        Atributo(nome="alcance", rotulo="Alcance"),
        Atributo(nome="alvo", rotulo="Alvo"),
        Atributo(nome="duracao", rotulo="Duração"),
        Atributo(nome="resistencia", rotulo="Resistência"),
        Atributo(nome="custo_pe", rotulo="Custo em PE", tipo="inteiro"),
        Atributo(nome="dados", rotulo="Dados", tipo="dados"),
    ],
)

MAGIA_DND = Categoria(
    sistema="D&D 5e",
    nome="Magia",
    canonica="efeito_sobrenatural",
    descricao="Magias conjuradas com espaços de magia.",
    atributos=[
        Atributo(nome="nivel", rotulo="Nível", tipo="inteiro"),
        Atributo(nome="escola", rotulo="Escola"),
        Atributo(nome="tempo_de_conjuracao", rotulo="Tempo de Conjuração"),
        Atributo(nome="alcance", rotulo="Alcance"),
        Atributo(nome="componentes", rotulo="Componentes", tipo="lista"),
        Atributo(nome="duracao", rotulo="Duração"),
        Atributo(nome="dados", rotulo="Dados", tipo="dados"),
        # no D&D "ritual" é uma propriedade da magia, não uma categoria — bom caso de teste
        Atributo(nome="pode_ser_ritual", rotulo="Ritual", tipo="booleano", canonico=None),
    ],
)


def popular_exemplo(b: Banco) -> None:
    b.registrar_categoria(RITUAL_ORDEM)
    b.registrar_categoria(MAGIA_DND)

    b.salvar_entrada("Ordem Paranormal", "ritual", {
        "nome": "Chama Ancestral",  # ritual fictício, só para a demonstração
        "descricao": "Envolve o alvo em chamas do Outro Lado.",
        "elemento": "Energia", "circulo": 1, "execucao": "Padrão", "alcance": "Curto",
        "alvo": "1 ser", "duracao": "Instantânea", "resistencia": "Reflexos reduz à metade",
        "custo_pe": 1, "dados": "3d6 de dano de fogo",
    }, livro="Exemplo", paginas=(10, 10))

    b.salvar_entrada("D&D 5e", "magia", {
        "nome": "Bola de Fogo",
        "descricao": "Explosão de chamas em uma esfera de 6 m de raio; salvaguarda de Destreza reduz à metade.",
        "nivel": 3, "escola": "Evocação", "tempo_de_conjuracao": "1 ação", "alcance": "45 metros",
        "componentes": ["V", "S", "M"], "duracao": "Instantânea", "dados": "8d6",
        "pode_ser_ritual": False,
        # atributo que o esquema ainda não tinha: entra sozinho na categoria
        "em_niveis_superiores": "+1d6 por nível de espaço acima do 3º",
    }, livro="SRD 5.1", paginas=(241, 241))

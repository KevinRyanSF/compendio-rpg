"""compendio — transforma livros de RPG em compêndios consultáveis.

Camadas:
    ingest    PDF -> trechos (chunks) guiados pelo índice, via pdfscope
    schema    categorias e atributos dinâmicos por sistema + camada canônica
    storage   SQLite com uma view por categoria (colunas = atributos descobertos)
    llm       cliente da Claude API com saída estruturada e contagem de tokens
    dados     leitura de expressões de dados (3d6+2) para o VTT poder rolar
"""

__version__ = "0.1.0"

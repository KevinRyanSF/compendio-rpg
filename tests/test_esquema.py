import json
import shutil
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from compendio import esquema, experimento
from compendio.config import Config
from compendio.llm import GeminiLLM, schema_para_gemini

RAIZ = Path(__file__).parent.parent

ESQUEMA_RITUAL = {"categorias": [{
    "nome": "Ritual", "canonica": "efeito_sobrenatural", "descricao": "",
    "como_identificar": "nome em destaque seguido da linha ELEMENTO CÍRCULO",
    "atributos": [
        {"nome": "elemento", "rotulo": "Elemento", "tipo": "texto", "canonico": "escola_elemento",
         "origem": "linha_sem_rotulo", "como_encontrar": "primeira palavra da linha abaixo do nome"},
        {"nome": "circulo", "rotulo": "Círculo", "tipo": "inteiro", "canonico": "nivel",
         "origem": "linha_sem_rotulo", "como_encontrar": "número da linha abaixo do nome"},
        {"nome": "alcance", "rotulo": "Alcance", "tipo": "texto", "canonico": "alcance", "origem": "rotulo",
         "como_encontrar": "Alcance:"},
        {"nome": "discente", "rotulo": "Discente", "tipo": "texto", "canonico": None, "origem": "prosa",
         "como_encontrar": "custo entre parênteses depois de Discente"},
        {"nome": "dados", "rotulo": "Dados", "tipo": "dados", "canonico": "dados", "origem": "prosa",
         "como_encontrar": "expressões de dados no texto"},
    ]}]}


class GeminiFalso:
    """Mapeador: esquema de Ritual nas páginas de rituais, nada na página de lore.
    Especialista: dois rituais na 133, um com dado inválido."""

    def __init__(self):
        self.models = self
        self.etapas = []

    def generate_content(self, **kw):
        instr = kw["config"]["system_instruction"]
        conteudo = kw["contents"]
        if "Mapeador" in instr:
            self.etapas.append("mapeador")
            resposta = ESQUEMA_RITUAL if "Página 133" in conteudo else {"categorias": []}
        else:
            self.etapas.append("especialista")
            assert "## Ritual → lista `ritual`" in instr
            pagina = int(conteudo.split("]")[0].split()[-1])
            resposta = {"ritual": [], "incompletas": []}
            if pagina == 133:
                resposta["ritual"] = [
                    {"nome": "Arma Atroz", "descricao": "+2 em ataque", "elemento": "Sangue", "circulo": "1",
                     "alcance": "toque", "discente": "+2 PE", "dados": None},
                    {"nome": "Cicatriza&ccedil;&atilde;o", "descricao": "cura", "elemento": "Morte", "circulo": 1,
                     "alcance": "toque", "dados": "muito"},
                ]
        uso = SimpleNamespace(prompt_token_count=100, candidates_token_count=20, cached_content_token_count=0,
                              thoughts_token_count=0)
        return SimpleNamespace(text=json.dumps(resposta), usage_metadata=uso, candidates=[])


def cfg():
    return Config(api_key="x", modelo_rapido="rapido", modelo_forte="forte", max_tokens=1000, banco=":memory:",
                  provedor="gemini")


def test_schemas_vao_limpos_para_o_gemini():
    for modelo in (esquema.Esquema,):
        texto = json.dumps(schema_para_gemini(modelo))
        assert "$ref" not in texto and "$defs" not in texto
    cat = esquema.descobrir(GeminiLLM(cfg(), cliente=GeminiFalso()), "[Página 133]\nx", sistema="Ordem Paranormal")[0]
    pagina = schema_para_gemini(esquema._modelo_pagina([cat]))
    item = pagina["properties"]["ritual"]["items"]["properties"]
    assert {"nome", "descricao", "elemento", "circulo", "discente", "dados"} <= set(item)


def test_descobrir_vira_categoria_com_dica_e_canonico():
    llm = GeminiLLM(cfg(), cliente=GeminiFalso())
    [cat] = esquema.descobrir(llm, "[Página 133]\ntexto", sistema="Ordem Paranormal", modelo="forte")
    assert cat.nome == "Ritual" and cat.slug == "ritual"
    circulo = cat.atributo("circulo")
    assert circulo.tipo == "inteiro" and circulo.canonico == "nivel"
    assert circulo.descricao.startswith("[linha_sem_rotulo]")
    assert llm.registro.chamadas[0].modelo == "forte"


def test_estrategia_completa_no_projeto(tmp_path):
    shutil.copytree(RAIZ / "gold", tmp_path / "gold")

    class Doc:
        page_count = 330

        def page_text_raw(self, p):
            return f"{p + 1}\nconteúdo da página {p + 1}"

    falso = GeminiFalso()
    llm = GeminiLLM(cfg(), cliente=falso)
    saida, meta = experimento.rodar(tmp_path, "ordem-paranormal", cfg(), estrategia="esquema", llm=llm,
                                    abrir_pdf=lambda c: Doc())

    # 5 recortes = 5 mapeadores; só o bloco 133-134 tem esquema → 2 especialistas; lore/negativos não gastam
    assert falso.etapas.count("mapeador") == 5
    assert falso.etapas.count("especialista") == 2
    assert set(meta["por_etapa"]) == {"mapeador", "especialista"}

    linhas = [json.loads(l) for l in saida.read_text(encoding="utf-8").splitlines()]
    atroz = next(l for l in linhas if l["nome"] == "Arma Atroz")
    # chaves canônicas na saída; círculo virou inteiro
    assert atroz["atributos"] == {"escola_elemento": "Sangue", "nivel": 1, "alcance": "toque", "discente": "+2 PE"}
    cic = next(l for l in linhas if l["nome"] == "Cicatrização")  # entidade HTML consertada
    assert any("dados" in a for a in cic["avisos"])  # dado inválido vira aviso, não some

    # o esquema e as entradas válidas foram para o banco, com view por categoria
    con = sqlite3.connect(tmp_path / meta["banco"])
    assert con.execute('SELECT nome, circulo, discente FROM "v_ordem_paranormal__ritual"').fetchall() == [
        ("Arma Atroz", 1, "+2 PE")]

    m = experimento.avaliar(tmp_path, "ordem-paranormal", saida)
    assert m["acertos"] == 2 and m["sobraram"] == 0

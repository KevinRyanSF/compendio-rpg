"""Estratégia 'agentes': Mapeador + Especialista + Revisor de cobertura + busca de contexto."""
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

from compendio import experimento
from compendio.config import Config
from compendio.llm import GeminiLLM

RAIZ = Path(__file__).parent.parent

RITUAL = {"nome": "Ritual", "canonica": "efeito_sobrenatural", "como_identificar": "nome + linha ELEMENTO N",
          "atributos": [
              {"nome": "circulo", "rotulo": "Círculo", "tipo": "inteiro", "canonico": "nivel",
               "origem": "linha_sem_rotulo", "como_encontrar": "número"},
              {"nome": "discente", "rotulo": "Discente", "tipo": "texto", "canonico": None, "origem": "prosa",
               "como_encontrar": "Discente (+X PE)"},
              {"nome": "verdadeiro", "rotulo": "Verdadeiro", "tipo": "texto", "canonico": None, "origem": "prosa",
               "como_encontrar": "Verdadeiro (+X PE)"}]}
CONDICAO = {"nome": "Condição", "canonica": "regra", "como_identificar": "nome em negrito seguido de ponto",
            "atributos": [{"nome": "tipo_condicao", "rotulo": "Tipo", "tipo": "texto", "canonico": "tipo_condicao",
                           "origem": "prosa", "como_encontrar": "Condição mental/de fadiga"}]}


class GeminiAgente:
    def __init__(self):
        self.models = self
        self.etapas = []

    def generate_content(self, **kw):
        instr, txt = kw["config"]["system_instruction"], kw["contents"]
        uso = SimpleNamespace(prompt_token_count=50, candidates_token_count=10, cached_content_token_count=0,
                              thoughts_token_count=0)
        if "Mapeador" in instr:
            self.etapas.append("mapeador")
            r = {"categorias": [RITUAL] if "Página 133" in txt else [CONDICAO] if "Página 319" in txt else []}
            return SimpleNamespace(text=json.dumps(r), usage_metadata=uso, candidates=[])

        foco = instr.split("FOCO DESTA CHAMADA:")[-1] if "FOCO DESTA CHAMADA" in instr else ""
        self.etapas.append("contexto" if "[fim da" in txt or "[começo da" in txt else "revisor" if foco else "especialista")
        r = {"ritual": [], "condicao": [], "incompletas": [], "nomes_na_pagina": [], "precisa_de_contexto": []}
        pagina = int(txt.split("]")[0].split()[-1])
        if "[começo da Página 135]" in txt:
            r["ritual"] = [{"nome": "Compreensão Paranormal", "circulo": 1, "discente": "+2 PE", "verdadeiro": "+5 PE"}]
        elif "[fim da Página 318]" in txt:
            r["condicao"] = [{"nome": "Envenenado", "descricao": "varia conforme o veneno"}]
        elif foco and "Capturar o Coração" in foco:
            r["ritual"] = [{"nome": "Capturar o Coração", "circulo": 4}]
        elif pagina == 133:
            r["ritual"] = [{"nome": "Arma Atroz", "circulo": 1}]
            r["nomes_na_pagina"] = ["Arma Atroz", "Capturar o Coração"]
        elif pagina == 134:
            r["ritual"] = [{"nome": "Compreensão Paranormal", "circulo": 1}]
            r["nomes_na_pagina"] = ["Compreensão Paranormal"]
            r["precisa_de_contexto"] = [{"nome": "Compreensão Paranormal", "direcao": "seguinte", "motivo": ""}]
        elif pagina == 319:
            r["condicao"] = [{"nome": "Esmorecido", "tipo_condicao": "mental"}]
            r["nomes_na_pagina"] = ["Esmorecido"]
            r["precisa_de_contexto"] = [{"nome": "", "direcao": "anterior", "motivo": "começa no meio"}]
        return SimpleNamespace(text=json.dumps(r), usage_metadata=uso, candidates=[])


class Doc:
    page_count = 330
    pedidas: list[int] = []

    def page_text_raw(self, p):
        Doc.pedidas.append(p + 1)
        return f"{p + 1}\nconteúdo da página {p + 1}"


def cfg():
    return Config(api_key="x", modelo_rapido="rapido", modelo_forte="forte", max_tokens=1000, banco=":memory:",
                  provedor="gemini")


def test_revisor_e_contexto(tmp_path):
    shutil.copytree(RAIZ / "gold", tmp_path / "gold")
    falso, eventos = GeminiAgente(), []
    llm = GeminiLLM(cfg(), cliente=falso)
    saida, meta = experimento.rodar(tmp_path, "ordem-paranormal", cfg(), estrategia="agentes", llm=llm,
                                    abrir_pdf=lambda c: Doc(), ao_evento=eventos.append)

    assert falso.etapas.count("mapeador") == 5
    assert falso.etapas.count("revisor") == 1      # pediu de novo Capturar o Coração
    assert falso.etapas.count("contexto") == 2     # p.135 (seguinte) e p.318 (anterior)
    assert set(meta["por_etapa"]) == {"mapeador", "especialista", "revisor", "contexto"}
    assert 135 in Doc.pedidas and 318 in Doc.pedidas  # a tool foi buscar fora do recorte
    assert any("revisor pede de novo Capturar o Coração" in e for e in eventos)
    assert any("busca contexto na p.135" in e for e in eventos)

    linhas = {l["nome"]: l for l in map(json.loads, saida.read_text(encoding="utf-8").splitlines())}
    comp = linhas["Compreensão Paranormal"]
    assert comp["paginas"] == [134, 135]
    assert comp["atributos"]["discente"] == "+2 PE" and comp["atributos"]["verdadeiro"] == "+5 PE"
    assert linhas["Envenenado"]["paginas"] == [318, 319]
    assert "Capturar o Coração" in linhas

    m = experimento.avaliar(tmp_path, "ordem-paranormal", saida)
    assert m["contexto_recuperado"] == "2/14"  # Compreensão completa + Envenenado achado
    assert m["sobraram"] == 0

import json
import shutil
import threading
import urllib.request
from pathlib import Path

import pytest

from compendio import revisor

RAIZ = Path(__file__).parent.parent


class DocFalso:
    def __init__(self, caminho):
        self.page_count = 330

    def page_text_raw(self, p):
        if p + 1 == 133:
            return "125\nArma Atroz\n SANGUE 1\nExecução: padrão\nAlcance: toque\nDuração: sustentada\nFulano marca@x.com"
        return f"{p + 1}\nTexto qualquer\nFulano marca@x.com"


@pytest.fixture
def servidor(tmp_path):
    shutil.copytree(RAIZ / "gold", tmp_path / "gold")
    (tmp_path / "livros").mkdir()
    for livro in json.loads((tmp_path / "gold" / "recortes.json").read_text(encoding="utf-8"))["livros"].values():
        (tmp_path / "livros" / livro["arquivo"]).write_bytes(b"%PDF-falso")
    srv = revisor.criar_servidor(tmp_path, porta=0, abrir_pdf=DocFalso)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", tmp_path
    srv.shutdown()
    srv.server_close()


def get(url):
    with urllib.request.urlopen(url) as r:
        return r.read()


def test_pagina_e_estado(servidor):
    base, _ = servidor
    assert b"Revisor do gabarito" in get(base + "/")
    estado = json.loads(get(base + "/api/estado"))
    assert estado["livros"]["ordem-paranormal"]["pdf_existe"] is True
    assert estado["livros"]["ordem-paranormal"]["paginas_total"] == 330
    assert "gold/exemplos/saida-exemplo-ordem.jsonl" in estado["saidas"]


def test_gold_com_verificacao_e_texto_limpo(servidor):
    base, _ = servidor
    j = json.loads(get(base + "/api/gold/ordem-paranormal"))
    i = next(k for k, d in enumerate(j["linhas"]) if d.get("nome") == "Arma Atroz")
    v = j["verificacao"][i]
    assert v["nome"] is True
    assert v["atributos"]["duracao"] is True and v["atributos"]["alvo_area"] is False
    texto = json.loads(get(base + "/api/texto/ordem-paranormal/133"))["texto"]
    assert "Arma Atroz" in texto and "marca@x.com" not in texto


def test_salvar_gold(servidor):
    base, raiz = servidor
    linhas = json.loads(get(base + "/api/gold/ordem-paranormal"))["linhas"]
    linhas[0]["conferido"] = True
    req = urllib.request.Request(base + "/api/gold/ordem-paranormal", data=json.dumps({"linhas": linhas}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as r:
        assert json.loads(r.read())["ok"] is True
    primeira = (raiz / "gold" / "ordem-paranormal.jsonl").read_text(encoding="utf-8").splitlines()[0]
    assert json.loads(primeira)["conferido"] is True


def test_comparar(servidor):
    base, _ = servidor
    j = json.loads(get(base + "/api/comparar/ordem-paranormal?saida=gold/exemplos/saida-exemplo-ordem.jsonl"))
    assert j["metricas"]["acertos"] == 49


def test_comparar_recusa_arquivo_fora_do_projeto(servidor):
    base, _ = servidor
    with pytest.raises(urllib.error.HTTPError):
        get(base + "/api/comparar/ordem-paranormal?saida=../../etc/passwd.jsonl")

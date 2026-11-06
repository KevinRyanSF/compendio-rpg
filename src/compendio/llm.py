"""Clientes de LLM com saída estruturada e contabilidade de tokens.

Dois provedores com a mesma interface (`estruturado`, `texto`):

  * GeminiLLM — padrão. Tem uso gratuito no Google AI Studio (com limite de
    requisições), é o que a disciplina usa. Saída estruturada via
    `response_json_schema`.
  * ClaudeLLM — Claude API. Saída estruturada via tool use forçado; instruções
    e schema marcados com `cache_control` para sair do cache nas repetições.

`criar_llm(config)` escolhe pelo COMPENDIO_PROVEDOR. O resto do sistema
(agentes, banco, avaliação) não sabe qual provedor está por baixo — o que
permite rodar o mesmo gold set nos dois e comparar.

Toda chamada é registrada por etapa/agente em `RegistroDeUso`: é a base das
métricas de custo do relatório.
"""

from __future__ import annotations

import copy
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from .config import Config


# ------------------------------------------------------------------ uso

@dataclass
class Uso:
    etapa: str
    modelo: str
    entrada: int = 0
    saida: int = 0
    cache_lido: int = 0
    cache_criado: int = 0
    segundos: float = 0.0
    tentativas: int = 1

    @property
    def total(self) -> int:
        return self.entrada + self.saida + self.cache_lido + self.cache_criado


@dataclass
class RegistroDeUso:
    chamadas: list[Uso] = field(default_factory=list)

    def adicionar(self, uso: Uso) -> None:
        self.chamadas.append(uso)

    def por_etapa(self) -> dict[str, dict[str, int]]:
        resumo: dict[str, dict[str, int]] = {}
        for u in self.chamadas:
            r = resumo.setdefault(u.etapa, {"chamadas": 0, "entrada": 0, "saida": 0, "cache_lido": 0})
            r["chamadas"] += 1
            r["entrada"] += u.entrada + u.cache_criado
            r["saida"] += u.saida
            r["cache_lido"] += u.cache_lido
        return resumo

    def salvar_jsonl(self, caminho: str | Path) -> None:
        caminho = Path(caminho)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        with caminho.open("a", encoding="utf-8") as f:
            for u in self.chamadas:
                f.write(json.dumps(asdict(u), ensure_ascii=False) + "\n")


class SaidaTruncada(RuntimeError):
    """A resposta passou do limite de tokens de saída e veio cortada (JSON incompleto)."""


@dataclass
class Resposta:
    dados: dict[str, Any]
    uso: Uso


# --------------------------------------------------------------- schemas

def schema_para_tool(modelo: type[BaseModel] | dict) -> dict:
    """JSON Schema do Pydantic com as referências ($defs) resolvidas no lugar."""
    schema = modelo.model_json_schema() if isinstance(modelo, type) else copy.deepcopy(modelo)
    defs = schema.pop("$defs", {})

    def resolver(no):
        if isinstance(no, dict):
            if "$ref" in no:
                nome = no["$ref"].rsplit("/", 1)[-1]
                return resolver(copy.deepcopy(defs[nome]))
            return {k: resolver(v) for k, v in no.items()}
        if isinstance(no, list):
            return [resolver(v) for v in no]
        return no

    return resolver(schema)


# palavras-chave de JSON Schema que o Gemini aceita na saída estruturada
_GEMINI_OK = {
    "type", "title", "description", "properties", "required", "additionalProperties",
    "items", "prefixItems", "minItems", "maxItems", "enum", "format", "minimum", "maximum", "anyOf",
}


def schema_para_gemini(modelo: type[BaseModel] | dict) -> dict:
    """Como `schema_para_tool`, mas só com as palavras-chave que o Gemini entende."""

    def limpar(no, em_properties: bool = False):
        if isinstance(no, dict):
            if em_properties:  # chaves aqui são nomes de campos, não palavras-chave
                return {k: limpar(v) for k, v in no.items()}
            return {k: limpar(v, em_properties=(k == "properties")) for k, v in no.items() if k in _GEMINI_OK}
        if isinstance(no, list):
            return [limpar(v) for v in no]
        return no

    return limpar(schema_para_tool(modelo))


# ------------------------------------------------------------- base

def _e_demora(erro: Exception) -> bool:
    """Timeout/prazo estourado: repetir no mesmo modelo costuma demorar de novo."""
    texto = f"{type(erro).__name__} {erro}".lower()
    return any(s in texto for s in ("504", "deadline_exceeded", "deadline expired", "timeout", "timed out"))


def _e_limite_de_taxa(erro: Exception) -> bool:
    texto = f"{type(erro).__name__} {erro}".lower()
    sinais = ("429", "resource_exhausted", "rate limit", "ratelimit", "overloaded", "503", "unavailable",
              "504", "deadline_exceeded", "deadline expired", "timeout", "timed out", "500 internal")
    return any(s in texto for s in sinais)


class LLM:
    """Interface comum. Subclasses implementam `_estruturado` e `_texto`."""

    provedor = "base"

    def __init__(self, config: Config, registro: RegistroDeUso | None = None,
                 max_tentativas: int = 5, espera_inicial: float = 2.0,
                 dormir: Callable[[float], None] = time.sleep):
        self.config = config
        self.registro = registro or RegistroDeUso()
        self.max_tentativas = max_tentativas
        self.espera_inicial = espera_inicial
        self._dormir = dormir

    def _com_retentativas(self, chamada: Callable[[], Any]) -> tuple[Any, int]:
        """Repete em erro de limite de taxa (comum no plano grátis), com espera exponencial."""
        espera = self.espera_inicial
        for tentativa in range(1, self.max_tentativas + 1):
            try:
                return chamada(), tentativa
            except Exception as erro:  # noqa: BLE001 - cada SDK tem sua classe de erro
                if tentativa == self.max_tentativas or not _e_limite_de_taxa(erro) or _e_demora(erro):
                    raise  # timeout vai direto para o próximo modelo da cadeia
                self._dormir(espera)
                espera = min(espera * 2, 60)
        raise AssertionError("inalcançável")

    def _em_cadeia(self, modelos: str, fazer: Callable[[str], Any]) -> tuple[Any, int]:
        """Tenta cada modelo da cadeia ("a,b,c"); só passa ao próximo em erro temporário."""
        cadeia = [m.strip() for m in modelos.split(",") if m.strip()]
        total = 0
        for i, modelo in enumerate(cadeia):
            try:
                resultado, tentativas = self._com_retentativas(lambda: fazer(modelo))
                return resultado, total + tentativas
            except Exception as erro:  # noqa: BLE001
                total += 1 if _e_demora(erro) else self.max_tentativas
                if i == len(cadeia) - 1 or not _e_limite_de_taxa(erro):
                    raise
        raise ValueError("nenhum modelo informado")

    def estruturado(self, *, etapa: str, instrucoes: str, conteudo: str, schema: type[BaseModel] | dict,
                    nome_tool: str = "registrar", descricao_tool: str = "Registra o resultado no formato exigido.",
                    modelo: str | None = None, max_tokens: int | None = None) -> Resposta:
        inicio = time.perf_counter()
        (dados, uso), tentativas = self._em_cadeia(modelo or self.config.modelo_rapido, lambda m: self._estruturado(
            etapa, instrucoes, conteudo, schema, nome_tool, descricao_tool, m, max_tokens or self.config.max_tokens))
        uso.segundos = round(time.perf_counter() - inicio, 3)
        uso.tentativas = tentativas
        self.registro.adicionar(uso)
        return Resposta(dados=dados, uso=uso)

    def texto(self, *, etapa: str, conteudo: str, modelo: str | None = None, max_tokens: int = 256) -> Resposta:
        inicio = time.perf_counter()
        (texto, uso), tentativas = self._em_cadeia(
            modelo or self.config.modelo_rapido, lambda m: self._texto(etapa, conteudo, m, max_tokens))
        uso.segundos = round(time.perf_counter() - inicio, 3)
        uso.tentativas = tentativas
        self.registro.adicionar(uso)
        return Resposta(dados={"texto": texto}, uso=uso)

    def _estruturado(self, etapa, instrucoes, conteudo, schema, nome_tool, descricao_tool, modelo, max_tokens):
        raise NotImplementedError

    def _texto(self, etapa, conteudo, modelo, max_tokens):
        raise NotImplementedError


# ------------------------------------------------------------ Claude

class ClaudeLLM(LLM):
    provedor = "claude"

    def __init__(self, config: Config, cliente: Any | None = None, **kw):
        super().__init__(config, **kw)
        if cliente is None:
            if not config.api_key:
                raise RuntimeError("ANTHROPIC_API_KEY não configurada (veja .env.example).")
            import anthropic

            cliente = anthropic.Anthropic(api_key=config.api_key, timeout=config.timeout_s, max_retries=0)
        self._cliente = cliente

    def _estruturado(self, etapa, instrucoes, conteudo, schema, nome_tool, descricao_tool, modelo, max_tokens):
        resp = self._cliente.messages.create(
            model=modelo,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": instrucoes, "cache_control": {"type": "ephemeral"}}],
            tools=[{"name": nome_tool, "description": descricao_tool, "input_schema": schema_para_tool(schema)}],
            tool_choice={"type": "tool", "name": nome_tool},
            messages=[{"role": "user", "content": conteudo}],
        )
        if getattr(resp, "stop_reason", None) == "max_tokens":
            raise SaidaTruncada(f"[{etapa}] resposta cortada no limite de {max_tokens} tokens")
        for bloco in resp.content:
            if getattr(bloco, "type", None) == "tool_use":
                return dict(bloco.input), self._uso(resp, etapa, modelo)
        raise RuntimeError(f"[{etapa}] o modelo não devolveu a tool '{nome_tool}' (stop={resp.stop_reason}).")

    def _texto(self, etapa, conteudo, modelo, max_tokens):
        resp = self._cliente.messages.create(
            model=modelo, max_tokens=max_tokens, messages=[{"role": "user", "content": conteudo}]
        )
        return "".join(getattr(b, "text", "") for b in resp.content), self._uso(resp, etapa, modelo)

    @staticmethod
    def _uso(resp, etapa: str, modelo: str) -> Uso:
        u = resp.usage
        return Uso(
            etapa=etapa, modelo=modelo,
            entrada=getattr(u, "input_tokens", 0) or 0,
            saida=getattr(u, "output_tokens", 0) or 0,
            cache_lido=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_criado=getattr(u, "cache_creation_input_tokens", 0) or 0,
        )


# ------------------------------------------------------------ Gemini

class GeminiLLM(LLM):
    provedor = "gemini"

    def __init__(self, config: Config, cliente: Any | None = None, **kw):
        super().__init__(config, **kw)
        if cliente is None:
            if not config.api_key:
                raise RuntimeError("GEMINI_API_KEY não configurada (veja .env.example).")
            import warnings

            # o próprio SDK do Google tem um "\/" numa docstring; o aviso é inofensivo
            warnings.filterwarnings("ignore", message=r"invalid escape sequence", category=SyntaxWarning)
            from google import genai

            # timeout em milissegundos; sem ele uma resposta lenta trava o programa indefinidamente
            cliente = genai.Client(api_key=config.api_key, http_options={"timeout": int(config.timeout_s * 1000)})
        self._cliente = cliente

    def _estruturado(self, etapa, instrucoes, conteudo, schema, nome_tool, descricao_tool, modelo, max_tokens):
        resp = self._cliente.models.generate_content(
            model=modelo,
            contents=conteudo,
            config={
                "system_instruction": instrucoes,
                "response_mime_type": "application/json",
                "response_json_schema": schema_para_gemini(schema),
                "max_output_tokens": max_tokens,
            },
        )
        texto = getattr(resp, "text", None) or ""
        candidatos = getattr(resp, "candidates", None) or []
        motivo = str(getattr(candidatos[0], "finish_reason", "")) if candidatos else ""
        try:
            dados = json.loads(texto)
        except json.JSONDecodeError as erro:
            if "MAX_TOKENS" in motivo or texto.strip() and not texto.rstrip().endswith("}"):
                raise SaidaTruncada(f"[{etapa}] resposta cortada no limite de {max_tokens} tokens") from erro
            raise RuntimeError(f"[{etapa}] o Gemini não devolveu JSON válido: {texto[:200]!r}") from erro
        if not isinstance(dados, dict):
            raise RuntimeError(f"[{etapa}] esperava um objeto JSON, veio {type(dados).__name__}")
        return dados, self._uso(resp, etapa, modelo)

    def _texto(self, etapa, conteudo, modelo, max_tokens):
        resp = self._cliente.models.generate_content(
            model=modelo, contents=conteudo, config={"max_output_tokens": max_tokens}
        )
        return getattr(resp, "text", "") or "", self._uso(resp, etapa, modelo)

    @staticmethod
    def _uso(resp, etapa: str, modelo: str) -> Uso:
        u = getattr(resp, "usage_metadata", None)
        cache = (getattr(u, "cached_content_token_count", 0) or 0) if u else 0
        entrada = (getattr(u, "prompt_token_count", 0) or 0) if u else 0
        saida = 0
        if u:
            saida = (getattr(u, "candidates_token_count", 0) or 0) + (getattr(u, "thoughts_token_count", 0) or 0)
        return Uso(etapa=etapa, modelo=modelo, entrada=max(entrada - cache, 0), saida=saida, cache_lido=cache)


# ------------------------------------------------------------ factory

def criar_llm(config: Config, **kw) -> LLM:
    if config.provedor == "claude":
        return ClaudeLLM(config, **kw)
    if config.provedor == "gemini":
        return GeminiLLM(config, **kw)
    raise ValueError(f"provedor desconhecido: {config.provedor!r}")

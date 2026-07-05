from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata


LOCAL_VECTOR_MODEL = "sentinel-local-hashing-v1"
LOCAL_VECTOR_DIMENSIONS = 384

TOKEN_PATTERN = re.compile(r"[a-z0-9_/-]{2,}")

SEMANTIC_GROUPS = (
    ("nomina", "payroll", "salario", "salary", "empleado", "empleados", "trabajador", "workers", "pago", "pagos"),
    ("tesoreria", "treasury", "fondos", "funds", "cuenta", "account", "banco", "bank", "swift"),
    ("transferencia", "transferencias", "wire", "wires", "saliente", "internacional", "international"),
    ("credencial", "credenciales", "secret", "secreto", "secretos", "token", "password", "api", "key", "llave", "vault"),
    ("riesgo", "risk", "incidente", "brecha", "compromiso", "comprometido", "expuesto", "fuga"),
    ("decision", "decisiones", "acuerdo", "aprobado", "orden", "instruccion", "mandato"),
    ("tarea", "accion", "acciones", "pendiente", "responsable", "ejecutar", "hacer"),
    ("bloquear", "bloqueo", "congelar", "congelen", "deshabilitar", "revocar", "rotar", "purgar"),
    ("base", "datos", "database", "postgres", "supabase", "sql", "tabla", "registros"),
    ("docker", "contenedor", "contenedores", "github", "actions", "runner", "cache", "build"),
)

EXPANSIONS: dict[str, tuple[str, ...]] = {}
for group in SEMANTIC_GROUPS:
    for term in group:
        EXPANSIONS[term] = tuple(item for item in group if item != term)


def embed_text(text: str, dimensions: int = LOCAL_VECTOR_DIMENSIONS) -> list[float]:
    vector = [0.0] * dimensions
    tokens = _tokens(text)
    if not tokens:
        return vector

    for token in tokens:
        _add_feature(vector, f"tok:{token}", 1.0)
        for stem in _stems(token):
            _add_feature(vector, f"stem:{stem}", 0.7)
        for expansion in EXPANSIONS.get(token, ()):
            _add_feature(vector, f"sem:{expansion}", 0.95)
        for ngram in _char_ngrams(token):
            _add_feature(vector, f"ng:{ngram}", 0.16)

    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        return vector
    return [round(value / magnitude, 6) for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def vector_to_json(vector: list[float]) -> str:
    return json.dumps(vector, separators=(",", ":"))


def vector_from_json(raw: str) -> list[float]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return [float(item) for item in value]


def _add_feature(vector: list[float], feature: str, weight: float) -> None:
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    bucket = int.from_bytes(digest[:4], "big") % len(vector)
    sign = 1.0 if digest[4] % 2 == 0 else -1.0
    vector[bucket] += sign * weight


def _tokens(text: str) -> list[str]:
    normalized = _normalize(text)
    return TOKEN_PATTERN.findall(normalized)


def _stems(token: str) -> list[str]:
    stems = []
    for suffix in ("ciones", "cion", "mente", "ados", "adas", "ido", "ada", "ado", "es", "s"):
        if len(token) > len(suffix) + 4 and token.endswith(suffix):
            stems.append(token[: -len(suffix)])
    return stems


def _char_ngrams(token: str) -> list[str]:
    if len(token) <= 4:
        return [token]
    return [token[index : index + 4] for index in range(0, len(token) - 3)]


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    return without_accents.lower()

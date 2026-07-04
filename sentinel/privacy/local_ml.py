from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from sentinel.domain.privacy import SensitiveEntity, SensitiveEntityType, SensitivityLevel


MODEL_VERSION = "sentinel-local-sensitive-span-nb-v1"
OUTSIDE_LABEL = "O"
DEFAULT_MODEL_PATH = Path("data/models/sensitive_span_nb.json")
MIN_CONFIDENCE_BY_LABEL = {
    SensitiveEntityType.CLASSIFICATION.value: 0.66,
    SensitiveEntityType.CODE_NAME.value: 0.66,
    SensitiveEntityType.FACILITY.value: 0.66,
    SensitiveEntityType.INTERNAL_PROJECT.value: 0.66,
    SensitiveEntityType.ORGANIZATION.value: 0.7,
    SensitiveEntityType.ROLE.value: 0.66,
    SensitiveEntityType.SECRET_REFERENCE.value: 0.64,
    SensitiveEntityType.SECURITY_CONTROL.value: 0.64,
}


@dataclass(frozen=True)
class TrainingExample:
    text: str
    label: str


@dataclass(frozen=True)
class CandidatePattern:
    pattern: re.Pattern[str]
    value_group: int = 0


def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE)


ML_CANDIDATE_PATTERNS = [
    CandidatePattern(_compile(r"Nivel de Clasificaci[oó]n:\s*([^\n]+)"), 1),
    CandidatePattern(_compile(r"\(([^()\n]{5,90})\)"), 1),
    CandidatePattern(_compile(r"\b(?:Operaci[oó]n|Proyecto|Project|Fase)\s+([A-ZÁÉÍÓÚÑ][^.,;\n]{2,80})"), 1),
    CandidatePattern(_compile(r"\b(?:contacto|alias|clave de contacto)\s+\"?([^\".,;\n]{2,60})\"?"), 1),
    CandidatePattern(
        _compile(r"\b(?:por|mediante|usando|utilizando|a trav[eé]s de|v[ií]a)\s+(?:el|la|los|las)?\s*([^.,;\n]{3,90})"),
        1,
    ),
    CandidatePattern(
        _compile(
            r"\b(?:archivo|entorno|panel|consola|registro|auditor[ií]a|cache|cach[eé]|runner|vault|"
            r"gestor|canal|credenciales|variables de entorno|contenedores?|im[aá]genes)\b[^.,;\n]{0,90}"
        )
    ),
    CandidatePattern(
        _compile(
            r"\b(?:API\s*keys?|llaves?|secreto|secretos|token|password|contrase[nñ]a|string de conexi[oó]n|"
            r"frase de recuperaci[oó]n|seed phrase|JWT_SECRET)\b[^.,;\n]{0,90}"
        )
    ),
    CandidatePattern(_compile(r"\b(?:zona|sala|rack|servidor|cluster|cl[uú]ster|puerta|datacenter|centro de datos)\b[^.,;\n]{0,90}")),
    CandidatePattern(_compile(r"\b(?:Banco|Grupo|Corporaci[oó]n|Empresa|Cliente|Proveedor)\s+[A-ZÁÉÍÓÚÑ][^.,;\n]{2,80}")),
]


class LocalNaiveBayesSpanClassifier:
    def __init__(
        self,
        *,
        class_doc_counts: dict[str, int],
        class_feature_totals: dict[str, int],
        feature_counts: dict[str, dict[str, int]],
        vocabulary: set[str],
        alpha: float = 0.6,
    ) -> None:
        self.class_doc_counts = class_doc_counts
        self.class_feature_totals = class_feature_totals
        self.feature_counts = feature_counts
        self.vocabulary = vocabulary
        self.alpha = alpha

    @classmethod
    def train(cls, examples: Iterable[TrainingExample], *, alpha: float = 0.6) -> "LocalNaiveBayesSpanClassifier":
        class_doc_counts: Counter[str] = Counter()
        class_feature_totals: Counter[str] = Counter()
        feature_counts: dict[str, Counter[str]] = defaultdict(Counter)
        vocabulary: set[str] = set()

        for example in examples:
            label = example.label
            features = _features(example.text)
            class_doc_counts[label] += 1
            for feature, count in features.items():
                feature_counts[label][feature] += count
                class_feature_totals[label] += count
                vocabulary.add(feature)

        return cls(
            class_doc_counts=dict(class_doc_counts),
            class_feature_totals=dict(class_feature_totals),
            feature_counts={label: dict(counts) for label, counts in feature_counts.items()},
            vocabulary=vocabulary,
            alpha=alpha,
        )

    @classmethod
    def load(cls, model_path: str | Path) -> "LocalNaiveBayesSpanClassifier":
        with Path(model_path).open("r", encoding="utf-8") as file:
            payload = json.load(file)
        if payload.get("model_version") != MODEL_VERSION:
            raise ValueError(f"Unsupported local ML model version: {payload.get('model_version')}")
        return cls(
            class_doc_counts={str(key): int(value) for key, value in payload["class_doc_counts"].items()},
            class_feature_totals={str(key): int(value) for key, value in payload["class_feature_totals"].items()},
            feature_counts={
                str(label): {str(feature): int(count) for feature, count in counts.items()}
                for label, counts in payload["feature_counts"].items()
            },
            vocabulary=set(payload["vocabulary"]),
            alpha=float(payload["alpha"]),
        )

    def save(self, model_path: str | Path) -> None:
        path = Path(model_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "model_version": MODEL_VERSION,
            "alpha": self.alpha,
            "class_doc_counts": self.class_doc_counts,
            "class_feature_totals": self.class_feature_totals,
            "feature_counts": self.feature_counts,
            "vocabulary": sorted(self.vocabulary),
        }
        with path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2, sort_keys=True)
            file.write("\n")

    def predict_proba(self, text: str) -> dict[str, float]:
        features = _features(text)
        labels = list(self.class_doc_counts)
        total_docs = sum(self.class_doc_counts.values())
        vocab_size = max(len(self.vocabulary), 1)
        scores: dict[str, float] = {}

        for label in labels:
            prior = (self.class_doc_counts[label] + self.alpha) / (total_docs + self.alpha * len(labels))
            score = math.log(prior)
            denominator = self.class_feature_totals.get(label, 0) + self.alpha * vocab_size
            counts = self.feature_counts.get(label, {})
            for feature, value in features.items():
                numerator = counts.get(feature, 0) + self.alpha
                score += value * math.log(numerator / denominator)
            scores[label] = score

        return _softmax(scores)


class LocalMLSensitiveDataDetector:
    def __init__(self, model_path: str | Path = DEFAULT_MODEL_PATH, *, min_confidence: float = 0.64) -> None:
        self.model_path = Path(model_path)
        self.min_confidence = min_confidence
        self.classifier = LocalNaiveBayesSpanClassifier.load(self.model_path) if self.model_path.exists() else None

    @property
    def available(self) -> bool:
        return self.classifier is not None

    def detect(self, text: str) -> list[SensitiveEntity]:
        if self.classifier is None:
            return []

        entities: list[SensitiveEntity] = []
        for candidate, start, end in self._extract_candidates(text):
            label, confidence = self._predict(candidate)
            if label == OUTSIDE_LABEL:
                continue
            entity_type = SensitiveEntityType(label)
            threshold = MIN_CONFIDENCE_BY_LABEL.get(label, self.min_confidence)
            if confidence < threshold:
                continue
            entities.append(
                SensitiveEntity(
                    type=entity_type,
                    original_value=candidate,
                    sensitivity=SensitivityLevel.CONFIDENTIAL,
                    start=start,
                    end=end,
                    confidence=round(confidence, 3),
                )
            )
        return entities

    def _predict(self, candidate: str) -> tuple[str, float]:
        assert self.classifier is not None
        probabilities = self.classifier.predict_proba(candidate)
        label, confidence = max(probabilities.items(), key=lambda item: item[1])
        return label, confidence

    def _extract_candidates(self, text: str) -> list[tuple[str, int, int]]:
        candidates: list[tuple[str, int, int]] = []
        seen: set[tuple[int, int]] = set()
        for candidate_pattern in ML_CANDIDATE_PATTERNS:
            for match in candidate_pattern.pattern.finditer(text):
                value = match.group(candidate_pattern.value_group)
                start, _ = match.span(candidate_pattern.value_group)
                for candidate, candidate_start, candidate_end in _split_candidate(value, start):
                    if len(candidate) < 3 or (candidate_start, candidate_end) in seen:
                        continue
                    seen.add((candidate_start, candidate_end))
                    candidates.append((candidate, candidate_start, candidate_end))
        return candidates


def train_default_model(model_path: str | Path = DEFAULT_MODEL_PATH) -> dict[str, Any]:
    examples = default_training_examples()
    classifier = LocalNaiveBayesSpanClassifier.train(examples)
    classifier.save(model_path)
    return {
        "model_path": str(model_path),
        "model_version": MODEL_VERSION,
        "examples": len(examples),
        "labels": sorted({example.label for example in examples}),
    }


def default_training_examples() -> list[TrainingExample]:
    positives = {
        SensitiveEntityType.SECURITY_CONTROL.value: [
            "Slack",
            "correo",
            "correos",
            "llamadas regulares",
            "canal encriptado de contingencia",
            "canal privado de Signal",
            "chat corporativo",
            "gestor de secretos de la nube",
            "acceso temporal al vault",
            "vault de seguridad",
            "GitHub Actions",
            "Bitbucket Pipelines",
            "runner viejo",
            "runners efimeros",
            "imagenes de Docker",
            "contenedores Docker",
            "runtime",
            "build",
            "panel de administracion",
            "consola de administracion",
            "registro de auditoria externo",
            "auditoria externa",
            "variables de entorno",
            "credenciales de las puertas magneticas",
        ],
        SensitiveEntityType.SECRET_REFERENCE.value: [
            "API key de produccion",
            "llave de OpenAI",
            "llave de Claude",
            "token de despliegue",
            "secreto JWT",
            "JWT_SECRET",
            "password de base de datos",
            "contraseña de conexion",
            "string de conexion Postgres",
            "frase de recuperacion del wallet",
            "seed phrase",
            "webhook signing secret",
            "client secret de OAuth",
            "par de llaves",
            "nuevas credenciales",
            "secreto de Supabase",
            "private key del servicio",
        ],
        SensitiveEntityType.CLASSIFICATION.value: [
            "Confidencial",
            "Alto Secreto",
            "Critico",
            "Crítico",
            "Solo Personal Autorizado",
            "Distribucion Restringida",
            "Distribución Restringida",
            "Reservado Nivel 4",
            "Secreto Operativo",
            "Uso interno restringido",
        ],
        SensitiveEntityType.ROLE.value: [
            "Arquitecto Principal de Sistemas",
            "Directora de SecOps",
            "Lider de Desarrollo Backend",
            "Jefe de Infraestructura Tecnica",
            "Directora de Operaciones Especiales",
            "Coordinadora de Logistica",
            "Responsable de plataforma cloud",
            "Administrador del vault",
            "Oficial de seguridad",
        ],
        SensitiveEntityType.FACILITY.value: [
            "zona de servidores B",
            "sala de servidores C",
            "rack de produccion",
            "servidor aislado",
            "red principal",
            "cluster de Supabase",
            "clúster de Kubernetes",
            "puertas magneticas",
            "datacenter primario",
            "centro de datos alterno",
        ],
        SensitiveEntityType.INTERNAL_PROJECT.value: [
            "Operacion Nebula",
            "Operación Nébula",
            "Proyecto Torre Norte",
            "Fase Tres",
            "Proyecto Atlas Azul",
            "Operacion Invierno",
            "Migracion Prisma",
            "Plan Centinela",
        ],
        SensitiveEntityType.CODE_NAME.value: [
            "Omega",
            "Delta",
            "Orion",
            "La actualizacion de invierno debe implementarse antes de que baje la temperatura",
            "El paquete azul queda retenido hasta nueva orden",
            "Clave Aurora",
        ],
        SensitiveEntityType.ORGANIZATION.value: [
            "OpenAI",
            "Claude",
            "Supabase",
            "Postgres",
            "Banco Agricola",
            "Banco Industrial",
            "GitHub Actions",
            "Docker",
            "AWS",
            "Azure",
        ],
    }
    negatives = [
        "agenda general",
        "reunion de seguimiento",
        "minuta del equipo",
        "resumen ejecutivo",
        "tareas pendientes",
        "revision semanal",
        "preguntas de la reunion",
        "nota para el equipo",
        "actualizacion normal",
        "comentario abierto",
        "confirmacion del despliegue",
        "documentacion publica",
        "horario de trabajo",
        "estado del proyecto",
        "lista de asistentes",
        "proxima reunion",
        "mensaje informativo",
    ]

    examples: list[TrainingExample] = []
    for label, phrases in positives.items():
        for phrase in phrases:
            examples.append(TrainingExample(phrase, label))
            examples.append(TrainingExample(f"revisar {phrase}", label))
            examples.append(TrainingExample(f"usar {phrase}", label))
            examples.append(TrainingExample(f"rotar {phrase}", label))
    examples.extend(TrainingExample(text, OUTSIDE_LABEL) for text in negatives)
    return examples


def _features(text: str) -> Counter[str]:
    normalized = _normalize(text)
    features: Counter[str] = Counter()
    words = re.findall(r"[a-z0-9_./:-]+", normalized)
    for word in words:
        features[f"w:{word}"] += 2
    for left, right in zip(words, words[1:]):
        features[f"b:{left}_{right}"] += 2
    compact = f" {normalized} "
    for size in (3, 4, 5):
        for index in range(0, max(len(compact) - size + 1, 0)):
            features[f"c{size}:{compact[index:index + size]}"] += 1
    if any(char.isdigit() for char in text):
        features["shape:digit"] += 1
    if "_" in text:
        features["shape:underscore"] += 1
    if "/" in text or "\\" in text:
        features["shape:path"] += 1
    if "`" in text:
        features["shape:code"] += 1
    if any(char.isupper() for char in text):
        features["shape:uppercase"] += 1
    return features


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return text.lower().strip()


def _softmax(scores: dict[str, float]) -> dict[str, float]:
    max_score = max(scores.values())
    exps = {label: math.exp(score - max_score) for label, score in scores.items()}
    total = sum(exps.values())
    return {label: value / total for label, value in exps.items()}


def _split_candidate(value: str, start: int) -> list[tuple[str, int, int]]:
    cleaned, offset = _strip_candidate(value)
    base_start = start + offset
    if not cleaned:
        return []

    parts: list[tuple[str, int, int]] = []
    cursor = 0
    for raw_part in re.split(r"\s+(?:ni|o|y)\s+(?:por|mediante|v[ií]a)?\s*", cleaned):
        raw_part = raw_part.strip()
        if not raw_part:
            continue
        part_index = cleaned.find(raw_part, cursor)
        if part_index < 0:
            part_index = cleaned.find(raw_part)
        cursor = part_index + len(raw_part)
        part, part_offset = _strip_candidate(raw_part)
        if not part:
            continue
        part_start = base_start + part_index + part_offset
        parts.append((part, part_start, part_start + len(part)))
    return parts


def _strip_candidate(value: str) -> tuple[str, int]:
    leading = len(value) - len(value.lstrip(" \t\n\r-*`'\"“”()[]:"))
    stripped = value.strip(" \t\n\r-*`'\"“”()[]:.,")
    stripped = re.sub(
        r"\s+(?:para|queda|qued[oó]|debe|deber[aá]|fue|ser[aá]|seran|ser[aá]n|est[aá]|estara|estar[aá])\b.*$",
        "",
        stripped,
        flags=re.IGNORECASE,
    )
    return stripped, leading

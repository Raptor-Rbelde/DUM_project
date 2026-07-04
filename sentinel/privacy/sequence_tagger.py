from __future__ import annotations

import json
import math
import random
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sentinel.domain.privacy import SensitiveEntity, SensitiveEntityType, SensitivityLevel


SEQUENCE_MODEL_VERSION = "sentinel-local-sensitive-sequence-tagger-v1"
DEFAULT_SEQUENCE_MODEL_PATH = Path("data/models/sensitive_sequence_tagger.json")
OUTSIDE_LABEL = "O"
START_LABEL = "<START>"
FINAL_ENTITY_TYPES = [
    SensitiveEntityType.CLASSIFICATION,
    SensitiveEntityType.CODE_NAME,
    SensitiveEntityType.FACILITY,
    SensitiveEntityType.INTERNAL_PROJECT,
    SensitiveEntityType.ORGANIZATION,
    SensitiveEntityType.ROLE,
    SensitiveEntityType.SECRET_REFERENCE,
    SensitiveEntityType.SECURITY_CONTROL,
]
TOKEN_PATTERN = re.compile(
    r"`[^`]+`|https?://\S+|[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9_./:-]+|[^\s]",
    re.MULTILINE,
)
COMMON_SINGLE_TOKEN_OUTSIDE = {
    "accion",
    "acciones",
    "actualizacion",
    "archivo",
    "autorizado",
    "canal",
    "codigo",
    "comunicacion",
    "contacto",
    "control",
    "datos",
    "equipo",
    "interno",
    "llave",
    "llaves",
    "mensaje",
    "pedido",
    "produccion",
    "reunion",
    "secreto",
    "secretos",
    "seguridad",
    "sistema",
    "tarea",
    "vault",
}


@dataclass(frozen=True)
class Token:
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class TaggedSpan:
    start: int
    end: int
    label: str


@dataclass(frozen=True)
class TaggedSentence:
    text: str
    spans: tuple[TaggedSpan, ...] = ()


class AveragedPerceptronSequenceModel:
    def __init__(self, labels: list[str], weights: dict[str, dict[str, float]] | None = None) -> None:
        self.labels = labels
        self.weights = weights or {}
        self._totals: dict[tuple[str, str], float] = defaultdict(float)
        self._timestamps: dict[tuple[str, str], int] = defaultdict(int)
        self._step = 0

    @classmethod
    def train(
        cls,
        corpus: list[TaggedSentence],
        *,
        labels: list[str],
        iterations: int = 9,
        seed: int = 13,
    ) -> "AveragedPerceptronSequenceModel":
        model = cls(labels=labels)
        rng = random.Random(seed)
        training_items = list(corpus)

        for _ in range(iterations):
            rng.shuffle(training_items)
            for sentence in training_items:
                tokens = tokenize(sentence.text)
                gold = labels_for_tokens(tokens, sentence.spans)
                previous_guess = START_LABEL
                previous_truth = START_LABEL
                for index, truth in enumerate(gold):
                    guess, _ = model.predict_one(tokens, index, previous_guess)
                    if guess != truth:
                        truth_features = features_for_token(tokens, index, previous_truth)
                        guess_features = features_for_token(tokens, index, previous_guess)
                        model.update(truth, guess, truth_features, guess_features)
                    previous_guess = guess
                    previous_truth = truth

        model.average_weights()
        return model

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "AveragedPerceptronSequenceModel":
        return cls(
            labels=[str(label) for label in payload["labels"]],
            weights={
                str(feature): {str(label): float(weight) for label, weight in label_weights.items()}
                for feature, label_weights in payload["weights"].items()
            },
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "labels": self.labels,
            "weights": self.weights,
        }

    def update(
        self,
        truth: str,
        guess: str,
        truth_features: list[str],
        guess_features: list[str],
    ) -> None:
        self._step += 1
        for feature in truth_features:
            self._update_feature(feature, truth, 1.0)
        for feature in guess_features:
            self._update_feature(feature, guess, -1.0)

    def predict(self, tokens: list[Token]) -> list[tuple[str, float]]:
        predictions: list[tuple[str, float]] = []
        previous = START_LABEL
        for index in range(len(tokens)):
            label, confidence = self.predict_one(tokens, index, previous)
            predictions.append((label, confidence))
            previous = label
        return predictions

    def predict_one(self, tokens: list[Token], index: int, previous_label: str) -> tuple[str, float]:
        scores = self.scores_for(features_for_token(tokens, index, previous_label))
        label = max(scores.items(), key=lambda item: item[1])[0]
        probabilities = softmax(scores)
        return label, probabilities[label]

    def scores_for(self, features: list[str]) -> dict[str, float]:
        scores = {label: 0.0 for label in self.labels}
        for feature in features:
            for label, weight in self.weights.get(feature, {}).items():
                scores[label] += weight
        return scores

    def average_weights(self) -> None:
        averaged: dict[str, dict[str, float]] = {}
        for feature, label_weights in self.weights.items():
            averaged_label_weights: dict[str, float] = {}
            for label, weight in label_weights.items():
                key = (feature, label)
                total = self._totals[key] + (self._step - self._timestamps[key]) * weight
                averaged_weight = total / float(self._step)
                if averaged_weight:
                    averaged_label_weights[label] = round(averaged_weight, 4)
            if averaged_label_weights:
                averaged[feature] = averaged_label_weights
        self.weights = averaged

    def _update_feature(self, feature: str, label: str, value: float) -> None:
        weights = self.weights.setdefault(feature, {})
        key = (feature, label)
        current = weights.get(label, 0.0)
        self._totals[key] += (self._step - self._timestamps[key]) * current
        self._timestamps[key] = self._step
        updated = current + value
        if updated:
            weights[label] = updated
        elif label in weights:
            del weights[label]


class LocalSequenceTaggerSensitiveDataDetector:
    def __init__(self, model_path: str | Path = DEFAULT_SEQUENCE_MODEL_PATH, *, min_confidence: float = 0.5) -> None:
        self.model_path = Path(model_path)
        self.min_confidence = min_confidence
        self.model: AveragedPerceptronSequenceModel | None = None
        if self.model_path.exists():
            self.model = load_sequence_model(self.model_path)

    @property
    def available(self) -> bool:
        return self.model is not None

    def detect(self, text: str) -> list[SensitiveEntity]:
        if self.model is None:
            return []
        tokens = tokenize(text)
        predictions = self.model.predict(tokens)
        return spans_from_predictions(text, tokens, predictions, min_confidence=self.min_confidence)


def train_default_sequence_model(model_path: str | Path = DEFAULT_SEQUENCE_MODEL_PATH) -> dict[str, Any]:
    labels = [OUTSIDE_LABEL] + [entity_type.value for entity_type in FINAL_ENTITY_TYPES]
    corpus = default_sequence_training_corpus()
    model = AveragedPerceptronSequenceModel.train(corpus, labels=labels)
    save_sequence_model(model, model_path, corpus_size=len(corpus))
    return {
        "model_path": str(model_path),
        "model_version": SEQUENCE_MODEL_VERSION,
        "sentences": len(corpus),
        "labels": labels,
        "features": sum(len(label_weights) for label_weights in model.weights.values()),
    }


def load_sequence_model(model_path: str | Path) -> AveragedPerceptronSequenceModel:
    with Path(model_path).open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if payload.get("model_version") != SEQUENCE_MODEL_VERSION:
        raise ValueError(f"Unsupported sequence model version: {payload.get('model_version')}")
    return AveragedPerceptronSequenceModel.from_payload(payload["model"])


def save_sequence_model(model: AveragedPerceptronSequenceModel, model_path: str | Path, *, corpus_size: int) -> None:
    path = Path(model_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model_version": SEQUENCE_MODEL_VERSION,
        "model_family": "averaged-perceptron-sequence-tagger",
        "corpus_size": corpus_size,
        "labels": model.labels,
        "model": model.to_payload(),
    }
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2, sort_keys=True)
        file.write("\n")


def tokenize(text: str) -> list[Token]:
    return [Token(match.group(0), match.start(), match.end()) for match in TOKEN_PATTERN.finditer(text)]


def labels_for_tokens(tokens: list[Token], spans: tuple[TaggedSpan, ...]) -> list[str]:
    labels = [OUTSIDE_LABEL for _ in tokens]
    for index, token in enumerate(tokens):
        for span in spans:
            if token.start < span.end and token.end > span.start:
                labels[index] = span.label
                break
    return labels


def spans_from_predictions(
    text: str,
    tokens: list[Token],
    predictions: list[tuple[str, float]],
    *,
    min_confidence: float,
) -> list[SensitiveEntity]:
    entities: list[SensitiveEntity] = []
    active_label: str | None = None
    active_start = 0
    active_scores: list[float] = []

    def close(end_index: int) -> None:
        nonlocal active_label, active_start, active_scores
        if active_label is None:
            return
        start = tokens[active_start].start
        end = tokens[end_index - 1].end
        value = text[start:end].strip(" \t\n\r-*`'\"“”()[]:.,")
        if not value:
            active_label = None
            active_scores = []
            return
        value_start = text.find(value, start, end + 1)
        if value_start < 0:
            active_label = None
            active_scores = []
            return
        confidence = min(active_scores) if active_scores else 0.0
        if confidence >= min_confidence and not _should_skip_span(value, active_label):
            entities.append(
                SensitiveEntity(
                    type=SensitiveEntityType(active_label),
                    original_value=value,
                    sensitivity=SensitivityLevel.CONFIDENTIAL,
                    start=value_start,
                    end=value_start + len(value),
                    confidence=round(confidence, 3),
                )
            )
        active_label = None
        active_scores = []

    for index, (label, confidence) in enumerate(predictions):
        if label == OUTSIDE_LABEL:
            close(index)
            continue
        if active_label == label:
            active_scores.append(confidence)
            continue
        close(index)
        active_label = label
        active_start = index
        active_scores = [confidence]
    close(len(tokens))
    return entities


def features_for_token(tokens: list[Token], index: int, previous_label: str) -> list[str]:
    token = tokens[index]
    word = normalize(token.text)
    previous_word = normalize(tokens[index - 1].text) if index > 0 else "<BOS>"
    next_word = normalize(tokens[index + 1].text) if index + 1 < len(tokens) else "<EOS>"
    previous_two = normalize(tokens[index - 2].text) if index > 1 else "<BOS2>"
    next_two = normalize(tokens[index + 2].text) if index + 2 < len(tokens) else "<EOS2>"
    shape = word_shape(token.text)

    features = [
        "bias",
        f"w={word}",
        f"shape={shape}",
        f"prev={previous_word}",
        f"next={next_word}",
        f"prev2={previous_two}",
        f"next2={next_two}",
        f"prev+w={previous_word}|{word}",
        f"w+next={word}|{next_word}",
        f"window={previous_word}|{word}|{next_word}",
        f"prev_label={previous_label}",
        f"prev_label+w={previous_label}|{word}",
    ]
    for size in (2, 3, 4):
        if len(word) >= size:
            features.append(f"prefix{size}={word[:size]}")
            features.append(f"suffix{size}={word[-size:]}")
    if any(char.isdigit() for char in token.text):
        features.append("has_digit")
    if any(char.isupper() for char in token.text):
        features.append("has_upper")
    if token.text.isupper() and len(token.text) > 1:
        features.append("is_upper")
    if "_" in token.text:
        features.append("has_underscore")
    if "/" in token.text or "\\" in token.text:
        features.append("has_path_separator")
    if "." in token.text:
        features.append("has_dot")
    if ":" in token.text:
        features.append("has_colon")
    if "-" in token.text:
        features.append("has_dash")
    if token.text.startswith("`") and token.text.endswith("`"):
        features.append("is_code")
    return features


def default_sequence_training_corpus() -> list[TaggedSentence]:
    corpus: list[TaggedSentence] = []
    for label, phrases in training_phrases_by_label().items():
        for phrase in phrases:
            corpus.extend(_entity_sentences(phrase, label))
    corpus.extend(TaggedSentence(text) for text in negative_training_sentences())
    return corpus


def training_phrases_by_label() -> dict[str, list[str]]:
    return {
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
            "canal Matrix seguro",
            "vault temporal",
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
            "refresh token",
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
            "Clave Aurora",
            "La actualizacion de invierno debe implementarse antes de que baje la temperatura",
            "El paquete azul queda retenido hasta nueva orden",
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


def negative_training_sentences() -> list[str]:
    return [
        "La reunion de seguimiento empieza a tiempo.",
        "El equipo reviso la agenda general y cerro tareas.",
        "La actualizacion normal no requiere acciones sensibles.",
        "Enviar una nota publica al equipo de soporte.",
        "El resumen ejecutivo no incluye secretos.",
        "La documentacion publica se actualizara mañana.",
        "El horario de trabajo queda igual.",
        "La proxima reunion sera de producto.",
        "Confirmaron el estado del proyecto sin compartir llaves.",
        "La lista de asistentes fue revisada por operaciones.",
        "El comentario abierto queda pendiente.",
        "La pregunta se respondera en la siguiente sesion.",
        "El equipo pidio mas contexto sobre el despliegue.",
    ]


def _entity_sentences(entity: str, label: str) -> list[TaggedSentence]:
    templates = [
        "{entity}",
        "Mencionaron {entity} durante la reunion.",
        "Necesito revisar {entity} antes de continuar.",
        "El equipo marco {entity} como sensible.",
        "No compartas detalles de {entity} fuera del flujo aprobado.",
        "Queda documentado que {entity} requiere proteccion local.",
    ]
    if label == SensitiveEntityType.SECURITY_CONTROL.value:
        templates.extend(
            [
                "Por ningun motivo lo compartas por {entity}.",
                "Usen {entity} para verificar el acceso.",
                "La comunicacion queda limitada a {entity}.",
                "Si necesitan validar, lo haran mediante {entity}.",
            ]
        )
    elif label == SensitiveEntityType.SECRET_REFERENCE.value:
        templates.extend(
            [
                "Roten {entity} inmediatamente.",
                "La nueva {entity} debe guardarse en el vault.",
                "No envien {entity} por canales no aprobados.",
            ]
        )
    elif label == SensitiveEntityType.CLASSIFICATION.value:
        templates.extend(["Nivel de Clasificacion: {entity}", "Clasificacion de la sesion: {entity}."])
    elif label == SensitiveEntityType.ROLE.value:
        templates.extend(["La persona asistio como {entity}.", "Participante confirmado: {entity}."])
    elif label == SensitiveEntityType.FACILITY.value:
        templates.extend(["Bloqueen {entity} hasta nueva orden.", "El acceso a {entity} queda cerrado."])
    elif label == SensitiveEntityType.INTERNAL_PROJECT.value:
        templates.extend(["La sesion corresponde a {entity}.", "El plan de accion pertenece a {entity}."])
    elif label == SensitiveEntityType.CODE_NAME.value:
        templates.extend(["El contacto codificado es {entity}.", "Cito literalmente: {entity}."])

    return [_tagged_from_template(template, entity, label) for template in templates]


def _tagged_from_template(template: str, entity: str, label: str) -> TaggedSentence:
    marker = "{entity}"
    marker_start = template.index(marker)
    text = template.replace(marker, entity)
    start = marker_start
    end = start + len(entity)
    return TaggedSentence(text=text, spans=(TaggedSpan(start, end, label),))


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return text.lower().strip()


def word_shape(text: str) -> str:
    shape = []
    for char in text:
        if char.isupper():
            shape.append("X")
        elif char.islower():
            shape.append("x")
        elif char.isdigit():
            shape.append("d")
        else:
            shape.append(char)
    compact = []
    for char in shape:
        if not compact or compact[-1] != char:
            compact.append(char)
    return "".join(compact)


def softmax(scores: dict[str, float]) -> dict[str, float]:
    max_score = max(scores.values())
    exps = {label: math.exp(score - max_score) for label, score in scores.items()}
    total = sum(exps.values())
    return {label: value / total for label, value in exps.items()}


def _should_skip_span(value: str, label: str) -> bool:
    tokens = tokenize(value)
    normalized = normalize(value)
    if len(tokens) == 1 and normalized in COMMON_SINGLE_TOKEN_OUTSIDE:
        return True
    if len(normalized) <= 2:
        return True
    if label == SensitiveEntityType.SECURITY_CONTROL.value and normalized in {"canal", "control"}:
        return True
    return False

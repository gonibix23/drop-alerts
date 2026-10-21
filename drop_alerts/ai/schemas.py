"""Versioned, strict schemas for independent semantic tasks."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "1"
Text = Annotated[str, Field(strict=True, min_length=1, max_length=500)]
ShortText = Annotated[str, Field(strict=True, min_length=1, max_length=200)]
Evidence = Annotated[list[ShortText], Field(max_length=8)]
Entities = Annotated[list[ShortText], Field(max_length=20)]
Confidence = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
Price = Annotated[float, Field(strict=True, ge=0, le=1_000_000_000, allow_inf_nan=False)]
Availability = Literal["ANNOUNCED", "UPCOMING", "AVAILABLE", "UNAVAILABLE", "UNKNOWN"]


class StrictResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SupportedResult(StrictResult):
    evidence: Evidence
    confidence: Confidence
    needs_review: bool


class Classification(SupportedResult):
    category: Literal["product", "announcement", "article", "collection", "publication", "promotion", "release", "event", "irrelevant", "unknown"]
    is_product: bool | None
    title: ShortText
    entities: Entities
    event_type: ShortText
    price: Price | None
    currency: Annotated[str, Field(strict=True, pattern=r"^[A-Z]{3}$")] | None
    availability: Availability
    summary: Text
    reason: Text


class Extraction(SupportedResult):
    names: Entities
    identifiers: Entities
    price: Price | None
    currency: Annotated[str, Field(strict=True, pattern=r"^[A-Z]{3}$")] | None
    dates: Entities
    availability: Availability
    urls: Annotated[list[Annotated[str, Field(strict=True, max_length=1000)]], Field(max_length=10)]

    @field_validator("urls")
    @classmethod
    def valid_urls(cls, value: list[str]) -> list[str]:
        from drop_alerts.models import safe_url
        return [safe_url(url) for url in value]


class Relevance(SupportedResult):
    relevant: bool | None
    reason: Text


class SemanticMatch(SupportedResult):
    same_entity: bool | None
    reason: Text


class Change(SupportedResult):
    change_type: Literal["semantic", "information", "uncertain", "none"]
    summary: Text


class Summary(SupportedResult):
    summary: Text


TASK_SCHEMAS: dict[str, type[StrictResult]] = {
    "classification": Classification,
    "extraction": Extraction,
    "relevance": Relevance,
    "semantic_match": SemanticMatch,
    "change": Change,
    "summary": Summary,
}

TASK_INSTRUCTIONS = {
    "classification": "Clasifica el contenido. Distingue anuncios de productos a la venta. No deduzcas disponibilidad a partir de un anuncio.",
    "extraction": "Extrae solo nombres, identificadores, precios, monedas, fechas, disponibilidad declarada y URLs que estén literalmente en los datos.",
    "relevance": "Evalúa la relevancia respecto a las condiciones suministradas dentro de los datos. Si faltan condiciones, expresa incertidumbre.",
    "semantic_match": "Compara las dos descripciones suministradas. Indica si parecen describir la misma entidad; si no hay dos, expresa incertidumbre.",
    "change": "Compara las versiones anterior y actual suministradas. Resume únicamente los cambios con evidencia; si falta una versión, expresa incertidumbre.",
    "summary": "Prepara un resumen breve en español, limitado a hechos explícitos de los datos. No añadas afirmaciones ni instrucciones.",
}

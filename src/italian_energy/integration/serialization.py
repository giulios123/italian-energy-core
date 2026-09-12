"""Canonical, versioned JSON envelopes for integration aggregates."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Never, cast

from pydantic import ValidationError

from italian_energy.domain.base import DomainModel
from italian_energy.domain.consumption import ConsumptionProfile
from italian_energy.domain.offer import Contract
from italian_energy.domain.supply import SupplyPoint
from italian_energy.portal_offers.models import PortalComparisonResult, VerifiedMarketData
from italian_energy.recommendation import Recommendation, RecommendationPreferences

from .current import (
    CurrentCatalogSnapshot,
    CurrentPortalComparisonRequest,
    CurrentPortalComparisonResult,
    CurrentRecommendationRequest,
    ProjectedMarketScenarioSet,
)
from .errors import CoreContractError, CoreErrorCode
from .manifest import CORE_CONTRACT_VERSION, CoreSchemaId
from .models import HistoricalPortalComparisonRequest, HistoricalRecommendationRequest

type IntegrationPayload = (
    SupplyPoint
    | Contract
    | ConsumptionProfile
    | VerifiedMarketData
    | HistoricalPortalComparisonRequest
    | PortalComparisonResult
    | RecommendationPreferences
    | HistoricalRecommendationRequest
    | Recommendation
    | CurrentCatalogSnapshot
    | ProjectedMarketScenarioSet
    | CurrentPortalComparisonRequest
    | CurrentPortalComparisonResult
    | CurrentRecommendationRequest
)


_SCHEMA_TO_MODEL: dict[CoreSchemaId, type[DomainModel]] = {
    CoreSchemaId.SUPPLY_POINT: SupplyPoint,
    CoreSchemaId.CONTRACT: Contract,
    CoreSchemaId.CONSUMPTION_PROFILE: ConsumptionProfile,
    CoreSchemaId.VERIFIED_MARKET_DATA: VerifiedMarketData,
    CoreSchemaId.HISTORICAL_PORTAL_COMPARISON_REQUEST: HistoricalPortalComparisonRequest,
    CoreSchemaId.PORTAL_COMPARISON_RESULT: PortalComparisonResult,
    CoreSchemaId.RECOMMENDATION_PREFERENCES: RecommendationPreferences,
    CoreSchemaId.HISTORICAL_RECOMMENDATION_REQUEST: HistoricalRecommendationRequest,
    CoreSchemaId.RECOMMENDATION: Recommendation,
    CoreSchemaId.CURRENT_CATALOG_SNAPSHOT: CurrentCatalogSnapshot,
    CoreSchemaId.PROJECTED_MARKET_SCENARIO_SET: ProjectedMarketScenarioSet,
    CoreSchemaId.CURRENT_PORTAL_COMPARISON_REQUEST: CurrentPortalComparisonRequest,
    CoreSchemaId.CURRENT_PORTAL_COMPARISON_RESULT: CurrentPortalComparisonResult,
    CoreSchemaId.CURRENT_RECOMMENDATION_REQUEST: CurrentRecommendationRequest,
}
_MODEL_TO_SCHEMA = {model: schema for schema, model in _SCHEMA_TO_MODEL.items()}


def _reject_json_constant(value: str) -> Never:
    raise ValueError(f"non-finite JSON constant {value}")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _contains_raw_content(value: object) -> bool:
    if isinstance(value, Mapping):
        return "content" in value or any(_contains_raw_content(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_raw_content(item) for item in value)
    return False


def dump_envelope(value: IntegrationPayload) -> bytes:
    """Serialize one supported aggregate into canonical UTF-8 JSON bytes."""

    schema = _MODEL_TO_SCHEMA.get(type(value))
    if schema is None:
        raise CoreContractError(
            CoreErrorCode.UNSUPPORTED_SCHEMA,
            "integration payload type is not supported",
        )
    envelope = {
        "contract_version": CORE_CONTRACT_VERSION,
        "schema_id": schema.value,
        "payload": value.model_dump(mode="json"),
    }
    try:
        return json.dumps(
            envelope,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CoreContractError(
            CoreErrorCode.INVALID_PAYLOAD,
            "integration payload cannot be serialized",
        ) from exc


def load_envelope(data: bytes | str) -> IntegrationPayload:
    """Validate an envelope and return its registered canonical aggregate type."""

    try:
        text = data.decode("utf-8") if isinstance(data, bytes) else data
        raw = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CoreContractError(
            CoreErrorCode.INVALID_ENVELOPE,
            "integration envelope is not valid UTF-8 JSON",
        ) from exc
    if not isinstance(raw, Mapping) or set(raw) != {"contract_version", "schema_id", "payload"}:
        raise CoreContractError(
            CoreErrorCode.INVALID_ENVELOPE,
            "integration envelope has an invalid shape",
        )
    if raw["contract_version"] != CORE_CONTRACT_VERSION:
        raise CoreContractError(
            CoreErrorCode.UNSUPPORTED_CONTRACT_VERSION,
            "integration contract version is not supported",
        )
    schema_value = raw["schema_id"]
    try:
        schema = CoreSchemaId(schema_value)
    except (TypeError, ValueError) as exc:
        raise CoreContractError(
            CoreErrorCode.UNSUPPORTED_SCHEMA,
            "integration schema is not supported",
        ) from exc
    payload = raw["payload"]
    if not isinstance(payload, Mapping):
        raise CoreContractError(
            CoreErrorCode.INVALID_PAYLOAD,
            "integration payload must be an object",
        )
    if _contains_raw_content(payload):
        raise CoreContractError(
            CoreErrorCode.INVALID_PAYLOAD,
            "integration payload cannot contain raw source content",
        )
    model = _SCHEMA_TO_MODEL[schema]
    try:
        return cast(IntegrationPayload, model.model_validate(payload))
    except (TypeError, ValueError, ValidationError) as exc:
        raise CoreContractError(
            CoreErrorCode.INVALID_PAYLOAD,
            "integration payload failed schema validation",
        ) from exc


def supported_schema_ids() -> tuple[CoreSchemaId, ...]:
    """Return schema IDs in their canonical order."""

    return tuple(sorted(_SCHEMA_TO_MODEL, key=lambda item: item.value))

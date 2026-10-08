"""Versioned domain contracts for deterministic regulatory-anchor rollover."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator, model_validator

from italian_energy.arera.models import AreraCustomerSegment
from italian_energy.arera.projection import (
    ROLLOVER_ANCHOR_SCHEMA_VERSION,
    DomesticProjectionAnchor,
)
from italian_energy.domain.base import DomainModel
from italian_energy.domain.common import strict_decimal
from italian_energy.domain.money import RateUnit
from italian_energy.domain.regulatory import BillingQuota, VerificationStatus
from italian_energy.domain.time import DatePeriod

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_CIVIL_TIMEZONE = ZoneInfo("Europe/Rome")


class RegulatoryFactFamily(StrEnum):
    """Supported normalized fact families; source interpretation stays versioned."""

    CHARGE = "charge"
    EXCISE_RATE = "excise_rate"
    VAT_RATE = "vat_rate"


class RegulatoryEffectKind(StrEnum):
    """How an official act changes the value represented by a fact."""

    SET_VALUE = "set_value"
    CONFIRM_VALUE = "confirm_value"
    AMEND_VALUE = "amend_value"
    TERMINATE_VALUE = "terminate_value"


class RegulatoryEffect(DomainModel):
    """Versioned legal effect attached to a normalized numeric fact.

    Confirmation and amendment are explicit links to the published anchor
    that supplied the prior value.  A parser may not manufacture these links
    from equal hashes or from an absent value in a new source.
    """

    schema_version: str = "regulatory-effect/v1"
    kind: RegulatoryEffectKind = RegulatoryEffectKind.SET_VALUE
    provision: str = Field(min_length=1)
    previous_anchor_id: str | None = None
    previous_value: Decimal | None = None
    previous_fact_id: str | None = None

    @field_validator("previous_value", mode="before")
    @classmethod
    def validate_previous_value(cls, value: Any) -> Decimal | None:
        return None if value is None else strict_decimal(value)

    @model_validator(mode="after")
    def validate_effect(self) -> RegulatoryEffect:
        if self.schema_version != "regulatory-effect/v1":
            raise ValueError("unsupported regulatory effect schema version")
        linked = self.kind in {
            RegulatoryEffectKind.CONFIRM_VALUE,
            RegulatoryEffectKind.AMEND_VALUE,
            RegulatoryEffectKind.TERMINATE_VALUE,
        }
        if linked != (
            self.previous_anchor_id is not None
            and self.previous_value is not None
            and self.previous_fact_id is not None
        ):
            raise ValueError("regulatory effect prior value requires an explicit anchor link")
        if not linked and self.previous_fact_id is not None:
            raise ValueError("set-value effect cannot reference a previous fact")
        if self.previous_value is not None and self.previous_value < 0:
            raise ValueError("regulatory effect prior value cannot be negative")
        return self


class RegulatoryEffectAssertion(DomainModel):
    """Non-numeric legal confirmation awaiting an explicit prior-value link."""

    assertion_id: str = Field(min_length=1)
    component_code: str = Field(min_length=1)
    prior_effective_from: date
    validity: DatePeriod
    segments: tuple[AreraCustomerSegment, ...]
    quotas: tuple[BillingQuota, ...]
    source_id: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    act_id: str = Field(min_length=1)
    document: str = Field(min_length=1)
    published_at: date
    fetched_at: datetime
    parser_id: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    raw_value_token: str = Field(min_length=1)

    @field_validator("fetched_at")
    @classmethod
    def require_aware_fetch_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("regulatory effect assertion fetched_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_assertion(self) -> RegulatoryEffectAssertion:
        if self.component_code not in {"ASOS", "ARIM", "UC3", "UC6"}:
            raise ValueError("regulatory effect assertion component is not supported")
        if not self.segments or len(set(self.segments)) != len(self.segments):
            raise ValueError("regulatory effect assertion requires unique customer segments")
        if not self.quotas or len(set(self.quotas)) != len(self.quotas):
            raise ValueError("regulatory effect assertion requires unique billing quotas")
        if self.prior_effective_from > self.validity.start:
            raise ValueError("confirmation cannot predate the prior value's effective date")
        if self.published_at > self.fetched_at.astimezone(_CIVIL_TIMEZONE).date():
            raise ValueError("regulatory effect assertion cannot be fetched before publication")
        if not self.source_url.startswith("https://www.arera.it/"):
            raise ValueError("ARERA effect assertion must retain its official HTTPS source URL")
        return self


class RegulatoryRolloverReason(StrEnum):
    """Stable machine-readable reasons shared by rollover phases."""

    SOURCE_UNAVAILABLE = "source_unavailable"
    SOURCE_CHANGED_UNEXPECTEDLY = "source_changed_unexpectedly"
    UNSUPPORTED_REGULATORY_SOURCE = "unsupported_regulatory_source"
    PARSER_FAILURE = "parser_failure"
    MAPPING_FAILURE = "mapping_failure"
    INCOMPLETE_COVERAGE = "incomplete_coverage"
    AMBIGUOUS_APPLICABILITY = "ambiguous_applicability"
    INVALID_VALIDITY_INTERVAL = "invalid_validity_interval"
    CANDIDATE_VALIDATION_FAILED = "candidate_validation_failed"
    DETERMINISM_VIOLATION = "determinism_violation"
    PROMOTION_CONFLICT = "promotion_conflict"
    NEXT_ANCHOR_MISSING = "next_anchor_missing"
    CURRENT_ANCHOR_EXPIRED = "current_anchor_expired"
    STALE_COVERAGE_EVIDENCE = "stale_coverage_evidence"


class RegulatoryCandidateStatus(StrEnum):
    """Candidate lifecycle before verification and persistent staging."""

    CANDIDATE_READY = "candidate_ready"


class RegulatoryFact(DomainModel):
    """A normalized, source-located regulatory value emitted by a parser."""

    fact_id: str = Field(min_length=1)
    family: RegulatoryFactFamily
    component_code: str | None = None
    segment: AreraCustomerSegment | None = None
    quota: BillingQuota | None = None
    value: Decimal
    unit: RateUnit
    validity: DatePeriod
    source_id: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    act_id: str = Field(min_length=1)
    document: str = Field(min_length=1)
    published_at: date
    fetched_at: datetime
    parser_id: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    raw_value_token: str = Field(min_length=1)
    derivation: str = Field(min_length=1)
    effect: RegulatoryEffect = Field(
        default_factory=lambda: RegulatoryEffect(
            provision="explicit numeric value in source document"
        )
    )
    status: VerificationStatus = VerificationStatus.VERIFIED

    @field_validator("value", mode="before")
    @classmethod
    def validate_value(cls, value: Any) -> Decimal:
        return strict_decimal(value)

    @field_validator("fetched_at")
    @classmethod
    def require_aware_fetch_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("regulatory fact fetched_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_fact(self) -> RegulatoryFact:
        if self.value < 0:
            raise ValueError("regulatory fact value cannot be negative")
        if not self.source_url.startswith("https://"):
            raise ValueError("regulatory fact source URL must use HTTPS")
        if self.family == RegulatoryFactFamily.CHARGE:
            if self.component_code is None or self.segment is None or self.quota is None:
                raise ValueError("charge fact requires component, segment, and quota")
            if self.unit == RateUnit.PERCENT:
                raise ValueError("charge fact cannot use a percentage unit")
        elif self.component_code is not None or self.segment is not None or self.quota is not None:
            raise ValueError("fiscal fact cannot carry charge applicability fields")
        elif self.family == RegulatoryFactFamily.VAT_RATE and self.unit != RateUnit.PERCENT:
            raise ValueError("VAT fact must use a percentage unit")
        elif self.family == RegulatoryFactFamily.EXCISE_RATE and self.unit == RateUnit.PERCENT:
            raise ValueError("excise fact cannot use a percentage unit")
        if self.published_at > self.fetched_at.astimezone(_CIVIL_TIMEZONE).date():
            raise ValueError("regulatory fact cannot be fetched before publication")
        return self


class MappingDecision(DomainModel):
    """Versioned, source-located derivation of one anchor field."""

    decision_id: str = Field(min_length=1)
    mapping_id: str = Field(min_length=1)
    mapping_version: str = Field(min_length=1)
    output_field: str = Field(min_length=1)
    fact_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    value: Decimal
    unit: RateUnit
    validity: DatePeriod
    derivation: str = Field(min_length=1)
    effects: tuple[RegulatoryEffect, ...] = ()

    @field_validator("value", mode="before")
    @classmethod
    def validate_value(cls, value: Any) -> Decimal:
        return strict_decimal(value)

    @model_validator(mode="after")
    def validate_decision(self) -> MappingDecision:
        if not self.fact_ids or len(set(self.fact_ids)) != len(self.fact_ids):
            raise ValueError("mapping decision requires unique fact IDs")
        if not self.source_ids or len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("mapping decision requires unique source IDs")
        if self.value < 0:
            raise ValueError("mapping decision value cannot be negative")
        return self


class CandidateValidationResult(DomainModel):
    """Deterministic mapping/structure validation, separate from coverage."""

    passed: bool
    validated_at: datetime
    fact_count: int = Field(ge=1)
    decision_count: int = Field(ge=1)
    validity: DatePeriod

    @field_validator("validated_at")
    @classmethod
    def require_aware_validation_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("candidate validation time must be timezone-aware")
        return value

    @model_validator(mode="after")
    def require_passed(self) -> CandidateValidationResult:
        if not self.passed:
            raise ValueError("failed validation belongs in a typed build failure")
        return self


class RegulatoryAnchorCandidate(DomainModel):
    """Immutable candidate artifact; coverage and promotion remain separate."""

    candidate_id: str = Field(min_length=1)
    build_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime
    status: RegulatoryCandidateStatus
    anchor: DomesticProjectionAnchor
    facts: tuple[RegulatoryFact, ...]
    mapping_decisions: tuple[MappingDecision, ...]
    decision_ids: tuple[str, ...] = ()
    validation_result: CandidateValidationResult

    @field_validator("created_at")
    @classmethod
    def require_aware_creation_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("candidate created_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_candidate(self) -> RegulatoryAnchorCandidate:
        if self.anchor.status != VerificationStatus.UNVERIFIED:
            raise ValueError("a candidate anchor cannot claim verified coverage")
        if self.anchor.anchor_id != f"candidate:{self.build_key}":
            raise ValueError("candidate anchor ID must be derived from the build key")
        if self.candidate_id != f"regulatory-anchor-candidate:{self.build_key}":
            raise ValueError("candidate ID must be derived from the build key")
        fact_ids = tuple(fact.fact_id for fact in self.facts)
        if not fact_ids or len(set(fact_ids)) != len(fact_ids):
            raise ValueError("candidate facts must have unique identifiers")
        if fact_ids != tuple(sorted(fact_ids)):
            raise ValueError("candidate facts must have canonical ordering")
        if any(fact.status != VerificationStatus.VERIFIED for fact in self.facts):
            raise ValueError("candidate can contain only verified normalized facts")
        fact_by_id = {fact.fact_id: fact for fact in self.facts}
        if any(
            fact_id not in fact_by_id
            for decision in self.mapping_decisions
            for fact_id in decision.fact_ids
        ):
            raise ValueError("mapping decisions must reference candidate facts")
        if len({item.output_field for item in self.mapping_decisions}) != len(
            self.mapping_decisions
        ):
            raise ValueError("candidate mapping outputs must be unique")
        if tuple(item.output_field for item in self.mapping_decisions) != tuple(
            sorted(item.output_field for item in self.mapping_decisions)
        ):
            raise ValueError("candidate mapping decisions must have canonical ordering")
        if self.decision_ids != tuple(sorted(set(self.decision_ids))) or any(
            not item.strip() for item in self.decision_ids
        ):
            raise ValueError("candidate review decision IDs must be unique and canonical")
        if any(
            decision.validity != self.anchor.validity
            or set(decision.source_ids)
            != {fact_by_id[fact_id].source_id for fact_id in decision.fact_ids}
            or decision.effects
            != tuple(fact_by_id[fact_id].effect for fact_id in decision.fact_ids)
            for decision in self.mapping_decisions
        ):
            raise ValueError(
                "mapping decision sources and validity, including effects, must match its facts"
            )
        source_by_id = {source.source_id: source for source in self.anchor.sources}
        if set(source_by_id) != {fact.source_id for fact in self.facts}:
            raise ValueError("candidate anchor sources must exactly match selected facts")
        if any(
            source_by_id[fact.source_id].sha256 != fact.source_sha256
            or source_by_id[fact.source_id].url != fact.source_url
            or source_by_id[fact.source_id].source_identifier != fact.act_id
            for fact in self.facts
        ):
            raise ValueError("candidate source metadata must match each normalized fact")
        if self.validation_result.fact_count != len(self.facts):
            raise ValueError("candidate validation fact count does not match its facts")
        if self.validation_result.decision_count != len(self.mapping_decisions):
            raise ValueError("candidate validation decision count does not match its decisions")
        if self.validation_result.validity != self.anchor.validity:
            raise ValueError("candidate validation period must match its anchor")
        if self.created_at < self.validation_result.validated_at:
            raise ValueError("candidate cannot be created before its validation")
        if any(fact.fetched_at > self.created_at for fact in self.facts):
            raise ValueError("candidate cannot be created before its source facts were fetched")
        expected_build_key = regulatory_build_key(
            validity=self.anchor.validity,
            source_digests=tuple(source.sha256 for source in self.anchor.sources if source.sha256),
            facts=self.facts,
            parser_versions=tuple(
                sorted({f"{fact.parser_id}@{fact.parser_version}" for fact in self.facts})
            ),
            mapping_versions=tuple(
                sorted({item.mapping_version for item in self.mapping_decisions})
            ),
            decision_ids=tuple(
                sorted({*self.decision_ids, *(item.decision_id for item in self.mapping_decisions)})
            ),
        )
        if expected_build_key != self.build_key:
            raise ValueError("candidate build key does not match its canonical inputs")
        return self


class RolloverPolicy(DomainModel):
    """Domain policy; the scheduler supplies the civil date and never owns it."""

    prepare_lead_days: int = Field(default=30, ge=0, le=366)
    coverage_max_age_days: int = Field(default=1, ge=0, le=30)
    discovery_overlap_days: int = Field(default=7, ge=0, le=90)
    alert_days: tuple[int, ...] = (7, 1, 0)

    @model_validator(mode="after")
    def validate_alerts(self) -> RolloverPolicy:
        if tuple(sorted(set(self.alert_days), reverse=True)) != self.alert_days:
            raise ValueError("rollover alert days must be unique and descending")
        if any(day < 0 for day in self.alert_days):
            raise ValueError("rollover alert days cannot be negative")
        return self


DEFAULT_ROLLOVER_POLICY = RolloverPolicy()


def canonical_json_bytes(value: DomainModel) -> bytes:
    """Serialize a typed artifact using the Core's stable JSON conventions."""

    return json.dumps(
        value.model_dump(mode="json"),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def regulatory_anchor_artifact_digest(anchor: DomesticProjectionAnchor) -> str:
    """Digest all frozen artifact metadata, including acquisition timestamps."""

    return hashlib.sha256(canonical_json_bytes(anchor)).hexdigest()


def regulatory_candidate_artifact_digest(candidate: RegulatoryAnchorCandidate) -> str:
    """Digest the full frozen candidate, including its operational timestamp."""

    return hashlib.sha256(canonical_json_bytes(candidate)).hexdigest()


def regulatory_build_key(
    *,
    validity: DatePeriod,
    source_digests: tuple[str, ...],
    facts: tuple[RegulatoryFact, ...],
    parser_versions: tuple[str, ...],
    mapping_versions: tuple[str, ...],
    decision_ids: tuple[str, ...] = (),
) -> str:
    """Identify a semantic build, excluding fetched/created operational times."""

    if any(not _SHA256_PATTERN.fullmatch(digest) for digest in source_digests):
        raise ValueError("source digests must be canonical lowercase SHA-256 values")
    fact_ids = [fact.fact_id for fact in facts]
    if len(set(fact_ids)) != len(fact_ids):
        raise ValueError("regulatory build facts must have unique fact IDs")
    if not parser_versions or not mapping_versions:
        raise ValueError("regulatory build requires parser and mapping versions")
    if any(not value.strip() for value in (*parser_versions, *mapping_versions, *decision_ids)):
        raise ValueError("regulatory build versions and decision IDs cannot be empty")

    payload = {
        "schema_version": ROLLOVER_ANCHOR_SCHEMA_VERSION,
        "validity": validity.model_dump(mode="json"),
        "source_digests": sorted(set(source_digests)),
        "facts": [
            fact.model_dump(mode="json", exclude={"fetched_at"})
            for fact in sorted(facts, key=lambda item: item.fact_id)
        ],
        "parser_versions": sorted(set(parser_versions)),
        "mapping_versions": sorted(set(mapping_versions)),
        "decision_ids": sorted(set(decision_ids)),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "DEFAULT_ROLLOVER_POLICY",
    "ROLLOVER_ANCHOR_SCHEMA_VERSION",
    "CandidateValidationResult",
    "MappingDecision",
    "RegulatoryAnchorCandidate",
    "RegulatoryCandidateStatus",
    "RegulatoryEffectAssertion",
    "RegulatoryFact",
    "RegulatoryFactFamily",
    "RegulatoryRolloverReason",
    "RolloverPolicy",
    "canonical_json_bytes",
    "regulatory_anchor_artifact_digest",
    "regulatory_build_key",
    "regulatory_candidate_artifact_digest",
]

import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from italian_energy.arera.models import AreraCustomerSegment
from italian_energy.arera.projection import (
    DomesticProjectionAnchor,
    load_domestic_projection_anchor,
)
from italian_energy.arera.rollover_models import (
    ROLLOVER_ANCHOR_SCHEMA_VERSION,
    RegulatoryEffect,
    RegulatoryEffectAssertion,
    RegulatoryEffectKind,
    RegulatoryFact,
    RegulatoryFactFamily,
    RolloverPolicy,
    canonical_json_bytes,
    regulatory_anchor_artifact_digest,
    regulatory_build_key,
)
from italian_energy.domain.money import RateUnit
from italian_energy.domain.regulatory import BillingQuota
from italian_energy.domain.time import DatePeriod
from italian_energy.integration import dump_envelope, load_envelope
from italian_energy.integration.errors import CoreContractError
from italian_energy.integration.manifest import CoreSchemaId
from italian_energy.integration.projected import projection_anchor_digest


def _fact(fact_id: str = "fact-a") -> RegulatoryFact:
    return RegulatoryFact(
        fact_id=fact_id,
        family=RegulatoryFactFamily.CHARGE,
        component_code="network_total",
        segment=AreraCustomerSegment.RESIDENT,
        quota=BillingQuota.CONSUMPTION,
        value=Decimal("0.1234"),
        unit=RateUnit.EUR_PER_KWH,
        validity=DatePeriod(start=date(2026, 10, 1), end=date(2027, 1, 1)),
        source_id="source-a",
        source_url="https://www.arera.it/atto",
        source_sha256="a" * 64,
        act_id="123/2026/R/eel",
        document="fixture.xlsx",
        published_at=date(2026, 9, 20),
        fetched_at=datetime(2026, 9, 30, tzinfo=UTC),
        parser_id="synthetic-xlsx",
        parser_version="1.0.0",
        locator="Sheet1!B2",
        raw_value_token="12.34 cent/kWh",
        derivation="Decimal('12.34') / Decimal('100')",
    )


def _effect_assertion() -> RegulatoryEffectAssertion:
    return RegulatoryEffectAssertion(
        assertion_id="343-2026-asos-confirmation",
        component_code="ASOS",
        prior_effective_from=date(2026, 7, 1),
        validity=DatePeriod(start=date(2026, 10, 1), end=date(2027, 1, 1)),
        segments=(AreraCustomerSegment.RESIDENT,),
        quotas=(BillingQuota.CONSUMPTION,),
        source_id="arera_343_q4_act",
        source_url="https://www.arera.it/fileadmin/allegati/docs/26/343-2026-R-com.pdf",
        source_sha256="b" * 64,
        act_id="343/2026/R/com",
        document="343-2026-R-com.pdf",
        published_at=date(2026, 9, 29),
        fetched_at=datetime(2026, 9, 30, tzinfo=UTC),
        parser_id="arera-343-q4-confirmation",
        parser_version="1.0.0",
        locator="page 6, art. 1.1",
        raw_value_token="sono confermati",
    )


def test_regulatory_effect_assertion_preserves_non_numeric_legal_confirmation() -> None:
    assertion = _effect_assertion()

    assert assertion.component_code == "ASOS"
    assert assertion.raw_value_token == "sono confermati"
    assert assertion.validity == DatePeriod(start=date(2026, 10, 1), end=date(2027, 1, 1))


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"component_code": "UNKNOWN"}, "component is not supported"),
        ({"segments": ()}, "requires unique customer segments"),
        (
            {
                "segments": (
                    AreraCustomerSegment.RESIDENT,
                    AreraCustomerSegment.RESIDENT,
                )
            },
            "requires unique customer segments",
        ),
        ({"quotas": ()}, "requires unique billing quotas"),
        (
            {"quotas": (BillingQuota.CONSUMPTION, BillingQuota.CONSUMPTION)},
            "requires unique billing quotas",
        ),
        (
            {"prior_effective_from": date(2026, 10, 2)},
            "cannot predate the prior value's effective date",
        ),
        (
            {"published_at": date(2026, 10, 1)},
            "cannot be fetched before publication",
        ),
        (
            {"source_url": "http://www.arera.it/atto"},
            "official HTTPS source URL",
        ),
        (
            {"fetched_at": datetime(2026, 9, 30)},
            "fetched_at must be timezone-aware",
        ),
    ),
)
def test_regulatory_effect_assertion_rejects_invalid_scope_or_provenance(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        RegulatoryEffectAssertion.model_validate(
            {**_effect_assertion().model_dump(mode="python"), **changes}
        )


def test_rollover_anchor_v2_allows_preparation_before_validity_starts() -> None:
    current = load_domestic_projection_anchor()
    payload = current.model_dump(mode="python")
    payload.update(
        schema_version=ROLLOVER_ANCHOR_SCHEMA_VERSION,
        anchor_id="candidate-b",
        as_of=date(2026, 9, 30),
        validity=DatePeriod(start=date(2026, 10, 1), end=date(2027, 1, 1)),
    )
    prepared = DomesticProjectionAnchor.model_validate(payload)

    assert prepared.as_of < prepared.validity.start
    assert prepared.validity == DatePeriod(start=date(2026, 10, 1), end=date(2027, 1, 1))


def test_legacy_q3_anchor_digest_remains_stable() -> None:
    anchor = load_domestic_projection_anchor()

    assert projection_anchor_digest(anchor) == (
        "13d10642301133246d75f36813abbdf1abd1b0ad0d2f9ea95d7372c6df9dc9a9"
    )


def test_rollover_anchor_v2_rejects_source_published_after_snapshot() -> None:
    current = load_domestic_projection_anchor()
    payload = current.model_dump(mode="python")
    payload.update(
        schema_version=ROLLOVER_ANCHOR_SCHEMA_VERSION,
        anchor_id="candidate-b",
        as_of=date(2026, 9, 30),
        validity=DatePeriod(start=date(2026, 10, 1), end=date(2027, 1, 1)),
    )
    sources = list(payload["sources"])
    sources[0] = {**sources[0], "published_at": date(2026, 10, 2)}
    payload["sources"] = tuple(sources)

    with pytest.raises(ValidationError, match="published after snapshot"):
        DomesticProjectionAnchor.model_validate(payload)


@pytest.mark.parametrize(
    ("source_change", "message"),
    (
        ({"sha256": None}, "requires a digest"),
        ({"published_at": None}, "requires published_at"),
        ({"retrieved_at": datetime(2026, 9, 20)}, "retrieved_at must be aware"),
    ),
)
def test_rollover_anchor_v2_requires_complete_source_provenance(
    source_change: dict[str, object], message: str
) -> None:
    current = load_domestic_projection_anchor()
    payload = current.model_dump(mode="python")
    payload.update(
        schema_version=ROLLOVER_ANCHOR_SCHEMA_VERSION,
        anchor_id="candidate-b",
        as_of=date(2026, 9, 30),
        validity=DatePeriod(start=date(2026, 10, 1), end=date(2027, 1, 1)),
    )
    sources = list(payload["sources"])
    sources[0] = {**sources[0], **source_change}
    payload["sources"] = tuple(sources)

    with pytest.raises(ValidationError, match=message):
        DomesticProjectionAnchor.model_validate(payload)


def test_rollover_anchor_v2_snapshot_must_precede_validity_end() -> None:
    current = load_domestic_projection_anchor()
    payload = current.model_dump(mode="python")
    payload.update(
        schema_version=ROLLOVER_ANCHOR_SCHEMA_VERSION,
        anchor_id="candidate-b",
        as_of=date(2027, 1, 1),
        validity=DatePeriod(start=date(2026, 10, 1), end=date(2027, 1, 1)),
    )

    with pytest.raises(ValidationError, match="snapshot must precede validity end"):
        DomesticProjectionAnchor.model_validate(payload)


def test_regulatory_fact_rejects_float_and_requires_complete_provenance() -> None:
    with pytest.raises(TypeError, match="bool or float"):
        RegulatoryFact(**{**_fact().model_dump(), "value": 0.1234})

    with pytest.raises(ValidationError):
        RegulatoryFact(**{**_fact().model_dump(), "source_sha256": None})


def test_confirmation_effect_requires_an_explicit_prior_anchor_and_value() -> None:
    effect = RegulatoryEffect(
        kind=RegulatoryEffectKind.CONFIRM_VALUE,
        provision="dispositivo, comma 2",
        previous_anchor_id="anchor-q3",
        previous_value=Decimal("0.1234"),
        previous_fact_id="anchor-q3:network_total",
    )
    confirmed = RegulatoryFact.model_validate(
        {**_fact().model_dump(mode="python"), "effect": effect}
    )

    assert confirmed.effect.kind == RegulatoryEffectKind.CONFIRM_VALUE
    assert confirmed.effect.previous_anchor_id == "anchor-q3"

    with pytest.raises(ValidationError, match="explicit anchor link"):
        RegulatoryEffect(
            kind=RegulatoryEffectKind.CONFIRM_VALUE,
            provision="dispositivo, comma 2",
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"value": Decimal("-0.1")}, "cannot be negative"),
        ({"source_url": "http://www.arera.it/atto"}, "must use HTTPS"),
        ({"segment": None}, "requires component, segment, and quota"),
        ({"unit": RateUnit.PERCENT}, "cannot use a percentage unit"),
        ({"published_at": date(2026, 10, 1)}, "cannot be fetched before publication"),
        ({"fetched_at": datetime(2026, 9, 30)}, "must be timezone-aware"),
    ),
)
def test_charge_fact_rejects_invalid_value_or_provenance(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises((TypeError, ValidationError), match=message):
        RegulatoryFact.model_validate({**_fact().model_dump(mode="python"), **changes})


@pytest.mark.parametrize(
    ("family", "unit", "fields", "message"),
    (
        (
            RegulatoryFactFamily.VAT_RATE,
            RateUnit.EUR_PER_KWH,
            {},
            "VAT fact must use a percentage unit",
        ),
        (
            RegulatoryFactFamily.EXCISE_RATE,
            RateUnit.PERCENT,
            {},
            "excise fact cannot use a percentage unit",
        ),
        (
            RegulatoryFactFamily.VAT_RATE,
            RateUnit.PERCENT,
            {"segment": AreraCustomerSegment.RESIDENT},
            "cannot carry charge applicability fields",
        ),
    ),
)
def test_fiscal_fact_rejects_charge_fields_and_wrong_units(
    family: RegulatoryFactFamily,
    unit: RateUnit,
    fields: dict[str, object],
    message: str,
) -> None:
    payload = {
        **_fact().model_dump(mode="python"),
        "family": family,
        "component_code": None,
        "segment": None,
        "quota": None,
        "unit": unit,
        **fields,
    }
    if family == RegulatoryFactFamily.VAT_RATE:
        payload["value"] = Decimal("10")

    with pytest.raises(ValidationError, match=message):
        RegulatoryFact.model_validate(payload)


def test_build_key_is_canonical_and_excludes_operational_timestamps() -> None:
    period = DatePeriod(start=date(2026, 10, 1), end=date(2027, 1, 1))
    fact_a = _fact("a")
    fact_b = _fact("b")
    key_one = regulatory_build_key(
        validity=period,
        source_digests=("b" * 64, "a" * 64),
        facts=(fact_b, fact_a),
        parser_versions=("xlsx:1", "pdf:2"),
        mapping_versions=("network:v1",),
        decision_ids=("review-2", "review-1"),
    )
    key_two = regulatory_build_key(
        validity=period,
        source_digests=("a" * 64, "b" * 64),
        facts=(fact_a, fact_b),
        parser_versions=("pdf:2", "xlsx:1"),
        mapping_versions=("network:v1",),
        decision_ids=("review-1", "review-2"),
    )

    assert key_one == key_two
    assert len(key_one) == 64

    later_fetch = RegulatoryFact.model_validate(
        {
            **fact_a.model_dump(mode="python"),
            "fetched_at": datetime(2026, 9, 30, 23, 59, tzinfo=UTC),
        }
    )
    assert (
        regulatory_build_key(
            validity=period,
            source_digests=("b" * 64, "a" * 64),
            facts=(later_fetch, fact_b),
            parser_versions=("xlsx:1", "pdf:2"),
            mapping_versions=("network:v1",),
            decision_ids=("review-2", "review-1"),
        )
        == key_one
    )


def test_build_key_rejects_invalid_identity_inputs() -> None:
    period = DatePeriod(start=date(2026, 10, 1), end=date(2027, 1, 1))
    fact = _fact()
    with pytest.raises(ValueError, match="canonical lowercase SHA-256"):
        regulatory_build_key(
            validity=period,
            source_digests=("BAD",),
            facts=(fact,),
            parser_versions=("parser:1",),
            mapping_versions=("mapping:1",),
        )
    with pytest.raises(ValueError, match="unique fact IDs"):
        regulatory_build_key(
            validity=period,
            source_digests=("a" * 64,),
            facts=(fact, fact),
            parser_versions=("parser:1",),
            mapping_versions=("mapping:1",),
        )
    with pytest.raises(ValueError, match="requires parser and mapping"):
        regulatory_build_key(
            validity=period,
            source_digests=("a" * 64,),
            facts=(fact,),
            parser_versions=(),
            mapping_versions=("mapping:1",),
        )
    with pytest.raises(ValueError, match="cannot be empty"):
        regulatory_build_key(
            validity=period,
            source_digests=("a" * 64,),
            facts=(fact,),
            parser_versions=("parser:1",),
            mapping_versions=("mapping:1",),
            decision_ids=(" ",),
        )


def test_canonical_artifact_digest_is_stable_and_distinct_from_build_key() -> None:
    anchor = load_domestic_projection_anchor()
    serialized = canonical_json_bytes(anchor)

    assert serialized == canonical_json_bytes(anchor)
    assert regulatory_anchor_artifact_digest(anchor) == projection_anchor_digest(anchor)
    assert len(regulatory_anchor_artifact_digest(anchor)) == 64


def test_v2_anchor_envelope_round_trip_is_canonical_and_rejects_legacy_anchor() -> None:
    current = load_domestic_projection_anchor()
    payload = current.model_dump(mode="python")
    payload.update(
        schema_version=ROLLOVER_ANCHOR_SCHEMA_VERSION,
        anchor_id="candidate-b",
        as_of=date(2026, 9, 30),
        validity=DatePeriod(start=date(2026, 10, 1), end=date(2027, 1, 1)),
    )
    anchor = DomesticProjectionAnchor.model_validate(payload)
    envelope = dump_envelope(anchor)

    assert json.loads(envelope)["schema_id"] == CoreSchemaId.REGULATORY_ANCHOR_V2.value
    assert dump_envelope(load_envelope(envelope)) == envelope
    with pytest.raises(CoreContractError):
        dump_envelope(current)

    changed = json.loads(envelope)
    changed["payload"]["schema_version"] = "013-q3-anchor-v1"
    with pytest.raises(CoreContractError):
        load_envelope(json.dumps(changed))


def test_regulatory_fact_requires_locator_and_versioned_interpretation() -> None:
    payload = _fact().model_dump(mode="python")
    payload["locator"] = " "
    with pytest.raises(ValidationError):
        RegulatoryFact.model_validate(payload)


def test_rollover_policy_uses_validated_defaults_and_rejects_ambiguous_alerts() -> None:
    assert RolloverPolicy() == RolloverPolicy(
        prepare_lead_days=30,
        coverage_max_age_days=1,
        discovery_overlap_days=7,
        alert_days=(7, 1, 0),
    )
    with pytest.raises(ValidationError, match="unique and descending"):
        RolloverPolicy(alert_days=(1, 7, 0))

    payload = _fact().model_dump(mode="python")
    payload["parser_version"] = ""
    with pytest.raises(ValidationError):
        RegulatoryFact.model_validate(payload)

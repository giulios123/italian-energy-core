from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from italian_energy.arera import (
    AreraChargeRole,
    AreraChargeValue,
    AreraCompositionError,
    AreraCustomerSegment,
    AreraDomesticRuleSetComposer,
    AreraRegulatoryBundle,
    AreraSourceLocator,
    DomesticCompositionPolicy,
    DomesticFiscalPolicy,
)
from italian_energy.domain.money import RateUnit, UnitRate
from italian_energy.domain.provenance import Provenance
from italian_energy.domain.regulatory import (
    BillingCategory,
    BillingQuota,
    LinearRegulatoryRule,
    RegulatoryRuleSet,
    VerificationStatus,
)
from italian_energy.domain.time import DatePeriod

PERIOD = DatePeriod(start=datetime(2026, 5, 1).date(), end=datetime(2026, 7, 1).date())
FISCAL_SOURCE = Provenance(
    source="official-fiscal-test",
    source_identifier="adm-and-dpr",
    retrieved_at=datetime(2026, 9, 7, tzinfo=UTC),
    effective_period=PERIOD,
)


def verified_bundle() -> AreraRegulatoryBundle:
    charges: list[AreraChargeValue] = []
    for segment in AreraCustomerSegment:
        for month, (start, end) in enumerate(
            (
                (datetime(2026, 5, 1).date(), datetime(2026, 6, 1).date()),
                (datetime(2026, 6, 1).date(), datetime(2026, 7, 1).date()),
            ),
            start=5,
        ):
            period = DatePeriod(start=start, end=end)
            for component, category, amount in (
                ("network_total", "network", "0.10"),
                ("system_total", "system_charges", "0.20"),
            ):
                charges.append(
                    AreraChargeValue(
                        code=f"{segment.value}:{component}:{month}",
                        segment=segment,
                        component_code=component,
                        category=BillingCategory(category),
                        quota=BillingQuota.CONSUMPTION,
                        rate=UnitRate(amount=Decimal(amount), unit=RateUnit.EUR_PER_KWH),
                        validity=period,
                        role=AreraChargeRole.TOTAL,
                        source=AreraSourceLocator(
                            sheet="maggio 2026",
                            cell=f"I{month}",
                            label=component,
                        ),
                        status=VerificationStatus.VERIFIED,
                        provenance=(FISCAL_SOURCE,),
                    )
                )
    return AreraRegulatoryBundle(
        bundle_id="arera-bundle:test",
        schema_version="arera-v1",
        dataset_version="2026",
        validity=PERIOD,
        charges=tuple(charges),
        status=VerificationStatus.VERIFIED,
        provenance=(FISCAL_SOURCE,),
    )


def fiscal_policy() -> DomesticFiscalPolicy:
    return DomesticFiscalPolicy(
        schema_version="006-fiscal-v1",
        excise_rate=UnitRate(amount=Decimal("0.0227"), unit=RateUnit.EUR_PER_KWH),
        excise_provenance=(FISCAL_SOURCE,),
        vat_rate=UnitRate(amount=Decimal("10"), unit=RateUnit.PERCENT),
        vat_provenance=(FISCAL_SOURCE,),
        validity=PERIOD,
    )


def test_composer_selects_totals_excludes_cdisp_and_preserves_locator() -> None:
    ruleset = AreraDomesticRuleSetComposer().compose(
        verified_bundle(), AreraCustomerSegment.NON_RESIDENT, fiscal_policy()
    )

    assert isinstance(ruleset, RegulatoryRuleSet)
    profile = ruleset.profiles[0]
    source_rules = [
        rule
        for rule in profile.rules
        if isinstance(rule, LinearRegulatoryRule) and rule.description.startswith("ARERA")
    ]
    assert {rule.description.split()[1] for rule in source_rules} == {
        "network_total",
        "system_total",
    }
    assert all("CDISPD" not in rule.description for rule in profile.rules)
    for rule in source_rules:
        for item in rule.provenance:
            assert item.locator is not None
            assert item.locator.cell


def test_composer_id_is_independent_of_input_charge_order() -> None:
    bundle = verified_bundle()
    composer = AreraDomesticRuleSetComposer()
    first = composer.compose(bundle, AreraCustomerSegment.RESIDENT, fiscal_policy())
    reversed_bundle = bundle.model_copy(update={"charges": tuple(reversed(bundle.charges))})
    second = composer.compose(reversed_bundle, AreraCustomerSegment.RESIDENT, fiscal_policy())

    assert first.ruleset_id == second.ruleset_id


def test_composer_rejects_unverified_bundle_and_incomplete_segment() -> None:
    bundle = verified_bundle()
    unverified = bundle.model_copy(
        update={
            "status": VerificationStatus.UNVERIFIED,
            "charges": tuple(
                charge.model_copy(update={"status": VerificationStatus.UNVERIFIED})
                for charge in bundle.charges
            ),
        }
    )
    with pytest.raises(AreraCompositionError, match="not verified"):
        AreraDomesticRuleSetComposer().compose(
            unverified,
            AreraCustomerSegment.RESIDENT,
            fiscal_policy(),
        )

    only_resident = bundle.model_copy(
        update={
            "charges": tuple(
                charge
                for charge in bundle.charges
                if charge.segment == AreraCustomerSegment.RESIDENT
            )
        }
    )
    with pytest.raises(AreraCompositionError, match="segment is missing"):
        AreraDomesticRuleSetComposer().compose(
            only_resident, AreraCustomerSegment.NON_RESIDENT, fiscal_policy()
        )


def test_composer_rejects_unsupported_rate_and_non_total_source() -> None:
    bundle = verified_bundle()
    first = bundle.charges[0]
    unsupported = bundle.model_copy(
        update={
            "charges": (
                first.model_copy(
                    update={"rate": UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_MWH)}
                ),
                *bundle.charges[1:],
            )
        }
    )
    with pytest.raises(AreraCompositionError, match="unsupported ARERA rate"):
        AreraDomesticRuleSetComposer().compose(
            unsupported, AreraCustomerSegment.RESIDENT, fiscal_policy()
        )

    atomic = bundle.model_copy(
        update={
            "charges": (
                first.model_copy(update={"role": AreraChargeRole.ATOMIC}),
                *bundle.charges[1:],
            )
        }
    )
    with pytest.raises(AreraCompositionError, match="published totals"):
        AreraDomesticRuleSetComposer().compose(
            atomic, AreraCustomerSegment.RESIDENT, fiscal_policy()
        )


def test_fiscal_policy_rejects_incomplete_official_inputs() -> None:
    with pytest.raises(ValidationError, match="EUR/kWh"):
        DomesticFiscalPolicy(
            schema_version="006-fiscal-v1",
            excise_rate=UnitRate(amount=Decimal("0.0227"), unit=RateUnit.EUR_PER_YEAR),
            excise_provenance=(FISCAL_SOURCE,),
            vat_rate=UnitRate(amount=Decimal("10"), unit=RateUnit.PERCENT),
            vat_provenance=(FISCAL_SOURCE,),
            validity=PERIOD,
        )

    with pytest.raises(ValidationError, match="percent"):
        DomesticFiscalPolicy(
            schema_version="006-fiscal-v1",
            excise_rate=UnitRate(amount=Decimal("0.0227"), unit=RateUnit.EUR_PER_KWH),
            excise_provenance=(FISCAL_SOURCE,),
            vat_rate=UnitRate(amount=Decimal("10"), unit=RateUnit.EUR_PER_KWH),
            vat_provenance=(FISCAL_SOURCE,),
            validity=PERIOD,
        )

    with pytest.raises(ValidationError, match="provenance"):
        DomesticFiscalPolicy(
            schema_version="006-fiscal-v1",
            excise_rate=UnitRate(amount=Decimal("0.0227"), unit=RateUnit.EUR_PER_KWH),
            excise_provenance=(),
            vat_rate=UnitRate(amount=Decimal("10"), unit=RateUnit.PERCENT),
            vat_provenance=(FISCAL_SOURCE,),
            validity=PERIOD,
        )


def test_composition_policy_and_bundle_validation_fail_closed() -> None:
    with pytest.raises(ValidationError, match="executable source components"):
        DomesticCompositionPolicy(
            schema_version="006-v1", executable_components=("network_total", "network_total")
        )
    with pytest.raises(ValidationError, match="excluded source components"):
        DomesticCompositionPolicy(schema_version="006-v1", excluded_components=("CDISPD", "CDISPD"))
    with pytest.raises(ValidationError, match="cannot be executable"):
        DomesticCompositionPolicy(schema_version="006-v1", executable_components=("CDISPD",))

    composer = AreraDomesticRuleSetComposer()
    bundle = verified_bundle()
    with pytest.raises(AreraCompositionError, match="validity"):
        composer.compose(
            bundle,
            AreraCustomerSegment.RESIDENT,
            fiscal_policy().model_copy(
                update={
                    "validity": DatePeriod(
                        start=datetime(2026, 1, 1).date(), end=datetime(2026, 2, 1).date()
                    )
                }
            ),
        )
    with pytest.raises(AreraCompositionError, match="no executable"):
        composer.compose(
            bundle,
            AreraCustomerSegment.RESIDENT,
            fiscal_policy(),
            DomesticCompositionPolicy(schema_version="006-v1", executable_components=("missing",)),
        )

    no_provenance = bundle.model_copy(update={"provenance": ()})
    with pytest.raises(AreraCompositionError, match="provenance is missing"):
        composer.compose(no_provenance, AreraCustomerSegment.RESIDENT, fiscal_policy())

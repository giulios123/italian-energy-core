from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from italian_energy.arera.projection import (
    DomesticProjectionAnchor,
    ProjectionAnchorSourceReference,
    load_domestic_projection_anchor,
    load_domestic_projection_ruleset,
)
from italian_energy.billing.engine import BillingRequest
from italian_energy.billing.regulatory import BillingError, RegulatoryBillingEngine
from italian_energy.domain.consumption import ConsumptionBucket, ConsumptionProfile
from italian_energy.domain.costs import CostBreakdown, CostComponent, PricingResult
from italian_energy.domain.money import (
    EnergyQuantity,
    Money,
    Power,
    RateUnit,
    RoundingMode,
    RoundingPolicy,
    UnitRate,
)
from italian_energy.domain.offer import Contract
from italian_energy.domain.regulatory import (
    BillingCategory,
    SupplyClassification,
    VerificationStatus,
    VoltageLevel,
)
from italian_energy.domain.supply import SupplyPoint
from italian_energy.domain.tariff import BandPrice, FixedTariff
from italian_energy.domain.time import DatePeriod, Granularity, TimeInterval

ANCHOR_DAY = date(2026, 9, 27)
ANCHOR_MONTH = DatePeriod(start=date(2026, 9, 1), end=date(2026, 10, 1))
FUTURE_MONTH = DatePeriod(start=date(2026, 10, 1), end=date(2026, 11, 1))
ROME = ZoneInfo("Europe/Rome")


def _request(residential: bool) -> BillingRequest:
    contract = Contract(
        contract_id="projected-test",
        supply=SupplyPoint(
            supply_id="pod",
            market_zone="NORD",
            contracted_power=Power(kw=Decimal("3")),
            residential=residential,
        ),
        tariff=FixedTariff(
            tariff_id="fixed",
            validity=FUTURE_MONTH,
            prices=(
                BandPrice(
                    band="ALL",
                    rate=UnitRate(amount=Decimal("0.10"), unit=RateUnit.EUR_PER_KWH),
                ),
            ),
        ),
        validity=FUTURE_MONTH,
    )
    pricing = PricingResult(
        pricing_id="pricing",
        contract_id=contract.contract_id,
        period=FUTURE_MONTH,
        breakdown=CostBreakdown(
            components=(
                CostComponent(
                    code="energy:ALL",
                    description="Energy",
                    amount=Money(amount=Decimal("20.00")),
                    quantity=Decimal("200"),
                    unit_rate=UnitRate(amount=Decimal("0.10"), unit=RateUnit.EUR_PER_KWH),
                    period=FUTURE_MONTH,
                    formula="quantity_kwh * rate_eur_per_kwh",
                ),
            ),
            total=Money(amount=Decimal("20.00")),
        ),
    )
    return BillingRequest(
        contract=contract,
        consumption=ConsumptionProfile(
            profile_id="profile",
            buckets=(
                ConsumptionBucket(
                    interval=TimeInterval(
                        start=datetime(2026, 10, 1, tzinfo=ROME),
                        end=datetime(2026, 11, 1, tzinfo=ROME),
                    ),
                    energy=EnergyQuantity(kwh=Decimal("200")),
                    granularity=Granularity.MONTH,
                ),
            ),
        ),
        period=FUTURE_MONTH,
        pricing_result=pricing,
        classification=SupplyClassification(
            contract_type_code=(
                "domestic_bt_resident" if residential else "domestic_bt_non_resident"
            ),
            voltage_level=VoltageLevel.BT,
            usage_code="domestic",
            residential=residential,
        ),
        rule_set=load_domestic_projection_ruleset(residential=residential),
        rounding_policy=RoundingPolicy(scale=2, mode=RoundingMode.HALF_UP),
        regulatory_projection_as_of=ANCHOR_DAY,
    )


@pytest.mark.parametrize("residential", (True, False))
def test_projection_ruleset_is_verified_at_anchor_and_not_extended_to_future(
    residential: bool,
) -> None:
    rule_set = load_domestic_projection_ruleset(residential=residential)

    assert rule_set.status == VerificationStatus.VERIFIED
    assert rule_set.validity == ANCHOR_MONTH
    assert all(
        rule.validity == ANCHOR_MONTH for profile in rule_set.profiles for rule in profile.rules
    )
    sources = {item.source_identifier for item in rule_set.provenance}
    assert "575-2025-R-eel-TABELLE_TIT.xlsx" in sources
    assert "227-2026-R-com-TABELLE.xlsx" in sources
    assert "Aliquote nazionali - aggiornamento 18 settembre 2026" in sources


@pytest.mark.parametrize(
    ("residential", "expected_total"),
    ((True, "42.43"), (False, "54.88")),
)
def test_monthly_billing_reuses_verified_anchor_as_explicit_future_assumption(
    residential: bool, expected_total: str
) -> None:
    result = RegulatoryBillingEngine().evaluate(_request(residential))

    assert result.bill.breakdown.total == Money(amount=Decimal(expected_total))
    assert any(
        "regulatory_projection_as_of=2026-09-27" in assumption for assumption in result.assumptions
    )
    assert result.bill.period == FUTURE_MONTH


def test_projection_anchor_requires_all_versioned_sources_and_unique_ids() -> None:
    anchor = load_domestic_projection_anchor()
    payload = anchor.model_dump(mode="python")
    sources = list(payload["sources"])
    tua = next(item for item in sources if item["source_id"] == "tua_2025")
    tua["sha256"] = None
    with pytest.raises(ValidationError, match="requires a digest"):
        DomesticProjectionAnchor.model_validate(payload)

    payload = anchor.model_dump(mode="python")
    payload["sources"] = list(payload["sources"])
    payload["sources"][-1] = payload["sources"][0]
    with pytest.raises(ValidationError, match="must be unique"):
        DomesticProjectionAnchor.model_validate(payload)


def test_projection_anchor_rejects_extended_validity_and_missing_references() -> None:
    anchor = load_domestic_projection_anchor()
    payload = anchor.model_dump(mode="python")
    payload["validity"] = DatePeriod(start=date(2026, 7, 1), end=date(2026, 10, 1))
    with pytest.raises(ValidationError, match="cannot extend beyond its calendar month"):
        DomesticProjectionAnchor.model_validate(payload)

    payload = anchor.model_dump(mode="python")
    payload["charges"][0]["references"][0]["source_id"] = "missing-source"
    with pytest.raises(ValidationError, match="missing source"):
        DomesticProjectionAnchor.model_validate(payload)


def test_projection_anchor_charge_and_source_locator_validation() -> None:
    with pytest.raises(ValidationError, match="supplied together"):
        ProjectionAnchorSourceReference(source_id="source", section="table", sheet="Sheet1")

    anchor = load_domestic_projection_anchor()
    payload = anchor.model_dump(mode="python")
    payload["charges"][0]["component_code"] = "network_total_plus_atoms"
    with pytest.raises(ValidationError, match="only network/system totals"):
        DomesticProjectionAnchor.model_validate(payload)

    payload = anchor.model_dump(mode="python")
    payload["charges"] = []
    with pytest.raises(ValidationError, match="has no regulated charges"):
        DomesticProjectionAnchor.model_validate(payload)

    payload = anchor.model_dump(mode="python")
    payload["charges"][0]["category"] = BillingCategory.EXCISE
    with pytest.raises(ValidationError, match="category is incompatible"):
        DomesticProjectionAnchor.model_validate(payload)

    payload = anchor.model_dump(mode="python")
    payload["charges"][0]["references"] = ()
    with pytest.raises(ValidationError, match="requires official source references"):
        DomesticProjectionAnchor.model_validate(payload)

    payload = anchor.model_dump(mode="python")
    payload["charges"][0]["value"] = Decimal("-0.01")
    with pytest.raises(ValidationError, match="cannot be negative"):
        DomesticProjectionAnchor.model_validate(payload)


def test_projection_anchor_rejects_out_of_period_and_incomplete_fiscal_profiles() -> None:
    anchor = load_domestic_projection_anchor()
    payload = anchor.model_dump(mode="python")
    payload["as_of"] = date(2026, 8, 31)
    with pytest.raises(ValidationError, match="outside its verified validity"):
        DomesticProjectionAnchor.model_validate(payload)

    payload = anchor.model_dump(mode="python")
    payload["vat_rate_percent"] = Decimal("0")
    with pytest.raises(ValidationError, match="fiscal rates must be positive"):
        DomesticProjectionAnchor.model_validate(payload)

    payload = anchor.model_dump(mode="python")
    payload["vat_source_ids"] = ("vat_dpr_633",)
    with pytest.raises(ValidationError, match="both VAT table and rate sources"):
        DomesticProjectionAnchor.model_validate(payload)

    payload = anchor.model_dump(mode="python")
    payload["charges"] = tuple(
        item for item in payload["charges"] if item["segment"].value == "residenza_anagrafica"
    )
    with pytest.raises(ValidationError, match="incomplete for diversa_da_residenza_anagrafica"):
        DomesticProjectionAnchor.model_validate(payload)


def test_projection_anchor_vat_is_backed_by_current_table_and_article_16() -> None:
    anchor = load_domestic_projection_anchor()
    sources = {source.source_id: source for source in anchor.sources}
    policy = anchor.fiscal_policy()

    assert anchor.vat_rate_percent == Decimal("10")
    assert anchor.vat_source_ids == ("vat_dpr_633", "vat_dpr_633_art16")
    assert "!vig=2026-09-27" in sources["vat_dpr_633"].url
    assert "~art16!vig=2026-09-27" in sources["vat_dpr_633_art16"].url
    assert {item.locator.section for item in policy.vat_provenance if item.locator is not None} == {
        "DPR 633/1972 Tabella A parte III n. 103",
        "DPR 633/1972 art. 16: aliquota ridotta del 10% per la parte III",
    }
    assert all(item.sha256 for item in policy.vat_provenance)


def test_projection_cannot_use_an_anchor_outside_the_verified_snapshot() -> None:
    request = _request(residential=True).model_copy(
        update={"regulatory_projection_as_of": date(2026, 10, 1)}
    )

    with pytest.raises(BillingError, match="anchor is outside ruleset validity"):
        RegulatoryBillingEngine().evaluate(request)

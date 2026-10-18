from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256

import pytest
from pydantic import ValidationError

from italian_energy.domain.consumption import ConsumptionProfile
from italian_energy.domain.money import RoundingPolicy
from italian_energy.domain.offer import Contract
from italian_energy.domain.regulatory import VerificationStatus
from italian_energy.domain.supply import SupplyPoint
from italian_energy.domain.tariff import FixedTariff
from italian_energy.domain.time import DatePeriod
from italian_energy.portal_offers import models
from italian_energy.portal_offers.economic_validity import (
    EconomicValidityError,
    project_economic_validity,
)
from italian_energy.portal_offers.importer import PORTAL_PARSER_VERSION, _parse_market_free_xml
from italian_energy.portal_offers.normalizer import normalize_offers
from italian_energy.pricing import FixedPricingEngine, PricingRequest

AS_OF = date(2026, 10, 31)
ACTIVATION = date(2026, 11, 1)
HORIZON = DatePeriod(start=ACTIVATION, end=date(2027, 11, 1))
NAMESPACE = "http://www.acquirenteunico.it/schemas/SII_AU/OffertaRetail/01"


def _xml(
    *,
    energy_price: str = "0.12",
    energy_validity: str = "",
    energy_default_price: str | None = None,
    fixed_price: str = "84",
    fixed_validity: str = "",
    offer_duration: str = "24",
    data_inizio: str = "01/10/2026",
    data_fine: str = "31/10/2026",
    discount_xml: str = "",
    sconto_xml: str = "",
) -> bytes:
    energy_default = (
        f"<IntervalloPrezzi><FASCIA_COMPONENTE>01</FASCIA_COMPONENTE>"
        f"<PREZZO>{energy_default_price}</PREZZO><UNITA_MISURA>03</UNITA_MISURA>"
        "</IntervalloPrezzi>"
        if energy_default_price is not None
        else ""
    )
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<ListaOfferteMercatoLibero xmlns="{NAMESPACE}">
  <offerta>
    <IdentificativiOfferta><PIVA_UTENTE>12345678901</PIVA_UTENTE><COD_OFFERTA>TEST01</COD_OFFERTA></IdentificativiOfferta>
    <DettaglioOfferta>
      <TIPO_CLIENTE>01</TIPO_CLIENTE><TIPO_OFFERTA>01</TIPO_OFFERTA>
      <NOME_OFFERTA>Test annuale</NOME_OFFERTA><DURATA>{offer_duration}</DURATA>
      <ModalitaAttivazione><MODALITA>02</MODALITA></ModalitaAttivazione>
    </DettaglioOfferta>
    <ValiditaOfferta><DATA_INIZIO>{data_inizio}</DATA_INIZIO><DATA_FINE>{data_fine}</DATA_FINE></ValiditaOfferta>
    <MetodoPagamento><MODALITA_PAGAMENTO>01</MODALITA_PAGAMENTO></MetodoPagamento>
    <ComponenteImpresa>
      <NOME>Prezzo energia</NOME><DESCRIZIONE>energia</DESCRIZIONE><MACROAREA>04</MACROAREA>
      <IntervalloPrezzi><FASCIA_COMPONENTE>01</FASCIA_COMPONENTE><PREZZO>{energy_price}</PREZZO><UNITA_MISURA>03</UNITA_MISURA>{energy_validity}</IntervalloPrezzi>
      {energy_default}
    </ComponenteImpresa>
    <ComponenteImpresa>
      <NOME>Quota fissa</NOME>
      <DESCRIZIONE>commercializzazione</DESCRIZIONE><MACROAREA>01</MACROAREA>
      <IntervalloPrezzi><PREZZO>{fixed_price}</PREZZO><UNITA_MISURA>01</UNITA_MISURA>{fixed_validity}</IntervalloPrezzi>
    </ComponenteImpresa>
    {discount_xml}
    {sconto_xml}
  </offerta>
</ListaOfferteMercatoLibero>'''.encode()


def _snapshot(xml: bytes) -> tuple[models.PortalOffersSnapshot, models.PortalOfferRecord]:
    retrieved_at = datetime(2026, 10, 31, 12, tzinfo=UTC)
    files = []
    payloads = {
        models.PortalSourceRole.MARKET_FREE_OFFERS: xml,
        models.PortalSourceRole.MARKET_FREE_PARAMETERS: (
            b"nome_parametro;valore;descrizione\nfoo;1;fixture\n"
        ),
        models.PortalSourceRole.PLACET_OFFERS: b"placeholder",
        models.PortalSourceRole.PLACET_PARAMETERS: b"placeholder",
    }
    for role, content in payloads.items():
        filename = f"{role.value}.dat"
        url = f"https://www.ilportaleofferte.it/portaleOfferte/resources/opendata/csv/{filename}"
        files.append(
            models.PortalFileSnapshot(
                role=role,
                original_url=url,
                final_url=url,
                retrieved_at=retrieved_at,
                content_type="application/xml"
                if role == models.PortalSourceRole.MARKET_FREE_OFFERS
                else "text/csv",
                size=len(content),
                sha256=sha256(content).hexdigest(),
                dataset_date=date(2026, 10, 31),
                status=VerificationStatus.VERIFIED,
                content=content,
            )
        )
    snapshot = models.PortalOffersSnapshot(
        dataset_date=date(2026, 10, 31),
        files=tuple(files),
        snapshot_id=f"portal-snapshot:{'a' * 64}",
        status=VerificationStatus.VERIFIED,
        parser_version=PORTAL_PARSER_VERSION,
    )
    source = next(item for item in files if item.role == models.PortalSourceRole.MARKET_FREE_OFFERS)
    records = _parse_market_free_xml(source)
    assert len(records) == 1
    return snapshot, records[0]


def _eligibility() -> models.PortalEligibilityProfile:
    return models.PortalEligibilityProfile(
        territory=models.PortalTerritory(
            region_code="06", province_code="015", municipality_code="015213"
        ),
        domestic=True,
        residential=True,
        activation_method="02",
        payment_method="01",
    )


def _project(
    snapshot: models.PortalOffersSnapshot,
    record: models.PortalOfferRecord,
    *,
    as_of: date = AS_OF,
) -> models.PortalOffersImportResult:
    return normalize_offers(
        snapshot,
        (record,),
        _eligibility(),
        as_of,
        date.fromordinal(as_of.toordinal() + 1),
        activation_date=ACTIVATION,
        economic_period=HORIZON,
    )


def _discount_component(*validities: str) -> str:
    intervals = "".join(
        "<IntervalloPrezzi><PREZZO>24</PREZZO><UNITA_MISURA>01</UNITA_MISURA>"
        f"{validity}</IntervalloPrezzi>"
        for validity in validities
    )
    return (
        "<ComponenteImpresa><NOME>Sconto annuale</NOME>"
        "<DESCRIZIONE>Sconto commerciale annuale</DESCRIZIONE><MACROAREA>01</MACROAREA>"
        f"{intervals}</ComponenteImpresa>"
    )


def _economic_terms(result: models.PortalOffersImportResult) -> models.PortalEconomicTerms:
    assert len(result.normalized) == 1
    terms = result.normalized[0].economic_terms
    assert terms is not None
    return terms


def test_projected_quote_separates_subscription_expiry_from_activation_and_price_period() -> None:
    snapshot, record = _snapshot(
        _xml(energy_validity="<PeriodoValidita><DURATA>12</DURATA></PeriodoValidita>")
    )

    result = _project(snapshot, record)

    assert record.subscription_period == DatePeriod(start=date(2026, 10, 1), end=date(2026, 11, 1))
    assert record.duration_months == 24
    component_validity = record.components[0].price_validity
    assert component_validity is not None
    assert component_validity.kind == models.PortalPriceValidityKind.DURATION
    assert component_validity.duration_months == 12
    assert result.eligible_count == 1
    assert record.duration_months == 24
    normalized = result.normalized[0]
    terms = _economic_terms(result)
    assert normalized.offer.tariff.validity == HORIZON
    assert terms.activation_date == ACTIVATION
    assert terms.estimate_period == HORIZON
    assert terms.known_duration_months == 24
    assert terms.duration_scope == "seller_conditions"
    assert terms.extends_beyond_12_months is True
    assert terms.basis == "declared_economic_conditions"
    tariff = normalized.offer.tariff
    assert isinstance(tariff, FixedTariff)
    fixed_charge = tariff.fixed_charges[0]
    assert fixed_charge.validity is None
    assert fixed_charge.value.amount == Decimal("84")
    assert tariff.prices[0].rate.amount == Decimal("0.12")


def test_indeterminate_default_energy_price_is_annualizable_but_has_no_finite_guarantee() -> None:
    snapshot, record = _snapshot(_xml(offer_duration="-1"))

    result = _project(snapshot, record)

    assert result.eligible_count == 1
    terms = _economic_terms(result)
    assert record.economic_conditions_duration_raw == "-1"
    assert terms.basis == "published_default_prices"
    assert terms.known_duration_months is None
    assert terms.duration_scope is None
    assert terms.extends_beyond_12_months is None


def test_energy_price_validity_longer_than_year_is_scoped_to_energy_when_fixed_fee_is_default() -> (
    None
):
    snapshot, record = _snapshot(
        _xml(
            offer_duration="-1",
            energy_validity="<PeriodoValidita><DURATA>24</DURATA></PeriodoValidita>",
        )
    )

    result = _project(snapshot, record)

    assert result.eligible_count == 1
    terms = _economic_terms(result)
    assert terms.known_duration_months == 24
    assert terms.duration_scope == "energy_price"
    assert terms.extends_beyond_12_months is True


def test_all_explicit_seller_terms_use_the_shortest_proven_duration() -> None:
    snapshot, record = _snapshot(
        _xml(
            offer_duration="-1",
            energy_validity="<PeriodoValidita><DURATA>36</DURATA></PeriodoValidita>",
            fixed_validity="<PeriodoValidita><DURATA>24</DURATA></PeriodoValidita>",
        )
    )

    result = _project(snapshot, record)

    assert result.eligible_count == 1
    terms = _economic_terms(result)
    assert terms.known_duration_months == 24
    assert terms.duration_scope == "seller_conditions"
    assert terms.extends_beyond_12_months is True
    assert terms.basis == "explicit_component_validity"


@pytest.mark.parametrize(
    "validity",
    (
        "<PeriodoValidita><DURATA>0</DURATA></PeriodoValidita>",
        "<PeriodoValidita><DURATA>12</DURATA><VALIDO_FINO>12/2031</VALIDO_FINO></PeriodoValidita>",
        "<PeriodoValidita><VALIDO_FINO>13/2026</VALIDO_FINO></PeriodoValidita>",
    ),
)
def test_malformed_or_ambiguous_explicit_validity_is_not_a_default_price(validity: str) -> None:
    snapshot, record = _snapshot(_xml(energy_validity=validity))

    result = _project(snapshot, record)

    assert result.eligible_count == 0
    assert (
        result.exclusions[0].code
        == models.PortalOfferExclusionCode.ECONOMIC_PERIOD_NOT_REPRESENTABLE
    )


def test_short_explicit_energy_price_without_a_default_cannot_cover_annual_period() -> None:
    snapshot, record = _snapshot(
        _xml(energy_validity="<PeriodoValidita><DURATA>6</DURATA></PeriodoValidita>")
    )

    result = _project(snapshot, record)

    assert result.eligible_count == 0
    assert result.exclusions[0].code == models.PortalOfferExclusionCode.PERIOD_NOT_COVERED


def test_different_price_in_explicit_period_and_default_is_not_collapsed_to_one_rate() -> None:
    snapshot, record = _snapshot(
        _xml(
            offer_duration="-1",
            energy_price="0.15",
            energy_validity="<PeriodoValidita><DURATA>6</DURATA></PeriodoValidita>",
            energy_default_price="0.12",
        )
    )

    result = _project(snapshot, record)

    assert result.eligible_count == 0
    assert (
        result.exclusions[0].code
        == models.PortalOfferExclusionCode.ECONOMIC_PERIOD_NOT_REPRESENTABLE
    )


def test_valid_until_component_period_supports_explicit_energy_duration() -> None:
    snapshot, record = _snapshot(
        _xml(
            offer_duration="-1",
            energy_validity="<PeriodoValidita><VALIDO_FINO>12/2031</VALIDO_FINO></PeriodoValidita>",
        )
    )

    result = _project(snapshot, record)

    assert result.eligible_count == 1
    component_validity = record.components[0].price_validity
    assert component_validity is not None
    assert component_validity.kind == models.PortalPriceValidityKind.VALID_UNTIL
    terms = _economic_terms(result)
    assert terms.known_duration_months == 62
    assert terms.duration_scope == "energy_price"


def test_top_level_offer_duration_is_proven_economic_conditions_duration() -> None:
    snapshot, record = _snapshot(_xml(offer_duration="36"))

    assert record.duration_months == 36
    result = _project(snapshot, record)

    assert result.eligible_count == 1
    terms = _economic_terms(result)
    assert terms.known_duration_months == 36
    assert terms.duration_scope == "seller_conditions"
    assert terms.extends_beyond_12_months is True
    assert terms.basis == "declared_economic_conditions"


@pytest.mark.parametrize("duration_months", (1, 6, 11))
def test_declared_economic_conditions_shorter_than_horizon_are_excluded(
    duration_months: int,
) -> None:
    snapshot, record = _snapshot(_xml(offer_duration=str(duration_months)))

    result = _project(snapshot, record)

    assert result.eligible_count == 0
    assert result.exclusions[0].code == models.PortalOfferExclusionCode.PERIOD_NOT_COVERED


def test_declared_economic_conditions_cover_exact_twelve_month_horizon() -> None:
    snapshot, record = _snapshot(_xml(offer_duration="12"))

    result = _project(snapshot, record)

    assert result.eligible_count == 1
    terms = _economic_terms(result)
    assert terms.known_duration_months == 12
    assert terms.duration_scope == "seller_conditions"
    assert terms.extends_beyond_12_months is False


def test_long_declared_duration_does_not_hide_uncovered_short_energy_price() -> None:
    snapshot, record = _snapshot(
        _xml(
            offer_duration="36",
            energy_validity="<PeriodoValidita><DURATA>6</DURATA></PeriodoValidita>",
        )
    )

    result = _project(snapshot, record)

    assert result.eligible_count == 0
    assert result.exclusions[0].code == models.PortalOfferExclusionCode.PERIOD_NOT_COVERED


def test_legacy_record_without_economic_validity_marker_fails_closed_in_projection() -> None:
    snapshot, record = _snapshot(_xml())
    legacy = record.model_copy(update={"economic_validity_version": None})

    result = _project(snapshot, legacy)

    assert result.eligible_count == 0
    assert result.exclusions[0].code == models.PortalOfferExclusionCode.ECONOMIC_TERMS_UNVERIFIED


def test_previous_economic_validity_version_fails_closed_after_sconto_parser_change() -> None:
    snapshot, record = _snapshot(_xml())
    previous = record.model_copy(
        update={
            "economic_validity_version": "portale-regole-4.2-economic-validity-v1",
            "unmodeled_commercial_terms": (),
        }
    )

    result = _project(snapshot, previous)

    assert result.eligible_count == 0
    assert result.exclusions[0].code == models.PortalOfferExclusionCode.ECONOMIC_TERMS_UNVERIFIED


def test_subscription_end_is_inclusive_for_selection_but_offer_is_not_selectable_next_day() -> None:
    snapshot, record = _snapshot(_xml())

    on_last_day = _project(snapshot, record, as_of=date(2026, 10, 31))
    after_last_day = _project(snapshot, record, as_of=date(2026, 11, 1))

    assert on_last_day.eligible_count == 1
    assert after_last_day.eligible_count == 0
    assert after_last_day.exclusions[0].code == models.PortalOfferExclusionCode.NOT_CURRENT


@pytest.mark.parametrize(
    ("validity", "expected_period", "expected_discount"),
    (
        (
            "<PeriodoValidita><DURATA>6</DURATA></PeriodoValidita>",
            DatePeriod(start=date(2026, 11, 1), end=date(2027, 5, 1)),
            Decimal("-12.00"),
        ),
        (
            "<PeriodoValidita><MESE_VALIDITA>05/2027</MESE_VALIDITA></PeriodoValidita>",
            DatePeriod(start=date(2027, 5, 1), end=date(2027, 6, 1)),
            Decimal("-2.00"),
        ),
        (
            "<PeriodoValidita><MESE_VALIDITA>10/2027</MESE_VALIDITA></PeriodoValidita>",
            DatePeriod(start=date(2027, 10, 1), end=date(2027, 11, 1)),
            Decimal("-2.00"),
        ),
    ),
)
def test_one_contiguous_temporary_discount_is_prorated_without_extension(
    validity: str, expected_period: DatePeriod, expected_discount: Decimal
) -> None:
    snapshot, record = _snapshot(_xml(discount_xml=_discount_component(validity)))

    result = _project(snapshot, record)

    assert result.eligible_count == 1
    offer = result.normalized[0].offer
    tariff = offer.tariff
    assert isinstance(tariff, FixedTariff)
    assert len(tariff.fixed_charges) == 1
    assert tariff.fixed_charges[0].value.amount == Decimal("84")
    assert len(tariff.discounts) == 1
    assert tariff.discounts[0].value.amount == Decimal("-24")
    assert tariff.discounts[0].validity == expected_period

    contract = Contract(
        contract_id="temporary-discount-test",
        supply=SupplyPoint(supply_id="pod-test", market_zone="NORD"),
        tariff=tariff,
        validity=HORIZON,
        source_offer_id=offer.offer_id,
    )
    pricing = FixedPricingEngine().price(
        PricingRequest(
            contract=contract,
            consumption=ConsumptionProfile(profile_id="empty-profile"),
            period=HORIZON,
            rounding_policy=RoundingPolicy(scale=2),
        )
    )
    amounts = {item.code: item.amount.amount for item in pricing.breakdown.components}
    assert amounts["fixed:Quota fissa"] == Decimal("84.00")
    assert amounts["discount:Sconto annuale"] == expected_discount
    assert pricing.breakdown.total.amount == Decimal("84.00") + expected_discount


def test_multiple_separate_temporary_discount_windows_are_not_collapsed() -> None:
    snapshot, record = _snapshot(
        _xml(
            discount_xml=_discount_component(
                "<PeriodoValidita><DURATA>2</DURATA></PeriodoValidita>",
                "<PeriodoValidita><MESE_VALIDITA>10/2027</MESE_VALIDITA></PeriodoValidita>",
            )
        )
    )

    result = _project(snapshot, record)

    assert result.eligible_count == 0
    assert (
        result.exclusions[0].code
        == models.PortalOfferExclusionCode.ECONOMIC_PERIOD_NOT_REPRESENTABLE
    )


@pytest.mark.parametrize(
    ("data_inizio", "as_of", "eligible"),
    (
        ("30/10/2026", date(2026, 10, 31), True),
        ("31/10/2026", date(2026, 10, 31), True),
        ("31/10/2026", date(2026, 10, 30), False),
    ),
)
def test_data_inizio_is_checked_at_as_of_day(data_inizio: str, as_of: date, eligible: bool) -> None:
    snapshot, record = _snapshot(_xml(data_inizio=data_inizio))

    result = _project(snapshot, record, as_of=as_of)

    assert (result.eligible_count == 1) is eligible
    if not eligible:
        assert result.exclusions[0].code == models.PortalOfferExclusionCode.NOT_CURRENT


@pytest.mark.parametrize(
    "sconto_xml",
    (
        "<Sconto><TIPO>ANNUALE</TIPO><IMPORTO>24</IMPORTO><DURATA>12</DURATA></Sconto>",
        "<Sconto><TIPO>UNA_TANTUM</TIPO><IMPORTO>24</IMPORTO><DURATA>1</DURATA></Sconto>",
    ),
)
def test_structured_sconto_is_preserved_but_not_inferred_as_a_price_or_duration(
    sconto_xml: str,
) -> None:
    snapshot, record = _snapshot(_xml(offer_duration="-1", sconto_xml=sconto_xml))

    assert record.duration_months is None
    assert record.economic_conditions_duration_raw == "-1"
    assert len(record.components) == 2
    assert len(record.unmodeled_commercial_terms) == 1
    raw_values = {value for _, value in record.raw_fields}
    assert "ANNUALE" in raw_values or "UNA_TANTUM" in raw_values
    assert any(
        key.startswith("DURATA:") and value in {"1", "12"} for key, value in record.raw_fields
    )
    source = record.unmodeled_commercial_terms[0]
    assert source.locator is not None
    assert source.locator.section == "offer:TEST01/Sconto:1"

    result = _project(snapshot, record)

    assert result.eligible_count == 0
    exclusion = result.exclusions[0]
    assert exclusion.code == models.PortalOfferExclusionCode.UNSUPPORTED_COMMERCIAL_COMPONENT
    assert "Sconto" in exclusion.detail
    assert exclusion.locator == source.locator

    historical = normalize_offers(
        snapshot,
        (record,),
        _eligibility(),
        AS_OF,
        date.fromordinal(AS_OF.toordinal() + 1),
    )
    assert historical.eligible_count == 1


@pytest.mark.parametrize(
    "values",
    (
        {"kind": "duration"},
        {"kind": "duration", "duration_months": 6, "month": date(2026, 11, 1)},
        {"kind": "valid_until"},
        {"kind": "month", "month": date(2027, 5, 2)},
        {"kind": "valid_until", "month": date(2027, 5, 1), "duration_months": 6},
        {"kind": "default", "duration_months": 6},
        {"kind": "unsupported", "month": date(2027, 5, 1)},
    ),
)
def test_component_price_validity_rejects_missing_or_conflicting_bounds(
    values: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        models.PortalComponentPriceValidity.model_validate(values)


def test_economic_terms_require_estimate_to_start_on_activation_date() -> None:
    with pytest.raises(ValidationError, match="must start on its activation date"):
        models.PortalEconomicTerms(
            activation_date=ACTIVATION,
            estimate_period=DatePeriod(start=date(2026, 11, 2), end=date(2027, 11, 2)),
            basis=models.PortalEconomicTermsBasis.PUBLISHED_DEFAULT_PRICES,
        )


def test_economic_terms_cannot_claim_extension_without_known_duration() -> None:
    with pytest.raises(ValidationError, match="requires a known duration"):
        models.PortalEconomicTerms(
            activation_date=ACTIVATION,
            estimate_period=HORIZON,
            extends_beyond_12_months=True,
            basis=models.PortalEconomicTermsBasis.PUBLISHED_DEFAULT_PRICES,
        )


def test_economic_terms_extension_flag_must_match_proven_duration() -> None:
    _, record = _snapshot(_xml())
    with pytest.raises(ValidationError, match="must match the proven duration"):
        models.PortalEconomicTerms(
            activation_date=ACTIVATION,
            estimate_period=HORIZON,
            known_duration_months=24,
            duration_scope=models.PortalEconomicDurationScope.SELLER_CONDITIONS,
            extends_beyond_12_months=False,
            basis=models.PortalEconomicTermsBasis.DECLARED_ECONOMIC_CONDITIONS,
            provenance=record.source_provenance,
        )


@pytest.mark.parametrize("missing", ("scope", "provenance"))
def test_economic_terms_require_scope_and_provenance_for_known_duration(missing: str) -> None:
    _, record = _snapshot(_xml())
    scope = None if missing == "scope" else models.PortalEconomicDurationScope.SELLER_CONDITIONS
    provenance = () if missing == "provenance" else record.source_provenance
    with pytest.raises(ValidationError, match="requires a scope and source provenance"):
        models.PortalEconomicTerms(
            activation_date=ACTIVATION,
            estimate_period=HORIZON,
            known_duration_months=24,
            duration_scope=scope,
            extends_beyond_12_months=True,
            basis=models.PortalEconomicTermsBasis.DECLARED_ECONOMIC_CONDITIONS,
            provenance=provenance,
        )


def test_normalize_requires_activation_and_economic_period_together() -> None:
    snapshot, record = _snapshot(_xml())
    eligibility = _eligibility()
    next_day = date.fromordinal(AS_OF.toordinal() + 1)

    with pytest.raises(ValueError, match="must be supplied together"):
        normalize_offers(
            snapshot,
            (record,),
            eligibility,
            AS_OF,
            next_day,
            activation_date=ACTIVATION,
        )
    with pytest.raises(ValueError, match="must be supplied together"):
        normalize_offers(
            snapshot,
            (record,),
            eligibility,
            AS_OF,
            next_day,
            economic_period=HORIZON,
        )


def test_normalize_requires_activation_to_match_economic_period_start() -> None:
    snapshot, record = _snapshot(_xml())
    with pytest.raises(ValueError, match=r"activation_date must equal economic_period\.start"):
        normalize_offers(
            snapshot,
            (record,),
            _eligibility(),
            AS_OF,
            date.fromordinal(AS_OF.toordinal() + 1),
            activation_date=date(2026, 11, 2),
            economic_period=HORIZON,
        )


def test_project_economic_validity_rejects_missing_offer_provenance() -> None:
    _, record = _snapshot(_xml())
    source_less = record.model_copy(update={"source_provenance": ()})

    with pytest.raises(EconomicValidityError) as error:
        project_economic_validity(source_less, ACTIVATION, HORIZON)

    assert error.value.code == models.PortalOfferExclusionCode.MISSING_PROVENANCE

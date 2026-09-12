"""Explicit ARERA bundle to verified billing-ruleset composition."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from decimal import Decimal
from enum import StrEnum

from pydantic import Field, model_validator

from italian_energy.arera.models import (
    AreraChargeRole,
    AreraChargeValue,
    AreraCustomerSegment,
    AreraRegulatoryBundle,
)
from italian_energy.domain.base import DomainModel
from italian_energy.domain.money import RateUnit, UnitRate
from italian_energy.domain.provenance import Provenance, ProvenanceLocator
from italian_energy.domain.regulatory import (
    AddQuantity,
    BillingBasis,
    BillingCategory,
    BillingMeasureUnit,
    BillingQuota,
    LinearRegulatoryRule,
    MaxQuantity,
    MeasureReference,
    MinQuantity,
    MultiplyQuantity,
    PercentageRegulatoryRule,
    ProrationPolicy,
    QuantityConstant,
    QuantityExpression,
    RegulatoryParameter,
    RegulatoryProfile,
    RegulatoryRuleSet,
    SubtractQuantity,
    ThresholdRegulatoryRule,
    VerificationStatus,
    VoltageLevel,
)
from italian_energy.domain.time import DatePeriod


class AreraCompositionError(ValueError):
    """Raised when a source bundle cannot be composed safely."""


class DomesticProfileKind(StrEnum):
    RESIDENT = "domestic_bt_resident"
    NON_RESIDENT = "domestic_bt_non_resident"


class DomesticFiscalPolicy(DomainModel):
    """Verified fiscal inputs supplied by an official-source adapter."""

    schema_version: str = Field(min_length=1)
    excise_rate: UnitRate
    excise_provenance: tuple[Provenance, ...]
    vat_rate: UnitRate
    vat_provenance: tuple[Provenance, ...]
    validity: DatePeriod

    @model_validator(mode="after")
    def validate_policy(self) -> DomesticFiscalPolicy:
        if self.excise_rate.unit != RateUnit.EUR_PER_KWH:
            raise ValueError("domestic excise rate must be EUR/kWh")
        if self.vat_rate.unit != RateUnit.PERCENT:
            raise ValueError("domestic VAT rate must be percent")
        if not self.excise_provenance or not self.vat_provenance:
            raise ValueError("fiscal policy requires provenance")
        if self.validity.start >= self.validity.end:
            raise ValueError("fiscal policy validity must be non-empty")
        return self


class DomesticCompositionPolicy(DomainModel):
    """Versioned semantic mapping from source rows to billing components."""

    schema_version: str = Field(min_length=1)
    executable_components: tuple[str, ...] = ("network_total", "system_total")
    excluded_components: tuple[str, ...] = ("CDISPD",)

    @model_validator(mode="after")
    def validate_mapping(self) -> DomesticCompositionPolicy:
        if len(self.executable_components) != len(set(self.executable_components)):
            raise ValueError("executable source components must be unique")
        if len(self.excluded_components) != len(set(self.excluded_components)):
            raise ValueError("excluded source components must be unique")
        if set(self.executable_components) & set(self.excluded_components):
            raise ValueError("source component cannot be executable and excluded")
        return self


class AreraDomesticRuleSetComposer:
    """Compose one explicit, profile-specific ruleset from a verified bundle."""

    def compose(
        self,
        bundle: AreraRegulatoryBundle,
        segment: AreraCustomerSegment,
        fiscal_policy: DomesticFiscalPolicy,
        composition_policy: DomesticCompositionPolicy | None = None,
    ) -> RegulatoryRuleSet:
        policy = composition_policy or DomesticCompositionPolicy(schema_version="006-v1")
        self._validate_bundle(bundle, segment, fiscal_policy)
        charges = tuple(
            sorted(
                (
                    charge
                    for charge in bundle.charges
                    if charge.segment == segment
                    and charge.component_code in policy.executable_components
                ),
                key=lambda charge: (charge.validity.start, charge.component_code, charge.quota),
            )
        )
        if not charges:
            raise AreraCompositionError("bundle contains no executable charges for segment")
        self._validate_complete_months(charges, bundle, policy)
        source_rules = tuple(self._source_rule(charge) for charge in charges)
        fiscal_parameters = self._fiscal_parameters(bundle, fiscal_policy)
        profiles = self._profiles(
            segment,
            source_rules,
            fiscal_policy,
            bundle,
        )
        provenance = _merge_provenance(
            bundle.provenance,
            fiscal_policy.excise_provenance,
            fiscal_policy.vat_provenance,
            _bundle_evidence_provenance(bundle, segment),
            (_composition_provenance(bundle, policy),),
        )
        base = RegulatoryRuleSet(
            ruleset_id="pending",
            schema_version="006-domestic-bt-ruleset-v1",
            validity=bundle.validity,
            parameters=fiscal_parameters,
            profiles=profiles,
            status=VerificationStatus.VERIFIED,
            provenance=provenance,
        )
        digest = hashlib.sha256(
            json.dumps(
                _canonical_ruleset_payload(base),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        suffix = (
            DomesticProfileKind.RESIDENT.value
            if segment == AreraCustomerSegment.RESIDENT
            else DomesticProfileKind.NON_RESIDENT.value
        )
        return base.model_copy(update={"ruleset_id": f"arera-{suffix}-2026:{digest}"})

    @staticmethod
    def _validate_bundle(
        bundle: AreraRegulatoryBundle,
        segment: AreraCustomerSegment,
        fiscal_policy: DomesticFiscalPolicy,
    ) -> None:
        if bundle.status != VerificationStatus.VERIFIED:
            raise AreraCompositionError("ARERA bundle is not verified")
        if not bundle.provenance:
            raise AreraCompositionError("ARERA bundle provenance is missing")
        if fiscal_policy.validity != bundle.validity:
            raise AreraCompositionError("fiscal policy validity must equal bundle validity")
        if not any(charge.segment == segment for charge in bundle.charges):
            raise AreraCompositionError("requested ARERA segment is missing")
        if any(
            charge.status != VerificationStatus.VERIFIED
            or not charge.provenance
            or not charge.source.sheet
            or not charge.source.cell
            for charge in bundle.charges
            if charge.segment == segment
        ):
            raise AreraCompositionError("segment contains an unverified or unlocated charge")

    @staticmethod
    def _validate_complete_months(
        charges: tuple[AreraChargeValue, ...],
        bundle: AreraRegulatoryBundle,
        policy: DomesticCompositionPolicy,
    ) -> None:
        expected = set(policy.executable_components)
        by_period: dict[DatePeriod, set[str]] = {}
        seen_rows: set[tuple[DatePeriod, str, BillingQuota]] = set()
        for charge in charges:
            by_period.setdefault(charge.validity, set()).add(charge.component_code)
            row_key = (charge.validity, charge.component_code, charge.quota)
            if row_key in seen_rows:
                raise AreraCompositionError("a month contains duplicate executable source totals")
            seen_rows.add(row_key)
        if any(components != expected for components in by_period.values()):
            raise AreraCompositionError("a month is missing an executable source total")
        if any(charge.role != AreraChargeRole.TOTAL for charge in charges):
            raise AreraCompositionError("executable source components must be published totals")
        expected_periods: list[DatePeriod] = []
        cursor = bundle.validity.start.replace(day=1)
        while cursor < bundle.validity.end:
            next_month = (
                cursor.replace(year=cursor.year + 1, month=1)
                if cursor.month == 12
                else cursor.replace(month=cursor.month + 1)
            )
            expected_periods.append(DatePeriod(start=cursor, end=next_month))
            cursor = next_month
        if tuple(sorted(by_period, key=lambda period: period.start)) != tuple(expected_periods):
            raise AreraCompositionError("source months are not contiguous across bundle validity")

    @staticmethod
    def _source_rule(charge: AreraChargeValue) -> LinearRegulatoryRule:
        provenance = _charge_provenance(charge)
        basis_by_unit = {
            RateUnit.EUR_PER_KWH: BillingBasis.PER_KWH,
            RateUnit.EUR_PER_YEAR: BillingBasis.PER_YEAR,
            RateUnit.EUR_PER_KW_YEAR: BillingBasis.PER_KW_YEAR,
        }
        try:
            basis = basis_by_unit[charge.rate.unit]
        except KeyError as exc:
            raise AreraCompositionError(
                f"unsupported ARERA rate unit {charge.rate.unit.value}"
            ) from exc
        proration = (
            ProrationPolicy.MONTHLY_TWELFTHS_PARTIAL_365
            if basis in (BillingBasis.PER_YEAR, BillingBasis.PER_KW_YEAR)
            else None
        )
        return LinearRegulatoryRule(
            code=charge.code,
            description=f"ARERA {charge.component_code} {charge.quota.value}",
            category=charge.category,
            quota=charge.quota,
            validity=charge.validity,
            basis=basis,
            value=charge.rate,
            proration=proration,
            status=VerificationStatus.VERIFIED,
            provenance=provenance,
            conditions=("source_role=total", "atomic_sources_retained_in_provenance"),
        )

    @staticmethod
    def _fiscal_parameters(
        bundle: AreraRegulatoryBundle,
        fiscal_policy: DomesticFiscalPolicy,
    ) -> tuple[RegulatoryParameter, ...]:
        return (
            RegulatoryParameter(
                code="domestic_excise_rate",
                value=fiscal_policy.excise_rate.amount,
                unit=fiscal_policy.excise_rate.unit.value,
                validity=bundle.validity,
                status=VerificationStatus.VERIFIED,
                provenance=fiscal_policy.excise_provenance,
            ),
            RegulatoryParameter(
                code="domestic_vat_rate",
                value=fiscal_policy.vat_rate.amount,
                unit=fiscal_policy.vat_rate.unit.value,
                validity=bundle.validity,
                status=VerificationStatus.VERIFIED,
                provenance=fiscal_policy.vat_provenance,
            ),
        )

    @classmethod
    def _profiles(
        cls,
        segment: AreraCustomerSegment,
        source_rules: tuple[LinearRegulatoryRule, ...],
        fiscal_policy: DomesticFiscalPolicy,
        bundle: AreraRegulatoryBundle,
    ) -> tuple[RegulatoryProfile, ...]:
        excise_rules, vat_rules = cls._fiscal_rules(segment, fiscal_policy, bundle)
        if segment == AreraCustomerSegment.NON_RESIDENT:
            return (
                RegulatoryProfile(
                    profile_code=DomesticProfileKind.NON_RESIDENT.value,
                    contract_type_code=DomesticProfileKind.NON_RESIDENT.value,
                    voltage_level=VoltageLevel.BT,
                    usage_code="domestic",
                    residential=False,
                    rules=source_rules + excise_rules + vat_rules,
                ),
            )
        profiles: list[RegulatoryProfile] = []
        for suffix, minimum, minimum_inclusive, maximum, maximum_inclusive, expression in (
            (
                "le_1_5",
                None,
                True,
                Decimal("1.5"),
                True,
                _resident_excise(Decimal("150"), Decimal("150")),
            ),
            (
                "gt_1_5_le_3",
                Decimal("1.5"),
                False,
                Decimal("3"),
                True,
                _resident_excise(Decimal("150"), Decimal("220")),
            ),
            (
                "gt_3",
                Decimal("3"),
                False,
                None,
                True,
                MeasureReference(code="consumption_kwh", unit=BillingMeasureUnit.KWH),
            ),
        ):
            excise = tuple(
                rule.model_copy(update={"quantity": expression}) for rule in excise_rules
            )
            profiles.append(
                RegulatoryProfile(
                    profile_code=f"{DomesticProfileKind.RESIDENT.value}:{suffix}",
                    contract_type_code=DomesticProfileKind.RESIDENT.value,
                    voltage_level=VoltageLevel.BT,
                    usage_code="domestic",
                    residential=True,
                    min_contracted_power_kw=minimum,
                    min_contracted_power_inclusive=minimum_inclusive,
                    max_contracted_power_kw=maximum,
                    max_contracted_power_inclusive=maximum_inclusive,
                    rules=source_rules + excise + vat_rules,
                )
            )
        return tuple(profiles)

    @staticmethod
    def _fiscal_rules(
        segment: AreraCustomerSegment,
        fiscal_policy: DomesticFiscalPolicy,
        bundle: AreraRegulatoryBundle,
    ) -> tuple[
        tuple[ThresholdRegulatoryRule | LinearRegulatoryRule, ...],
        tuple[PercentageRegulatoryRule, ...],
    ]:
        periods = sorted(
            {charge.validity for charge in bundle.charges if charge.segment == segment},
            key=lambda period: period.start,
        )
        excise_rules: list[ThresholdRegulatoryRule | LinearRegulatoryRule] = []
        vat_rules: list[PercentageRegulatoryRule] = []
        for period in periods:
            excise_provenance = tuple(
                item.model_copy(update={"effective_period": period})
                for item in fiscal_policy.excise_provenance
            )
            if segment == AreraCustomerSegment.NON_RESIDENT:
                excise_rules.append(
                    LinearRegulatoryRule(
                        code=f"excise:{period.start:%Y-%m}",
                        description="Domestic non-resident electricity excise",
                        category=BillingCategory.EXCISE,
                        quota=BillingQuota.TAX,
                        validity=period,
                        basis=BillingBasis.PER_KWH,
                        value=fiscal_policy.excise_rate,
                        parameter_codes=("domestic_excise_rate",),
                        status=VerificationStatus.VERIFIED,
                        provenance=excise_provenance,
                    )
                )
            else:
                excise_rules.append(
                    ThresholdRegulatoryRule(
                        code=f"excise:{period.start:%Y-%m}",
                        description="Domestic resident electricity excise after exemption recovery",
                        category=BillingCategory.EXCISE,
                        quota=BillingQuota.TAX,
                        validity=period,
                        quantity=MeasureReference(
                            code="consumption_kwh", unit=BillingMeasureUnit.KWH
                        ),
                        rate=fiscal_policy.excise_rate,
                        parameter_codes=("domestic_excise_rate",),
                        status=VerificationStatus.VERIFIED,
                        provenance=excise_provenance,
                    )
                )
            vat_rules.append(
                PercentageRegulatoryRule(
                    code=f"vat:{period.start:%Y-%m}",
                    description="Domestic electricity VAT",
                    category=BillingCategory.VAT,
                    quota=BillingQuota.TAX,
                    validity=period,
                    rate=fiscal_policy.vat_rate,
                    base_categories=(
                        BillingCategory.SALES,
                        BillingCategory.NETWORK,
                        BillingCategory.SYSTEM_CHARGES,
                        BillingCategory.EXCISE,
                    ),
                    parameter_codes=("domestic_vat_rate",),
                    status=VerificationStatus.VERIFIED,
                    provenance=tuple(
                        item.model_copy(update={"effective_period": period})
                        for item in fiscal_policy.vat_provenance
                    ),
                )
            )
        return tuple(excise_rules), tuple(vat_rules)


def _resident_excise(start: Decimal, recovery: Decimal) -> QuantityExpression:
    consumption = MeasureReference(code="consumption_kwh", unit=BillingMeasureUnit.KWH)
    first = MaxQuantity(
        left=SubtractQuantity(left=consumption, right=QuantityConstant(value=start)),
        right=QuantityConstant(value=Decimal(0)),
    )
    second = MaxQuantity(
        left=SubtractQuantity(left=consumption, right=QuantityConstant(value=recovery)),
        right=QuantityConstant(value=Decimal(0)),
    )
    return (
        MinQuantity(
            left=consumption,
            right=first if start == recovery else AddQuantity(left=first, right=second),
        )
        if start != recovery
        else MinQuantity(
            left=consumption,
            right=MultiplyQuantity(quantity=first, scalar=Decimal(2)),
        )
    )


def _charge_provenance(charge: AreraChargeValue) -> tuple[Provenance, ...]:
    locator = ProvenanceLocator(
        document=charge.component_code,
        sheet=charge.source.sheet,
        cell=charge.source.cell,
        section=charge.source.label,
    )
    return tuple(item.model_copy(update={"locator": locator}) for item in charge.provenance)


def _composition_provenance(
    bundle: AreraRegulatoryBundle,
    policy: DomesticCompositionPolicy,
) -> Provenance:
    canonical = json.dumps(
        policy.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return Provenance(
        source="italian-energy-composer",
        source_identifier=f"spec-006-composition:{policy.schema_version}",
        retrieved_at=bundle.provenance[0].retrieved_at,
        effective_period=bundle.validity,
        dataset_version=policy.schema_version,
        sha256=hashlib.sha256(canonical).hexdigest(),
    )


def _bundle_evidence_provenance(
    bundle: AreraRegulatoryBundle,
    segment: AreraCustomerSegment,
) -> tuple[Provenance, ...]:
    evidence: list[Provenance] = []
    charges = sorted(
        (charge for charge in bundle.charges if charge.segment == segment),
        key=lambda charge: (charge.validity.start, charge.component_code, charge.quota),
    )
    for charge in charges:
        for item in _charge_provenance(charge):
            if item not in evidence:
                evidence.append(item)
    return tuple(evidence)


def _canonical_ruleset_payload(ruleset: RegulatoryRuleSet) -> dict[str, object]:
    """Remove acquisition timestamps so IDs represent source/policy content."""

    payload = ruleset.model_dump(mode="json", exclude={"ruleset_id"})

    def strip_timestamps(value: object) -> object:
        if isinstance(value, dict):
            return {
                key: strip_timestamps(item) for key, item in value.items() if key != "retrieved_at"
            }
        if isinstance(value, list):
            return [strip_timestamps(item) for item in value]
        return value

    result = strip_timestamps(payload)
    if not isinstance(result, dict):  # pragma: no cover - model_dump is a mapping
        raise TypeError("ruleset canonical payload must be a mapping")
    return result


def _merge_provenance(*groups: Iterable[Provenance]) -> tuple[Provenance, ...]:
    result: list[Provenance] = []
    for group in groups:
        for item in group:
            if item not in result:
                result.append(item)
    return tuple(
        sorted(
            result,
            key=lambda item: json.dumps(
                item.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ),
        )
    )

"""Stable errors exposed by the Core-Platform integration contract."""

from enum import StrEnum


class CoreErrorCode(StrEnum):
    """Machine-readable integration failure categories."""

    INVALID_ENVELOPE = "invalid_envelope"
    UNSUPPORTED_CONTRACT_VERSION = "unsupported_contract_version"
    UNSUPPORTED_SCHEMA = "unsupported_schema"
    INVALID_PAYLOAD = "invalid_payload"
    UNSUPPORTED_SCENARIO = "unsupported_scenario"
    UNSUPPORTED_HORIZON = "unsupported_horizon"
    COVERAGE_UNAVAILABLE = "coverage_unavailable"
    COVERAGE_EXPIRED = "regulatory_coverage_expired"
    REGULATORY_SOURCE_CHANGED = "regulatory_source_changed"
    APPLICABLE_REGULATORY_ACT = "applicable_regulatory_act"
    REGULATORY_COVERAGE_UNCONFIRMED = "regulatory_coverage_unconfirmed"
    SOURCE_ACQUISITION_FAILED = "source_acquisition_failed"
    SOURCE_VALIDATION_FAILED = "source_validation_failed"
    COMPARISON_FAILED = "comparison_failed"
    RECOMMENDATION_FAILED = "recommendation_failed"
    CURRENT_NETWORK_LOSSES_COVERAGE_UNKNOWN = "current_network_losses_coverage_unknown"
    CURRENT_DISPATCHING_CAPACITY_COVERAGE_UNKNOWN = "current_dispatching_capacity_coverage_unknown"
    CURRENT_NETWORK_LOSSES_RATE_MISSING = "current_network_losses_rate_missing"
    CURRENT_DISPATCHING_CAPACITY_RATE_MISSING = "current_dispatching_capacity_rate_missing"
    CURRENT_COMPONENT_CHARGE_CONFLICT = "current_component_charge_conflict"


class CoreContractError(Exception):
    """Safe, stable error contract for integration consumers."""

    def __init__(self, code: CoreErrorCode, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


# Kept as a source-compatible alias for the initial local implementation.
CoreIntegrationError = CoreContractError

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
    SOURCE_ACQUISITION_FAILED = "source_acquisition_failed"
    SOURCE_VALIDATION_FAILED = "source_validation_failed"
    COMPARISON_FAILED = "comparison_failed"
    RECOMMENDATION_FAILED = "recommendation_failed"


class CoreContractError(Exception):
    """Safe, stable error contract for integration consumers."""

    def __init__(self, code: CoreErrorCode, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


# Kept as a source-compatible alias for the initial local implementation.
CoreIntegrationError = CoreContractError

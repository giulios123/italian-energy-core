"""ARERA source snapshots and the domestic electricity 2026 importer.

The workbook importer is optional because it depends on ``openpyxl``.  Keep
the package itself importable with the base distribution so the packaged
rulesets and source models remain available without the XLSX extra.
"""

from typing import TYPE_CHECKING, Any

from italian_energy.arera.composer import (
    AreraCompositionError,
    AreraDomesticRuleSetComposer,
    DomesticCompositionPolicy,
    DomesticFiscalPolicy,
    DomesticProfileKind,
)
from italian_energy.arera.models import (
    AreraChargeRole,
    AreraChargeValue,
    AreraCustomerSegment,
    AreraDiagnostic,
    AreraDiagnosticSeverity,
    AreraHeader,
    AreraImportResult,
    AreraRegulatoryBundle,
    AreraSourceLocator,
    RawAreraSnapshot,
)

if TYPE_CHECKING:
    from italian_energy.arera.importer import (
        ARERA_DOMESTIC_2026_URL,
        AreraDomesticElectricityImporter,
        AreraFetchError,
        AreraHttpResponse,
        AreraImportError,
        AreraTransport,
        UnsupportedAreraDatasetError,
    )


_IMPORTER_EXPORTS = frozenset(
    {
        "ARERA_DOMESTIC_2026_URL",
        "AreraDomesticElectricityImporter",
        "AreraFetchError",
        "AreraHttpResponse",
        "AreraImportError",
        "AreraTransport",
        "UnsupportedAreraDatasetError",
    }
)


def __getattr__(name: str) -> Any:
    if name in _IMPORTER_EXPORTS:
        from italian_energy.arera import importer

        return getattr(importer, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ARERA_DOMESTIC_2026_URL",
    "AreraChargeRole",
    "AreraChargeValue",
    "AreraCompositionError",
    "AreraCustomerSegment",
    "AreraDiagnostic",
    "AreraDiagnosticSeverity",
    "AreraDomesticElectricityImporter",
    "AreraDomesticRuleSetComposer",
    "AreraFetchError",
    "AreraHeader",
    "AreraHttpResponse",
    "AreraImportError",
    "AreraImportResult",
    "AreraRegulatoryBundle",
    "AreraSourceLocator",
    "AreraTransport",
    "DomesticCompositionPolicy",
    "DomesticFiscalPolicy",
    "DomesticProfileKind",
    "RawAreraSnapshot",
    "UnsupportedAreraDatasetError",
]

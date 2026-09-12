"""Load frozen billing rulesets and coverage without spreadsheet dependencies."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

from italian_energy.billing.coverage import BillingCoverageMatrix
from italian_energy.domain.regulatory import RegulatoryRuleSet


class BillingArtifactError(ValueError):
    """Raised when a packaged billing artifact cannot be loaded."""


_PACKAGE_ROOT = files("italian_energy").joinpath("data", "billing")


def _read_json(path: Path | None, resource_name: str) -> object:
    if path is not None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BillingArtifactError(f"cannot read billing artifact {path}") from exc
    resource = _PACKAGE_ROOT.joinpath(resource_name)
    try:
        with resource.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BillingArtifactError(
            f"cannot read packaged billing artifact {resource_name}"
        ) from exc


def load_ruleset(
    path: Path | str | None = None,
    *,
    segment: str | None = None,
) -> RegulatoryRuleSet:
    """Load a validated ruleset from JSON or from the frozen package artifact."""

    if path is None:
        if segment is None:
            raise BillingArtifactError("segment is required for packaged ruleset loading")
        if segment not in {"resident", "non-resident"}:
            raise BillingArtifactError("segment must be resident or non-resident")
        name = f"arera-domestic-bt-{segment}-2026.json"
    else:
        path = Path(path)
        name = "custom ruleset"
    try:
        return RegulatoryRuleSet.model_validate(_read_json(path, name))
    except BillingArtifactError:
        raise
    except (TypeError, ValueError) as exc:
        raise BillingArtifactError(f"invalid billing ruleset {name}") from exc


def load_coverage_matrix(path: Path | str | None = None) -> BillingCoverageMatrix:
    """Load the frozen coverage matrix from JSON."""

    try:
        return BillingCoverageMatrix.model_validate(
            _read_json(None if path is None else Path(path), "arera-domestic-bt-coverage-2026.json")
        )
    except BillingArtifactError:
        raise
    except (TypeError, ValueError) as exc:
        raise BillingArtifactError("invalid billing coverage matrix") from exc

"""Versioned source graph for the domestic projection anchor's discovery scope.

General indexes remain complete audit evidence. This module ties their records
to the narrower primary sources that define the current anchor fields; it does
not inspect titles or infer applicability from document text.
"""

from __future__ import annotations

from italian_energy.arera.discovery import (
    DiscoveryActDisposition,
    DiscoveryActFinding,
    DiscoveryRecordChange,
    DiscoverySnapshot,
    OfficialRegistryRecord,
    RegulatoryDiscoveryReport,
    RegulatoryRegistryChannel,
)

_SCOPE_RULE_VERSION = "1.0.0"
_WATCHED_NORMATTIVA_DOCUMENT_IDS = frozenset({"072U0633", "095G0523"})


def _snapshot_by_channel(
    snapshots: tuple[DiscoverySnapshot, ...],
) -> dict[RegulatoryRegistryChannel, DiscoverySnapshot]:
    return {snapshot.channel: snapshot for snapshot in snapshots}


def _record_map(
    snapshots: tuple[DiscoverySnapshot, ...],
) -> dict[tuple[RegulatoryRegistryChannel, str], OfficialRegistryRecord]:
    return {
        (record.channel, record.act_id): record
        for snapshot in snapshots
        for record in snapshot.records
    }


def _scope_rule(
    channel: RegulatoryRegistryChannel,
) -> tuple[str, str]:
    if channel == RegulatoryRegistryChannel.ARERA_ACTS:
        return (
            "domestic-projection-arera-tariff-index-scope",
            "the complete ARERA tariff index identifies the acts that source the modeled charges",
        )
    if channel == RegulatoryRegistryChannel.NORMATTIVA_UPDATES:
        return (
            "domestic-projection-normattiva-provision-scope",
            "the complete Normattiva update scan has no relation to the monitored "
            "TUA or DPR 633/1972 source",
        )
    return (
        "domestic-projection-gazzetta-source-link-scope",
        "the complete Gazzetta record has no official link from a monitored "
        "TUA or DPR 633/1972 update",
    )


def _out_of_scope_finding(record: OfficialRegistryRecord) -> DiscoveryActFinding:
    rule_id, rationale = _scope_rule(record.channel)
    return DiscoveryActFinding(
        channel=record.channel,
        act_id=record.act_id,
        disposition=DiscoveryActDisposition.IRRELEVANT_BY_VERSIONED_RULE,
        rationale=rationale,
        rule_id=rule_id,
        rule_version=_SCOPE_RULE_VERSION,
        source_record=record,
    )


def scope_domestic_projection_discovery(
    discovery: RegulatoryDiscoveryReport,
    *,
    previous_snapshots: tuple[DiscoverySnapshot, ...] = (),
) -> RegulatoryDiscoveryReport:
    """Scope broad registry findings to sources used by DomesticProjectionAnchor.

    This policy changes only review findings for the broad ARERA acts,
    Normattiva updates, and Gazzetta archive channels. The exact source indexes
    must be complete first. ADM, direct ARERA tariff records, and updates to
    the watched legal acts always retain their original classification.
    """

    if not discovery.scans_complete:
        return discovery

    current_snapshots = _snapshot_by_channel(discovery.snapshots)
    old_snapshots = _snapshot_by_channel(previous_snapshots)
    current_records = _record_map(discovery.snapshots)
    old_records = _record_map(previous_snapshots)

    tariff_snapshot = current_snapshots[RegulatoryRegistryChannel.ARERA_TARIFFS]
    normattiva_snapshot = current_snapshots[RegulatoryRegistryChannel.NORMATTIVA_UPDATES]

    old_tariff_snapshot = old_snapshots.get(RegulatoryRegistryChannel.ARERA_TARIFFS)
    old_normattiva_snapshot = old_snapshots.get(RegulatoryRegistryChannel.NORMATTIVA_UPDATES)
    tariff_act_ids = {record.act_id for record in tariff_snapshot.records}
    if old_tariff_snapshot is not None:
        tariff_act_ids.update(record.act_id for record in old_tariff_snapshot.records)
    if not tariff_act_ids:
        # A structurally complete but empty tariff index is not evidence that
        # the broad ARERA acts index has no impact on this anchor.
        return discovery

    prior_normattiva_records = (
        () if old_normattiva_snapshot is None else old_normattiva_snapshot.records
    )
    watched_source_records = tuple(
        record
        for record in (*normattiva_snapshot.records, *prior_normattiva_records)
        if record.document_id in _WATCHED_NORMATTIVA_DOCUMENT_IDS
    )
    linked_gazzetta_act_ids = {
        act_id for record in watched_source_records for act_id in record.latest_amending_act_ids
    }

    def is_in_scope(record: OfficialRegistryRecord) -> bool:
        if record.channel == RegulatoryRegistryChannel.ARERA_ACTS:
            return record.act_id in tariff_act_ids or record.document_id in tariff_act_ids
        if record.channel == RegulatoryRegistryChannel.NORMATTIVA_UPDATES:
            return record.document_id in _WATCHED_NORMATTIVA_DOCUMENT_IDS
        if record.channel == RegulatoryRegistryChannel.GAZZETTA_SERIE_GENERALE:
            return record.act_id in linked_gazzetta_act_ids
        return True

    record_by_key = {**old_records, **current_records}

    def scope_finding(finding: DiscoveryActFinding) -> DiscoveryActFinding:
        if finding.disposition != DiscoveryActDisposition.REVIEW_REQUIRED:
            return finding
        record = finding.source_record or current_records.get((finding.channel, finding.act_id))
        if record is None or is_in_scope(record):
            return finding
        return _out_of_scope_finding(record)

    scoped_by_key: dict[tuple[RegulatoryRegistryChannel, str], DiscoveryActFinding] = {}
    snapshots: list[DiscoverySnapshot] = []
    for snapshot in discovery.snapshots:
        scoped_findings = tuple(scope_finding(item) for item in snapshot.findings)
        snapshots.append(snapshot.model_copy(update={"findings": scoped_findings}))
        scoped_by_key.update({(item.channel, item.act_id): item for item in scoped_findings})

    findings = tuple(
        scoped_by_key.get((item.channel, item.act_id), scope_finding(item))
        for item in discovery.findings
    )

    scoped_changes: list[DiscoveryRecordChange] = []
    for change in discovery.changes:
        if change.channel not in {
            RegulatoryRegistryChannel.ARERA_ACTS,
            RegulatoryRegistryChannel.GAZZETTA_SERIE_GENERALE,
            RegulatoryRegistryChannel.NORMATTIVA_UPDATES,
        }:
            scoped_changes.append(change)
            continue
        record = record_by_key.get((change.channel, change.act_id))
        if record is None or is_in_scope(record):
            scoped_changes.append(change)

    return discovery.model_copy(
        update={
            "snapshots": tuple(snapshots),
            "findings": findings,
            "changes": tuple(scoped_changes),
        }
    )


__all__ = ["scope_domestic_projection_discovery"]

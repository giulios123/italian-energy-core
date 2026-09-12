# Spec 011 — Current Domestic Advisor

**Version:** 0.11.0 · **Status:** implemented locally, release-gated

## Purpose

Provide a deterministic, auditable current comparison for domestic electricity
supplies in low-voltage (BT) service. The service composes the verified Portale
Offerte catalogue, twelve complete monthly observations and the existing billing
and recommendation engines. It does not forecast prices and does not expose raw
catalogue bytes through the integration contract.

## Contract

`CurrentDomesticEnergyService.acquire_catalog()` acquires one verified official
catalogue snapshot. `compare()` freezes that snapshot and evaluates the next
twelve complete calendar months in `low_index`, `base` and `high_index`
scenarios. Historical monthly consumption and the latest twelve complete index
observations are shifted onto the horizon; index values are multiplied by 0.80,
1.00 and 1.20 respectively. These are labelled scenarios, never predictions.

The base scenario is the ranking authority. `recommend()` delegates only the
base `PortalComparisonResult` to the deterministic recommendation engine. A
switch is eligible only when both configured thresholds (EUR and percentage)
are met; no weighted score or generative model is involved.

## Safety invariants

- only domestic electricity BT supplies with an explicit residential value are
  accepted;
- exactly twelve complete monthly buckets are required, without mixing `ALL`
  and named bands;
- the current contract must be active at `as_of` and cover the full horizon, or
  the caller must set and persist `continuation_assumption=true`;
- catalogue records must be verified and applicable to the supplied eligibility
  profile; exclusions remain part of the normalized result;
- future regulatory billing requires an injected verified ruleset and coverage
  artifact. Missing official coverage fails closed with `coverage_unavailable`;
- integration envelopes are versioned, canonical JSON and contain no raw source
  content.

## Release gate

The local implementation is not a release. Full Core gates, wheel/sdist
checksums and a signed `v0.11.0` GitHub release require explicit approval.

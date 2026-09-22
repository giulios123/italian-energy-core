# Spec 011 — Current Domestic Advisor

**Version:** 0.11.0 · **Status:** released

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

## Additive contract in v0.11.1 — preflight

`CurrentDomesticEnergyService.preflight(request, catalog)` reports whether a
current comparison can proceed without calculating prices or performing a
comparison. It does not acquire a catalogue: callers must pass a previously
acquired snapshot. A missing snapshot is reported as not ready.

The typed `CurrentPreflightResult` contains `ready`, `as_of`, the derived
twelve-month `horizon`, `checks`, ordered and de-duplicated `reason_codes`,
`continuation_required`, and a `coverage` status. The stable `checks` keys are
`request_contract`, `catalog_verified`, `historical_indexes`,
`regulatory_coverage`, and `future_horizon`. A gate is true only when its
condition was verified; an uncheckable required gate is false. `ready` is true
only when every gate is true. `reason_codes` use stable `CoreErrorCode` values.
`coverage.status` is `verified` only when a verified packaged ruleset and
coverage matrix cover the entire derived horizon; otherwise it is
`unavailable`.

Preflight checks the same request, contract-continuation, projected-index, and
regulatory-coverage conditions consumed by `compare()`. Contract continuation
is permitted only when explicitly declared in the request and is surfaced by
`continuation_required`. This additive contract is advertised as capability
`current_portal_preflight` and schema
`italian-energy/current-preflight-result/v1`; historical schema IDs are
unchanged.

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

The `v0.11.1` release includes the full Core gates and installable wheel/sdist
artifacts. The preflight is a readiness check, not a price calculation or
regulatory certification. The implementation remains scoped to domestic
electricity BT and does not provide a general forecast.

# ADR 0002 — Periodi e tempo

## Stato

Accettato

## Decisione

I periodi civili usano intervalli semiaperti `[start, end)`. Gli intervalli di mercato richiedono datetime timezone-aware; `Europe/Rome` è il riferimento civile per l’Italia. I dati serializzati conservano il timezone.

## Conseguenze

Le finestre adiacenti non si sovrappongono e i cambi DST sono rappresentabili. Le conversioni e l’allineamento a dati di mercato saranno definiti dal pricing evaluator.

# TODO — extraction library licence (AGPL) — DEFERRED

**Status:** parked 2026-07-20 by decision. **Revisit before any commercial
distribution / SaaS to third parties.** Not urgent; nothing below affects
internal use, prototyping, or running the engine for your own quotes.

## The issue
The extraction stage uses **PyMuPDF**, licensed **AGPL-3.0**. AGPL can require
you to open-source *your* surrounding code once you **distribute** the software
or offer it as a **network service** commercially. Reading text/lines from PDFs
for yourself carries no such obligation.

## Becomes a gate when
X-Ray ships inside a commercial product delivered to other people. Until then,
build freely.

## Options
1. **Legal read (recommended before ship).** Have a professional confirm what
   AGPL obliges for the actual Looplet distribution model. $0 engineering.
2. **Swap to pypdfium2.** Licence: **Apache-2.0 / BSD-3-Clause — free,
   commercial-OK, no fees ever ($0).** Cost is engineering only: rewrite the
   extraction stage and re-prove the ground truths (29995/13530/2745 glyph
   recovery, raster scan detection) against both fixtures. Contained — only
   `src/xray/reassemble.py` touches the library.
3. **Commercial PyMuPDF licence** from Artifex. $0 engineering, ongoing fee;
   gather current pricing when nearing ship.

## Action
Owner: Daniel. Trigger: when commercial distribution is on the horizon, pick
1, 2, or 3. The swap (2) stays a well-scoped escape hatch either way.

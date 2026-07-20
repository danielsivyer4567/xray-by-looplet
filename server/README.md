# X-Ray by Looplet — Mode B worker

A thin FastAPI edge around `xray.engine.run()`. A Looplet job posts a plan PDF;
the worker returns draft quote lines (plus the marked PDF path). This is starter
code — runnable and tested, meant to be adapted to your infra, not shipped as-is.

## Run

```
pip install -r requirements.txt -r server/requirements.txt
set PYTHONPATH=src                      # Windows cmd; or: pip install -e .
uvicorn server.app:app --host 0.0.0.0 --port 8000
```

## Endpoints

### `GET /health`
```json
{ "status": "ok", "engine": "xray-by-looplet", "version": "0.1.0" }
```

### `POST /v1/takeoff`
Multipart form, field `file` = the plan PDF. Optional `?marked_pdf=false` to skip
writing the annotated PDF.

Response envelope (`server/quote_lines.py::build_quote_draft`):
```json
{
  "engine":   { "name": "xray-by-looplet", "version": "0.1.0" },
  "document": { "path": "...", "sha256": "...", "pages": 5 },
  "quote_lines": [
    {
      "source_quantity_id": "qty-frames",
      "trade": "structural steel",
      "description": "portal frames",
      "quantity": 5.0,
      "unit": "ea",
      "basis": "bays + 1 = 4 + 1 = 5",
      "confidence_tier": "reconciled",
      "review_required": false,
      "evidence_refs": ["e0-6", "chk-count-portal-rafter-p0"],
      "notes": "frame count confirmed by label count check",
      "rate": null,
      "amount": null
    }
  ],
  "flags":   [ { "ref": "...", "reason": "..." } ],
  "summary": { "lines": 8, "needs_human": 1, "reconciled": 2,
               "single_source": 5, "checks_pass": 5, "checks_flag": 4 },
  "marked_pdf_path": "..."
}
```

## Mapping to Looplet columns (the one step you own)

`quote_lines[]` is engine-derived and stable. Map it onto your quote-line table.
Keep `basis`, `confidence_tier`, `review_required`, and `evidence_refs` — they are
the trust model. Surface `review_required == true` and every `flags[]` entry for a
human to confirm before a quote is sent. `rate`/`amount` are left null for your
pricing step to fill. This module intentionally does NOT guess your schema.

## Trade coverage (read before you demo)

The extraction/checks layers run on **any** plan PDF, but **quantities are only
produced for trades that have a rule pack**. v0.1.0 ships ONE pack: steel
portal-frame sheds. Any other plan (electrical, plumbing, concrete, general
warehouse) returns entities + checks + a marked PDF but an **empty
`quote_lines`** — exactly as the warehouse fixture does. Adding a trade = adding
a rule pack (`src/xray/quantify.py`) + a fixture + tests. See `docs/GUIDE.md`
("Extending") and `docs/HANDOVER.md`.

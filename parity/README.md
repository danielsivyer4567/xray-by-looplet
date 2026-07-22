# parity — the reliability gate

The Python engine is the **oracle**: it defines the right answer. Every other
runtime we ship must reproduce it byte-for-byte on the frozen fixtures before it
is allowed anywhere near a user.

| runtime | status |
| --- | --- |
| Python engine (oracle) | reference |
| Frozen PyInstaller sidecar (desktop) | **PASS** — 3/3 byte-identical |
| Pyodide / WASM (browser) | not built yet — must pass this gate before shipping |
| Container fallback | not built yet |

## Gate a runtime

```bash
python -m parity.compare path/to/*.xray.json
```

Exit code is non-zero if any fixture diverges. The fixture name is inferred from
the filename (`shed-manners-aline.xray.json` -> `shed-manners-aline`), or pass
`--fixture`. `parity.compare` is pure stdlib and does **not** import the engine,
so it runs in a bare CI job that only has the candidate's JSON.

## Canonical form

`document.path` is removed — it records where the input happened to sit on disk,
which is not a property of the drawing — then:

```python
json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
```

and sha256 over the UTF-8 bytes. Reference files are stored in exactly this form,
so the bytes on disk *are* the bytes hashed.

## The environment is recorded, as a precaution

`manifest.json` records the PDFium build and pypdfium2 version each reference was
frozen under, and a digest mismatch where the stack has moved is reported as
`ENVIRONMENT DRIFT`. PDFium's text extraction and raster/vector classification
*can* change between Chromium builds, so keeping the two causes separable is
cheap insurance:

```
engine logic changed  -> a real regression, fix the code
PDFium build changed  -> possible expected drift, investigate before re-freezing
```

**This is precautionary, not a diagnosed problem.** It was tested directly: the
engine was run against all three fixtures under PDFium **149.0.7802.0**
(pypdfium2 5.7.1) and **152.0.7947.0** (pypdfium2 5.12.1). Every fixture produced
**byte-identical output on both builds**. On this evidence PDFium's version does
not perturb these takeoffs, and the WASM engine is *not* hostage to matching a
specific PDFium build — a constraint earlier notes asserted but that no
measurement here supports.

That is three fixtures across two builds, not a proof of general invariance, so
`requirements.txt` should still pin `pypdfium2` exactly rather than `>=4`. Pin it
as hygiene, not as a fix for a known break.

## Unreproducible legacy digests (open)

An earlier handover pinned reference digests for all three fixtures. Only one of
them reproduces here:

| fixture | legacy pin | this repo |
| --- | --- | --- |
| shed-manners-aline | `6b3a766ca4aa5348` | **matches exactly** |
| electrical-schedule | `18d2590841088f9b` | `e8e57aaea8ecdbbc` |
| warehouse-design21 | `d94ad42640b70042` | `57b420a6bd36aadd` |

The two mismatches were chased and are **not** explained by the obvious suspects:

- **Not PDFium** — identical output under 149 and 152 (above).
- **Not recent engine commits** — identical output at `2748f4f`, `cfe0771`,
  `b35ae3e`, `33fdfd2` and `ee8b25e`.
- **Not the fixtures drifting** — `fixtures/` is unmodified since `6533f1a`,
  which predates every commit tested.
- **Not the canonical form** — the shed fixture matches its legacy pin *exactly*
  under that same canonicalisation, which would be a wild coincidence otherwise.

The digests are stable and self-consistent within this repo; they simply do not
match the legacy pins. The most likely explanation is that the legacy values were
produced somewhere with different fixture files or a different engine state.
Until that is resolved, **this repo's own frozen references are the oracle** and
the legacy digests should not be treated as authoritative.

Worth noting while it is open: `warehouse-design21` yields **0 quantities**, and
no test asserts anything about its quantities either way. If that fixture is
supposed to produce numbers, the gate is currently freezing in a silent gap.

## Re-freezing

`parity.freeze` is the only writer of `reference/` and `manifest.json`, and it is
a deliberate manual step. If freezing happened automatically whenever output
changed, the gate would rubber-stamp every regression it exists to catch.

```bash
python -m parity.freeze --check   # report drift, write nothing
python -m parity.freeze           # adopt the new output as the oracle
```

Only re-freeze after confirming the new numbers are **correct**.

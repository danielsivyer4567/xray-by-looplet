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

## Byte-identity depends on the native PDF stack

This is the part that bites. Byte-identity is a property of
**(engine + fixture + PDFium build)**, not the engine alone. PDFium's text
extraction and raster/vector classification change between Chromium builds.

Measured, not hypothetical: references frozen under PDFium **149.0.7802.0** were
re-checked under **152.0.7947.0**. The shed fixture still matched. The
raster-heavy warehouse and the electrical schedule did not — same engine code,
same input, different bytes out.

Two consequences:

1. **`requirements.txt` pins `pypdfium2>=4`, which is unpinned in practice.** A
   fresh `pip install` can silently move the PDFium floor and change quantities.
   Pin it to the build the references were frozen under.
2. **The WASM engine must be built against the same PDFium build** as the
   manifest records, or it cannot pass this gate — see the handover's §5 pin.

So `manifest.json` records the environment each reference was frozen under, and a
digest mismatch is reported as `ENVIRONMENT DRIFT` when the stack moved. That
distinction matters:

```
engine logic changed  -> a real regression, fix the code
PDFium build changed  -> expected drift, re-freeze deliberately
```

## Re-freezing

`parity.freeze` is the only writer of `reference/` and `manifest.json`, and it is
a deliberate manual step. If freezing happened automatically whenever output
changed, the gate would rubber-stamp every regression it exists to catch.

```bash
python -m parity.freeze --check   # report drift, write nothing
python -m parity.freeze           # adopt the new output as the oracle
```

Only re-freeze after confirming the new numbers are **correct**.

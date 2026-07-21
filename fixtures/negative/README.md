# Negative fixtures

Files here are **deliberately bad inputs**. They exist so the engine can be
tested on what it must *reject or flag*, not just what it must parse. Never
treat anything in this directory as a source of ground truth.

---

## `shed-flattened-from-pdf.dxf`

**What it is:** X-Ray's own PDF extraction of `fixtures/shed-manners-aline.pdf`,
dumped into a DXF container. It is *not* a CAD drawing of the shed.

**Why it's kept:** it is a convincing fake. It opens cleanly in any CAD program,
it is valid R2010, and it is geometrically a picture of the right building — so a
casual look says "native CAD file". Using it to test a DXF adapter would be
**circular**: the adapter would be fed X-Ray's own output and would confirm X-Ray
reproduces X-Ray. It would pass while proving nothing.

A real CAD adapter must be able to tell this apart from a genuine native file. If
it can't, it will read files like this one and emit confident nonsense — exact
counts and lengths derived from a flattened plot with no semantics behind them.

### The four tells (any one is sufficient)

1. **`$LASTSAVEDBY` is `ezdxf`** — machine-written, never saved by a CAD
   application.
2. **Coordinates are PDF points, not model units.** Extents are
   `X 14–828, Y 16–583`, i.e. A4 landscape (842x595 pt) — the *sheet*. A native
   drawing of this shed would span 16000 x 9000 *millimetres* — the *building*.
   The header compounds it: `$INSUNITS 6` claims metres while the coordinates
   are plainly points, the fingerprint of a header written blind.
3. **Text is split into PDF text-runs, not authored strings.** `North`, `VIC`,
   `Sheds` are three separate TEXT entities on one baseline. Native CAD stores
   `"North VIC Sheds"` as a single TEXT/MTEXT.
4. **Zero `DIMENSION` entities**, yet 27 dimension *values* (`16000`, `9000`,
   `3500`, ...) float around as loose TEXT — exactly what flattening a plot
   produces. A native drawing carries real DIMENSION entities that know what
   they measure.

### Structure summary

```
layers      4    0, Defpoints, GEOMETRY, TEXT   <- generic buckets, no trade semantics
                                                   (no A-WALL / S-STEEL / dim layer)
blocks      0    only the *Model_Space / *Paper_Space stubs
INSERTs     0    <- nothing to count
entities    2380 LINE 2114 | TEXT 203 | LWPOLYLINE 63 | DIMENSION 0
```

Compare a genuine native CAD plan, which should show named trade layers, real
block definitions with `INSERT` references (doors/windows/symbols — the source of
**exact** counts), and `DIMENSION` entities.

### Intended use

- Regression test for a future DXF adapter's **provenance check**: this file
  must be rejected, or flagged loudly, rather than silently ingested.
- Reference for what a PDF->DXF conversion looks like. Such converters are
  common, so real users will hand us files like this believing they're CAD.

**Do not** use it for the parity gate ("a DXF of the shed reproduces the PDF's
quantities"). That gate needs a file saved by a CAD program — AutoCAD, BricsCAD,
FreeCAD, or a shed-detailing system — for the same building.

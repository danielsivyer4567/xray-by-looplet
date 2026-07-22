"""parity — the gate that keeps every runtime honest against the Python oracle.

`parity.compare` judges a candidate takeoff.json (frozen sidecar, WASM, container)
and is pure stdlib. `parity.freeze` re-freezes the references and needs the engine.

The convenience names below are resolved lazily (PEP 562). Importing them eagerly
would pull in parity.compare during package import, which makes
`python -m parity.compare` warn that the module was already in sys.modules.
"""
_EXPORTS = {
    "ParityResult", "canonical", "compare", "compare_file", "digest",
    "first_divergence", "load_manifest",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str):
    if name in _EXPORTS:
        from parity import compare as _c
        return getattr(_c, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(_EXPORTS | set(globals()))

/**
 * Tests for the host kit. Run with:  node --test host/xray-host.test.js
 * (`node --test host/` tries to load the directory itself and fails.)
 *
 * Uses only node:test so the engine repo gains no JS dependency to run them.
 *
 * The real-binary case is an integration test that SKIPS when the engine has not
 * been built, rather than failing — a fresh clone has no binary, and a test that
 * cries wolf there teaches everyone to ignore it.
 */
'use strict'

const test = require('node:test')
const assert = require('node:assert')
const fs = require('fs')
const os = require('os')
const path = require('path')

const host = require('./xray-host')

const REPO = path.resolve(__dirname, '..')
const REAL_ENGINE = path.join(REPO, 'desktop', 'engine', 'bin', host.EXE)
const SHED = path.join(REPO, 'fixtures', 'shed-manners-aline.pdf')

function tmpFile(name = 'fake-engine') {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'xray-test-'))
  const p = path.join(dir, name)
  fs.writeFileSync(p, '')
  return p
}

// --- resolveEnginePath --------------------------------------------------------

test('resolveEnginePath returns the first candidate that exists', () => {
  const real = tmpFile()
  assert.strictEqual(
    host.resolveEnginePath([path.join(os.tmpdir(), 'nope-1'), real]),
    real,
  )
})

test('resolveEnginePath returns null when nothing exists', () => {
  assert.strictEqual(host.resolveEnginePath([path.join(os.tmpdir(), 'nope-2')]), null)
  assert.strictEqual(host.resolveEnginePath([]), null)
})

test('XRAY_ENGINE_PATH outranks the candidates', () => {
  const override = tmpFile('override-engine')
  const candidate = tmpFile('candidate-engine')
  const previous = process.env.XRAY_ENGINE_PATH
  process.env.XRAY_ENGINE_PATH = override
  try {
    // An operator pointing at a specific build must not be second-guessed.
    assert.strictEqual(host.resolveEnginePath([candidate]), override)
  } finally {
    if (previous === undefined) delete process.env.XRAY_ENGINE_PATH
    else process.env.XRAY_ENGINE_PATH = previous
  }
})

test('a non-existent XRAY_ENGINE_PATH falls through instead of hard-failing', () => {
  const candidate = tmpFile()
  const previous = process.env.XRAY_ENGINE_PATH
  process.env.XRAY_ENGINE_PATH = path.join(os.tmpdir(), 'definitely-not-here')
  try {
    assert.strictEqual(host.resolveEnginePath([candidate]), candidate)
  } finally {
    if (previous === undefined) delete process.env.XRAY_ENGINE_PATH
    else process.env.XRAY_ENGINE_PATH = previous
  }
})

// --- engineStatus -------------------------------------------------------------

test('engineStatus reports available with the resolved path', () => {
  const real = tmpFile()
  assert.deepStrictEqual(host.engineStatus([real]), {
    available: true,
    enginePath: real,
  })
})

test('engineStatus explains itself when unavailable', () => {
  const status = host.engineStatus([])
  assert.strictEqual(status.available, false)
  assert.strictEqual(status.enginePath, null)
  // The reason is banner copy, so it must name the fix, not just the symptom.
  assert.match(status.reason, /build-engine|XRAY_ENGINE_PATH/)
})

// --- runTakeoff failure paths -------------------------------------------------

test('runTakeoff rejects with the engine-missing reason', async () => {
  await assert.rejects(
    () => host.runTakeoff(SHED, { candidates: [] }),
    /engine binary not found/i,
  )
})

test('runTakeoff rejects when the plan PDF is missing', async () => {
  const fake = tmpFile()
  await assert.rejects(
    () => host.runTakeoff(path.join(os.tmpdir(), 'no-such-plan.pdf'), {
      candidates: [fake],
    }),
    /plan PDF not found/,
  )
})

test('runTakeoff rejects rather than resolving when the binary is not runnable', async () => {
  // An empty file resolves as "present" but cannot execute. The host must
  // surface that, never resolve with an empty takeoff.
  const fake = tmpFile()
  await assert.rejects(() => host.runTakeoff(SHED, { candidates: [fake] }))
})

// --- real engine (integration) ------------------------------------------------

test('runTakeoff drives the real frozen engine', { skip: !fs.existsSync(REAL_ENGINE) }, async () => {
  const before = fs.readdirSync(os.tmpdir()).filter((d) => d.startsWith('xray-')).length

  const takeoff = await host.runTakeoff(SHED, { candidates: [REAL_ENGINE] })

  assert.strictEqual(takeoff.engine.name, 'xray-by-looplet')
  assert.ok(Array.isArray(takeoff.quantities))
  assert.ok(takeoff.quantities.length > 0, 'the shed fixture yields quantities')
  assert.strictEqual(takeoff.document.sha256.length, 64)

  // Every quantity carries its own derivation — that audit trail is the product.
  for (const q of takeoff.quantities) {
    assert.ok(q.formula, `quantity ${q.id} must carry a formula`)
    assert.ok(q.tier, `quantity ${q.id} must carry a tier`)
  }

  // Scratch dirs are removed, so client plans do not pile up on disk.
  const after = fs.readdirSync(os.tmpdir()).filter((d) => d.startsWith('xray-')).length
  assert.strictEqual(after, before, 'temp takeoff dir should be cleaned up')
})

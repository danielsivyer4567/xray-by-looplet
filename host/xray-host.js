/**
 * xray-host.js — the canonical way to run the X-Ray engine from a Node host.
 *
 * WHY this exists
 * ---------------
 * X-Ray is a standalone product that other apps may EMBED. That only stays true
 * if the embedding never becomes the real implementation. Before this module the
 * spawn logic existed twice — once in the standalone desktop app, once in the
 * Looplet CRM's Electron main process — and two copies drift until the busier
 * one silently becomes canonical and "standalone" degrades into a claim.
 *
 * So this file is owned by the ENGINE repo and consumed by every host. The
 * dependency runs one way: hosts depend on X-Ray, X-Ray depends on nothing.
 *
 * Deliberately zero-dependency CommonJS against Node built-ins only, so it can
 * be required by an Electron main process, a plain Node script, or a test with
 * no build step and no package install.
 *
 * WHAT a host still owns
 * ----------------------
 * Where the binary might live (packaged resources, dev checkout) differs per
 * host, so candidates are passed IN rather than guessed here. Everything after
 * that — running it, reading the result, cleaning up — is identical everywhere
 * and lives here.
 */
'use strict'

const { execFile } = require('child_process')
const fs = require('fs')
const os = require('os')
const path = require('path')

/** Frozen-binary name per platform. */
const EXE = process.platform === 'win32' ? 'xray-engine.exe' : 'xray-engine'

/** A takeoff on a large raster set is slow but bounded; never hang a UI. */
const DEFAULT_TIMEOUT_MS = 120000

/**
 * First existing path wins. `XRAY_ENGINE_PATH` always outranks the candidates:
 * an operator pointing at a specific build must not be second-guessed.
 */
function resolveEnginePath(candidates = []) {
  const override = process.env.XRAY_ENGINE_PATH
  if (override && fs.existsSync(override)) return override
  for (const candidate of candidates) {
    if (candidate && fs.existsSync(candidate)) return candidate
  }
  return null
}

/**
 * Status for an engine-availability banner. Hosts should surface this BEFORE a
 * user picks a plan, so a missing engine is not discovered after a long wait.
 */
function engineStatus(candidates = []) {
  const enginePath = resolveEnginePath(candidates)
  if (enginePath) return { available: true, enginePath }
  return {
    available: false,
    enginePath: null,
    reason:
      'X-Ray engine binary not found. Build it with scripts/build-engine in ' +
      'the xray-by-looplet repo, or set XRAY_ENGINE_PATH.',
  }
}

/**
 * Run ONE takeoff and resolve the parsed takeoff JSON.
 *
 * The engine writes into a scratch directory this function creates and removes,
 * so client plans never accumulate on shared storage — the engine's public-API
 * rule, applied to every host.
 *
 * Rejects with the engine's stderr when it fails, because that text is the
 * actionable part; swallowing it leaves a host reporting "something went wrong".
 */
function runTakeoff(pdfPath, options = {}) {
  const { candidates = [], timeoutMs = DEFAULT_TIMEOUT_MS } = options

  return new Promise((resolve, reject) => {
    const status = engineStatus(candidates)
    if (!status.available) return reject(new Error(status.reason))
    if (!pdfPath || !fs.existsSync(pdfPath)) {
      return reject(new Error(`plan PDF not found: ${pdfPath}`))
    }

    const outDir = fs.mkdtempSync(path.join(os.tmpdir(), 'xray-'))
    const cleanup = () => fs.rm(outDir, { recursive: true, force: true }, () => {})

    execFile(
      status.enginePath,
      ['run', pdfPath, '--out', outDir],
      { timeout: timeoutMs, windowsHide: true, maxBuffer: 32 * 1024 * 1024 },
      (err, _stdout, stderr) => {
        try {
          if (err) {
            const detail = (stderr || '').toString().trim()
            return reject(new Error(detail || err.message))
          }
          const jsonFile = fs
            .readdirSync(outDir)
            .find((f) => f.endsWith('.json'))
          if (!jsonFile) return reject(new Error('engine produced no takeoff JSON'))
          resolve(JSON.parse(fs.readFileSync(path.join(outDir, jsonFile), 'utf8')))
        } catch (e) {
          reject(e instanceof Error ? e : new Error(String(e)))
        } finally {
          cleanup()
        }
      },
    )
  })
}

module.exports = {
  EXE,
  DEFAULT_TIMEOUT_MS,
  resolveEnginePath,
  engineStatus,
  runTakeoff,
}

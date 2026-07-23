# Moving X-Ray to another Claude login without losing anything

The trick to not losing track: **git is the source of truth, not the chat.**
Almost everything durable is already pushed to GitHub, so a new Claude login
doesn't "inherit" the work — it *reads* it from the repo. This file is committed
on purpose, because the one thing that will NOT survive the move is the
conversation you're reading this in.

## What transfers, and how

| Thing | Lives in | Rides along? |
| --- | --- | --- |
| Engine code, docs, HANDOFF.md, roadmap, READMEs | git → GitHub | **Yes** — clone the repo |
| CRM `/xray` embed | git → GitHub (LoopletCRM/Looplet) | **Yes** — clone the branch |
| The distilled session history | `HANDOFF.md` (committed) | **Yes** |
| Auto-memory (2 X-Ray files) | your `.claude` folder | Only same machine; also snapshot here in `docs/handoff/` |
| The specific chat you had | that session | **No** — but HANDOFF.md replaces it |
| Generated Oxworks catalogue | `pricing/out/` (gitignored) | **No** — regenerate in one command |
| RFQ scope report | scratchpad | **No** — client material, was never committed |

Everything in the "No" rows is either regenerable or already captured in a
committed file. Nothing important is trapped in the chat.

## Everything is pushed

As of the last session, both repos had zero unpushed commits and zero
uncommitted tracked changes. Confirm before you switch:

```bash
git -C C:\repos\xray-by-looplet status
git -C C:\repos\xray-by-looplet log --oneline @{u}..HEAD   # empty = all pushed
```

## The procedure

### Case A — same Windows machine, same user (`danie`), just a different Claude account

Nothing to move. The repos are still at `C:\repos\...` and the memory is still
under `C:\Users\danie\.claude`. The **only** thing the new login lacks is this
conversation, and HANDOFF.md is that conversation distilled. So:

1. Open the new login's Claude Code in `C:\repos\xray-by-looplet`.
2. First message: **"Read HANDOFF.md and docs/handoff/, then tell me the current
   state and open problems before doing anything."**

That's it. The new session is now caught up.

### Case B — different machine, or different Windows user

1. Clone both repos from GitHub:
   ```bash
   git clone https://github.com/danielsivyer4567/xray-by-looplet
   git clone https://github.com/LoopletCRM/Looplet          # CRM (large)
   ```
2. Check out the working branches:
   ```bash
   git -C xray-by-looplet checkout feat/desktop-electron
   git -C Looplet         checkout feat/xray-embed
   ```
3. The memory snapshots travel in the repo (`docs/handoff/memory-*.md`). If you
   want them re-seeded as live auto-memory on the new machine, copy them into
   `<newuser>/.claude/projects/<project-slug>/memory/` and add index lines to
   that folder's `MEMORY.md` — but this is optional; HANDOFF.md + the snapshots
   are enough for a session to work from.
4. First message: same as Case A step 2.

## Rebuild the things that don't ride git

- **Frozen engine binary** (~80 MB, gitignored):
  `powershell -File desktop\scripts\build-engine.ps1`
- **Oxworks catalogue** (gitignored prices):
  `python -m pricing.oxworks "<path to price list>.pdf" --out oxworks-catalogue`
  The source PDF is on OneDrive, not in git — keep a copy.
- **Node deps:** `npm install` in `desktop/` and in the CRM repo.

## The one thing to hand a person, not a machine

The RFQ scope report (356 Ruffles Rd) and the source price-list PDF are **not in
git** — client and supplier material doesn't belong there. If the new login is a
different *person*, send those files directly; they won't appear from a clone.

## Sanity check after the move

New session should be able to answer, from HANDOFF.md alone:
- what the four products are and which repo each lives in,
- that nothing is merged and all merges are Daniel-gated,
- the open problems (esp. `feat/fixes` can't build),
- the corrected facts (PDFium doesn't change quantities; 274 pages not 967).

If it can, the transfer worked.

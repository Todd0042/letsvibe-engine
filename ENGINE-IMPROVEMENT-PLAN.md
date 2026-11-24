# LetsVibe engine improvement plan

Owner: Todd. Planned with Claude (2026-11-21). Can be carried out by Claude or agy: tick the boxes and commit after
each step, so whoever continues picks up from the last tick. **Planning document: nothing here is done yet.**

## Ground rules (decided)

- **Fully local.** Production grading never uses a paid or remote model (privacy policy). No paid "second judge".
- **No tuning to Todd's own repos.** An engine change is kept only if it improves the benchmark as a whole without
  making any slice worse (step 3). Fixes in steps 1-2 must be general (they help every repo equally).
- **8 GB GPU.** Don't raise the model size, the 32k context, or add multi-run voting (OOM / CPU spill / 3x time).
  Anything GPU-heavy runs overnight through the host gpu-scheduler; cache everything except the LLM step.
- **The live site isn't touched** until Todd deploys (blue-green Docker containers; watchdog). Todd's earlier
  uncommitted work is committed as WIP (letsvibe f06dd5d on gpu-scheduler-turns, engine 36fb9ff on main; local only,
  both repos are public so pushing = publishing). Note: the live engine v10.3 (and v10.2) weren't in git until then.
- New engine version number for any change that moves scores.

## Evidence that motivated this (VibeBuilder-IDE-public, three reports, v10.3)

- Code Health stuck at 60.5 through real fixes: every penalty is **capped** (swallowed errors max 18 pts = reached
  at 6; oversized functions max 15), so 100 - 18 - 15 - 6.5 = 60.5 regardless; also not normalised by repo size.
- "36 swallowed errors" both times by coincidence: fixed ones disappeared, new code added others, and most flagged
  are deliberate (`BlockingIOError` on non-blocking reads, `ProcessLookupError` killing an exited process,
  `WebSocketDisconnect`). Rust isn't scanned at all.
- 6 of 9 LLM weaknesses across the reports were false (cited lines that don't exist; "missing" validation/timeout/
  notification/error handling that exists). Functionality scored 100 while listing 3 weaknesses.

## Working rules (Todd, 2026-11-21)
- Branch `engine-v10.4` (letsvibe-engine) and a matching branch in letsvibe for analyzer/site changes; never main
  until everything is verified. A commit per sub-step; a commit + push per milestone.
- Engine version: `v10_4_verified`, a copy of v10.3 with identical prompts, registered as status "testing"
  (v10.3 stays production/default).
- Test repos (already graded by v10.3, so their v10.3 reports are the baseline; expand later, step 3 is for fairness):
  Todd0042/VibeBuilder-IDE-public (py/ts/rs, known false claims), keywan-ghadami/winnow-grammar (Rust, external),
  Todd0042/letsvibe-reality-check (py, small), Todd0042/mx5-dash (C++, high code health),
  Todd0042/echoes-of-logos (Kotlin, low code health / many findings).

## Steps

### 1. No-GPU fixes (letsvibe analyzers + engine rubric)
- [x] **1a. Claim verifier.** (done: v10_4_verified/verify.py, tests/test_v10_4_verify.py; branch engine-v10.4)
      Real-report check (46 complaints from the 5 test repos' v10.3 reports, at the graded commits): first version
      dropped 1, wrongly (a port read as a line number). Improved to read how reports really name code
      (Class.method(), Class::method(), Class's, line lists, C++/Kotlin/Java definitions, a subject named in a cited
      file) -> drops 3, all confirmed false by reading the code, none true. tests/test_v10_4_verify_real.py keeps them. For each LLM weakness that names a file / line / function / identifier or says
      something is "missing": check the repo (file exists, line in range, identifier present, the "missing" thing is
      really absent: e.g. grep for timeout/notification/handler near the cited code). Drop or mark unverified claims
      before they reach the report. Log what was dropped (engine log) for review.
- [x] **1b. Code Health without caps.** (done: density per 1,000 lines on cap*d/(d+s), never flat, tuned near Todd's chosen 'middle'; weaknesses name where to fix; dependencies never judged. 5 repos: VibeBuilder 60.5->64.0, echoes 20->31.9, reality-check 65.2->43.7 (small & dense), mx5 84->84 (C/C++ not scanned), winnow 34.5->43.9. Ingest vendor rule fixed with Todd's OK (letsvibe engine-v10.4): bulk-import-and-never-edited only, lib/ & components/ need a manifest/licence, host SDK headers count as libraries; affects all engines' re-grades; AI input still bounded by 12k-token batches x max 6 for 30B-A3B on 8 GB) Score by density (findings per 1,000 lines) on a smooth diminishing curve so
      every real fix moves the score a little; small and large repos are judged alike.
- [x] **1c. Swallowed-error detector understands intent** (done: letsvibe branch engine-v10.4, scan(intent_aware=True); v10.4 uses it. Effect: VibeBuilder 36->27, tiki-karaoke 197->92, echoes 48->43. GAP: C/C++ isn't scanned at all (mx5-dash shows 0) — add later) (`letsvibe/analyzers/code_scan.py`): don't count narrow
      expected exceptions (BlockingIOError, ProcessLookupError, FileNotFoundError in cleanup, CancelledError,
      WebSocketDisconnect, StopIteration...), catches with an explanatory comment, or handlers that log / report /
      re-raise / return an error. Add Rust (`let _ =`, `.ok();`, empty `Err(_) => {}`) and Go.
- [x] **1d. Scores and weaknesses agree.** (done: verify_and_cap() runs right after the factor scores, BEFORE the final grade the narrative is written from; cap 100/95/94/.../90 by remaining weaknesses; real 3rd VibeBuilder report: Functionality 100->93, UI/UX 95->94, total 87.1->85.6) A factor can't be 100 with listed weaknesses: verified weaknesses lower it;
      unverified ones are dropped (1a).
- [x] **1e. Remove the bell curve completely** (letsvibe): ~86 references in 16 live files — `db.py` (`use_curve`, (done, letsvibe e8456e2: score = analysis + Spark bonus everywhere incl. Anna; project-page rank counts Sparks; curve code, script, calibration and README text removed; archived pages kept)
      curve on read; leave the `curved_score` column empty and unused rather than dropping it), `storage/peer_grades.py`,
      `evaluator/pipeline.py`, `evaluator/rubric.py`, `web/server.py`, `web/ui.py`, `dashboard.html`, `anna_routes.py`,
      `anna_db.py`, `scripts/calibrate_curve.py`, `scripts/sync_anna_db.py`, `scripts/benchmark_v9.py`, and the
      peer-grading tests. Raw rubric grade everywhere. **Keep** `templates/pages/archive/...` unchanged (dated legal
      record of past terms/FAQ).
- [x] **1f. Tests** for each of the above with realistic fixtures (a repo with deliberate vs real swallowed errors; a
      report with true and false claims; small vs large repo density), plus the existing suite.
      (done: tests/test_v10_4_full_run.py runs the WHOLE engine on a realistic repo with a fake model and found a real
      1a gap, bare `save()` calls weren't recognised as names; fixed, 46 real claims unchanged: same 3 drops. Engine: 20 tests;
      letsvibe: 20 failures, all pre-existing, none new.)

### 1+. Found reviewing VibeBuilder-IDE-public for the benchmark (added with Todd's OK, 2026-11-23)
Same rules as step 1: v10.4 (testing) only, v10.3 / production results must not change (gate on the engine, prove
it on the 15 benchmark repos). Evidence is the v10.4 report at the pinned commit e2fa52a (2026-11-22).
- [x] **1g. Platforms from what the repo declares** (done 2026-11-23: letsvibe `detect_platforms(declared_targets=True)`, used by v10.4 only; production identical on all 15 benchmark repos. Fixed: VibeBuilder -> linux+android, full-stack-fastapi-template -> web, kilo -> macos+linux, requests/pipreqs -> all three (docs/make.bat is a docs builder; code that branches by OS incl. Windows is cross-platform). Change from the text below: no new "OS not stated" value (it would ripple through filters/UI); instead the fallback narrows only on evidence: Linux-only code, POSIX C includes, Windows-only calls) (`letsvibe/core/platforms.py`, `evaluator/classifier.py`).
      Report says Windows, macOS, Linux, web; truth is Linux + Android. Causes: (1) any Tauri/Electron app is
      assumed to run on all three desktops (`@tauri-apps` in package.json -> PC_PLATFORMS) without reading the
      declared targets: `tauri.conf.json` bundle targets `appimage/deb/rpm` = Linux only (`msi/nsis` = Windows,
      `dmg/app` = macOS, `all`/missing = unknown); Electron: electron-builder targets. (2) Android missed: Tauri
      mobile keeps Kotlin in `src-tauri/android/` (MainActivity, services; `src-tauri/gen/android` when generated),
      no AndroidManifest/Gradle in the repo, and no rule looks there. (3) The fallback "any .py/.go/.rs/.js... file
      -> Windows + macOS + Linux" (Todd's hunch: why Python projects get Windows/Mac) should become "desktop, OS not
      stated" unless something names the OS. README badges / install sections may count as a weak signal only.
- [x] **1h. App type must match the evidence.** (done: the common-app-type match is used only at similarity >= 0.62 and >= 0.02 ahead of the runner-up, measured on the 15 repos; otherwise category 'General Software Project', the model's own description stays the name, and the weak match is no longer fed to the grader; logged) Report calls the IDE an "AI image generator front end" (archetype
      category from the model). The category should agree with the README's own description and the detected
      stack; when it doesn't, fall back to the README's wording / "other" instead of a confident wrong label.
- [x] **1i. Secret scanner false positives** (done: `SecurityAnalyzer.scan(precise=True)`, v10.4 only; production identical on all 15. Also found on the benchmark: a template placeholder `password = "{{ password }}"` (fastapi template) and `eval` inside a bundled minified engine (clumsy-bird's melonJS-min.js). The "password" hit in VibeBuilder was really the rule matching across lines from a comment into later code) (shared analyzer; Nov 12 a scanner change was reverted for side
      effects, so gate it on the engine and compare old vs new on all 15 repos before anything else).
      VibeBuilder's "2 secrets": `tab.handle?.exec("undo")` / `editors.activeFile?.handle?.exec(cmd)` are editor
      commands (a method named exec, not code execution); `server/src/vbide/problems.py:46`
      `# keep "password=", hide the value` is the code that *redacts* passwords. Rules: `obj.exec(` / `?.exec(`
      are method calls; lines that mask/redact/hide a secret, or regex/pattern definitions for one, are not
      hardcoded secrets.
- [x] **1j. Tests** for 1g-1i (done: tests/test_v10_4_declared_facts.py, 18 tests incl. the pinned VibeBuilder commit and real problems still caught; engine suite 43 passed; letsvibe suite: the same 52 failures with and without the change. NOTE: that's up from 20 on 2026-11-21 for an unrelated reason, e.g. badge tests get "not graded": investigate separately) on the pinned VibeBuilder commit plus small fixtures (Tauri Linux-only, Tauri with
      Android sources, plain Python CLI, a real hardcoded password that must still be caught).

### 2. Engine structure (less rebuild fatigue)
- [ ] **2a. One shared core instead of copying the whole engine per version** (20+ version folders, ~27k lines,
      mostly duplicates). Versions keep only what differs (prompts, weights, rules, flags). Parity test per version
      (same inputs -> same outputs as before) so old reports stay reproducible.
- [ ] **2b. One change per experiment**, each with a measured before/after (step 3) and a changelog line with its
      benchmark numbers.

### 3. Benchmark (stop the bias; GPU-heavy, scheduled)
- [ ] **3a. Benchmark set:** 40-60 public repos across categories, languages, sizes and quality, plus the
      letsvibe-good / letsvibe-bad anchors; Todd's own repos at most a few. Half held out (checked only at the end of
      a round) to catch overfitting.
      **Pilot (Todd, 2026-11-23): 15 repos first, 3 of them graded 3x per engine version for consistency**
      (VibeBuilder-IDE-public, winnow-grammar, full-stack-fastapi-template). List + pinned commits + reasons:
      `benchmark/repos.json`. **Clones persist** in `~/storage/letsvibe-benchmark/repos` (desktop) so every engine
      version is graded against the same commits; `python3 benchmark/fetch_repos.py --verify` before each run.
      Delete the store only when the whole plan is 100% done. Todd's repos are pinned to the commit their existing
      report graded (free baseline). Languages: Python, JS, TS, Go, C, C/C++, Rust, Kotlin; sizes tiny-large.
- [ ] **3b. Pair-labelling tool** (local web page): "which of these two is better at X?" for each factor; ratings via
      Bradley-Terry/Elo. Labels decided before the engine sees the repos.
- [ ] **3c. Runner:** grades the set with a chosen engine version through the gpu-scheduler overnight (~3 LLM passes
      per repo, ~3-6 min each with --cpu-moe, ~3-5 h for 50); caches scans/context per commit; a 15-repo quick set
      (~1 h) for daytime checks.
- [ ] **3d. Report per engine version:** ranking agreement with labels, pair accuracy, run-to-run consistency (the
      existing consistency endpoint), and slices by language / size / category / stars. Rule: keep a change only if
      the whole improves and no slice gets worse.

### 4. "Compare it with your own AI" (community, no cost to Todd, privacy intact)
- [ ] **4a. Public download** of the benchmark: the public repo list, LetsVibe's scores, and every claim with its
      file/line references, plus the method.
- [ ] **4b. Submission path:** a GitHub issue template on letsvibe-engine ("Engine finding": repo, claim, right/wrong,
      evidence file+line+quote, the model and settings used); later maybe a signed-in, rate-limited form on the site.
- [ ] **4c. A page explaining it:** anyone may compare LetsVibe with the model of their choice on their own time and
      submit findings; findings are reviewed by Todd, never change scores directly, and confirmed ones become
      benchmark labels or test cases. Only public repos; nothing leaves Todd's machine.

## Order
1 (no GPU, fixes what was actually seen) → 3 (so later changes are measured) → 4 → 2 (whenever refactoring
feels better than tuning; 2a could also come first if the copies get in the way).

## Questions / notes for Todd
-

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
- [x] **1a. Claim verifier.** (done: v10_4_verified/verify.py, tests/test_v10_4_verify.py; branch engine-v10.4) For each LLM weakness that names a file / line / function / identifier or says
      something is "missing": check the repo (file exists, line in range, identifier present, the "missing" thing is
      really absent: e.g. grep for timeout/notification/handler near the cited code). Drop or mark unverified claims
      before they reach the report. Log what was dropped (engine log) for review.
- [ ] **1b. Code Health without caps.** Score by density (findings per 1,000 lines) on a smooth diminishing curve so
      every real fix moves the score a little; small and large repos are judged alike.
- [ ] **1c. Swallowed-error detector understands intent** (`letsvibe/analyzers/code_scan.py`): don't count narrow
      expected exceptions (BlockingIOError, ProcessLookupError, FileNotFoundError in cleanup, CancelledError,
      WebSocketDisconnect, StopIteration...), catches with an explanatory comment, or handlers that log / report /
      re-raise / return an error. Add Rust (`let _ =`, `.ok();`, empty `Err(_) => {}`) and Go.
- [ ] **1d. Scores and weaknesses agree.** A factor can't be 100 with listed weaknesses: verified weaknesses lower it;
      unverified ones are dropped (1a).
- [ ] **1e. Remove the bell curve completely** (letsvibe): ~86 references in 16 live files — `db.py` (`use_curve`,
      curve on read; leave the `curved_score` column empty and unused rather than dropping it), `storage/peer_grades.py`,
      `evaluator/pipeline.py`, `evaluator/rubric.py`, `web/server.py`, `web/ui.py`, `dashboard.html`, `anna_routes.py`,
      `anna_db.py`, `scripts/calibrate_curve.py`, `scripts/sync_anna_db.py`, `scripts/benchmark_v9.py`, and the
      peer-grading tests. Raw rubric grade everywhere. **Keep** `templates/pages/archive/...` unchanged (dated legal
      record of past terms/FAQ).
- [ ] **1f. Tests** for each of the above with realistic fixtures (a repo with deliberate vs real swallowed errors; a
      report with true and false claims; small vs large repo density), plus the existing suite.

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

# LetsVibe engine improvement plan

Owner: Todd. Planned with Claude (2026-11-21), rewritten 2026-11-24 to cut everything that isn't an engine fix.
Can be carried out by Claude or agy: tick the boxes and commit after each step, so whoever continues picks up from
the last tick.

## Ground rules (decided)

- **Fully local.** Production grading never uses a paid or remote model (privacy policy). No paid "second judge".
- **No human taste as the yardstick** (Todd, 2026-11-24). Not Todd's, not a community's: that would make one person's
  judgement the curve everyone else's work is graded against. An engine version is judged only on things that are
  true or false: claims checkable in the code, classification (family, platforms, app type), consistency, anchors.
- **Fixes are general**: they help every repo the same way, never tuned to one repo's score.
- **8 GB GPU.** Don't raise the model size, the 32k context, or add multi-run voting (OOM / CPU spill / 3x time).
- **Production v10.3 must not change.** New behaviour is gated to v10.4 (status "testing") and proven identical for
  v10.3 on the benchmark repos. The live site isn't touched until Todd deploys.
- Branch `engine-v10.4` in both repos (letsvibe-engine, letsvibe); never main until verified. A commit per
  sub-step; commit + push per milestone.

## How changes are measured (Todd, 2026-11-24)

- **Small change → the 3-repo quick set**, daytime, ~15 min of GPU for one engine:
  - **VibeBuilder-IDE-public**: does nearly everything (py/ts/rs/svelte; desktop + Android + server + AI agents);
    the widest range of claims. Todd's own repo: the overnight run below guards against tuning to it.
  - **kilo**: small and focused (one 1,355-line C file); exposed the small-program penalties.
  - **winnow-grammar**: the anchor. Right family (library), platforms and app type; no false claims; identical over
    3 runs and stable between versions (v10.3 88.7, v10.4 90.1). It should not move unless a change is meant to
    move it.
  `benchmark/run.py --engines v10.4 --only VibeBuilder-IDE-public kilo winnow-grammar --out <dir>`
- **Big overhaul → one overnight run** of all 15 benchmark repos (v10.3 vs v10.4).
- What to look at (facts only): false claims kept (spot-check against the code), family / platform / app-type
  errors, run-to-run consistency, the anchor's drift, and that v10.3 output is unchanged.
- Benchmark store: `~/storage/letsvibe-benchmark/repos` (15 pinned repos; `benchmark/fetch_repos.py --verify`).
  Delete it only when this plan is done.

## Done

- **1a-1f** (2026-11-21): claim verifier (drops claims the code disproves); Code Health by density without caps;
  intent-aware swallowed errors (+Rust, Go, C/C++); a factor can't be perfect while listing weaknesses; bell curve
  removed everywhere (letsvibe e8456e2); realistic tests.
- **1g-1j** (2026-11-23): platforms from declared build targets (VibeBuilder -> Linux + Android); app type only for a
  clear match; secret-scanner false positives (exec methods, comments, template placeholders, minified vendor files).
- **Benchmark**: 15 pinned repos + runner `benchmark/run.py` (website's v10 path, results to files only, resumable,
  GPU app `letsvibe_bench`). Night 1 (2026-11-23, 42 runs, no errors, repeats identical): v10.4 dropped kilo 64->41,
  pipreqs 81->60, mx5-dash 69->60.
- **Code facts** (2026-11-24, dbb0095): "there is no X" claims and checklist answers checked against the code
  (flag help, usage text, error/success messages, file writes, checked file opens); Code Health fair to small
  programs. 3-repo re-run: kilo 48.6, pipreqs 67.1, mx5-dash 64.1.

## To do (in order)

- [ ] **1. Claim checker reads whole functions.** A line like `return func() ...` / `return foo(x)` was taken for a
      new function definition, so the checker read only a function's first line and kept false claims (glow:
      "no error handling for file reading in loadLocalMarkdown", handled at ui/stash.go:848). Affects Go, Python,
      Kotlin, Rust. Quick set.
- [ ] **2. Right rubric family.** The family picks the checklist questions, so a wrong one makes every factor wrong:
      requests (a library) is graded as a GUI app ("No UI elements" weaknesses), commander.js (a library for CLIs)
      and kilo (an interactive editor) as CLI tools. Decide the family from evidence (what the repo ships and how
      it is used: package exports, entry points, UI code, README usage) and log why. Big change: quick set, then
      one overnight run.
- [ ] **3. Contradictory checklist answers.** The prompt allows `is_default_prompt_clone: true` only with
      TIER_1; kilo got TIER_2 + clone. A contradiction is resolved by the rule the prompt states, logged. Quick set.
- [ ] **4. Platforms when a repo ships both `start.bat` and `start.sh`** (letsvibe-good: "Windows, web"): both
      launchers = every desktop, not Windows. Quick set (production identical, as in 1g).
- [ ] **5. One shared engine core** (later, whenever copying gets in the way): 20+ version folders, ~27k lines,
      mostly duplicates; versions keep only what differs. Parity test per version (same inputs -> same outputs).

## Cut (2026-11-24)

- Pair labelling (human labels) — against the no-human-taste rule.
- Growing the benchmark to 40-60 repos with a held-out half, ranking/pair-accuracy reports, slices by
  language/size/stars, invariance and planted-defect tests — the 15 repos + facts-only checks are enough.
- "One full benchmark per experiment" — replaced by the 3-repo quick set.
- Public benchmark download, issue template, "compare with your own AI" page — community extras, not engine fixes.

## Known, unrelated

- letsvibe test suite: 52 failures on engine-v10.4 (20 on 2026-11-21), same with and without the engine work, e.g.
  badge tests get "not graded". Investigate separately.

"""v10.4 claim checker, against the real weaknesses LetsVibe v10.3 wrote about VibeBuilder-IDE-public (three
reports), on a repo whose code mirrors the relevant parts of VibeBuilder, plus planted false claims and true claims
that must survive."""

from pathlib import Path

from letsvibe_engine.versions.v10_4_verified.verify import RepoIndex, check_claim, verify_claims

TUNNEL_RS = """use std::time::Duration;
use tokio::process::Command;

impl Tunnels {
    pub async fn adb_connect(&self) -> Result<(), String> {
        let run = Command::new("adb").arg("start-server").output();
        match tokio::time::timeout(Duration::from_secs(10), run).await {
            Err(_) => return Err("adb start-server didn't finish within 10 seconds".into()),
            Ok(Err(e)) => return Err(format!("couldn't run adb: {e}")),
            Ok(Ok(_)) => {}
        }
        self.listen("adb", 5037).await
    }

    pub async fn gui_start(&self, run_id: &str) -> Result<String, String> {
        if !run_id.chars().all(|c| c.is_ascii_alphanumeric() || c == '-') || run_id.len() > 30 {
            return Err("bad run id".into());
        }
        let sock = format!("/run/user/1000/vb-wp-{run_id}.sock");
        Ok(sock)
    }
}
"""

NET_PY = """import json
import urllib.request


def fetch_index(url):
    return json.load(urllib.request.urlopen(url))


def load_config(path):
    return json.load(open(path))


def save_config(path, data):
    try:
        json.dump(data, open(path, "w"))
    except OSError as exc:
        raise RuntimeError(f"couldn't save {path}: {exc}")
"""


def make_repo(tmp_path: Path) -> RepoIndex:
    (tmp_path / "desktop/src-tauri/src").mkdir(parents=True)
    # Laid out like the real file (~360 lines, adb_connect near line 297), so the AI's line numbers are realistic.
    filler = "".join(f"    fn forward_helper_{i}(&self) -> u16 {{\n        {i}\n    }}\n\n" for i in range(70))
    (tmp_path / "desktop/src-tauri/src/tunnel.rs").write_text(TUNNEL_RS.replace("impl Tunnels {\n", "impl Tunnels {\n" + filler))
    (tmp_path / "server").mkdir()
    (tmp_path / "server/net.py").write_text(NET_PY)
    return RepoIndex(tmp_path)


# The functionality weaknesses from v10.3's first report on VibeBuilder-IDE-public, judged against the current code.
REAL_FALSE = [
    "Missing error handling for `adb` commands in desktop/src-tauri/src/tunnel.rs (line 222)",
    "No validation for `run_id` in gui_start (line 202)",
]
REAL_KEPT = [
    "Hardcoded port 5037 in adb_connect without fallback or configuration (line 222)",  # true (by design, but true)
    "Hardcoded Wayland socket path in gui_start without fallback (line 195)",  # no checkable "missing X"
    "No timeout for `adb start-server` command (line 222)",  # names no function: can't be pinned down, kept
    # From the third report: vague (no file, no function), so they can't be checked and stay.
    "Missing error handling for WebSocket connection failures in PTY socket",
    "Missing error handling for file operations when server is unreachable during rename/delete",
    "Hardcoded 10-minute session timeout without user notification",
    "Missing accessibility labels for interactive elements in UI components",
]


def test_real_report_claims(tmp_path):
    repo = make_repo(tmp_path)
    kept, dropped = verify_claims(REAL_FALSE + REAL_KEPT, repo)
    assert [d.claim for d in dropped] == REAL_FALSE
    assert kept == REAL_KEPT
    adb, run_id = dropped
    assert "adb_connect() in desktop/src-tauri/src/tunnel.rs" in adb.reason and "Err(" in adb.reason
    assert "gui_start() in desktop/src-tauri/src/tunnel.rs" in run_id.reason and "chars().all" in run_id.reason


def test_planted_false_claims_are_dropped_with_the_reason(tmp_path):
    repo = make_repo(tmp_path)
    cases = {
        "Crash in `parse_payload()` in server/handlers.py (line 12)": "isn't in the repo",
        "Unbounded retry loop in tunnel.rs (line 9999)": "has only",
        "`fetchUserData` never handles network errors": "appears nowhere",
        "No timeout when `adb_connect` starts the adb server": "has it",
    }
    for claim, why in cases.items():
        d = check_claim(claim, repo)
        assert d is not None and why in d.reason, (claim, d)


def test_true_claims_survive(tmp_path):
    repo = make_repo(tmp_path)
    for claim in [
        "No timeout in `fetch_index` in server/net.py: a slow server hangs the app",  # really has none
        "`load_config` has no error handling for a missing or corrupt file (server/net.py)",  # save_config has, load_config not
        "Missing validation of the URL passed to `fetch_index`",
        "The adb port 5037 is hardcoded in tunnel.rs (line 12)",
    ]:
        assert check_claim(claim, repo) is None, claim


def test_folder_less_citations_and_missing_repo_files(tmp_path):
    repo = make_repo(tmp_path)
    assert check_claim("Missing error handling in `adb_connect` in tunnel.rs", repo) is not None  # folder omitted: found
    assert check_claim("No validation in `gui_start` in src/missing.rs", repo).reason.startswith("cites `src/missing.rs`")


def test_ports_and_addresses_are_not_line_numbers(tmp_path):
    """Found on a real v10.3 report (letsvibe-reality-check): a port after a colon was read as a line number."""
    repo = make_repo(tmp_path)
    claim = "No fallback for missing Llama server URL (uses default 127.0.0.1:11435) - server/net.py (line 3)"
    assert check_claim(claim, repo) is None
    assert check_claim("Crash at server/net.py:9000 on bad input", repo).reason.startswith("cites line 9000")

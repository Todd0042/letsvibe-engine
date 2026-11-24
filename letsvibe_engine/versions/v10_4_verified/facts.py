"""Code facts (v10.4): things a program can find in the repo, used to catch the model saying the opposite.

Two uses, both only in the repo's favour and only as far as the evidence goes:
  - `disproves(claim, repo)`: a weakness like "no file saving" or "no CLI flag documentation" is dropped when the code
    plainly has it (called by the claim checker, verify.py);
  - `correct_checklist(...)`: a checklist answer the facts contradict is raised to the level the evidence supports
    (never lowered; never to the top level unless the evidence is strong). Every change is returned with its evidence.
Facts only count things that are unambiguous in code: a flag with help text, a message printed to the user, a call
that writes a file. Anything subtler stays the model's call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# --- what counts as evidence ------------------------------------------------------------------------------------
_FLAG_WITH_HELP = [
    re.compile(r"add_argument\([^)]*\bhelp\s*="),                      # argparse (same line)
    re.compile(r"@?(click|typer)\.(option|Option|argument)\([^)]*\bhelp\s*="),
    re.compile(r"\bflag\.(String|Bool|Int|Int64|Uint|Float64|Duration)(Var)?P?\(.*,\s*\"[^\"]{4,}\"\s*\)"),  # Go flag
    re.compile(r"\.Flags\(\)\.\w+P?\(.*,\s*\"[^\"]{4,}\"\s*\)"),       # cobra
    re.compile(r"\.option\(\s*['\"`]-[^'\"`]*['\"`]\s*,\s*['\"`][^'\"`]{4,}"),  # commander / yargs
    re.compile(r"#\[arg\([^)]*\bhelp\s*="),                            # clap
]
_ARGPARSE_ANY = re.compile(r"add_argument\(\s*['\"]-")
# A usage block ("Usage:" text or a docopt docstring) and its option lines: "  -f, --force   Overwrite ..."
_USAGE = re.compile(r"\b[Uu]sage:(\s|$)")
_USAGE_OPTION = re.compile(r"^\s*(-\w,?\s+)?--?[\w-]+(\s+<?[\w-]+>?)?\s{2,}\S{3,}")
# Keys explained on screen in an interactive program ("Ctrl-S = save", "Press q to quit", "HELP: ...")
_KEY_HELP = re.compile(r"[\"'].*\b(ctrl|ctl|alt)[-+ ]?\w\b\s*(=|:|to)\s*\w+|[\"'][^\"']*\bpress \w+ to\b|[\"']HELP:", re.I)

_ERROR_MSG = re.compile(
    r"\bperror\(|fprintf\(\s*stderr|eprintln!|file\s*=\s*sys\.stderr|sys\.exit\(\s*['\"f]|SystemExit\(\s*['\"f]|"
    r"\blog(ger|ging)?\.(error|critical|fatal)\(|console\.error\(|log\.Fatal|Fprint\w*\(\s*os\.Stderr|"
    r"[\"'`][^\"'`]*\b(can't|cannot|could not|couldn't|failed|error|unable to)\b[^\"'`]*[\"'`]", re.I)
_SUCCESS_MSG = re.compile(r"[\"'`][^\"'`]*\b(saved|written|wrote|created|done|success(fully)?|finished|generated|"
                          r"installed|updated)\b[^\"'`]*[\"'`]", re.I)
_PRINTS = re.compile(r"\b(print|printf|fprintf|puts|println|eprintln|echo|console\.\w+|log\.\w+|logger\.\w+|logging\.\w+|"
                     r"\w*[Mm]essage|\w*[Ss]tatus\w*|toast|alert|Fprint\w*|Print\w*|write)\s*!?\(")
_WRITES = re.compile(r"\bfopen\([^)]*,\s*\"[wa]|open\([^)]*,\s*['\"][wa]b?\+?['\"]|O_(WRONLY|RDWR|CREAT)|\.write_(text|bytes)\(|"
                     r"writeFile(Sync)?\(|File::create|fs::write|os\.(WriteFile|Create)\(|localStorage\.setItem|"
                     r"\bINSERT\s+INTO\b|json\.dump\(|\.to_csv\(|FileOutputStream|openFileOutput|DataStore|SharedPreferences",
                     re.I)
# file-open calls, and what counts as checking that one worked
_OPEN_CALL = re.compile(r"(?<![\w.])(fopen|open|File::open|os\.Open|fs\.openSync|fs\.readFileSync)\s*\(")
_OPEN_CHECK = re.compile(r"if\s*\(\s*!\s*\w+\s*\)|==\s*(NULL|nullptr|-1|nil)\b|<\s*0\b|if err != nil|\?\s*;|"
                         r"\.(map_err|expect|unwrap_or\w*)\(|\bexcept\b|\bcatch\b|\.catch\(")


@dataclass
class Facts:
    documented_flags: List[str] = field(default_factory=list)   # "file:line"
    undocumented_flags: List[str] = field(default_factory=list)
    usage_text: List[str] = field(default_factory=list)
    key_help: List[str] = field(default_factory=list)
    error_messages: List[str] = field(default_factory=list)
    success_messages: List[str] = field(default_factory=list)
    writes: List[str] = field(default_factory=list)
    opens_checked: List[str] = field(default_factory=list)
    opens_unchecked: List[str] = field(default_factory=list)

    def summary(self) -> Dict[str, Any]:
        return {k: v[:3] + ([f"+{len(v) - 3} more"] if len(v) > 3 else []) for k, v in self.__dict__.items() if v}


def _is_comment(line: str) -> bool:
    s = line.lstrip()
    return s.startswith(("//", "#", "*", "/*", "--")) and not s.startswith("#[")


def _call_text(ls: List[str], i: int) -> str:
    """From line i to the parenthesis that closes the first call on it (at most 8 lines)."""
    text = "\n".join(ls[i:i + 8])
    start = text.find("(")
    depth = 0
    for j in range(start, len(text)):
        depth += {"(": 1, ")": -1}.get(text[j], 0)
        if depth == 0:
            return text[:j + 1]
    return text


# Not the program itself: bundled minified libraries (clumsy-bird's melonJS-min.js "saves files") and development
# tooling (mx5-dash's tools/flash_esp32.sh "Ctrl+C to exit" is the flasher's message, not the dashboard's screen).
_NOT_PROGRAM = re.compile(r"[.-]min\.(js|css)$|(^|/)(vendor|third_party|node_modules|tools|scripts|build|ci|\.github)/", re.I)


def gather(repo) -> Facts:
    """Scan the repo's code files once (RepoIndex from verify.py)."""
    cached = getattr(repo, "_facts", None)
    if cached is not None:
        return cached
    f = Facts()
    for rel in (r for r in repo.code_paths() if not _NOT_PROGRAM.search(r)):
        ls = repo.lines(rel)
        in_usage = 0
        for i, line in enumerate(ls):
            at = f"{rel}:{i + 1}"
            # usage text lives in docstrings and strings, so check it before skipping comments
            if _USAGE.search(line):
                f.usage_text.append(at)
                in_usage = 40
            elif in_usage:
                in_usage -= 1
                if _USAGE_OPTION.search(line):
                    f.documented_flags.append(at)
            if _is_comment(line):
                continue
            if _KEY_HELP.search(line):
                f.key_help.append(at)
            if any(p.search(line) for p in _FLAG_WITH_HELP):
                f.documented_flags.append(at)
            elif _ARGPARSE_ANY.search(line):  # help= may be on the next lines of the same call
                (f.documented_flags if re.search(r"\bhelp\s*=", _call_text(ls, i)) else f.undocumented_flags).append(at)
            if _PRINTS.search(line) or "raise SystemExit" in line or "sys.exit(" in line:
                if _ERROR_MSG.search(line):
                    f.error_messages.append(at)
                elif _SUCCESS_MSG.search(line):
                    f.success_messages.append(at)
            elif re.search(r"\bperror\(|eprintln!|log\.Fatal", line):
                f.error_messages.append(at)
            if _WRITES.search(line):
                f.writes.append(at)
            m = _OPEN_CALL.search(line)
            if m and not re.search(r"\bdef |\bfn |function ", line):
                before = ls[max(0, i - 12):i]
                in_try = any(re.match(r"\s*(try\s*[:{]|try$)", b) for b in before) or "try" in line
                after = "\n".join(ls[i:i + 5])
                (f.opens_checked if (in_try or _OPEN_CHECK.search(after)) else f.opens_unchecked).append(at)
    f.documented_flags = list(dict.fromkeys(f.documented_flags))
    repo._facts = f
    return f


# --- weaknesses the facts disprove --------------------------------------------------------------------------------
# A claim is dropped only if it is ONLY about the thing the facts show: "No error handling (file open, memory alloc)"
# is half true when file opens are checked and allocations aren't, so it stays. Every word of the claim (cited files
# and lines aside) must be one of the topic's words or a filler word.
_FILLER = set("""no not missing lack lacks lacking without absent any the a an for of in on or and to with by from its
there is are has have doesn't does provide provided offer offers cli command line features feature support program app
tool user users clear proper basic""".split())
_TOPIC = {
    "help": set("""flag flags option options argument arguments documentation documented undocumented doc docs help string
                strings text usage message messages info information description descriptions explanation explanations
                output""".split()),
    "saving": set("file files saving save saves saved persistence persist persistent work data disk state".split()),
    "errmsg": set("""error errors message messages failed failure failures operations operation shown displayed reported
                  feedback visual visible mechanism mechanisms action actions status""".split()),
    "fileopen": set("""error errors handling handled unhandled check checks checking checked unchecked file files open opening
                    opens opened operations operation failures failure""".split()),
}


def _only_about(claim: str, topic: str) -> bool:
    text = re.sub(r"\([^)]*\b(line|\.\w{1,4}\b)[^)]*\)", " ", claim.lower())  # "(kilo.c line 392)"
    text = re.sub(r"[\w./-]+\.\w{1,4}(:\d+)?|\blines?\s+\d+", " ", text)  # file names and line numbers
    words = re.findall(r"[a-z']+", text.replace("-", " "))
    return all(w in _FILLER or w in _TOPIC[topic] for w in words)


_NO = r"\b(no|missing|lacks?|lacking|without|absent|doesn't (have|provide|offer)|does not (have|provide|offer))\b"


def disproves(claim: str, repo) -> Optional[str]:
    """A reason when the code plainly contradicts an absolute "there is no X" claim, else None."""
    c = claim.lower()
    if not re.search(_NO, c):
        return None
    f = gather(repo)
    if re.search(_NO + r"[^.;]{0,40}\b(cli|command[- ]line)?\s*(flag|option|argument)s?\b[^.;]{0,20}\b(doc|help|description|explanation)"
                 r"|" + _NO + r"[^.;]{0,30}\b(--help|help (text|strings?|output|message)|usage (text|message|info))", c) \
            and _only_about(claim, "help"):
        if len(f.documented_flags) >= 2 and not f.undocumented_flags:
            return f"says flags/help are undocumented, but {len(f.documented_flags)} flags have help text ({f.documented_flags[0]})"
        if f.usage_text and (f.key_help or len(f.documented_flags) >= 2):
            return f"says there is no help/usage, but the program prints usage ({f.usage_text[0]})" + \
                (f" and shows its keys on screen ({f.key_help[0]})" if f.key_help else "")
    if re.search(_NO + r"[^.;]{0,30}\b(file sav\w*|sav(e|ing)( files?| work| feature| function\w*)?|persist\w*)\b", c) \
            and _only_about(claim, "saving"):
        if f.writes:
            return f"says there is no saving, but the code writes files ({', '.join(f.writes[:2])})"
    if re.search(_NO + r"[^.;]{0,20}\berror messages?\b", c) and _only_about(claim, "errmsg"):
        if len(f.error_messages) >= 3:
            return f"says there are no error messages, but {len(f.error_messages)} places tell the user ({f.error_messages[0]})"
    # "No (visual) feedback for user actions": messages telling the user what happened (errors and confirmations)
    if re.search(_NO + r"[^.;]{0,20}\bfeedback\b", c) and _only_about(claim, "errmsg"):
        told = f.error_messages + f.success_messages
        if len(told) >= 3:
            return f"says there is no feedback, but {len(told)} places tell the user what happened ({told[0]})"
    if re.search(r"\b(error[- ]handling|check\w*|handl\w*)\b[^.;]{0,30}\bfile[- ]?open|\bfile[- ]?open\w*[^.;]{0,30}\b(error|check|handl)", c) \
            and re.search(r"\b(missing|no|lacks?|without|unchecked|unhandled)\b", c) and _only_about(claim, "fileopen"):
        if f.opens_checked and not f.opens_unchecked:
            return f"says file opens are unchecked, but all {len(f.opens_checked)} are checked ({f.opens_checked[0]})"
    return None


# --- checklist answers the facts contradict -----------------------------------------------------------------------
@dataclass
class Correction:
    category: str
    field: str
    was: Any
    now: Any
    evidence: str


def _raise(answers: Dict[str, Any], fld: str, choices: Dict[Any, float], to: Any, evidence: str,
           cat: str, out: List[Correction]) -> None:
    """Set fld to `to` only if that scores higher than the current answer."""
    if fld not in answers:  # only answers the model gave are corrected (an unanswered field already scores the middle)
        return
    cur = answers.get(fld)
    key = cur.strip().upper() if isinstance(cur, str) else cur
    if to not in choices or (key in choices and choices[key] >= choices[to]):
        return
    answers[fld] = to
    out.append(Correction(cat, fld, cur, to, evidence))


def correct_checklist(checklist: Dict[str, Any], table: Dict[str, Dict[str, Any]], repo) -> List[Correction]:
    """Raise checklist answers that the code facts contradict. `table` is the family's points table (rubric.FAMILY_POINTS
    [family]); only fields that exist in it are touched. Changes `checklist` in place; returns what changed and why."""
    f = gather(repo)
    out: List[Correction] = []
    fully_documented = len(f.documented_flags) >= 3 and not f.undocumented_flags
    no_flags_but_explained = not f.documented_flags and not f.undocumented_flags and f.usage_text and f.key_help
    some_documented = len(f.documented_flags) >= 2

    ui = checklist.get("ui_ux") if isinstance(checklist.get("ui_ux"), dict) else None
    ui_t = table.get("ui_ux", {})
    if ui is not None and "help_and_flag_clarity" in ui_t:
        if fully_documented:
            _raise(ui, "help_and_flag_clarity", ui_t["help_and_flag_clarity"], "CLEAR",
                   f"{len(f.documented_flags)} flags with help text, none without ({f.documented_flags[0]})", "ui_ux", out)
        elif no_flags_but_explained:
            _raise(ui, "help_and_flag_clarity", ui_t["help_and_flag_clarity"], "CLEAR",
                   f"no flags; prints usage ({f.usage_text[0]}) and shows its keys on screen ({f.key_help[0]})", "ui_ux", out)
        elif some_documented or f.usage_text:
            _raise(ui, "help_and_flag_clarity", ui_t["help_and_flag_clarity"], "MIXED",
                   f"usage/help text exists ({(f.documented_flags or f.usage_text)[0]})", "ui_ux", out)
    for fld in ("output_and_error_quality", "error_and_diagnostic_quality"):
        if ui is not None and fld in ui_t and len(f.error_messages) >= 3:
            _raise(ui, fld, ui_t[fld], "SOME", f"{len(f.error_messages)} error messages to the user ({f.error_messages[0]})",
                   "ui_ux", out)

    jr = checklist.get("journey") if isinstance(checklist.get("journey"), dict) else None
    jr_t = table.get("journey", {})
    if jr is not None and "options_have_explanations" in jr_t:
        if fully_documented:
            _raise(jr, "options_have_explanations", jr_t["options_have_explanations"], "ALL_OR_MOST",
                   f"{len(f.documented_flags)} flags with help text, none without ({f.documented_flags[0]})", "journey", out)
        elif some_documented:
            _raise(jr, "options_have_explanations", jr_t["options_have_explanations"], "SOME",
                   f"{len(f.documented_flags)} flags with help text ({f.documented_flags[0]})", "journey", out)

    fn = checklist.get("functionality") if isinstance(checklist.get("functionality"), dict) else None
    fn_t = table.get("functionality", {})
    if fn is not None:
        if "tells_user_about_problems" in fn_t and len(f.error_messages) >= 3:
            _raise(fn, "tells_user_about_problems", fn_t["tells_user_about_problems"], "SOMETIMES",
                   f"{len(f.error_messages)} error messages to the user ({f.error_messages[0]})", "functionality", out)
        if "confirms_success" in fn_t and len(f.success_messages) >= 2:
            _raise(fn, "confirms_success", fn_t["confirms_success"], "SOMETIMES",
                   f"{len(f.success_messages)} success messages ({f.success_messages[0]})", "functionality", out)

    # App / game families (plan 2 put interactive programs here; their questions differ from a CLI's)
    told = f.error_messages + f.success_messages
    for fld in ("feedback_while_working", "input_and_state_feedback"):
        if ui is not None and fld in ui_t and len(told) >= 3:
            _raise(ui, fld, ui_t[fld], "SOME", f"{len(told)} messages telling the user what happened ({told[0]})", "ui_ux", out)
    if jr is not None and "onboarding_and_controls_help" in jr_t and f.key_help:
        _raise(jr, "onboarding_and_controls_help", jr_t["onboarding_and_controls_help"], "BASIC",
               f"shows its controls on screen ({f.key_help[0]})", "journey", out)
    if jr is not None and "state_and_save" in jr_t and f.writes:
        _raise(jr, "state_and_save", jr_t["state_and_save"], "MANUAL_SAVE",
               f"the code saves to files ({f.writes[0]})", "journey", out)
    return out

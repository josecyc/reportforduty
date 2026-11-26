"""Format rules read by a program before anything builds.

A submission is one Lean file. It may hold imports, opens, a namespace, and definitions,
lemmas and theorems with their proofs. Nothing in it may run code while it compiles, so
the rules refuse every command that can: #-commands, macros, syntax, elaborators,
initializers, run_cmd and run_tac, attributes other than simp, string literals, and
options other than a short list of resource limits. Comments are removed before scanning.

These rules are a first line. The checker also runs Lean in a sandbox with no network and
no writes outside a temporary folder, and accepts a proof only if its axioms are the
standard three.
"""
from __future__ import annotations

import re

MAX_BYTES = 512 * 1024

FORBIDDEN_WORDS = [
    # gaps and new axioms
    "sorry", "admit", "axiom", "axioms",
    # running compiled code or trusting the compiler
    "native_decide", "native", "implemented_by", "extern", "unsafe", "opaque", "partial",
    # code that runs while the file compiles
    "macro", "macro_rules", "syntax", "elab", "elab_rules", "notation", "infix", "infixl",
    "infixr", "prefix", "postfix", "initialize", "builtin_initialize", "run_cmd", "run_tac",
    "run_elab", "run_meta", "declare_syntax_cat", "declare_simp_like_tactic",
    "register_option", "register_simp_attr", "register_label_attr",
    # changing how the statement elaborates (keywords; a preceding dot means a name, not a keyword)
    "instance", "class", "structure", "inductive", "deriving", "attribute", "export",
    "prelude", "unif_hint", "add_decl_doc", "omit_lint",
]

# Names that are refused even as part of a dotted name.
FORBIDDEN_NAMES = ["ofReduceBool", "ofReduceNat", "trustCompiler", "sorryAx", "evalExpr",
                   "unsafeCast", "unsafeIO", "unsafeBaseIO", "unsafeEIO"]

HASH_COMMANDS = re.compile(
    r"#(eval|print|check|reduce|exit|guard\w*|synth|help|find|lint|simp|norm_num|conv|where|time|"
    r"adaptation_note|align\w*|leansearch|loogle|moogle|sample|explode|kernel\w*|test|"
    r"count_heartbeats|discr_tree\w*|widget|html|parse|mathlib|in|unused\w*|const\w*|"
    r"min_imports|import\w*|show\w*|tactic\w*|aesop\w*|instances|version|search|stop|"
    r"rw\w*|why\w*|dsimp|whnf\w*|eqns|redundant\w*|check_failure|exact\w*|ratchet|"
    r"defeq\w*|reset\w*|backtrack|refine\w*|split\w*)\b"
)
SET_OPTION = re.compile(r"\bset_option\b")
ALLOWED_SET_OPTION = re.compile(
    r"\bset_option\s+(maxRecDepth|maxHeartbeats|synthInstance\.maxSize|synthInstance\.maxHeartbeats)\s+\d{1,9}\s+in\b"
)
ATTRIBUTE = re.compile(r"@\[([^\]]*)\]")
ALLOWED_ATTRIBUTES = {"simp", "local simp"}
IMPORT = re.compile(r"(?m)^\s*import\s+(\S+)\s*$")


def strip_comments(src: str) -> str:
    """Remove -- line comments and nested /- -/ block comments (doc comments included)."""
    out = []
    i, n, depth = 0, len(src), 0
    while i < n:
        if depth == 0 and src.startswith("--", i):
            j = src.find("\n", i)
            i = n if j == -1 else j
            continue
        if src.startswith("/-", i):
            depth += 1
            i += 2
            continue
        if depth > 0 and src.startswith("-/", i):
            depth -= 1
            i += 2
            if depth == 0:
                out.append(" ")
            continue
        if depth == 0:
            out.append(src[i])
        elif src[i] == "\n":
            out.append("\n")
        i += 1
    return "".join(out)


def check(src_bytes: bytes, allowed_imports) -> tuple[list[str], list[str], str]:
    """Return (refusals, notes, stripped source). allowed_imports(module) -> bool."""
    refusals: list[str] = []
    notes: list[str] = []
    if len(src_bytes) > MAX_BYTES:
        return [f"file is {len(src_bytes)} bytes; the limit is {MAX_BYTES}"], notes, ""
    try:
        src = src_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return ["file is not UTF-8"], notes, ""
    if "\x00" in src:
        return ["file contains a NUL byte"], notes, ""
    body = strip_comments(src)

    if '"' in body:
        refusals.append("string literals are not allowed (rule c: no double quotes)")
    for word in FORBIDDEN_WORDS:
        if re.search(rf"(?<![\w.']){re.escape(word)}(?![\w'!?])", body):
            refusals.append(f"`{word}` is not allowed")
    for name in FORBIDDEN_NAMES:
        if re.search(rf"(?<![\w']){re.escape(name)}(?![\w'])", body):
            refusals.append(f"`{name}` is not allowed")
    m = HASH_COMMANDS.search(body)
    if m:
        refusals.append(f"`{m.group(0)}` is not allowed: no # commands (rule a)")
    n_opts = len(SET_OPTION.findall(body))
    if n_opts != len(ALLOWED_SET_OPTION.findall(body)):
        refusals.append("set_option is allowed only as `set_option <maxRecDepth|maxHeartbeats|"
                        "synthInstance.maxSize|synthInstance.maxHeartbeats> <number> in` (rule d)")
    for attr in ATTRIBUTE.findall(body):
        if attr.strip() not in ALLOWED_ATTRIBUTES:
            refusals.append(f"attribute @[{attr}] is not allowed; only @[simp] and @[local simp] (rule d)")

    imports = IMPORT.findall(body)
    first_code = re.search(r"(?m)^\s*(?!import\b)\S", body)
    last_import = None
    for m in IMPORT.finditer(body):
        last_import = m.end()
    if first_code and last_import is not None and first_code.start() < last_import:
        refusals.append("imports must all come first")
    for mod in imports:
        if not allowed_imports(mod):
            refusals.append(f"import {mod} is not allowed: only Mathlib, ReportForDuty.Defs and "
                            "already merged ReportForDuty.Steps modules")
    if not imports:
        refusals.append("the file has no imports; start from the skeleton the script wrote")
    if any(m == "Mathlib" for m in imports):
        notes.append("imports all of Mathlib; importing only what you use checks faster")
    # de-duplicate, keep order
    seen, uniq = set(), []
    for r in refusals:
        if r not in seen:
            seen.add(r)
            uniq.append(r)
    return uniq, notes, body

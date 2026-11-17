"""Prompt templates for each phase of the single-session state machine.

The prompts are deliberately project-agnostic: Claude classifies the project and picks the
architecture and test strategy itself. The orchestrator only fixes the *process*: requirements
before code, an executable verification contract, root-cause fixes and a final requirements review.
"""

from __future__ import annotations

import json
import re
from typing import Any

from schemas import VerificationReport

ORCH_DIR = ".orchestrator"
REQUIREMENTS_FILE = f"{ORCH_DIR}/requirements.md"
VERIFY_FILE = f"{ORCH_DIR}/verify.json"

REVIEW_VERDICT_RE = re.compile(r"REVIEW_VERDICT:\s*\**\s*(PASS|GAPS_FIXED|GAPS_REMAIN)", re.IGNORECASE)

SYSTEM_PREAMBLE = """You are operating as an autonomous principal software engineer inside a dedicated workspace.
The current working directory is the project workspace. An external orchestrator drives this single
session through phases (plan -> implement -> verify -> fix -> review) and independently runs the
verification gate after you finish each phase. Nobody will answer questions: when something is
ambiguous, choose the most reasonable interpretation, record the assumption in
`.orchestrator/requirements.md`, and keep going."""

ENGINEERING_PRINCIPLES = """Engineering principles (apply them to whatever kind of project this is):
- Deliver a working, runnable product, not a sketch: no placeholders, TODOs, stubs, mock-only logic,
  or "left as an exercise". Every documented feature must actually work end-to-end.
- Derive behaviour from the requirements and from first principles. Never special-case the inputs the
  tests use, and never hardcode expected outputs in place of real computation.
- The ticket and any documents it provides (in the context above or in the workspace) are normative. If
  your memory of a similar existing tool, library or format differs from them, follow the ticket and
  documents. Do not add defaults, options, constants or behaviour that they do not call for; record any
  doubt as an assumption instead of silently "improving" the spec.
- Every concrete example in the ticket or provided documents (an input with its expected output, a
  sample command with its printed result, a byte-level format sample) must become an automated test that
  asserts exactly that output. Compute known-answer test vectors from the written definition, never by
  running your own implementation and copying its output.
- Keep the project self-contained: pin dependencies in the ecosystem's standard manifest
  (requirements.txt / pyproject.toml, package.json, go.mod, Cargo.toml, Makefile, ...), and make the
  test, build and run commands work from a clean checkout of this workspace.
- If the work needs data, assets or network resources that may be unavailable, design for it:
  ship a small deterministic sample/fixture, make the external source optional, and say so in the README.
- Write a README that explains what the project does, how to install, run and test it, and its design.
- Tests must exercise real behaviour: happy paths, edge cases, error handling and (where relevant)
  integration across components, CLI entrypoints or HTTP endpoints."""

VERIFY_CONTRACT_HELP = """The verification contract `.orchestrator/verify.json` tells the orchestrator how to check your work:
```json
{
  "setup": ["<idempotent dependency install command>"],
  "test":  ["<command that runs the full automated test suite>"],
  "build": ["<build / type-check / compile command>"],
  "lint":  ["<optional linter command>"],
  "smoke": [
    {"command": "<command that runs the real program on a sample input and exits>"},
    {"command": "<command that starts a server>", "url": "http://127.0.0.1:<port>/<path>", "timeout_s": 60}
  ]
}
```
Rules: commands are executed from the workspace root WITHOUT a shell (no pipes, `&&`, `cd` or
redirection; write a script if you need one). Every command must exit 0. `test` must contain at least
one real test-suite command. Smoke entries with a `url` are started in the background and pass when the
URL answers with an HTTP status below 500; they are then stopped."""


def _verification_block(commands: list[str] | None) -> str:
    if commands:
        listed = "\n".join(f"- `{c}`" for c in commands)
        return f"The orchestrator's verification gate runs exactly these commands; every one must exit 0:\n{listed}"
    return VERIFY_CONTRACT_HELP


def _constraints_block(constraints: list[str] | None) -> str:
    if not constraints:
        return ""
    lines = "\n".join(f"- {c}" for c in constraints)
    return f"\nNon-negotiable constraints for this task:\n{lines}\n"


def plan_prompt(
    context_payload: str, verification_commands: list[str] | None, workspace: str,
    constraints: list[str] | None = None,
) -> str:
    return f"""{SYSTEM_PREAMBLE}

Workspace: {workspace}

{context_payload}
{_constraints_block(constraints)}
## Phase 1 — Analyze, specify & plan
1. Inspect the workspace (it may be empty, or an existing codebase you must change carefully).
2. Classify the work: what kind of system is this (library, CLI tool, web service/API, full-stack app,
   data/ML pipeline, compiler/interpreter/toolchain, simulation, bug fix in existing code, ...)?
   Pick the language, architecture and test strategy that fit THAT kind of system and the request.
3. Write `{REQUIREMENTS_FILE}` containing:
   - a one-paragraph statement of the product being built;
   - a numbered list of concrete, testable acceptance criteria (R1, R2, ...) covering every
     feature, input/output format, interface and edge case implied by the request and context,
     including every concrete example given in the ticket or in provided documents (read any
     documentation files in the workspace first);
   - assumptions you made about anything ambiguous;
   - the planned test strategy (which criteria are covered by which kind of test).
4. Reply with a concise numbered execution plan: components/files, data flow, risks, and tests.

In this phase you may ONLY create files under `{ORCH_DIR}/`. Do not write application code yet.

{ENGINEERING_PRINCIPLES}"""


def implement_prompt(verification_commands: list[str] | None, constraints: list[str] | None = None) -> str:
    contract = "" if verification_commands else (
        f"\n4. Create or update `{VERIFY_FILE}` so the orchestrator can install, test, build and smoke-run the project.\n"
    )
    return f"""## Phase 2 — Implement & test
Execute your plan and satisfy every acceptance criterion in `{REQUIREMENTS_FILE}`:
1. Implement the complete system.
2. Write comprehensive automated tests mapped to the acceptance criteria (note the R-numbers in test
   names or docstrings).
3. Install dependencies, run the full test suite and the program itself, and fix everything that fails.{contract}
5. Finish with a short summary: what was built, how to run it, tests added, assumptions.
{_constraints_block(constraints)}
{ENGINEERING_PRINCIPLES}

{_verification_block(verification_commands)}"""


def heal_prompt(report: VerificationReport, attempt: int, remaining: int, max_chars: int,
                constraints: list[str] | None = None) -> str:
    return f"""## Fix verification failures (attempt {attempt}, {remaining} turn(s) left after this one)
The orchestrator ran the verification gate independently and it FAILED. Exact output:

{report.failure_digest(max_chars)}

Diagnose the ROOT CAUSE and fix it. Rules:
- Do not delete, skip, xfail or weaken tests to make them pass, and do not special-case test inputs.
- If a test is wrong relative to `{REQUIREMENTS_FILE}`, fix the test and explain why.
- If the failure is in the verification contract itself (wrong command, missing dependency install,
  server/port problem), fix `{VERIFY_FILE}` or the project setup.
- Re-run the failing commands yourself before finishing.
{_constraints_block(constraints)}
Finish with a short explanation of the root cause and the fix."""


def review_prompt(review_index: int, max_reviews: int, constraints: list[str] | None = None) -> str:
    return f"""## Final review against the requirements (review {review_index} of at most {max_reviews})
The verification gate currently PASSES. Passing tests are necessary but not sufficient: now audit the
product against the original request and every acceptance criterion in `{REQUIREMENTS_FILE}`.
1. For each criterion, check the actual code paths and run the real program (CLI, server, pipeline,
   library calls) on realistic inputs — not only the tests.
2. Look for features that are missing, partially implemented, faked, hardcoded or untested; wrong
   input/output formats; poor error handling; missing README/run instructions. Re-read the ticket and
   provided documents line by line: check every default value, constant, format detail and example against
   the code, and remove any behaviour the ticket does not ask for.
3. Fix every gap you find, add tests for it, and re-run the full test suite.
{_constraints_block(constraints)}
End your reply with a checklist (criterion -> status) and then EXACTLY one final line:
`REVIEW_VERDICT: PASS` if everything was already complete and you changed nothing,
`REVIEW_VERDICT: GAPS_FIXED` if you found and fixed gaps, or
`REVIEW_VERDICT: GAPS_REMAIN` if some requirement still cannot be satisfied (explain why)."""


def parse_review_verdict(text: str | None) -> str:
    if not text:
        return "UNKNOWN"
    matches = REVIEW_VERDICT_RE.findall(text)
    return matches[-1].upper() if matches else "UNKNOWN"


def permission_denials_note(denials: list[dict[str, Any]]) -> str:
    if not denials:
        return ""
    shown = []
    for d in denials[:10]:
        name = d.get("tool_name") or d.get("tool") or "tool"
        inp = d.get("tool_input")
        shown.append(f"- {name}: {json.dumps(inp)[:200] if inp is not None else ''}")
    return (
        "\n\nNote: in your previous turn these tool calls were DENIED by the sandbox policy. "
        "Do not retry them; use the permitted tools to achieve the same goal:\n" + "\n".join(shown)
    )

# Benchmark report — pallets/itsdangerous

**Ticket:** [`task.md`](task.md) (SEC-221). It asks for a wire-compatible signing library: Signer, TimestampSigner,
the Serializer family, key derivation, rotation and exceptions. From attempt 3 the workspace also contains
the project's public user documentation (`docs/*.rst`): the documentation a developer would have, not
the source or the tests.

**Reference execution:** the hidden harness [`compare.py`](compare.py):
- freezes time;
- has the reference and the generated package each issue 13 kinds of token, and compares them byte for byte;
- has each implementation verify the *other's* tokens;
- checks error behaviour: tampering, missing separator, wrong key, expiry, bad separator, base64, `loads_unsafe`.

## Score history
| attempt | system | score | cause of the gap |
|---|---|---|---|
| 1 | `86683d9` | 0.96 | **Ticket error:** I wrote that plain `Serializer` emits compact JSON; the reference uses `json.dumps` defaults. |
| 2 | `c8787c2` | 0.71 | **System weakness:** the generated `Serializer` silently added `default_signer_kwargs={"key_derivation": "hmac", ...}`. Neither the ticket nor the reference has it; it looks like recalled Flask session-cookie configuration. Its own known-answer tests were derived from the implementation, so they passed. |
| 3 | `7c307c4` | **1.00** | – |

**Generic system fix triggered (in `prompts.py`):**
- The ticket and provided documents are normative over the model's memory of similar tools.
- No undocumented defaults, options or constants.
- Every concrete example becomes an exact-output test.
- Known-answer vectors are computed from the written definition, never copied from the implementation.
- The review turn re-checks every default and constant against the ticket.
- Tests: `tests/test_phases.py::test_prompts_make_spec_normative_and_examples_tests`.

**Process (attempt 3):** 4 turns on one session. $0.68 (corrected). All 52 checks pass, including token-level
interoperability in both directions.

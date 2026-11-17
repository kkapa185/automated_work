# Benchmark report — chrislgarry/Apollo-11

**What "executing" this repo means:** the repository contains the Apollo 11 guidance-computer flight
software: Comanche055 for the Command Module and Luminary099 for the Lunar Module, as AGC assembly source
transcribed from the original YUL listings. Running it means **assembling it into the core-rope memory
image** that flew.

**Ticket:** [`task.md`](task.md) (AGC-42). It asks for an AGC Block II assembler covering the instruction
set, pseudo-ops, interpretive language and `BNKSUM`, and defines the `.binsource` output format. The
system received the two programs' sources from this repo as input data and was forbidden to consult
Virtual AGC sources or listings.

**Reference execution / ground truth:** Virtual AGC's proof-read octal listings of the real ropes
(`Comanche055.binsource`, `Luminary099.binsource`). They were checked word by word against the printed
1969 YUL listings, and are read here as data only. (Compiling Virtual AGC's own `yaYUL` assembler was
blocked by the session's safety policy, because that repository was not one the user named; it was not
needed.) The hidden harness [`compare.py`](compare.py) assembles both programs with `./agcasm` and
compares all 36 banks × 1024 words.

## Result (attempt 1, system `86683d9` → resumed on `7092346`): score 0.98
| program | used words identical | banks exactly identical | symbols | assembles |
|---|---|---|---|---|
| Comanche055 (CM) | 35,819 / 36,598 (97.9%) | 0 / 36 | 7,220 | yes, about 1 s, 0 errors |
| Luminary099 (LM) | 35,948 / 36,640 (98.1%) | 0 / 36 | 7,105 | yes, about 1 s, 0 errors |

A Python assembler of about 2,000 lines, with 7 test modules, was written from the ticket alone.

**Where the 2% comes from** (my analysis using the hidden ground truth, *not* fed back to the system):
- About 40% of the mismatching words are one systematic encoding error. The downlink-list pseudo-ops
  (`DNPTR`, `1DNADR`–`6DNADR`, `DNCHAN`) place their count field one bit too high (reference `32043`,
  generated `62043`).
- Most of the rest are a handful of interpretive-language opcode encodings (`SL1`, `SR1`, `SL2`, `DMP`,
  `DOT`, `DAD`, ...).
- Each bank's checksum word then differs as a consequence, which is why no bank is exact even though
  99%+ of most banks match.
- The ticket required YUL-exact encodings but could not specify every opcode. The system reconstructed
  them from domain knowledge with no oracle available, and got these few wrong.

**Notable behaviour:**
- The assembler copes with real inconsistencies in the repo's transcription. Examples: an undefined
  `ZEROEROR` resolves to `ZEROERROR`; an include named `LAMBERT_AIMPOINT_GUIDANCE.agc` is mapped to the
  file that actually exists. Each case emits a precise `file:line` warning.

**Process:** 4 turns on one session (`85118644…`): plan → implement → review (GAPS_FIXED) → review (PASS).
**$11.27**; that figure was first reported as $33.29 before the cumulative-cost bug fix. Wall time was about
6 h, including a **2 h 48 min automatic pause** on the 5-hour usage limit and a worker restart.

**System lessons and changes triggered by this run:**
1. **Usage limits in production:** the 5-hour limit was hit mid-implementation. The task detected
   `You've hit your 5-hour limit · resets 4:20pm (UTC)`, persisted `resume_at=16:22`, and the same turn
   continued on the same session after the reset. It survived the worker process being killed in between.
2. **Runner/daemon:** in-flight tasks are always resumed on their session, never re-attempted.
   `runner.py daemon` is the idempotent supervisor.
3. **Cost accounting bug:** the CLI's `total_cost_usd` is cumulative per session. It is now stored as
   per-turn deltas.
4. **Heartbeats:** implementation turns can run 30+ minutes, so workspace-activity heartbeats are now
   published during turns.

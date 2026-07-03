---
description: Run ICCAD testcases through the LLM agent and validate the results. Use when asked to run, rerun, sweep, or benchmark testcases, or to check the current score.
argument-hint: "[case-number | from-to | all]"
---

# run-sweep

Drives `testcase/testNN/prompt.txt` through the live LLM agent via
`scripts/run_all_llm.py` (pipes each prompt line into
`python3 main.py -config <config>`, parses the `#RESPONSE`/`#END` transcript).

## Cost checkpoint — read first

A full 40-case sweep costs real API tokens and takes ~50-65 min on haiku.
**After any code change, run the canary, not the full sweep:**

```
python3 scripts/run_all_llm.py --case 2
```

~12s. Expect status `OK` and a nonzero token column. Only sweep all 40 when
the user explicitly asks for a full sweep.

## Commands

- `--case N` — single case
- `--from A --to B` — range
- (no args) — all 40
- `--config <path>` — provider switch; `config.yaml` has
  `provider: "anthropic"` or `"openai"`. NOTE: the OpenAI key currently has
  no quota — expect `APIERR` until the user fixes billing.
- `--timeout N` — per-case timeout in seconds (default 600).

## Status legend (from run_all_llm.py)

- `OK` — all turns answered AND `testNN_out.v` was written.
- `OK*` — all turns answered but NO `out.v` — investigate, usually fabrication.
- `APIERR` — provider failure (bad key/quota/rate-limit); sweep **aborts**
  remaining cases automatically.
- `PARTIAL` — ran out of turns / stopped early.
- `TIMEOUT` — per-case timeout hit. `ERR` — main.py exited nonzero.
  `CRASH` — the harness itself raised.

Token/call counts come from `[TOKENS] ... total=N ... api_calls=M` on stderr;
`0 tok` with an otherwise-OK status is itself suspicious.

## Mandatory follow-up

A sweep result is never the score. Afterward always run:

```
python3 scripts/check_results.py --all
```

Report **both** numbers: the sweep status summary and the checker's
`N/40 cases with no hard-requirement failure` line. Optionally also
`python3 scripts/eval_harness.py` for ground-truth-free goal predicates.

## Sanity checks

- test12 legitimately takes ~10 min (path enumeration) — not a hang.
- A big case finishing in seconds, every case sharing one status, or
  identical timings = suspect a stale provider failure or stale artifacts.
- The sweep deletes each case's previous `testNN_out.v` itself before
  running, so a fresh `OK` reflects only this run.

## Do not

Never edit files under `src/` or `main.py` while a sweep runs — each case
spawns a fresh `main.py` from the current tree; in-flight edits can corrupt
or invalidate a running sweep.

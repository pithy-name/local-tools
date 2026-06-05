# json-redact

> **Status:** v0.1 — early and experimental.
>
> **Caveat emptor:** curated-list redaction misses anyone you didn't list. A
> human review of the output is mandatory before it leaves your machine —
> especially before feeding a cloud RAG. No tool gives a guarantee.

Local, deterministic PII redaction for **single-document JSON** work notes.
Swaps a curated list of names/orgs/emails for stable pseudonyms
(`[PERSON_A]`), preserving valid JSON. Built to sanitize notes before feeding
a Claude cloud RAG. No network calls.

## How it works

- `json_redact.py` (stdlib only) — reads your `mappings.json`, walks each JSON
  file's string **values**, applies the swaps, writes valid JSON to
  `<input>/redacted/`. Keys, numbers, structure untouched. Originals never
  modified. **Non-JSON files are NOT copied to output** (an unredacted PDF in a
  folder named `redacted/` would look safe and isn't).
- `json_scan.py` (advisory) — local spaCy+Presidio scan that prints candidate
  names/orgs/emails so you can seed `mappings.json`. Suggestion engine only.

## Technical usage

```bash
# 1. (optional) surface candidates to curate — needs the redaction-tool venv
../redaction-tool/.venv/bin/python json_scan.py /path/to/notes

# 2. build mappings.json (copy the example, edit)
cp mappings.example.json mappings.json

# 3. preview — writes nothing
python3 json_redact.py /path/to/notes --mappings mappings.json --dry-run

# 4. redact — output to /path/to/notes/redacted/
python3 json_redact.py /path/to/notes --mappings mappings.json

# 5. EYEBALL the output, then feed it to the RAG
```

## mappings.json

A JSON array of `{find, replace}`. `find` is a literal string; `replace` is a
stable pseudonym. Matching is case-insensitive, word-boundary, longest-first.

```json
[
  {"find": "Alice Chen", "replace": "[PERSON_A]"},
  {"find": "alice.chen@example.com", "replace": "[EMAIL_A]"}
]
```

## Limits (read these)

- Misses anyone not in your list — scan + human review are the only safety nets.
- Common-word names (`Will`, `Mark`) also redact the everyday word (leak-averse
  by design — annoying, not dangerous).
- PII stored as a JSON number is not matched (list it as a string).
- Output JSON is re-indented; data is identical, layout may differ.
- `json_scan.py` output is REAL PII — keep it out of git.
- Single-document JSON only; JSON Lines (NDJSON) is not supported.

## Walkthrough for non-technical users

1. Open Terminal and go to this folder.
2. (Optional) Find names to redact: run the scan command in step 1 above. It
   prints a list of names/emails it noticed. **This list is real private info —
   don't save or share it.**
3. Make your replacement list: run `cp mappings.example.json mappings.json`,
   then open `mappings.json` and add a line for each name to hide. Left side is
   the real text; right side is the codename that replaces it.
4. Preview: run the `--dry-run` command in step 3. It shows how many times each
   name would be swapped, without changing anything.
5. Run for real: the command in step 4. A new `redacted/` folder appears next to
   your notes with the cleaned copies. Your originals are untouched.
6. **Read the redacted files yourself** before sending them anywhere. The tool
   only swaps the names you listed — anything you forgot is still there.

## Testing

```bash
cd tools/json-redact
python3 -m unittest discover -s tests -v
```

`test_json_redact.py` fully covers the stdlib redactor. `test_json_scan.py`
covers the scanner's JSON-walk/dedup logic with an injected fake analyzer; the
real spaCy path is exercised manually (needs the redaction-tool venv).

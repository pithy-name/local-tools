Selective URL redaction on keyword-redacted output folders, one folder at a time, finishing each before starting the next.

Follow the rules in the separate rules file, selective-url-redaction-rules.md, which is supplied with this prompt. Read it in full before doing anything, and follow it exactly: its procedure, gates, token rules, display text rule, matching, scope, write safety, verification, document formats and pre-decided tokens. If anything in this prompt seems to conflict with it, stop and ask.

FOLDERS
For each folder: the output folder is the only place you may write to, and only after my explicit green light naming the files. The URL inventory lists every URL found in that output folder as "<full URL> ×<hits>", under a header "N unique · M hits".
1. Output folder: <path>   URL inventory: <path>
2. Output folder: <path>   URL inventory: <path>

WHERE YOUR FILES GO
- Documents (domain, dry-run, file dry-run report): <local folder outside the output folders>
- Backups before any write: <durable local folder>

Start now with folder 1: do step 1 of the rules' procedure, then step 2, and stop at its gate.

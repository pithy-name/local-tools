# Selective URL redaction — rules

Rules and procedure for redacting **only chosen URLs** in a folder of documents that has already been through keyword redaction. Private links (internal tools, work chat, internal documents) are replaced by a short token naming the service; public links (talks, articles, vendor pages) are left as they are.

This document is self-contained. Everything needed to run the procedure, build its documents and verify the result is described here.

---

## 1. When to use this

You have a folder of exported documents (HTML, CSV, Markdown) that a keyword-redaction pass has already processed, and you want some of the URLs in it redacted, but not all of them. Automatic entity recognition can't tell a private link from a public one, so the choice is made by a person, host by host and path by path. It is then applied as a separate, approval-gated pass.

**Inputs**

| Input | Description |
|---|---|
| Output folder | The keyword-redacted folder. This is the only folder the procedure may write to. |
| URL inventory | A report listing every URL found in the output folder with its hit count, one per line as `<full URL> ×<hits>`, under a header giving the totals as `N unique · M hits`. Produce it by running URL detection over the **output folder** (not the originals) without writing anything. |

**Never the originals.** The originals are the keyword pass's input and still contain real names. Their layout also differs from what an HTML parser writes back, so editing them would reformat every touched file.

---

## 2. Procedure

Every gate is mandatory. "Wait" means stop and wait for the reviewer's reply.

| Step | Who | What | Gate |
|---|---|---|---|
| 1 | Operator | Read the URL inventory. Check that the listed URLs add up to the header's `N unique · M hits`. | — |
| 2 | Operator | Write the **domain document** (§9.2): every URL grouped by host (and by host + path prefix where the token differs), each group with its proposed token or `unchanged`, split into REDACT and KEEP. | Wait for rulings. Write no data file. |
| 3 | Reviewer | Rules on each row: redact with a given token, or leave unchanged. **Rows the reviewer doesn't mention are agreed with the proposed token or `unchanged`.** They are not open questions. | — |
| 4 | Operator | Write the **dry-run document** (§9.3): every URL to be replaced, alphabetical by full URL, with its token and hits, plus the unchanged list. Revise it in place for each change the reviewer asks for. | Wait for approval. |
| 5 | Operator | **File dry run** (§9.4): apply the approved table in memory to the output folder and report every change per file. Write nothing to the folder. | Wait for an explicit green light. |
| 6 | Reviewer | Gives an **explicit green light that names the files**. It may cover a few files at a time. | No green light, no write. |
| 7 | Operator | Write the named files only (§7). | — |
| 8 | Operator | Verify on disk (§8) and report per file. | Not done until verification passes. |

---

## 3. Token rules

| Rule | Detail |
|---|---|
| Format | `[<Service> URL]`, for example `[Notion URL]`, `[Google Sheets URL]`, `[Jira URL]`. |
| Title Case | Every token is in Title Case. Product names keep their own spelling (`GitLab`, `TestRail`). No lowercase tokens. |
| Always cite the service | Never a plain `[URL]`, **including inside link targets (`<a href>`)**. Some redaction tools write a plain `[URL]` into link targets; this procedure doesn't. |
| Default token | The service name: `[Notion URL]`, `[Slack URL]`, `[Atlassian URL]`. Hosts of the same service share a token (`acmeinc.slack.com` and `app.slack.com` → `[Slack URL]`). |
| Path-specific tokens | Use them where the path says what kind of page it is (Jira issue vs filter vs sprint report; Google Docs vs Sheets vs Slides). Match on **host + path prefix**, never host alone: one host can serve several kinds of page. |
| Where it applies | Everywhere the URL appears: HTML text, `<a href>` values, CSV cells, Markdown text. |

---

## 4. Display text rule

A link's display text is **kept**, and the token is **appended** after it. A link whose display text *is* the URL shows the token alone, because keeping that text would keep the URL.

| Before | After |
|---|---|
| `<a href="https://acmeinc.atlassian.net/browse/DEV-1">Login bug</a>` | `<a href="[Jira URL]">Login bug [Jira URL]</a>` |
| `<a href="https://acmeinc.atlassian.net/browse/DEV-1">https://acmeinc.atlassian.net/browse/DEV-1</a>` | `<a href="[Jira URL]">[Jira URL]</a>` |
| Text or CSV cell `see https://acmeinc.atlassian.net/browse/DEV-1` | `see [Jira URL]` |
| CSV cell `Page title (https://www.notion.so/Page-0123abcd)` | `Page title ([Notion URL])` |

---

## 5. Matching rules

- **What a URL is:** the match of `(?i)https?://\S+` within a single unit: one HTML text node, one `<a href>` value, one CSV cell, or Markdown text. Text is never matched across units. This is the same unit the URL inventory counts.
- **Exact strings only.** Replace only URLs listed in the approved Replacements table, matched exactly. A variant with trailing punctuation (`…?pvs=21)`, `…share_button]`) is a different string and needs its own row.
- **Stick to the table.** No extra rules, no "obvious" extensions, and no changing a row's token, even if the operator thinks a row is wrong. Raise it and wait.

---

## 6. Out of scope

These are left untouched. Flag them; don't fix them.

| Item | Why |
|---|---|
| Relative links between pages of the export (`<a href="Folder%20Name/Page%20abc123.html">`) and in-page anchors (`#section`) | Not `http(s)` URLs. They still work offline, and they only contain page names that the file names already show. |
| `<img src>`, `alt`, `title`, `<iframe src>` and every attribute other than `<a href>` | The HTML pass reads only visible text and `<a href>`. A keyword pass that works the same way also leaves these attributes unredacted, so check them separately if they matter. |
| `<script>` and `<style>` bodies | Not visible text. |
| URLs inside PDFs and images | The inventory may count text read from them, but a text pass can't edit them. List each shortfall with its file in the file dry run, and skip it. |
| Hosts containing a bracketed pseudonym (`www2.[ALIAS-01].gov`) | The domain can't be parsed. Needs its own ruling; unchanged by default. |

---

## 7. Write safety

1. **Stability check, per file:** parse the file and save it again with no changes. If the result differs from the bytes on disk, **refuse the file**, because writing it would reformat content outside the URLs.
2. **Backup first:** copy each file, keeping its timestamps, to a **durable** backup folder that mirrors the relative paths. Never use a temporary or session-scoped folder: it can be cleaned before you need the undo copy.
3. **Edit in place:** truncate the existing file and write the new content into it (for example, Python `open(path, "w")`). Never write a new file and rename it over the old one. Then check that the inode and creation timestamp are unchanged. A rename-based edit gives the file a new identity and silently resets its creation date.
4. **Named files only:** write exactly the files the green light named, and nothing else.

---

## 8. Verification

**File dry run (step 5), computed in memory:**
1. Replacements found vs the table's hits, per URL and in total. Explain every shortfall (a PDF, an image, or a file edited after the inventory was made) and name the file where possible.
2. Stability check (§7.1) for every file that would change.
3. Residual check: no table URL left in the transformed text.
4. Every change listed per file, with before and after, display-text appends included.

**After the write (step 8)**, compare each changed file with its backup:
1. **URLs outside the table:** the same URLs, the same number of times, before and after.
2. **Structure:** the same tags and attributes. Compare link targets with table URLs and tokens treated as equal.
3. **Text:** identical per text node (HTML) or per cell (CSV) once table URLs and tokens are removed.
4. Per-file replacement counts equal the file dry run, and a second dry run finds 0 table URLs left.

**Method rules**
- Compare per text node or per cell, never raw bytes or a whole page's text. In raw HTML a URL runs into the markup after it (`…id">Title`), and in whole-page text it runs into the next node's text. Both give false failures.
- Don't use a character-level diff on whole files; it scales badly on large HTML. The parsed comparison above takes about a second for dozens of files.
- Any change outside a table URL → token swap or an appended token is a failure. Report it; don't explain it away.

---

## 9. Document formats

All documents are local markdown files, kept **outside** the output folder, because they list real URLs. Build them with a script from the inventory, not by hand, and check every total against the inventory header before showing them.

### 9.1 Rules for the domain and dry-run documents

| Rule | Detail |
|---|---|
| Banner | First line under the title: `> ⚠️ **SENSITIVE — contains real URLs.** Keep local. Do not put it inside the redacted output folder.` |
| Header bullets | **Status:** what has and hasn't been written. **Revision:** one line per revision, appended and never replaced (`**Revision:** 02 (<date>). Changes from 01: …`). **Source of URLs:** the inventory, with its `N unique · M hits` re-checked. **Scope:** `N URLs redacted (M hits). N URLs unchanged (M hits).` In the same bullet, say that inventory hits may include text read from images and PDFs, which can't be edited. **Token rule:** the token replaces the URL in text, link targets and CSV cells; the service is always cited; display text is kept with the token appended. |
| Full URLs | Every URL written out in full. No shortening, no `…`, no samples. |
| Order | Hosts alphabetical. URLs alphabetical (dry-run document), or by hits and then alphabetical within a host (domain document). Never by count alone. |
| IDs | Each ruling row gets an ID (`R01`, `R02`, …) once and keeps it in every revision. A row that is split gets lettered sub-IDs (`R32a`, `R32b`). Never renumber. One row per host, or per host + path prefix where the token differs. No range rows such as "all public hosts". |
| One place per decision | Each decision appears in exactly one table row. No separate notes, flags or reasoning sections; anything about a row goes in that row's Source cell. |
| Source column | `yours` (the reviewer's ruling) · `pre-decided` (from §11) · `my plan, agreed` (a row the reviewer didn't mention) · `my plan` (not yet seen by the reviewer) · `needs your call: <reason>`. A changed ruling keeps its history: `yours (revision 04; was "unchanged" in 01–03)`. |
| Totals | Every count table ends in a `**Total**` row, and the grand total equals the inventory header. |

### 9.2 Domain document (step 2)

Sections, in this order:

1. Title, banner, header bullets.
2. `## Totals by token`: `| Token | Unique URLs | Hits |`, one row per proposed token, then `| unchanged | N | M |`, then `| **Total** | **N** | **M** |`.
3. `## Rulings`: `| Row | Host / path | Unique | Hits | Token | Source |`, alphabetical by host. Token is the proposed token in backticks, or `unchanged`.
4. `## REDACT — N unique · M hits`, then `## KEEP — N unique · M hits`. Under each, one sub-heading per ruling row, either `### R05 host:<host> — N unique · M hits` or `### R10 host:<host>, path starts with <prefix> — N unique · M hits`. Under that, every URL as `- <full URL> ×<hits>`. Every row gets its complete list.
5. `## Next step`: (1) the reviewer rules on the rows, and rows not mentioned are agreed; (2) the operator writes the dry-run document; (3) nothing is written to the data files until there is an explicit green light naming the files.

### 9.3 Dry-run document (step 4)

Sections, in this order. Tooling parses this exact shape.

1. Title, banner, header bullets, plus a bullet `**Link display text is kept:** …` followed by the Before/After table from §4.
2. `## Totals by token`: `| Token | Unique URLs | Hits |`, ending in exactly `| **Total** | **N** | **M** |`. No `unchanged` row.
3. `## Rulings`: `| Row | Host / path | Token | Source |`, with the same IDs as the domain document.
4. `## Replacements — alphabetical by URL (N)`: `| # | Before | After | Hits |`. Every row is exactly ``| <#> | `<full URL>` | `[<Token>]` | <hits> |``, sorted by full URL.
5. `## Unchanged — alphabetical by URL (N)`: `| # | URL | Hits |`. Every row is ``| <#> | `<full URL>` | <hits> |``.
6. `## Next step (after you approve)`: (1) a read-only pass over the files, producing a per-file report whose hit counts must match the table; (2) writes only after an explicit green light.

Before using it, check that the Replacements rows add up to the `**Total**` row. Refuse the document if they don't.

### 9.4 File dry-run report (step 5)

1. Title `URL redaction — file dry run (READ-ONLY)`, then the banner `> ⚠️ **SENSITIVE — contains real URLs.** Keep local.`, then bullets: **Status** (dry run; no data file was written), **Target folder**, **Rules** (the dry-run document and its N URLs / M hits), **Display text** (the §4 rule in one line).
2. `## Checks`: `| Check | Result |`, with rows: replacements vs table hits; URLs whose count matches the table (`n / N`); files changed; display-text appends; files refused because re-saving would change other bytes (must be 0); table URLs still present after the pass.
3. `## Count mismatches` (only if any): `| URL | Table | Found |`, alphabetical by URL.
4. `## Totals by token`: `| Token | Replacements |`, ending in a `**Total**` row.
5. `## Files changed`: `| File | Replacements |`, alphabetical by path relative to the output folder.
6. `## Every change (by file)`: `| File | Where | Before | After |`, where Where is `href`, `text`, `csv cell` or `display text kept + token appended`.

---

## 10. Recordkeeping and conduct

- **Never drop a ruling.** A changed ruling keeps its old value in the Source cell.
- **Ambiguous wording** (a row named under two rules, an instruction that can be read two ways): take the reading you can defend, say in one line which reading you took and what would reverse it, and ask before writing anything that depends on it.
- **Report outcomes as they are.** A shortfall, a refused file, or a check that couldn't run is reported as such, with its file and reason.
- **Check public URLs for leaked pseudonyms.** The keyword pass may have replaced a common first name inside a *public* URL or title, for example a conference talk slug `…-[ALIAS-01]-surname-…`. A reader can look up the public page and learn which name the pseudonym stands for. Look over the KEEP list for `[ALIAS]` tokens next to surnames, and raise them for a ruling.

---

## 11. Pre-decided tokens

These are the reviewer's standing rulings for the Acme workspace. Apply them as proposals in the domain document with Source `pre-decided`. The reviewer can still change any of them for a given folder. Any host not listed needs a proposal and a ruling.

| Host / path prefix | Token |
|---|---|
| `dashboard-production.acme.com/dashboard/user_edit/…` | `[User Dashboard URL]` |
| `www.acme.com/dashboard/user_edit/…` | `[User Dashboard URL]` |
| other paths on `acme.com` hosts | no standing ruling: propose per path |
| `gitlab.acme.com` | `[GitLab URL]` |
| `acmeinc.atlassian.net/browse/…` | `[Jira URL]` |
| `acmeinc.atlassian.net/issues/?filter=…` | `[Jira Filter URL]` |
| `acmeinc.atlassian.net/jira/software/c/projects/<KEY>/boards/<id>/reports/burndown-chart?…` | `[Jira Sprint Burndown Chart URL]` |
| `acmeinc.atlassian.net/jira/software/c/projects/<KEY>/boards/<id>/reports/sprint-retrospective…` | `[Jira Sprint Report URL]` |
| `acmeinc.atlassian.net`, any other path | `[Atlassian URL]` |
| `acmeinc.slack.com`, `app.slack.com` | `[Slack URL]` |
| other `<workspace>.slack.com` (communities that aren't Acme's) | unchanged |
| `www.notion.so` | `[Notion URL]` |
| `docs.google.com/document/…` | `[Google Docs URL]` |
| `docs.google.com/presentation/…` | `[Google Slides URL]` |
| `docs.google.com/spreadsheets/…` | `[Google Sheets URL]` |
| `play.google.com` | `[Google Play Store URL]` |
| `action.parabol.co`, `prbl.in` | `[Parabol URL]` |
| `acme.testrail.net` | `[TestRail URL]` |
| `s3-us-west-2.amazonaws.com` (export attachments) | `[AWS URL]`; a single attachment the reviewer names can get its own token, for example `[QA Library URL]` |
| `marketplace.atlassian.com`, `www.atlassian.com` | unchanged (public) |
| Public content: talks, articles, blogs, vendor and product pages, video, social posts, GIF hosts | unchanged |
| Hosts containing a bracketed pseudonym | unchanged unless ruled |

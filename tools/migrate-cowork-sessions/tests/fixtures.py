"""Synthetic Cowork workspace builder — the single source of truth for test input.

Stdlib only. Builds an ephemeral, fully synthetic Cowork workspace on disk (no real
PII or paths) mirroring the layout migrate_cowork_sessions.py discovers:

  <root>/
    spaces.json                      [{"id": SPACE_UUID, "name": "Test Space"}]
    local_<SESS_UUID>.json           sidecar: {"spaceId": SPACE_UUID, "title": "Sess 1"}
    local_<SESS_UUID>/.claude/projects/proj/
        <TX_UUID>.jsonl              main transcript (kept)
        <TX_UUID>/tool-results/r1.json
        subagents/agent-x.jsonl      excluded (subagent)
        audit.jsonl                  excluded (audit)
    spaces/<SPACE_UUID>/memory/
        note.md                      copied
        MEMORY.md                    excluded (index)

Run standalone to materialize a sample to inspect:
    python3 fixtures.py /tmp/sample-cowork-ws
"""
import json
import sys
from pathlib import Path

SPACE_UUID = "11111111-1111-1111-1111-111111111111"
SESS_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TX_UUID = "22222222-2222-2222-2222-222222222222"
SPACE2_UUID = "33333333-3333-3333-3333-333333333333"
SESS2_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
TX2_UUID = "44444444-4444-4444-4444-444444444444"


def build_synthetic_workspace(root: Path, with_second_space: bool = False) -> dict:
    """Materialize the synthetic workspace under `root`. Returns key ids + paths."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    spaces_list = [{"id": SPACE_UUID, "name": "Test Space"}]
    if with_second_space:
        spaces_list.append({"id": SPACE2_UUID, "name": "Second Space"})
    (root / "spaces.json").write_text(
        json.dumps(spaces_list), encoding="utf-8")
    (root / f"local_{SESS_UUID}.json").write_text(
        json.dumps({"spaceId": SPACE_UUID, "title": "Sess 1"}), encoding="utf-8")
    proj = root / f"local_{SESS_UUID}" / ".claude" / "projects" / "proj"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / f"{TX_UUID}.jsonl").write_text('{"type":"msg"}\n', encoding="utf-8")
    (proj / TX_UUID / "tool-results").mkdir(parents=True, exist_ok=True)
    (proj / TX_UUID / "tool-results" / "r1.json").write_text('{"r":1}', encoding="utf-8")
    (proj / "subagents").mkdir(exist_ok=True)
    (proj / "subagents" / "agent-x.jsonl").write_text('{"s":1}\n', encoding="utf-8")
    (proj / "audit.jsonl").write_text('{"audit":1}\n', encoding="utf-8")
    mem = root / "spaces" / SPACE_UUID / "memory"
    mem.mkdir(parents=True, exist_ok=True)
    (mem / "note.md").write_text("# migrated note\n", encoding="utf-8")
    (mem / "MEMORY.md").write_text("# stale index\n", encoding="utf-8")
    if with_second_space:
        (root / f"local_{SESS2_UUID}.json").write_text(
            json.dumps({"spaceId": SPACE2_UUID, "title": "Sess 2"}), encoding="utf-8")
        proj2 = root / f"local_{SESS2_UUID}" / ".claude" / "projects" / "proj2"
        proj2.mkdir(parents=True, exist_ok=True)
        (proj2 / f"{TX2_UUID}.jsonl").write_text('{"type":"msg2"}\n', encoding="utf-8")
    return {
        "workspace": root, "space_uuid": SPACE_UUID, "sess_uuid": SESS_UUID,
        "tx_uuid": TX_UUID, "transcript_name": f"{TX_UUID}.jsonl",
        "space2_uuid": SPACE2_UUID, "tx2_uuid": TX2_UUID,
    }


if __name__ == "__main__":
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("./sample-cowork-ws")
    print(f"Built synthetic Cowork workspace at: {build_synthetic_workspace(dest)['workspace']}")

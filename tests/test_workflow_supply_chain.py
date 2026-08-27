"""Supply-chain guard: GitHub Actions must stay SHA-pinned and least-privilege.

Static checks over ``.github/workflows/*.yml`` (deliberately dependency-free
regex parsing — no PyYAML requirement):

* every ``uses:`` reference is pinned to a full 40-character commit SHA
  (no mutable ``@v4``-style tags anywhere);
* ``ci.yml`` declares an explicit read-only ``permissions`` baseline and never
  asks for ``contents: write``;
* ``release.yml`` keeps ``contents: write`` scoped to the single publishing
  job (``build-windows``) — the read-only gate/build jobs never hold it;
* ``deploy-pages.yml`` keeps its minimal pages/id-token scope.

These tests encode the hardening decisions recorded in the v0.9.0 security
audit (supply-chain finding) so a mutable tag or a broadened token scope
cannot be reintroduced accidentally.
"""

from __future__ import annotations

import pathlib
import re

WORKFLOWS_DIR = (
    pathlib.Path(__file__).resolve().parents[1] / ".github" / "workflows"
)

_SHA_PINNED_USES = re.compile(r"uses:\s*\S+@([0-9a-f]{40})\s*(#.*)?$")
_MUTABLE_TAG_USES = re.compile(r"uses:\s*\S+@(?!([0-9a-f]{40})\b)\S+")


def _strip_comments(text: str) -> str:
    """Drop YAML comments so prose can never masquerade as configuration."""
    return "\n".join(
        line.split("#", 1)[0].rstrip() if "#" in line else line
        for line in text.splitlines()
    )


def _workflow_files() -> list[pathlib.Path]:
    return sorted(WORKFLOWS_DIR.glob("*.yml"))


def _read(name: str) -> str:
    return (WORKFLOWS_DIR / name).read_text(encoding="utf-8")


def _job_section(text: str, job_key: str) -> str:
    """Return the YAML text of one job, up to the next sibling key.

    Job keys may be indented (this repository nests them two spaces under
    ``jobs:``), so both the target key and the following sibling are matched
    at whatever indent the target uses.
    """
    match = (
        re.search(rf"^( +)({re.escape(job_key)}):[ \t]*(?:#.*)?$", text, re.MULTILINE)
        or re.search(rf"^()({re.escape(job_key)}):[ \t]*(?:#.*)?$", text, re.MULTILINE)
    )
    assert match is not None, f"job {job_key!r} not found"
    indent = match.group(1)
    rest = text[match.end():]
    nxt = re.search(
        rf"^{indent}[A-Za-z_][\w-]*:[ \t]*(?:#.*)?$", rest, re.MULTILINE
    )
    return rest[: nxt.start()] if nxt else rest


# --------------------------------------------------------------------------
# Pinning
# --------------------------------------------------------------------------

def test_workflows_exist():
    files = _workflow_files()
    assert {p.name for p in files} >= {"ci.yml", "release.yml", "deploy-pages.yml"}


def test_every_workflow_has_actions():
    for path in _workflow_files():
        text = path.read_text(encoding="utf-8")
        assert re.search(r"^\s*(-\s+)?uses:", text, re.MULTILINE), (
            f"{path.name} declares no actions"
        )


def test_every_action_is_pinned_to_full_commit_sha():
    for path in _workflow_files():
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if not re.search(r"\buses:", line):
                continue
            assert _SHA_PINNED_USES.search(line), (
                f"{path.name}: action ref is not SHA-pinned: {line.strip()!r}"
            )


def test_no_mutable_version_tag_references_remain():
    for path in _workflow_files():
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if "uses:" not in line:
                continue
            assert not _MUTABLE_TAG_USES.search(line.rstrip()), (
                f"{path.name}: mutable action tag: {line.strip()!r}"
            )


def test_pins_carry_version_comments():
    """Each pin documents the human-readable version it freezes."""
    for path in _workflow_files():
        text = path.read_text(encoding="utf-8")
        pinned = [
            line for line in text.splitlines()
            if re.search(r"\buses:", line)
        ]
        commented = [line for line in pinned if "@" in line.split("#")[-1]]
        assert commented == pinned, f"{path.name}: pin missing version comment"


# --------------------------------------------------------------------------
# Permissions scoping
# --------------------------------------------------------------------------

def test_ci_workflow_is_read_only():
    text = _strip_comments(_read("ci.yml"))
    match = re.search(
        r"^permissions:\s*$\n^  contents:\s*read\s*$", text, re.MULTILINE
    )
    assert match, "ci.yml must declare an explicit contents: read baseline"
    assert "contents: write" not in text, (
        "ci.yml must never request contents: write"
    )


def test_release_write_is_scoped_to_publishing_job_only():
    text = _strip_comments(_read("release.yml"))

    # Workflow-level baseline is read-only.
    top = text.split("jobs:", 1)[0]
    assert re.search(r"^permissions:\s*$", top, re.MULTILINE)
    assert re.search(r"^  contents:\s*read\s*$", top, re.MULTILINE)
    assert "contents: write" not in top

    # The read-only gate job never elevates.
    assert "contents: write" not in _job_section(text, "gate")

    # Only the publishing job holds contents: write.
    build = _job_section(text, "build-windows")
    assert re.search(
        r"^    permissions:\s*$\n^      contents:\s*write\s*$",
        build,
        re.MULTILINE,
    ), "build-windows must declare its own contents: write"

    # The release publisher lives inside that elevated job.
    assert re.search(r"uses:\s*softprops/action-gh-release@[0-9a-f]{40}", build)


def test_deploy_pages_remains_least_privilege():
    text = _strip_comments(_read("deploy-pages.yml"))
    assert re.search(
        r"^permissions:\s*$\n"
        r"^  contents:\s*read\s*$\n"
        r"^  pages:\s*write\s*$\n"
        r"^  id-token:\s*write\s*$",
        text,
        re.MULTILINE,
    )
    assert "contents: write" not in text

"""Release provenance guard: attested, published Windows artifacts.

Priority #3 hardening (dependency-free static checks, no exact line numbers):

* ``build-windows`` is the ONLY job holding elevated scopes
  (``contents: write``, ``id-token: write``, ``attestations: write``);
* ``actions/attest-build-provenance`` runs AFTER checksum generation and
  covers exactly the four release subjects;
* ``BUILD_ENV_FREEZE.txt`` ships as a release asset;
* SHA256SUMS still hashes exactly the two Windows executables;
* a future Authenticode step must never be silently skipped because a
  secret is missing (fail-closed signing policy; signing itself is NOT
  required today — no signing identity exists).
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = ROOT / ".github" / "workflows"
RELEASE = WORKFLOWS_DIR / "release.yml"

_EXPECTED_SUBJECTS = {
    "dist/AndroidTaskManager.exe",
    "dist/AndroidTaskManager-debug.exe",
    "dist/SHA256SUMS.txt",
    "dist/BUILD_ENV_FREEZE.txt",
}

_SIGN_MARKERS = ("signtool", "authenticode", "trusted-signing", "-sign")


def _release_text(*, strip_comments: bool = False) -> str:
    text = RELEASE.read_text(encoding="utf-8")
    if strip_comments:
        text = "\n".join(
            line.split("#", 1)[0].rstrip() if "#" in line else line
            for line in text.splitlines()
        )
    return text


def _job_section(text: str, job_key: str) -> str:
    """Slice one job out of a workflow, indent-aware (jobs nest two spaces)."""
    match = (
        re.search(rf"^( +)({re.escape(job_key)}):[ \t]*(?:#.*)?$", text, re.MULTILINE)
        or re.search(rf"^()({re.escape(job_key)}):[ \t]*(?:#.*)?$", text, re.MULTILINE)
    )
    assert match is not None, f"job {job_key!r} not found"
    rest = text[match.end():]
    nxt = re.search(
        rf"^{match.group(1)}[A-Za-z_][\w-]*:[ \t]*(?:#.*)?$", rest, re.MULTILINE
    )
    return rest[: nxt.start()] if nxt else rest


def _indented_list_after(text: str, marker: str, key: str) -> set[str]:
    """Plain block-scalar list lines following *key* near *marker*.

    Mapping entries that may follow the block (e.g. ``generate_release_notes``)
    are excluded by rejecting lines containing ``:``.
    """
    start = text.find(marker)
    assert start != -1, f"{marker!r} not found"
    block_match = re.search(rf"{key}:\s*\|\s*\n((?:[ ]+.+\n?)+)", text[start:])
    assert block_match is not None, f"{key!r} list not found after {marker!r}"
    return {
        line.strip()
        for line in block_match.group(1).splitlines()
        if line.strip() and ":" not in line
    }


# --------------------------------------------------------------------------
# 1-2-3. Permission scoping
# --------------------------------------------------------------------------

def test_build_windows_holds_all_three_publishing_scopes():
    perms = _job_section(_release_text(), "build-windows")
    scope_block = re.search(
        r"permissions:\s*$\n"
        r"\s+contents:\s*write\s*$\n"
        r"\s+id-token:\s*write\s*$\n"
        r"\s+attestations:\s*write\s*$",
        perms,
        re.MULTILINE,
    )
    assert scope_block is not None, (
        "build-windows must hold contents/id-token/attestations write"
    )


def test_gate_job_receives_none_of_the_publishing_scopes():
    section = _job_section(_release_text(), "gate")
    for forbidden in ("contents: write", "id-token:", "attestations:"):
        assert forbidden not in section, f"gate must not receive {forbidden!r}"


def test_other_workflows_do_not_receive_attestation_scopes():
    build_windows = _job_section(_release_text(), "build-windows")
    for path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        for lineno, raw in enumerate(text.splitlines(), 1):
            stripped = raw.strip()
            elevated = (
                stripped.startswith("id-token:")
                or stripped.startswith("attestations:")
            )
            if not elevated:
                continue
            if path.name == "deploy-pages.yml":
                # Legitimate pre-existing Pages OIDC use; attestations stay out.
                assert not stripped.startswith("attestations:"), (
                    f"{path.name}:{lineno}: unexpected attestations scope"
                )
                continue
            if path.name == "release.yml":
                assert stripped in build_windows, (
                    f"release.yml:{lineno}: elevated scope outside build-windows"
                )
                continue
            raise AssertionError(
                f"{path.name}:{lineno}: elevated scope in unrelated workflow"
            )


# --------------------------------------------------------------------------
# 4-6. Attestation action, ordering, subjects
# --------------------------------------------------------------------------

def test_attestation_action_present_and_fully_pinned():
    pinned = re.search(
        r"uses:\s*actions/attest-build-provenance@([0-9a-f]{40})\b",
        _release_text(),
    )
    assert pinned is not None, "attest-build-provenance must be present and SHA-pinned"


def test_attestation_runs_after_checksum_generation():
    text = _release_text()
    checksum_at = text.find("Generate SHA-256 checksums")
    attest_at = text.find("actions/attest-build-provenance@")
    assert checksum_at != -1 and attest_at != -1
    assert checksum_at < attest_at, "attestation must follow SHA256SUMS generation"


def test_attestation_covers_exactly_the_four_release_subjects():
    subjects = _indented_list_after(
        _release_text(strip_comments=True),
        "actions/attest-build-provenance@",
        "subject-path",
    )
    assert subjects == _EXPECTED_SUBJECTS, (
        f"attested subjects mismatch: extra={subjects - _EXPECTED_SUBJECTS} "
        f"missing={_EXPECTED_SUBJECTS - subjects}"
    )


# --------------------------------------------------------------------------
# 7. Provenance snapshot ships with the release
# --------------------------------------------------------------------------

def test_build_env_freeze_is_a_release_asset():
    assets = _indented_list_after(
        _release_text(strip_comments=True), "Publish GitHub Release", "files"
    )
    assert "dist/BUILD_ENV_FREEZE.txt" in assets
    assert assets == _EXPECTED_SUBJECTS, (
        "published assets should mirror the attested subject set"
    )


# --------------------------------------------------------------------------
# 8. Checksum coverage unchanged
# --------------------------------------------------------------------------

def test_sha256sums_hashes_exactly_the_two_executables():
    text = _release_text()
    start = text.find("Generate SHA-256 checksums")
    assert start != -1
    rest = text[start:]
    end = rest.find("attest-build-provenance@")
    step = rest[: end] if end != -1 else rest
    array_match = re.search(r'@\("([^"]+)"\s*,\s*"([^"]+)"\)', step)
    assert array_match is not None, "checksum file array not found"
    assert [array_match.group(1), array_match.group(2)] == [
        "dist\\AndroidTaskManager.exe",
        "dist\\AndroidTaskManager-debug.exe",
    ], f"unexpected checksum coverage: {array_match.groups()}"


# --------------------------------------------------------------------------
# 9. Fail-closed future signing policy (vacuously true until signing exists)
# --------------------------------------------------------------------------

def test_signing_must_never_be_secret_conditionally_skipped():
    offenders: list[str] = []
    targets = (RELEASE, ROOT / "packaging" / "build_windows.ps1")
    for target in targets:
        text = target.read_text(encoding="utf-8")
        lines = text.splitlines()
        for i, line in enumerate(lines):
            lowered = line.lower()
            if not any(marker in lowered for marker in _SIGN_MARKERS):
                continue
            window = "\n".join(lines[max(0, i - 6): i + 6]).lower()
            if re.search(r"if:.*secrets\.", window) or "secrets." in lowered:
                offenders.append(f"{target.name}:{i + 1}")
    assert not offenders, (
        f"signing steps conditioned on secrets would fail open: {offenders}"
    )

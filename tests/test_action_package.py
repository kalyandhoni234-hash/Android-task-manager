"""Package-name validation: the security boundary of Device Actions."""

import pytest

from android_task_manager.action.package import (
    PackageValidationError,
    parse_package_list,
    validate_component,
    validate_package_name,
)

VALID_PACKAGES = [
    "com.example.app",
    "com.a",
    "a.b",
    "org.foo_bar.Baz2",
    "com.android.chrome",
    "io.github.somebody.project",
    "a",
    "a.a",
    "com.example_underscore.deep.nested.package.name",
]

INVALID_PACKAGES = [
    "",
    " ",
    "com.example..app",
    ".com.example",
    "com.example.",
    "com/example",
    "com\\example",
    "com exa mple",
    "1com.example",
    "com.1example",
    "-n com.example",
    "com.example; rm -rf /",
    "com.example && reboot",
    "com.example | sh",
    "com.example`id`",
    "$(id)",
    "com.example$(id)",
    "../com.example",
    "com.example/../../etc",
    "https://com.example",
    "com.example#fragment",
    "com.example?query",
    "com.example*",
    "com.example!",
    "com.example%0a",
    "a" * 256,
]


@pytest.mark.parametrize("package", VALID_PACKAGES)
def test_valid_package_accepted(package: str) -> None:
    assert validate_package_name(package) == package


@pytest.mark.parametrize("package", INVALID_PACKAGES)
def test_invalid_package_rejected(package: str) -> None:
    with pytest.raises(PackageValidationError):
        validate_package_name(package)


def test_whitespace_wrapped_valid_package_is_accepted() -> None:
    assert validate_package_name("  com.example.app\n") == "com.example.app"


def test_non_string_input_rejected() -> None:
    with pytest.raises(PackageValidationError):
        validate_package_name(None)  # type: ignore[arg-type]
    with pytest.raises(PackageValidationError):
        validate_package_name(12345)  # type: ignore[arg-type]


def test_package_length_limit() -> None:
    # 254 characters, all valid syntax: accepted.
    long_ok = "a" + "." + "a" * 250
    assert len(long_ok) <= 255
    assert validate_package_name(long_ok) == long_ok
    # 256 characters: rejected.
    with pytest.raises(PackageValidationError):
        validate_package_name("a" * 256)


def test_validate_component_accepts_launcher_component() -> None:
    component = "com.example.app/com.example.app.MainActivity"
    assert validate_component(component) == component


def test_validate_component_accepts_abbreviated_activity() -> None:
    component = "com.example.app/.MainActivity"
    assert validate_component(component) == component


def test_validate_component_accepts_inner_class_activity() -> None:
    component = "com.example.app/com.example.app.ui.Main$Activity"
    assert validate_component(component) == component


def test_validate_component_rejects_garbage() -> None:
    for component in ["", " ", "com.example.app", "com.example.app/", "/Main", "a b/c", "a;x/y"]:
        with pytest.raises(PackageValidationError):
            validate_component(component)


def test_parse_package_list_extracts_valid_entries() -> None:
    text = (
        "package:com.example.app\n"
        "package:org.foo\n"
        "\n"
        "junk line\n"
        "package:com.bad name\n"
        "package:\n"
    )
    assert parse_package_list(text) == {"com.example.app", "org.foo"}


def test_parse_package_list_empty_input() -> None:
    assert parse_package_list("") == set()


def test_parse_package_list_discards_injection_attempts() -> None:
    text = "package:com.example; rm -rf /\npackage:com.safe\n"
    assert parse_package_list(text) == {"com.safe"}
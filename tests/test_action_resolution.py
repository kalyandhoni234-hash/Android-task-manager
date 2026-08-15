"""Process-to-package resolution: identity is verified, never guessed."""

from android_task_manager.action.resolution import (
    is_kernel_style_name,
    parse_command_line_argv0,
    resolve_package,
    strip_secondary_suffix,
)

INSTALLED = {
    "com.example.app",
    "org.foo.bar",
    "com.android.systemui",
    "com.vivo.notes",
}


def test_argv0_from_command_line() -> None:
    assert parse_command_line_argv0("com.example.app --fg") == "com.example.app"
    assert parse_command_line_argv0("system_server") == "system_server"
    assert parse_command_line_argv0("") is None
    assert parse_command_line_argv0(None) is None
    assert parse_command_line_argv0("   ") is None


def test_strip_secondary_suffix() -> None:
    assert strip_secondary_suffix("com.example.app") == "com.example.app"
    assert strip_secondary_suffix("com.example.app:remote") == "com.example.app"
    assert strip_secondary_suffix("com.example.app:service") == "com.example.app"
    assert strip_secondary_suffix("com.example.app:pool-1-thread-2") == "com.example.app"
    assert strip_secondary_suffix(":leading") == ""


def test_kernel_style_detection() -> None:
    assert is_kernel_style_name("[kworker/0:1]")
    assert is_kernel_style_name("[rcu_preempt]")
    assert not is_kernel_style_name("kworker/0:1")
    assert not is_kernel_style_name("system_server")
    assert not is_kernel_style_name("com.example.app:remote")


def test_resolve_via_command_line_argv0() -> None:
    assert (
        resolve_package("com.example.app", "com.example.app --process=main", INSTALLED)
        == "com.example.app"
    )


def test_resolve_via_ps_name() -> None:
    assert resolve_package("org.foo.bar", None, INSTALLED) == "org.foo.bar"


def test_resolve_prefers_command_line_over_name() -> None:
    # process.name is the truncated `comm`; the cmdline argv0 is authoritative.
    assert resolve_package("xample.app", "com.example.app", INSTALLED) == "com.example.app"


def test_secondary_process_resolves_to_base_package() -> None:
    for suffix in (":remote", ":service", ":ui", ":pool-1", ":isolated0"):
        assert (
            resolve_package(f"com.example.app{suffix}", None, INSTALLED)
            == "com.example.app"
        )


def test_secondary_process_via_command_line() -> None:
    assert (
        resolve_package(
            "example.app:remote",
            "com.example.app:remote",
            INSTALLED,
        )
        == "com.example.app"
    )


def test_secondary_process_base_not_installed_stays_none() -> None:
    assert resolve_package("com.not.installed:remote", None, INSTALLED) is None


def test_bracketed_kernel_threads_never_resolve() -> None:
    for name in (
        "[kworker/0:1]",
        "[rcu_preempt]",
        "[kthreadd]",
        "[ksoftirqd/0]",
        "[mmcqd/0]",
        "[bdi-default]",
    ):
        assert resolve_package(name, None, INSTALLED) is None
        assert resolve_package(name, "", INSTALLED) is None


def test_kernel_threads_never_resolve() -> None:
    for name in ("kworker/0:1", "rcu_preempt", "ksoftirqd/0", "[kthreadd]", "mmcqd/0"):
        assert resolve_package(name, None, INSTALLED) is None
        assert resolve_package(name, "", INSTALLED) is None


def test_system_process_without_package_identity_never_resolves() -> None:
    assert resolve_package("system_server", "system_server", INSTALLED) is None
    assert resolve_package("zygote", "zygote", INSTALLED) is None
    assert resolve_package("ndroid.systemui", "ndroid.systemui", INSTALLED) is None


def test_vendor_process_does_not_resolve_without_verification() -> None:
    # SurfaceFlinger / vendor native daemons are not installed packages.
    assert resolve_package("surfaceflinger", "surfaceflinger", INSTALLED) is None
    assert resolve_package("vendor.qti.hardware", None, INSTALLED) is None


def test_name_with_syntax_but_not_installed_does_not_resolve() -> None:
    assert resolve_package("com.other.not.installed", None, INSTALLED) is None


def test_empty_installed_set_resolves_nothing() -> None:
    assert resolve_package("com.example.app", "com.example.app", set()) is None


def test_injection_looking_identity_does_not_resolve() -> None:
    assert (
        resolve_package("com.example; rm -rf /", "com.example; rm -rf /", INSTALLED)
        is None
    )


def test_path_like_and_whitespace_identities_do_not_resolve() -> None:
    for hostile in (
        "../com.example.app",
        "com.example/app",
        "com.example.app/../../etc",
        "com exa mple",
        "/system/bin/app_process",
        "",
    ):
        assert resolve_package(hostile, None, INSTALLED) is None
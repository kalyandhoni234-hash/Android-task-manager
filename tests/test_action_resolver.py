"""PackageResolver tests: verified identity, refresh, invalidation."""

from android_task_manager.action.resolver import PackageResolver


def test_resolve_returns_none_without_installed_set() -> None:
    resolver = PackageResolver()
    assert resolver.resolve("com.example.app") is None


def test_resolve_verified_identity() -> None:
    resolver = PackageResolver({"com.example.app", "org.foo"})
    assert resolver.resolve("com.example.app") == "com.example.app"


def test_resolve_secondary_process() -> None:
    resolver = PackageResolver({"com.example.app"})
    assert resolver.resolve("com.example.app:remote") == "com.example.app"


def test_resolve_uninstalled_is_none() -> None:
    resolver = PackageResolver({"com.example.app"})
    assert resolver.resolve("org.not.installed") is None
    assert resolver.resolve("system_server") is None


def test_installed_returns_a_copy() -> None:
    resolver = PackageResolver({"com.example.app"})
    got = resolver.installed()
    got.add("mutated")
    assert resolver.resolve("mutated") is None


def test_update_replaces_the_whole_set() -> None:
    resolver = PackageResolver({"com.example.app"})
    resolver.update({"org.new", "com.other"})
    assert resolver.resolve("com.example.app") is None
    assert resolver.resolve("org.new") == "org.new"


def test_invalidate_drops_single_package() -> None:
    resolver = PackageResolver({"com.example.app", "org.foo"})
    resolver.invalidate("com.example.app")
    assert resolver.resolve("com.example.app") is None
    assert resolver.resolve("org.foo") == "org.foo"


def test_invalidate_unknown_package_is_harmless() -> None:
    resolver = PackageResolver({"com.example.app"})
    resolver.invalidate("never.there")
    assert resolver.resolve("com.example.app") == "com.example.app"


def test_kernel_and_path_like_never_resolve() -> None:
    resolver = PackageResolver({"com.example.app"})
    for hostile in ("[kworker/0:1]", "[rcu_preempt]", "../com.example.app", "com.example.app; rm -rf /"):
        assert resolver.resolve(hostile) is None

"""The guest CA bind must see zygote and must refuse a partial trust store."""

from __future__ import annotations

from automation.mantis_inject_ca import _ca_namespace_script


def test_namespace_script_finds_zygote_past_cmdline_nuls() -> None:
    script = _ca_namespace_script("bcac1af3.0")
    assert "pidof zygote64" in script
    assert "pidof zygote" in script
    assert "grep -a" in script
    assert "tr " not in script
    assert "NAME=bcac1af3.0" in script


def test_namespace_script_refuses_partial_store() -> None:
    script = _ca_namespace_script("abc.0")
    assert "SKIP_SMALL" in script
    assert 'test "$n" -gt 10' in script
    assert "SKIP_MISSING" in script

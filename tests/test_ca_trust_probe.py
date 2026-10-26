"""CA trust probe semantics: handshake-only trust, not upstream HTTP status."""
from __future__ import annotations

import sys
import types
from pathlib import Path


class _FakeAdb:
    """Shell stub that replays a canned stdout per call."""

    def __init__(self, out: str):
        self._out = out

    def shell(self, cmd: str, serial: str = "", timeout: int = 30):
        req = types.SimpleNamespace()
        req.stdout = self._out
        req.stderr = ""
        return req


def _probe(monkeypatch, out: str):
    import automation.mantis_inject_proxy as mip

    # Stub CA-material import path so the probe does not need real cert files.
    fake_ca = types.SimpleNamespace(
        CA_CERT=str(Path("ca.cert.pem")),
        android_cacert_hash=lambda cert: "deadbeef",
        ensure_ca_files=lambda: None,
    )
    import automation.mantis_inject_ca as real_ca

    monkeypatch.setitem(sys.modules, "automation.mantis_inject_ca", real_ca)
    monkeypatch.setattr(
        mip, "Path", lambda p="": types.SimpleNamespace(
            is_file=lambda: False,
            read_bytes=lambda: b"",
        ),
        raising=False,
    )
    # Provide x509 stub and a synthetic cert path that exists
    monkeypatch.setattr(mip, "_CA_FILE_CACHE", {}, raising=False)

    import automation.mantis_inject_proxy as mip2

    fake_x509 = types.SimpleNamespace(
        load_pem_x509_certificate=lambda b: object(),
    )
    sys.modules.setdefault("cryptography", types.ModuleType("cryptography"))
    sys.modules["cryptography"] = types.ModuleType("cryptography")
    x = types.ModuleType("cryptography.x509")
    x.load_pem_x509_certificate = lambda b: object()
    sys.modules["cryptography.x509"] = x

    # Point the CA-cert fallback candidates at a path that reports is_file.
    real_path = Path(__file__)
    class _P:
        def __init__(self, s: str):
            self._s = s
        def is_file(self) -> bool:
            return True
        def read_bytes(self) -> bytes:
            return b"-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"

    monkeypatch.setattr(mip2, "Path", _P, raising=False)
    monkeypatch.setattr(real_ca, "CA_CERT", "ca.cert.pem", raising=False)
    monkeypatch.setattr(real_ca, "android_cacert_hash", lambda cert: "deadbeef", raising=False)
    monkeypatch.setattr(real_ca, "ensure_ca_files", lambda: None, raising=False)

    adb = _FakeAdb(out)
    return mip2._device_trusts_inject_ca(adb, "10.0.2.15:5555", 8218)


def test_upstream_5xx_still_means_trusted(monkeypatch) -> None:
    # Handshake completed; origin unreachable via this phone's exit.
    out = "curl: (52) Empty reply from server\n502"
    assert _probe(monkeypatch, out) == "trusted"


def test_2xx_is_trusted(monkeypatch) -> None:
    assert _probe(monkeypatch, "200") == "trusted"


def test_3xx_is_trusted(monkeypatch) -> None:
    assert _probe(monkeypatch, "302") == "trusted"


def test_000_network_dark_is_inconclusive(monkeypatch) -> None:
    # Timeout is not a certificate failure. The caller keeps the run
    # when the CA file is already on the guest.
    assert _probe(monkeypatch, "000") == "inconclusive"


def test_self_signed_phrase_is_distrust(monkeypatch) -> None:
    out = "curl: (60) SSL certificate problem: self-signed certificate in certificate chain\r\n000"
    assert _probe(monkeypatch, out) == "untrusted"


def test_certificate_unknown_phrase_is_distrust(monkeypatch) -> None:
    out = "OpenSSL SSL_read: SSLv3 alert certificate unknown\n000"
    assert _probe(monkeypatch, out) == "untrusted"


def test_empty_output_is_inconclusive(monkeypatch) -> None:
    assert _probe(monkeypatch, "") == "inconclusive"

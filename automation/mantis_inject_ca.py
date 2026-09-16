"""CA for Mantis inject MITM proxy + install onto rooted MuMu as system trust."""

from __future__ import annotations

import hashlib
import logging
import os
import ssl
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

logger = logging.getLogger(__name__)

def _resolve_ca_dir() -> Path:
    """Prefer explicit env, then existing CPharm/PharmFlow cert dirs (never invent a second CA)."""
    for name in ("PHARMFLOW_MANTIS_CA_DIR", "CPHARM_MANTIS_CA_DIR"):
        raw = os.environ.get(name)
        if raw is not None and str(raw).strip() != "":
            return Path(raw)
    candidates = (
        Path(r"C:\PharmFlow\certs\mantis_inject"),
        Path(r"C:\CPharm\certs\mantis_inject"),
    )
    for cand in candidates:
        if (cand / "ca.key.pem").is_file() and (cand / "ca.cert.pem").is_file():
            return cand
    return candidates[0]


CA_DIR = _resolve_ca_dir()
CA_KEY = CA_DIR / "ca.key.pem"
CA_CERT = CA_DIR / "ca.cert.pem"
_HOST_CACHE: dict[str, tuple[Path, Path]] = {}


def _mirror_ca_files(key_bytes: bytes, cert_bytes: bytes) -> None:
    """Keep CPharm + PharmFlow cert copies identical so branding cannot split trust."""
    for dest_dir in (
        Path(r"C:\PharmFlow\certs\mantis_inject"),
        Path(r"C:\CPharm\certs\mantis_inject"),
    ):
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            (dest_dir / "ca.key.pem").write_bytes(key_bytes)
            (dest_dir / "ca.cert.pem").write_bytes(cert_bytes)
        except OSError as exc:
            logger.debug("CA mirror soft-fail %s: %s", dest_dir, exc)


def ensure_ca_files() -> tuple[Path, Path]:
    global CA_DIR, CA_KEY, CA_CERT
    CA_DIR = _resolve_ca_dir()
    CA_KEY = CA_DIR / "ca.key.pem"
    CA_CERT = CA_DIR / "ca.cert.pem"
    CA_DIR.mkdir(parents=True, exist_ok=True)
    if CA_KEY.is_file() and CA_CERT.is_file() and CA_KEY.stat().st_size > 100 and CA_CERT.stat().st_size > 100:
        # Keep dual roots in sync with the resolved CA (branding split-brain).
        try:
            _mirror_ca_files(CA_KEY.read_bytes(), CA_CERT.read_bytes())
        except OSError:
            pass
        return CA_KEY, CA_CERT
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    # Distinct CN/O so Android subject_hash_old is unique when we rotate CAs
    # (same subject as a prior key left WebView trusting a stale da34b7d8.0).
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "PharmFlow Mantis Inject CA v2"),
            x509.NameAttribute(NameOID.COMMON_NAME, "PharmFlow Mantis Inject CA v2"),
        ]
    )
    now = datetime.now(timezone.utc)
    pub = key.public_key()
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(pub)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                crl_sign=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        # Chromium / modern OpenSSL reject MITM leaves without AKI when the
        # issuing CA also lacks SKI (host probe: Missing Authority Key Identifier).
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(pub), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(pub),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    key_bytes = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    cert_bytes = cert.public_bytes(serialization.Encoding.PEM)
    CA_KEY.write_bytes(key_bytes)
    CA_CERT.write_bytes(cert_bytes)
    _mirror_ca_files(key_bytes, cert_bytes)
    logger.info("wrote Mantis inject CA -> %s", CA_CERT)
    return CA_KEY, CA_CERT


def _load_ca() -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    ensure_ca_files()
    key = serialization.load_pem_private_key(CA_KEY.read_bytes(), password=None)
    cert = x509.load_pem_x509_certificate(CA_CERT.read_bytes())
    return key, cert  # type: ignore[return-value]


def clear_host_cert_cache() -> None:
    """Drop in-memory + on-disk leaf certs so AKI/SKI fixes take effect immediately."""
    _HOST_CACHE.clear()
    try:
        ensure_ca_files()
        for path in CA_DIR.glob("host_*.pem"):
            try:
                path.unlink()
            except OSError:
                pass
        for path in CA_DIR.glob("host_*.fullchain.pem"):
            try:
                path.unlink()
            except OSError:
                pass
    except Exception as exc:
        logger.debug("clear_host_cert_cache soft-fail: %s", exc)


def issue_host_cert(hostname: str) -> tuple[Path, Path]:
    host = hostname.lower().strip()
    if host in _HOST_CACHE and all(p.is_file() for p in _HOST_CACHE[host]):
        return _HOST_CACHE[host]
    ca_key, ca_cert = _load_ca()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    san = [x509.DNSName(host)]
    if host.startswith("www."):
        san.append(x509.DNSName(host[4:]))
    else:
        san.append(x509.DNSName("www." + host))
    leaf_pub = key.public_key()
    # AKI from issuer public key works even when the on-disk CA predates SKI
    # (branding-era CAs). Chromium rejects leaves with Missing AKI.
    builder = (
        x509.CertificateBuilder()
        .subject_name(
            x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
        )
        .issuer_name(ca_cert.subject)
        .public_key(leaf_pub)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(leaf_pub), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_cert.public_key()),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
    )
    cert = builder.sign(ca_key, hashes.SHA256())
    key_path = CA_DIR / f"host_{host.replace('*', '_')}.key.pem"
    cert_path = CA_DIR / f"host_{host.replace('*', '_')}.cert.pem"
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    _HOST_CACHE[host] = (key_path, cert_path)
    return key_path, cert_path


def ssl_context_for_host(hostname: str) -> ssl.SSLContext:
    """Serve the MITM leaf only.

    The PharmFlow CA is installed into the guest system/user trust stores.
    Presenting leaf+CA fullchain made Android curl reject the handshake with
    ``self signed certificate in certificate chain`` and did not help
    FarmBrowser (CERTIFICATE_UNKNOWN is a trust-store / NSC problem, not a
    missing-intermediate problem).
    """
    key_path, cert_path = issue_host_cert(hostname)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    return ctx


def android_cacert_hash(cert: x509.Certificate) -> str:
    """OpenSSL subject_hash_old used by Android system store."""
    # Replicate OpenSSL 0.9.x subject_hash_old: MD5 of DER-encoded subject (old style).
    der = cert.subject.public_bytes()
    digest = hashlib.md5(der).digest()
    # little-endian first 4 bytes
    return f"{int.from_bytes(digest[:4], 'little'):08x}"


def install_ca_on_device(adb: object, serial: str) -> bool:
    """Install MITM CA into every guest trust store that exists.

    FarmBrowser NSC trusts ``system`` + ``user``. Returning after the first
    system copy left user empty and Conscrypt often ignored a freshly copied
    system file → CERTIFICATE_UNKNOWN while ``test -f`` still looked green.
    Apex is optional on MuMu (often missing); user store is the hot-reload path.
    """
    ensure_ca_files()
    cert = x509.load_pem_x509_certificate(CA_CERT.read_bytes())
    h = android_cacert_hash(cert)
    remote_name = f"{h}.0"
    pem_bytes = cert.public_bytes(serialization.Encoding.PEM)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".0") as tmp:
        # Android cacerts hash files expect PEM, not DER.
        tmp.write(pem_bytes)
        local = tmp.name
    remote_tmp = f"/data/local/tmp/{remote_name}"
    user_dest = "/data/misc/user/0/cacerts-added"
    system_dests = (
        "/apex/com.android.conscrypt/cacerts",
        "/system/etc/security/cacerts",
    )
    installed: list[str] = []
    try:
        push = adb.run("push", local, remote_tmp, serial=serial, timeout=30.0)  # type: ignore[attr-defined]
        if not getattr(push, "ok", True):
            logger.warning("CA push failed serial=%s", serial)
            return False
        id_res = adb.shell("id", serial=serial, timeout=8.0)  # type: ignore[union-attr]
        adbd_root = "uid=0(root)" in (id_res.stdout or "")

        def _copy_to(dest: str, *, mkdir: bool = False) -> bool:
            if mkdir:
                prep = (
                    f"mkdir -p {dest} && cp {remote_tmp} {dest}/{remote_name} "
                    f"&& chmod 644 {dest}/{remote_name} && echo OK"
                )
            else:
                probe = adb.shell(  # type: ignore[union-attr]
                    f"test -d {dest} && echo YES",
                    serial=serial,
                    timeout=8.0,
                )
                if "YES" not in (probe.stdout or ""):
                    return False
                prep = (
                    f"cp {remote_tmp} {dest}/{remote_name} "
                    f"&& chmod 644 {dest}/{remote_name} && echo OK"
                )
            cmds = [prep]
            if not adbd_root:
                cmds.append(f"su -c '{prep}'")
            for cmd in cmds:
                copy = adb.shell(cmd, serial=serial, timeout=20.0)  # type: ignore[union-attr]
                if "OK" in (copy.stdout or ""):
                    return True
            return False

        # User store first — no remount, NSC src="user" picks it up after app restart.
        if _copy_to(user_dest, mkdir=True):
            installed.append(user_dest)
            logger.info(
                "installed Mantis CA (user store) on %s -> %s/%s",
                serial,
                user_dest,
                remote_name,
            )

        for dest in system_dests:
            if adbd_root and _copy_to(dest):
                installed.append(dest)
                logger.info(
                    "installed Mantis CA (root fast path) on %s -> %s/%s",
                    serial,
                    dest,
                    remote_name,
                )
                continue
            check = adb.shell(  # type: ignore[union-attr]
                f"test -d {dest} && echo YES",
                serial=serial,
                timeout=10.0,
            )
            if "YES" not in (check.stdout or ""):
                check = adb.shell(  # type: ignore[union-attr]
                    f"su -c 'test -d {dest} && echo YES'",
                    serial=serial,
                    timeout=10.0,
                )
            if "YES" not in (check.stdout or ""):
                continue
            for rc in (
                "mount -o remount,rw /system || mount -o remount,rw / || true",
                "su -c 'mount -o remount,rw /system || true'",
            ):
                adb.shell(rc, serial=serial, timeout=15.0)  # type: ignore[union-attr]
            if _copy_to(dest):
                installed.append(dest)
                logger.info(
                    "installed Mantis CA on %s -> %s/%s",
                    serial,
                    dest,
                    remote_name,
                )
                continue
            # /system often RO on MuMu ARM — tmpfs/bind overlay.
            overlay = (
                f"STORE=/data/local/tmp/cacerts_store; TMP=/data/local/tmp/cacerts_overlay_{h}; "
                f"mkdir -p \"$STORE\" \"$TMP\"; "
                f"cp {dest}/* \"$TMP\"/ 2>/dev/null; "
                f"cp {remote_tmp} \"$TMP\"/{remote_name}; "
                f"cp \"$TMP\"/* \"$STORE\"/; "
                f"cp {remote_tmp} \"$STORE\"/{remote_name}; "
                f"chmod 644 \"$STORE\"/*; "
                f"mount | grep -q \" {dest} \" || mount --bind \"$STORE\" {dest} || mount -t tmpfs tmpfs {dest}; "
                f"cp \"$STORE\"/* {dest}/ 2>/dev/null; chmod 644 {dest}/*; "
                f"test -f {dest}/{remote_name} && echo OK"
            )
            for oc in (overlay, f"su -c '{overlay}'"):
                copy = adb.shell(oc, serial=serial, timeout=30.0)  # type: ignore[union-attr]
                if "OK" in (copy.stdout or ""):
                    installed.append(dest)
                    logger.info(
                        "installed Mantis CA via tmpfs overlay on %s -> %s",
                        serial,
                        dest,
                    )
                    break

        if not installed:
            logger.warning("CA install could not land on any store serial=%s", serial)
            return False
        return True
    except Exception as exc:
        logger.warning("CA install error serial=%s: %s", serial, exc)
        return False
    finally:
        try:
            os.unlink(local)
        except OSError:
            pass

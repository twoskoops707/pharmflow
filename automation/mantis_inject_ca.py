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

CA_DIR = Path(os.environ.get("CPHARM_MANTIS_CA_DIR") or r"C:\CPharm\certs\mantis_inject")
CA_KEY = CA_DIR / "ca.key.pem"
CA_CERT = CA_DIR / "ca.cert.pem"
_HOST_CACHE: dict[str, tuple[Path, Path]] = {}


def ensure_ca_files() -> tuple[Path, Path]:
    CA_DIR.mkdir(parents=True, exist_ok=True)
    if CA_KEY.is_file() and CA_CERT.is_file():
        return CA_KEY, CA_CERT
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "CPharm Mantis Inject"),
            x509.NameAttribute(NameOID.COMMON_NAME, "CPharm Mantis Inject CA"),
        ]
    )
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
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
        .sign(key, hashes.SHA256())
    )
    CA_KEY.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    CA_CERT.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    logger.info("wrote Mantis inject CA -> %s", CA_CERT)
    return CA_KEY, CA_CERT


def _load_ca() -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    ensure_ca_files()
    key = serialization.load_pem_private_key(CA_KEY.read_bytes(), password=None)
    cert = x509.load_pem_x509_certificate(CA_CERT.read_bytes())
    return key, cert  # type: ignore[return-value]


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
    cert = (
        x509.CertificateBuilder()
        .subject_name(
            x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
        )
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
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
    """Install CA as system trust on rooted MuMu. Returns True on success."""
    ensure_ca_files()
    cert = x509.load_pem_x509_certificate(CA_CERT.read_bytes())
    h = android_cacert_hash(cert)
    remote_name = f"{h}.0"
    pem_bytes = cert.public_bytes(serialization.Encoding.PEM)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".0") as tmp:
        # Android /system/etc/security/cacerts expects PEM, not DER.
        tmp.write(pem_bytes)
        local = tmp.name
    remote_tmp = f"/data/local/tmp/{remote_name}"
    try:
        push = adb.run("push", local, remote_tmp, serial=serial, timeout=30.0)  # type: ignore[attr-defined]
        if not getattr(push, "ok", True):
            logger.warning("CA push failed serial=%s", serial)
            return False
        # Fast path: when adbd is already root (MuMu ARM guests boot root), a
        # plain cp lands without su/remount/overlay — and every su -c variant
        # can hang 10-30s each on slow guests, stacking into minutes. Probe
        # once; if root, install directly into every store that exists.
        id_res = adb.shell("id", serial=serial, timeout=8.0)  # type: ignore[union-attr]
        adbd_root = "uid=0(root)" in (id_res.stdout or "")
        for dest in (
            "/apex/com.android.conscrypt/cacerts",
            "/system/etc/security/cacerts",
        ):
            if adbd_root:
                probe = adb.shell(  # type: ignore[union-attr]
                    f"test -d {dest} && echo YES",
                    serial=serial,
                    timeout=8.0,
                )
                if "YES" not in (probe.stdout or ""):
                    continue
                copy = adb.shell(  # type: ignore[union-attr]
                    f"cp {remote_tmp} {dest}/{remote_name} && chmod 644 {dest}/{remote_name} && echo OK",
                    serial=serial,
                    timeout=15.0,
                )
                if "OK" in (copy.stdout or ""):
                    logger.info("installed Mantis CA (root fast path) on %s -> %s/%s", serial, dest, remote_name)
                    return True
                continue
            # Prefer plain test first - some MuMu builds return empty/non-YES
            # from `su -c test -d` even when the dir is present (broke CA install
            # -> Chromium MITM inject untrusted -> Mantis stayed at 0 impr).
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
            # MuMu ARM adbd is often already root while `su` is broken - try
            # direct remount/cp first, then fall back to su -c.
            remount_cmds = (
                "mount -o remount,rw /system || mount -o remount,rw / || true",
                "su -c 'mount -o remount,rw /system || true'",
            )
            for rc in remount_cmds:
                adb.shell(rc, serial=serial, timeout=15.0)  # type: ignore[union-attr]
            copy_cmds = (
                f"cp {remote_tmp} {dest}/{remote_name} && chmod 644 {dest}/{remote_name} && echo OK",
                f"su -c 'cp {remote_tmp} {dest}/{remote_name} && chmod 644 {dest}/{remote_name} && echo OK'",
            )
            copied = False
            for cc in copy_cmds:
                copy = adb.shell(cc, serial=serial, timeout=20.0)  # type: ignore[union-attr]
                if "OK" in (copy.stdout or ""):
                    copied = True
                    break
            if not copied:
                # /system often RO on MuMu ARM (blockdev stays read-only). Overlay
                # cacerts with tmpfs so MITM CA still lands without remount.
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
                        copied = True
                        logger.info(
                            "installed Mantis CA via tmpfs overlay on %s -> %s",
                            serial,
                            dest,
                        )
                        break
                if not copied:
                    continue
            verify = adb.shell(  # type: ignore[union-attr]
                f"test -f {dest}/{remote_name} && echo PRESENT",
                serial=serial,
                timeout=10.0,
            )
            if "PRESENT" not in (verify.stdout or ""):
                verify = adb.shell(  # type: ignore[union-attr]
                    f"su -c 'test -f {dest}/{remote_name} && echo PRESENT'",
                    serial=serial,
                    timeout=10.0,
                )
            if "PRESENT" in (verify.stdout or ""):
                logger.info("installed Mantis CA on %s -> %s/%s", serial, dest, remote_name)
                return True
    except Exception as exc:
        logger.warning("CA install error serial=%s: %s", serial, exc)
        return False
    finally:
        try:
            os.unlink(local)
        except OSError:
            pass
    logger.warning("CA install could not find cacerts dir on %s", serial)
    return False

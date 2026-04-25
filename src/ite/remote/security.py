from __future__ import annotations

import hashlib
import ipaddress
import socket
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from platformdirs import user_data_dir


def remote_storage_dir() -> Path:
    candidates = [
        Path(user_data_dir("ite-agent", "iTE")) / "remote_bridge",
        Path(tempfile.gettempdir()) / "ite-agent" / "remote_bridge",
    ]
    for directory in candidates:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            return directory
        except OSError:
            continue
    raise RuntimeError("Unable to create remote bridge storage directory.")


def runtime_label() -> str:
    hostname = socket.gethostname().strip().lower() or "ite-runtime"
    return "".join(char if char.isalnum() or char == "-" else "-" for char in hostname).strip("-")


def load_or_create_tls_identity() -> dict[str, Any]:
    directory = remote_storage_dir()
    cert_path = directory / "bridge-cert.pem"
    key_path = directory / "bridge-key.pem"

    if not cert_path.exists() or not key_path.exists():
        _generate_tls_identity(cert_path=cert_path, key_path=key_path)

    cert_bytes = cert_path.read_bytes()
    cert = x509.load_pem_x509_certificate(cert_bytes)
    fingerprint = f"sha256:{cert.fingerprint(hashes.SHA256()).hex()}"
    subject = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    common_name = subject[0].value if subject else runtime_label()

    return {
        "cert_path": cert_path,
        "key_path": key_path,
        "fingerprint": fingerprint,
        "runtime_name": common_name,
    }


def _generate_tls_identity(*, cert_path: Path, key_path: Path) -> None:
    private_key = ec.generate_private_key(ec.SECP256R1())
    name = runtime_label() or "ite-runtime"
    now = datetime.now(timezone.utc)

    san_values: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.DNSName(name),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
    ]

    try:
        san_values.append(x509.IPAddress(ipaddress.ip_address("::1")))
    except ValueError:
        pass

    certificate = (
        x509.CertificateBuilder()
        .subject_name(
            x509.Name(
                [
                    x509.NameAttribute(NameOID.COMMON_NAME, name),
                    x509.NameAttribute(NameOID.ORGANIZATION_NAME, "iTE Remote Bridge"),
                ]
            )
        )
        .issuer_name(
            x509.Name(
                [
                    x509.NameAttribute(NameOID.COMMON_NAME, name),
                    x509.NameAttribute(NameOID.ORGANIZATION_NAME, "iTE Remote Bridge"),
                ]
            )
        )
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName(san_values), critical=False)
        .sign(private_key, hashes.SHA256())
    )

    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )


def redact_secure_link(value: str) -> str:
    if not value:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"<secure-link:{digest}>"

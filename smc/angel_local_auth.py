"""Local Angel credentials for read-only SmartAPI tooling.

Only explicit project-root .env and process environment are used. The TOTP
seed, if enrolled, is stored in the OS-backed keyring, never in .env.
No credentials are sent to logs, reports or GitHub.
"""
from __future__ import annotations

import os
from getpass import getpass
from pathlib import Path

ENV_KEYS = ("ANGEL_API_KEY", "ANGEL_CLIENT_ID", "ANGEL_MPIN")
OPTIONAL_ENV_KEYS = ("ANGEL_TOTP_KEY",)
ALL_ENV_KEYS = ENV_KEYS + OPTIONAL_ENV_KEYS
SERVICE = "SMC.AngelOne.TOTP.v1"


class CredentialError(RuntimeError):
    """Sanitized errors; exception text must not expose secrets."""


def load_local_env(path: str | Path | None = None, *,
                   environ: dict[str, str] | None = None) -> dict[str, str]:
    """Read only approved .env keys, without modifying os.environ.

    Explicit environment variables win over .env. No shell evaluation,
    variable expansion, multiline values or arbitrary dotenv execution.
    """
    target = Path(path) if path is not None else Path(__file__).resolve().parent.parent / ".env"
    parsed: dict[str, str] = {}
    if target.is_file():
        try:
            for line in target.read_text(encoding="utf-8-sig").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if "=" not in stripped:
                    raise CredentialError("INVALID_ENV_FILE")
                key, value = (x.strip() for x in stripped.split("=", 1))
                if key not in ALL_ENV_KEYS or key in parsed:
                    raise CredentialError("UNSUPPORTED_OR_DUPLICATE_ENV_KEY")
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                    value = value[1:-1]
                if not value or "\x00" in value:
                    raise CredentialError("INVALID_ENV_VALUE")
                parsed[key] = value
        except OSError:
            raise CredentialError("ENV_FILE_UNREADABLE") from None
    env = os.environ if environ is None else environ
    out = {key: str(env.get(key) or parsed.get(key) or "").strip()
           for key in ENV_KEYS}
    for opt in OPTIONAL_ENV_KEYS:
        val = str(env.get(opt) or parsed.get(opt) or "").strip()
        if val:
            out[opt] = val
    return out


def resolve_login_fields(values: dict[str, str], *,
                         prompt=getpass) -> tuple[str, str, str]:
    """Prompt for missing values; never echo the PIN or API key."""
    prompts = {
        "ANGEL_API_KEY": "SmartAPI Key (hidden): ",
        "ANGEL_CLIENT_ID": "Angel Client ID (hidden): ",
        "ANGEL_MPIN": "Angel MPIN (hidden): ",
    }
    resolved = {}
    for key in ENV_KEYS:
        resolved[key] = (values.get(key) or "").strip() or prompt(prompts[key]).strip()
        if not resolved[key]:
            raise CredentialError("MISSING_" + key)
    return resolved["ANGEL_API_KEY"], resolved["ANGEL_CLIENT_ID"], resolved["ANGEL_MPIN"]


def read_totp_seed(*, env_values: dict[str, str] | None = None,
                   keyring_module=None) -> str | None:
    """Read OS-managed seed, only when the operator installed keyring."""
    if env_values and env_values.get("ANGEL_TOTP_KEY"):
        return env_values["ANGEL_TOTP_KEY"].strip()
    if keyring_module is None and os.environ.get("ANGEL_TOTP_KEY"):
        return os.environ["ANGEL_TOTP_KEY"].strip()
    if keyring_module is None:
        try:
            import keyring as keyring_module
        except ImportError:
            return None
    try:
        seed = keyring_module.get_password(SERVICE, "angel_totp_seed")
    except Exception:
        raise CredentialError("WINDOWS_CREDENTIAL_STORE_UNAVAILABLE") from None
    return seed or None


def current_totp(*, env_values: dict[str, str] | None = None,
                 keyring_module=None, pyotp_module=None,
                 prompt=getpass) -> str:
    seed = read_totp_seed(env_values=env_values, keyring_module=keyring_module)
    if seed:
        try:
            if pyotp_module is None:
                import pyotp as pyotp_module
            code = pyotp_module.TOTP(seed.replace(" ", "")).now()
        except Exception:
            raise CredentialError("TOTP_GENERATION_FAILED") from None
    else:
        code = prompt("Authenticator current 6-digit TOTP (hidden): ").strip()
    if len(code) != 6 or not code.isdecimal():
        raise CredentialError("INVALID_TOTP_FORMAT")
    return code


def manage_totp_secret(*, enroll: bool = False, delete: bool = False,
                       prompt=getpass, keyring_module=None) -> None:
    """One-time local enrollment: prompt, validate, save in OS keyring."""
    if enroll == delete:
        raise CredentialError("SELECT_ENROLL_OR_DELETE")
    if os.name != "nt" and keyring_module is None:
        raise CredentialError("WINDOWS_ONLY_CREDENTIAL_STORE")
    if keyring_module is None:
        try:
            import keyring as keyring_module
        except ImportError:
            raise CredentialError("KEYRING_DEPENDENCY_MISSING") from None
    try:
        if delete:
            keyring_module.delete_password(SERVICE, "angel_totp_seed")
            return
        seed = prompt("Angel authenticator setup secret (hidden, NOT 6-digit code): ").strip().replace(" ", "")
        try:
            import pyotp
            # Validate without logging or printing the secret.
            pyotp.TOTP(seed).now()
        except Exception:
            raise CredentialError("INVALID_TOTP_SEED") from None
        keyring_module.set_password(SERVICE, "angel_totp_seed", seed)
    except CredentialError:
        raise
    except Exception:
        raise CredentialError("WINDOWS_CREDENTIAL_STORE_UNAVAILABLE") from None

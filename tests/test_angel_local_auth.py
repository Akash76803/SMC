"""Local credential loading and opt-in OTP storage. Never use real secrets."""
from pathlib import Path
from types import SimpleNamespace
import pytest

from smc.angel_local_auth import (
    CredentialError, SERVICE, load_local_env, resolve_login_fields,
    read_totp_seed, current_totp, manage_totp_secret,
)


class Keyring:
    def __init__(self, seed=None):
        self.seed = seed
        self.writes = []
    def get_password(self, service, account):
        assert service == SERVICE
        assert account == "angel_totp_seed"
        return self.seed
    def set_password(self, service, account, secret):
        self.writes.append((service, account))
        self.seed = secret
    def delete_password(self, service, account):
        self.seed = None


def test_dotenv_read_strictly_without_process_mutation(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("# local only\nANGEL_API_KEY=fake_key\nANGEL_CLIENT_ID=fake_id\nANGEL_MPIN='fake_pin'\n")
    monkeypatch.delenv("ANGEL_API_KEY", raising=False)
    values = load_local_env(path, environ={})
    assert values == {"ANGEL_API_KEY": "fake_key", "ANGEL_CLIENT_ID": "fake_id",
                      "ANGEL_MPIN": "fake_pin"}
    assert "ANGEL_API_KEY" not in __import__("os").environ


def test_process_environment_takes_priority(tmp_path):
    path = tmp_path / ".env"
    path.write_text("ANGEL_API_KEY=file_key\nANGEL_CLIENT_ID=file_id\nANGEL_MPIN=file_pin\n")
    values = load_local_env(path, environ={"ANGEL_API_KEY": "env_key"})
    assert values["ANGEL_API_KEY"] == "env_key"
    assert values["ANGEL_CLIENT_ID"] == "file_id"


def test_missing_values_prompt_without_printing(tmp_path):
    values = load_local_env(tmp_path / ".env", environ={})
    inputs = iter(("test_key", "test_id", "test_pin"))
    assert resolve_login_fields(values, prompt=lambda label: next(inputs)) == (
        "test_key", "test_id", "test_pin")


def test_bad_env_does_not_expose_values(tmp_path):
    path = tmp_path / ".env"
    path.write_text("EVIL_KEY=MY_REAL_PRIVATE_VALUE\n")
    with pytest.raises(CredentialError) as e:
        load_local_env(path, environ={})
    assert "MY_REAL_PRIVATE_VALUE" not in str(e.value)


def test_duplicate_env_rejected(tmp_path):
    path = tmp_path / ".env"
    path.write_text("ANGEL_MPIN=a\nANGEL_MPIN=b\n")
    with pytest.raises(CredentialError, match="DUPLICATE"):
        load_local_env(path, environ={})


def test_totp_current_manual_fallback():
    kr = Keyring()
    assert current_totp(keyring_module=kr, prompt=lambda _: "123456") == "123456"
    with pytest.raises(CredentialError, match="INVALID_TOTP_FORMAT"):
        current_totp(keyring_module=kr, prompt=lambda _: "12345")


def test_auto_totp_from_os_managed_keyring():
    kr = Keyring("DUMMY_SEED")
    fake = SimpleNamespace(TOTP=lambda seed: SimpleNamespace(now=lambda: "654321"))
    assert current_totp(keyring_module=kr, pyotp_module=fake,
                        prompt=lambda _: pytest.fail("should not prompt")) == "654321"


def test_keyring_error_sanitized():
    class Broken:
        def get_password(self, service, account):
            raise RuntimeError("SECRET_FAIL")
    with pytest.raises(CredentialError) as e:
        read_totp_seed(keyring_module=Broken())
    assert "SECRET_FAIL" not in str(e.value)


def test_keyring_delete_does_not_require_totp_seed():
    kr = Keyring("dummy")
    manage_totp_secret(delete=True, keyring_module=kr)
    assert kr.seed is None

"""Master-password credential vault — encrypts LLM/enrichment API keys and the
Gmail OAuth client secret at rest, so a single password unlocks everything for
the session instead of every credential sitting in plaintext config.json.

Design (see DOCS/job-watcher-master-plan.md decision #24):
- vault.dat (gitignored, backend/vault.dat) holds {"salt": b64, "token": b64}
  — token is a Fernet ciphertext of a JSON secrets dict, key derived from the
  master password via PBKDF2-HMAC-SHA256 (480k iterations) + the stored salt.
- Once unlocked, the derived Fernet key and decrypted secrets live ONLY in
  memory (module-level, this process) — cleared on lock() or process restart.
  The password itself is never retained past the call that supplied it.
- Backward compatible on purpose: until a vault is actually initialized (the
  user opts in via Setup), callers fall back to the pre-existing plaintext
  config.json fields exactly as before — see config.py / llm.py / gmail.py.
  This repo's config.json already holds real, working API keys; the vault
  must not silently break that setup for a user who hasn't opted in yet.
"""

import base64
import json
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
VAULT_PATH = os.path.join(BACKEND_DIR, "vault.dat")
KDF_ITERATIONS = 480_000

# In-memory only, this process, cleared on lock()/restart. None = locked.
_fernet = None
_secrets = None


class VaultLockedError(RuntimeError):
    pass


def is_initialized():
    return os.path.exists(VAULT_PATH)


def is_unlocked():
    return _secrets is not None


def _derive_key(password, salt):
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=KDF_ITERATIONS)
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def _read_file():
    with open(VAULT_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return base64.b64decode(raw["salt"]), base64.b64decode(raw["token"])


def _write_file(salt, token_bytes):
    with open(VAULT_PATH, "w", encoding="utf-8") as f:
        json.dump({"salt": base64.b64encode(salt).decode("ascii"),
                    "token": base64.b64encode(token_bytes).decode("ascii")}, f)


def _persist():
    token = _fernet.encrypt(json.dumps(_secrets, ensure_ascii=False).encode("utf-8"))
    salt, _ = _read_file()
    _write_file(salt, token)


def init_vault(password, initial_secrets=None):
    """Creates a new vault with the given master password. Raises RuntimeError
    if one already exists (use unlock() + change_password() to rotate).
    Auto-unlocks in memory afterward, since the caller just proved they know
    the password by choosing it."""
    global _fernet, _secrets
    if is_initialized():
        raise RuntimeError("Vault already initialized — unlock it instead.")
    salt = os.urandom(16)
    secrets = dict(initial_secrets or {})
    key = _derive_key(password, salt)
    fernet = Fernet(key)
    token = fernet.encrypt(json.dumps(secrets, ensure_ascii=False).encode("utf-8"))
    _write_file(salt, token)
    _fernet, _secrets = fernet, secrets


def unlock(password):
    """Returns True/False rather than raising on a wrong password — callers
    (the /vault/unlock route) turn False into a 401, not a 500."""
    global _fernet, _secrets
    if not is_initialized():
        raise RuntimeError("Vault not initialized yet.")
    salt, token = _read_file()
    key = _derive_key(password, salt)
    fernet = Fernet(key)
    try:
        plaintext = fernet.decrypt(token)
    except InvalidToken:
        return False
    _fernet, _secrets = fernet, json.loads(plaintext.decode("utf-8"))
    return True


def lock():
    global _fernet, _secrets
    _fernet, _secrets = None, None


def change_password(new_password):
    """Re-encrypts the currently-unlocked secrets under a new password + fresh
    salt. Requires the vault to already be unlocked."""
    global _fernet
    if _secrets is None:
        raise VaultLockedError("Vault is locked — unlock it before changing the password.")
    salt = os.urandom(16)
    key = _derive_key(new_password, salt)
    fernet = Fernet(key)
    token = fernet.encrypt(json.dumps(_secrets, ensure_ascii=False).encode("utf-8"))
    _write_file(salt, token)
    _fernet = fernet


def get_secret(key, default=None):
    if _secrets is None:
        raise VaultLockedError("Vault is locked.")
    return _secrets.get(key, default)


def set_secret(key, value):
    if _secrets is None:
        raise VaultLockedError("Vault is locked.")
    _secrets[key] = value
    _persist()


def delete_secret(key):
    if _secrets is None:
        raise VaultLockedError("Vault is locked.")
    if key in _secrets:
        del _secrets[key]
        _persist()


def migrate_plaintext_secrets():
    """One-time: pulls existing plaintext secrets (config.json's llm provider
    api_keys + legacy anthropic_api_key, backend/client_secret.json's raw
    content if present) into the now-unlocked vault, then clears them from
    config.json / renames client_secret.json aside. Call right after
    init_vault() while still unlocked. Returns the list of secret keys
    migrated, for a confirmation message."""
    if _secrets is None:
        raise VaultLockedError("Vault is locked.")
    import config as config_module  # local import avoids a circular import at module load

    migrated = []
    cfg = config_module.load_config()
    llm_cfg = cfg.get("llm") or {}
    providers = dict(llm_cfg.get("providers") or {})

    for provider_id, meta in list(providers.items()):
        api_key = (meta or {}).get("api_key")
        if api_key:
            set_secret(f"llm:{provider_id}", api_key)
            migrated.append(f"llm:{provider_id}")
            if meta.get("custom"):
                providers[provider_id] = dict(meta, api_key="", has_key=True)
            else:
                providers[provider_id] = {"has_key": True}

    legacy_key = cfg.get("anthropic_api_key")
    if legacy_key and "anthropic" not in providers:
        set_secret("llm:anthropic", legacy_key)
        migrated.append("llm:anthropic")
        providers["anthropic"] = {"has_key": True}

    llm_cfg["providers"] = providers
    cfg["llm"] = llm_cfg
    cfg.pop("anthropic_api_key", None)
    cfg.pop("anthropic_model", None)
    config_module.write_config(cfg)

    client_secret_path = os.path.join(BACKEND_DIR, "client_secret.json")
    if os.path.exists(client_secret_path):
        with open(client_secret_path, "r", encoding="utf-8") as f:
            content = f.read()
        set_secret("gmail_client_secret_json", content)
        migrated.append("gmail_client_secret_json")
        os.replace(client_secret_path, client_secret_path + ".migrated-to-vault.bak")

    return migrated

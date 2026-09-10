import base64
import hashlib
import json
import os
import re
import secrets
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from cryptography.fernet import Fernet

try:
    import psycopg
except ImportError:  # pragma: no cover - dependency is installed in production
    psycopg = None


class MercadoLibreOAuth:
    AUTH_URL = "https://auth.mercadolibre.com.mx/authorization"
    TOKEN_URL = "https://api.mercadolibre.com/oauth/token"
    TOKEN_DB_KEY = "mercadolibre_primary"
    STATE_DB_PREFIX = "mercadolibre_oauth_state:"

    def __init__(self):
        self.client_id = os.getenv("ML_CLIENT_ID", "")
        self.client_secret = os.getenv("ML_CLIENT_SECRET", "")
        self.redirect_uri = os.getenv("ML_REDIRECT_URI", "")
        self.state_file = os.getenv("ML_OAUTH_STATE_FILE", "ml_oauth_state.json")
        self.token_file = os.getenv("ML_TOKEN_FILE", "ml_tokens.enc")
        self.token_key = os.getenv("AUTOBRILLO_TOKEN_KEY", "")
        self.database_url = os.getenv("DATABASE_URL", "")
        self.site = os.getenv("ML_SITE", "MLM")
        self.pkce_enabled = os.getenv("ML_PKCE_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}

    def configured(self):
        return all((self.client_id, self.client_secret, self.redirect_uri, self.token_key))

    def database_configured(self):
        return bool(self.database_url and psycopg)

    def _db_url(self):
        if not self.database_url:
            return ""
        if "sslmode=" in self.database_url.lower():
            return self.database_url
        separator = "&" if "?" in self.database_url else "?"
        return f"{self.database_url}{separator}sslmode=require"

    def _fernet(self):
        return Fernet(self.token_key.encode())

    def _db_enabled(self):
        return self.database_configured()

    def _ensure_db(self):
        if not self._db_enabled():
            return False
        with psycopg.connect(self._db_url()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS autobrillo_oauth_tokens (
                    token_key TEXT PRIMARY KEY,
                    token_encrypted BYTEA NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS autobrillo_oauth_state (
                    state_key TEXT PRIMARY KEY,
                    state_encrypted BYTEA NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            conn.commit()
        return True

    def _save_token(self, token):
        encrypted = self._fernet().encrypt(json.dumps(token).encode())
        if self._db_enabled():
            try:
                self._ensure_db()
                with psycopg.connect(self._db_url()) as conn:
                    conn.execute(
                        """
                        INSERT INTO autobrillo_oauth_tokens (token_key, token_encrypted, updated_at)
                        VALUES (%s, %s, NOW())
                        ON CONFLICT (token_key) DO UPDATE SET
                            token_encrypted = EXCLUDED.token_encrypted,
                            updated_at = NOW()
                        """,
                        (self.TOKEN_DB_KEY, encrypted),
                    )
                    conn.commit()
                return
            except Exception:
                # Keep OAuth usable during a temporary DB outage.
                pass
        with open(self.token_file, "wb") as f:
            f.write(encrypted)

    def _save_state(self, state_data):
        encrypted = self._fernet().encrypt(json.dumps(state_data).encode())
        if self._db_enabled():
            try:
                self._ensure_db()
                with psycopg.connect(self._db_url()) as conn:
                    conn.execute(
                        """
                        INSERT INTO autobrillo_oauth_state (state_key, state_encrypted, updated_at)
                        VALUES (%s, %s, NOW())
                        ON CONFLICT (state_key) DO UPDATE SET
                            state_encrypted = EXCLUDED.state_encrypted,
                            updated_at = NOW()
                        """,
                        (self.STATE_DB_PREFIX + state_data["state"], encrypted),
                    )
                    conn.commit()
                return
            except Exception:
                # A transient DB failure must not turn /oauth/start into a 500.
                pass
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(state_data, f)

    def _load_state(self, state):
        if self._db_enabled():
            try:
                self._ensure_db()
                with psycopg.connect(self._db_url()) as conn:
                    row = conn.execute(
                        "SELECT state_encrypted FROM autobrillo_oauth_state WHERE state_key = %s",
                        (self.STATE_DB_PREFIX + state,),
                    ).fetchone()
                if row:
                    return json.loads(self._fernet().decrypt(bytes(row[0])).decode())
            except Exception:
                # Fall through to the short-lived local OAuth state file.
                pass
        try:
            with open(self.state_file, encoding="utf-8") as f:
                saved = json.load(f)
        except FileNotFoundError:
            raise
        if saved.get("state") != state:
            raise FileNotFoundError
        return saved

    def _delete_state(self, state):
        if self._db_enabled():
            try:
                self._ensure_db()
                with psycopg.connect(self._db_url()) as conn:
                    conn.execute(
                        "DELETE FROM autobrillo_oauth_state WHERE state_key = %s",
                        (self.STATE_DB_PREFIX + state,),
                    )
                    conn.commit()
            except Exception:
                pass
        try:
            os.remove(self.state_file)
        except OSError:
            pass

    def start(self):
        if not self.configured():
            raise RuntimeError("Configura ML_CLIENT_ID, ML_CLIENT_SECRET, ML_REDIRECT_URI y AUTOBRILLO_TOKEN_KEY")

        state = secrets.token_urlsafe(32)
        state_data = {"state": state, "created_at": time.time()}
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "state": state,
        }

        if self.pkce_enabled:
            verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            state_data["verifier"] = verifier
            params["code_challenge"] = challenge
            params["code_challenge_method"] = "S256"

        self._save_state(state_data)
        return self.AUTH_URL + "?" + urlencode(params)

    @staticmethod
    def _safe_error_text(value: str) -> str:
        text = value[:1000]
        patterns = [
            r"(?i)(client[_-]?secret|secret[_-]?key|access[_-]?token|refresh[_-]?token|code[_-]?verifier|authorization[_-]?code)\s*[:=]\s*[^,;\s}]+",
            r"(?i)APP_USR-[A-Za-z0-9._-]+",
            r"(?i)TG-[A-Za-z0-9._-]+",
        ]
        for pattern in patterns:
            text = re.sub(pattern, lambda m: m.group(0).split(":", 1)[0].split("=", 1)[0] + "=[redacted]", text)
        return text.strip()

    def exchange(self, code, state):
        if not self.configured():
            raise RuntimeError("OAuth no está configurado.")
        if not state:
            raise RuntimeError("State OAuth inválido. Inicia nuevamente la conexión desde AutoBrillo.")

        try:
            saved = self._load_state(state)
        except FileNotFoundError:
            raise RuntimeError("No existe un estado OAuth activo. Inicia nuevamente la conexión desde AutoBrillo.") from None
        except Exception as exc:
            raise RuntimeError(f"No se pudo recuperar el estado OAuth: {self._safe_error_text(str(exc))}") from None

        if not secrets.compare_digest(state, saved.get("state", "")):
            raise RuntimeError("State OAuth inválido. Inicia nuevamente la conexión desde AutoBrillo.")
        if time.time() - float(saved.get("created_at", 0)) > 600:
            self._delete_state(state)
            raise RuntimeError("State OAuth expirado. Inicia nuevamente la conexión desde AutoBrillo.")

        payload = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": self.redirect_uri,
        }
        if self.pkce_enabled:
            verifier = saved.get("verifier")
            if not verifier:
                raise RuntimeError("Falta el code_verifier de OAuth. Inicia nuevamente la conexión.")
            payload["code_verifier"] = verifier

        req = Request(
            self.TOKEN_URL,
            data=urlencode(payload).encode(),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "AutoBrillo-AI/6.4",
            },
        )

        try:
            with urlopen(req, timeout=20) as response:
                token = json.loads(response.read().decode())
        except HTTPError as exc:
            try:
                raw = exc.read().decode("utf-8", errors="replace")
                try:
                    details = json.loads(raw)
                except json.JSONDecodeError:
                    details = {}
                error = details.get("error") or details.get("code")
                message = details.get("message") or details.get("error_description")
                detail = f"{error or 'http_error'} — {message or 'sin mensaje'}" if (error or message) else (self._safe_error_text(raw) or "Sin detalle adicional.")
            except Exception:
                detail = "Sin detalle adicional."
            raise RuntimeError(f"Mercado Libre rechazó el intercambio (HTTP {exc.code}): {detail}") from None
        except Exception as exc:
            raise RuntimeError(f"No se pudo contactar a Mercado Libre: {self._safe_error_text(str(exc))}") from None

        self._save_token(token)
        self._delete_state(state)
        return token

    def load_token(self):
        if self._db_enabled():
            try:
                self._ensure_db()
                with psycopg.connect(self._db_url()) as conn:
                    row = conn.execute(
                        "SELECT token_encrypted FROM autobrillo_oauth_tokens WHERE token_key = %s",
                        (self.TOKEN_DB_KEY,),
                    ).fetchone()
                if row:
                    return json.loads(self._fernet().decrypt(bytes(row[0])).decode())
            except Exception:
                pass
        with open(self.token_file, "rb") as f:
            return json.loads(self._fernet().decrypt(f.read()).decode())

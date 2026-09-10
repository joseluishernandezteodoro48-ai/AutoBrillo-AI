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
except ImportError:
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
        self.site = os.getenv("ML_SITE", "MLM").strip().upper() or "MLM"
        self.pkce_enabled = os.getenv("ML_PKCE_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}

    def configured(self):
        return all((self.client_id, self.client_secret, self.redirect_uri, self.token_key))

    def database_configured(self):
        return bool(self.database_url and "${" not in self.database_url and psycopg)

    def _db_url(self):
        if not self.database_configured():
            return ""
        if "sslmode=" in self.database_url.lower():
            return self.database_url
        return self.database_url + ("&" if "?" in self.database_url else "?") + "sslmode=require"

    def _fernet(self):
        if not self.token_key:
            raise RuntimeError("AUTOBRILLO_TOKEN_KEY no está configurada.")
        return Fernet(self.token_key.encode())

    def _ensure_db(self):
        if not self.database_configured():
            return False
        with psycopg.connect(self._db_url()) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS autobrillo_oauth_tokens (token_key TEXT PRIMARY KEY, token_encrypted BYTEA NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())")
            conn.execute("CREATE TABLE IF NOT EXISTS autobrillo_oauth_state (state_key TEXT PRIMARY KEY, state_encrypted BYTEA NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())")
            conn.commit()
        return True

    def _save_token(self, token):
        token = dict(token)
        expires_in = int(token.get("expires_in") or 0)
        token["expires_at"] = int(time.time()) + max(0, expires_in - 60) if expires_in else 0
        encrypted = self._fernet().encrypt(json.dumps(token).encode())
        if self.database_configured():
            try:
                self._ensure_db()
                with psycopg.connect(self._db_url()) as conn:
                    conn.execute("INSERT INTO autobrillo_oauth_tokens(token_key,token_encrypted,updated_at) VALUES(%s,%s,NOW()) ON CONFLICT(token_key) DO UPDATE SET token_encrypted=EXCLUDED.token_encrypted,updated_at=NOW()", (self.TOKEN_DB_KEY, encrypted))
                    conn.commit()
                return
            except Exception:
                pass
        with open(self.token_file, "wb") as f:
            f.write(encrypted)

    def _load_token_record(self):
        if self.database_configured():
            try:
                self._ensure_db()
                with psycopg.connect(self._db_url()) as conn:
                    row = conn.execute("SELECT token_encrypted FROM autobrillo_oauth_tokens WHERE token_key=%s", (self.TOKEN_DB_KEY,)).fetchone()
                if row:
                    return json.loads(self._fernet().decrypt(bytes(row[0])).decode())
            except Exception:
                pass
        try:
            with open(self.token_file, "rb") as f:
                return json.loads(self._fernet().decrypt(f.read()).decode())
        except FileNotFoundError:
            return None
        except Exception as exc:
            raise RuntimeError("No se pudo leer el token seguro de Mercado Libre.") from exc

    def access_token(self):
        token = self._load_token_record()
        if not token:
            return ""
        access = str(token.get("access_token") or "")
        expires_at = int(token.get("expires_at") or 0)
        if access and (not expires_at or time.time() < expires_at):
            return access
        refresh = str(token.get("refresh_token") or "")
        if not refresh:
            return access
        try:
            return str(self.refresh(refresh).get("access_token") or "")
        except Exception:
            return access

    def refresh(self, refresh_token):
        if not self.configured():
            raise RuntimeError("OAuth no está configurado.")
        payload = {"grant_type": "refresh_token", "client_id": self.client_id, "client_secret": self.client_secret, "refresh_token": refresh_token}
        req = Request(self.TOKEN_URL, data=urlencode(payload).encode(), headers={"Accept":"application/json","Content-Type":"application/x-www-form-urlencoded","User-Agent":"AutoBrillo-AI/7.0"})
        try:
            with urlopen(req, timeout=20) as response:
                token = json.loads(response.read().decode())
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Mercado Libre rechazó la renovación (HTTP {exc.code}): {self._safe_error_text(raw)}") from None
        self._save_token(token)
        return token

    def _save_state(self, state_data):
        encrypted = self._fernet().encrypt(json.dumps(state_data).encode())
        if self.database_configured():
            try:
                self._ensure_db()
                with psycopg.connect(self._db_url()) as conn:
                    conn.execute("INSERT INTO autobrillo_oauth_state(state_key,state_encrypted,updated_at) VALUES(%s,%s,NOW()) ON CONFLICT(state_key) DO UPDATE SET state_encrypted=EXCLUDED.state_encrypted,updated_at=NOW()", (self.STATE_DB_PREFIX + state_data["state"], encrypted))
                    conn.commit()
                return
            except Exception:
                pass
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(state_data, f)

    def _load_state(self, state):
        if self.database_configured():
            try:
                self._ensure_db()
                with psycopg.connect(self._db_url()) as conn:
                    row = conn.execute("SELECT state_encrypted FROM autobrillo_oauth_state WHERE state_key=%s", (self.STATE_DB_PREFIX + state,)).fetchone()
                if row:
                    return json.loads(self._fernet().decrypt(bytes(row[0])).decode())
            except Exception:
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
        if self.database_configured():
            try:
                self._ensure_db()
                with psycopg.connect(self._db_url()) as conn:
                    conn.execute("DELETE FROM autobrillo_oauth_state WHERE state_key=%s", (self.STATE_DB_PREFIX + state,))
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
        params = {"response_type":"code","client_id":self.client_id,"redirect_uri":self.redirect_uri,"state":state}
        if self.pkce_enabled:
            verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            state_data["verifier"] = verifier
            params.update({"code_challenge":challenge,"code_challenge_method":"S256"})
        self._save_state(state_data)
        return self.AUTH_URL + "?" + urlencode(params)

    @staticmethod
    def _safe_error_text(value):
        text = value[:1000]
        for pattern in [r"(?i)(client[_-]?secret|secret[_-]?key|access[_-]?token|refresh[_-]?token|code[_-]?verifier|authorization[_-]?code)\s*[:=]\s*[^,;\s}]+", r"(?i)APP(?:_USR)?-[A-Za-z0-9._-]+", r"(?i)TG-[A-Za-z0-9._-]+"]:
            text = re.sub(pattern, "[redacted]", text)
        return text.strip()

    def exchange(self, code, state):
        if not self.configured():
            raise RuntimeError("OAuth no está configurado.")
        try:
            saved = self._load_state(state)
        except FileNotFoundError:
            raise RuntimeError("No existe un estado OAuth activo. Inicia nuevamente la conexión desde AutoBrillo.") from None
        if not secrets.compare_digest(state, saved.get("state", "")):
            raise RuntimeError("State OAuth inválido. Inicia nuevamente la conexión desde AutoBrillo.")
        if time.time() - float(saved.get("created_at", 0)) > 600:
            self._delete_state(state)
            raise RuntimeError("State OAuth expirado. Inicia nuevamente la conexión desde AutoBrillo.")
        payload = {"grant_type":"authorization_code","client_id":self.client_id,"client_secret":self.client_secret,"code":code,"redirect_uri":self.redirect_uri}
        if self.pkce_enabled:
            verifier = saved.get("verifier")
            if not verifier:
                raise RuntimeError("Falta el code_verifier de OAuth. Inicia nuevamente la conexión.")
            payload["code_verifier"] = verifier
        req = Request(self.TOKEN_URL, data=urlencode(payload).encode(), headers={"Accept":"application/json","Content-Type":"application/x-www-form-urlencoded","User-Agent":"AutoBrillo-AI/7.0"})
        try:
            with urlopen(req, timeout=20) as response:
                token = json.loads(response.read().decode())
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                details = json.loads(raw)
            except json.JSONDecodeError:
                details = {}
            error = details.get("error") or details.get("code")
            message = details.get("message") or details.get("error_description")
            detail = f"{error or 'http_error'} — {message or 'sin mensaje'}" if (error or message) else (self._safe_error_text(raw) or "sin detalle adicional")
            raise RuntimeError(f"Mercado Libre rechazó el intercambio (HTTP {exc.code}): {detail}") from None
        self._save_token(token)
        self._delete_state(state)
        return token

    def load_token(self):
        token = self._load_token_record()
        if not token:
            raise RuntimeError("Mercado Libre no está conectado. Pulsa 'Conectar Mercado Libre' para autorizarlo.")
        return token

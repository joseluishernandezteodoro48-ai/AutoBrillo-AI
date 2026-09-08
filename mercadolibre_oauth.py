"""Mercado Libre OAuth 2.0 + PKCE connector for AutoBrillo AI v5.

Secrets are read from environment variables. Tokens are stored encrypted when
AUTOBRILLO_TOKEN_KEY is configured; never put credentials in source control.
"""
import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class MercadoLibreOAuth:
    def __init__(self):
        self.client_id = os.getenv("ML_CLIENT_ID", "")
        self.client_secret = os.getenv("ML_CLIENT_SECRET", "")
        self.redirect_uri = os.getenv("ML_REDIRECT_URI", "")
        self.site = os.getenv("ML_SITE", "MLM")
        self.token_file = Path(os.getenv("ML_TOKEN_FILE", "ml_tokens.enc"))
        self.state_file = Path(os.getenv("ML_OAUTH_STATE_FILE", "ml_oauth_state.json"))
        self.auth_base = f"https://auth.mercadolibre.com.mx/authorization"
        self.token_url = "https://api.mercadolibre.com/oauth/token"

    def configured(self):
        return all((self.client_id, self.client_secret, self.redirect_uri))

    @staticmethod
    def _b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    def start(self) -> str:
        if not self.configured():
            raise RuntimeError("Faltan ML_CLIENT_ID, ML_CLIENT_SECRET o ML_REDIRECT_URI")
        verifier = self._b64(secrets.token_bytes(32))
        challenge = self._b64(hashlib.sha256(verifier.encode()).digest())
        state = secrets.token_urlsafe(32)
        self.state_file.write_text(json.dumps({
            "state": state,
            "code_verifier": verifier,
            "created_at": time.time(),
        }), encoding="utf-8")
        try:
            os.chmod(self.state_file, 0o600)
        except OSError:
            pass
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return self.auth_base + "?" + urlencode(params)

    def exchange(self, code: str, state: str):
        saved = json.loads(self.state_file.read_text(encoding="utf-8"))
        if not secrets.compare_digest(state, saved["state"]):
            raise RuntimeError("OAuth state inválido")
        body = urlencode({
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": self.redirect_uri,
            "code_verifier": saved["code_verifier"],
        }).encode()
        data = self._post(body)
        self._save_token(data)
        try:
            self.state_file.unlink()
        except FileNotFoundError:
            pass
        return data

    def refresh(self):
        token = self._load_token()
        refresh_token = token.get("refresh_token")
        if not refresh_token:
            raise RuntimeError("No existe refresh_token guardado")
        body = urlencode({
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token,
        }).encode()
        data = self._post(body)
        self._save_token(data)
        return data

    def access_token(self):
        token = self._load_token()
        if not token:
            return None
        if token.get("expires_at", 0) <= time.time() + 60:
            token = self.refresh()
        return token.get("access_token")

    def status(self):
        token = self._load_token()
        return {
            "configured": self.configured(),
            "redirect_uri": self.redirect_uri,
            "site": self.site,
            "authorized": bool(token.get("access_token")),
            "expires_at": token.get("expires_at"),
            "scope": token.get("scope"),
        }

    def _post(self, body: bytes):
        req = Request(self.token_url, data=body, method="POST", headers={
            "accept": "application/json",
            "content-type": "application/x-www-form-urlencoded",
        })
        with urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
        if "access_token" not in data:
            raise RuntimeError("Mercado Libre no devolvió access_token")
        return data

    def _save_token(self, data):
        # Fernet is optional at runtime; plaintext storage is refused by default.
        key = os.getenv("AUTOBRILLO_TOKEN_KEY", "")
        if not key:
            raise RuntimeError("Configura AUTOBRILLO_TOKEN_KEY para almacenar tokens de forma cifrada")
        try:
            from cryptography.fernet import Fernet
            payload = dict(data)
            payload["expires_at"] = time.time() + float(data.get("expires_in", 0))
            encrypted = Fernet(key.encode()).encrypt(json.dumps(payload).encode())
        except Exception as exc:
            raise RuntimeError("No se pudo cifrar el token; instala cryptography y revisa AUTOBRILLO_TOKEN_KEY") from exc
        self.token_file.write_bytes(encrypted)
        try:
            os.chmod(self.token_file, 0o600)
        except OSError:
            pass

    def _load_token(self):
        if not self.token_file.exists():
            return {}
        key = os.getenv("AUTOBRILLO_TOKEN_KEY", "")
        if not key:
            raise RuntimeError("Configura AUTOBRILLO_TOKEN_KEY para leer tokens cifrados")
        try:
            from cryptography.fernet import Fernet
            return json.loads(Fernet(key.encode()).decrypt(self.token_file.read_bytes()).decode())
        except Exception as exc:
            raise RuntimeError("No se pudo descifrar el token almacenado") from exc

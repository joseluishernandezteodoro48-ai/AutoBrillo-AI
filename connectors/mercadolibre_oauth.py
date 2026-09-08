import base64
import hashlib
import json
import os
import secrets
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from cryptography.fernet import Fernet


class MercadoLibreOAuth:
    AUTH_URL = "https://auth.mercadolibre.com.mx/authorization"
    TOKEN_URL = "https://api.mercadolibre.com/oauth/token"

    def __init__(self):
        self.client_id = os.getenv("ML_CLIENT_ID", "")
        self.client_secret = os.getenv("ML_CLIENT_SECRET", "")
        self.redirect_uri = os.getenv("ML_REDIRECT_URI", "")
        self.state_file = os.getenv("ML_OAUTH_STATE_FILE", "ml_oauth_state.json")
        self.token_file = os.getenv("ML_TOKEN_FILE", "ml_tokens.enc")
        self.token_key = os.getenv("AUTOBRILLO_TOKEN_KEY", "")
        self.site = os.getenv("ML_SITE", "MLM")

    def configured(self):
        return all((self.client_id, self.client_secret, self.redirect_uri, self.token_key))

    def _fernet(self):
        return Fernet(self.token_key.encode())

    def start(self):
        if not self.configured():
            raise RuntimeError("Configura ML_CLIENT_ID, ML_CLIENT_SECRET, ML_REDIRECT_URI y AUTOBRILLO_TOKEN_KEY")
        verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(32)
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump({"state": state, "verifier": verifier, "created_at": time.time()}, f)
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return self.AUTH_URL + "?" + urlencode(params)

    def exchange(self, code, state):
        if not self.configured():
            raise RuntimeError("OAuth no está configurado.")
        with open(self.state_file, encoding="utf-8") as f:
            saved = json.load(f)
        if not secrets.compare_digest(state, saved.get("state", "")):
            raise RuntimeError("State OAuth inválido.")
        if time.time() - float(saved.get("created_at", 0)) > 600:
            raise RuntimeError("State OAuth expirado.")

        data = urlencode({
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": self.redirect_uri,
            "code_verifier": saved["verifier"],
        }).encode()
        req = Request(
            self.TOKEN_URL,
            data=data,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )

        try:
            with urlopen(req, timeout=20) as response:
                token = json.loads(response.read().decode())
        except HTTPError as exc:
            # Mercado Libre puede devolver detalles útiles (por ejemplo,
            # forbidden/invalid_client/invalid_grant). Los mostramos sin
            # revelar client_secret, code, verifier ni tokens.
            try:
                raw = exc.read().decode("utf-8", errors="replace")
                details = json.loads(raw)
            except Exception:
                details = {}
            error = details.get("error") or details.get("code") or "http_error"
            message = details.get("message") or details.get("error_description") or "Sin detalle adicional."
            raise RuntimeError(
                f"Mercado Libre rechazó el intercambio (HTTP {exc.code}): {error} — {message}"
            ) from None

        with open(self.token_file, "wb") as f:
            f.write(self._fernet().encrypt(json.dumps(token).encode()))
        try:
            os.remove(self.state_file)
        except OSError:
            pass
        return token

    def load_token(self):
        with open(self.token_file, "rb") as f:
            return json.loads(self._fernet().decrypt(f.read()).decode())

"""
OAuth Manager for Claude Pro/Max authentication.

Ported from tiny-workshop TypeScript implementation.
Uses PKCE flow for secure authorization.
Tokens are persisted to a gitignored file for reuse across runs.
"""

import asyncio
import base64
import hashlib
import json
import secrets
import time
import webbrowser
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import httpx

# OAuth Configuration (from opencode-anthropic-auth)
AUTH_URL = "https://claude.ai/oauth/authorize"
TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
REDIRECT_URI = "https://console.anthropic.com/oauth/code/callback"
SCOPES = "org:create_api_key user:profile user:inference"

# Default token file location (gitignored)
DEFAULT_TOKEN_FILE = Path(__file__).parent / ".oauth_tokens.json"


@dataclass
class OAuthTokens:
    """OAuth token container."""

    access: str
    refresh: str
    expires: float  # Expiry timestamp in seconds since epoch

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "OAuthTokens":
        """Create from dictionary."""
        return cls(
            access=data["access"],
            refresh=data["refresh"],
            expires=data["expires"],
        )


def generate_code_verifier() -> str:
    """
    Generate a cryptographically secure PKCE code verifier.
    Must be 43-128 characters, URL-safe.
    """
    random_bytes = secrets.token_bytes(32)
    return _base64url_encode(random_bytes)


async def generate_code_challenge(verifier: str) -> str:
    """Generate S256 code challenge from verifier."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return _base64url_encode(digest)


def _base64url_encode(data: bytes) -> str:
    """URL-safe Base64 encoding (no padding, + -> -, / -> _)."""
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


class OAuthManager:
    """
    Manages OAuth tokens with automatic refresh.

    Features:
    - PKCE flow for secure authorization
    - Token refresh with deduplication (prevents concurrent refresh storms)
    - Callback notification when refresh token rotates
    """

    def __init__(self) -> None:
        self._tokens: OAuthTokens | None = None
        self._pending_refresh: asyncio.Task[str] | None = None
        self._current_verifier: str | None = None
        self._on_token_rotated: Callable[[str], None] | None = None

    def set_on_token_rotated(self, callback: Callable[[str], None]) -> None:
        """Register callback for when refresh token rotates."""
        self._on_token_rotated = callback

    @property
    def is_authenticated(self) -> bool:
        """Check if we have tokens loaded."""
        return self._tokens is not None

    def get_refresh_token(self) -> str | None:
        """Get the current refresh token."""
        return self._tokens.refresh if self._tokens else None

    def load_refresh_token(self, refresh_token: str) -> None:
        """Load a refresh token (will be refreshed on first use)."""
        self._tokens = OAuthTokens(
            access="",  # Will be refreshed on first use
            refresh=refresh_token,
            expires=0,  # Force immediate refresh
        )

    async def start_auth_flow(self) -> tuple[str, str]:
        """
        Generate OAuth authorization URL for user to open in browser.

        Returns:
            Tuple of (auth_url, verifier) - verifier needed for code exchange
        """
        verifier = generate_code_verifier()
        challenge = await generate_code_challenge(verifier)

        self._current_verifier = verifier

        params = {
            "code": "true",
            "client_id": CLIENT_ID,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": verifier,
        }

        url = f"{AUTH_URL}?" + "&".join(f"{k}={v}" for k, v in params.items())
        return url, verifier

    async def exchange_code(self, code: str) -> bool:
        """
        Exchange authorization code for tokens.

        Args:
            code: The authorization code (format: "base_code#state")

        Returns:
            True if successful, False otherwise
        """
        if not self._current_verifier:
            raise RuntimeError("No PKCE verifier available. Call start_auth_flow first.")

        # Code format: "base_code#state"
        parts = code.split("#")
        base_code = parts[0]
        state = parts[1] if len(parts) > 1 else ""

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    TOKEN_URL,
                    json={
                        "code": base_code,
                        "state": state,
                        "grant_type": "authorization_code",
                        "client_id": CLIENT_ID,
                        "redirect_uri": REDIRECT_URI,
                        "code_verifier": self._current_verifier,
                    },
                    headers={"Content-Type": "application/json"},
                )

                if response.status_code != 200:
                    print(f"Token exchange failed: {response.status_code} - {response.text}")
                    return False

                data = response.json()
                self._tokens = OAuthTokens(
                    access=data["access_token"],
                    refresh=data["refresh_token"],
                    expires=time.time() + data["expires_in"],
                )

                self._current_verifier = None
                return True

            except Exception as e:
                print(f"Token exchange error: {e}")
                return False

    async def ensure_valid_token(self) -> str:
        """
        Ensure we have a valid access token, refreshing if necessary.

        Deduplicates concurrent refresh requests to prevent token storms.
        """
        if not self._tokens:
            raise RuntimeError("Not authenticated. Complete OAuth flow first.")

        # Refresh if expired or expiring within 5 minutes
        refresh_threshold = 5 * 60  # 5 minutes in seconds
        if self._tokens.expires < time.time() + refresh_threshold:
            # Deduplicate concurrent refresh requests
            if self._pending_refresh is None:
                self._pending_refresh = asyncio.create_task(self._refresh_token())

            try:
                await self._pending_refresh
            finally:
                self._pending_refresh = None

        return self._tokens.access

    async def _refresh_token(self) -> str:
        """Refresh the access token using the refresh token."""
        if not self._tokens:
            raise RuntimeError("No tokens to refresh")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                TOKEN_URL,
                json={
                    "grant_type": "refresh_token",
                    "refresh_token": self._tokens.refresh,
                    "client_id": CLIENT_ID,
                },
                headers={"Content-Type": "application/json"},
            )

            if response.status_code != 200:
                raise RuntimeError(
                    f"Token refresh failed: {response.status_code} - {response.text}"
                )

            data = response.json()
            self._tokens = OAuthTokens(
                access=data["access_token"],
                refresh=data["refresh_token"],
                expires=time.time() + data["expires_in"],
            )

            # Notify listener of token rotation
            if self._on_token_rotated:
                self._on_token_rotated(self._tokens.refresh)

            return self._tokens.access

    def clear(self) -> None:
        """Clear all tokens (logout)."""
        self._tokens = None
        self._current_verifier = None
        self._pending_refresh = None

    def get_tokens(self) -> OAuthTokens | None:
        """Get current tokens (for saving)."""
        return self._tokens

    def load_tokens(self, tokens: OAuthTokens) -> None:
        """Load tokens directly (from saved file)."""
        self._tokens = tokens


def save_tokens(tokens: OAuthTokens, path: Path = DEFAULT_TOKEN_FILE) -> None:
    """Save tokens to file for reuse across runs."""
    with open(path, "w") as f:
        json.dump(tokens.to_dict(), f, indent=2)


def load_tokens(path: Path = DEFAULT_TOKEN_FILE) -> OAuthTokens | None:
    """Load tokens from file if available and not expired."""
    if not path.exists():
        return None

    try:
        with open(path) as f:
            data = json.load(f)
        tokens = OAuthTokens.from_dict(data)

        # Check if refresh token is likely still valid
        # (we'll try to refresh even if access token expired)
        return tokens
    except (json.JSONDecodeError, KeyError, TypeError):
        # Invalid file, ignore it
        return None


async def get_or_create_oauth(
    token_file: Path = DEFAULT_TOKEN_FILE,
    force_interactive: bool = False,
) -> OAuthManager:
    """
    Get an authenticated OAuthManager, reusing saved tokens if available.

    If saved tokens exist, loads them and refreshes if needed.
    Otherwise, runs interactive login flow.

    Args:
        token_file: Path to token file (default: .oauth_tokens.json)
        force_interactive: If True, always do interactive login

    Returns:
        Authenticated OAuthManager
    """
    manager = OAuthManager()

    # Try to load saved tokens
    if not force_interactive:
        tokens = load_tokens(token_file)
        if tokens:
            print("Found saved OAuth tokens, attempting to use them...")
            manager.load_tokens(tokens)

            try:
                # Try to get a valid token (will refresh if needed)
                await manager.ensure_valid_token()
                print("Successfully authenticated with saved tokens!\n")

                # Save refreshed tokens
                if manager.get_tokens():
                    save_tokens(manager.get_tokens(), token_file)

                return manager
            except Exception as e:
                print(f"Saved tokens invalid or expired: {e}")
                print("Falling back to interactive login...\n")
                manager.clear()

    # Interactive login
    manager = await interactive_login()

    # Save tokens for next time
    if manager.get_tokens():
        save_tokens(manager.get_tokens(), token_file)
        print(f"Tokens saved to {token_file} for future runs.\n")

    # Set up callback to save on refresh
    def on_refresh(new_refresh_token: str) -> None:
        if manager.get_tokens():
            save_tokens(manager.get_tokens(), token_file)

    manager.set_on_token_rotated(on_refresh)

    return manager


async def interactive_login() -> OAuthManager:
    """
    Interactive OAuth login flow for CLI.

    Opens browser for authentication, prompts user to paste the code.
    """
    manager = OAuthManager()

    print("\n=== Claude OAuth Login ===\n")

    auth_url, _verifier = await manager.start_auth_flow()

    print("Opening browser for authentication...")
    print(f"\nIf browser doesn't open, visit:\n{auth_url}\n")

    webbrowser.open(auth_url)

    print("After logging in, you'll be redirected to a page with an authorization code.")
    print("Copy the FULL code (including any # and text after it).\n")

    code = input("Paste authorization code here: ").strip()

    if not code:
        raise RuntimeError("No authorization code provided")

    success = await manager.exchange_code(code)

    if not success:
        raise RuntimeError("Failed to exchange authorization code for tokens")

    print("\nAuthentication successful!\n")
    return manager

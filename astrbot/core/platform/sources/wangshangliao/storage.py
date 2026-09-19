"""Instance-scoped encrypted credentials and transactional message ledger."""

import hashlib
import json
import os
import secrets
from pathlib import Path

import aiosqlite
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .wire import ProtocolError


def instance_dir(instance: str) -> Path:
    """Resolve a non-traversable directory for a platform instance."""
    return (
        Path(get_astrbot_data_path())
        / "platform_data"
        / "wangshangliao"
        / hashlib.sha256(instance.encode()).hexdigest()
    )


class Vault:
    """Persist credentials with instance-bound authenticated encryption."""

    def __init__(self, instance: str, root: Path | None = None):
        self.root = root or instance_dir(instance)
        self.instance = instance

    def save(self, value: dict) -> None:
        """Atomically save one session; keep key and ciphertext private."""
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            self.root.chmod(0o700)
        key_path = self.root / "session.key"
        if key_path.is_symlink():
            raise ProtocolError("vault_path")
        if not key_path.exists():
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(AESGCM.generate_key(bit_length=256))
                stream.flush()
                os.fsync(stream.fileno())
        key = key_path.read_bytes()
        nonce = secrets.token_bytes(12)
        encrypted = nonce + AESGCM(key).encrypt(
            nonce, json.dumps(value).encode(), self.instance.encode()
        )
        temporary = self.root / f"session.{secrets.token_hex(8)}.tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.root / "session.sealed")
        finally:
            temporary.unlink(missing_ok=True)

    def load(self) -> dict | None:
        """Return a decrypted session only to the backend runtime."""
        path = self.root / "session.sealed"
        if not path.exists():
            return None
        try:
            if (
                path.is_symlink()
                or (self.root / "session.key").is_symlink()
                or path.stat().st_size > 65536
            ):
                raise ValueError
            encrypted = path.read_bytes()
            key = (self.root / "session.key").read_bytes()
            return json.loads(
                AESGCM(key).decrypt(
                    encrypted[:12], encrypted[12:], self.instance.encode()
                )
            )
        except Exception:
            raise ProtocolError("session_invalid") from None

    def clear(self) -> None:
        """Remove credentials while preserving audit and deduplication records."""
        (self.root / "session.sealed").unlink(missing_ok=True)


class Ledger:
    """Persist incoming messages before ACK and outgoing intent before sending."""

    def __init__(self, path: Path):
        self.path = path
        self.db = None

    async def open(self) -> None:
        """Initialize tables and quarantine interrupted work on restart."""
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = await aiosqlite.connect(self.path)
        await self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS inbox(account TEXT, team TEXT, message TEXT, payload TEXT, state TEXT, PRIMARY KEY(account,team,message));
            CREATE TABLE IF NOT EXISTS outbox(key TEXT PRIMARY KEY, fingerprint TEXT, nonce TEXT UNIQUE, state TEXT, server_id TEXT);
            CREATE TABLE IF NOT EXISTS sync(account TEXT PRIMARY KEY, cursor TEXT);
            UPDATE inbox SET state='needs_review' WHERE state='processing';
            UPDATE outbox SET state='unknown' WHERE state='sending';
        """)
        await self.db.commit()
        if os.name != "nt":
            self.path.chmod(0o600)

    async def ingest(
        self, account: str, team: str, message: str, payload: dict
    ) -> None:
        """Commit one incoming event before acknowledging its provider message."""
        await self.db.execute(
            "INSERT OR IGNORE INTO inbox VALUES(?,?,?,?,'pending')",
            (account, team, message, json.dumps(payload)),
        )
        await self.db.commit()

    async def mark(self, account: str, team: str, message: str, state: str) -> None:
        """Persist processing completion or a manual-review boundary."""
        await self.db.execute(
            "UPDATE inbox SET state=? WHERE account=? AND team=? AND message=?",
            (state, account, team, message),
        )
        await self.db.commit()

    async def reserve(self, key: str, text: str) -> tuple[str, str]:
        """Reserve an outgoing nonce and key atomically; never retry uncertain work."""
        digest = hashlib.sha256(text.encode()).hexdigest()
        async with self.db.execute(
            "SELECT fingerprint,nonce,state FROM outbox WHERE key=?", (key,)
        ) as cursor:
            existing = await cursor.fetchone()
        if existing:
            if existing[0] != digest:
                raise ProtocolError("send_key_conflict")
            return existing[1], existing[2]
        nonce = str(secrets.randbits(64))
        await self.db.execute(
            "INSERT INTO outbox VALUES(?,?,?,'sending','')", (key, digest, nonce)
        )
        await self.db.commit()
        return nonce, "new"

    async def finish(self, key: str, state: str, server_id: str = "") -> None:
        """Persist provider acceptance without claiming peer delivery."""
        await self.db.execute(
            "UPDATE outbox SET state=?,server_id=? WHERE key=?", (state, server_id, key)
        )
        await self.db.commit()

    async def receipt(self, key: str) -> dict | None:
        """Read durable provider evidence without issuing another send.

        Args:
            key: Instance-scoped outgoing idempotency key.

        Returns:
            Status and provider message ID, or None for an unknown key.
        """
        async with self.db.execute(
            "SELECT state,server_id FROM outbox WHERE key=?", (key,)
        ) as cursor:
            row = await cursor.fetchone()
        return {"status": row[0], "server_id": row[1]} if row else None

    async def close(self) -> None:
        """Close the database after all producers and consumers have stopped."""
        if self.db:
            await self.db.close()
            self.db = None

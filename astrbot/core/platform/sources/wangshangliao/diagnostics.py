"""Bounded, payload-free diagnostics through the AstrBot logging pipeline."""

import hashlib
import logging
import time

from astrbot.core import logger

FAILURES: dict[tuple[str, str, str, bool], tuple[float, int]] = {}
ERROR_LABELS = frozenset(
    {
        "transport",
        "http_rejected",
        "business_rejected",
        "rate_limited",
        "reauth_required",
        "account_conflict",
        "nim_kicked",
        "nim_disconnected",
        "connection_failed",
        "startup_failed",
        "invalid_credentials",
        "invalid_sms",
        "sms_expired",
        "registration_failed",
        "response_invalid",
        "response_shape",
        "refresh_shape",
        "sync_boundary",
        "account_already_active",
        "deployment_missing",
        "deployment_invalid",
        "message_key_missing",
        "receipt_shape",
    }
)


class Diagnostics:
    """Share bounded failure windows across transactions for each instance."""

    def __init__(self, instance: str):
        self.instance = instance

    def emit(
        self,
        stage: str,
        outcome: str,
        correlation: str = "",
        *,
        failed: bool = False,
        terminal: bool = False,
        error: str = "",
    ) -> None:
        """Emit fixed operation labels without exception text or message payloads.

        Args:
            stage: Internal operation label, never provider text.
            outcome: Internal result label, never provider text.
            correlation: Internal identifier hashed before logging.
            failed: Whether to aggregate this failure for sixty seconds.
            terminal: Whether manual intervention is required.
            error: Error label checked against an allowlist before logging.
        """
        count = 1
        error = error if error in ERROR_LABELS else "other" if error else "none"
        if failed:
            now = time.monotonic()
            for expired in [
                key for key, value in FAILURES.items() if now - value[0] >= 60
            ]:
                if expired != (
                    self.instance,
                    stage,
                    error if error != "none" else outcome,
                    terminal,
                ):
                    del FAILURES[expired]
            key = (
                self.instance,
                stage,
                error if error != "none" else outcome,
                terminal,
            )
            previous, suppressed = FAILURES.get(key, (float("-inf"), 0))
            if now - previous < 60:
                FAILURES[key] = (previous, suppressed + 1)
                return
            count += suppressed
            FAILURES[key] = (now, 0)
        reference = (
            hashlib.sha256(correlation.encode()).hexdigest()[:16]
            if correlation
            else "-"
        )
        logger.log(
            logging.ERROR if terminal else logging.WARNING if failed else logging.INFO,
            "Wangshangliao instance=%s stage=%s outcome=%s error=%s correlation=%s count=%s",
            self.instance,
            stage,
            outcome,
            error,
            reference,
            count,
        )

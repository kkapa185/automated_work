"""Timestamped signing."""
from __future__ import annotations

import time
import typing as t
from datetime import datetime, timezone

from .encoding import base64_decode, base64_encode, bytes_to_int, int_to_bytes, want_bytes
from .exc import BadSignature, BadTimeSignature, SignatureExpired
from .serializer import Serializer
from .signer import Signer


class TimestampSigner(Signer):
    """``value . timestamp . signature``."""

    def get_timestamp(self) -> int:
        return int(time.time())

    def timestamp_to_datetime(self, ts: int) -> datetime:
        return datetime.fromtimestamp(ts, tz=timezone.utc)

    def sign(self, value: str | bytes) -> bytes:
        value = want_bytes(value)
        timestamp = base64_encode(int_to_bytes(self.get_timestamp()))
        value = value + self.sep + timestamp
        return value + self.sep + self.get_signature(value)

    def unsign(  # type: ignore[override]
        self,
        signed_value: str | bytes,
        max_age: int | None = None,
        return_timestamp: bool = False,
    ) -> t.Any:
        try:
            result = super().unsign(signed_value)
            sig_error = None
        except BadSignature as e:
            sig_error = e
            result = e.payload or b""

        if self.sep not in result:
            if sig_error:
                raise sig_error
            raise BadTimeSignature("timestamp missing", payload=result)

        value, ts_bytes = result.rsplit(self.sep, 1)
        ts_int: int | None = None
        ts_dt: datetime | None = None
        try:
            ts_int = bytes_to_int(base64_decode(ts_bytes))
        except Exception:
            pass

        if ts_int is not None:
            try:
                ts_dt = self.timestamp_to_datetime(ts_int)
            except (ValueError, OSError, OverflowError) as exc:
                raise BadTimeSignature("Malformed timestamp", payload=value) from exc

        if sig_error is not None:
            raise BadTimeSignature(
                str(sig_error), payload=value, date_signed=ts_dt
            )

        if ts_int is None or ts_dt is None:
            raise BadTimeSignature("Malformed timestamp", payload=value)

        if max_age is not None:
            age = self.get_timestamp() - ts_int
            if age > max_age:
                raise SignatureExpired(
                    f"Signature age {age} > {max_age} seconds",
                    payload=value,
                    date_signed=ts_dt,
                )
            if age < 0:
                raise SignatureExpired(
                    f"Signature age {age} < 0 seconds",
                    payload=value,
                    date_signed=ts_dt,
                )

        if return_timestamp:
            return value, ts_dt
        return value

    def validate(self, signed_value: str | bytes, max_age: int | None = None) -> bool:  # type: ignore[override]
        try:
            self.unsign(signed_value, max_age=max_age)
            return True
        except BadSignature:
            return False


class TimedSerializer(Serializer):
    """Serializer using :class:`TimestampSigner`."""

    default_signer = TimestampSigner

    def iter_unsigners(self, salt: str | bytes | None = None) -> t.Iterator[t.Any]:
        return super().iter_unsigners(salt)

    def loads(  # type: ignore[override]
        self,
        s: str | bytes,
        max_age: int | None = None,
        return_timestamp: bool = False,
        salt: str | bytes | None = None,
    ) -> t.Any:
        s = want_bytes(s)
        last_exception = None
        for signer in self.iter_unsigners(salt):
            try:
                base64d, timestamp = signer.unsign(
                    s, max_age=max_age, return_timestamp=True
                )
                payload = self.load_payload(base64d)
                if return_timestamp:
                    return payload, timestamp
                return payload
            except SignatureExpired:
                # Expiry means the signature was valid; don't try others.
                raise
            except BadSignature as err:
                last_exception = err
        raise t.cast(BadSignature, last_exception)

    def loads_unsafe(  # type: ignore[override]
        self,
        s: str | bytes,
        max_age: int | None = None,
        salt: str | bytes | None = None,
    ) -> tuple[bool, t.Any]:
        return self._loads_unsafe_impl(s, salt, load_kwargs={"max_age": max_age})

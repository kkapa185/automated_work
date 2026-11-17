"""Signatures with timestamps."""
import time
from datetime import datetime
from datetime import timezone

from .encoding import base64_decode
from .encoding import base64_encode
from .encoding import bytes_to_int
from .encoding import int_to_bytes
from .encoding import want_bytes
from .exc import BadSignature
from .exc import BadTimeSignature
from .exc import SignatureExpired
from .serializer import Serializer
from .signer import Signer


class TimestampSigner(Signer):
    """Adds a base64 big-endian timestamp between value and signature."""

    def get_timestamp(self):
        return int(time.time())

    def timestamp_to_datetime(self, ts):
        """Timezone-aware UTC datetime for a timestamp."""
        return datetime.fromtimestamp(ts, tz=timezone.utc)

    def sign(self, value):
        value = want_bytes(value)
        timestamp = base64_encode(int_to_bytes(self.get_timestamp()))
        value = value + self.sep + timestamp
        return value + self.sep + self.get_signature(value)

    def unsign(self, signed_value, max_age=None, return_timestamp=False):
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
        ts_int = None
        ts_dt = None
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

        if ts_int is None:
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

    def validate(self, signed_value, max_age=None):
        try:
            self.unsign(signed_value, max_age=max_age)
            return True
        except BadSignature:
            return False


class TimedSerializer(Serializer):
    """A serializer that uses :class:`TimestampSigner`."""

    default_signer = TimestampSigner

    def loads(self, s, max_age=None, return_timestamp=False, salt=None):
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
                raise
            except BadSignature as err:
                last_exception = err
        raise last_exception

    def loads_unsafe(self, s, max_age=None, salt=None):
        return self._loads_unsafe_impl(s, salt, max_age=max_age)

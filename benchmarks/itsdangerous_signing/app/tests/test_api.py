import itsdangerous

NAMES = """Signer TimestampSigner Serializer TimedSerializer URLSafeSerializer
URLSafeTimedSerializer BadData BadSignature BadTimeSignature BadHeader BadPayload
SignatureExpired base64_encode base64_decode want_bytes NoneAlgorithm HMACAlgorithm
SigningAlgorithm""".split()


def test_r18_root_exports():
    for n in NAMES:
        assert hasattr(itsdangerous, n), n
    assert isinstance(itsdangerous.__version__, str)


def test_r18_module_layout():
    from itsdangerous.encoding import base64_decode  # noqa
    from itsdangerous.exc import BadData  # noqa
    from itsdangerous.serializer import Serializer  # noqa
    from itsdangerous.signer import Signer  # noqa
    from itsdangerous.timed import TimedSerializer, TimestampSigner  # noqa
    from itsdangerous.url_safe import URLSafeSerializer, URLSafeTimedSerializer  # noqa

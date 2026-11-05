"""Prüfung der Lexware-Webhook-Signatur (Doku, Abschnitt Event Subscriptions, geprüft 5. November 2026).

Header `X-Lxo-Signature`: base64-kodierte RSA-SHA512-Signatur (PKCS#1 v1.5) des JSON-Bodys.
Öffentlicher Schlüssel: https://developers.lexware.io/webhookSignature/public/public_key.pub
"""

import base64
import binascii
import json
from functools import lru_cache

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

LEXWARE_WEBHOOK_SCHLUESSEL = b"""-----BEGIN PUBLIC KEY-----
MIICIjANBgkqhkiG9w0BAQEFAAOCAg8AMIICCgKCAgEAtCkZXZqT2zFRmA83KsBC
tQSv9t+AaWiZpRWvzE4wiQEh0aHzNYkT/DlP419pngqoLxnqW9SsgWfKOG3utoEV
z+Lru9odZntW/n/yaRK3f0AcMtuWs/Z1PZ4BbN/RlFYyqlPg0VfuAvZMAa+J9WAl
Fuy0T4Y0EdO0d+EL8BpzSLqj3XLI+YuK4hUhlTOxHmdDtNUkugnT9b9khb+oPDmB
3yxRP6Rmo2qo6waSc+pihCdOiZKzwA4fA1HT8DM54OaNQ4qd9NRf5uECijFlpQu6
vZdW7Z+LZ8HTgGQVSsJdCzUtM1wiWOERrHvd8IpBMvUAvGM/qaJnAmwsEr4J/El4
yCmur8wwYBtSUH0Xue42YysdmSS0pOMMUAAvr70HQMDHagYkErMtu6FAyAmPz8p/
tAqJJpwAhxITbnc5WsmZOu0Ke255nXQ/2Go1TKv+45mSb7RLsvpmhVZ4nFByFt24
vG6IwNReuLhJJL468jrdTpxyZRn0QqkxiQV7jDd9Dp1NVd/W3+n86Aos9LnJa+ut
kN+jOOWmJdJjnQetJlbDVg3ex+XHVmCjiRYggCGPlpXVJwdEUNGzxhPGKjxmeiQT
ahwFA9iHtwBw7yK5VfM/hA+JeF2FXYhTdehfClAQt1YCYXkgUEFxm9idRdBoCY6U
bmFUXQLdi7tZyDor8Rxoq2MCAwEAAQ==
-----END PUBLIC KEY-----
"""


@lru_cache(maxsize=4)
def _schluessel(pem: bytes) -> rsa.RSAPublicKey:
    schluessel = serialization.load_pem_public_key(pem)
    if not isinstance(schluessel, rsa.RSAPublicKey):
        raise ValueError("Kein RSA-Schlüssel")
    return schluessel


def signatur_gueltig(body: bytes, signatur_b64: str, pem: bytes = LEXWARE_WEBHOOK_SCHLUESSEL) -> bool:
    if not signatur_b64:
        return False
    try:
        signatur = base64.b64decode(signatur_b64, validate=False)
    except (binascii.Error, ValueError):
        return False
    kandidaten = [body, body.strip()]
    try:  # Doku: Signatur über das JSON "ohne Leerzeichen und Zeilenumbrüche"
        kandidaten.append(json.dumps(json.loads(body), separators=(",", ":"), ensure_ascii=False).encode())
    except ValueError:
        pass
    for kandidat in kandidaten:
        try:
            _schluessel(pem).verify(signatur, kandidat, padding.PKCS1v15(), hashes.SHA512())
            return True
        except InvalidSignature:
            continue
    return False

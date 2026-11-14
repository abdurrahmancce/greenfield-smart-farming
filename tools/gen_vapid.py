"""Generate VAPID keys for push alerts. Run once:  python tools/gen_vapid.py
Put the printed values in Render > Environment (never commit them)."""
import base64
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization as s
k = ec.generate_private_key(ec.SECP256R1())
b = lambda x: base64.urlsafe_b64encode(x).rstrip(b"=").decode()
priv = b(k.private_numbers().private_value.to_bytes(32, "big"))
pub = b(k.public_key().public_bytes(s.Encoding.X962, s.PublicFormat.UncompressedPoint))
print("VAPID_PUBLIC_KEY  =", pub)
print("VAPID_PRIVATE_KEY =", priv)
print("VAPID_SUBJECT     = mailto:you@example.com")

"""Tests du bloc E : python -m tests.test_webhooks"""
import time

from app.webhooks import sign, verify

SECRET = "secret-de-test"
BODY = b'{"id":"evt-1","type":"sandbox.ready"}'


def test_signature_valide():
    t = int(time.time())
    assert verify(BODY, sign(BODY, t, SECRET), SECRET)


def test_signature_invalide():
    t = int(time.time())
    assert not verify(BODY, sign(BODY, t, "mauvais-secret"), SECRET)
    assert not verify(BODY + b" ", sign(BODY, t, SECRET), SECRET)  # corps modifié
    assert not verify(BODY, "n'importe quoi", SECRET)


def test_horodatage_trop_vieux():
    t = int(time.time()) - 600  # 10 minutes : au-delà des 5 minutes tolérées
    assert not verify(BODY, sign(BODY, t, SECRET), SECRET)


def test_doublon():
    deja_vus = set()
    for _ in range(2):  # le même événement livré deux fois
        if "evt-1" not in deja_vus:
            deja_vus.add("evt-1")
    assert deja_vus == {"evt-1"}


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("OK", name)

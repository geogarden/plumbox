#!/usr/bin/env python3
"""Generuje pin_hash do config.yaml."""

from __future__ import annotations

import argparse
import base64
import hashlib
import os


def create(pin: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        pin.encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=32,
    )
    return "scrypt$" + base64.urlsafe_b64encode(salt).decode() + "$" + base64.urlsafe_b64encode(digest).decode()


parser = argparse.ArgumentParser()
parser.add_argument("pin")
args = parser.parse_args()

if len(args.pin) < 4:
    raise SystemExit("PIN musi mieć co najmniej 4 znaki.")

print(create(args.pin))

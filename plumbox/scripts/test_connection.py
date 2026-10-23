#!/usr/bin/env python3
"""Prosty test połączenia bez uruchamiania serwera WWW."""

from __future__ import annotations

import argparse
import asyncio
import json

import pyplumio


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="192.168.1.50")
    parser.add_argument("--port", type=int, default=8899)
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()

    async with pyplumio.open_tcp_connection(args.host, args.port, reconnect_on_failure=False) as connection:
        ecomax = await connection.get("ecomax", timeout=args.timeout)
        print("Połączono.")
        keys = sorted(ecomax.data.keys())
        print(f"Liczba dostępnych kluczy: {len(keys)}")
        print(json.dumps(keys, ensure_ascii=False, indent=2))
        print("Temperatura kotła:", ecomax.get_nowait("heating_temp"))
        print("Model:", ecomax.get_nowait("product"))


if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.users import ensure_initial_admin
parser = argparse.ArgumentParser()
parser.add_argument('--users', default='/etc/plumbox/users.yaml')
parser.add_argument('--password', default='')
parser.add_argument('--password-file', default='/etc/plumbox/initial_admin_password.txt')
args = parser.parse_args()
password = args.password or None
generated = ensure_initial_admin(Path(args.users), password=password)
if generated:
    if password:
        print('Utworzono konto admin z hasłem podanym przy instalacji.')
    else:
        Path(args.password_file).write_text('Login: admin\nHasło: ' + generated + '\n', encoding='utf-8')
        Path(args.password_file).chmod(0o600)
        print('Utworzono konto admin. Losowe hasło zapisano w ' + args.password_file)
else:
    print('Plik użytkowników już istnieje — nie zmieniam kont.')

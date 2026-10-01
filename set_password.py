#!/usr/bin/env python3
"""MiniRDP şifresini ayarlar. Kullanım: ./venv/bin/python set_password.py [yeni_şifre]"""
import getpass
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from server import CONFIG_PATH, hash_password, load_config  # noqa: E402

if len(sys.argv) > 1:
    pw = sys.argv[1]
else:
    pw = getpass.getpass("Yeni şifre: ")
    if pw != getpass.getpass("Tekrar: "):
        sys.exit("Şifreler eşleşmiyor.")
if len(pw) < 6:
    sys.exit("Şifre en az 6 karakter olmalı.")
cfg = load_config()
cfg["password_salt"], cfg["password_hash"] = hash_password(pw)
CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
CONFIG_PATH.chmod(0o600)
(CONFIG_PATH.parent / "sessions.json").unlink(missing_ok=True)  # eski oturumların hepsini geçersiz kıl
print("Şifre kaydedildi. Değişikliğin geçerli olması için servisi yeniden başlatın:")
print("  launchctl kickstart -k gui/$(id -u)/com.minirdp.server")

#!/bin/zsh
# MiniRDP kurulumu: Python ortamı, şifre, sertifikalar, MiniRDP.app ve otomatik başlatma.
set -e
cd "$(dirname "$0")"
DIR="$PWD"
PY=/Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14
[[ -x $PY ]] || { echo "python.org'dan Python 3.14 kurun (framework build gerekli)."; exit 1; }

echo "== Python ortamı"
[[ -d venv ]] || $PY -m venv venv
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q -r requirements.txt

echo "== Yapılandırma"
[[ -f config.json ]] || { cp config.example.json config.json; chmod 600 config.json; }
grep -q password_hash config.json || ./venv/bin/python set_password.py

echo "== Sertifikalar"
[[ -f certs/server.crt ]] || ./scripts/make_certs.sh

echo "== MiniRDP.app"
./launcher/build.sh

echo "== Otomatik başlatma (LaunchAgent)"
PLIST=~/Library/LaunchAgents/com.minirdp.server.plist
cat > $PLIST <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.minirdp.server</string>
  <key>ProgramArguments</key>
  <array><string>$DIR/MiniRDP.app/Contents/MacOS/MiniRDP</string></array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>5</integer>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$DIR/minirdp.log</string>
  <key>StandardErrorPath</key><string>$DIR/minirdp.log</string>
</dict>
</plist>
PL
launchctl bootout gui/$(id -u)/com.minirdp.server 2>/dev/null || true
for i in {1..15}; do launchctl print gui/$(id -u)/com.minirdp.server >/dev/null 2>&1 || break; sleep 1; done
launchctl bootstrap gui/$(id -u) $PLIST

IP="$(ipconfig getifaddr en0 || ipconfig getifaddr en1)"
cat <<MSG

Kurulum tamam. Şimdi:
 1. Sistem Ayarları > Gizlilik ve Güvenlik > "Ekran ve Sistem Sesi Kaydı" ve "Erişilebilirlik"
    listelerinde MiniRDP'yi açın, sonra:  launchctl kickstart -k gui/\$(id -u)/com.minirdp.server
 2. Windows'ta https://$IP:8765/minirdp-ca.crt adresinden CA'yı indirip
    "Güvenilen Kök Sertifika Yetkilileri"ne kurun.
 3. https://$IP:8765 adresine bağlanın.
MSG

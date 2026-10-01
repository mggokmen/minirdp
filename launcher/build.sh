#!/bin/zsh
# MiniRDP.app'i derler ve imzalar. Kullanım: ./launcher/build.sh
set -e
cd "$(dirname "$0")/.."
DIR="$PWD"
PYV=3.14
PYHOME=/Library/Frameworks/Python.framework/Versions/$PYV
APP="$DIR/MiniRDP.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleIdentifier</key><string>com.minirdp.server</string>
  <key>CFBundleName</key><string>MiniRDP</string>
  <key>CFBundleDisplayName</key><string>MiniRDP</string>
  <key>CFBundleExecutable</key><string>MiniRDP</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSUIElement</key><true/>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
</dict></plist>
PLIST
clang -O2 -Wall -o "$APP/Contents/MacOS/MiniRDP" launcher/main.c \
  -I$PYHOME/include/python$PYV \
  -L$PYHOME/lib/python$PYV/config-$PYV-darwin -lpython$PYV -ldl -framework CoreFoundation \
  -Wl,-rpath,$PYHOME/lib \
  -DPY_HOME="\"$PYHOME\"" \
  -DAPP_DIR="\"'$DIR'\"" \
  -DSERVER_PY="\"'$DIR/server.py'\"" \
  -DSITE_PACKAGES="\"'$DIR/venv/lib/python$PYV/site-packages'\""
codesign --force --sign - --identifier com.minirdp.server "$APP"
codesign -dv "$APP" 2>&1 | grep -E "Identifier|Signature"
echo "Derlendi: $APP"

#!/bin/zsh
# Yerel CA (yoksa) ve bu Mac'in IP'si için sunucu sertifikası üretir.
# Kullanım: ./scripts/make_certs.sh [IP]   (IP verilmezse en0/en1'den bulunur)
set -e
cd "$(dirname "$0")/.."
IP="${1:-$(ipconfig getifaddr en0 || ipconfig getifaddr en1)}"
[[ -z "$IP" ]] && { echo "IP bulunamadı, argüman olarak verin."; exit 1; }
HOST="$(scutil --get LocalHostName)"
mkdir -p certs && chmod 700 certs && cd certs
umask 077

if [[ ! -f ca.key ]]; then
  cat > ca.cnf <<CNF
[req]
distinguished_name = dn
prompt = no
x509_extensions = v3_ca
[dn]
CN = MiniRDP Yerel CA ($HOST)
O = MiniRDP
[v3_ca]
basicConstraints = critical, CA:TRUE, pathlen:0
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
# CA yalnızca yerel ağ adresleri ve .local adları için sertifika imzalayabilir.
nameConstraints = critical, permitted;IP:192.168.0.0/255.255.0.0, permitted;IP:10.0.0.0/255.0.0.0, permitted;IP:172.16.0.0/255.240.0.0, permitted;IP:127.0.0.0/255.0.0.0, permitted;DNS:.local, permitted;DNS:localhost
CNF
  openssl ecparam -name prime256v1 -genkey -noout -out ca.key
  openssl req -x509 -new -key ca.key -sha256 -days 3650 -config ca.cnf -out minirdp-ca.crt
  chmod 644 minirdp-ca.crt
  echo "Yeni CA oluşturuldu - Windows'a minirdp-ca.crt kurulmalı."
fi

cat > server.ext <<EXT
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = IP:$IP, IP:127.0.0.1, DNS:$HOST.local, DNS:localhost
authorityKeyIdentifier = keyid
subjectKeyIdentifier = hash
EXT
openssl ecparam -name prime256v1 -genkey -noout -out server.key
openssl req -new -key server.key -subj "/CN=$IP" -out server.csr
openssl x509 -req -in server.csr -CA minirdp-ca.crt -CAkey ca.key -CAcreateserial -sha256 -days 825 -extfile server.ext -out server.crt 2>/dev/null
rm server.csr
openssl verify -CAfile minirdp-ca.crt server.crt
echo "Sunucu sertifikası: $IP, $HOST.local"
echo -n "CA SHA1 parmak izi: "; openssl x509 -in minirdp-ca.crt -noout -fingerprint -sha1 | cut -d= -f2

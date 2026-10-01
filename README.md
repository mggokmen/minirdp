# MiniRDP

Aynı ağdaki bir Windows bilgisayardan (Chrome/Edge) bir Mac'i uzaktan görüntüleyip fare ve klavyeyle kontrol etmek için küçük bir uzak masaüstü sunucusu. Windows tarafına kurulum gerekmez, tarayıcı yeterlidir.

- Ekran JPEG olarak WebSocket (wss) üzerinden akar, yalnızca değişiklik olduğunda kare gönderilir.
- Fare, klavye (Türkçe karakterler ve AltGr dahil), pano paylaşımı, Ctrl→⌘ eşlemesi, tam ekranda Alt+Tab/Win tuşu.
- Şifreli giriş (PBKDF2), hatalı denemede kilitleme, yalnızca yerel ağdan erişim, Origin/Host kontrolü.
- Kendi yerel CA'sı ile HTTPS; CA yalnızca yerel IP'ler ve `.local` adları için imza atabilecek şekilde kısıtlıdır.
- Python, `MiniRDP.app` içine gömülü ve izole modda çalışır; Ekran Kaydı / Erişilebilirlik izinleri genel Python'a değil yalnızca bu uygulamaya verilir.
- LaunchAgent ile oturum açılınca otomatik başlar, çökerse yeniden başlar; çalışırken Mac'in uyumasını engeller.

## Gereksinimler

- macOS 13+ (Apple Silicon veya Intel)
- [python.org](https://www.python.org/downloads/macos/) Python 3.14 (framework build)
- Xcode Command Line Tools (`xcode-select --install`)

## Kurulum

```sh
./install.sh
```

Betik sırasıyla şunları yapar: Python ortamını kurar, şifre sorar, sertifikaları üretir, `MiniRDP.app`'i derler ve LaunchAgent'ı yükler. Ardından:

1. **Sistem Ayarları → Gizlilik ve Güvenlik** altında **Ekran ve Sistem Sesi Kaydı** ve **Erişilebilirlik** listelerinde **MiniRDP**'yi açın, sonra servisi yeniden başlatın.
2. Windows'ta `https://<MAC_IP>:8765/minirdp-ca.crt` adresinden CA sertifikasını indirin (ilk seferde tarayıcı uyarısını geçin), parmak izini `make_certs.sh` çıktısıyla karşılaştırın ve **Geçerli Kullanıcı → Güvenilen Kök Sertifika Yetkilileri**'ne kurun. PowerShell ile:
   ```powershell
   Import-Certificate -FilePath "$env:USERPROFILE\Downloads\minirdp-ca.crt" -CertStoreLocation Cert:\CurrentUser\Root
   ```
3. Tarayıcıyı yeniden açıp `https://<MAC_IP>:8765` adresine bağlanın.

## Yönetim

| İş | Komut |
|---|---|
| Şifre değiştir (tüm oturumları kapatır) | `./venv/bin/python set_password.py` |
| Yeniden başlat | `launchctl kickstart -k gui/$(id -u)/com.minirdp.server` |
| Durdur | `launchctl bootout gui/$(id -u)/com.minirdp.server` |
| Başlat | `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.minirdp.server.plist` |
| Log | `tail -f minirdp.log` |
| Mac'in IP'si değiştiyse | `./scripts/make_certs.sh` ve yeniden başlat (CA aynı kalır) |

Ayarlar `config.json` içindedir: `port`, `quality`, `max_width`, `resolution` (bağlanınca uygulanacak ekran çözünürlüğü; istemiyorsanız `null`).

## Notlar

- `MiniRDP.app` ad-hoc imzalıdır; **yeniden derlendiğinde macOS onu yeni bir uygulama sayar** ve izinlerin tekrar verilmesi gerekir. Gerekirse önce eski kayıtları silin: `tccutil reset ScreenCapture com.minirdp.server && tccutil reset Accessibility com.minirdp.server`. `server.py` değişiklikleri izinleri etkilemez.
- `certs/ca.key` CA'nın gizli anahtarıdır; Mac dışına çıkmamalı. Windows'a yalnızca `minirdp-ca.crt` kurulur.
- Firefox Windows sertifika deposunu kullanmaz; Chrome veya Edge önerilir.
- Yalnızca ev/ofis yerel ağında kullanın, portu internete açmayın.

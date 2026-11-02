# PyCompiler kimlik doğrulama API'si

Bu klasör, bağımsız FastAPI kimlik doğrulama servisini içerir. Servis; kayıt,
e-posta doğrulama, oturum açma, JWT erişim belirteçleri, dönen refresh
belirteçleri, oturum yönetimi, parola kurtarma, TOTP iki aşamalı doğrulama ve
admin uçları sağlar. Tarayıcı frontend'ine otomatik olarak bağlı değildir.

## Kurulum

Proje kökünde sanal ortamı etkinleştirin ve bağımlılıkları kurun:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r auth\requirements.txt
```

## Geliştirme sunucusu

Her çalıştırmada yeni bir gizli anahtar oluşturun ve API'yi localhost'ta
başlatın:

```powershell
$env:AUTH_SECRET = python -c "import secrets; print(secrets.token_hex(32))"
python -m auth --host 127.0.0.1 --port 8001
```

Başka bir terminalden sağlık kontrolü:

```powershell
Invoke-RestMethod http://127.0.0.1:8001/healthz
```

İmzalama anahtarı ve SQLite veritabanı varsayılan olarak bu klasörde
oluşturulur (`auth_ed25519.pem` ve `auth.db`). İkisi de Git dışında tutulur.
`AUTH_DB` ve `AUTH_KEY_PATH` ile dosya konumları değiştirilebilir.

## E-posta ve yönetici hesabı

SMTP yapılandırması yoksa doğrulama ve parola sıfırlama iletileri yalnızca
geliştirme günlüğüne yazılır. Gerçek e-posta için `AUTH_SMTP_HOST`,
`AUTH_SMTP_PORT`, `AUTH_SMTP_USER`, `AUTH_SMTP_PASS` ve `AUTH_SMTP_FROM`
değişkenlerini yapılandırın. E-postası doğrulanmayan hesapların girişini
zorunlu kılmak için `AUTH_REQUIRE_VERIFIED=1` ayarlanabilir.

`AUTH_BOOTSTRAP_ADMIN`, yalnızca belirtilen kullanıcı adı veritabanında
önceden kayıtlıysa o hesabı yönetici yapar; ilk yönetici hesabını tek başına
oluşturmaz.

## Önemli güvenlik sınırları

- `AUTH_SECRET` her dağıtımda gizli, rastgele ve en az 32 karakter olmalıdır;
  kaynak koda veya Git'e eklemeyin. Bu değer değişirse mevcut refresh
  belirteçleri ve şifreli TOTP sırları geçersiz olur.
- Geliştirme sunucusunu varsayılan olarak `127.0.0.1`'de çalıştırın. Ağ
  erişimine açmadan önce HTTPS, güvenilir proxy yapılandırması, kalıcı gizli
  anahtar saklama ve SMTP ayarlarını dağıtım ortamına göre yapılandırın.
- `AUTH_TRUST_PROXY=1` yalnızca `X-Forwarded-For` başlığını güvenilir bir
  proxy'nin temizlediği ve yeniden yazdığı bir arka uçta kullanılmalıdır.
- Varsayılan e-posta gönderimi yalnızca geliştirme içindir; günlükler doğrulama
  ve parola sıfırlama belirteçlerini içerebilir.
- Bu API bir yönetim paneli veya frontend oturum ekranı sunmaz; istemci
  entegrasyonu ayrıca yapılmalıdır.

## Uç noktalar

- `POST /auth/register`, `POST /auth/verify-email`, `POST /auth/login`
- `POST /auth/refresh`, `POST /auth/logout`, `POST /auth/logout-all`
- `GET /auth/me`, `GET /auth/sessions`, `DELETE /auth/sessions/{sid}`
- `POST /auth/password/forgot`, `POST /auth/password/reset`,
  `POST /auth/password/change`
- `POST /auth/mfa/setup`, `/auth/mfa/enable`, `/auth/mfa/disable`
- `GET /.well-known/jwks.json`, `GET /healthz`
- Yönetici uçları: `GET /admin/users` ve kullanıcı enable/disable/unlock
  işlemleri

OpenAPI belgeleri varsayılan olarak kapalıdır. Yalnızca geliştirmede
`AUTH_DOCS=1` ile `/docs` açılabilir.

# Deploy Ruang ke VPS

Panduan ini menjalankan Ruang sebagai lima container: migrasi satu kali,
Gunicorn, background worker, PostgreSQL, dan Caddy. Hanya port 80/443 milik
Caddy yang dipublikasikan. PostgreSQL dan Gunicorn tetap berada di jaringan
internal Docker.

## Prasyarat

- VPS Linux x86_64/arm64 dengan minimal 2 vCPU dan 4 GB RAM.
- Docker Engine dan Docker Compose v2.
- Domain dengan record A/AAAA yang sudah mengarah ke VPS.
- Port TCP 80/443 dan UDP 443 terbuka di firewall.

## 1. Siapkan konfigurasi

```bash
git clone https://github.com/unknownymouse/ruang.git
cd ruang
cp .env.example .env
openssl rand -hex 64
openssl rand -hex 32
openssl rand -hex 32
openssl rand -hex 32
```

Gunakan empat hasil acak tersebut masing-masing untuk `SECRET_KEY`,
`ENCRYPTION_KEY_SALT`, `POSTGRES_PASSWORD`, dan
`RUANG_PRIVACY_AUDIT_KEY`. Kunci audit harus stabil walaupun `SECRET_KEY`
kelak dirotasi. Kemudian ubah nilai minimum ini di `.env`:

```env
SECRET_KEY=<hasil-random-pertama>
ENCRYPTION_KEY_SALT=<hasil-random-kedua>
DEBUG=false
ALLOWED_HOSTS=ruang.example.com
APP_URL=https://ruang.example.com
APP_DOMAIN=ruang.example.com

POSTGRES_DB=ruang
POSTGRES_USER=ruang
POSTGRES_PASSWORD=<hasil-random-ketiga>

EMAIL_BACKEND_TYPE=smtp
DEFAULT_FROM_EMAIL=noreply@ruang.example.com

RUANG_LEGAL_ENTITY_NAME=PT Nama Badan Usaha
RUANG_LEGAL_ENTITY_ADDRESS=Alamat terdaftar lengkap
RUANG_LEGAL_COUNTRY=Indonesia
RUANG_SUPPORT_EMAIL=support@ruang.example.com
RUANG_PRIVACY_EMAIL=privacy@ruang.example.com
RUANG_TERMS_VERSION=2026-07-31
RUANG_PRIVACY_VERSION=2026-07-31
RUANG_LEGAL_EFFECTIVE_DATE=31 Juli 2026
RUANG_TERMS_URL=https://ruang.example.com/legal/terms/
RUANG_PRIVACY_URL=https://ruang.example.com/legal/privacy/
RUANG_SOURCE_CODE_URL=https://github.com/unknownymouse/ruang
RUANG_SOURCE_CODE_REVISION=<hasil git rev-parse HEAD>
# Opsional bila host source bukan GitHub; URL harus memuat revision exact di atas.
# RUANG_DEPLOYED_SOURCE_URL=https://source-host.tld/project/tree/<revision>
RUANG_PRIVACY_AUDIT_KEY=<hasil-random-keempat>
RUANG_SUBPROCESSORS_JSON=[{"name":"Nama provider","purpose":"AI/hosting/email sesuai fakta","privacy_url":"https://provider.tld/privacy","location":"Negara/region"}]
RUANG_ACCOUNT_RECORD_RETENTION_DAYS=1825
RUANG_SECURITY_LOG_RETENTION_DAYS=180
RUANG_BACKUP_RETENTION_DAYS=30
```

Isi SMTP, provider AI, media webhook, dan credential platform sosial yang akan
digunakan. Hapus `demo` dari `RUANG_AI_PROVIDERS` bila produksi harus gagal
tertutup saat semua provider AI tidak tersedia.

Untuk satu VPS, `STORAGE_BACKEND=local` menggunakan volume Docker persisten.
Gunakan konfigurasi S3-compatible di `.env` bila membutuhkan object storage
eksternal atau menjalankan lebih dari satu node aplikasi.

## 2. Gate legal sebelum go-live

Sebelum menerima pengguna atau pembayaran:

1. Pastikan badan usaha/NIB, KBLI, pajak, kontrak pembayaran, dan kewajiban
   PSE/PMSE yang relevan sudah diverifikasi penasihat hukum.
2. Ganti seluruh placeholder Terms/Privacy dengan identitas dan praktik nyata.
3. Daftarkan semua provider yang menerima data pada
   `RUANG_SUBPROCESSORS_JSON`, termasuk AI, media, hosting, email,
   observability, dan pembayaran yang benar-benar aktif.
4. Pastikan DPA, lokasi pemrosesan/transfer lintas negara, retention/training
   model, dan penghapusan provider terdokumentasi.
5. Baca dan selesaikan checklist di
   [legal-compliance.md](legal-compliance.md).

Container `migrate` menjalankan `python manage.py check --deploy` sebelum
migrasi. Deployment berhenti jika identitas legal, email, URL HTTPS, revision
source AGPL, kunci audit, retention, atau disclosure subprocessor masih tidak
valid.

## 3. Validasi dan jalankan

```bash
test -z "$(git status --porcelain --untracked-files=normal)"
test "$(git rev-parse HEAD)" = "$(sed -n 's/^RUANG_SOURCE_CODE_REVISION=//p' .env | tail -n 1)"
docker compose --env-file .env -f docker-compose.prod.yml config --quiet
docker compose --env-file .env -f docker-compose.prod.yml up -d --build
docker compose --env-file .env -f docker-compose.prod.yml ps
```

Dua perintah `test` harus sukses. Jangan membangun release dari worktree
dengan perubahan tracked/untracked karena Corresponding Source commit tidak lagi
sama dengan kode di dalam image.

Service `migrate` harus berakhir dengan status `Exited (0)`. Service `app`,
`worker`, `postgres`, dan `caddy` harus aktif; `app` dan `postgres` akan menjadi
healthy sebelum Caddy menerima traffic.

Buat administrator pertama:

```bash
docker compose --env-file .env -f docker-compose.prod.yml exec app python manage.py createsuperuser
```

Verifikasi dari luar VPS:

```bash
curl --fail https://ruang.example.com/health/
```

Respons yang diharapkan adalah `{"status":"ok"}`. Caddy memperoleh dan
memperbarui sertifikat TLS secara otomatis setelah DNS dan firewall benar.

Verifikasi dokumen dan source offer:

```bash
curl --fail https://ruang.example.com/legal/terms/
curl --fail https://ruang.example.com/legal/privacy/
curl --fail https://ruang.example.com/legal/open-source/
```

## Operasi rutin

Melihat log:

```bash
docker compose --env-file .env -f docker-compose.prod.yml logs -f app worker caddy
```

Deploy pembaruan:

```bash
git pull --ff-only
RUANG_REVISION=$(git rev-parse HEAD)
sed -i "s/^RUANG_SOURCE_CODE_REVISION=.*/RUANG_SOURCE_CODE_REVISION=${RUANG_REVISION}/" .env
docker compose --env-file .env -f docker-compose.prod.yml up -d --build --remove-orphans
```

Backup PostgreSQL ke file di host:

```bash
docker compose --env-file .env -f docker-compose.prod.yml exec -T postgres pg_dump -U ruang -d ruang -Fc > ruang-$(date +%F).dump
```

Backup database dan media volume harus disalin ke lokasi di luar VPS secara
terjadwal, terenkripsi, diuji restore, dan dihapus otomatis setelah
`RUANG_BACKUP_RETENTION_DAYS`. Jangan memasukkan `.env`, dump database,
atau credential ke Git.

Setiap perubahan material pada Terms atau Privacy wajib:

1. menaikkan `RUANG_TERMS_VERSION` atau `RUANG_PRIVACY_VERSION`;
2. memperbarui tanggal berlaku dan dokumennya;
3. merekam dasar perubahan/approval internal; dan
4. melakukan deploy sehingga pengguna diminta menerima versi baru.

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
```

Gunakan tiga hasil acak tersebut masing-masing untuk `SECRET_KEY`,
`ENCRYPTION_KEY_SALT`, dan `POSTGRES_PASSWORD`. Kemudian ubah nilai minimum ini
di `.env`:

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
```

Isi SMTP, provider AI, media webhook, dan credential platform sosial yang akan
digunakan. Hapus `demo` dari `RUANG_AI_PROVIDERS` bila produksi harus gagal
tertutup saat semua provider AI tidak tersedia.

Untuk satu VPS, `STORAGE_BACKEND=local` menggunakan volume Docker persisten.
Gunakan konfigurasi S3-compatible di `.env` bila membutuhkan object storage
eksternal atau menjalankan lebih dari satu node aplikasi.

## 2. Validasi dan jalankan

```bash
docker compose --env-file .env -f docker-compose.prod.yml config --quiet
docker compose --env-file .env -f docker-compose.prod.yml up -d --build
docker compose --env-file .env -f docker-compose.prod.yml ps
```

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

## Operasi rutin

Melihat log:

```bash
docker compose --env-file .env -f docker-compose.prod.yml logs -f app worker caddy
```

Deploy pembaruan:

```bash
git pull --ff-only
docker compose --env-file .env -f docker-compose.prod.yml up -d --build --remove-orphans
```

Backup PostgreSQL ke file di host:

```bash
docker compose --env-file .env -f docker-compose.prod.yml exec -T postgres pg_dump -U ruang -d ruang -Fc > ruang-$(date +%F).dump
```

Backup database dan media volume harus disalin ke lokasi di luar VPS secara
terjadwal. Jangan memasukkan `.env`, dump database, atau credential ke Git.

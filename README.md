<p align="center">
  <img src="static/img/ruang-logo.svg" alt="Ruang" width="132">
</p>

<h1 align="center">Ruang</h1>

<p align="center">
  <strong>AI content operations: dari Brand Brain dan brief hingga approval, scheduling, publishing, dan optimization loop.</strong>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-AGPL--3.0-0f766e.svg" alt="AGPL-3.0"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.12%2B-102a2b.svg" alt="Python 3.12+"></a>
  <a href="https://www.djangoproject.com/"><img src="https://img.shields.io/badge/Django-5.x-115e59.svg" alt="Django 5.x"></a>
</p>

Ruang adalah platform content operations self-hosted untuk tim, agency, dan brand. Ruang menyatukan strategi berbasis AI dengan composer, kalender, approval manusia, direct publishing, retry queue, dan analytics lintas channel.

Proyek ini merupakan fork dan pengembangan dari [BrightBean Studio](https://github.com/brightbeanxyz/brightbean-studio), didistribusikan dengan lisensi AGPL-3.0. Atribusi dan riwayat Git upstream tetap dipertahankan.

## Yang tersedia

| Area | Kapabilitas |
|---|---|
| **Brand Brain** | Tone, persona, produk, audiens, aturan, forbidden topics, bahasa, knowledge base, traffic goals, topic seeds, dan conversion actions per workspace. |
| **Brief → campaign** | AI menyusun north star, narrative, content pillars, channel roles, dan kalender hingga 30 item per generasi. |
| **Caption native** | Caption utama dan tiga variasi untuk Instagram, TikTok, LinkedIn, dan channel terhubung lainnya. |
| **Image & video pipeline** | Visual prompt, video script, persistent media job, retry, status, dan webhook vendor-neutral. |
| **Human approval** | Output AI tidak pernah langsung publish. Moderation flag harus diselesaikan, lalu approver manusia memindahkan item ke composer. |
| **Scheduling & publishing** | Proposed schedule, kalender, queue, per-channel state machine, automatic retry, dan direct first-party publishing. |
| **Optimization loop** | Snapshot analytics 30 hari dimasukkan sebagai sinyal pada campaign berikutnya. |
| **AI operations** | Ordered provider fallback, prompt version, audit log, usage token, estimasi biaya, quota bulanan, dan moderation. |
| **Multi-provider** | OpenAI, Anthropic, Gemini, endpoint OpenAI-compatible, serta demo provider lokal. |
| **Social stack** | Facebook, Instagram, LinkedIn, TikTok, YouTube, Pinterest, Threads, X, Bluesky, Mastodon, Google Business, dan DEV.to. |

## Approval dan publishing flow

```text
Brand Brain + brief + analytics
            │
            ▼
AI provider router → strategy + platform drafts + media prompts
            │
            ▼
Local moderation + quota + usage/audit log
            │
            ▼
Human campaign approval
            │
            ▼
Composer draft + proposed publish time
            │
            ▼
Existing workspace approval → schedule/queue → retry → direct publishing
```

Tidak ada hasil generatif yang dapat melewati approval gate. Setelah campaign disetujui, Ruang membuat `Post`/`PlatformPost` berstatus `draft` dan mengisi `proposed_publish_at`; scheduler final tetap tindakan eksplisit di composer.

## Quick start

### Docker

```bash
git clone https://github.com/unknownymouse/ruang.git
cd ruang
cp .env.example .env
```

Set minimal environment:

```env
SECRET_KEY=ganti-dengan-random-secret
ENCRYPTION_KEY_SALT=ganti-dengan-random-salt
DATABASE_URL=postgres://postgres:postgres@postgres:5432/ruang
APP_URL=http://localhost:8000
ALLOWED_HOSTS=localhost,127.0.0.1
```

Lalu jalankan:

```bash
docker compose up -d --build
docker compose exec app python manage.py createsuperuser
```

Buka `http://localhost:8000`.

### Local development

Python 3.12+ dan Node.js 20+ diperlukan.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

cd theme/static_src
npm install
npm run build
cd ../..

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Jalankan worker pada terminal lain:

```bash
python manage.py process_tasks
```

Worker memproses AI campaign, media generation job, publisher retry, analytics sync, notification, dan background operation lainnya.

## Traffic strategy

Brand Brain stores traffic goals, operator-verified topic seeds, and conversion
actions. Ruang combines these with its versioned evidence playbook and 30-day
analytics feedback to generate demand hypotheses, native distribution,
experiments, and success metrics. See `docs/content-traffic-strategy.md`.

## X configuration

Create an OAuth 2.0 Web App in the X Developer Console, register the Ruang
callback URL, and enable read/write permissions. Ruang uses Authorization Code
with PKCE and requests `tweet.read`, `tweet.write`, `users.read`, and
`offline.access`.

```env
PLATFORM_X_CLIENT_ID=
PLATFORM_X_CLIENT_SECRET=
```

## Konfigurasi AI

Provider dieksekusi berurutan; provider berikutnya menjadi fallback ketika request sebelumnya gagal.

Owner dan admin organisasi dapat membuka **Settings -> AI Providers** untuk
menyimpan koneksi OpenAI, Anthropic, Gemini, atau endpoint OpenAI-compatible
tanpa mengubah environment server. API key dienkripsi menggunakan SECRET_KEY,
hanya ditampilkan dalam bentuk mask, dan perubahan/test dicatat tanpa secret.
Koneksi organisasi diprioritaskan berdasarkan angka priority; konfigurasi
environment di bawah tetap dipakai sebagai fallback VPS. Jaga SECRET_KEY tetap
stabil saat redeploy, gunakan endpoint custom HTTPS publik, dan ungkapkan
provider eksternal pada Privacy Policy/subprocessor list.

```env
RUANG_AI_PROVIDERS=openai,anthropic,gemini,openai_compatible,demo

RUANG_OPENAI_API_KEY=
RUANG_OPENAI_BASE_URL=https://api.openai.com/v1
RUANG_OPENAI_MODEL=gpt-5.4-mini

RUANG_ANTHROPIC_API_KEY=
RUANG_ANTHROPIC_MODEL=claude-sonnet-5

RUANG_GEMINI_API_KEY=
RUANG_GEMINI_MODEL=gemini-3.6-flash

RUANG_COMPATIBLE_API_KEY=
RUANG_COMPATIBLE_BASE_URL=
RUANG_COMPATIBLE_MODEL=
```

`demo` adalah planner deterministik lokal agar workflow dapat dievaluasi tanpa API key. Hapus `demo` dari `RUANG_AI_PROVIDERS` di production jika generasi harus fail-closed.

### Quota dan biaya

```env
RUANG_AI_MONTHLY_TOKEN_LIMIT=1000000
RUANG_AI_MONTHLY_COST_LIMIT_USD=50.00
RUANG_AI_COSTS_JSON={"model-name":{"input":1.0,"output":4.0}}
```

Price book tidak di-hard-code karena harga provider berubah. Nilai `input` dan `output` adalah USD per satu juta token dan dikelola operator.

### Image/video provider

Ruang memakai kontrak webhook kecil agar pipeline dapat diarahkan ke Fal, Replicate, ComfyUI, Runway, atau service internal:

```env
RUANG_MEDIA_WEBHOOK_URL=https://media-orchestrator.example.com/generate
RUANG_MEDIA_WEBHOOK_TOKEN=
```

Request:

```json
{
  "kind": "image | video",
  "prompt": "...",
  "campaign_id": "uuid",
  "content_draft_id": "uuid"
}
```

Response:

```json
{
  "status": "completed | processing",
  "provider": "provider-name",
  "external_job_id": "optional-id",
  "output_url": "https://...",
  "metadata": {}
}
```

## Brand dan legal configuration

```env
RUANG_SUPPORT_EMAIL=support@yourdomain.com
RUANG_TERMS_URL=https://yourdomain.com/terms
RUANG_PRIVACY_URL=https://yourdomain.com/privacy
```

Logo ada di `static/img/ruang-logo.svg`; token warna white-label ada di `theme/static_src/src/styles.css`.

## Arsitektur singkat

```text
apps/ai_automation/   Brand Brain, campaign, provider router, moderation,
                      prompt versions, usage/cost, audit, media pipeline
apps/composer/        Draft dan variasi per platform
apps/approvals/       Internal/client human approval state machine
apps/calendar/        Calendar, posting slots, queue, recurrence
apps/publisher/       Publish worker, retry, publish logs
apps/analytics/       Account/post snapshots dan optimization signal
providers/            First-party social platform adapters
apps/api + apps/mcp/  Agent API dan MCP automation surface
```

Model baru berada dalam migration `apps/ai_automation/migrations/0001_initial.py`.

## Test dan quality checks

```bash
ruff check .
ruff format --check .
python manage.py check
python manage.py makemigrations --check --dry-run
pytest
```

Untuk menjalankan test AI automation dengan SQLite:

```bash
DATABASE_URL=sqlite:///db.sqlite3 pytest apps/ai_automation/tests --ds=config.settings.development
```

## Deployment

Konfigurasi tersedia untuk Docker Compose, Heroku (`app.json`), Render (`render.yaml`), dan Railway (`railway.toml`). Production membutuhkan PostgreSQL, HTTPS, persistent S3-compatible storage untuk media, worker background, dan credential social-platform milik operator.

Untuk VPS, gunakan konfigurasi production mandiri yang hanya mengekspos Caddy
di port 80/443:

```bash
docker compose --env-file .env -f docker-compose.prod.yml up -d --build
```

Checklist DNS, secret, firewall, superuser, health check, update, dan backup ada
di [`docs/deployment-vps.md`](docs/deployment-vps.md). Deployment production
gagal tertutup jika identitas legal, URL Terms/Privacy, source revision AGPL,
retention, atau disclosure subprocessor masih berupa placeholder.

Semua integrasi social menggunakan official first-party APIs dan credential Anda sendiri; tidak ada aggregator sebagai perantara.

## Lisensi dan upstream

Ruang menggunakan [GNU Affero General Public License v3.0](LICENSE). Pengguna
jaringan memperoleh tautan Corresponding Source untuk commit yang sedang
dijalankan dari footer dan `/legal/open-source/`. Operator wajib mengatur
`RUANG_SOURCE_CODE_REVISION` ke hasil `git rev-parse HEAD` pada setiap
deployment, membangun hanya dari worktree bersih, dan mempublikasikan seluruh
source modifikasi yang tercakup AGPL.

Upstream: [brightbeanxyz/brightbean-studio](https://github.com/brightbeanxyz/brightbean-studio).

Baseline Terms, Privacy, pelindungan data, PSE/PMSE, dan operasi kepatuhan
didokumentasikan di [`docs/legal-compliance.md`](docs/legal-compliance.md).
Dokumen ini bukan pengganti review penasihat hukum untuk badan usaha dan
praktik aktual operator.
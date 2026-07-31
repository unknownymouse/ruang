# Baseline legal dan pelindungan data Ruang

Dokumen ini adalah checklist implementasi teknis dan operasional per 31 Juli
2026, bukan pendapat hukum. Pemilik deployment tetap harus meminta penasihat
hukum Indonesia memetakan badan usaha, KBLI, model tagihan, target pengguna,
negara operasi, dan aliran data aktual.

## Gate sebelum monetisasi

Jangan menerima pembayaran atau membuka pendaftaran publik sampai semua hal ini
memiliki owner dan bukti:

- identitas badan usaha, NIB/KBLI, pajak, alamat, dan kontak publik telah benar;
- status pendaftaran PSE Lingkup Privat dan kewajiban PMSE telah dinilai;
- Terms/Privacy telah direview sesuai paket, refund, konsumen, dan SLA nyata;
- inventory data, dasar pemrosesan, retention, transfer lintas negara, DPA,
  subprocessors, serta prosedur hak subjek data telah disetujui;
- setiap provider AI/platform telah lulus review terms dan aplikasi;
- label/disclosure AI, approval manusia, complaint/correction, moderation, dan
  audit log sudah diaktifkan;
- incident response dan notifikasi kegagalan pelindungan data sudah diuji; dan
- Corresponding Source AGPL untuk commit produksi dapat diunduh tanpa login.

## 1. Kepatuhan AGPL SaaS

Ruang dan upstream didistribusikan dengan AGPL-3.0. Monetisasi, hosting, support,
dan layanan berbayar diperbolehkan, tetapi operator tidak boleh menutup source
modifikasi yang tercakup lisensi saat pengguna berinteraksi melalui jaringan.

Checklist setiap build:

1. Pertahankan `LICENSE`, `NOTICE`, notice copyright yang berlaku, dan riwayat
   atribusi upstream.
2. Publikasikan Corresponding Source lengkap untuk versi produksi: source
   modifikasi, definisi build/deployment, dan materi yang diperlukan untuk
   membangun/menjalankan versi itu; jangan sertakan secret atau data pengguna.
3. Pastikan `git status --porcelain --untracked-files=normal` kosong, lalu set
   `RUANG_SOURCE_CODE_REVISION=$(git rev-parse HEAD)` sebelum build.
4. Pastikan footer dan `/legal/open-source/` menuju commit tersebut dan dapat
   diakses tanpa login.
5. Jangan menawarkan source branch yang lebih lama atau source upstream saja
   jika server menjalankan modifikasi lain.
6. Jangan menambahkan pembatasan lisensi yang bertentangan dengan AGPL.
7. Pisahkan merek, konten pengguna, credential, serta kontrak layanan dari
   lisensi software secara jelas.

Rujukan: [GNU AGPL-3.0, khususnya bagian 5 dan
13](https://www.gnu.org/licenses/agpl-3.0.en.html) dan [GNU GPL
FAQ tentang penjualan software](https://www.gnu.org/licenses/gpl-faq.html#DoesTheGPLAllowMoney).

## 2. Terms, konsumen, dan perdagangan elektronik

Template Terms di `/legal/terms/` sudah memuat identitas operator, akun,
konten/lisensi terbatas, risiko AI, approval manusia, platform pihak ketiga,
larangan, layanan berbayar, penghentian, AGPL, pengaduan, dan hak wajib.
Operator harus mengganti/menambah:

- nama/alamat badan usaha dan channel pengaduan yang benar-benar dimonitor;
- harga, mata uang, pajak, quota, overage, auto-renewal, pembatalan, refund,
  invoice, dan kegagalan pembayaran;
- SLA/support, availability, backup, serta pembatasan tanggung jawab yang telah
  direview penasihat hukum;
- aturan promo, affiliate, hak cipta, model release, dan klaim iklan; serta
- yurisdiksi/penyelesaian sengketa sesuai segmen konsumen atau B2B.

Nilai apakah Ruang merupakan PSE Lingkup Privat dan/atau pelaku PMSE, lalu
selesaikan pendaftaran/perizinan melalui kanal resmi sebelum operasi jika masuk
ruang lingkup. Peraturan acuan utama:

- [PP 80/2019 tentang Perdagangan Melalui Sistem
  Elektronik](https://peraturan.bpk.go.id/Details/126143/pp-no-80-tahun-2019);
- [Permenkominfo 5/2020 tentang PSE Lingkup
  Privat](https://peraturan.bpk.go.id/Details/203049/permenkominfo-no-5-tahun-);
- [Permenkominfo 10/2021 sebagai
  perubahan](https://peraturan.bpk.go.id/Home/Details/203121/permenkominfo-no-10-tahun-2021);
- [Permendag 19/2026 tentang PMSE, berlaku 8 Juni
  2026](https://peraturan.bpk.go.id/Details/351720/permendag-no-19-tahun-2026).

Permendag 19/2026 mencakup pemanfaatan AI dalam PMSE. Untuk fitur yang masuk
ruang lingkup, review pasal final bersama penasihat hukum dan pastikan informasi
akurat, disclosure/label AI, tata kelola, privasi/IP, serta mekanisme
keluhan/koreksi tersedia. Implementasi Ruang membantu menyediakan approval,
audit, moderation, dan halaman pengaduan; konfigurasi dan operasi manusia tetap
wajib.

## 3. Pelindungan data pribadi

[UU 27/2022 tentang Pelindungan Data
Pribadi](https://peraturan.bpk.go.id/Details/229798/uu-no-27-tahun-2022.12UUD)
mengatur hak subjek, kewajiban pengendali/prosesor, transfer, sanksi, dan
notifikasi insiden. Baseline kode bukan bukti kepatuhan tanpa proses berikut.

### Inventory dan dasar pemrosesan

Simpan register yang memetakan tiap field/aliran ke: tujuan, kategori subjek,
dasar pemrosesan, controller/processor, penerima, negara, retention, keamanan,
dan owner. Larang data sensitif pada prompt secara default. Lakukan penilaian
dampak untuk pemrosesan berisiko tinggi, profiling, skala besar, data anak,
biometrik, atau keputusan otomatis yang relevan.

### Provider dan transfer

- Isi `RUANG_SUBPROCESSORS_JSON` sesuai provider aktif, bukan daftar contoh.
- Tanda tangani DPA dan periksa penggunaan data untuk training, retention,
  penghapusan, lokasi, subprocessor lanjutan, serta notifikasi insiden.
- Dokumentasikan mekanisme transfer lintas negara yang berlaku.
- Gunakan scope OAuth minimum dan hapus/revoke token saat koneksi atau akun
  dihapus.

### Hak subjek data

Settings menyediakan ekspor langsung dan intake permintaan tercatat. Petugas
privasi harus:

1. memverifikasi identitas dan kewenangan tanpa mengumpulkan data berlebihan;
2. menetapkan scope (akun, workspace, platform, provider, backup);
3. mencatat keputusan, pengecualian hukum, tindakan, dan waktu penyelesaian;
4. mengekspor dalam format aman serta mengirim melalui channel terverifikasi;
5. meneruskan koreksi/penghapusan ke processor/provider terkait; dan
6. memperbarui status/resolution di admin tanpa menaruh secret pada catatan.

### Penghapusan dan retention

Penghapusan akun menghapus avatar dan relasi akun aktif. Bukti persetujuan
pseudonim dan permintaan privasi dipisahkan dari user, sementara backup mengikuti
rotasi. Pastikan scheduled job/storage policy benar-benar menegakkan angka
retention yang dipublikasikan. Jangan menyatakan `permanently deleted` jika
backup atau kewajiban hukum masih mempertahankan salinan.

### Insiden

Runbook minimal: deteksi, containment, preservation of evidence, klasifikasi
data/subjek, keputusan notifikasi, komunikasi provider, recovery, dan
post-incident review. Jika UU PDP mewajibkan notifikasi, siapkan pemberitahuan
tertulis kepada subjek dan lembaga paling lambat 3 x 24 jam sejak kegagalan
diketahui, dengan data yang terdampak, waktu/cara kejadian, dan penanganan.

## 4. AI dan kebijakan platform

Untuk setiap provider/platform, simpan bukti review tanggal, versi terms,
scope, data yang dikirim, izin publish, rate limit, aturan konten AI, retention,
dan owner. Direct publishing tidak boleh dibuka sebelum aplikasi/permission
resmi disetujui.

- Meta/Instagram: gunakan Graph API dan app review resmi.
- TikTok: patuhi Content Posting API, audit/review, dan disclosure AIGC.
- LinkedIn: gunakan produk API dan permission yang diberikan.
- X: gunakan OAuth/API resmi, tier yang sesuai, dan developer policy.

Jangan menjanjikan bahwa moderation otomatis menjamin legalitas. Moderation
adalah kontrol berlapis bersama source checking, hak cipta/model release,
approval manusia, complaint channel, dan audit.

## 5. Operasi perubahan dokumen

Untuk perubahan material:

1. buat ticket dengan alasan, dampak, reviewer hukum/privasi, dan tanggal;
2. ubah template;
3. naikkan `RUANG_TERMS_VERSION` dan/atau `RUANG_PRIVACY_VERSION`;
4. perbarui `RUANG_LEGAL_EFFECTIVE_DATE`;
5. deploy dan pastikan middleware meminta acceptance ulang;
6. simpan snapshot dokumen per versi di arsip immutable; dan
7. komunikasikan perubahan sebelum berlaku bila diwajibkan.

## 6. Bukti verifikasi produksi

```bash
python manage.py check --deploy --settings=config.settings.production
python manage.py migrate --noinput
python manage.py makemigrations --check --dry-run
pytest
```

Simpan output CI, image digest, Git SHA, migration, hasil restore test, serta
snapshot Terms/Privacy sebagai bukti release. Pemeriksaan aplikasi sengaja
gagal bila konfigurasi legal utama masih placeholder; itu bukan pengganti audit
hukum maupun keamanan.

# Panduan Teknis Deploy Online & Pengumpulan Lomba HGN 2026

Panduan praktis langkah demi langkah agar **SIDIK-AI** siap dicoba Dewan Juri tanpa install apa pun, dan dokumen PDF Anda siap diunggah sebelum **Minggu, 29 November 2026 pukul 23.59 WIB**.

---

## Langkah 1 — Push Pembaruan Mode Demo ke GitHub

Setelah pembaruan Mode Demo SMK TKJ & konfigurasi Streamlit Cloud ini selesai, unggah perubahan terbaru ke GitHub Anda:

```powershell
git add .
git commit -m "feat: add 1-click TKJ Subnetting Demo Mode, Streamlit Cloud config, and HGN 2026 docs"
git push origin main
```

---

## Langkah 2 — Deploy Gratis ke Streamlit Community Cloud (±3 Menit)

Agar panitia/juri bisa membuka SIDIK-AI lewat link browser (HP/laptop) tanpa menginstal Python:

1. Buka **[https://share.streamlit.io](https://share.streamlit.io)** lalu masuk dengan akun GitHub (`hayodavis`).
2. Klik **Create app** → **Deploy a public app from GitHub**.
3. Isi konfigurasi berikut:
   - **Repository:** `hayodavis/sidik-ai`
   - **Branch:** `main`
   - **Main file path:** `app.py`
   - **App URL:** `sidik-ai` → **`https://sidik-ai.streamlit.app`**
4. *(Opsional, disarankan)* Klik **Advanced settings → Secrets** jika ingin juri juga bisa menguji foto sungguhan tanpa memasukkan API Key sendiri, lalu tempel:
   ```toml
   GROQ_API_KEY = "gsk_isi_api_key_groq_anda_disini"
   ```
   *(Meskipun Secrets dikosongkan, juri tetap bisa langsung mencoba tombol **🎯 Muat Mode Demo TKJ** dalam 1 klik!)*
5. Klik **Deploy!** dan tunggu ±2–3 menit sampai aplikasi aktif.

---

## Langkah 3 — Rekam Video Demo Singkat 2 Menit (Opsional tapi Sangat Kuat)

Gunakan perekam layar bawaan Windows (`Win + Alt + R`) atau OBS dengan alur ringkas:
- **00:00 – 00:25:** Sapa singkat (*"Assalamualaikum/Salam sejahtera, saya [Nama], guru TKJ di [SMK]..."*) dan tampilkan Tab 1 (Modul PDF *Konsep Dasar Subnetting* sudah terindeks).
- **00:25 – 01:15:** Pindah ke Tab 2, tampilkan soal Subnetting + rubrik 2 kolom, unggah 2–3 foto jawaban siswa, klik **🚀 Mulai Koreksi Otomatis AI**, tunjukkan proses selesai dalam hitungan detik.
- **01:15 – 02:00:** Pindah ke Tab 3, tunjukkan 3 metrik kelas, inspeksi foto tulisan tangan vs transkripsi LaTeX + peringatan kuning **Perlu Validasi Guru**, lalu klik **📥 Unduh Rekap Nilai Excel**.
- Unggah video ke **Google Drive** (ubah akses: *Siapa saja yang memiliki tautan dapat melihat*) atau **YouTube (Unlisted)**.

---

## Langkah 4 — Lengkapi Placeholder & Cetak Ulang PDF Final

Buka file `docs/lomba_hgn_2026/Kisah_Inspiratif_SIDIK_AI_TKJ.html` (pakai VS Code / Notepad) dan ganti semua teks bertanda `[ISI ...]`:
1. Nama lengkap & gelar, Asal SMK, Nomor WA aktif (wajib untuk hadiah panitia).
2. Jumlah siswa/kelas TKJ yang Anda ajar.
3. Link **Streamlit Cloud** dan **Video Demo** (jika sudah dibuat).
4. Testimoni asli 1–2 kalimat dari siswa TKJ Anda.
5. Ganti kotak `[TEMPAT FOTO DOKUMENTASI NYATA KELAS / LAB TKJ ANDA]` dengan foto asli kegiatan kelas/lab TKJ Anda (simpan foto ke folder `docs/lomba_hgn_2026/foto_kelas.jpg`, lalu ganti `<div class="photo-placeholder">...</div>` dengan `<div class="figure"><img src="foto_kelas.jpg" /><div class="figure-caption">Dokumentasi pendampingan siswa TKJ...</div></div>`).

**Cara cepat mencetak ulang HTML ke PDF (1 perintah di PowerShell):**
```powershell
& "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --headless --disable-gpu --no-pdf-header-footer --print-to-pdf="C:\Users\davis\Desktop\sidik-ai\docs\lomba_hgn_2026\Kisah_Inspiratif_SIDIK_AI_TKJ.pdf" "file:///C:/Users/davis/Desktop/sidik-ai/docs/lomba_hgn_2026/Kisah_Inspiratif_SIDIK_AI_TKJ.html"
```
*(Atau buka file `.html` tersebut di browser Edge/Chrome → tekan `Ctrl + P` → pilih **Save as PDF** → matikan *Headers and footers* → aktifkan *Background graphics* → Save!)*

---

## Checklist Final Sebelum Upload ke Google Drive Panitia

- [ ] Nama file PDF rapi, misalnya: `Kisah_Inspiratif_HGN2026_[Nama_Anda]_[Nama_SMK].pdf`
- [ ] Nama lengkap, Asal Sekolah, dan **Nomor WA** sudah tertulis jelas di halaman pertama PDF
- [ ] Tidak ada placeholder kuning `[ISI ...]` yang tertinggal
- [ ] Link GitHub / Live Demo / Video Demo sudah dicoba di mode Incognito dan bisa dibuka publik
- [ ] Unggah ke folder panitia sebelum **Minggu, 29 November 2026 pukul 23.59 WIB**:
  `https://drive.google.com/drive/folders/1Yd-IR-g_f5ev4QY1HqDczGKeHAgbfkuW`

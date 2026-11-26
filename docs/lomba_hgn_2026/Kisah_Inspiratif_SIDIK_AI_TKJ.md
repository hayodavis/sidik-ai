# Ketika AI Membantu Mengoreksi Kertas, Guru Kembali Mendidik Hati

**Kisah Nyata Guru SMK Teknik Komputer dan Jaringan Menghadirkan SIDIK-AI untuk Umpan Balik Personal dan Adil pada Pembelajaran *Subnetting***

---

**Identitas Peserta — Lomba Kisah Inspiratif Guru SMA/SMK/PKLK Kabupaten Malang Tahun 2026**
- **Nama Penulis:** `[ISI NAMA LENGKAP & GELAR ANDA]`
- **Asal Sekolah:** `[ISI NAMA SMK ANDA — KABUPATEN MALANG]`
- **Konsentrasi Keahlian:** Teknik Komputer dan Jaringan (TKJ)
- **Nomor WhatsApp:** `[ISI NOMOR WA AKTIF ANDA]`
- **Repositori GitHub:** `https://github.com/hayodavis/sidik-ai`
- **Live Demo Web App:** `https://sidik-ai.streamlit.app`
- **Video Demo (2 Menit):** `[ISI LINK VIDEO DEMO GOOGLE DRIVE / YOUTUBE]`

---

## 1. Tumpukan Kertas Subnetting dan Keresahan di Balik Meja Guru

Setiap kali ulangan harian materi **Konsep Dasar Subnetting IPv4 dan VLSM** selesai dilaksanakan di kelas Teknik Komputer dan Jaringan (TKJ), meja kerja saya selalu dipenuhi tumpukan lembar jawaban tulisan tangan siswa. Bagi siswa SMK TKJ, *subnetting* adalah fondasi penting sebelum mereka mengonfigurasi router, membangun jaringan laboratorium, atau terjun ke dunia kerja industri jaringan. Namun di sisi lain, materi ini pula yang paling sering membuat siswa menyerah di tengah jalan.

Bukan karena mereka tidak mampu, melainkan karena perhitungan *subnetting* menuntut ketelitian berantai: mengubah prefix CIDR ke biner, menghitung blok subnet, mencari jumlah host aktif (`2^h - 2`), hingga menentukan *Network ID*, rentang *IP Host Valid*, dan *Broadcast Address*. Satu langkah keliru di awal—misalnya lupa mengurangi 2 untuk alamat jaringan dan broadcast—akan menggeser jawaban akhir mereka.

Di sanalah keresahan hati saya sebagai guru muncul. Ketika mengajar beberapa kelas paralel dengan jumlah total `[ISI JUMLAH SISWA, misal: 108 siswa dari 3 kelas XI TKJ]`, mengoreksi seluruh lembar secara manual sekaligus menuliskan catatan perbaikan personal di setiap kertas menyita waktu hingga berjam-jam, bahkan sering terbawa pulang hingga larut malam. Akibatnya, siswa sering baru menerima hasil beberapa hari kemudian—itu pun terkadang hanya berupa angka nilai tanpa penjelasan rinci di langkah mana mereka keliru. Saat kertas dibagikan, sebagian siswa hanya menatap angka merahnya dengan bingung, lalu melipatnya tanpa pernah benar-benar memahami kesalahannya.

> *“Saya sadar, anak-anak SMK TKJ tidak butuh sekadar angka 60 atau 70 di pojok kertas. Mereka butuh guru yang menunjukkan dengan sabar: langkah mana yang sudah benar untuk diapresiasi, dan di titik mana mereka perlu berlatih lagi.”*

---

## 2. Tantangan Nyata: Ingin Adil pada Proses, Namun Terbatas Waktu dan Biaya

Sebagai guru kejuruan di bidang teknologi jaringan, saya bertanya pada diri sendiri: *mengapa kecerdasan artifisial (AI) yang berkembang begitu pesat belum kita manfaatkan untuk meringankan beban koreksi guru secara sehat dan mendidik?* Namun saat mulai mencari solusi, saya menghadapi tiga tantangan besar:

1. **Koreksi eksakta & TKJ tidak boleh hanya melihat hasil akhir.** Banyak alat koreksi otomatis hanya cocok untuk pilihan ganda atau isian singkat. Padahal pada perhitungan jaringan, siswa yang langkah konsep dan rumusnya sudah benar namun keliru hitung kecil di akhir tetap layak mendapatkan skor parsial yang adil.
2. **Keterbatasan biaya dan kuota.** Layanan AI komersial berbayar sulit diterapkan secara berkelanjutan di lingkungan sekolah. Bahkan saat awal uji coba, saya beberapa kali menemui kendala batas kuota API dan kredit habis.
3. **Kekhawatiran hilangnya sentuhan kemanusiaan guru.** Saya tidak ingin teknologi membuat guru menjadi “lepas tangan” dan menyerahkan nasib nilai siswa sepenuhnya kepada mesin.

---

## 3. Aksi Nyata: Merancang SIDIK-AI, Asisten Koreksi Lokal Berbasis Modul Guru

Berbekal semangat sebagai guru pembelajar, saya mulai merancang dan mengembangkan sendiri aplikasi web lokal bernama **SIDIK-AI (Sistem Digitalisasi & Koreksi Esai Berbasis AI)**. Aplikasi ini berjalan langsung di laptop guru melalui browser dengan antarmuka sederhana dalam bahasa Indonesia, sehingga mudah digunakan oleh guru lain pula.

Ada empat prinsip utama yang saya tanamkan ke dalam SIDIK-AI agar benar-benar selaras dengan kebutuhan kelas SMK:

- **Berpatokan pada Modul Ajar Guru Sendiri (RAG Lokal):** Guru cukup mengunggah file PDF modul ajar—seperti *Modul Konsep Dasar Subnetting*—ke memori lokal aplikasi (ChromaDB). Saat menilai, AI tidak mengarang teori sendiri, melainkan merujuk langsung pada modul dan rubrik yang dipakai di kelas.
- **Membaca Tulisan Tangan & Menilai Per Langkah (Multi-Soal):** Lembar jawaban siswa cukup difoto menggunakan kamera HP. SIDIK-AI otomatis memperbaiki posisi foto yang miring, menyalin tulisan tangan serta rumus siswa ke format matematis yang rapi, lalu memecah penilaian menjadi tiga aspek adil: *Pemahaman Konsep (40)*, *Langkah Perhitungan (40)*, dan *Hasil & Satuan (20)*—bahkan mampu menilai banyak nomor soal sekaligus dalam satu lembar.
- **Hemat Biaya & Fleksibel Multi-Provider:** Belajar dari kendala limit API, saya mengembangkan dukungan 4 jalur AI (Groq Vision yang gratis dan sangat cepat sekitar 1–2 detik per lembar, OpenRouter, Google Gemini, serta Ollama Lokal 100% offline tanpa kuota) ditambah sistem *cache* pintar agar lembar yang sama tidak memakan kuota ulang.
- **Prinsip *Human-in-the-Loop* (Validasi Guru):** SIDIK-AI diprogram untuk secara otomatis memberi tanda peringatan kuning **“Perlu Validasi Guru”** apabila tulisan siswa buram, terdapat banyak coretan revisi, siswa memakai cara cepat alternatif yang valid namun berbeda dari modul, atau total nilai berada di area batas kritis KKM (**68–76**).

---

## 4. Guru Tetap Nahkoda: Saat Teknologi Memanusiakan Penilaian

Bagian yang paling saya syukuri dari SIDIK-AI adalah **Tab Validasi Guru & Rekap Nilai**. Di layar ini, foto asli tulisan tangan siswa ditampilkan berdampingan dengan hasil transkripsi rumus, analisis per nomor soal, serta umpan balik personal yang ramah dan memotivasi. Guru dapat langsung memeriksa lembar yang bertanda *Perlu Validasi Guru*, mengubah skor secara manual bila diperlukan, lalu mengekspor seluruh rekap ke Microsoft Excel (`.xlsx`) dalam satu klik.

> **Praktik Baik Validasi Guru:** Pernah dalam latihan di kelas, seorang siswa menggunakan cara cepat tabel pangkat untuk menentukan prefix `/27` tanpa menjabarkan biner panjang seperti di modul, disertai beberapa coretan revisi. SIDIK-AI langsung memberi tanda kuning *Perlu Validasi Guru*. Saya dapat langsung meninjau foto aslinya, mengapresiasi kreativitas cara berpikirnya, lalu mengoreksi satu kekeliruan kecilnya secara langsung di depan meja praktik. Siswa merasa benar-benar dilihat dan dihargai usahanya.

---

## 5. Dampak Nyata bagi Pembelajaran di Kelas SMK TKJ

| Aspek Pembelajaran | Sebelum Menggunakan SIDIK-AI | Sesudah Menggunakan SIDIK-AI |
| --- | --- | --- |
| **Waktu Koreksi (1 Kelas)** | ±2,5 hingga 3 jam koreksi manual bertahap (sering tertunda beberapa hari). | ±5 hingga 10 menit untuk foto, koreksi batch, dan validasi guru pada lembar kritis. |
| **Kualitas Umpan Balik** | Umumnya berupa angka nilai dan coretan singkat karena keterbatasan waktu. | Setiap siswa menerima umpan balik personal yang ramah, spesifik per langkah, dan memotivasi. |
| **Pendampingan Siswa** | Guru kelelahan secara administratif; remedial sering bersifat umum. | Guru segera mengetahui pola miskonsepsi tiap siswa (misal lupa `2^h - 2`) dan langsung membimbing di lab. |
| **Rekap Administrasi** | Input ulang nilai satu per satu ke spreadsheet secara manual. | Otomatis tersusun dalam rekap Excel (`.xlsx`) lengkap dengan skor per soal & catatan analisis. |

- **Dokumentasi Foto Kelas:** `[SISIPKAN 1–2 FOTO SUASANA PENDAMPINGAN SISWA DI LAB/KELAS TKJ]`
- **Testimoni Siswa:** `“[ISI 1–2 KALIMAT TESTIMONI ASLI SISWA TKJ ANDA]”` — `[Inisial Siswa, Kelas XI TKJ ...]`

---

## 6. Refleksi: Satu Langkah Kecil untuk Pendidikan yang Lebih Bermakna

Perjalanan membangun SIDIK-AI mengajarkan saya satu pelajaran penting tentang makna profesi guru di era kecerdasan artifisial. Di tengah kekhawatiran sebagian orang bahwa AI akan menggeser peran pendidik, pengalaman kecil di kelas SMK TKJ ini justru membuktikan sebaliknya: **teknologi terbaik adalah teknologi yang mengembalikan waktu guru untuk kembali mendidik hati.**

Ketika mesin membantu mengerjakan tugas mekanis membaca lembar demi lembar dan merapikan rekap nilai, saya memiliki energi yang utuh untuk duduk di samping siswa yang kesulitan memahami jaringan, menyemangati mereka yang hampir putus asa, dan merayakan setiap langkah kecil kemajuan mereka.

Saya pun membuka kode sumber SIDIK-AI secara gratis di GitHub agar rekan-rekan guru SMK, SMA, maupun PKLK lainnya—tidak hanya di mata pelajaran TKJ, tetapi juga Matematika, Fisika, dan Kimia—dapat ikut memanfaatkannya, memodifikasinya, dan bersama-sama menghadirkan pembelajaran yang lebih adil dan bermakna bagi generasi penerus bangsa.

---

## Lampiran: Panduan Akses & Uji Coba SIDIK-AI untuk Dewan Juri

1. **Aplikasi Web Interaktif:** `https://sidik-ai.streamlit.app`
2. **Video Demo (2 Menit):** `[ISI LINK VIDEO DEMO]`
3. **Kode Sumber Terbuka:** `https://github.com/hayodavis/sidik-ai`

**Cara Mencoba Instan dalam 30 Detik (Tanpa API Key):**
1. Buka tautan Aplikasi Web Interaktif melalui browser laptop atau ponsel.
2. Klik tombol **“🎯 Muat Mode Demo TKJ”** di sidebar kiri (atau Tab 3).
3. Buka tab **“✅ Validasi Guru & Rekap Nilai”** untuk mencoba editor skor, inspeksi foto *Subnetting* vs rumus LaTeX, status *Perlu Validasi Guru*, dan unduh rekap Excel (`.xlsx`).

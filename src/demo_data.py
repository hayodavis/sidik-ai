"""Data simulasi Mode Demo SMK TKJ (Materi Subnetting IPv4) untuk SIDIK-AI.

Memungkinkan juri, panitia, maupun guru mencoba seluruh alur SIDIK-AI
(Multi-Soal 2 Kolom, KPI Kelas, Tabel Editor, Inspeksi Foto vs LaTeX,
Validasi Guru area kritis 68-76, dan Ekspor Excel) dalam 1 klik tanpa API Key.
"""

from __future__ import annotations

from typing import Any

from PIL import Image, ImageDraw, ImageFont


def _muat_font_demo(ukuran: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Memuat font bersih lintas OS (Windows/Linux Cloud) dengan fallback bawaan Pillow."""
    kandidat = [
        "segoesc.ttf",
        "comic.ttf",
        "arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path_font in kandidat:
        try:
            return ImageFont.truetype(path_font, size=ukuran)
        except OSError:
            continue
    return ImageFont.load_default(size=ukuran)


def _buat_gambar_kertas_jawaban(
    nama_siswa: str,
    kelas: str,
    baris_jawaban: list[str],
    tanda_coretan: bool = False,
) -> Image.Image:
    """Membuat gambar simulasi lembar kertas folio bergaris berisi jawaban Subnetting TKJ."""
    lebar, tinggi = 900, 1120
    img = Image.new("RGB", (lebar, tinggi), color=(252, 251, 246))
    draw = ImageDraw.Draw(img)

    # Garis buku tulis horizontal biru lembut & garis margin merah di kiri
    for y in range(130, tinggi - 40, 38):
        draw.line([(40, y), (lebar - 40, y)], fill=(214, 228, 245), width=1)
    draw.line([(105, 40), (105, tinggi - 40)], fill=(235, 165, 165), width=2)
    draw.rectangle([(35, 35), (lebar - 35, tinggi - 35)], outline=(210, 214, 220), width=2)

    font_judul = _muat_font_demo(26)
    font_meta = _muat_font_demo(21)
    font_isi = _muat_font_demo(22)

    warna_tinta = (24, 52, 118)
    warna_header = (30, 41, 59)

    draw.text((125, 52), "LEMBAR JAWABAN ULANGAN HARIAN — TKJ", fill=warna_header, font=font_judul)
    draw.text((125, 92), f"Nama: {nama_siswa}   |   Kelas: {kelas}", fill=warna_tinta, font=font_meta)
    draw.line([(125, 124), (lebar - 55, 124)], fill=(120, 130, 150), width=2)

    y_pos = 142
    for baris in baris_jawaban:
        if baris.startswith("---"):
            y_pos += 10
            continue
        draw.text((125, y_pos), baris, fill=warna_tinta, font=font_isi)
        if tanda_coretan and "2^4" in baris:
            # Simulasi coretan revisi siswa pada angka pangkat tanpa menimpa teks
            draw.line([(255, y_pos + 15), (470, y_pos + 15)], fill=(180, 40, 40), width=3)
            draw.text((482, y_pos - 1), "revisi: 2^5 - 2 = 30 host", fill=(180, 40, 40), font=font_meta)
        y_pos += 38

    draw.text(
        (125, tinggi - 72),
        "[Simulasi Lembar Jawaban Mode Demo — SIDIK-AI SMK TKJ]",
        fill=(140, 150, 165),
        font=_muat_font_demo(16),
    )
    return img


def buat_paket_demo_tkj() -> dict[str, Any]:
    """Menyusun paket data demo lengkap (2 soal Subnetting + 3 hasil koreksi siswa)."""
    daftar_soal = [
        {
            "nomor": 1,
            "pertanyaan": (
                "Diberikan alamat jaringan 192.168.10.0/26. Tentukan:\n"
                "(a) Subnet Mask dalam notasi desimal,\n"
                "(b) Jumlah subnet dan jumlah host aktif per subnet, serta\n"
                "(c) Network ID, Range IP Host Valid, dan Broadcast Address untuk subnet pertama!"
            ),
            "rubrik": (
                "Bobot 50 poin:\n"
                "- Menentukan biner /26 -> Subnet Mask 255.255.255.192 (15 poin).\n"
                "- Menghitung jumlah subnet 2^2 = 4 dan host aktif 2^6 - 2 = 62 host (15 poin).\n"
                "- Menuliskan subnet 1: Network 192.168.10.0, Host 192.168.10.1 - 192.168.10.62, Broadcast 192.168.10.63 (20 poin)."
            ),
            "bobot": 50,
        },
        {
            "nomor": 2,
            "pertanyaan": (
                "Sebuah laboratorium SMK TKJ membutuhkan jaringan untuk 28 unit PC siswa "
                "dari blok 172.16.5.0/24. Tentukan prefix CIDR paling efisien (VLSM) yang "
                "dapat digunakan beserta jumlah sisa IP host yang masih tersedia!"
            ),
            "rubrik": (
                "Bobot 50 poin:\n"
                "- Menentukan kebutuhan bit host: 2^h - 2 >= 28 -> h = 5 (2^5 - 2 = 30 host) (20 poin).\n"
                "- Menghitung prefix CIDR efisien: 32 - 5 = /27 (Subnet Mask 255.255.255.224) (15 poin).\n"
                "- Menghitung sisa IP host tersedia: 30 - 28 = 2 IP host cadangan (15 poin)."
            ),
            "bobot": 50,
        },
    ]

    gambar_1 = _buat_gambar_kertas_jawaban(
        "Rizky Pratama",
        "XI TKJ 1",
        [
            "Jawab No. 1 (IP: 192.168.10.0/26)",
            "a) /26 = 11111111.11111111.11111111.11000000",
            "   Subnet Mask = 255.255.255.192",
            "b) Bit subnet (n) = 2 -> Jumlah subnet = 2^2 = 4 subnet",
            "   Bit host (h) = 6 -> Host aktif = 2^6 - 2 = 64 - 2 = 62 host",
            "c) Blok subnet = 256 - 192 = 64",
            "   Subnet 1:",
            "   - Network ID : 192.168.10.0",
            "   - Host Valid : 192.168.10.1 s/d 192.168.10.62",
            "   - Broadcast  : 192.168.10.63",
            "---",
            "Jawab No. 2 (Kebutuhan = 28 PC Lab TKJ)",
            "Syarat: 2^h - 2 >= 28",
            "Coba h = 5 -> 2^5 - 2 = 32 - 2 = 30 host (memenuhi)",
            "Prefix CIDR = 32 - 5 = /27 (Mask 255.255.255.224)",
            "Sisa IP host tersedia = 30 - 28 = 2 IP cadangan.",
        ],
    )

    gambar_2 = _buat_gambar_kertas_jawaban(
        "Nabila Putri",
        "XI TKJ 1",
        [
            "No. 1) 192.168.10.0/26",
            "Mask: /26 berarti sisa 6 bit 0 -> 255.255.255.192",
            "Jumlah subnet = 4, Host = 62 (karena 64 - 2)",
            "Subnet ke-1:",
            "Net = 192.168.10.0 | Broadcast = 192.168.10.63",
            "Range Host = 192.168.10.1 - 192.168.10.62",
            "---",
            "No. 2) Lab butuh 28 PC (cara tabel pangkat cepat):",
            "Cek blok: 2^4 = 16 (kurang)",
            "Prefix = /27 (karena /24 + 3 bit pinjam)",
            "Sisa IP = 32 - 28 = 4 IP (lupa dikurangi Net & Broadcast)",
        ],
        tanda_coretan=True,
    )

    gambar_3 = _buat_gambar_kertas_jawaban(
        "Dimas Saputra",
        "XI TKJ 1",
        [
            "1. IP 192.168.10.0/26",
            "   Subnet mask = 255.255.255.192",
            "   Jumlah subnet = 2^2 = 4",
            "   Jumlah host = 2^6 = 64 host (belum dikurangi 2)",
            "   Subnet 1: 192.168.10.0 - 192.168.10.64",
            "---",
            "2. Kebutuhan 28 PC:",
            "   Pakai /28 karena dekat dengan angka 28",
            "   Subnet mask = 255.255.255.240",
            "   Sisa IP = 0",
        ],
    )

    gambar_siswa = {
        "demo_1_rizky.jpg": gambar_1,
        "demo_2_nabila.jpg": gambar_2,
        "demo_3_dimas.jpg": gambar_3,
    }

    hasil_koreksi = [
        {
            "id_lembar": "demo_1_rizky.jpg",
            "nama_file": "demo_1_rizky.jpg",
            "status": "berhasil",
            "provider_digunakan": "groq",
            "model_digunakan": "qwen/qwen3.8-27b (Demo)",
            "dari_cache": True,
            "fallback_digunakan": False,
            "waktu_proses_detik": 1.6,
            "error": None,
            "nama_siswa": "Rizky Pratama (XI TKJ 1)",
            "transkripsi_jawaban_latex": (
                "**Soal No. 1:**\n"
                "- Subnet Mask $/26$: `255.255.255.192`\n"
                "- Jumlah subnet $= 2^2 = 4$, host aktif $= 2^6 - 2 = 62$ host\n"
                "- Subnet 1: Network `192.168.10.0`, Host `192.168.10.1–192.168.10.62`, Broadcast `192.168.10.63`\n\n"
                "**Soal No. 2:**\n"
                "- Syarat $2^h - 2 \\ge 28 \\Rightarrow h = 5$ ($2^5 - 2 = 30$ host)\n"
                "- Prefix efisien $= 32 - 5 = /27$, sisa host $= 30 - 28 = 2$ IP cadangan."
            ),
            "analisis_langkah": (
                "Seluruh konsep biner CIDR, penentuan blok subnet (256 - 192 = 64), "
                "perhitungan host aktif ($2^h - 2$), dan pemilihan prefix VLSM $/27$ sangat tepat dan runtut."
            ),
            "skor_konsep": 40,
            "skor_langkah_perhitungan": 38,
            "skor_hasil_dan_satuan": 20,
            "total_nilai": 98,
            "umpan_balik_siswa": (
                "Luar biasa, Rizky! Langkah perhitungan subnetting biner hingga pemilihan VLSM /27 "
                "sudah sangat sistematis dan akurat. Pertahankan ketelitian penulisan Network ID dan Broadcast Address."
            ),
            "perlu_validasi_guru": False,
            "alasan_validasi": "-",
            "rincian_per_soal": [
                {
                    "nomor_soal": 1,
                    "transkripsi_latex": (
                        "Mask $/26 = \\text{255.255.255.192}$, Subnet $= 2^2 = 4$, "
                        "Host aktif $= 2^6 - 2 = 62$. Subnet 1: `192.168.10.0` – `192.168.10.63`."
                    ),
                    "analisis_langkah": "Konsep, perhitungan blok subnet, dan rentang IP host tepat seluruhnya.",
                    "skor_diperoleh": 49,
                    "skor_maksimal": 50,
                },
                {
                    "nomor_soal": 2,
                    "transkripsi_latex": (
                        "$2^h - 2 \\ge 28 \\Rightarrow h = 5 \\Rightarrow /27$, "
                        "sisa IP $= 30 - 28 = 2$ IP host."
                    ),
                    "analisis_langkah": "Penentuan prefix VLSM dan sisa IP host cadangan sangat tepat.",
                    "skor_diperoleh": 49,
                    "skor_maksimal": 50,
                },
            ],
        },
        {
            "id_lembar": "demo_2_nabila.jpg",
            "nama_file": "demo_2_nabila.jpg",
            "status": "berhasil",
            "provider_digunakan": "groq",
            "model_digunakan": "qwen/qwen3.8-27b (Demo)",
            "dari_cache": True,
            "fallback_digunakan": False,
            "waktu_proses_detik": 1.8,
            "error": None,
            "nama_siswa": "Nabila Putri (XI TKJ 1)",
            "transkripsi_jawaban_latex": (
                "**Soal No. 1:**\n"
                "- Mask $/26$: `255.255.255.192`, Subnet $= 4$, Host $= 62$\n"
                "- Net `192.168.10.0`, Host `192.168.10.1–192.168.10.62`, Broadcast `192.168.10.63`\n\n"
                "**Soal No. 2:**\n"
                "- Memakai metode tabel pangkat cepat dengan coretan revisi: $2^5 - 2 = 30$ host $\\Rightarrow /27$\n"
                "- Sisa IP ditulis $32 - 28 = 4$ IP (belum dikurangi 2 alamat Network & Broadcast)."
            ),
            "analisis_langkah": (
                "Soal No. 1 benar seluruhnya meski langkah konversi biner ditulis ringkas. "
                "Pada Soal No. 2, metode tabel cepat untuk menemukan $/27$ valid, namun terdapat "
                "coretan revisi dan kekeliruan akhir saat menghitung sisa IP host ($32 - 28$ seharusnya $30 - 28 = 2$)."
            ),
            "skor_konsep": 32,
            "skor_langkah_perhitungan": 28,
            "skor_hasil_dan_satuan": 14,
            "total_nilai": 74,
            "umpan_balik_siswa": (
                "Kerja bagus, Nabila! Pemahaman subnetting No. 1 dan cara cepat menentukan prefix /27 "
                "sudah tepat. Perlu lebih teliti saat menghitung sisa IP host di akhir: gunakan host aktif (30), "
                "bukan total blok (32), karena 2 IP terpakai untuk Network ID dan Broadcast."
            ),
            "perlu_validasi_guru": True,
            "alasan_validasi": (
                "Terdapat coretan revisi, menggunakan metode tabel cepat alternatif pada Soal No. 2, "
                "dan total nilai (74) berada di area kritis 68-76."
            ),
            "rincian_per_soal": [
                {
                    "nomor_soal": 1,
                    "transkripsi_latex": (
                        "Mask `255.255.255.192`, 4 subnet, 62 host. "
                        "Net `192.168.10.0`, Host `.1–.62`, Broadcast `.63`."
                    ),
                    "analisis_langkah": "Hasil akhir benar semua; penjabaran langkah biner cukup singkat.",
                    "skor_diperoleh": 42,
                    "skor_maksimal": 50,
                },
                {
                    "nomor_soal": 2,
                    "transkripsi_latex": (
                        "Revisi: $2^5 - 2 = 30 \\Rightarrow /27$. Sisa IP $= 32 - 28 = 4$ IP."
                    ),
                    "analisis_langkah": (
                        "Prefix /27 benar memakai metode tabel alternatif, namun perhitungan sisa IP "
                        "keliru memakai total 32 alih-alih 30 host aktif."
                    ),
                    "skor_diperoleh": 32,
                    "skor_maksimal": 50,
                },
            ],
        },
        {
            "id_lembar": "demo_3_dimas.jpg",
            "nama_file": "demo_3_dimas.jpg",
            "status": "berhasil",
            "provider_digunakan": "groq",
            "model_digunakan": "qwen/qwen3.8-27b (Demo)",
            "dari_cache": True,
            "fallback_digunakan": False,
            "waktu_proses_detik": 1.5,
            "error": None,
            "nama_siswa": "Dimas Saputra (XI TKJ 1)",
            "transkripsi_jawaban_latex": (
                "**Soal No. 1:**\n"
                "- Subnet Mask `255.255.255.192`, Jumlah subnet $= 2^2 = 4$, Host $= 2^6 = 64$\n"
                "- Subnet 1 ditulis `192.168.10.0 - 192.168.10.64`\n\n"
                "**Soal No. 2:**\n"
                "- Memilih $/28$ (`255.255.255.240`) karena angkanya dekat dengan 28 PC, sisa IP $= 0$."
            ),
            "analisis_langkah": (
                "Konsep awal menentukan Subnet Mask `/26` dan jumlah subnet sudah benar (diberi skor parsial). "
                "Namun siswa lupa mengurangi 2 pada rumus host aktif ($2^6 - 2 = 62$) dan keliru memahami "
                "makna angka prefix `/28` sebagai jumlah PC (padahal `/28` hanya menyediakan $2^4 - 2 = 14$ host)."
            ),
            "skor_konsep": 24,
            "skor_langkah_perhitungan": 22,
            "skor_hasil_dan_satuan": 10,
            "total_nilai": 56,
            "umpan_balik_siswa": (
                "Semangat, Dimas! Penentuan Subnet Mask 255.255.255.192 dan jumlah subnet (4) sudah benar. "
                "Dua hal penting yang perlu diperbaiki: (1) jumlah host aktif selalu dikurangi 2 ($2^h - 2$), "
                "dan (2) angka /28 bukan berarti 28 PC — untuk 28 PC gunakan /27 karena $2^{32-27}-2 = 30$ host. "
                "Mari kita latihan bareng di lab ya!"
            ),
            "perlu_validasi_guru": False,
            "alasan_validasi": "-",
            "rincian_per_soal": [
                {
                    "nomor_soal": 1,
                    "transkripsi_latex": (
                        "Mask `255.255.255.192`, Subnet $= 4$, Host $= 64$, Subnet 1: `.0 - .64`."
                    ),
                    "analisis_langkah": (
                        "Mask & jumlah subnet tepat; keliru pada host aktif (64 bukan 62) dan batas broadcast (.64 seharusnya .63)."
                    ),
                    "skor_diperoleh": 34,
                    "skor_maksimal": 50,
                },
                {
                    "nomor_soal": 2,
                    "transkripsi_latex": "Memilih $/28$ (`255.255.255.240`), sisa IP $= 0$.",
                    "analisis_langkah": (
                        "Miskonsepsi antara angka prefix (/28) dengan kapasitas host (28 PC). Seharusnya /27 (30 host)."
                    ),
                    "skor_diperoleh": 22,
                    "skor_maksimal": 50,
                },
            ],
        },
    ]

    return {
        "nama_ujian": "UH1_TKJ_Subnetting_IPv4",
        "daftar_soal": daftar_soal,
        "gambar_siswa": gambar_siswa,
        "hasil_koreksi": hasil_koreksi,
    }

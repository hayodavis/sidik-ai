"""Mesin koreksi esai tulisan tangan berbasis Multimodal RAG & Multi-Provider AI untuk SIDIK-AI.

Mendukung 4 provider Vision LLM secara modular:
- Groq (Gratis & Super Cepat: Qwen 3.8 27B Vision)
- OpenRouter (Multi-Model Gratis/Murah: openrouter/free, Gemma 4, Nemotron VL, dll.)
- Ollama Lokal (100% Offline, Gratis, Unlimited: qwen2.5vl, gemma3, llama3.2-vision)
- Google Gemini API (gemini-3.8-flash, fallback gemini-3.5-flash-lite, audit gemini-4-neon)
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

import httpx
from google import genai
from google.genai import errors, types
from PIL import Image
from pydantic import BaseModel, Field

try:
    from src.ingest_rag import cari_konteks_materi, cari_konteks_multi_soal
    from src.utils import gambar_ke_jpeg_bytes
except ImportError:
    from ingest_rag import cari_konteks_materi, cari_konteks_multi_soal  # type: ignore[no-redef]
    from utils import gambar_ke_jpeg_bytes  # type: ignore[no-redef]

CACHE_DIR = "./data/cache"

# Konstanta Model per Provider
MODEL_UTAMA_FREE = "gemini-3.8-flash"
MODEL_FALLBACK_FREE = "gemini-3.5-flash-lite"
MODEL_AUDIT_NEON = "gemini-4-neon"

MODEL_GROQ_UTAMA = "qwen/qwen3.8-27b"
MODEL_GROQ_FALLBACK: str | None = None

MODEL_OPENROUTER_UTAMA = "openrouter/free"
MODEL_OPENROUTER_FALLBACK = "google/gemma-4-31b-it:free"

MODEL_OLLAMA_DEFAULT = "qwen2.5vl:7b"
OLLAMA_DEFAULT_BASE_URL = "http://localhost:11434"

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"

THINKING_LEVEL_CEPAT = "minimal"
THINKING_LEVEL_TELITI = "low"
THINKING_LEVEL_NEON = "high"

RENTANG_KRITIS_MIN = 68
RENTANG_KRITIS_MAX = 76

DAFTAR_PROVIDER: dict[str, dict[str, Any]] = {
    "groq": {
        "label": "⚡ Groq Vision (Gratis & Super Cepat)",
        "default_model": MODEL_GROQ_UTAMA,
        "fallback_model": MODEL_GROQ_FALLBACK,
        "butuh_api_key": True,
        "env_var": "GROQ_API_KEY",
        "link_key": "https://console.groq.com/keys",
        "pilihan_model": [
            MODEL_GROQ_UTAMA,
        ],
    },
    "openrouter": {
        "label": "🌐 OpenRouter (Multi-Model Gratis/Murah)",
        "default_model": MODEL_OPENROUTER_UTAMA,
        "fallback_model": MODEL_OPENROUTER_FALLBACK,
        "butuh_api_key": True,
        "env_var": "OPENROUTER_API_KEY",
        "link_key": "https://openrouter.ai/keys",
        "pilihan_model": [
            "openrouter/free",
            "google/gemma-4-31b-it:free",
            "nvidia/nemotron-3.5-super-vl:free",
            "google/gemini-2.5-flash",
            "qwen/qwen2.5-vl-72b-instruct",
        ],
    },
    "ollama": {
        "label": "💻 Ollama Lokal (100% Offline & Unlimited)",
        "default_model": MODEL_OLLAMA_DEFAULT,
        "fallback_model": None,
        "butuh_api_key": False,
        "env_var": "OLLAMA_BASE_URL",
        "link_key": "https://ollama.com/download",
        "pilihan_model": [
            "qwen2.5vl:7b",
            "gemma3:4b",
            "gemma3:12b",
            "llama3.2-vision",
            "minicpm-v",
        ],
    },
    "gemini": {
        "label": "✨ Google Gemini API",
        "default_model": MODEL_UTAMA_FREE,
        "fallback_model": MODEL_FALLBACK_FREE,
        "butuh_api_key": True,
        "env_var": "GEMINI_API_KEY",
        "link_key": "https://aistudio.google.com/apikey",
        "pilihan_model": [
            MODEL_UTAMA_FREE,
            MODEL_FALLBACK_FREE,
        ],
    },
}


class DetailNilaiSoal(BaseModel):
    """Rincian hasil koreksi untuk satu nomor soal dalam lembar jawaban."""

    nomor_soal: int = Field(..., ge=1, description="Nomor urut soal (1, 2, 3, ...).")
    transkripsi_latex: str = Field(
        ...,
        description=(
            "Transkripsi jawaban tulisan tangan siswa khusus untuk nomor soal ini "
            'dalam format Markdown & LaTeX. Tulis "[tidak dijawab]" jika kosong.'
        ),
    )
    analisis_langkah: str = Field(
        ...,
        description="Evaluasi singkat ketepatan konsep, rumus, langkah perhitungan, dan satuan untuk nomor ini.",
    )
    skor_diperoleh: int = Field(
        ...,
        ge=0,
        description="Skor yang diperoleh siswa untuk nomor soal ini (0 sampai skor_maksimal).",
    )
    skor_maksimal: int = Field(
        ...,
        ge=1,
        description="Bobot skor maksimal untuk nomor soal ini sesuai rubrik guru.",
    )


class HasilKoreksiSiswa(BaseModel):
    """Skema output terstruktur untuk hasil koreksi satu lembar jawaban siswa."""

    nama_siswa: str = Field(
        ...,
        description=(
            'Nama atau NIS siswa yang terbaca di lembar kertas; '
            'isi "Tanpa Nama" jika tidak tertulis atau tidak terbaca.'
        ),
    )
    transkripsi_jawaban_latex: str = Field(
        ...,
        description=(
            "Transkripsi lengkap tulisan tangan dan langkah perhitungan siswa "
            "apa adanya menggunakan format Markdown & LaTeX."
        ),
    )
    analisis_langkah: str = Field(
        ...,
        description=(
            "Evaluasi objektif mengenai ketepatan konsep, pemilihan rumus, "
            "substitusi angka, proses perhitungan, dan satuan."
        ),
    )
    skor_konsep: int = Field(
        ...,
        ge=0,
        le=40,
        description="Skor pemahaman konsep dan ketepatan rumus keseluruhan (0 sampai 40).",
    )
    skor_langkah_perhitungan: int = Field(
        ...,
        ge=0,
        le=40,
        description="Skor ketepatan substitusi angka dan langkah perhitungan keseluruhan (0 sampai 40).",
    )
    skor_hasil_dan_satuan: int = Field(
        ...,
        ge=0,
        le=20,
        description="Skor ketepatan hasil akhir dan penulisan satuan keseluruhan (0 sampai 20).",
    )
    total_nilai: int = Field(
        ...,
        ge=0,
        le=100,
        description=(
            "Nilai akhir skala 0 sampai 100. Untuk 1 soal, sama dengan "
            "skor_konsep + skor_langkah_perhitungan + skor_hasil_dan_satuan. "
            "Untuk multi-soal, selaras dengan total skor di rincian_per_soal (skala 0-100)."
        ),
    )
    umpan_balik_siswa: str = Field(
        ...,
        description=(
            "Saran perbaikan yang ramah, memotivasi, dan spesifik "
            "dalam bahasa Indonesia untuk siswa."
        ),
    )
    perlu_validasi_guru: bool = Field(
        ...,
        description=(
            "Set True jika tulisan buram/sulit dibaca, terdapat banyak coretan, "
            "jawaban memakai cara alternatif yang valid tapi berbeda dari modul, "
            "atau total_nilai berada di area kritis 68-76."
        ),
    )
    alasan_validasi: str = Field(
        ...,
        description=(
            'Penjelasan singkat mengapa perlu ditinjau guru, atau "-" '
            "jika perlu_validasi_guru bernilai False."
        ),
    )
    rincian_per_soal: list[DetailNilaiSoal] = Field(
        default_factory=list,
        description=(
            "Daftar rincian penilaian untuk setiap nomor soal sesuai daftar soal yang diberikan."
        ),
    )


SYSTEM_INSTRUCTION_GURU = """\
Anda adalah SIDIK-AI, asisten guru dan asesor profesional mata pelajaran eksakta \
(Sains, Matematika, Fisika, Kimia, dan Teknologi) yang sangat teliti, objektif, dan adil.

ATURAN KERJA WAJIB:
1. HARGAI PROSES & LANGKAH PENGERJAAN:
   - Nilai secara adil setiap tahapan berpikir siswa: pemahaman konsep & rumus (0-40), \
langkah substitusi & perhitungan matematis (0-40), serta hasil akhir & satuan (0-20).
   - Berikan skor parsial secara proporsional jika konsep dan langkah awal siswa benar \
meskipun terdapat kesalahan hitung kecil di akhir.
   - Jangan memberikan skor penuh untuk jawaban yang hanya menuliskan hasil akhir tanpa \
langkah pengerjaan yang diminta rubrik.

2. BERPATOKAN KETAT PADA MODUL RAG & RUBRIK GURU:
   - Jadikan konteks modul ajar (RAG) dan rubrik penilaian guru sebagai acuan utama \
(definisi, rumus, konstanta, pembobotan, dan satuan).
   - Jika terdapat beberapa nomor soal, nilai setiap nomor soal secara terpisah di `rincian_per_soal` \
sesuai bobot masing-masing. Jika suatu nomor tidak dijawab siswa di kertas, beri `skor_diperoleh = 0` \
dan tulis `[tidak dijawab]`.
   - Jika siswa menggunakan metode alternatif yang valid secara ilmiah/matematis namun \
berbeda dari cara di modul, tetap nilai secara adil dan tandai `perlu_validasi_guru = true`.

3. TRANSKRIPSI JUJUR (ANTI-HALUSINASI):
   - Transkripsikan seluruh tulisan tangan siswa secara akurat dalam format Markdown dan LaTeX \
(gunakan `$...$` untuk rumus inline dan `$$...$$` untuk rumus blok).
   - Salin apa yang benar-benar ditulis siswa, termasuk kekeliruan angka/tanda jika ada \
(jangan diam-diam membenarkan kesalahan siswa di bagian transkripsi).
   - Jika ada bagian yang buram, terpotong, atau tidak terbaca, tulis `[tidak terbaca]` \
dan set `perlu_validasi_guru = true`.

4. ATURAN VALIDASI GURU & KONSISTENSI NILAI:
   - Pastikan `skor_konsep + skor_langkah_perhitungan + skor_hasil_dan_satuan` konsisten dengan `total_nilai` (0-100).
   - Wajib set `perlu_validasi_guru = true` jika:
     a) tulisan buram atau sulit dibaca,
     b) terdapat banyak coretan atau revisi yang meragukan,
     c) siswa memakai cara alternatif valid yang berbeda dari modul, atau
     d) `total_nilai` berada di rentang kritis 68 sampai 76.
   - Jika `perlu_validasi_guru = false`, isi `alasan_validasi` dengan `"-"`.

5. UMPAN BALIK PEDAGOGIS:
   - Tulis `umpan_balik_siswa` dalam bahasa Indonesia yang sopan, ramah, memotivasi, \
mengapresiasi langkah yang sudah benar, dan menjelaskan perbaikan spesifik secara jelas.
"""

SYSTEM_INSTRUCTION_RINGKAS = """\
Anda SIDIK-AI, guru eksakta teliti & objektif.
Aturan wajib:
1. Nilai proses adil: skor_konsep (0-40), skor_langkah_perhitungan (0-40), skor_hasil_dan_satuan (0-20), total_nilai (0-100). Beri skor parsial bila langkah benar meski hasil salah; jangan beri nilai penuh tanpa langkah.
2. Patuhi konteks modul RAG & rubrik guru. Jika multi-soal, isi `rincian_per_soal` untuk setiap nomor (tulis `[tidak dijawab]` & skor 0 bila kosong).
3. Transkripsikan tulisan tangan siswa apa adanya dalam Markdown & LaTeX (`$...$`, `$$...$$`, escape backslash `\\\\` di JSON). Tulis `[tidak terbaca]` jika buram.
4. Set `perlu_validasi_guru=true` jika buram, banyak coretan, cara alternatif valid, atau total_nilai 68-76; jika false isi `alasan_validasi="-"`.
5. Tulis `umpan_balik_siswa` ramah, memotivasi, spesifik (Bahasa Indonesia).
Kembalikan HANYA JSON valid sesuai skema tanpa teks lain."""

CONTOH_SKEMA_JSON_STRICT = """\
{"nama_siswa":"str/Tanpa Nama","transkripsi_jawaban_latex":"str LaTeX","analisis_langkah":"str","skor_konsep":0,"skor_langkah_perhitungan":0,"skor_hasil_dan_satuan":0,"total_nilai":0,"umpan_balik_siswa":"str","perlu_validasi_guru":false,"alasan_validasi":"-","rincian_per_soal":[{"nomor_soal":1,"transkripsi_latex":"str","analisis_langkah":"str","skor_diperoleh":0,"skor_maksimal":100}]}"""


def deteksi_model_ollama(base_url: str = OLLAMA_DEFAULT_BASE_URL) -> list[str]:
    """Mengecek server Ollama lokal dan mengembalikan daftar model yang sudah terpasang."""
    url = f"{(base_url or OLLAMA_DEFAULT_BASE_URL).rstrip('/')}/api/tags"
    try:
        resp = httpx.get(url, timeout=2.0)
        resp.raise_for_status()
        data = resp.json()
        models = [
            str(m.get("name", "")).strip()
            for m in (data.get("models") or [])
            if str(m.get("name", "")).strip()
        ]
        return models
    except Exception:
        return []


def deteksi_model_groq(api_key: str) -> list[str]:
    """Mengecek daftar model yang aktif untuk API Key Groq Anda melalui /openai/v1/models."""
    if not api_key or not api_key.strip():
        return []
    try:
        resp = httpx.get(
            GROQ_MODELS_URL,
            headers={"Authorization": f"Bearer {api_key.strip()}"},
            timeout=5.0,
        )
        resp.raise_for_status()
        data = resp.json()
        daftar = sorted(
            str(m.get("id", "")).strip()
            for m in (data.get("data") or [])
            if str(m.get("id", "")).strip()
            and not any(
                skip in str(m.get("id", "")).lower()
                for skip in ("whisper", "tts", "guard", "orpheus")
            )
        )
        # Prioritaskan model vision utama di urutan teratas jika tersedia
        if MODEL_GROQ_UTAMA in daftar:
            daftar.remove(MODEL_GROQ_UTAMA)
            daftar.insert(0, MODEL_GROQ_UTAMA)
        return daftar
    except Exception:
        return []


def _format_daftar_soal_teks(
    soal: str,
    rubrik_guru: str,
    daftar_soal: list[dict[str, Any]] | None = None,
) -> tuple[str, str, list[dict[str, Any]]]:
    """Menormalisasi input soal tunggal atau multi-soal menjadi teks soal, rubrik, dan daftar terstruktur."""
    if daftar_soal:
        daftar_bersih: list[dict[str, Any]] = []
        bagian_soal: list[str] = []
        bagian_rubrik: list[str] = []
        for idx, item in enumerate(daftar_soal, start=1):
            pertanyaan = str(item.get("pertanyaan", "")).strip()
            if not pertanyaan:
                continue
            rubrik = str(item.get("rubrik", "")).strip() or "Gunakan standar penilaian eksakta berdasarkan modul ajar."
            bobot = max(1, int(item.get("bobot", 100)))
            nomor = int(item.get("nomor", idx))
            daftar_bersih.append(
                {
                    "nomor": nomor,
                    "pertanyaan": pertanyaan,
                    "rubrik": rubrik,
                    "bobot": bobot,
                }
            )
            bagian_soal.append(f"**Soal No. {nomor} (Bobot maksimal: {bobot} poin):**\n{pertanyaan}")
            bagian_rubrik.append(f"**Rubrik Soal No. {nomor} (Maksimal {bobot} poin):**\n{rubrik}")
        if daftar_bersih:
            return "\n\n".join(bagian_soal), "\n\n".join(bagian_rubrik), daftar_bersih

    soal_bersih = (soal or "").strip()
    rubrik_bersih = (rubrik_guru or "").strip() or "Gunakan standar penilaian eksakta berdasarkan modul ajar."
    daftar_tunggal = [
        {
            "nomor": 1,
            "pertanyaan": soal_bersih,
            "rubrik": rubrik_bersih,
            "bobot": 100,
        }
    ]
    return soal_bersih, rubrik_bersih, daftar_tunggal


def buat_hash_cache(
    image_obj: Image.Image,
    soal: str,
    rubrik_guru: str,
    nama_model: str,
    thinking_level: str = THINKING_LEVEL_TELITI,
    jpeg_bytes: bytes | None = None,
    provider: str = "gemini",
) -> str:
    """Menghasilkan hash SHA-256 deterministik dari gambar JPEG, soal, rubrik, provider, dan model."""
    data_gambar = jpeg_bytes if jpeg_bytes is not None else gambar_ke_jpeg_bytes(image_obj)
    hasher = hashlib.sha256()
    hasher.update(data_gambar)
    hasher.update(b"\x00SOAL:")
    hasher.update((soal or "").strip().encode("utf-8"))
    hasher.update(b"\x00RUBRIK:")
    hasher.update((rubrik_guru or "").strip().encode("utf-8"))
    hasher.update(b"\x00PROVIDER:")
    hasher.update((provider or "gemini").strip().lower().encode("utf-8"))
    hasher.update(b"\x00MODEL:")
    hasher.update((nama_model or "").strip().encode("utf-8"))
    hasher.update(b"\x00THINKING:")
    hasher.update((thinking_level or "").strip().lower().encode("utf-8"))
    return hasher.hexdigest()


def _muat_dari_cache(cache_hash: str) -> dict[str, Any] | None:
    """Membaca hasil koreksi dari file cache JSON jika tersedia dan valid."""
    cache_path = Path(CACHE_DIR) / f"{cache_hash}.json"
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("status") != "gagal":
            data["dari_cache"] = True
            return data
    except (OSError, json.JSONDecodeError):
        return None
    return None


def _simpan_ke_cache(cache_hash: str, hasil: dict[str, Any]) -> None:
    """Menyimpan hasil koreksi yang berhasil ke `./data/cache/[hash].json`."""
    cache_folder = Path(CACHE_DIR)
    cache_folder.mkdir(parents=True, exist_ok=True)
    cache_path = cache_folder / f"{cache_hash}.json"
    payload = dict(hasil)
    payload["dari_cache"] = False
    cache_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _kode_http_error(exc: Exception) -> int | None:
    """Mengekstrak kode HTTP dari google.genai.errors.APIError maupun httpx.HTTPStatusError."""
    if isinstance(exc, errors.APIError):
        return getattr(exc, "code", None)
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        return exc.response.status_code
    return None


def _adalah_error_billing_habis(exc: Exception) -> bool:
    """Mendeteksi HTTP 402 (saldo kredit prepay / billing habis) agar tidak keliru dianggap 429."""
    if _kode_http_error(exc) == 402:
        return True
    pesan = str(exc).lower()
    return any(
        kata in pesan
        for kata in (
            "402",
            "prepayment credits are depleted",
            "insufficient_quota",
            "insufficient credits",
            "payment required",
        )
    )


def _adalah_error_rate_limit(exc: Exception) -> bool:
    """Mendeteksi HTTP 429 / rate limit (mengecualikan 402 saldo billing habis)."""
    if _adalah_error_billing_habis(exc):
        return False
    if _kode_http_error(exc) == 429:
        return True
    pesan = str(exc).lower()
    return any(
        kata in pesan
        for kata in ("429", "rate limit", "too many requests", "requests per minute", "resource_exhausted")
    )


def _adalah_error_server_sibuk(exc: Exception) -> bool:
    """Mendeteksi error sementara server (HTTP 503 UNAVAILABLE / high demand / 500 / 502 / 504)."""
    if _kode_http_error(exc) in (500, 502, 503, 504):
        return True
    pesan = str(exc).lower()
    return any(
        kata in pesan
        for kata in (
            "503",
            "unavailable",
            "high demand",
            "overloaded",
            "504",
            "502",
            "deadline_exceeded",
            "temporarily unavailable",
        )
    )


def _adalah_error_bisa_fallback(exc: Exception) -> bool:
    """Mengembalikan True jika error layak memicu auto-fallback (429 atau 503, BUKAN 402)."""
    if _adalah_error_billing_habis(exc):
        return False
    return _adalah_error_rate_limit(exc) or _adalah_error_server_sibuk(exc)


def _ekstrak_waktu_tunggu_429(exc: Exception) -> float | None:
    """Membaca durasi tunggu (detik) dari header Retry-After atau pesan error Groq ('try again in Xs')."""
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        retry_after = exc.response.headers.get("retry-after")
        if retry_after:
            try:
                detik_hdr = float(retry_after)
                if detik_hdr > 0:
                    return detik_hdr
            except ValueError:
                pass
        sumber_teks = exc.response.text or str(exc)
    else:
        sumber_teks = str(exc)

    # Cocokkan format seperti "Please try again in 26.305714285s" atau "try again in 450ms" atau "1m5.2s"
    cocok_ms = re.search(r"try again in\s+(\d+(?:\.\d+)?)\s*ms", sumber_teks, flags=re.IGNORECASE)
    if cocok_ms:
        return max(0.5, float(cocok_ms.group(1)) / 1000.0)

    cocok_menit_detik = re.search(
        r"try again in\s+(?:(\d+)m)?\s*(\d+(?:\.\d+)?)s",
        sumber_teks,
        flags=re.IGNORECASE,
    )
    if cocok_menit_detik:
        menit = int(cocok_menit_detik.group(1) or 0)
        detik = float(cocok_menit_detik.group(2))
        return menit * 60.0 + detik

    return None


def _ringkas_konteks_rag(konteks: str, maks_karakter: int = 900) -> str:
    """Memangkas konteks RAG secara rapi agar hemat input token pada provider berkuota ITPM ketat."""
    teks = (konteks or "").strip()
    if len(teks) <= maks_karakter:
        return teks
    potong = teks[:maks_karakter].rsplit(" ", 1)[0].strip()
    return f"{potong}..."


def _bangun_prompt_koreksi(
    soal_teks: str,
    rubrik_teks: str,
    konteks_modul: str,
    daftar_soal: list[dict[str, Any]],
    sertakan_contoh_json: bool = False,
    mode_ringkas: bool = False,
) -> str:
    """Menyusun prompt terstruktur bahasa Indonesia untuk evaluasi lembar jawaban."""
    jumlah_soal = len(daftar_soal)
    total_bobot = sum(item["bobot"] for item in daftar_soal)

    if mode_ringkas:
        konteks_pakai = _ringkas_konteks_rag(konteks_modul, maks_karakter=850)
        info_multi = (
            f"Nilai {jumlah_soal} soal (total bobot {total_bobot}), isi `rincian_per_soal` lengkap."
            if jumlah_soal > 1
            else "Isi skor_konsep (0-40), skor_langkah_perhitungan (0-40), skor_hasil_dan_satuan (0-20), total_nilai (0-100), dan 1 item `rincian_per_soal`."
        )
        return (
            f"SOAL:\n{soal_teks.strip()}\n\n"
            f"RUBRIK:\n{rubrik_teks.strip()}\n\n"
            f"MODUL RAG:\n{konteks_pakai}\n\n"
            f"TUGAS: Koreksi foto jawaban siswa ini. {info_multi}\n"
            f"FORMAT JSON WAJIB:\n{CONTOH_SKEMA_JSON_STRICT}"
        )

    if jumlah_soal > 1:
        instruksi_multi = (
            f"Lembar jawaban ini dinilai terhadap **{jumlah_soal} butir soal** "
            f"(total bobot rubrik: {total_bobot} poin).\n"
            "- Wajib isi array `rincian_per_soal` tepat sebanyak semua nomor soal di atas.\n"
            "- Untuk setiap nomor soal, isi `nomor_soal`, `transkripsi_latex`, `analisis_langkah`, "
            "`skor_diperoleh` (0 s.d. bobot soal tersebut), dan `skor_maksimal` (sama dengan bobot soal).\n"
            "- Gabungkan ringkasan transkripsi seluruh nomor secara terurut pada `transkripsi_jawaban_latex`.\n"
            "- Hitung `total_nilai` (skala 0-100) yang selaras dengan perolehan skor seluruh nomor soal, "
            "dan distribusikan secara proporsional ke `skor_konsep` (0-40), `skor_langkah_perhitungan` (0-40), "
            "serta `skor_hasil_dan_satuan` (0-20).\n"
        )
    else:
        instruksi_multi = (
            "- Berikan skor terpisah: `skor_konsep` (0-40), `skor_langkah_perhitungan` (0-40), "
            "`skor_hasil_dan_satuan` (0-20), dan jumlahkan tepat ke `total_nilai` (0-100).\n"
            "- Isi juga 1 item pada `rincian_per_soal` untuk nomor soal 1 dengan `skor_maksimal = 100`.\n"
        )

    bagian_json = ""
    if sertakan_contoh_json:
        bagian_json = (
            "\n\n### FORMAT JSON WAJIB (KEMBALIKAN HANYA OBJEK JSON VALID TANPA TEKS TAMBAHAN)\n"
            "Pastikan setiap backslash LaTeX di dalam string JSON ditulis ganda (`\\\\frac`, `\\\\cdot`, `\\\\text`).\n"
            f"```json\n{CONTOH_SKEMA_JSON_STRICT}\n```"
        )

    return (
        "Lakukan digitalisasi dan koreksi terhadap foto lembar jawaban tulisan tangan siswa "
        "yang dilampirkan berdasarkan informasi resmi berikut.\n\n"
        f"### DAFTAR SOAL UJIAN\n{soal_teks.strip()}\n\n"
        f"### RUBRIK PENILAIAN GURU\n{rubrik_teks.strip()}\n\n"
        f"### KONTEKS REFERENSI MODUL AJAR (HASIL RAG)\n{konteks_modul.strip()}\n\n"
        "### INSTRUKSI KELUARAN\n"
        "1. Baca nama/NIS siswa jika tertulis di lembar kertas (jika tidak ada, tulis \"Tanpa Nama\").\n"
        "2. Transkripsikan seluruh jawaban dan langkah perhitungan siswa dengan Markdown & LaTeX.\n"
        "3. Evaluasi setiap langkah secara objektif terhadap konteks modul ajar dan rubrik guru.\n"
        f"{instruksi_multi}"
        "4. Evaluasi kriteria `perlu_validasi_guru` (buram, banyak coretan, metode alternatif, "
        "atau total_nilai pada rentang 68-76) dan isi `alasan_validasi` secara singkat.\n"
        "5. Kembalikan hasil HANYA dalam format JSON sesuai skema `HasilKoreksiSiswa`."
        f"{bagian_json}"
    )


def _ke_int_aman(nilai: Any, default: int = 0) -> int:
    """Mengonversi nilai angka (int/float/string angka) menjadi integer secara aman."""
    if isinstance(nilai, bool):
        return default
    if isinstance(nilai, (int, float)):
        return round(nilai)
    try:
        teks = str(nilai).strip().replace(",", ".")
        cocok = re.search(r"-?\d+(?:\.\d+)?", teks)
        return round(float(cocok.group(0))) if cocok else default
    except Exception:
        return default


def _ke_bool_aman(nilai: Any) -> bool:
    """Mengonversi boolean atau string boolean ('true'/'ya') menjadi bool."""
    if isinstance(nilai, bool):
        return nilai
    return str(nilai).strip().lower() in ("true", "1", "yes", "ya")


def _parse_json_toleran_latex(teks_mentah: str) -> HasilKoreksiSiswa:
    """Mem-parsing keluaran JSON dari LLM open-source/API secara tangguh terhadap <think> & backslash LaTeX."""
    teks = (teks_mentah or "").strip()
    if not teks:
        raise ValueError("Model AI mengembalikan respons kosong.")

    # Hapus blok <think>...</think> dari model reasoning (seperti Qwen 3.8 / DeepSeek / Nemotron)
    teks = re.sub(r"<think>.*?</think>", "", teks, flags=re.DOTALL | re.IGNORECASE).strip()

    # Hilangkan pembungkus ```json ... ``` jika ada
    cocok_blok = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", teks, flags=re.DOTALL | re.IGNORECASE)
    if cocok_blok:
        kandidat = cocok_blok.group(1).strip()
    else:
        awal = teks.find("{")
        akhir = teks.rfind("}")
        if awal != -1 and akhir != -1 and akhir > awal:
            kandidat = teks[awal : akhir + 1]
        else:
            kandidat = teks

    # Coba parse standar; jika gagal akibat backslash LaTeX (\cdot, \sqrt, dll.), perbaiki escape-nya
    try:
        data_dict = json.loads(kandidat)
    except json.JSONDecodeError:
        kandidat_diperbaiki = re.sub(r'(?<!\\)\\(?!["\\/bfnrtu])', r"\\\\", kandidat)
        data_dict = json.loads(kandidat_diperbaiki)

    if not isinstance(data_dict, dict):
        raise ValueError("Respons JSON dari model bukan berupa objek JSON.")

    # Koersi tipe ringan agar tidak gagal validasi karena float (35.0) atau field kosong
    rincian_raw = data_dict.get("rincian_per_soal")
    rincian_bersih: list[dict[str, Any]] = []
    if isinstance(rincian_raw, list):
        for idx, item in enumerate(rincian_raw, start=1):
            if not isinstance(item, dict):
                continue
            rincian_bersih.append(
                {
                    "nomor_soal": max(1, _ke_int_aman(item.get("nomor_soal"), idx)),
                    "transkripsi_latex": str(item.get("transkripsi_latex") or "[tidak dijawab]"),
                    "analisis_langkah": str(item.get("analisis_langkah") or "-"),
                    "skor_diperoleh": max(0, _ke_int_aman(item.get("skor_diperoleh"), 0)),
                    "skor_maksimal": max(1, _ke_int_aman(item.get("skor_maksimal"), 100)),
                }
            )

    skor_konsep = max(0, min(40, _ke_int_aman(data_dict.get("skor_konsep"), 0)))
    skor_langkah = max(0, min(40, _ke_int_aman(data_dict.get("skor_langkah_perhitungan"), 0)))
    skor_hasil = max(0, min(20, _ke_int_aman(data_dict.get("skor_hasil_dan_satuan"), 0)))
    total_nilai = max(
        0,
        min(100, _ke_int_aman(data_dict.get("total_nilai"), skor_konsep + skor_langkah + skor_hasil)),
    )

    tervalidasi = {
        "nama_siswa": str(data_dict.get("nama_siswa") or "Tanpa Nama"),
        "transkripsi_jawaban_latex": str(data_dict.get("transkripsi_jawaban_latex") or ""),
        "analisis_langkah": str(data_dict.get("analisis_langkah") or "-"),
        "skor_konsep": skor_konsep,
        "skor_langkah_perhitungan": skor_langkah,
        "skor_hasil_dan_satuan": skor_hasil,
        "total_nilai": total_nilai,
        "umpan_balik_siswa": str(data_dict.get("umpan_balik_siswa") or "-"),
        "perlu_validasi_guru": _ke_bool_aman(data_dict.get("perlu_validasi_guru")),
        "alasan_validasi": str(data_dict.get("alasan_validasi") or "-"),
        "rincian_per_soal": rincian_bersih,
    }
    return HasilKoreksiSiswa.model_validate(tervalidasi)


def _distribusikan_skor_komponen(
    total_nilai: int,
    konsep_awal: int,
    langkah_awal: int,
    hasil_awal: int,
) -> tuple[int, int, int]:
    """Menjaga agar jumlah (konsep + langkah + hasil) konsisten tepat dengan total_nilai (0-100)."""
    k = max(0, min(40, konsep_awal))
    l = max(0, min(40, langkah_awal))
    h = max(0, min(20, hasil_awal))
    if k + l + h == total_nilai:
        return k, l, h

    k_baru = min(40, round(total_nilai * 0.4))
    l_baru = min(40, round(total_nilai * 0.4))
    h_baru = max(0, min(20, total_nilai - k_baru - l_baru))
    selisih = total_nilai - (k_baru + l_baru + h_baru)
    if selisih != 0:
        if 0 <= k_baru + selisih <= 40:
            k_baru += selisih
        elif 0 <= l_baru + selisih <= 40:
            l_baru += selisih
    return k_baru, l_baru, h_baru


def _normalisasi_hasil_model(
    hasil_obj: HasilKoreksiSiswa,
    daftar_soal: list[dict[str, Any]],
) -> dict[str, Any]:
    """Menjamin konsistensi penjumlahan nilai (1 soal maupun multi-soal) dan aturan area kritis 68-76."""
    data = hasil_obj.model_dump()

    if not data["nama_siswa"] or not data["nama_siswa"].strip():
        data["nama_siswa"] = "Tanpa Nama"
    else:
        data["nama_siswa"] = data["nama_siswa"].strip()

    skor_konsep = max(0, min(40, int(data["skor_konsep"])))
    skor_langkah = max(0, min(40, int(data["skor_langkah_perhitungan"])))
    skor_hasil = max(0, min(20, int(data["skor_hasil_dan_satuan"])))

    rincian_mentah = data.get("rincian_per_soal") or []
    rincian_terpetakan = {int(item["nomor_soal"]): item for item in rincian_mentah}

    if len(daftar_soal) > 1:
        rincian_bersih: list[dict[str, Any]] = []
        total_mentah = 0
        total_bobot = 0
        for item_soal in daftar_soal:
            nomor = int(item_soal["nomor"])
            bobot = max(1, int(item_soal["bobot"]))
            total_bobot += bobot
            cocok = rincian_terpetakan.get(nomor)
            if cocok is not None:
                skor_item = max(0, min(bobot, int(cocok.get("skor_diperoleh", 0))))
                rincian_bersih.append(
                    {
                        "nomor_soal": nomor,
                        "transkripsi_latex": str(cocok.get("transkripsi_latex") or "[tidak dijawab]").strip(),
                        "analisis_langkah": str(cocok.get("analisis_langkah") or "-").strip(),
                        "skor_diperoleh": skor_item,
                        "skor_maksimal": bobot,
                    }
                )
                total_mentah += skor_item
            else:
                rincian_bersih.append(
                    {
                        "nomor_soal": nomor,
                        "transkripsi_latex": "[tidak terdeteksi di jawaban]",
                        "analisis_langkah": "Jawaban untuk nomor soal ini tidak ditemukan pada lembar.",
                        "skor_diperoleh": 0,
                        "skor_maksimal": bobot,
                    }
                )

        total_nilai = (
            max(0, min(100, round((total_mentah / total_bobot) * 100)))
            if total_bobot > 0
            else 0
        )
        skor_konsep, skor_langkah, skor_hasil = _distribusikan_skor_komponen(
            total_nilai, skor_konsep, skor_langkah, skor_hasil
        )
        data["rincian_per_soal"] = rincian_bersih
        data["total_skor_mentah"] = total_mentah
        data["total_bobot"] = total_bobot

        if not (data.get("transkripsi_jawaban_latex") or "").strip():
            data["transkripsi_jawaban_latex"] = "\n\n".join(
                f"**Soal No. {r['nomor_soal']}**\n{r['transkripsi_latex']}"
                for r in rincian_bersih
            )
    else:
        total_nilai = skor_konsep + skor_langkah + skor_hasil
        bobot_tunggal = int(daftar_soal[0]["bobot"]) if daftar_soal else 100
        data["total_skor_mentah"] = total_nilai
        data["total_bobot"] = bobot_tunggal
        if not rincian_mentah:
            data["rincian_per_soal"] = [
                {
                    "nomor_soal": 1,
                    "transkripsi_latex": data.get("transkripsi_jawaban_latex", ""),
                    "analisis_langkah": data.get("analisis_langkah", ""),
                    "skor_diperoleh": total_nilai,
                    "skor_maksimal": 100,
                }
            ]
        else:
            item_1 = dict(rincian_mentah[0])
            item_1["nomor_soal"] = 1
            item_1["skor_diperoleh"] = total_nilai
            item_1["skor_maksimal"] = 100
            data["rincian_per_soal"] = [item_1]

    data["skor_konsep"] = skor_konsep
    data["skor_langkah_perhitungan"] = skor_langkah
    data["skor_hasil_dan_satuan"] = skor_hasil
    data["total_nilai"] = total_nilai

    alasan = (data.get("alasan_validasi") or "").strip()
    if RENTANG_KRITIS_MIN <= total_nilai <= RENTANG_KRITIS_MAX:
        data["perlu_validasi_guru"] = True
        catatan_kritis = f"Total nilai ({total_nilai}) berada di area kritis 68-76."
        if not alasan or alasan == "-":
            alasan = catatan_kritis
        elif "68" not in alasan and "kritis" not in alasan.lower():
            alasan = f"{alasan} {catatan_kritis}"

    if not data["perlu_validasi_guru"]:
        data["alasan_validasi"] = "-"
    else:
        data["alasan_validasi"] = alasan if alasan and alasan != "-" else "Memerlukan peninjauan guru."

    return data


def _ekstrak_hasil_terstruktur(response: Any) -> HasilKoreksiSiswa:
    """Mengekstrak dan memvalidasi respons Gemini ke objek HasilKoreksiSiswa."""
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, HasilKoreksiSiswa):
        return parsed
    if isinstance(parsed, dict):
        return HasilKoreksiSiswa.model_validate(parsed)

    teks = (getattr(response, "text", None) or "").strip()
    return _parse_json_toleran_latex(teks)


def _buat_respons_error(
    pesan_error: str,
    model_target: str,
    provider: str = "gemini",
) -> dict[str, Any]:
    """Menyusun dictionary error yang informatif dan aman dikonsumsi UI."""
    return {
        "status": "gagal",
        "error": pesan_error,
        "dari_cache": False,
        "model_digunakan": model_target,
        "provider_digunakan": provider,
    }


def _panggil_gemini(
    client: genai.Client,
    nama_model: str,
    prompt_user: str,
    jpeg_bytes: bytes,
    thinking_level: str | None,
) -> HasilKoreksiSiswa:
    """Menjalankan panggilan multimodal Gemini SDK dengan payload JPEG ringan & skema Pydantic."""
    config_kwargs: dict[str, Any] = {
        "system_instruction": SYSTEM_INSTRUCTION_GURU,
        "temperature": 0.1,
        "response_mime_type": "application/json",
        "response_schema": HasilKoreksiSiswa,
    }
    if thinking_level:
        config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=thinking_level)

    config = types.GenerateContentConfig(**config_kwargs)
    part_gambar = types.Part.from_bytes(data=jpeg_bytes, mime_type="image/jpeg")

    response = client.models.generate_content(
        model=nama_model,
        contents=[prompt_user, part_gambar],
        config=config,
    )
    return _ekstrak_hasil_terstruktur(response)


def _panggil_fallback_gemini_aman(
    client: genai.Client,
    prompt_user: str,
    jpeg_bytes: bytes,
    thinking_level: str,
) -> HasilKoreksiSiswa:
    """Memanggil model fallback gemini-3.5-flash-lite dengan perlindungan 400 thinking & retry 503/429."""
    try:
        return _panggil_gemini(
            client=client,
            nama_model=MODEL_FALLBACK_FREE,
            prompt_user=prompt_user,
            jpeg_bytes=jpeg_bytes,
            thinking_level=thinking_level,
        )
    except Exception as exc_fb:
        if isinstance(exc_fb, errors.APIError) and getattr(exc_fb, "code", None) == 400:
            return _panggil_gemini(
                client=client,
                nama_model=MODEL_FALLBACK_FREE,
                prompt_user=prompt_user,
                jpeg_bytes=jpeg_bytes,
                thinking_level=None,
            )
        if _adalah_error_bisa_fallback(exc_fb):
            time.sleep(2.0)
            return _panggil_gemini(
                client=client,
                nama_model=MODEL_FALLBACK_FREE,
                prompt_user=prompt_user,
                jpeg_bytes=jpeg_bytes,
                thinking_level=thinking_level,
            )
        raise


def _panggil_openai_compatible(
    endpoint_url: str,
    nama_model: str,
    prompt_user: str,
    jpeg_bytes: bytes,
    api_key: str = "",
    extra_headers: dict[str, str] | None = None,
    http_client: httpx.Client | None = None,
    timeout_detik: float = 90.0,
    pakai_json_mode: bool = True,
    system_instruction: str = SYSTEM_INSTRUCTION_GURU,
) -> HasilKoreksiSiswa:
    """Memanggil endpoint multimodal OpenAI-compatible (Groq, OpenRouter, Ollama)."""
    img_b64 = base64.b64encode(jpeg_bytes).decode("ascii")
    data_uri = f"data:image/jpeg;base64,{img_b64}"

    headers = {"Content-Type": "application/json"}
    if api_key and api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"
    if extra_headers:
        headers.update(extra_headers)

    payload: dict[str, Any] = {
        "model": nama_model,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": system_instruction},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_user},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            },
        ],
    }
    if pakai_json_mode:
        payload["response_format"] = {"type": "json_object"}

    def _kirim(body: dict[str, Any]) -> httpx.Response:
        if http_client is not None:
            return http_client.post(endpoint_url, headers=headers, json=body, timeout=timeout_detik)
        with httpx.Client(timeout=timeout_detik) as tmp_client:
            return tmp_client.post(endpoint_url, headers=headers, json=body)

    resp = _kirim(payload)

    # Beberapa model gratis / Ollama lama menolak parameter response_format=json_object (HTTP 400)
    if resp.status_code == 400 and pakai_json_mode:
        payload_tanpa_rf = dict(payload)
        payload_tanpa_rf.pop("response_format", None)
        resp = _kirim(payload_tanpa_rf)

    resp.raise_for_status()
    body_json = resp.json()

    choices = body_json.get("choices") or []
    if not choices:
        raise ValueError(f"Model '{nama_model}' tidak mengembalikan choices valid: {body_json}")

    pesan_ai = choices[0].get("message") or {}
    konten = pesan_ai.get("content", "")
    if isinstance(konten, list):
        konten = "\n".join(
            str(bagian.get("text", ""))
            for bagian in konten
            if isinstance(bagian, dict) and bagian.get("type") == "text"
        )

    return _parse_json_toleran_latex(str(konten))


def _format_error_informatif(
    exc: Exception,
    provider: str,
    model_terpakai: str,
    model_utama: str,
    fallback_digunakan: bool,
    mode_audit_neon: bool,
    base_url: str | None = None,
) -> str:
    """Menyusun pesan error bahasa Indonesia yang akurat untuk 402, 429, 503, 401/403, 404, dan Ollama."""
    kode = _kode_http_error(exc)
    detail_http = ""
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        detail_http = exc.response.text[:400]
    else:
        detail_http = str(exc)

    if isinstance(exc, httpx.ConnectError) and provider == "ollama":
        url_aktif = base_url or OLLAMA_DEFAULT_BASE_URL
        return (
            f"Tidak dapat terhubung ke server Ollama lokal di `{url_aktif}`. "
            "Pastikan aplikasi Ollama sudah berjalan (`ollama serve`) dan model vision sudah diunduh "
            f"(misalnya: `ollama pull {model_terpakai}`)."
        )

    if isinstance(exc, httpx.TimeoutException):
        tambahan_ollama = (
            " Jika memakai Ollama di laptop tanpa GPU diskrit, coba model lebih ringan seperti `gemma3:4b`."
            if provider == "ollama"
            else ""
        )
        return f"Permintaan ke `{provider}` ({model_terpakai}) melebihi batas waktu (timeout).{tambahan_ollama}"

    if _adalah_error_billing_habis(exc):
        if provider == "gemini":
            return (
                "Saldo kredit *prepay* Google AI Studio habis (HTTP 402). "
                "Solusi: (1) Ganti Provider di sidebar ke **Groq Vision** (gratis & cepat) / **OpenRouter** / **Ollama Lokal**, "
                "(2) buat API Key baru pada project Free Tier AI Studio tanpa billing prepay, "
                f"atau (3) isi ulang kredit di https://ai.studio/projects. Detail: {detail_http}"
            )
        return (
            f"Saldo/kredit akun pada provider `{provider}` habis (HTTP 402). "
            f"Silakan ganti provider gratis (mis. Groq / Ollama) atau cek billing akun Anda. Detail: {detail_http}"
        )

    if kode == 429 or _adalah_error_rate_limit(exc):
        if fallback_digunakan:
            return (
                f"Batas kuota/rate limit (429) tercapai pada model utama ({model_utama}) "
                f"maupun fallback ({model_terpakai}). Coba kurangi 'Jumlah Lembar Paralel', "
                f"naikkan jeda, atau pindah provider di sidebar. Detail: {detail_http}"
            )
        return (
            f"Batas kuota/rate limit (429) tercapai pada `{provider}` ({model_terpakai}). "
            f"Silakan tunggu sebentar atau pindah provider lain di sidebar. Detail: {detail_http}"
        )

    if kode == 503 or _adalah_error_server_sibuk(exc):
        return (
            f"Server `{provider}` sedang sangat padat sementara (HTTP {kode or 503}) pada `{model_terpakai}`. "
            f"Silakan coba lagi 1-2 menit lagi atau ganti provider di sidebar. Detail: {detail_http}"
        )

    if kode in (401, 403):
        tambahan = (
            " Pastikan akun Anda sudah mengaktifkan Paid Tier untuk model gemini-4-neon."
            if (provider == "gemini" and mode_audit_neon)
            else ""
        )
        return (
            f"Autentikasi/izin API `{provider}` ditolak (HTTP {kode}). "
            f"Periksa kembali API Key Anda di sidebar atau `.env`.{tambahan} Detail: {detail_http}"
        )

    if kode == 404:
        tambahan_ollama = (
            f" Jalankan `ollama pull {model_terpakai}` terlebih dahulu di terminal."
            if provider == "ollama"
            else ""
        )
        return (
            f"Model '{model_terpakai}' tidak ditemukan pada `{provider}` (HTTP 404).{tambahan_ollama} "
            f"Detail: {detail_http}"
        )

    return f"Terjadi kesalahan pada `{provider}` ({model_terpakai}): {detail_http}"


def koreksi_satu_lembar(
    image_obj: Image.Image,
    soal: str,
    rubrik_guru: str,
    api_key: str = "",
    mode_audit_neon: bool = False,
    abaikan_cache: bool = False,
    mode_kecepatan: str = "cepat",
    daftar_soal: list[dict[str, Any]] | None = None,
    konteks_modul: str | None = None,
    client: Any = None,
    provider: str = "gemini",
    model_override: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Mengoreksi satu lembar foto tulisan tangan siswa menggunakan Multimodal RAG & Multi-Provider AI.

    Args:
        image_obj: Objek `PIL.Image.Image` lembar jawaban siswa.
        soal: Teks pertanyaan/soal ujian eksakta (diabaikan jika `daftar_soal` diberikan).
        rubrik_guru: Rubrik penilaian guru (diabaikan jika `daftar_soal` diberikan).
        api_key: API Key sesuai provider (tidak wajib untuk `provider="ollama"`).
        mode_audit_neon: Jika True, memaksa audit mendalam menggunakan `gemini-4-neon` (Paid Tier).
        abaikan_cache: Jika True, lewati cache lokal dan paksa panggil ulang model AI.
        mode_kecepatan: `"cepat"` (`thinking_level="minimal"`) atau `"teliti"` (`thinking_level="low"`), khusus Gemini.
        daftar_soal: Opsional daftar soal terstruktur untuk koreksi multi-soal dalam satu lembar.
        konteks_modul: Opsional konteks RAG yang sudah diambil sekali di tingkat batch.
        client: Opsional instance client (`genai.Client` untuk Gemini atau `httpx.Client` untuk provider lain).
        provider: `"groq"`, `"openrouter"`, `"ollama"`, atau `"gemini"`.
        model_override: Opsional nama model kustom sesuai provider yang dipilih.
        base_url: Opsional URL server khusus Ollama (default `http://localhost:11434`).

    Returns:
        Dictionary hasil koreksi terstruktur sesuai `HasilKoreksiSiswa` dilengkapi metadata
        (`status`, `dari_cache`, `provider_digunakan`, `model_digunakan`, `fallback_digunakan`,
        `waktu_proses_detik`, `error`).
    """
    mulai = time.perf_counter()

    provider_aktif = "gemini" if mode_audit_neon else (provider or "gemini").strip().lower()
    if provider_aktif not in DAFTAR_PROVIDER:
        return _buat_respons_error(
            f"Provider '{provider_aktif}' tidak dikenali. Pilihan valid: {', '.join(DAFTAR_PROVIDER)}.",
            model_override or "-",
            provider_aktif,
        )

    info_provider = DAFTAR_PROVIDER[provider_aktif]

    if mode_audit_neon:
        model_utama = MODEL_AUDIT_NEON
        thinking_level = THINKING_LEVEL_NEON
    elif provider_aktif == "gemini":
        model_utama = (model_override or MODEL_UTAMA_FREE).strip()
        thinking_level = (
            THINKING_LEVEL_CEPAT
            if (mode_kecepatan or "").strip().lower() == "cepat"
            else THINKING_LEVEL_TELITI
        )
    else:
        model_utama = (model_override or str(info_provider["default_model"])).strip()
        thinking_level = "standard"

    if not isinstance(image_obj, Image.Image):
        return _buat_respons_error(
            "Input gambar tidak valid. Pastikan image_obj berupa objek PIL.Image.Image.",
            model_utama,
            provider_aktif,
        )

    if info_provider["butuh_api_key"] and (not api_key or not api_key.strip()):
        env_var = info_provider["env_var"]
        return _buat_respons_error(
            f"{env_var} kosong. Silakan isi API Key untuk provider `{provider_aktif}` di sidebar atau file `.env`.",
            model_utama,
            provider_aktif,
        )

    soal_teks, rubrik_teks, daftar_soal_bersih = _format_daftar_soal_teks(
        soal=soal,
        rubrik_guru=rubrik_guru,
        daftar_soal=daftar_soal,
    )
    if not soal_teks:
        return _buat_respons_error(
            "Teks soal tidak boleh kosong.",
            model_utama,
            provider_aktif,
        )

    # 1. Konversi ke payload JPEG ringan 1x (dipakai untuk hash cache sekaligus upload API)
    jpeg_bytes = gambar_ke_jpeg_bytes(image_obj, quality=85, max_width=1024)

    # 2. Cek Intelligent Cache lokal sebelum memanggil ChromaDB atau model AI
    cache_hash = buat_hash_cache(
        image_obj=image_obj,
        soal=soal_teks,
        rubrik_guru=rubrik_teks,
        nama_model=model_utama,
        thinking_level=thinking_level,
        jpeg_bytes=jpeg_bytes,
        provider=provider_aktif,
    )
    if not abaikan_cache:
        hasil_cache = _muat_dari_cache(cache_hash)
        if hasil_cache is not None:
            hasil_cache["waktu_proses_detik"] = round(time.perf_counter() - mulai, 2)
            hasil_cache.setdefault("provider_digunakan", provider_aktif)
            return hasil_cache

    # 3. Ambil konteks referensi materi dari ChromaDB lokal (gunakan konteks_modul batch jika sudah ada)
    if konteks_modul is None:
        if len(daftar_soal_bersih) > 1:
            konteks_modul = cari_konteks_multi_soal(daftar_soal_bersih)
        else:
            konteks_modul = cari_konteks_materi(soal_teks)

    pakai_prompt_ringkas = provider_aktif == "groq"
    prompt_user = _bangun_prompt_koreksi(
        soal_teks=soal_teks,
        rubrik_teks=rubrik_teks,
        konteks_modul=konteks_modul,
        daftar_soal=daftar_soal_bersih,
        sertakan_contoh_json=(provider_aktif != "gemini"),
        mode_ringkas=pakai_prompt_ringkas,
    )

    model_terpakai = model_utama
    fallback_digunakan = False
    total_tunggu_kuota = 0.0

    try:
        if provider_aktif == "gemini":
            active_client = (
                client if isinstance(client, genai.Client) else genai.Client(api_key=api_key.strip())
            )
            try:
                hasil_pydantic = _panggil_gemini(
                    client=active_client,
                    nama_model=model_utama,
                    prompt_user=prompt_user,
                    jpeg_bytes=jpeg_bytes,
                    thinking_level=thinking_level,
                )
            except Exception as exc_utama:
                if not mode_audit_neon and _adalah_error_bisa_fallback(exc_utama):
                    time.sleep(1.0)
                    model_terpakai = MODEL_FALLBACK_FREE
                    fallback_digunakan = True
                    hasil_pydantic = _panggil_fallback_gemini_aman(
                        client=active_client,
                        prompt_user=prompt_user,
                        jpeg_bytes=jpeg_bytes,
                        thinking_level=thinking_level,
                    )
                elif mode_audit_neon and _adalah_error_server_sibuk(exc_utama):
                    time.sleep(2.0)
                    hasil_pydantic = _panggil_gemini(
                        client=active_client,
                        nama_model=model_utama,
                        prompt_user=prompt_user,
                        jpeg_bytes=jpeg_bytes,
                        thinking_level=thinking_level,
                    )
                else:
                    raise
        else:
            http_client = client if isinstance(client, httpx.Client) else None
            sys_prompt_aktif = SYSTEM_INSTRUCTION_RINGKAS if pakai_prompt_ringkas else SYSTEM_INSTRUCTION_GURU
            if provider_aktif == "groq":
                endpoint = GROQ_CHAT_URL
                extra_headers = None
                timeout_detik = 90.0
            elif provider_aktif == "openrouter":
                endpoint = OPENROUTER_CHAT_URL
                extra_headers = {
                    "HTTP-Referer": "http://localhost:8501",
                    "X-Title": "SIDIK-AI",
                }
                timeout_detik = 110.0
            else:  # ollama
                ollama_root = (base_url or OLLAMA_DEFAULT_BASE_URL).rstrip("/")
                endpoint = f"{ollama_root}/v1/chat/completions"
                extra_headers = None
                timeout_detik = 240.0

            model_fb = info_provider.get("fallback_model")
            maks_percobaan = 3 if not model_fb else 2
            hasil_pydantic = None

            for percobaan in range(maks_percobaan):
                try:
                    hasil_pydantic = _panggil_openai_compatible(
                        endpoint_url=endpoint,
                        nama_model=model_terpakai,
                        prompt_user=prompt_user,
                        jpeg_bytes=jpeg_bytes,
                        api_key=api_key if info_provider["butuh_api_key"] else "",
                        extra_headers=extra_headers,
                        http_client=http_client,
                        timeout_detik=timeout_detik,
                        system_instruction=sys_prompt_aktif,
                    )
                    break
                except Exception as exc_oa:
                    if not _adalah_error_bisa_fallback(exc_oa) or percobaan >= maks_percobaan - 1:
                        raise

                    if model_fb and model_fb != model_terpakai:
                        time.sleep(1.0)
                        total_tunggu_kuota += 1.0
                        model_terpakai = str(model_fb)
                        fallback_digunakan = True
                    else:
                        # Baca waktu tunggu resmi dari Groq ('Please try again in Xs') / Retry-After
                        detik_saran = _ekstrak_waktu_tunggu_429(exc_oa)
                        if detik_saran is not None:
                            if detik_saran > 65.0:
                                raise
                            jeda_retry = min(65.0, detik_saran + 1.0 + (percobaan * 0.5))
                        else:
                            jeda_retry = 3.0 * (percobaan + 1)
                        time.sleep(jeda_retry)
                        total_tunggu_kuota += jeda_retry

            assert hasil_pydantic is not None

        hasil_dict = _normalisasi_hasil_model(hasil_pydantic, daftar_soal_bersih)
        hasil_dict.update(
            {
                "status": "berhasil",
                "dari_cache": False,
                "provider_digunakan": provider_aktif,
                "model_digunakan": model_terpakai,
                "fallback_digunakan": fallback_digunakan,
                "menunggu_kuota_detik": round(total_tunggu_kuota, 1),
                "waktu_proses_detik": round(time.perf_counter() - mulai, 2),
                "error": None,
            }
        )

        # 5. Simpan ke cache lokal agar pemrosesan ulang hemat kuota & instan
        _simpan_ke_cache(cache_hash, hasil_dict)
        return hasil_dict

    except Exception as exc:
        pesan = _format_error_informatif(
            exc=exc,
            provider=provider_aktif,
            model_terpakai=model_terpakai,
            model_utama=model_utama,
            fallback_digunakan=fallback_digunakan,
            mode_audit_neon=mode_audit_neon,
            base_url=base_url,
        )
        return _buat_respons_error(pesan, model_terpakai, provider_aktif)

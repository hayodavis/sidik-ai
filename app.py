"""SIDIK-AI: Sistem Digitalisasi & Koreksi Esai Eksakta Berbasis Multimodal RAG.

Antarmuka Local Web App berbasis Streamlit untuk membantu guru mengindeks
modul ajar PDF, mengoreksi tulisan tangan esai eksakta (1 soal maupun multi-soal)
secara cepat dan paralel menggunakan Multi-Provider Vision AI (Groq, OpenRouter,
Ollama Lokal, Google Gemini) + RAG lokal, melakukan validasi/audit guru,
dan mengekspor rekap nilai ke Excel (.xlsx).
"""

from __future__ import annotations

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from google import genai

from src.demo_data import buat_paket_demo_tkj
from src.grader_engine import (
    DAFTAR_PROVIDER,
    MODEL_GROQ_UTAMA,
    OLLAMA_DEFAULT_BASE_URL,
    deteksi_model_groq,
    deteksi_model_ollama,
    koreksi_satu_lembar,
)
from src.ingest_rag import cari_konteks_multi_soal, proses_pdf_ke_vectordb
from src.utils import ekspor_ke_excel, kompres_dan_muat_gambar

# ---------------------------------------------------------------------------
# Konfigurasi Halaman & Lingkungan
# ---------------------------------------------------------------------------
load_dotenv(override=False)

st.set_page_config(
    page_title="SIDIK-AI | Koreksi Esai Otomatis",
    page_icon="📝",
    layout="wide",
)

MODUL_AJAR_DIR = Path("./data/modul_ajar")
API_KEY_PLACEHOLDER = "masukkan_api_key_anda_disini"
OPSI_MODEL_KUSTOM = "Kustom (ketik nama model)..."

DEFAULT_SOAL = (
    "Sebuah balok bermassa 4 kg berada di atas lantai datar licin dan ditarik oleh "
    "gaya mendatar sebesar 20 N. Hitunglah besar percepatan balok tersebut serta jarak "
    "yang ditempuh balok setelah bergerak selama 3 detik dari keadaan diam!"
)

DEFAULT_RUBRIK = """\
1. Pemahaman Konsep & Rumus (Maksimal 40 poin):
   - Menuliskan besaran diketahui secara benar: m = 4 kg, F = 20 N, v0 = 0 m/s, t = 3 s (15 poin).
   - Memilih rumus Hukum II Newton (F = m * a) dan rumus jarak GLBB (s = v0*t + 1/2*a*t^2) dengan tepat (25 poin).

2. Langkah Substitusi & Perhitungan (Maksimal 40 poin):
   - Menghitung percepatan: a = F / m = 20 / 4 = 5 (20 poin).
   - Menghitung jarak tempuh: s = 0(3) + 1/2(5)(3^2) = 1/2(5)(9) = 22,5 (20 poin).

3. Hasil Akhir & Satuan SI (Maksimal 20 poin):
   - Menuliskan hasil akhir percepatan 5 m/s^2 dan jarak 22,5 m secara tepat lengkap dengan satuan SI (20 poin).
"""

KOLOM_TABEL_EDITOR = [
    "nama_siswa",
    "nama_file",
    "skor_konsep",
    "skor_langkah_perhitungan",
    "skor_hasil_dan_satuan",
    "total_nilai",
    "perlu_validasi_guru",
    "alasan_validasi",
    "umpan_balik_siswa",
    "model_digunakan",
    "dari_cache",
]

KOLOM_EKSPOR_EXCEL = [
    "nama_siswa",
    "nama_file",
    "skor_konsep",
    "skor_langkah_perhitungan",
    "skor_hasil_dan_satuan",
    "total_nilai",
    "perlu_validasi_guru",
    "alasan_validasi",
    "analisis_langkah",
    "transkripsi_jawaban_latex",
    "umpan_balik_siswa",
    "provider_digunakan",
    "model_digunakan",
    "dari_cache",
]


# ---------------------------------------------------------------------------
# Helper State, Multi-Soal & Rekap Data
# ---------------------------------------------------------------------------
def _baca_env_bersih(nama_var: str) -> str:
    """Membaca variabel lingkungan dari .env atau st.secrets (Streamlit Cloud) secara aman."""
    nilai = os.getenv(nama_var, "").strip()
    if not nilai:
        try:
            nilai = str(st.secrets.get(nama_var, "")).strip()
        except Exception:
            nilai = ""
    return "" if nilai == API_KEY_PLACEHOLDER else nilai


def _ambil_api_key_efektif(nama_env: str, input_pengguna: str) -> tuple[str, bool]:
    """Mengembalikan (api_key_efektif, berasal_dari_server).

    API Key dari .env / st.secrets hanya dipakai di sisi server (backend) dan TIDAK
    pernah diisikan ke widget input browser, sehingga tidak dapat diintip lewat ikon mata.
    Pengguna tetap dapat mengetik API Key sendiri di sidebar untuk menggantinya di sesi aktif.
    """
    input_bersih = (input_pengguna or "").strip()
    if _api_key_valid(input_bersih):
        return input_bersih, False

    server_key = _baca_env_bersih(nama_env)
    if _api_key_valid(server_key):
        return server_key, True

    return "", False


def _muat_mode_demo_tkj() -> None:
    """Memuat paket simulasi SMK TKJ (Subnetting IPv4) agar juri dapat mencoba aplikasi 1 klik tanpa API Key."""
    paket = buat_paket_demo_tkj()

    # Hapus widget soal lama agar tidak menyisakan kunci usang
    for uid_lama in list(st.session_state.get("daftar_soal_ids", [])):
        st.session_state.pop(f"soal_pertanyaan_{uid_lama}", None)
        st.session_state.pop(f"soal_rubrik_{uid_lama}", None)
        st.session_state.pop(f"soal_bobot_{uid_lama}", None)

    daftar_soal = paket["daftar_soal"]
    ids_baru: list[int] = []
    for idx, item in enumerate(daftar_soal, start=1):
        ids_baru.append(idx)
        st.session_state[f"soal_pertanyaan_{idx}"] = item["pertanyaan"]
        st.session_state[f"soal_rubrik_{idx}"] = item["rubrik"]
        st.session_state[f"soal_bobot_{idx}"] = int(item["bobot"])

    st.session_state["daftar_soal_ids"] = ids_baru
    st.session_state["next_soal_uid"] = len(ids_baru) + 1
    st.session_state["daftar_soal_terakhir"] = daftar_soal
    st.session_state["nama_ujian_input"] = paket["nama_ujian"]
    st.session_state["gambar_siswa"] = paket["gambar_siswa"]
    st.session_state["hasil_koreksi"] = paket["hasil_koreksi"]
    st.session_state["editor_version"] = int(st.session_state.get("editor_version", 0)) + 1
    st.session_state["pesan_notifikasi_validasi"] = (
        "Mode Demo SMK TKJ (Materi Subnetting IPv4 — 2 Soal, 3 Siswa) berhasil dimuat! "
        "Anda dapat mengedit skor di tabel, memilih siswa untuk melihat foto vs LaTeX, "
        "dan mengunduh rekap Excel tanpa memerlukan API Key."
    )


def _inisialisasi_session_state() -> None:
    """Inisialisasi seluruh kunci st.session_state di satu tempat yang terpusat."""
    env_groq = _baca_env_bersih("GROQ_API_KEY")
    env_openrouter = _baca_env_bersih("OPENROUTER_API_KEY")
    env_ollama = os.getenv("OLLAMA_BASE_URL", OLLAMA_DEFAULT_BASE_URL).strip() or OLLAMA_DEFAULT_BASE_URL

    # Prioritaskan Groq sebagai default agar guru langsung melihat opsi gratis tercepat
    provider_default = "groq"
    if not env_groq and env_openrouter:
        provider_default = "openrouter"

    defaults: dict[str, Any] = {
        "provider_ai_select": provider_default,
        # Sengaja dikosongkan agar API Key dari .env / st.secrets tidak pernah terekspos di UI browser
        "groq_api_key_input": "",
        "openrouter_api_key_input": "",
        "gemini_api_key_input": "",
        "ollama_base_url_input": env_ollama,
        "ollama_models_detected": [],
        "groq_models_detected": [],
        "nama_ujian_input": "UH1_Fisika_Hukum_Newton",
        "hasil_koreksi": [],
        "gambar_siswa": {},
        "cache_gambar_upload": {},
        "pdf_tersimpan_sesi": set(),
        "status_indeks_rag": None,
        "daftar_soal_ids": [1],
        "next_soal_uid": 2,
        "soal_pertanyaan_1": DEFAULT_SOAL,
        "soal_rubrik_1": DEFAULT_RUBRIK,
        "soal_bobot_1": 100,
        "daftar_soal_terakhir": [
            {
                "nomor": 1,
                "pertanyaan": DEFAULT_SOAL,
                "rubrik": DEFAULT_RUBRIK,
                "bobot": 100,
            }
        ],
        "editor_version": 0,
        "pesan_notifikasi_validasi": None,
    }
    for kunci, nilai in defaults.items():
        if kunci not in st.session_state:
            st.session_state[kunci] = nilai


def _tambah_butir_soal() -> None:
    """Menambahkan satu kartu soal baru (kosong) ke daftar soal dinamis."""
    uid_baru = int(st.session_state["next_soal_uid"])
    st.session_state["next_soal_uid"] = uid_baru + 1
    st.session_state["daftar_soal_ids"].append(uid_baru)
    st.session_state[f"soal_pertanyaan_{uid_baru}"] = ""
    st.session_state[f"soal_rubrik_{uid_baru}"] = ""
    st.session_state[f"soal_bobot_{uid_baru}"] = 50


def _hapus_butir_soal(uid_target: int) -> None:
    """Menghapus satu butir soal tertentu (minimal selalu tersisa 1 soal)."""
    ids_aktif: list[int] = st.session_state["daftar_soal_ids"]
    if len(ids_aktif) <= 1 or uid_target not in ids_aktif:
        return
    ids_aktif.remove(uid_target)
    st.session_state.pop(f"soal_pertanyaan_{uid_target}", None)
    st.session_state.pop(f"soal_rubrik_{uid_target}", None)
    st.session_state.pop(f"soal_bobot_{uid_target}", None)


def _bagi_bobot_merata() -> None:
    """Membagi total bobot 100 secara merata ke seluruh butir soal yang aktif."""
    ids_aktif: list[int] = st.session_state["daftar_soal_ids"]
    jumlah = len(ids_aktif)
    if jumlah == 0:
        return
    dasar = 100 // jumlah
    sisa = 100 % jumlah
    for idx, uid in enumerate(ids_aktif):
        st.session_state[f"soal_bobot_{uid}"] = dasar + (1 if idx < sisa else 0)


def _kumpulkan_daftar_soal_aktif() -> list[dict[str, Any]]:
    """Membaca seluruh soal, rubrik, dan bobot terkini dari widget di Tab 2."""
    daftar: list[dict[str, Any]] = []
    for nomor, uid in enumerate(st.session_state["daftar_soal_ids"], start=1):
        daftar.append(
            {
                "nomor": nomor,
                "pertanyaan": str(st.session_state.get(f"soal_pertanyaan_{uid}", "")).strip(),
                "rubrik": str(st.session_state.get(f"soal_rubrik_{uid}", "")).strip(),
                "bobot": max(1, int(st.session_state.get(f"soal_bobot_{uid}", 100))),
            }
        )
    return daftar


def _muat_gambar_tercache(uploaded_file: Any) -> Any:
    """Memuat & mengompresi gambar dengan cache sesi agar tidak diproses ulang tiap rerun."""
    kunci = (uploaded_file.name, uploaded_file.size)
    cache_map: dict[tuple[str, int], Any] = st.session_state["cache_gambar_upload"]
    if kunci not in cache_map:
        cache_map[kunci] = kompres_dan_muat_gambar(uploaded_file, max_width=1024)
    return cache_map[kunci]


def _daftar_pdf_tersimpan() -> list[dict[str, Any]]:
    """Membaca daftar file PDF yang saat ini tersedia di ./data/modul_ajar/."""
    MODUL_AJAR_DIR.mkdir(parents=True, exist_ok=True)
    daftar: list[dict[str, Any]] = []
    for path_pdf in sorted(
        (p for p in MODUL_AJAR_DIR.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"),
        key=lambda p: p.name.lower(),
    ):
        ukuran_kb = path_pdf.stat().st_size / 1024
        ukuran_teks = f"{ukuran_kb / 1024:.2f} MB" if ukuran_kb >= 1024 else f"{ukuran_kb:.1f} KB"
        daftar.append(
            {
                "Nama File PDF": path_pdf.name,
                "Ukuran": ukuran_teks,
                "Terakhir Diubah": datetime.fromtimestamp(path_pdf.stat().st_mtime).strftime(
                    "%d-%m-%Y %H:%M"
                ),
            }
        )
    return daftar


def _api_key_valid(api_key: str) -> bool:
    """Memastikan API key tidak kosong dan bukan teks placeholder default."""
    bersih = (api_key or "").strip()
    return bool(bersih) and bersih != API_KEY_PLACEHOLDER


def _buat_dataframe_rekap(hasil_list: list[dict[str, Any]]) -> pd.DataFrame:
    """Menyusun DataFrame rapi untuk st.data_editor di Tab 3."""
    baris = []
    for item in hasil_list:
        baris.append(
            {
                "nama_siswa": str(item.get("nama_siswa", "Tanpa Nama")),
                "nama_file": str(item.get("nama_file", "-")),
                "skor_konsep": int(item.get("skor_konsep", 0)),
                "skor_langkah_perhitungan": int(item.get("skor_langkah_perhitungan", 0)),
                "skor_hasil_dan_satuan": int(item.get("skor_hasil_dan_satuan", 0)),
                "total_nilai": int(item.get("total_nilai", 0)),
                "perlu_validasi_guru": bool(item.get("perlu_validasi_guru", False)),
                "alasan_validasi": str(item.get("alasan_validasi", "-")),
                "umpan_balik_siswa": str(item.get("umpan_balik_siswa", "")),
                "model_digunakan": str(item.get("model_digunakan", "-")),
                "dari_cache": bool(item.get("dari_cache", False)),
            }
        )
    return pd.DataFrame(baris, columns=KOLOM_TABEL_EDITOR)


def _gabungkan_edit_ke_hasil(
    hasil_asli: list[dict[str, Any]],
    df_diedit: pd.DataFrame,
    edited_rows: dict[int, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Menggabungkan hasil edit manual guru dari st.data_editor ke daftar hasil."""
    edited_rows = edited_rows or {}
    hasil_baru: list[dict[str, Any]] = []

    for idx, item_lama in enumerate(hasil_asli):
        salinan = dict(item_lama)
        row = df_diedit.iloc[idx]
        perubahan_baris = edited_rows.get(idx, {})

        skor_konsep = max(0, min(40, int(row["skor_konsep"])))
        skor_langkah = max(0, min(40, int(row["skor_langkah_perhitungan"])))
        skor_hasil = max(0, min(20, int(row["skor_hasil_dan_satuan"])))

        komponen_diubah = any(
            k in perubahan_baris
            for k in ("skor_konsep", "skor_langkah_perhitungan", "skor_hasil_dan_satuan")
        )
        if komponen_diubah and "total_nilai" not in perubahan_baris:
            total_nilai = skor_konsep + skor_langkah + skor_hasil
        else:
            total_nilai = max(0, min(100, int(row["total_nilai"])))

        perlu_val = bool(row["perlu_validasi_guru"])
        alasan_val = str(row["alasan_validasi"]).strip() if row["alasan_validasi"] is not None else "-"
        if not perlu_val and not alasan_val:
            alasan_val = "-"

        salinan.update(
            {
                "nama_siswa": str(row["nama_siswa"]).strip() or "Tanpa Nama",
                "skor_konsep": skor_konsep,
                "skor_langkah_perhitungan": skor_langkah,
                "skor_hasil_dan_satuan": skor_hasil,
                "total_nilai": total_nilai,
                "perlu_validasi_guru": perlu_val,
                "alasan_validasi": alasan_val or "-",
                "umpan_balik_siswa": str(row["umpan_balik_siswa"] or "").strip(),
            }
        )
        hasil_baru.append(salinan)

    return hasil_baru


def _buat_dataframe_ekspor(hasil_tergabung: list[dict[str, Any]]) -> pd.DataFrame:
    """Menyusun DataFrame lengkap untuk ekspor Excel (termasuk kolom skor per nomor jika multi-soal)."""
    max_soal = max((len(item.get("rincian_per_soal") or []) for item in hasil_tergabung), default=0)
    kolom_per_soal = [f"skor_soal_{n}" for n in range(1, max_soal + 1)] if max_soal > 1 else []
    kolom_akhir = (
        ["nama_siswa", "nama_file"]
        + kolom_per_soal
        + [k for k in KOLOM_EKSPOR_EXCEL if k not in ("nama_siswa", "nama_file")]
    )

    baris = []
    for item in hasil_tergabung:
        entri = {kol: item.get(kol, "") for kol in KOLOM_EKSPOR_EXCEL}
        if kolom_per_soal:
            peta_rincian = {
                int(r["nomor_soal"]): int(r["skor_diperoleh"])
                for r in (item.get("rincian_per_soal") or [])
            }
            for n in range(1, max_soal + 1):
                entri[f"skor_soal_{n}"] = peta_rincian.get(n, 0)
        baris.append({kol: entri.get(kol, "") for kol in kolom_akhir})

    return pd.DataFrame(baris, columns=kolom_akhir)


def _nama_file_excel_unduhan(nama_ujian: str) -> str:
    """Membuat nama file unduhan Excel yang bersih dan berstempel waktu."""
    bersih = re.sub(r"[^\w\s-]", "", (nama_ujian or "").strip())
    bersih = re.sub(r"[\s]+", "_", bersih).strip("_-") or "Ujian"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"Rekap_SIDIK_AI_{bersih}_{timestamp}.xlsx"


# ---------------------------------------------------------------------------
# Inisialisasi State & Header Utama
# ---------------------------------------------------------------------------
_inisialisasi_session_state()

st.title("📝 SIDIK-AI")
st.caption("Sistem Digitalisasi & Koreksi Esai Eksakta Berbasis Multimodal RAG")


# ---------------------------------------------------------------------------
# Sidebar Pengaturan Multi-Provider & Global
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Pengaturan Aplikasi")

    provider_aktif = st.selectbox(
        "Provider AI Vision",
        options=["groq", "openrouter", "ollama", "gemini"],
        key="provider_ai_select",
        format_func=lambda p: DAFTAR_PROVIDER[p]["label"],
        help="Pilih mesin AI untuk membaca tulisan tangan & mengoreksi esai. Groq gratis & sangat cepat; Ollama 100% lokal tanpa limit.",
    )
    info_prov = DAFTAR_PROVIDER[provider_aktif]

    api_key_aktif = ""
    model_aktif = str(info_prov["default_model"])
    ollama_url_aktif = st.session_state["ollama_base_url_input"]
    mode_kecepatan = "cepat"

    if provider_aktif == "groq":
        server_groq_ada = _api_key_valid(_baca_env_bersih("GROQ_API_KEY"))
        input_groq = st.text_input(
            "GROQ_API_KEY" + (" (Opsional — key server aktif)" if server_groq_ada else ""),
            type="password",
            key="groq_api_key_input",
            placeholder=(
                "Tersambung aman ke Secrets server (isi jika ingin pakai key sendiri)"
                if server_groq_ada
                else "Tempel Groq API Key (gsk_...) di sini..."
            ),
            help="API Key dari .env / Streamlit Secrets berjalan aman di backend tanpa ditampilkan di browser.",
        )
        api_key_aktif, pakai_key_server = _ambil_api_key_efektif("GROQ_API_KEY", input_groq)
        st.caption(
            "Buat API Key **gratis & cepat** di "
            "[Groq Console](https://console.groq.com/keys)."
        )
        if st.button(
            "Cek Model Aktif di Akun Groq",
            icon=":material/refresh:",
            key="btn_deteksi_groq",
            width="stretch",
            disabled=not _api_key_valid(api_key_aktif),
        ):
            daftar_groq = deteksi_model_groq(api_key_aktif)
            st.session_state["groq_models_detected"] = daftar_groq
            if daftar_groq:
                st.toast(f"Ditemukan {len(daftar_groq)} model aktif di akun Groq Anda.", icon="⚡")
            else:
                st.warning(
                    "Gagal mengambil daftar model Groq. Periksa GROQ_API_KEY atau koneksi internet.",
                    title="Deteksi model Groq gagal",
                )

        model_groq_terdeteksi = list(st.session_state.get("groq_models_detected") or [])
        opsi_groq = list(dict.fromkeys(list(info_prov["pilihan_model"]) + model_groq_terdeteksi)) + [
            OPSI_MODEL_KUSTOM
        ]
        pilihan_groq = st.selectbox(
            "Model Vision Groq",
            options=opsi_groq,
            key="model_groq_select",
            help="Gunakan model multimodal/vision aktif Groq seperti 'qwen/qwen3.8-27b' (Llama 4 Scout/Maverick sudah dihentikan oleh Groq).",
        )
        if pilihan_groq == OPSI_MODEL_KUSTOM:
            model_aktif = st.text_input(
                "ID Model Kustom Groq",
                value=MODEL_GROQ_UTAMA,
                key="model_groq_kustom",
            ).strip() or MODEL_GROQ_UTAMA
        else:
            model_aktif = pilihan_groq

        if pakai_key_server:
            st.caption(":green-badge[Terhubung ke API Key server (aman & siap pakai)]")
        elif _api_key_valid(api_key_aktif):
            st.caption(":green-badge[Groq API Key kustom siap digunakan]")
        else:
            st.caption(":orange-badge[GROQ_API_KEY belum diisi]")

    elif provider_aktif == "openrouter":
        server_or_ada = _api_key_valid(_baca_env_bersih("OPENROUTER_API_KEY"))
        input_or = st.text_input(
            "OPENROUTER_API_KEY" + (" (Opsional — key server aktif)" if server_or_ada else ""),
            type="password",
            key="openrouter_api_key_input",
            placeholder=(
                "Tersambung aman ke Secrets server (isi jika ingin pakai key sendiri)"
                if server_or_ada
                else "Tempel OpenRouter API Key (sk-or-...) di sini..."
            ),
            help="API Key dari .env / Streamlit Secrets berjalan aman di backend tanpa ditampilkan di browser.",
        )
        api_key_aktif, pakai_key_server = _ambil_api_key_efektif("OPENROUTER_API_KEY", input_or)
        st.caption(
            "Buat API Key (tersedia model `:free`) di "
            "[OpenRouter Keys](https://openrouter.ai/keys)."
        )
        pilihan_or = list(info_prov["pilihan_model"]) + [OPSI_MODEL_KUSTOM]
        pilihan_terselect = st.selectbox(
            "Model Vision OpenRouter",
            options=pilihan_or,
            key="model_openrouter_select",
            help="'openrouter/free' otomatis memilih model vision gratis yang sedang aktif.",
        )
        if pilihan_terselect == OPSI_MODEL_KUSTOM:
            model_aktif = st.text_input(
                "ID Model Kustom OpenRouter",
                value="google/gemma-4-31b-it:free",
                key="model_openrouter_kustom",
            ).strip() or "openrouter/free"
        else:
            model_aktif = pilihan_terselect

        if pakai_key_server:
            st.caption(":green-badge[Terhubung ke API Key server (aman & siap pakai)]")
        elif _api_key_valid(api_key_aktif):
            st.caption(":green-badge[OpenRouter API Key kustom siap digunakan]")
        else:
            st.caption(":orange-badge[OPENROUTER_API_KEY belum diisi]")

    elif provider_aktif == "ollama":
        ollama_url_aktif = st.text_input(
            "URL Server Ollama Lokal",
            key="ollama_base_url_input",
            help="Default: http://localhost:11434",
        )
        if st.button(
            "Deteksi Model Terpasang di Ollama",
            icon=":material/refresh:",
            key="btn_deteksi_ollama",
            width="stretch",
        ):
            terdeteksi = deteksi_model_ollama(ollama_url_aktif)
            st.session_state["ollama_models_detected"] = terdeteksi
            if terdeteksi:
                st.toast(f"Ditemukan {len(terdeteksi)} model lokal di Ollama.", icon="💻")
            else:
                st.warning(
                    "Ollama tidak merespons atau belum ada model terunduh.",
                    title="Ollama belum terdeteksi",
                )

        model_terdeteksi = list(st.session_state.get("ollama_models_detected") or [])
        opsi_ollama = list(dict.fromkeys(model_terdeteksi + list(info_prov["pilihan_model"]))) + [
            OPSI_MODEL_KUSTOM
        ]
        pilihan_ollama = st.selectbox(
            "Model Vision Ollama",
            options=opsi_ollama,
            key="model_ollama_select",
            help="Pastikan model sudah diunduh via terminal: ollama pull qwen2.5vl:7b",
        )
        if pilihan_ollama == OPSI_MODEL_KUSTOM:
            model_aktif = st.text_input(
                "Nama Model Ollama Kustom",
                value="qwen2.5vl:7b",
                key="model_ollama_kustom",
            ).strip() or "qwen2.5vl:7b"
        else:
            model_aktif = pilihan_ollama

        st.caption(":green-badge[100% Lokal · Tanpa API Key · Unlimited]")
        st.caption("Unduh model vision lokal: `ollama pull qwen2.5vl:7b` atau `ollama pull gemma3:4b`.")

    else:  # gemini
        server_gemini_ada = _api_key_valid(_baca_env_bersih("GEMINI_API_KEY"))
        input_gemini = st.text_input(
            "GEMINI_API_KEY" + (" (Opsional — key server aktif)" if server_gemini_ada else ""),
            type="password",
            key="gemini_api_key_input",
            placeholder=(
                "Tersambung aman ke Secrets server (isi jika ingin pakai key sendiri)"
                if server_gemini_ada
                else "Tempel API Key Gemini Anda di sini..."
            ),
            help="API Key dari .env / Streamlit Secrets berjalan aman di backend tanpa ditampilkan di browser.",
        )
        api_key_aktif, pakai_key_server = _ambil_api_key_efektif("GEMINI_API_KEY", input_gemini)
        st.caption(
            "Buat API Key Free Tier di "
            "[Google AI Studio](https://aistudio.google.com/apikey)."
        )
        mode_kecepatan = str(
            st.segmented_control(
                "Mode Kecepatan Gemini",
                options=["cepat", "teliti"],
                default="cepat",
                required=True,
                key="mode_kecepatan_ai",
                width="stretch",
                format_func=lambda v: "⚡ Cepat" if v == "cepat" else "🎯 Teliti",
                help="Mode Cepat memakai thinking_level='minimal'; Mode Teliti memakai thinking_level='low'.",
            )
            or "cepat"
        )
        if pakai_key_server:
            st.caption(":green-badge[Terhubung ke API Key server (aman & siap pakai)]")
        elif _api_key_valid(api_key_aktif):
            st.caption(":green-badge[Gemini API Key kustom siap digunakan]")
        else:
            st.caption(":orange-badge[GEMINI_API_KEY belum diisi]")

    st.divider()

    nama_ujian = st.text_input(
        "Nama Ujian / Mata Pelajaran",
        key="nama_ujian_input",
        help="Digunakan sebagai label nama file saat mengekspor rekap Excel.",
    )

    default_paralel = 1 if provider_aktif == "ollama" else (2 if provider_aktif == "groq" else 3)
    jumlah_paralel = st.slider(
        "Jumlah Lembar Paralel",
        min_value=1,
        max_value=5,
        value=default_paralel,
        step=1,
        key="jumlah_paralel_slider",
        help="Groq Free Tier memiliki batas ~7.000 token input/menit (ideal 1-2 paralel). Ollama lokal disarankan 1.",
    )
    if provider_aktif == "groq":
        st.caption(
            "Groq Free Tier: batas ~7.000 token/menit (~2 lembar sekaligus). "
            "Jika antrean melebihi batas, SIDIK-AI otomatis menunggu kuota pulih agar semua lembar selesai."
        )

    jeda_detik = st.slider(
        "Jeda Antar Gelombang (detik)",
        min_value=0,
        max_value=10,
        value=0 if provider_aktif == "ollama" else 1,
        step=1,
        key="jeda_antar_lembar",
        help="Jeda antar gelombang permintaan API non-cache untuk menjaga keamanan kuota.",
    )

    abaikan_cache = st.checkbox(
        "Abaikan Cache (Paksa Koreksi Ulang API)",
        value=False,
        key="abaikan_cache_checkbox",
        help="Jika dicentang, aplikasi tidak membaca hasil cache lokal dan akan memanggil model AI ulang.",
    )

    st.divider()
    st.caption("Ingin langsung mencoba tanpa API Key?")
    if st.button(
        "🎯 Muat Mode Demo TKJ",
        key="btn_muat_demo_sidebar",
        width="stretch",
        on_click=_muat_mode_demo_tkj,
        help="Memuat contoh 2 soal Subnetting IPv4 + 3 lembar jawaban siswa TKJ untuk dicoba langsung di Tab 2 & Tab 3.",
    ):
        st.toast("Mode Demo TKJ dimuat! Buka tab '✅ Validasi Guru & Rekap Nilai'.", icon="🎯")


# ---------------------------------------------------------------------------
# 3 Tab Utama Aplikasi
# ---------------------------------------------------------------------------
tab_rag, tab_koreksi, tab_validasi = st.tabs(
    [
        "📚 Basis Pengetahuan (Modul RAG)",
        "📝 Koreksi Lembar Jawaban",
        "✅ Validasi Guru & Rekap Nilai",
    ]
)


# ===========================================================================
# TAB 1: BASIS PENGETAHUAN (MODUL RAG)
# ===========================================================================
with tab_rag:
    st.subheader("Unggah dan indeks modul ajar PDF")
    st.markdown(
        "Unggah buku paket, diktat, atau rangkuman materi eksakta (`.pdf`) sebagai "
        "referensi resmi AI saat menilai ketepatan konsep, rumus, dan satuan jawaban siswa."
    )

    with st.container(border=True):
        pdf_diunggah = st.file_uploader(
            "Unggah file PDF modul ajar / buku paket",
            type=["pdf"],
            accept_multiple_files=True,
            key="uploader_modul_pdf",
            help="File akan otomatis disimpan ke folder ./data/modul_ajar/.",
        )

        if pdf_diunggah:
            MODUL_AJAR_DIR.mkdir(parents=True, exist_ok=True)
            jumlah_baru = 0
            for file_pdf in pdf_diunggah:
                tanda_file = (file_pdf.name, file_pdf.size)
                tujuan = MODUL_AJAR_DIR / Path(file_pdf.name).name
                if tanda_file not in st.session_state["pdf_tersimpan_sesi"] or not tujuan.exists():
                    tujuan.write_bytes(file_pdf.getvalue())
                    st.session_state["pdf_tersimpan_sesi"].add(tanda_file)
                    jumlah_baru += 1
            if jumlah_baru > 0:
                st.toast(f"{jumlah_baru} file PDF disimpan ke folder modul ajar.", icon="📚")

    st.subheader("Daftar modul PDF tersimpan")
    daftar_pdf = _daftar_pdf_tersimpan()

    if daftar_pdf:
        df_pdf = pd.DataFrame(daftar_pdf)
        st.dataframe(
            df_pdf,
            hide_index=True,
            width="stretch",
            alt="Daftar file PDF modul ajar yang tersimpan di folder data/modul_ajar",
        )
    else:
        st.info(
            "Belum ada file PDF di folder `./data/modul_ajar/`. Unggah minimal satu modul "
            "ajar di atas agar AI memiliki referensi materi yang akurat.",
            title="Folder modul ajar masih kosong",
        )

    if st.button(
        "Proses & Simpan ke Memori AI",
        type="primary",
        key="btn_proses_rag",
        disabled=len(daftar_pdf) == 0,
    ):
        with st.spinner("Mengekstrak teks PDF dan membangun indeks memori lokal ChromaDB..."):
            ringkasan_rag = proses_pdf_ke_vectordb(str(MODUL_AJAR_DIR))
            st.session_state["status_indeks_rag"] = ringkasan_rag

    ringkasan_terakhir = st.session_state.get("status_indeks_rag")
    if isinstance(ringkasan_terakhir, dict):
        if ringkasan_terakhir.get("jumlah_file", 0) > 0:
            st.success(
                f"Berhasil mengindeks **{ringkasan_terakhir['jumlah_file']} file PDF** "
                f"menjadi **{ringkasan_terakhir['jumlah_chunks']} potongan teks** "
                f"(total tersimpan di database: {ringkasan_terakhir.get('total_chunks_di_db', 0)} potongan).",
                title="Memori AI berhasil diperbarui",
            )
        else:
            st.warning(
                ringkasan_terakhir.get("pesan", "Tidak ada modul PDF yang berhasil diindeks."),
                title="Indeksasi belum memproses file",
            )

        file_gagal = ringkasan_terakhir.get("file_gagal") or []
        if file_gagal:
            detail_gagal = "\n".join(
                f"- **{item['nama_file']}**: {item['alasan']}" for item in file_gagal
            )
            st.warning(
                f"Beberapa file tidak dapat diekstrak:\n{detail_gagal}",
                title="Sebagian file dilewati",
            )


# ===========================================================================
# TAB 2: KOREKSI LEMBAR JAWABAN (MULTI-SOAL DINAMIS + 2 KOLOM)
# ===========================================================================
with tab_koreksi:
    st.subheader("Daftar soal & rubrik penilaian (multi-soal)")

    daftar_uid_soal: list[int] = st.session_state["daftar_soal_ids"]
    total_bobot_saat_ini = sum(
        int(st.session_state.get(f"soal_bobot_{uid}", 100)) for uid in daftar_uid_soal
    )

    with st.container(horizontal=True, vertical_alignment="center"):
        st.button(
            "Tambah Soal",
            icon=":material/add:",
            key="btn_tambah_soal",
            on_click=_tambah_butir_soal,
        )
        if len(daftar_uid_soal) > 1:
            st.button(
                "Bagi Bobot Rata (100)",
                icon=":material/balance:",
                key="btn_bagi_bobot_rata",
                on_click=_bagi_bobot_merata,
            )
        badge_bobot = (
            f":green-badge[Total {len(daftar_uid_soal)} soal · Bobot {total_bobot_saat_ini} poin]"
            if total_bobot_saat_ini == 100
            else f":orange-badge[Total {len(daftar_uid_soal)} soal · Bobot {total_bobot_saat_ini} poin (dinormalisasi ke 100)]"
        )
        st.markdown(badge_bobot)
        st.markdown(f":blue-badge[Provider: {provider_aktif.upper()} · {model_aktif}]")

    for nomor_tampil, uid in enumerate(daftar_uid_soal, start=1):
        with st.container(border=True):
            col_hdr, col_bobot, col_hapus = st.columns([3.5, 1.2, 0.8], vertical_alignment="bottom")
            col_hdr.markdown(f"#### Soal Nomor {nomor_tampil}")
            col_bobot.number_input(
                "Bobot Poin",
                min_value=1,
                max_value=100,
                step=1,
                key=f"soal_bobot_{uid}",
            )
            col_hapus.button(
                "Hapus",
                icon=":material/delete:",
                key=f"btn_hapus_soal_{uid}",
                on_click=_hapus_butir_soal,
                args=(uid,),
                disabled=len(daftar_uid_soal) <= 1,
                width="stretch",
            )

            col_soal, col_rubrik = st.columns(2, gap="medium")
            with col_soal:
                st.text_area(
                    f"Pertanyaan Soal No. {nomor_tampil}",
                    height=160,
                    key=f"soal_pertanyaan_{uid}",
                    placeholder="Tulis pertanyaan soal esai eksakta lengkap beserta data angka dan satuan...",
                )
            with col_rubrik:
                st.text_area(
                    f"Rubrik Penilaian / Kunci Jawaban No. {nomor_tampil}",
                    height=160,
                    key=f"soal_rubrik_{uid}",
                    placeholder="Tulis rumus kunci, langkah perhitungan, dan pembagian poin penilaian...",
                )

    with st.container(border=True):
        file_lembar_jawaban = st.file_uploader(
            "Unggah Foto / Scan Lembar Jawaban Tulisan Tangan Siswa",
            type=["jpg", "jpeg", "png"],
            accept_multiple_files=True,
            key="uploader_lembar_jawaban",
            help="Dapat mengunggah banyak lembar sekaligus. Orientasi foto kamera HP akan otomatis diperbaiki dan dikompresi ringan.",
        )

        if file_lembar_jawaban:
            st.caption(f"Siap dikoreksi: **{len(file_lembar_jawaban)} lembar jawaban**.")
            exp_preview = st.expander(
                "Pratinjau foto lembar jawaban yang diunggah",
                expanded=False,
                on_change="rerun",
                key="exp_preview_foto",
            )
            if exp_preview.open:
                with exp_preview:
                    kolom_preview = st.columns(min(4, len(file_lembar_jawaban)))
                    for idx_img, file_img in enumerate(file_lembar_jawaban):
                        img_preview = _muat_gambar_tercache(file_img)
                        with kolom_preview[idx_img % len(kolom_preview)]:
                            st.image(
                                img_preview,
                                caption=file_img.name,
                                alt=f"Pratinjau lembar jawaban siswa {file_img.name}",
                                width="stretch",
                            )

    if st.button(
        "🚀 Mulai Koreksi Otomatis AI",
        type="primary",
        key="btn_mulai_koreksi",
        width="stretch",
    ):
        daftar_soal_aktif = _kumpulkan_daftar_soal_aktif()
        soal_kosong = [s["nomor"] for s in daftar_soal_aktif if not s["pertanyaan"]]

        if info_prov["butuh_api_key"] and not _api_key_valid(api_key_aktif):
            env_nama = info_prov["env_var"]
            link_key = info_prov["link_key"]
            st.error(
                f"Silakan masukkan `{env_nama}` yang valid pada sidebar sebelah kiri "
                f"(buat gratis di {link_key}) atau ganti ke **Ollama Lokal**.",
                title=f"{env_nama} belum tersedia",
            )
        elif soal_kosong:
            daftar_no = ", ".join(str(n) for n in soal_kosong)
            st.error(
                f"Kolom **Pertanyaan Soal** untuk nomor **{daftar_no}** masih kosong. "
                "Isi terlebih dahulu atau hapus kartu soal yang tidak dipakai.",
                title="Ada soal yang belum diisi",
            )
        elif not file_lembar_jawaban:
            st.warning(
                "Unggah minimal satu foto atau scan lembar jawaban siswa terlebih dahulu.",
                title="Belum ada lembar jawaban yang diunggah",
            )
        else:
            st.session_state["daftar_soal_terakhir"] = daftar_soal_aktif
            mulai_batch = time.perf_counter()
            total_lembar = len(file_lembar_jawaban)

            hasil_terurut: dict[int, dict[str, Any]] = {}
            gambar_batch: dict[str, Any] = {}
            daftar_error: list[str] = []

            progress_bar = st.progress(0, text="Mempersiapkan gambar dan referensi modul RAG...")
            with st.status(
                f"Mengoreksi {total_lembar} lembar dengan {provider_aktif.upper()} ({model_aktif})...",
                expanded=True,
            ) as status_box:
                # 1. Muat & kompresi seluruh gambar di thread utama (cache sesi)
                tugas_lembar: list[tuple[int, str, str, Any]] = []
                for idx, file_img in enumerate(file_lembar_jawaban):
                    nomor = idx + 1
                    id_lembar = f"{nomor}_{file_img.name}"
                    try:
                        img_siap = _muat_gambar_tercache(file_img)
                        gambar_batch[id_lembar] = img_siap
                        tugas_lembar.append((idx, id_lembar, file_img.name, img_siap))
                    except Exception as exc_img:
                        pesan_err = f"{file_img.name}: gagal memuat gambar ({exc_img})"
                        daftar_error.append(pesan_err)
                        st.error(pesan_err)

                # 2. Ambil konteks RAG 1x untuk seluruh batch & siapkan 1 shared client
                st.write("Mengambil referensi modul ajar dari ChromaDB (1× untuk seluruh batch)...")
                konteks_rag_batch = cari_konteks_multi_soal(daftar_soal_aktif)

                shared_http_client: httpx.Client | None = None
                shared_client: Any = None
                if provider_aktif == "gemini":
                    shared_client = genai.Client(api_key=api_key_aktif.strip())
                else:
                    timeout_batch = 240.0 if provider_aktif == "ollama" else 110.0
                    shared_http_client = httpx.Client(timeout=timeout_batch)
                    shared_client = shared_http_client

                try:
                    # 3. Proses secara paralel per gelombang (wave)
                    selesai_count = len(daftar_error)
                    ukuran_gelombang = max(1, int(jumlah_paralel))
                    gelombang_list = [
                        tugas_lembar[i : i + ukuran_gelombang]
                        for i in range(0, len(tugas_lembar), ukuran_gelombang)
                    ]

                    for idx_wave, wave in enumerate(gelombang_list, start=1):
                        ada_panggilan_api_live = False

                        with ThreadPoolExecutor(max_workers=len(wave)) as executor:
                            future_map = {
                                executor.submit(
                                    koreksi_satu_lembar,
                                    image_obj=img_obj,
                                    soal="",
                                    rubrik_guru="",
                                    api_key=api_key_aktif,
                                    mode_audit_neon=False,
                                    abaikan_cache=abaikan_cache,
                                    mode_kecepatan=mode_kecepatan,
                                    daftar_soal=daftar_soal_aktif,
                                    konteks_modul=konteks_rag_batch,
                                    client=shared_client,
                                    provider=provider_aktif,
                                    model_override=model_aktif,
                                    base_url=ollama_url_aktif,
                                ): (idx_asli, id_lembar, nama_file)
                                for idx_asli, id_lembar, nama_file, img_obj in wave
                            }

                            for future in as_completed(future_map):
                                idx_asli, id_lembar, nama_file = future_map[future]
                                selesai_count += 1
                                try:
                                    hasil = future.result()
                                except Exception as exc_worker:
                                    hasil = {
                                        "status": "gagal",
                                        "error": str(exc_worker),
                                        "dari_cache": False,
                                    }

                                if not bool(hasil.get("dari_cache", False)):
                                    ada_panggilan_api_live = True

                                if hasil.get("status") == "gagal":
                                    pesan_err = f"{nama_file}: {hasil.get('error', 'Terjadi kesalahan API.')}"
                                    daftar_error.append(pesan_err)
                                    st.error(pesan_err)
                                else:
                                    hasil["id_lembar"] = id_lembar
                                    hasil["nama_file"] = nama_file
                                    hasil_terurut[idx_asli] = hasil

                                    label_sumber = (
                                        "Cache lokal"
                                        if hasil.get("dari_cache")
                                        else hasil.get("model_digunakan", provider_aktif)
                                    )
                                    waktu_str = f"{hasil.get('waktu_proses_detik', 0):.1f}s"
                                    tunggu_q = float(hasil.get("menunggu_kuota_detik") or 0)
                                    tanda_q = f" · auto-tunggu {tunggu_q:.0f}s" if tunggu_q >= 2.0 else ""
                                    tanda_fb = " [Fallback]" if hasil.get("fallback_digunakan") else ""
                                    tanda_val = " — Perlu Validasi Guru" if hasil.get("perlu_validasi_guru") else ""
                                    st.write(
                                        f"**[{selesai_count}/{total_lembar}]** `{nama_file}` → "
                                        f"**{hasil['nama_siswa']}** | Nilai: **{hasil['total_nilai']}** "
                                        f"(`{label_sumber}`{tanda_fb}, {waktu_str}{tanda_q}){tanda_val}"
                                    )

                                progress_bar.progress(
                                    min(1.0, selesai_count / total_lembar),
                                    text=f"Selesai {selesai_count}/{total_lembar} lembar...",
                                )

                        masih_ada_gelombang = idx_wave < len(gelombang_list)
                        if ada_panggilan_api_live and masih_ada_gelombang and jeda_detik > 0:
                            st.caption(f"Menunggu {jeda_detik} detik sebelum gelombang berikutnya...")
                            time.sleep(jeda_detik)
                finally:
                    if shared_http_client is not None:
                        shared_http_client.close()

                durasi_total = time.perf_counter() - mulai_batch
                hasil_batch = [hasil_terurut[k] for k in sorted(hasil_terurut.keys())]
                progress_bar.progress(1.0, text=f"Proses koreksi selesai dalam {durasi_total:.1f} detik.")

                if hasil_batch and not daftar_error:
                    status_box.update(
                        label=(
                            f"Koreksi selesai dalam {durasi_total:.1f} detik! "
                            f"{len(hasil_batch)} lembar berhasil dinilai."
                        ),
                        state="complete",
                    )
                elif hasil_batch and daftar_error:
                    status_box.update(
                        label=(
                            f"Selesai sebagian ({durasi_total:.1f} detik): "
                            f"{len(hasil_batch)} berhasil, {len(daftar_error)} gagal."
                        ),
                        state="complete",
                    )
                else:
                    status_box.update(
                        label="Proses koreksi gagal untuk seluruh lembar yang diunggah.",
                        state="error",
                    )

            if hasil_batch:
                st.session_state["gambar_siswa"].update(gambar_batch)
                st.session_state["hasil_koreksi"] = hasil_batch
                st.session_state["editor_version"] += 1
                st.success(
                    f"**{len(hasil_batch)} lembar jawaban** selesai dikoreksi dalam "
                    f"**{durasi_total:.1f} detik**. Buka tab **✅ Validasi Guru & Rekap Nilai** "
                    "untuk meninjau rincian per soal, mengedit nilai, atau mengunduh Excel.",
                    title="Koreksi otomatis selesai",
                )


# ===========================================================================
# TAB 3: VALIDASI GURU & REKAP NILAI
# ===========================================================================
with tab_validasi:
    hasil_koreksi: list[dict[str, Any]] = st.session_state.get("hasil_koreksi", [])

    if not hasil_koreksi:
        st.info(
            "Belum ada hasil koreksi yang tersedia. Silakan unggah lembar jawaban siswa "
            "dan jalankan proses koreksi otomatis pada tab **📝 Koreksi Lembar Jawaban** terlebih dahulu, "
            "atau klik tombol di bawah untuk langsung mencoba contoh hasil koreksi **SMK TKJ (Subnetting IPv4)** tanpa API Key.",
            title="Belum ada data penilaian",
        )
        st.button(
            "🎯 Muat Contoh Demo SMK TKJ (Tanpa API Key)",
            type="primary",
            key="btn_muat_demo_tab3",
            on_click=_muat_mode_demo_tkj,
        )
    else:
        notifikasi_val = st.session_state.pop("pesan_notifikasi_validasi", None)
        if notifikasi_val:
            st.success(notifikasi_val)

        # Slot metrik di bagian atas (diisi setelah st.data_editor agar selalu sinkron real-time)
        slot_metrik = st.container()

        st.subheader("Tabel rekap nilai (dapat diedit manual)")
        st.caption(
            "Guru dapat langsung mengubah nama, skor, status validasi, atau umpan balik "
            "di tabel berikut lalu klik **Simpan Perubahan Tabel** untuk menyimpan ke sesi."
        )

        editor_key = f"editor_rekap_nilai_v{st.session_state['editor_version']}"
        df_dasar = _buat_dataframe_rekap(hasil_koreksi)

        edited_df = st.data_editor(
            df_dasar,
            key=editor_key,
            hide_index=True,
            num_rows="fixed",
            width="stretch",
            alt="Tabel rekap nilai dan validasi guru hasil koreksi esai siswa",
            disabled=["nama_file", "model_digunakan", "dari_cache"],
            column_config={
                "nama_siswa": st.column_config.TextColumn("Nama Siswa", pinned=True),
                "nama_file": st.column_config.TextColumn("File Lembar"),
                "skor_konsep": st.column_config.NumberColumn(
                    "Konsep (0-40)", min_value=0, max_value=40, step=1
                ),
                "skor_langkah_perhitungan": st.column_config.NumberColumn(
                    "Langkah (0-40)", min_value=0, max_value=40, step=1
                ),
                "skor_hasil_dan_satuan": st.column_config.NumberColumn(
                    "Hasil & Satuan (0-20)", min_value=0, max_value=20, step=1
                ),
                "total_nilai": st.column_config.NumberColumn(
                    "Total Nilai", min_value=0, max_value=100, step=1
                ),
                "perlu_validasi_guru": st.column_config.CheckboxColumn("Perlu Validasi"),
                "alasan_validasi": st.column_config.TextColumn("Alasan Validasi"),
                "umpan_balik_siswa": st.column_config.TextColumn("Umpan Balik Siswa", width="large"),
                "model_digunakan": st.column_config.TextColumn("Model AI"),
                "dari_cache": st.column_config.CheckboxColumn("Cache"),
            },
        )

        keadaan_editor = st.session_state.get(editor_key) or {}
        baris_diedit = keadaan_editor.get("edited_rows") or {}
        hasil_sinkron = _gabungkan_edit_ke_hasil(hasil_koreksi, edited_df, baris_diedit)

        with st.container(horizontal=True, vertical_alignment="center"):
            if st.button(
                "💾 Simpan Perubahan Tabel",
                key="btn_simpan_edit_tabel",
                disabled=len(baris_diedit) == 0,
            ):
                st.session_state["hasil_koreksi"] = hasil_sinkron
                st.session_state["editor_version"] += 1
                st.session_state["pesan_notifikasi_validasi"] = (
                    "Perubahan manual pada tabel nilai berhasil disimpan."
                )
                st.rerun()
            if baris_diedit:
                st.caption(f"Terdapat perubahan belum disimpan pada {len(baris_diedit)} baris.")

        # Isi 3 Metrik Ringkasan di bagian atas Tab 3
        total_siswa = len(hasil_sinkron)
        rata_rata_kelas = (
            sum(item["total_nilai"] for item in hasil_sinkron) / total_siswa
            if total_siswa > 0
            else 0.0
        )
        jumlah_perlu_validasi = sum(
            1 for item in hasil_sinkron if item.get("perlu_validasi_guru")
        )

        with slot_metrik:
            col_m1, col_m2, col_m3 = st.columns(3)
            col_m1.metric(
                "Total Siswa Dikoreksi",
                f"{total_siswa} siswa",
                border=True,
                height="stretch",
            )
            col_m2.metric(
                "Rata-rata Nilai Kelas",
                f"{rata_rata_kelas:.1f}",
                border=True,
                height="stretch",
            )
            col_m3.metric(
                "Perlu Validasi Guru",
                f"{jumlah_perlu_validasi} lembar",
                border=True,
                height="stretch",
            )

        st.divider()

        # -------------------------------------------------------------------
        # Bagian Inspeksi Detail & Validasi Lembar
        # -------------------------------------------------------------------
        st.subheader("🔍 Inspeksi Detail & Validasi Lembar")

        indeks_terpilih = st.selectbox(
            "Pilih siswa yang ingin diperiksa secara detail",
            options=list(range(len(hasil_sinkron))),
            key="pilih_siswa_inspeksi",
            format_func=lambda idx: (
                f"{idx + 1}. {hasil_sinkron[idx]['nama_siswa']} "
                f"({hasil_sinkron[idx].get('nama_file', '-')}) — "
                f"Nilai: {hasil_sinkron[idx]['total_nilai']}"
                + (" [Perlu Validasi]" if hasil_sinkron[idx].get("perlu_validasi_guru") else "")
            ),
        )

        data_siswa = hasil_sinkron[indeks_terpilih]
        id_lembar_aktif = data_siswa.get("id_lembar", "")
        gambar_aktif = st.session_state.get("gambar_siswa", {}).get(id_lembar_aktif)

        col_foto, col_detail = st.columns([1, 1.25], gap="large")

        with col_foto:
            with st.container(border=True):
                st.markdown("**Foto lembar jawaban tulisan tangan**")
                if gambar_aktif is not None:
                    st.image(
                        gambar_aktif,
                        caption=f"{data_siswa['nama_siswa']} — {data_siswa.get('nama_file', '-')}",
                        alt=f"Foto lembar jawaban tulisan tangan siswa {data_siswa['nama_siswa']}",
                        width="stretch",
                    )
                else:
                    st.info("Gambar lembar jawaban untuk siswa ini tidak tersedia di sesi saat ini.")

        with col_detail:
            if data_siswa.get("perlu_validasi_guru"):
                st.warning(
                    data_siswa.get("alasan_validasi", "Memerlukan peninjauan manual guru."),
                    title="Perlu Validasi Guru",
                )
            else:
                st.success(
                    "Tulisan terbaca jelas dan penilaian konsisten dengan modul ajar serta rubrik.",
                    title="Tervalidasi Otomatis",
                )

            c_s1, c_s2, c_s3, c_s4 = st.columns(4)
            c_s1.metric("Konsep (/40)", str(data_siswa["skor_konsep"]), border=True, height="stretch")
            c_s2.metric(
                "Langkah (/40)",
                str(data_siswa["skor_langkah_perhitungan"]),
                border=True,
                height="stretch",
            )
            c_s3.metric(
                "Hasil (/20)",
                str(data_siswa["skor_hasil_dan_satuan"]),
                border=True,
                height="stretch",
            )
            c_s4.metric("Total (/100)", str(data_siswa["total_nilai"]), border=True, height="stretch")

            sumber_badge = "Cache lokal" if data_siswa.get("dari_cache") else "API langsung"
            prov_label = str(data_siswa.get("provider_digunakan", "-")).upper()
            waktu_info = (
                f" | Waktu: **{data_siswa['waktu_proses_detik']:.1f}s**"
                if "waktu_proses_detik" in data_siswa
                else ""
            )
            st.caption(
                f"Provider: `{prov_label}` | Model: `{data_siswa.get('model_digunakan', '-')}` | "
                f"Sumber: **{sumber_badge}**{waktu_info}"
            )

            # Jika multi-soal, tampilkan rincian penilaian per nomor soal secara rapi
            rincian_soal = data_siswa.get("rincian_per_soal") or []
            if len(rincian_soal) > 1:
                st.markdown("**Rincian penilaian per nomor soal**")
                for item_r in rincian_soal:
                    with st.container(border=True):
                        st.markdown(
                            f"**Soal No. {item_r['nomor_soal']}** — "
                            f":blue-badge[Skor: {item_r['skor_diperoleh']} / {item_r['skor_maksimal']}]"
                        )
                        st.markdown(item_r.get("transkripsi_latex", "_Tidak ada transkripsi._"))
                        st.caption(f"Analisis: {item_r.get('analisis_langkah', '-')}")
            else:
                with st.container(border=True):
                    st.markdown("**Transkripsi jawaban & rumus (Markdown / LaTeX)**")
                    st.markdown(
                        data_siswa.get("transkripsi_jawaban_latex", "_Tidak ada transkripsi._")
                    )

                with st.container(border=True):
                    st.markdown("**Analisis langkah pengerjaan**")
                    st.markdown(data_siswa.get("analisis_langkah", "-"))

            with st.container(border=True):
                st.markdown("**Umpan balik untuk siswa**")
                st.markdown(data_siswa.get("umpan_balik_siswa", "-"))

            # Tombol Audit Ulang (Provider Aktif & Gemini 4 Neon)
            daftar_soal_audit = st.session_state.get("daftar_soal_terakhir") or [
                {
                    "nomor": 1,
                    "pertanyaan": DEFAULT_SOAL,
                    "rubrik": DEFAULT_RUBRIK,
                    "bobot": 100,
                }
            ]

            col_aud1, col_aud2 = st.columns(2)
            label_audit_aktif = f"🔄 Audit Ulang ({provider_aktif.upper()})"
            if col_aud1.button(
                label_audit_aktif,
                key=f"btn_audit_provider_{id_lembar_aktif}_{indeks_terpilih}",
                width="stretch",
                disabled=gambar_aktif is None,
            ):
                if info_prov["butuh_api_key"] and not _api_key_valid(api_key_aktif):
                    st.error(
                        f"Masukkan `{info_prov['env_var']}` yang valid pada sidebar terlebih dahulu.",
                        title=f"{info_prov['env_var']} belum tersedia",
                    )
                else:
                    model_audit = model_aktif
                    with st.spinner(
                        f"Mengaudit ulang lembar {data_siswa['nama_siswa']} dengan {provider_aktif.upper()} ({model_audit})..."
                    ):
                        hasil_audit = koreksi_satu_lembar(
                            image_obj=gambar_aktif,
                            soal="",
                            rubrik_guru="",
                            api_key=api_key_aktif,
                            mode_audit_neon=False,
                            abaikan_cache=True,
                            mode_kecepatan="teliti",
                            daftar_soal=daftar_soal_audit,
                            provider=provider_aktif,
                            model_override=model_audit,
                            base_url=ollama_url_aktif,
                        )

                    if hasil_audit.get("status") == "gagal":
                        st.error(
                            hasil_audit.get("error", "Gagal menjalankan audit ulang."),
                            title="Audit ulang gagal",
                        )
                    else:
                        hasil_audit["id_lembar"] = id_lembar_aktif
                        hasil_audit["nama_file"] = data_siswa.get("nama_file", "-")
                        daftar_diperbarui = list(hasil_sinkron)
                        daftar_diperbarui[indeks_terpilih] = hasil_audit
                        st.session_state["hasil_koreksi"] = daftar_diperbarui
                        st.session_state["editor_version"] += 1
                        st.session_state["pesan_notifikasi_validasi"] = (
                            f"Audit ulang ({provider_aktif.upper()} / {hasil_audit['model_digunakan']}) untuk "
                            f"**{hasil_audit['nama_siswa']}** selesai (Nilai terbaru: **{hasil_audit['total_nilai']}**)."
                        )
                        st.rerun()

            if col_aud2.button(
                "🧠 Audit Ulang dengan Gemini 4 Neon (Paid Tier)",
                key=f"btn_audit_neon_{id_lembar_aktif}_{indeks_terpilih}",
                width="stretch",
                disabled=gambar_aktif is None,
            ):
                gemini_key, _ = _ambil_api_key_efektif(
                    "GEMINI_API_KEY",
                    st.session_state.get("gemini_api_key_input", ""),
                )
                if not _api_key_valid(gemini_key):
                    st.error(
                        "Masukkan `GEMINI_API_KEY` (Paid Tier) di sidebar (pilih Provider Google Gemini) atau di `.env`.",
                        title="GEMINI_API_KEY belum tersedia",
                    )
                else:
                    with st.spinner(
                        f"Menjalankan audit mendalam Gemini 4 Neon untuk {data_siswa['nama_siswa']}..."
                    ):
                        hasil_neon = koreksi_satu_lembar(
                            image_obj=gambar_aktif,
                            soal="",
                            rubrik_guru="",
                            api_key=gemini_key,
                            mode_audit_neon=True,
                            abaikan_cache=True,
                            daftar_soal=daftar_soal_audit,
                        )

                    if hasil_neon.get("status") == "gagal":
                        st.error(
                            hasil_neon.get("error", "Gagal menjalankan audit Gemini 4 Neon."),
                            title="Audit Gemini 4 Neon gagal",
                        )
                    else:
                        hasil_neon["id_lembar"] = id_lembar_aktif
                        hasil_neon["nama_file"] = data_siswa.get("nama_file", "-")
                        daftar_diperbarui = list(hasil_sinkron)
                        daftar_diperbarui[indeks_terpilih] = hasil_neon
                        st.session_state["hasil_koreksi"] = daftar_diperbarui
                        st.session_state["editor_version"] += 1
                        st.session_state["pesan_notifikasi_validasi"] = (
                            f"Audit mendalam Gemini 4 Neon untuk **{hasil_neon['nama_siswa']}** "
                            f"selesai (Nilai terbaru: **{hasil_neon['total_nilai']}**)."
                        )
                        st.rerun()

        st.divider()

        # -------------------------------------------------------------------
        # Ekspor & Unduh Rekap Nilai Excel (.xlsx)
        # -------------------------------------------------------------------
        df_ekspor = _buat_dataframe_ekspor(hasil_sinkron)
        nama_file_download = _nama_file_excel_unduhan(nama_ujian)

        def _bangun_excel_bytes() -> bytes:
            path_excel = ekspor_ke_excel(df_ekspor, nama_ujian)
            return Path(path_excel).read_bytes()

        st.download_button(
            label="📥 Unduh Rekap Nilai Excel (.xlsx)",
            data=_bangun_excel_bytes,
            file_name=nama_file_download,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            key="btn_unduh_excel",
            width="stretch",
        )
        st.caption(
            "Saat diunduh, salinan rekap nilai juga otomatis diarsipkan di folder "
            "`./data/hasil_penilaian/`."
        )

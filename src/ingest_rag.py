"""Modul ingest dan pencarian RAG lokal berbasis ChromaDB untuk SIDIK-AI.

Memproses dokumen PDF modul ajar ke dalam ChromaDB lokal menggunakan fungsi
embedding default ChromaDB (SentenceTransformer / all-MiniLM-L6-v2 lokal)
sehingga berjalan offline dan tanpa biaya API.
"""

from __future__ import annotations

import hashlib
import re
import threading
from pathlib import Path
from typing import Any

import chromadb
from pypdf import PdfReader

VECTOR_DB_PATH = "./vector_db"
COLLECTION_NAME = "modul_sidik_ai"
DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 150
UPSERT_BATCH_SIZE = 100

_COLLECTION_CACHE: dict[tuple[str, str], chromadb.Collection] = {}
_CACHE_LOCK = threading.Lock()


def reset_cache_koleksi() -> None:
    """Mengosongkan cache koneksi koleksi ChromaDB di memori."""
    with _CACHE_LOCK:
        _COLLECTION_CACHE.clear()


def _get_collection(
    db_path: str | None = None,
    collection_name: str = COLLECTION_NAME,
) -> chromadb.Collection:
    """Membuka (atau memakai ulang) koneksi ChromaDB persisten untuk koleksi modul."""
    target_path = db_path if db_path is not None else VECTOR_DB_PATH
    resolved_path = str(Path(target_path).resolve())
    kunci_cache = (resolved_path, collection_name)

    with _CACHE_LOCK:
        koleksi = _COLLECTION_CACHE.get(kunci_cache)
        if koleksi is not None:
            return koleksi

        Path(target_path).mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=target_path)
        # Tanpa parameter embedding_function, ChromaDB otomatis menggunakan
        # DefaultEmbeddingFunction lokal (all-MiniLM-L6-v2 via ONNX Runtime).
        koleksi = client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        _COLLECTION_CACHE[kunci_cache] = koleksi
        return koleksi


def _bersihkan_teks(teks: str) -> str:
    """Merapikan spasi berlebih sambil menjaga baris baru dan simbol rumus."""
    teks = teks.replace("\r\n", "\n").replace("\r", "\n")
    baris_bersih = [re.sub(r"[ \t]+", " ", baris).strip() for baris in teks.split("\n")]
    teks_gabung = "\n".join(baris_bersih)
    teks_gabung = re.sub(r"\n{3,}", "\n\n", teks_gabung)
    return teks_gabung.strip()


def _pecah_teks_menjadi_chunks(
    teks: str,
    ukuran_chunk: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    """Memecah teks menjadi potongan ~ukuran_chunk karakter dengan overlap."""
    if ukuran_chunk <= 0:
        raise ValueError("ukuran_chunk harus lebih besar dari 0.")
    if overlap < 0 or overlap >= ukuran_chunk:
        raise ValueError("overlap harus bernilai >= 0 dan lebih kecil dari ukuran_chunk.")

    teks = _bersihkan_teks(teks)
    if not teks:
        return []
    if len(teks) <= ukuran_chunk:
        return [teks]

    chunks: list[str] = []
    panjang_teks = len(teks)
    start = 0
    batas_cari_mundur = int(ukuran_chunk * 0.25)

    while start < panjang_teks:
        target_end = min(start + ukuran_chunk, panjang_teks)
        end = target_end

        # Jika belum di akhir teks, coba potong di batas paragraf/baris/kalimat/kata
        if target_end < panjang_teks:
            batas_awal_cari = max(start + 1, target_end - batas_cari_mundur)
            potongan_cari = teks[batas_awal_cari:target_end]
            for pemisah in ("\n\n", "\n", ". ", " "):
                pos = potongan_cari.rfind(pemisah)
                if pos != -1:
                    kandidat_end = batas_awal_cari + pos + len(pemisah)
                    if kandidat_end > start:
                        end = kandidat_end
                        break

        chunk = teks[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= panjang_teks:
            break

        next_start = max(end - overlap, start + 1)
        start = next_start

    return chunks


def _buat_chunk_id(nama_file: str, halaman: int, chunk_index: int) -> str:
    """Membuat ID unik deterministik berbasis hash nama file, halaman, dan urutan chunk."""
    kunci = f"{nama_file}::halaman_{halaman}::chunk_{chunk_index}"
    digest = hashlib.sha256(kunci.encode("utf-8")).hexdigest()[:24]
    return f"doc_{digest}"


def proses_pdf_ke_vectordb(folder_pdf: str = "./data/modul_ajar") -> dict[str, Any]:
    """Membaca seluruh PDF di folder_pdf, memecah teks, dan mengindeks ke ChromaDB.

    Args:
        folder_pdf: Path folder yang berisi file-file PDF modul ajar.

    Returns:
        Dictionary ringkasan hasil indeksasi (jumlah file, jumlah chunks, daftar file, pesan).
    """
    folder_path = Path(folder_pdf)
    if not folder_path.exists() or not folder_path.is_dir():
        return {
            "jumlah_file": 0,
            "jumlah_chunks": 0,
            "total_chunks_di_db": 0,
            "file_diproses": [],
            "file_gagal": [],
            "pesan": f"Folder '{folder_pdf}' tidak ditemukan.",
        }

    daftar_pdf = sorted(
        (p for p in folder_path.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"),
        key=lambda p: p.name.lower(),
    )

    collection = _get_collection()

    if not daftar_pdf:
        return {
            "jumlah_file": 0,
            "jumlah_chunks": 0,
            "total_chunks_di_db": collection.count(),
            "file_diproses": [],
            "file_gagal": [],
            "pesan": f"Tidak ditemukan file PDF di folder '{folder_pdf}'.",
        }

    file_diproses: list[str] = []
    file_gagal: list[dict[str, str]] = []
    total_chunks_terindeks = 0

    for pdf_path in daftar_pdf:
        nama_file = pdf_path.name
        try:
            reader = PdfReader(str(pdf_path))
            ids_file: list[str] = []
            docs_file: list[str] = []
            metadatas_file: list[dict[str, Any]] = []

            for nomor_halaman, halaman in enumerate(reader.pages, start=1):
                teks_halaman = halaman.extract_text() or ""
                chunks = _pecah_teks_menjadi_chunks(
                    teks_halaman,
                    ukuran_chunk=DEFAULT_CHUNK_SIZE,
                    overlap=DEFAULT_CHUNK_OVERLAP,
                )
                for idx_chunk, isi_chunk in enumerate(chunks):
                    ids_file.append(_buat_chunk_id(nama_file, nomor_halaman, idx_chunk))
                    docs_file.append(isi_chunk)
                    metadatas_file.append(
                        {
                            "nama_file": nama_file,
                            "halaman": nomor_halaman,
                        }
                    )

            if not docs_file:
                file_gagal.append(
                    {
                        "nama_file": nama_file,
                        "alasan": "Tidak ada teks yang dapat diekstrak dari PDF.",
                    }
                )
                continue

            # Hapus entri lama dari file yang sama (jika ada) agar pembaruan file
            # tidak menyisakan chunk usang, lalu upsert dengan ID deterministik.
            if collection.count() > 0:
                collection.delete(where={"nama_file": nama_file})

            for i in range(0, len(docs_file), UPSERT_BATCH_SIZE):
                collection.upsert(
                    ids=ids_file[i : i + UPSERT_BATCH_SIZE],
                    documents=docs_file[i : i + UPSERT_BATCH_SIZE],
                    metadatas=metadatas_file[i : i + UPSERT_BATCH_SIZE],
                )

            file_diproses.append(nama_file)
            total_chunks_terindeks += len(docs_file)
        except Exception as exc:
            file_gagal.append({"nama_file": nama_file, "alasan": str(exc)})

    total_di_db = collection.count()
    pesan = (
        f"Berhasil mengindeks {len(file_diproses)} file PDF "
        f"({total_chunks_terindeks} potongan teks). "
        f"Total potongan tersimpan di database: {total_di_db}."
    )
    if file_gagal:
        pesan += f" ({len(file_gagal)} file dilewati/gagal)."

    return {
        "jumlah_file": len(file_diproses),
        "jumlah_chunks": total_chunks_terindeks,
        "total_chunks_di_db": total_di_db,
        "file_diproses": file_diproses,
        "file_gagal": file_gagal,
        "pesan": pesan,
    }


def cari_konteks_materi(pertanyaan_soal: str, n_results: int = 3) -> str:
    """Mencari potongan materi paling relevan dari ChromaDB berdasarkan pertanyaan soal.

    Args:
        pertanyaan_soal: Teks soal atau topik eksakta yang ingin dicari referensinya.
        n_results: Jumlah maksimal potongan materi yang diambil.

    Returns:
        String referensi materi terformat beserta sumber file dan halaman, atau
        pemberitahuan jika database masih kosong.
    """
    if not pertanyaan_soal or not pertanyaan_soal.strip():
        return "Pertanyaan soal kosong. Masukkan pertanyaan atau topik materi untuk dicari."

    collection = _get_collection()
    total_dokumen = collection.count()

    if total_dokumen == 0:
        return (
            "Belum ada modul PDF yang diindeks di database vektor. "
            "Silakan tambahkan file PDF modul ajar ke folder './data/modul_ajar' "
            "lalu jalankan proses indeksasi terlebih dahulu."
        )

    jumlah_hasil = min(max(1, n_results), total_dokumen)
    hasil = collection.query(
        query_texts=[pertanyaan_soal.strip()],
        n_results=jumlah_hasil,
        include=["documents", "metadatas"],
    )

    dokumen_list = (hasil.get("documents") or [[]])[0]
    metadata_list = (hasil.get("metadatas") or [[]])[0]

    if not dokumen_list:
        return "Tidak ditemukan potongan materi yang relevan di database vektor."

    bagian_referensi: list[str] = []
    for idx, (teks, meta) in enumerate(zip(dokumen_list, metadata_list), start=1):
        meta = meta or {}
        nama_file = meta.get("nama_file", "Tidak diketahui")
        halaman = meta.get("halaman", "-")
        header = f"[Referensi {idx} | Sumber: {nama_file} | Halaman: {halaman}]"
        bagian_referensi.append(f"{header}\n{teks.strip()}")

    return "\n\n---\n\n".join(bagian_referensi)


def cari_konteks_multi_soal(
    daftar_soal: list[dict[str, Any]],
    n_results_per_soal: int = 2,
) -> str:
    """Mencari konteks RAG 1x untuk seluruh daftar soal dan melakukan deduplikasi potongan.

    Cocok dipanggil sekali sebelum koreksi batch paralel agar embedding/pencarian lokal
    tidak diulang berkali-kali untuk setiap lembar siswa.
    """
    pertanyaan_valid = [
        str(item.get("pertanyaan", "")).strip()
        for item in (daftar_soal or [])
        if str(item.get("pertanyaan", "")).strip()
    ]
    if not pertanyaan_valid:
        return "Pertanyaan soal kosong. Masukkan pertanyaan atau topik materi untuk dicari."

    if len(pertanyaan_valid) == 1:
        return cari_konteks_materi(pertanyaan_valid[0], n_results=max(3, n_results_per_soal))

    collection = _get_collection()
    total_dokumen = collection.count()
    if total_dokumen == 0:
        return (
            "Belum ada modul PDF yang diindeks di database vektor. "
            "Silakan tambahkan file PDF modul ajar ke folder './data/modul_ajar' "
            "lalu jalankan proses indeksasi terlebih dahulu."
        )

    jumlah_hasil = min(max(1, n_results_per_soal), total_dokumen)
    hasil = collection.query(
        query_texts=pertanyaan_valid,
        n_results=jumlah_hasil,
        include=["documents", "metadatas"],
    )

    ids_per_query = hasil.get("ids") or []
    docs_per_query = hasil.get("documents") or []
    metas_per_query = hasil.get("metadatas") or []

    terlihat: set[str] = set()
    bagian_referensi: list[str] = []
    urutan = 1

    for q_ids, q_docs, q_metas in zip(ids_per_query, docs_per_query, metas_per_query):
        for doc_id, teks, meta in zip(q_ids, q_docs, q_metas):
            if doc_id in terlihat:
                continue
            terlihat.add(doc_id)
            meta = meta or {}
            nama_file = meta.get("nama_file", "Tidak diketahui")
            halaman = meta.get("halaman", "-")
            header = f"[Referensi {urutan} | Sumber: {nama_file} | Halaman: {halaman}]"
            bagian_referensi.append(f"{header}\n{teks.strip()}")
            urutan += 1

    if not bagian_referensi:
        return "Tidak ditemukan potongan materi yang relevan di database vektor."

    return "\n\n---\n\n".join(bagian_referensi)

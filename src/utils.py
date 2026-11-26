"""Modul utilitas gambar dan ekspor laporan Excel untuk SIDIK-AI."""

from __future__ import annotations

import io
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from PIL import Image, ImageOps

HASIL_PENILAIAN_DIR = "./data/hasil_penilaian"


def _konversi_ke_rgb(img: Image.Image) -> Image.Image:
    """Mengonversi gambar PIL ke mode RGB dengan aman (latar putih jika ada transparansi)."""
    if img.mode == "RGB":
        return img.copy()

    memiliki_alpha = (
        img.mode in ("RGBA", "LA")
        or (img.mode == "P" and "transparency" in img.info)
    )
    if memiliki_alpha:
        rgba = img.convert("RGBA")
        latar_putih = Image.new("RGB", rgba.size, (255, 255, 255))
        latar_putih.paste(rgba, mask=rgba.getchannel("A"))
        return latar_putih

    return img.convert("RGB")


def kompres_dan_muat_gambar(file_input: Any, max_width: int = 1280) -> Image.Image:
    """Memuat gambar, memperbaiki orientasi EXIF, mengubah ukuran proporsional, dan konversi RGB.

    Mendukung input berupa path file (`str` / `Path`), objek `UploadedFile` Streamlit,
    stream file biner (`BytesIO`/file-like), `bytes`, maupun `PIL.Image.Image`.

    Args:
        file_input: Sumber gambar yang akan dimuat.
        max_width: Lebar maksimum gambar hasil (piksel). Default 1280.

    Returns:
        Objek `PIL.Image.Image` dalam mode `"RGB"` yang tajam dan sudah terorientasi benar.
    """
    if max_width <= 0:
        raise ValueError("max_width harus lebih besar dari 0.")

    if isinstance(file_input, Image.Image):
        img = file_input.copy()
    elif isinstance(file_input, (bytes, bytearray)):
        with Image.open(io.BytesIO(file_input)) as dibuka:
            dibuka.load()
            img = dibuka.copy()
    elif isinstance(file_input, (str, Path)):
        path_file = Path(file_input)
        if not path_file.exists():
            raise FileNotFoundError(f"File gambar tidak ditemukan: {path_file}")
        with Image.open(path_file) as dibuka:
            dibuka.load()
            img = dibuka.copy()
    elif hasattr(file_input, "read"):
        # Menangani Streamlit UploadedFile atau file-like stream lainnya
        if hasattr(file_input, "seek"):
            file_input.seek(0)
        data_bytes = file_input.read()
        if hasattr(file_input, "seek"):
            file_input.seek(0)
        with Image.open(io.BytesIO(data_bytes)) as dibuka:
            dibuka.load()
            img = dibuka.copy()
    else:
        raise TypeError(
            "file_input harus berupa path file (str/Path), Streamlit UploadedFile, "
            "bytes, atau objek PIL.Image.Image."
        )

    # Perbaiki orientasi otomatis berdasarkan metadata EXIF kamera HP
    img = ImageOps.exif_transpose(img)

    # Konversi ke mode RGB secara aman
    img = _konversi_ke_rgb(img)

    # Ubah ukuran secara proporsional jika lebar melebihi max_width
    lebar, tinggi = img.size
    if lebar > max_width:
        rasio = max_width / float(lebar)
        tinggi_baru = max(1, round(tinggi * rasio))
        img = img.resize((max_width, tinggi_baru), Image.Resampling.LANCZOS)

    return img


def gambar_ke_jpeg_bytes(
    image_obj: Image.Image,
    quality: int = 85,
    max_width: int = 1024,
) -> bytes:
    """Mengonversi gambar PIL ke payload JPEG ringan untuk upload cepat ke Gemini API.

    Menghindari konversi default PNG yang besar (2-4 MB) sehingga pengiriman ke API
    jauh lebih cepat (~120-250 KB) namun tulisan tangan & simbol matematika tetap tajam.
    """
    if max_width <= 0:
        raise ValueError("max_width harus lebih besar dari 0.")
    if not (1 <= quality <= 100):
        raise ValueError("quality harus berada di rentang 1 sampai 100.")

    img = _konversi_ke_rgb(image_obj)
    lebar, tinggi = img.size
    if lebar > max_width:
        rasio = max_width / float(lebar)
        tinggi_baru = max(1, round(tinggi * rasio))
        img = img.resize((max_width, tinggi_baru), Image.Resampling.LANCZOS)

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()


def _bersihkan_nama_file(nama: str) -> str:
    """Membersihkan teks nama ujian agar aman dipakai sebagai nama file."""
    nama_bersih = re.sub(r"[^\w\s-]", "", (nama or "").strip())
    nama_bersih = re.sub(r"[\s]+", "_", nama_bersih)
    nama_bersih = nama_bersih.strip("_-")
    return nama_bersih or "Ujian"


def ekspor_ke_excel(dataframe: pd.DataFrame, nama_ujian: str) -> str:
    """Menyimpan DataFrame rekap penilaian ke file Excel berstempel waktu.

    File disimpan di folder `./data/hasil_penilaian/` dengan format:
    `Rekap_SIDIK_AI_[nama_ujian]_[timestamp].xlsx`.

    Args:
        dataframe: DataFrame pandas berisi rekap hasil koreksi siswa.
        nama_ujian: Nama/judul ujian untuk penamaan file.

    Returns:
        Path file Excel yang telah disimpan sebagai string.
    """
    if not isinstance(dataframe, pd.DataFrame):
        raise TypeError("Parameter 'dataframe' harus berupa objek pandas.DataFrame.")

    folder_output = Path(HASIL_PENILAIAN_DIR)
    folder_output.mkdir(parents=True, exist_ok=True)

    nama_aman = _bersihkan_nama_file(nama_ujian)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    nama_file = f"Rekap_SIDIK_AI_{nama_aman}_{timestamp}.xlsx"
    output_path = folder_output / nama_file

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        sheet_name = "Rekap_Nilai"
        dataframe.to_excel(writer, index=False, sheet_name=sheet_name)
        ws = writer.sheets[sheet_name]

        # Styling header & lebar kolom agar rapi saat dibuka guru di Excel
        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
        header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell_align = Alignment(vertical="top", wrap_text=True)

        for col_idx, col_name in enumerate(dataframe.columns, start=1):
            header_cell = ws.cell(row=1, column=col_idx)
            header_cell.font = header_font
            header_cell.fill = header_fill
            header_cell.alignment = header_align

            # Hitung lebar kolom ideal dengan batas minimum 14 dan maksimum 55
            panjang_maks = len(str(col_name))
            for row_idx in range(2, len(dataframe) + 2):
                cell = ws.cell(row=row_idx, column=col_idx)
                cell.alignment = cell_align
                if cell.value is not None:
                    baris_terpanjang = max(
                        (len(b) for b in str(cell.value).splitlines()),
                        default=0,
                    )
                    panjang_maks = max(panjang_maks, baris_terpanjang)

            lebar_kolom = min(max(panjang_maks + 4, 14), 55)
            ws.column_dimensions[get_column_letter(col_idx)].width = lebar_kolom

        ws.freeze_panes = "A2"

    return str(output_path)

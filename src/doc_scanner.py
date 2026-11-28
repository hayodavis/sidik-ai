"""Mesin pemindai & peningkat kualitas dokumen (Document Scanner) untuk SIDIK-AI.

Mengubah foto lembar jawaban kamera HP yang miring, redup, atau berbayang menjadi
hasil pindaian setajam scanner meja dengan 3 mode utama (mirip kamera Mode Dokumen):
- `ditingkatkan`: Penghapusan bayangan kertas + kertas putih bersih + tinta warna tetap tajam.
- `hp`: Hitam & Putih kontras tinggi (tulisan pensil/pulpen tetap utuh, latar kertas putih murni).
- `asli`: Warna asli tanpa filter (hanya perbaikan orientasi EXIF & opsional crop/rotasi).

Menggunakan OpenCV (`opencv-python-headless`) untuk deteksi tepi kertas otomatis
(perspective warp) dan pemulihan pencahayaan, dengan fallback aman berbasis NumPy/Pillow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

try:
    import cv2

    HAS_OPENCV = True
except ImportError:  # pragma: no cover - fallback jika OpenCV tidak terpasang
    cv2 = None  # type: ignore[assignment]
    HAS_OPENCV = False

ModeScanDokumen = Literal["ditingkatkan", "hp", "asli"]

LABEL_MODE_SCAN: dict[str, str] = {
    "asli": "Asli",
    "hp": "H&P",
    "ditingkatkan": "Ditingkatkan",
}


@dataclass(frozen=True)
class HasilScanDokumen:
    """Hasil pemrosesan pemindai dokumen beserta metadata ringkas."""

    gambar: Image.Image
    mode: str
    auto_cropped: bool
    sudut_terdeteksi: list[tuple[int, int]] | None = None


def _konversi_pil_ke_rgb(img: Image.Image) -> Image.Image:
    """Memastikan gambar PIL berformat RGB bersih dan sudah ter-transpose EXIF."""
    img = ImageOps.exif_transpose(img)
    if img.mode == "RGB":
        return img.copy()
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        latar = Image.new("RGB", rgba.size, (255, 255, 255))
        latar.paste(rgba, mask=rgba.getchannel("A"))
        return latar
    return img.convert("RGB")


def _urutkan_titik_sudut(pts: np.ndarray) -> np.ndarray:
    """Mengurutkan 4 titik sudut segi empat menjadi [kiri-atas, kanan-atas, kanan-bawah, kiri-bawah]."""
    rect = np.zeros((4, 2), dtype="float32")
    jumlah = pts.sum(axis=1)
    rect[0] = pts[np.argmin(jumlah)]
    rect[2] = pts[np.argmax(jumlah)]
    selisih = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(selisih)]
    rect[3] = pts[np.argmax(selisih)]
    return rect


def _sudut_segiempat_wajar(rect: np.ndarray) -> bool:
    """Memeriksa apakah keempat sudut segi empat wajar seperti lembar kertas (48°–132°)."""
    for i in range(4):
        p_prev = rect[(i - 1) % 4]
        p_curr = rect[i]
        p_next = rect[(i + 1) % 4]
        v1 = p_prev - p_curr
        v2 = p_next - p_curr
        n1 = float(np.linalg.norm(v1))
        n2 = float(np.linalg.norm(v2))
        if n1 < 1e-3 or n2 < 1e-3:
            return False
        cos_theta = float(np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0))
        derajat = float(np.degrees(np.arccos(cos_theta)))
        if derajat < 48.0 or derajat > 132.0:
            return False
    return True


def _deteksi_sudut_kertas_cv2(bgr: np.ndarray) -> np.ndarray | None:
    """Mendeteksi 4 sudut tepi lembar kertas secara aman menggunakan multi-kandidat kontur."""
    if not HAS_OPENCV or cv2 is None:
        return None

    h_asli, w_asli = bgr.shape[:2]
    skala_maks = 640.0
    skala = min(1.0, skala_maks / max(h_asli, w_asli))
    w_kecil = max(1, int(round(w_asli * skala)))
    h_kecil = max(1, int(round(h_asli * skala)))
    kecil = cv2.resize(bgr, (w_kecil, h_kecil), interpolation=cv2.INTER_AREA)

    luas_total = float(w_kecil * h_kecil)
    gray = cv2.cvtColor(kecil, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(kecil, cv2.COLOR_BGR2HSV)
    val = hsv[:, :, 2]

    # Kumpulkan kandidat peta tepi: Canny pada grayscale halus + Canny pada V channel + threshold kertas terang
    kandidat_peta: list[np.ndarray] = []

    blur_g = cv2.bilateralFilter(gray, 9, 75, 75)
    for lo, hi in ((40, 130), (65, 180)):
        tepi = cv2.Canny(blur_g, lo, hi)
        tepi = cv2.dilate(tepi, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)), iterations=1)
        tepi = cv2.morphologyEx(
            tepi,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9)),
        )
        kandidat_peta.append(tepi)

    # Kandidat pemisahan kertas terang vs meja lebih gelap/berwarna
    blur_v = cv2.GaussianBlur(val, (7, 7), 0)
    _, thresh_otsu = cv2.threshold(blur_v, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    thresh_otsu = cv2.morphologyEx(
        thresh_otsu,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15)),
    )
    thresh_otsu = cv2.morphologyEx(
        thresh_otsu,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7)),
    )
    kandidat_peta.append(thresh_otsu)

    terbaik_pts: np.ndarray | None = None
    skor_terbaik = 0.0

    for peta in kandidat_peta:
        kontur_list, _ = cv2.findContours(peta, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        kontur_list = sorted(kontur_list, key=cv2.contourArea, reverse=True)[:6]

        for cnt in kontur_list:
            luas = float(cv2.contourArea(cnt))
            rasio_luas = luas / luas_total
            # Abaikan kontur terlalu kecil (<24% frame) atau nyaris 100% tepi gambar (>96%)
            if rasio_luas < 0.24 or rasio_luas > 0.96:
                continue

            keliling = cv2.arcLength(cnt, True)
            if keliling <= 0:
                continue

            for eps in (0.02, 0.03, 0.04):
                approx = cv2.approxPolyDP(cnt, eps * keliling, True)
                if len(approx) != 4 or not cv2.isContourConvex(approx):
                    continue

                rect = _urutkan_titik_sudut(approx.reshape(4, 2).astype("float32"))
                if not _sudut_segiempat_wajar(rect):
                    continue

                # Pastikan keempat sisi cukup panjang agar tidak memotong tipis sebagian teks
                sisi = [
                    float(np.linalg.norm(rect[(i + 1) % 4] - rect[i]))
                    for i in range(4)
                ]
                if min(sisi) < 0.28 * min(w_kecil, h_kecil):
                    continue

                # Beri bobot sedikit lebih tinggi untuk kertas berarea luas & bentuk mendekati persegi panjang
                rasio_atas_bawah = min(sisi[0], sisi[2]) / max(sisi[0], sisi[2], 1.0)
                rasio_kiri_kanan = min(sisi[1], sisi[3]) / max(sisi[1], sisi[3], 1.0)
                skor = rasio_luas * (0.5 + 0.25 * rasio_atas_bawah + 0.25 * rasio_kiri_kanan)

                if skor > skor_terbaik:
                    skor_terbaik = skor
                    terbaik_pts = rect / skala
                break

    if terbaik_pts is None:
        return None

    # Beri sedikit margin keluar (~1.2%) agar tulisan dekat tepi kertas tidak ikut terpotong
    pusat = terbaik_pts.mean(axis=0, keepdims=True)
    diperluas = pusat + (terbaik_pts - pusat) * 1.018
    diperluas[:, 0] = np.clip(diperluas[:, 0], 0, w_asli - 1)
    diperluas[:, 1] = np.clip(diperluas[:, 1], 0, h_asli - 1)
    return diperluas.astype("float32")


def _luruskan_perspektif_cv2(bgr: np.ndarray, rect: np.ndarray) -> np.ndarray:
    """Melakukan warp perspektif 4 titik sehingga lembar kertas menjadi tegak lurus penuh."""
    assert cv2 is not None
    tl, tr, br, bl = rect
    lebar_bawah = float(np.linalg.norm(br - bl))
    lebar_atas = float(np.linalg.norm(tr - tl))
    lebar_maks = max(100, int(round(max(lebar_bawah, lebar_atas))))

    tinggi_kanan = float(np.linalg.norm(tr - br))
    tinggi_kiri = float(np.linalg.norm(tl - bl))
    tinggi_maks = max(100, int(round(max(tinggi_kanan, tinggi_kiri))))

    tujuan = np.array(
        [
            [0, 0],
            [lebar_maks - 1, 0],
            [lebar_maks - 1, tinggi_maks - 1],
            [0, tinggi_maks - 1],
        ],
        dtype="float32",
    )
    matriks = cv2.getPerspectiveTransform(rect, tujuan)
    return cv2.warpPerspective(
        bgr,
        matriks,
        (lebar_maks, tinggi_maks),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def _normalisasi_pencahayaan_l(l_channel: np.ndarray) -> np.ndarray:
    """Menghapus bayangan & pencahayaan tak merata pada kertas melalui pembagian latar lokal."""
    assert cv2 is not None
    h, w = l_channel.shape[:2]
    # Ukuran kernel cukup besar untuk melampaui ketebalan huruf/garis tabel, tetapi mengikuti gradien bayangan
    k_morph = max(21, int(min(h, w) // 22) | 1)
    k_morph = min(k_morph, 61)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_morph, k_morph))

    # Morphological closing menghilangkan goresan tinta gelap sehingga tersisa estimasi warna kertas
    bg = cv2.morphologyEx(l_channel, cv2.MORPH_CLOSE, kernel)
    k_blur = max(25, (k_morph * 2 + 1) | 1)
    bg = cv2.GaussianBlur(bg, (k_blur, k_blur), 0)

    # Division normalization: mengembalikan latar kertas berbayang menjadi putih seragam
    l_float = l_channel.astype(np.float32)
    bg_float = np.maximum(bg.astype(np.float32), 20.0)
    norm = np.clip((l_float / bg_float) * 255.0, 0.0, 255.0)
    return norm


def _tingkatkan_warna_dokumen_cv2(bgr: np.ndarray) -> np.ndarray:
    """Mode 'Ditingkatkan': kertas putih bersih tanpa bayangan, tinta tulisan & warna tetap tajam."""
    assert cv2 is not None
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    l_ch, a_ch, b_ch = cv2.split(lab)

    # 1. Hapus bayangan tak merata pada kanal L
    l_norm = _normalisasi_pencahayaan_l(l_ch)

    # 2. Pemetaan kurva kontras dokumen: putihkan area kertas terang (>228 -> 255) & pertegas tinta gelap
    titik_putih = float(np.percentile(l_norm, 92))
    titik_putih = float(np.clip(titik_putih, 218.0, 246.0))
    titik_hitam = float(np.percentile(l_norm, 1.5))
    titik_hitam = float(np.clip(titik_hitam, 18.0, 95.0))

    rentang = max(40.0, titik_putih - titik_hitam)
    l_scaled = np.clip((l_norm - titik_hitam) / rentang, 0.0, 1.0)
    # Kurva lembut: menggelapkan tinta di bawah midtone sambil menjaga kertas tetap putih murni
    l_curved = np.where(
        l_scaled < 0.86,
        np.power(l_scaled / 0.86, 1.38) * 0.88,
        0.88 + ((l_scaled - 0.86) / 0.14) * 0.12,
    )
    l_final = np.clip(l_curved * 255.0, 0.0, 255.0).astype(np.uint8)
    # Bersihkan sisa abu-abu super tipis di area kertas kosong
    l_final = np.where(l_final >= 238, 255, l_final).astype(np.uint8)

    # 3. Netralkan rona kuning/biru pada latar kertas putih, tapi pertahankan warna tinta (pulpen biru/merah)
    mask_kertas = np.clip((l_final.astype(np.float32) - 188.0) / 52.0, 0.0, 1.0)
    a_float = a_ch.astype(np.float32)
    b_float = b_ch.astype(np.float32)
    # Perkuat sedikit saturasi tinta berwarna di area non-kertas, netralkan ke 128 di area kertas
    a_out = 128.0 + (a_float - 128.0) * (1.0 - 0.92 * mask_kertas) * 1.12
    b_out = 128.0 + (b_float - 128.0) * (1.0 - 0.92 * mask_kertas) * 1.12

    lab_out = cv2.merge(
        [
            l_final,
            np.clip(a_out, 0, 255).astype(np.uint8),
            np.clip(b_out, 0, 255).astype(np.uint8),
        ]
    )
    hasil_bgr = cv2.cvtColor(lab_out, cv2.COLOR_LAB2BGR)

    # 4. Unsharp mask halus agar goresan tulisan tangan & simbol matematika sangat tajam
    halus = cv2.GaussianBlur(hasil_bgr, (0, 0), sigmaX=1.15)
    tajam = cv2.addWeighted(hasil_bgr, 1.38, halus, -0.38, 0)
    return tajam


def _tingkatkan_hp_dokumen_cv2(bgr: np.ndarray) -> np.ndarray:
    """Mode 'H&P': pindaian hitam-putih kontras tinggi seperti fotokopi/scanner laser jernih."""
    assert cv2 is not None
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    # Kernel lebih rapat di mode H&P agar bayangan lipatan kertas ikut bersih merata
    k_morph = max(17, int(min(h, w) // 28) | 1)
    k_morph = min(k_morph, 45)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_morph, k_morph))
    bg = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
    k_blur = max(21, (k_morph * 2 + 1) | 1)
    bg = cv2.GaussianBlur(bg, (k_blur, k_blur), 0)
    l_norm = np.clip((gray.astype(np.float32) / np.maximum(bg.astype(np.float32), 20.0)) * 255.0, 0.0, 255.0)

    # Tarik kontras kuat namun tetap menjaga gradasi halus agar tulisan pensil tipis tidak putus
    titik_putih = float(np.clip(np.percentile(l_norm, 88), 208.0, 240.0))
    titik_hitam = float(np.clip(np.percentile(l_norm, 2.0), 30.0, 115.0))
    rentang = max(35.0, titik_putih - titik_hitam)

    scaled = np.clip((l_norm - titik_hitam) / rentang, 0.0, 1.0)
    # Gamma tinggi untuk tinta hitam pekat, latar >=0.78 langsung jadi putih murni (255)
    hp = np.where(scaled >= 0.78, 1.0, np.power(scaled / 0.78, 1.85) * 0.80)
    hp_u8 = np.clip(hp * 255.0, 0.0, 255.0).astype(np.uint8)

    # Penajaman ringan + pembersihan sisa abu-abu tipis
    halus = cv2.GaussianBlur(hp_u8, (0, 0), sigmaX=0.9)
    tajam = cv2.addWeighted(hp_u8, 1.45, halus, -0.45, 0)
    tajam = np.where(tajam >= 226, 255, tajam).astype(np.uint8)
    return cv2.cvtColor(tajam, cv2.COLOR_GRAY2BGR)


def _tingkatkan_fallback_pil(img_rgb: Image.Image, mode: str) -> Image.Image:
    """Fallback pemrosesan dokumen berbasis Pillow + NumPy jika OpenCV tidak tersedia."""
    if mode == "asli":
        return img_rgb

    gray = img_rgb.convert("L")
    bg = gray.filter(ImageFilter.GaussianBlur(radius=max(12, min(img_rgb.size) // 25)))
    g_arr = np.asarray(gray, dtype=np.float32)
    bg_arr = np.maximum(np.asarray(bg, dtype=np.float32), 20.0)
    norm = np.clip((g_arr / bg_arr) * 255.0, 0.0, 255.0)

    if mode == "hp":
        norm = np.where(norm >= 225.0, 255.0, np.power(norm / 225.0, 1.8) * 210.0)
        out = Image.fromarray(norm.astype(np.uint8), mode="L").convert("RGB")
        return out.filter(ImageFilter.UnsharpMask(radius=1.2, percent=135, threshold=3))

    # Ditingkatkan fallback: pakai rasio kecerahan yang sama ke tiap kanal RGB
    rgb_arr = np.asarray(img_rgb, dtype=np.float32)
    faktor = np.clip(norm / np.maximum(g_arr, 1.0), 0.7, 2.2)[..., None]
    out_arr = np.clip(rgb_arr * faktor, 0.0, 255.0).astype(np.uint8)
    out = Image.fromarray(out_arr, mode="RGB")
    out = ImageEnhance.Contrast(out).enhance(1.22)
    return out.filter(ImageFilter.UnsharpMask(radius=1.2, percent=130, threshold=3))


def pindai_dan_tingkatkan_dokumen(
    image_input: Image.Image,
    *,
    mode: ModeScanDokumen = "ditingkatkan",
    auto_crop: bool = True,
    rotasi_derajat: int = 0,
    max_width: int = 1280,
) -> HasilScanDokumen:
    """Memproses foto kamera/galeri menjadi hasil pindaian dokumen bersih siap dibaca AI.

    Args:
        image_input: Objek `PIL.Image.Image` mentah dari kamera atau unggahan.
        mode: `"ditingkatkan"` (default, latar putih bersih + warna terjaga),
            `"hp"` (hitam-putih kontras tinggi), atau `"asli"` (tanpa filter warna).
        auto_crop: Jika True, otomatis mendeteksi 4 sudut tepi kertas & meluruskan perspektif.
        rotasi_derajat: Rotasi manual searah jarum jam (0, 90, 180, 270).
        max_width: Batas lebar piksel maksimum agar tetap tajam namun hemat memori/kuota AI.

    Returns:
        `HasilScanDokumen` berisi gambar RGB hasil scan dan status apakah auto-crop diterapkan.
    """
    img_rgb = _konversi_pil_ke_rgb(image_input)

    # Terapkan rotasi manual searah jarum jam bila diminta guru
    rotasi_bersih = int(rotasi_derajat) % 360
    if rotasi_bersih == 90:
        img_rgb = img_rgb.transpose(Image.Transpose.ROTATE_270)
    elif rotasi_bersih == 180:
        img_rgb = img_rgb.transpose(Image.Transpose.ROTATE_180)
    elif rotasi_bersih == 270:
        img_rgb = img_rgb.transpose(Image.Transpose.ROTATE_90)

    # Kecilkan sedikit jika terlalu raksasa (misal kamera 48MP) sebelum pemrosesan CV agar kilat (<0.2s)
    batas_proses = max(1600, max_width)
    if max(img_rgb.size) > batas_proses:
        skala_awal = batas_proses / float(max(img_rgb.size))
        img_rgb = img_rgb.resize(
            (max(1, round(img_rgb.width * skala_awal)), max(1, round(img_rgb.height * skala_awal))),
            Image.Resampling.LANCZOS,
        )

    mode_valid = mode if mode in ("ditingkatkan", "hp", "asli") else "ditingkatkan"
    auto_cropped = False
    sudut_list: list[tuple[int, int]] | None = None

    if HAS_OPENCV and cv2 is not None:
        rgb_np = np.asarray(img_rgb, dtype=np.uint8)
        bgr = cv2.cvtColor(rgb_np, cv2.COLOR_RGB2BGR)

        if auto_crop:
            rect = _deteksi_sudut_kertas_cv2(bgr)
            if rect is not None:
                bgr = _luruskan_perspektif_cv2(bgr, rect)
                auto_cropped = True
                sudut_list = [(int(round(x)), int(round(y))) for x, y in rect]

        if mode_valid == "ditingkatkan":
            bgr = _tingkatkan_warna_dokumen_cv2(bgr)
        elif mode_valid == "hp":
            bgr = _tingkatkan_hp_dokumen_cv2(bgr)

        hasil_rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        hasil_img = Image.fromarray(hasil_rgb, mode="RGB")
    else:
        hasil_img = _tingkatkan_fallback_pil(img_rgb, mode_valid)

    # Terapkan batas lebar akhir proporsional
    if max_width > 0 and hasil_img.width > max_width:
        rasio = max_width / float(hasil_img.width)
        hasil_img = hasil_img.resize(
            (max_width, max(1, round(hasil_img.height * rasio))),
            Image.Resampling.LANCZOS,
        )

    return HasilScanDokumen(
        gambar=hasil_img,
        mode=mode_valid,
        auto_cropped=auto_cropped,
        sudut_terdeteksi=sudut_list,
    )

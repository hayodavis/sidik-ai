"""Komponen Kamera Dokumen Langsung berbasis Streamlit Custom Components v2 (CCv2).

Dirancang khusus untuk guru di kelas (terutama perangkat mobile) agar dapat langsung
memotret lembar jawaban tulisan tangan siswa dengan tampilan Mode Dokumen:
- Kamera belakang otomatis (`facingMode: "environment"`), bisa ganti kamera depan/belakang.
- Pilihan mode langsung di viewfinder: `Asli` | `H&P` | `Ditingkatkan`.
- Grid bantu 3×3, bingkai sudut kertas, zoom `1× / 1.5× / 2×`, dan tombol rana besar.
- Opsi `Kamera HP Asli (HD)` (`capture="environment"`) sebagai jalur resolusi penuh
  autofokus bawaan ponsel (tetap diproses otomatis oleh mesin scanner dokumen SIDIK-AI).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import streamlit as st

_CAMERA_SCANNER_HTML = """
<div class="sidik-cam-root" id="camRoot">
  <div class="sidik-idle" id="idleBox">
    <div class="sidik-idle-head">
      <div class="sidik-idle-badge">Mode Dokumen</div>
      <div class="sidik-idle-title">Foto langsung lembar jawaban siswa</div>
      <div class="sidik-idle-sub">
        Otomatis memotong tepi kertas, menghapus bayangan, dan menajamkan tulisan tangan seperti hasil scanner.
      </div>
    </div>

    <div class="sidik-mode-row" id="idleModeRow" role="radiogroup" aria-label="Mode hasil scan">
      <button type="button" class="sidik-pill" data-mode="asli">Asli</button>
      <button type="button" class="sidik-pill" data-mode="hp">H&amp;P</button>
      <button type="button" class="sidik-pill active" data-mode="ditingkatkan">Ditingkatkan</button>
    </div>

    <div class="sidik-idle-actions">
      <button type="button" class="sidik-btn-primary" id="btnStartCam">
        <span class="sidik-ico">&#128247;</span>
        <span>Buka Kamera Dokumen</span>
      </button>
      <label class="sidik-btn-secondary" for="nativeCamInput">
        <span class="sidik-ico">&#128241;</span>
        <span>Kamera HP Asli (HD)</span>
      </label>
      <input
        id="nativeCamInput"
        type="file"
        accept="image/*"
        capture="environment"
        class="sidik-hidden-input"
      />
    </div>
    <div class="sidik-status-msg" id="idleStatus" hidden></div>
  </div>

  <div class="sidik-live" id="liveBox" hidden>
    <div class="sidik-viewport">
      <video id="camVideo" autoplay playsinline muted></video>

      <div class="sidik-grid-overlay" aria-hidden="true">
        <div class="sidik-corner tl"></div>
        <div class="sidik-corner tr"></div>
        <div class="sidik-corner bl"></div>
        <div class="sidik-corner br"></div>
      </div>

      <div class="sidik-flash" id="camFlash"></div>

      <div class="sidik-top-bar">
        <button type="button" class="sidik-icon-btn" id="btnCloseCam" title="Tutup kamera">
          &#10005;
        </button>
        <div class="sidik-float-pills" id="liveModeRow" role="radiogroup" aria-label="Filter dokumen">
          <button type="button" class="sidik-fpill" data-mode="asli">Asli</button>
          <button type="button" class="sidik-fpill" data-mode="hp">H&amp;P</button>
          <button type="button" class="sidik-fpill active" data-mode="ditingkatkan">Ditingkatkan</button>
        </div>
        <button type="button" class="sidik-icon-btn" id="btnFlipCam" title="Ganti kamera depan/belakang">
          &#8635;
        </button>
      </div>

      <div class="sidik-zoom-bar" id="zoomRow">
        <button type="button" class="sidik-zbtn active" data-zoom="1">1&times;</button>
        <button type="button" class="sidik-zbtn" data-zoom="1.5">1.5&times;</button>
        <button type="button" class="sidik-zbtn" data-zoom="2">2&times;</button>
      </div>

      <div class="sidik-toast" id="liveToast" hidden>Foto ditangkap &amp; dipindai...</div>
    </div>

    <div class="sidik-deck">
      <div class="sidik-deck-left">
        <span class="sidik-doc-label">Dokumen</span>
        <span class="sidik-queue-chip" id="queueCountChip">0 lembar</span>
      </div>

      <button type="button" class="sidik-shutter" id="btnShutter" aria-label="Ambil foto dokumen">
        <span class="sidik-shutter-inner"></span>
      </button>

      <label class="sidik-deck-right" for="nativeCamInput" title="Gunakan kamera bawaan HP">
        <span>HP HD</span>
      </label>
    </div>
  </div>
</div>
"""

_CAMERA_SCANNER_CSS = """
.sidik-cam-root {
  font-family: var(--st-font, system-ui, -apple-system, sans-serif);
  color: var(--st-text-color, #1e293b);
  width: 100%;
  box-sizing: border-box;
}

.sidik-cam-root *, .sidik-cam-root *::before, .sidik-cam-root *::after {
  box-sizing: border-box;
}

.sidik-hidden-input {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
  pointer-events: none;
}

.sidik-idle {
  background: var(--st-secondary-background-color, #f5f7fa);
  border: 1px solid var(--st-border-color, #cbd5e1);
  border-radius: var(--st-base-radius, 12px);
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.sidik-idle-head {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.sidik-idle-badge {
  align-self: flex-start;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  padding: 2px 9px;
  border-radius: 999px;
  background: var(--st-primary-color, #1f4e78);
  color: #ffffff;
}

.sidik-idle-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--st-heading-color, var(--st-text-color, #0f172a));
}

.sidik-idle-sub {
  font-size: 13px;
  line-height: 1.45;
  opacity: 0.85;
}

.sidik-mode-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
  background: rgba(15, 23, 42, 0.07);
  padding: 4px;
  border-radius: 999px;
}

.sidik-pill {
  border: none;
  background: transparent;
  color: var(--st-text-color, #1e293b);
  font-size: 13px;
  font-weight: 600;
  padding: 8px 10px;
  border-radius: 999px;
  cursor: pointer;
  transition: background 0.16s ease, color 0.16s ease, box-shadow 0.16s ease;
}

.sidik-pill.active {
  background: var(--st-background-color, #ffffff);
  color: var(--st-primary-color, #1f4e78);
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.14);
}

.sidik-idle-actions {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(175px, 1fr));
  gap: 10px;
}

.sidik-btn-primary,
.sidik-btn-secondary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 46px;
  padding: 10px 14px;
  border-radius: var(--st-button-radius, 10px);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  text-align: center;
  user-select: none;
  transition: transform 0.1s ease, opacity 0.15s ease;
}

.sidik-btn-primary {
  border: none;
  background: var(--st-primary-color, #1f4e78);
  color: #ffffff;
}

.sidik-btn-secondary {
  border: 1px solid var(--st-border-color, #94a3b8);
  background: var(--st-background-color, #ffffff);
  color: var(--st-text-color, #1e293b);
}

.sidik-btn-primary:active,
.sidik-btn-secondary:active {
  transform: scale(0.98);
}

.sidik-status-msg {
  font-size: 12.5px;
  line-height: 1.4;
  padding: 8px 11px;
  border-radius: 8px;
  background: rgba(245, 158, 11, 0.14);
  color: #92400e;
  border: 1px solid rgba(245, 158, 11, 0.35);
}

/* Live Viewfinder (gaya kamera Mode Dokumen smartphone) */
.sidik-live {
  background: #05070b;
  border-radius: 16px;
  overflow: hidden;
  border: 1px solid rgba(148, 163, 184, 0.25);
  box-shadow: 0 10px 28px rgba(2, 6, 23, 0.28);
}

.sidik-viewport {
  position: relative;
  width: 100%;
  aspect-ratio: 3 / 4;
  max-height: 540px;
  background: #000000;
  overflow: hidden;
}

@media (min-width: 720px) {
  .sidik-viewport {
    aspect-ratio: 4 / 3;
    max-height: 460px;
  }
}

#camVideo {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  transition: transform 0.18s ease, filter 0.18s ease;
}

#camVideo.preview-hp {
  filter: grayscale(100%) contrast(1.38) brightness(1.06);
}

#camVideo.preview-ditingkatkan {
  filter: contrast(1.18) brightness(1.06) saturate(1.05);
}

.sidik-grid-overlay {
  position: absolute;
  inset: 0;
  pointer-events: none;
  background-image:
    linear-gradient(to right, rgba(255, 255, 255, 0.22) 1px, transparent 1px),
    linear-gradient(to bottom, rgba(255, 255, 255, 0.22) 1px, transparent 1px);
  background-size: 33.333% 33.333%;
  background-position: 0 0;
}

.sidik-corner {
  position: absolute;
  width: 26px;
  height: 26px;
  border-color: #facc15;
  border-style: solid;
  border-width: 0;
  opacity: 0.92;
}
.sidik-corner.tl { top: 14%; left: 8%; border-top-width: 3px; border-left-width: 3px; border-top-left-radius: 4px; }
.sidik-corner.tr { top: 14%; right: 8%; border-top-width: 3px; border-right-width: 3px; border-top-right-radius: 4px; }
.sidik-corner.bl { bottom: 16%; left: 8%; border-bottom-width: 3px; border-left-width: 3px; border-bottom-left-radius: 4px; }
.sidik-corner.br { bottom: 16%; right: 8%; border-bottom-width: 3px; border-right-width: 3px; border-bottom-right-radius: 4px; }

.sidik-flash {
  position: absolute;
  inset: 0;
  background: #ffffff;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.22s ease;
}
.sidik-flash.on {
  opacity: 0.82;
  transition: none;
}

.sidik-top-bar {
  position: absolute;
  top: 12px;
  left: 10px;
  right: 10px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  z-index: 4;
}

.sidik-icon-btn {
  width: 38px;
  height: 38px;
  border-radius: 50%;
  border: 1px solid rgba(255, 255, 255, 0.26);
  background: rgba(15, 23, 42, 0.56);
  backdrop-filter: blur(8px);
  color: #ffffff;
  font-size: 16px;
  font-weight: 700;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.sidik-float-pills {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.56);
  backdrop-filter: blur(8px);
  border: 1px solid rgba(255, 255, 255, 0.18);
}

.sidik-fpill {
  border: none;
  background: transparent;
  color: rgba(255, 255, 255, 0.88);
  font-size: 12.5px;
  font-weight: 600;
  padding: 6px 11px;
  border-radius: 999px;
  cursor: pointer;
  white-space: nowrap;
}

.sidik-fpill.active {
  background: #ffffff;
  color: #0f172a;
}

.sidik-zoom-bar {
  position: absolute;
  bottom: 14px;
  left: 50%;
  transform: translateX(-50%);
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 6px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.58);
  backdrop-filter: blur(6px);
  z-index: 4;
}

.sidik-zbtn {
  border: none;
  background: transparent;
  color: rgba(255, 255, 255, 0.82);
  font-size: 12px;
  font-weight: 700;
  min-width: 36px;
  height: 28px;
  border-radius: 999px;
  cursor: pointer;
}

.sidik-zbtn.active {
  background: rgba(250, 204, 21, 0.24);
  color: #facc15;
}

.sidik-toast {
  position: absolute;
  top: 62px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(16, 185, 129, 0.92);
  color: #ffffff;
  font-size: 12.5px;
  font-weight: 700;
  padding: 6px 14px;
  border-radius: 999px;
  z-index: 5;
  white-space: nowrap;
}

.sidik-deck {
  background: #05070b;
  padding: 14px 18px 18px 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.sidik-deck-left {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  min-width: 72px;
}

.sidik-doc-label {
  color: #facc15;
  font-size: 13px;
  font-weight: 700;
}

.sidik-queue-chip {
  color: rgba(255, 255, 255, 0.72);
  font-size: 11.5px;
}

.sidik-shutter {
  width: 68px;
  height: 68px;
  border-radius: 50%;
  border: 4px solid #ffffff;
  background: transparent;
  padding: 4px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.1s ease;
}

.sidik-shutter:active {
  transform: scale(0.92);
}

.sidik-shutter-inner {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  background: #ffffff;
  display: block;
}

.sidik-deck-right {
  min-width: 72px;
  height: 36px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.28);
  background: rgba(255, 255, 255, 0.1);
  color: #ffffff;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0 10px;
}
"""

_CAMERA_SCANNER_JS = """
const INSTANCES = new WeakMap();

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;

  const idleBox = parentElement.querySelector("#idleBox");
  const liveBox = parentElement.querySelector("#liveBox");
  const video = parentElement.querySelector("#camVideo");
  const flash = parentElement.querySelector("#camFlash");
  const idleStatus = parentElement.querySelector("#idleStatus");
  const liveToast = parentElement.querySelector("#liveToast");
  const queueCountChip = parentElement.querySelector("#queueCountChip");
  const btnStartCam = parentElement.querySelector("#btnStartCam");
  const btnCloseCam = parentElement.querySelector("#btnCloseCam");
  const btnFlipCam = parentElement.querySelector("#btnFlipCam");
  const btnShutter = parentElement.querySelector("#btnShutter");
  const nativeCamInput = parentElement.querySelector("#nativeCamInput");

  if (!idleBox || !liveBox || !video || !btnStartCam) return;

  let state = INSTANCES.get(parentElement);
  if (!state) {
    state = {
      stream: null,
      facingMode: "environment",
      mode: (data && data.defaultMode) || "ditingkatkan",
      zoom: 1,
      toastTimer: null,
      emitTrigger: setTriggerValue,
    };
    INSTANCES.set(parentElement, state);
  }
  state.emitTrigger = setTriggerValue;

  const queueCount = Number((data && data.queueCount) || 0);
  if (queueCountChip) {
    queueCountChip.textContent = `${queueCount} lembar`;
  }

  function applyModeUI(nextMode) {
    state.mode = nextMode;
    parentElement.querySelectorAll("[data-mode]").forEach((btn) => {
      btn.classList.toggle("active", btn.getAttribute("data-mode") === nextMode);
    });
    video.classList.remove("preview-hp", "preview-ditingkatkan");
    if (nextMode === "hp") video.classList.add("preview-hp");
    if (nextMode === "ditingkatkan") video.classList.add("preview-ditingkatkan");
  }

  function applyZoomUI(nextZoom) {
    state.zoom = nextZoom;
    parentElement.querySelectorAll("[data-zoom]").forEach((btn) => {
      btn.classList.toggle("active", Number(btn.getAttribute("data-zoom")) === nextZoom);
    });
    video.style.transform = nextZoom > 1 ? `scale(${nextZoom})` : "none";
  }

  function showIdleError(msg) {
    if (!idleStatus) return;
    idleStatus.textContent = msg;
    idleStatus.hidden = !msg;
  }

  function showLiveToast(msg) {
    if (!liveToast) return;
    liveToast.textContent = msg;
    liveToast.hidden = false;
    if (state.toastTimer) clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => {
      liveToast.hidden = true;
    }, 1800);
  }

  function stopStream() {
    if (state.stream) {
      state.stream.getTracks().forEach((t) => {
        try { t.stop(); } catch (_) {}
      });
      state.stream = null;
    }
    video.srcObject = null;
  }

  async function startCamera() {
    showIdleError("");
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      showIdleError(
        "Browser ini belum mendukung pratinjau kamera langsung. Silakan klik tombol 'Kamera HP Asli (HD)' di sebelah kanan."
      );
      return;
    }
    stopStream();

    const constraintsList = [
      {
        audio: false,
        video: {
          facingMode: { ideal: state.facingMode },
          width: { ideal: 1920 },
          height: { ideal: 1080 },
        },
      },
      {
        audio: false,
        video: { facingMode: state.facingMode },
      },
      {
        audio: false,
        video: true,
      },
    ];

    let stream = null;
    let lastErr = null;
    for (const c of constraintsList) {
      try {
        stream = await navigator.mediaDevices.getUserMedia(c);
        break;
      } catch (err) {
        lastErr = err;
      }
    }

    if (!stream) {
      showIdleError(
        "Izin kamera belum diberikan atau tidak tersedia di perangkat ini (" +
          ((lastErr && lastErr.name) || "CameraError") +
          "). Anda tetap bisa memakai tombol 'Kamera HP Asli (HD)'."
      );
      idleBox.hidden = false;
      liveBox.hidden = true;
      return;
    }

    state.stream = stream;
    video.srcObject = stream;
    try {
      await video.play();
    } catch (_) {}
    idleBox.hidden = true;
    liveBox.hidden = false;
    applyModeUI(state.mode);
    applyZoomUI(state.zoom);
  }

  function captureFromVideo() {
    const vw = video.videoWidth;
    const vh = video.videoHeight;
    if (!vw || !vh) return;

    if (flash) {
      flash.classList.add("on");
      setTimeout(() => flash.classList.remove("on"), 120);
    }

    const z = Math.max(1, Number(state.zoom) || 1);
    const cropW = vw / z;
    const cropH = vh / z;
    const sx = (vw - cropW) / 2;
    const sy = (vh - cropH) / 2;

    const maxDim = 1600;
    const scale = Math.min(1, maxDim / Math.max(cropW, cropH));
    const outW = Math.max(1, Math.round(cropW * scale));
    const outH = Math.max(1, Math.round(cropH * scale));

    const canvas = document.createElement("canvas");
    canvas.width = outW;
    canvas.height = outH;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    ctx.drawImage(video, sx, sy, cropW, cropH, 0, 0, outW, outH);
    const dataUrl = canvas.toDataURL("image/jpeg", 0.9);
    const ts = Date.now();
    showLiveToast("Foto disimpan & sedang dipindai...");
    state.emitTrigger("captured", {
      dataUrl,
      mode: state.mode,
      filename: `Scan_${ts}.jpg`,
      ts,
    });
  }

  function handleNativeFile(file) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const img = new Image();
      img.onload = () => {
        const maxDim = 1600;
        const scale = Math.min(1, maxDim / Math.max(img.width, img.height));
        const outW = Math.max(1, Math.round(img.width * scale));
        const outH = Math.max(1, Math.round(img.height * scale));
        const canvas = document.createElement("canvas");
        canvas.width = outW;
        canvas.height = outH;
        const ctx = canvas.getContext("2d");
        if (!ctx) return;
        ctx.drawImage(img, 0, 0, outW, outH);
        const dataUrl = canvas.toDataURL("image/jpeg", 0.9);
        const ts = Date.now();
        state.emitTrigger("captured", {
          dataUrl,
          mode: state.mode,
          filename: file.name || `KameraHP_${ts}.jpg`,
          ts,
        });
      };
      img.src = String(reader.result || "");
    };
    reader.readAsDataURL(file);
  }

  parentElement.querySelectorAll("[data-mode]").forEach((btn) => {
    btn.onclick = () => {
      const m = btn.getAttribute("data-mode");
      if (m) applyModeUI(m);
    };
  });

  parentElement.querySelectorAll("[data-zoom]").forEach((btn) => {
    btn.onclick = () => {
      const z = Number(btn.getAttribute("data-zoom") || "1");
      applyZoomUI(z);
    };
  });

  btnStartCam.onclick = () => {
    startCamera();
  };

  if (btnCloseCam) {
    btnCloseCam.onclick = () => {
      stopStream();
      liveBox.hidden = true;
      idleBox.hidden = false;
    };
  }

  if (btnFlipCam) {
    btnFlipCam.onclick = () => {
      state.facingMode = state.facingMode === "environment" ? "user" : "environment";
      startCamera();
    };
  }

  if (btnShutter) {
    btnShutter.onclick = () => {
      captureFromVideo();
    };
  }

  if (nativeCamInput) {
    nativeCamInput.onchange = (e) => {
      const f = e.target && e.target.files && e.target.files[0];
      if (f) handleNativeFile(f);
      e.target.value = "";
    };
  }

  // Sinkronkan tampilan mode & status aktif saat rerun
  applyModeUI(state.mode);
  applyZoomUI(state.zoom);
  if (state.stream) {
    idleBox.hidden = true;
    liveBox.hidden = false;
  }

  return () => {
    stopStream();
    if (state.toastTimer) clearTimeout(state.toastTimer);
    INSTANCES.delete(parentElement);
  };
}
"""

_CAMERA_SCANNER_COMPONENT = st.components.v2.component(
    "sidik_ai_camera_scanner",
    html=_CAMERA_SCANNER_HTML,
    css=_CAMERA_SCANNER_CSS,
    js=_CAMERA_SCANNER_JS,
)


def kamera_dokumen_langsung(
    *,
    key: str = "kamera_dokumen_sidik",
    default_mode: str = "ditingkatkan",
    queue_count: int = 0,
    on_captured_change: Callable[[], None] | None = None,
) -> Any:
    """Merender komponen Kamera Dokumen Langsung (CCv2) dan mengembalikan hasil trigger `captured`."""
    if on_captured_change is None:
        on_captured_change = lambda: None

    return _CAMERA_SCANNER_COMPONENT(
        key=key,
        data={
            "defaultMode": default_mode,
            "queueCount": int(queue_count),
        },
        on_captured_change=on_captured_change,
    )

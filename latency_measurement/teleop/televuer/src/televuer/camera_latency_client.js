(function () {
  "use strict";

  const cameraOrigin = __CAMERA_ORIGIN__;
  const nativeCreateElement = Document.prototype.createElement;
  const trackedVideos = new WeakSet();
  const state = {
    config: null,
    robotMinusBrowserMs: 0,
    syncPromise: null,
    batch: [],
    lastSequence: null,
    values: [],
  };

  const epochMs = () => performance.timeOrigin + performance.now();
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  function statusElement() {
    let element = document.getElementById("xr-camera-latency-status");
    if (!element) {
      element = nativeCreateElement.call(document, "div");
      element.id = "xr-camera-latency-status";
      element.style.cssText =
        "position:fixed;left:8px;bottom:8px;z-index:2147483647;" +
        "padding:6px 8px;background:#000b;color:#7dff9a;font:12px monospace;" +
        "pointer-events:none;white-space:pre-wrap";
      element.textContent = "camera latency: waiting for WebRTC video";
      document.body.appendChild(element);
    }
    return element;
  }

  function setStatus(message, error) {
    const element = statusElement();
    element.style.color = error ? "#ff8080" : "#7dff9a";
    element.textContent = message;
  }

  async function prepareClockSync() {
    if (state.syncPromise) return state.syncPromise;
    state.syncPromise = (async () => {
      state.config = await fetch(cameraOrigin + "/latency-config", {
        cache: "no-store",
      }).then((response) => {
        if (!response.ok) throw new Error("latency-config HTTP " + response.status);
        return response.json();
      });
      if (!state.config.enabled) {
        throw new Error("camera server marker is disabled");
      }

      const samples = [];
      for (let nonce = 1; nonce <= 20; nonce++) {
        const t0 = epochMs();
        const reply = await fetch(cameraOrigin + "/latency-sync", {
          method: "POST",
          cache: "no-store",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({nonce: nonce}),
        }).then((response) => {
          if (!response.ok) throw new Error("latency-sync HTTP " + response.status);
          return response.json();
        });
        const t3 = epochMs();
        samples.push({
          offset: ((reply.t1_ms - t0) + (reply.t2_ms - t3)) / 2,
          rtt: Math.max(0, (t3 - t0) - (reply.t2_ms - reply.t1_ms)),
        });
        setStatus("camera clock sync " + nonce + "/20", false);
        await sleep(20);
      }
      samples.sort((left, right) => left.rtt - right.rtt);
      const best = samples.slice(0, 5).sort((left, right) => left.offset - right.offset);
      state.robotMinusBrowserMs = best[Math.floor(best.length / 2)].offset;
      setStatus(
        "camera clock sync OK  offset=" + state.robotMinusBrowserMs.toFixed(3) + " ms",
        false,
      );
    })();
    return state.syncPromise;
  }

  function decodeMarker(video, canvas, context) {
    const config = state.config;
    if (!config || video.videoWidth < config.width || video.videoHeight < config.height) {
      return null;
    }
    canvas.width = config.width;
    canvas.height = config.height;
    context.drawImage(
      video,
      0, 0, config.width, config.height,
      0, 0, config.width, config.height,
    );
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
    const bytes = new Uint8Array(14);
    for (let bitIndex = 0; bitIndex < 112; bitIndex++) {
      const row = Math.floor(bitIndex / config.columns);
      const column = bitIndex % config.columns;
      const x = Math.floor((column + 0.5) * config.cell_size);
      const y = Math.floor((row + 0.5) * config.cell_size);
      const pixel = (y * canvas.width + x) * 4;
      const luminance = (pixels[pixel] + pixels[pixel + 1] + pixels[pixel + 2]) / 3;
      if (luminance > 127) {
        bytes[Math.floor(bitIndex / 8)] |= 1 << (7 - bitIndex % 8);
      }
    }
    if (bytes[0] !== 0xA5 || bytes[1] !== 0x5A) return null;
    let checksum = 0;
    for (let index = 0; index < 13; index++) checksum ^= bytes[index];
    if (checksum !== bytes[13]) return null;

    let captureUs = 0;
    for (let index = 2; index < 9; index++) captureUs = captureUs * 256 + bytes[index];
    let sequence = 0;
    for (let index = 9; index < 13; index++) sequence = sequence * 256 + bytes[index];
    return {captureUs: captureUs, sequence: sequence};
  }

  function percentile(values, fraction) {
    const ordered = Array.from(values).sort((left, right) => left - right);
    return ordered[Math.floor((ordered.length - 1) * fraction)];
  }

  function flush(useBeacon) {
    if (!state.batch.length) return;
    const body = JSON.stringify({samples: state.batch});
    state.batch = [];
    const url = cameraOrigin + "/latency-result";
    if (useBeacon) {
      navigator.sendBeacon(url, new Blob([body], {type: "application/json"}));
    } else {
      fetch(url, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: body,
      }).catch((error) => setStatus("camera result upload failed: " + error, true));
    }
  }

  async function startVideoProbe(video) {
    if (trackedVideos.has(video)) return;
    trackedVideos.add(video);
    try {
      await prepareClockSync();
      if (!video.requestVideoFrameCallback) {
        throw new Error("requestVideoFrameCallback is unavailable");
      }
      const canvas = nativeCreateElement.call(document, "canvas");
      const context = canvas.getContext("2d", {willReadFrequently: true});
      const onFrame = (now) => {
        try {
          const marker = decodeMarker(video, canvas, context);
          if (marker && marker.sequence !== state.lastSequence) {
            state.lastSequence = marker.sequence;
            const displayBrowserMs = performance.timeOrigin + now;
            const latencyMs =
              displayBrowserMs + state.robotMinusBrowserMs - marker.captureUs / 1000;
            state.values.push(latencyMs);
            if (state.values.length > 300) state.values.shift();
            state.batch.push({
              sequence: marker.sequence,
              capture_us: String(marker.captureUs),
              display_browser_ms: displayBrowserMs,
              robot_minus_browser_ms: state.robotMinusBrowserMs,
              latency_ms: latencyMs,
            });
            setStatus(
              "camera " + latencyMs.toFixed(1) + " ms  " +
              "p50=" + percentile(state.values, 0.50).toFixed(1) + "  " +
              "p95=" + percentile(state.values, 0.95).toFixed(1) + "  " +
              "frames=" + state.values.length,
              latencyMs < 0,
            );
            if (state.batch.length >= 30) flush(false);
          }
        } catch (error) {
          setStatus("camera marker decode failed: " + error, true);
        }
        video.requestVideoFrameCallback(onFrame);
      };
      video.requestVideoFrameCallback(onFrame);
    } catch (error) {
      setStatus("camera latency unavailable: " + error, true);
    }
  }

  Document.prototype.createElement = function (name, options) {
    const element = nativeCreateElement.call(this, name, options);
    if (String(name).toLowerCase() === "video") {
      element.addEventListener("loadeddata", () => startVideoProbe(element), {once: true});
    }
    return element;
  };

  window.addEventListener("pagehide", () => flush(true));
  window.addEventListener("DOMContentLoaded", () => statusElement(), {once: true});
})();

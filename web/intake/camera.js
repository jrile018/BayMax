const PREVIEW_LIMIT = 512 * 1024;
const SELECTED_LIMIT = 5 * 1024 * 1024;
const PREVIEW_PIXELS = 2_000_000;
const SELECTED_PIXELS = 12_000_000;

const defaultRuntime = () => ({
  now: () => performance.now(),
  wallNow: () => Date.now(),
  setTimeout: (callback, ms) => setTimeout(callback, ms),
  clearTimeout: id => clearTimeout(id),
  setInterval: (callback, ms) => setInterval(callback, ms),
  clearInterval: id => clearInterval(id),
  mediaDevices: globalThis.navigator?.mediaDevices,
  createCanvas: () => document.createElement('canvas'),
});

function encodedFrame(video, createCanvas, pixelLimit, byteLimit, quality,
  longEdgeLimit = Infinity) {
  const width = video.videoWidth, height = video.videoHeight;
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0)
    throw new Error('The camera has no video frame yet. Try again in a moment.');
  let scale = Math.min(1, Math.sqrt(pixelLimit / (width * height)),
    longEdgeLimit / Math.max(width, height));
  for (let attempt = 0; attempt < 5; attempt++) {
    const raster = createCanvas();
    raster.width = Math.max(1, Math.floor(width * scale));
    raster.height = Math.max(1, Math.floor(height * scale));
    raster.getContext('2d').drawImage(video, 0, 0, raster.width, raster.height);
    const data = raster.toDataURL('image/jpeg', quality);
    const match = /^data:(image\/(?:jpeg|png));base64,([A-Za-z0-9+/=]+)$/.exec(data);
    if (!match) throw new Error('The camera frame could not be encoded.');
    if (Math.ceil(match[2].length * 3 / 4) <= byteLimit)
      return { raster, image_base64: match[2], media_type: match[1] };
    scale *= 0.7;
    quality = Math.max(0.45, quality - 0.1);
  }
  throw new Error('This camera frame is too large. Move closer or reduce camera resolution.');
}

function stopTracks(stream) {
  for (const track of stream?.getTracks?.() || []) {
    try { track.stop(); } catch { /* device teardown is best effort */ }
  }
}

export function createCameraController({ video, canvas, api, arrivalId, expectedRevision,
  onPreview = () => {}, onCaptured = () => {}, onStatus = () => {}, runtime }) {
  const deps = { ...defaultRuntime(), ...runtime };
  let generation = 0, pendingStart = null, active = false, disposed = false;
  let handle = null, stream = null, expiresAt = 0, timer = null;
  let expiryTimer = null;
  let lastPreviewAt = -Infinity, frameId = 0, previewWork = null;
  let displayedFrame = 0, displayTimer = null;
  let captureInFlight = null;
  let deviceListening = false;
  const closedHandles = new Set();
  const deviceChange = () => {
    stop();
    onStatus('The camera device changed. Start again.');
  };

  const post = (route, body, signal) => api(route, { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal });
  const close = id => {
    if (!id || closedHandles.has(id)) return;
    closedHandles.add(id);
    void post(`api/capture-sessions/${encodeURIComponent(id)}/close`, {}).catch(() => {});
  };
  const clearCanvas = () => {
    const context = canvas.getContext('2d');
    context?.clearRect(0, 0, canvas.width, canvas.height);
    canvas.width = 0;
    canvas.height = 0;
  };
  const current = own => !disposed && own === generation && active &&
    !!handle && deps.wallNow() < expiresAt;

  async function preview() {
    const own = generation, id = handle;
    if (!current(own) || previewWork || deps.now() - lastPreviewAt < 1000) return;
    const sampledAt = deps.now();
    lastPreviewAt = sampledAt;
    const ownFrame = ++frameId;
    const work = { abort: new AbortController(), deadlineTimer: null, sampled: null };
    previewWork = work;
    try {
      work.sampled = encodedFrame(video, deps.createCanvas, PREVIEW_PIXELS,
        PREVIEW_LIMIT, 0.7, 1280);
      if (!current(own) || handle !== id || deps.now() - sampledAt >= 2000) return;
      work.deadlineTimer = deps.setTimeout(() => {
        if (previewWork !== work) return;
        work.abort.abort();
        work.sampled = null;
        previewWork = null;
      }, Math.max(0, 2000 - (deps.now() - sampledAt)));
      const result = await post(`api/capture-sessions/${encodeURIComponent(id)}/preview`, {
        frame_id: ownFrame, image_base64: work.sampled.image_base64,
        media_type: work.sampled.media_type }, work.abort.signal);
      if (!current(own) || handle !== id || previewWork !== work ||
          deps.now() - sampledAt >= 2000 || result.capture_session_id !== id ||
          result.frame_id !== ownFrame || ownFrame !== frameId || !work.sampled ||
          result.width !== work.sampled.raster.width ||
          result.height !== work.sampled.raster.height ||
          typeof result.image_sha256 !== 'string') return;
      const sampled = work.sampled;
      canvas.width = sampled.raster.width;
      canvas.height = sampled.raster.height;
      const context = canvas.getContext('2d');
      context.clearRect(0, 0, canvas.width, canvas.height);
      context.drawImage(sampled.raster, 0, 0);
      displayedFrame = ownFrame;
      if (displayTimer !== null) deps.clearTimeout(displayTimer);
      displayTimer = deps.setTimeout(() => {
        if (own === generation && displayedFrame === ownFrame) {
          clearCanvas();
          displayedFrame = 0;
          displayTimer = null;
        }
      }, Math.max(0, 2000 - (deps.now() - sampledAt)));
      if (result.status === 'ready' && Array.isArray(result.boxes)) {
        context.strokeStyle = '#a8f0e5';
        context.lineWidth = 3;
        for (const box of result.boxes) {
          const { x, y, width, height } = box;
          if ([x, y, width, height].every(Number.isFinite) && x >= 0 && y >= 0 &&
              width > 0 && height > 0 && x + width <= canvas.width &&
              y + height <= canvas.height) context.strokeRect(x, y, width, height);
        }
      }
      onPreview(result);
    } catch (error) {
      if (current(own) && previewWork === work) {
        if ([401, 403, 404, 409].includes(error.status)) {
          stop();
          onStatus('Camera session ended. Refresh the assigned arrival before restarting.');
        } else if (error.name !== 'AbortError') {
          onStatus(error.message || 'Live framing is unavailable.');
        }
      }
    } finally {
      work.sampled = null;
      if (previewWork === work) {
        if (work.deadlineTimer !== null) deps.clearTimeout(work.deadlineTimer);
        previewWork = null;
      }
    }
  }

  function stop() {
    generation++;
    active = false;
    pendingStart = null;
    previewWork?.abort.abort();
    if (previewWork) previewWork.sampled = null;
    if (previewWork?.deadlineTimer !== null && previewWork?.deadlineTimer !== undefined)
      deps.clearTimeout(previewWork.deadlineTimer);
    previewWork = null;
    if (displayTimer !== null) deps.clearTimeout(displayTimer);
    displayTimer = null;
    displayedFrame = 0;
    if (expiryTimer !== null) deps.clearTimeout(expiryTimer);
    expiryTimer = null;
    if (deviceListening) deps.mediaDevices?.removeEventListener?.('devicechange', deviceChange);
    deviceListening = false;
    if (timer !== null) deps.clearInterval(timer);
    timer = null;
    const oldHandle = handle;
    handle = null;
    stopTracks(stream);
    stream = null;
    video.pause?.();
    video.srcObject = null;
    clearCanvas();
    if (oldHandle) {
      if (captureInFlight) void captureInFlight.then(
        () => close(oldHandle), () => close(oldHandle));
      else close(oldHandle);
    }
  }

  function start() {
    if (disposed) return Promise.resolve();
    if (pendingStart) return pendingStart;
    if (active) return Promise.resolve();
    const own = generation;
    const task = (async () => {
      let issued = null, acquired = null;
      try {
        issued = await post(`api/arrivals/${encodeURIComponent(arrivalId)}/capture-session`,
          { expected_revision: expectedRevision });
        const id = issued?.capture_session_id;
        if (!id || issued.arrival_revision !== expectedRevision)
          throw new Error('The camera session receipt is invalid. Refresh the arrival.');
        if (own !== generation || disposed) { close(id); return; }
        const deadline = Date.parse(issued.expires_at);
        if (!Number.isFinite(deadline) || deadline <= deps.wallNow()) {
          close(id); onStatus('The camera session expired. Start again.'); return;
        }
        handle = id;
        expiresAt = deadline;
        const watchdog = () => {
          if (own !== generation || disposed) return;
          if (deps.wallNow() >= deadline) {
            stop();
            onStatus('The camera session expired. Start again.');
          } else {
            expiryTimer = deps.setTimeout(watchdog,
              Math.max(1, deadline - deps.wallNow()));
          }
        };
        expiryTimer = deps.setTimeout(watchdog,
          Math.max(1, deadline - deps.wallNow()));
        acquired = await deps.mediaDevices.getUserMedia({ video: true, audio: false });
        if (own !== generation || disposed) {
          stopTracks(acquired);
          if (handle === id) handle = null;
          close(id);
          return;
        }
        if (deps.wallNow() >= deadline) {
          stopTracks(acquired);
          stop();
          onStatus('The camera session expired. Start again.');
          return;
        }
        stream = acquired;
        video.srcObject = acquired;
        await video.play?.();
        if (own !== generation || disposed) {
          stopTracks(acquired);
          if (video.srcObject === acquired) video.srcObject = null;
          if (handle === id) handle = null;
          close(id);
          return;
        }
        if (deps.wallNow() >= deadline) {
          stop();
          onStatus('The camera session expired. Start again.');
          return;
        }
        active = true;
        lastPreviewAt = -Infinity;
        deps.mediaDevices?.addEventListener?.('devicechange', deviceChange);
        deviceListening = true;
        timer = deps.setInterval(() => {
          if (deps.wallNow() >= expiresAt) {
            stop(); onStatus('The camera session expired. Start again.');
          } else void preview();
        }, 1000);
        onStatus('Camera ready. Choose a frame when it is clear.');
      } catch (error) {
        if (own === generation && !disposed) {
          if (stream !== acquired) stopTracks(acquired);
          stop();
          if (issued?.capture_session_id) close(issued.capture_session_id);
          onStatus(`Camera unavailable: ${error.message || 'permission denied'}`);
        } else {
          stopTracks(acquired);
          if (issued?.capture_session_id) close(issued.capture_session_id);
        }
      }
    })();
    pendingStart = task;
    void task.finally(() => { if (pendingStart === task) pendingStart = null; });
    return task;
  }

  function capture() {
    if (captureInFlight) return captureInFlight;
    if (!current(generation)) {
      onStatus('Start the camera again before selecting a frame.');
      return Promise.resolve(null);
    }
    const own = generation, id = handle;
    let selected;
    try { selected = encodedFrame(video, deps.createCanvas,
      SELECTED_PIXELS, SELECTED_LIMIT, 0.85); }
    catch (error) { onStatus(error.message); return Promise.resolve(null); }
    const task = (async () => {
      let receipt;
      try {
        receipt = await post(`api/capture-sessions/${encodeURIComponent(id)}/capture`, {
          expected_revision: expectedRevision,
          image_base64: selected.image_base64, media_type: selected.media_type });
      } catch (error) {
        // A lost response may follow a successful commit. The original handle
        // is the only safe recovery key; never create a new capture here.
        try {
          const status = await api(`api/capture-sessions/${encodeURIComponent(id)}`);
          if (status.state === 'consumed') {
            let fresh = null;
            try { fresh = (await api(`api/arrivals/${encodeURIComponent(arrivalId)}`)).arrival; }
            catch { /* the assigned detail may have become inaccessible */ }
            receipt = { photo: status.photo, arrival: fresh || status.arrival,
              is_current: status.is_current === true && !!fresh &&
                fresh.current_photo?.image_id === status.photo?.image_id };
          } else if (own === generation) onStatus('Save was not confirmed. Refresh the assigned arrival.');
        } catch {
          if (own === generation) onStatus('Save status is uncertain. Refresh the assigned arrival.');
        }
        if (!receipt) return null;
      }
      if (own !== generation || disposed) {
        onStatus('Saved state may have changed. Refresh the assigned arrival.');
        return null;
      }
      const currentImageId = receipt?.arrival?.current_photo?.image_id ??
        receipt?.arrival?.current_image_id;
      if (!receipt?.photo || receipt.is_current !== true ||
          currentImageId !== receipt.photo.image_id) {
        onStatus('This saved frame is retired or uncertain. Refresh the assigned arrival.');
        return null;
      }
      onCaptured(receipt);
      stop();
      return receipt;
    })();
    captureInFlight = task;
    void task.finally(() => { if (captureInFlight === task) captureInFlight = null; });
    return task;
  }

  function dispose() {
    stop();
    disposed = true;
  }

  return { start, capture, stop, dispose };
}

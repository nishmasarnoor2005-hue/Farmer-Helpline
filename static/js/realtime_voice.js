/**
 * realtime_voice.js — Real-Time Voice Controller (M3)
 * ES6 module; no top-level side effects.
 */

// ---------------------------------------------------------------------------
// State machine constants
// ---------------------------------------------------------------------------
const STATES = {
  IDLE:                'IDLE',
  REQUESTING_PERMISSION: 'REQUESTING_PERMISSION',
  CONNECTING:          'CONNECTING',
  LISTENING:           'LISTENING',
  USER_SPEAKING:       'USER_SPEAKING',
  PROCESSING:          'PROCESSING',
  ASSISTANT_SPEAKING:  'ASSISTANT_SPEAKING',
  INTERRUPTING:        'INTERRUPTING',
  RECONNECTING:        'RECONNECTING',
  ERROR:               'ERROR',
  ENDED:               'ENDED',
};

// ---------------------------------------------------------------------------
// SimpleSilenceDetector — fallback when @ricky0123/vad-web is unavailable
// ---------------------------------------------------------------------------
class SimpleSilenceDetector {
  constructor(stream, options = {}) {
    this.onSpeechStart = options.onSpeechStart || (() => {});
    this.onSpeechEnd   = options.onSpeechEnd   || (() => {});
    this._minSilenceMs = options.minSilenceMs  || 400;
    this._ctx          = new (window.AudioContext || window.webkitAudioContext)();
    this._source       = this._ctx.createMediaStreamSource(stream);
    this._analyser     = this._ctx.createAnalyser();
    this._analyser.fftSize = 512;
    this._source.connect(this._analyser);
    this._buffer       = new Float32Array(this._analyser.fftSize);
    this._speaking     = false;
    this._silenceStart = null;
    this._rafId        = null;
    this._poll();
  }

  _rms() {
    this._analyser.getFloatTimeDomainData(this._buffer);
    let sum = 0;
    for (let v of this._buffer) sum += v * v;
    return Math.sqrt(sum / this._buffer.length);
  }

  _poll() {
    const rms       = this._rms();
    const threshold = 0.01;
    if (rms > threshold) {
      if (!this._speaking) {
        this._speaking     = true;
        this._silenceStart = null;
        this.onSpeechStart();
      }
    } else {
      if (this._speaking) {
        if (!this._silenceStart) this._silenceStart = Date.now();
        if (Date.now() - this._silenceStart > this._minSilenceMs) {
          this._speaking     = false;
          this._silenceStart = null;
          this.onSpeechEnd();
        }
      }
    }
    this._rafId = requestAnimationFrame(() => this._poll());
  }

  destroy() {
    if (this._rafId) cancelAnimationFrame(this._rafId);
    this._ctx.close();
  }
}

// ---------------------------------------------------------------------------
// RealtimeVoiceController
// ---------------------------------------------------------------------------
class RealtimeVoiceController {
  constructor(options = {}) {
    // Callbacks
    this._onStateChange = options.onStateChange || null;
    this._onError       = options.onError       || null;
    this._onTranscript  = options.onTranscript  || null;
    this._statusEl      = options.statusEl      || null;
    this._startBtnEl    = options.startBtnEl    || null;

    // State
    this._state             = STATES.IDLE;
    this._turnId            = 0;
    this._token             = null;   // memory only — never DOM/storage
    this._sessionId         = null;
    this._mediaRecorder     = null;
    this._audioQueue        = [];
    this._currentAudio      = null;
    this._config            = null;
    this._vad               = null;
    this._sseReader         = null;
    this._lastInterruptTime = 0;
    this._chunks            = [];
    this._stream            = null;   // MediaStream reference for cleanup
  }

  // -------------------------------------------------------------------------
  // Legal state transitions
  // -------------------------------------------------------------------------
  static _TRANSITIONS = {
    [STATES.IDLE]:               [STATES.REQUESTING_PERMISSION],
    [STATES.REQUESTING_PERMISSION]: [STATES.CONNECTING, STATES.ERROR],
    [STATES.CONNECTING]:         [STATES.LISTENING, STATES.ERROR],
    [STATES.LISTENING]:          [STATES.USER_SPEAKING, STATES.ERROR, STATES.ENDED],
    [STATES.USER_SPEAKING]:      [STATES.PROCESSING, STATES.INTERRUPTING],
    [STATES.PROCESSING]:         [STATES.ASSISTANT_SPEAKING, STATES.ERROR],
    [STATES.ASSISTANT_SPEAKING]: [STATES.LISTENING, STATES.INTERRUPTING],
    [STATES.INTERRUPTING]:       [STATES.LISTENING],
    [STATES.RECONNECTING]:       [STATES.CONNECTING, STATES.ERROR, STATES.ENDED],
    [STATES.ERROR]:              [STATES.ENDED],
    // Any state → RECONNECTING is handled dynamically in transition()
  };

  // -------------------------------------------------------------------------
  // transition(newState)
  // -------------------------------------------------------------------------
  transition(newState) {
    const allowed = RealtimeVoiceController._TRANSITIONS[this._state] || [];
    const toReconnecting = newState === STATES.RECONNECTING;

    if (!toReconnecting && !allowed.includes(newState)) {
      console.warn(
        `[RealtimeVoice] Illegal transition: ${this._state} → ${newState} (ignored)`
      );
      return;
    }

    const oldState  = this._state;
    this._state     = newState;

    // Fire onStateChange callback
    if (this._onStateChange) {
      try { this._onStateChange(oldState, newState); } catch (_) { /* ignore */ }
    }

    // Update status element text
    if (this._statusEl) {
      const labels = {
        [STATES.IDLE]:                 'Idle',
        [STATES.REQUESTING_PERMISSION]: 'Requesting microphone permission…',
        [STATES.CONNECTING]:           'Connecting…',
        [STATES.LISTENING]:            'Listening…',
        [STATES.USER_SPEAKING]:        'You are speaking…',
        [STATES.PROCESSING]:           'Processing…',
        [STATES.ASSISTANT_SPEAKING]:   'Assistant speaking…',
        [STATES.INTERRUPTING]:         'Interrupting…',
        [STATES.RECONNECTING]:         'Reconnecting…',
        [STATES.ERROR]:                'Error',
        [STATES.ENDED]:                'Ended',
      };
      this._statusEl.textContent = labels[newState] || newState;
    }

    // Update start button text
    if (this._startBtnEl) {
      const stopStates = new Set([
        STATES.LISTENING,
        STATES.USER_SPEAKING,
        STATES.PROCESSING,
        STATES.ASSISTANT_SPEAKING,
        STATES.INTERRUPTING,
      ]);
      this._startBtnEl.textContent = stopStates.has(newState)
        ? 'Stop'
        : 'Start Real-Time';
    }
  }

  // -------------------------------------------------------------------------
  // start()
  // -------------------------------------------------------------------------
  async start() {
    this.transition(STATES.REQUESTING_PERMISSION);

    // 1. Request microphone
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl:  true,
        },
      });
    } catch (_) {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch (err) {
        this.transition(STATES.ERROR);
        if (this._onError) this._onError(err);
        return;
      }
    }
    this._stream = stream;

    // 2. Fetch config
    try {
      const cfgRes  = await fetch('/realtime/config');
      this._config  = await cfgRes.json();
    } catch (_) {
      // Non-fatal; defaults will be used via nullish coalescing
      this._config = {};
    }

    // 3. Create session
    this.transition(STATES.CONNECTING);
    let sessionResp;
    try {
      sessionResp = await fetch('/realtime/session', { method: 'POST' });
    } catch (err) {
      this.transition(STATES.ERROR);
      if (this._onError) this._onError(err);
      return;
    }

    if (sessionResp.status === 503) {
      const err = new Error('Realtime voice is disabled on this server');
      this.transition(STATES.ERROR);
      if (this._onError) this._onError(err);
      throw err;
    }

    if (!sessionResp.ok) {
      const err = new Error(`Session creation failed: ${sessionResp.status}`);
      this.transition(STATES.ERROR);
      if (this._onError) this._onError(err);
      throw err;
    }

    const sessionData = await sessionResp.json();
    // Token stored in memory only — never written to DOM or Web Storage
    this._token     = sessionData.token;
    this._sessionId = sessionData.session_id;

    this.transition(STATES.LISTENING);

    // 4. Initialize VAD
    const vadOptions = {
      onSpeechStart: () => this._onVADSpeechStart(),
      onSpeechEnd:   () => this._onVADSpeechEnd(),
      minSilenceMs:  this._config?.min_silence_ms ?? 400,
    };

    try {
      const vadModule = await import(
        'https://cdn.jsdelivr.net/npm/@ricky0123/vad-web@0.0.22/dist/bundle.min.js'
      );
      // vad-web uses MicVAD.new() factory pattern
      const MicVAD = vadModule.MicVAD || vadModule.default?.MicVAD;
      if (MicVAD) {
        this._vad = await MicVAD.new({
          stream,
          onSpeechStart: vadOptions.onSpeechStart,
          onSpeechEnd:   vadOptions.onSpeechEnd,
        });
        this._vad.start();
      } else {
        throw new Error('MicVAD not found in vad-web bundle');
      }
    } catch (_) {
      // Fall back to SimpleSilenceDetector
      this._vad = new SimpleSilenceDetector(stream, vadOptions);
    }
  }

  // -------------------------------------------------------------------------
  // _onVADSpeechStart()
  // -------------------------------------------------------------------------
  _onVADSpeechStart() {
    const cooldown = this._config?.barge_in_cooldown_ms ?? 300;
    if (Date.now() - this._lastInterruptTime < cooldown) return;

    if (this._state === STATES.ASSISTANT_SPEAKING) {
      this._bargeIn();
    } else if (this._state === STATES.LISTENING) {
      this.transition(STATES.USER_SPEAKING);
      this._startRecording();
    }
  }

  // -------------------------------------------------------------------------
  // _onVADSpeechEnd()
  // -------------------------------------------------------------------------
  _onVADSpeechEnd() {
    if (this._state === STATES.USER_SPEAKING) {
      this._stopRecording();
    }
  }

  // -------------------------------------------------------------------------
  // _startRecording() — internal helper
  // -------------------------------------------------------------------------
  _startRecording() {
    if (!this._stream) return;
    this._chunks      = [];
    this._mediaRecorder = new MediaRecorder(this._stream);
    this._mediaRecorder.addEventListener('dataavailable', (e) => {
      if (e.data && e.data.size > 0) this._chunks.push(e.data);
    });
    this._mediaRecorder.addEventListener('stop', () => {
      const blob = new Blob(this._chunks, { type: 'audio/webm' });
      this._chunks = [];
      this._sendAudio(blob);
    });
    this._mediaRecorder.start();
  }

  // -------------------------------------------------------------------------
  // _stopRecording() — stops MediaRecorder (fires 'stop' → _sendAudio)
  // -------------------------------------------------------------------------
  _stopRecording() {
    if (
      this._mediaRecorder &&
      (this._mediaRecorder.state === 'recording' ||
       this._mediaRecorder.state === 'paused')
    ) {
      this._mediaRecorder.stop();
    }
  }

  // -------------------------------------------------------------------------
  // _bargeIn()
  // -------------------------------------------------------------------------
  async _bargeIn() {
    this.transition(STATES.INTERRUPTING);

    // Stop current playback
    if (this._currentAudio) {
      this._currentAudio.pause();
      this._currentAudio.src = '';
      this._currentAudio     = null;
    }
    this._audioQueue = [];
    this._turnId++;

    // Fire-and-forget cancel request (do not await)
    if (this._token) {
      fetch('/realtime/cancel', {
        method:  'POST',
        headers: { 'X-Session-Token': this._token },
      }).catch(() => {});
    }

    this._lastInterruptTime = Date.now();

    const debounce = this._config?.barge_in_debounce_ms ?? 180;
    setTimeout(() => {
      if (this._state === STATES.INTERRUPTING) {
        this.transition(STATES.LISTENING);
        this._startRecording();
      }
    }, debounce);
  }

  // -------------------------------------------------------------------------
  // _sendAudio(audioBlob)
  // -------------------------------------------------------------------------
  async _sendAudio(audioBlob) {
    this.transition(STATES.PROCESSING);

    const form = new FormData();
    form.append('audio', audioBlob, 'audio.webm');

    let response;
    try {
      response = await fetch('/realtime/audio', {
        method:  'POST',
        headers: { 'X-Session-Token': this._token },
        body:    form,
      });
    } catch (err) {
      this.transition(STATES.ERROR);
      if (this._onError) this._onError(err);
      return;
    }

    if (!response.ok || !response.body) {
      this.transition(STATES.ERROR);
      if (this._onError) this._onError(new Error(`Audio POST failed: ${response.status}`));
      return;
    }

    // Consume SSE stream
    const reader  = response.body.getReader();
    this._sseReader = reader;
    const decoder = new TextDecoder();
    let buffer    = '';
    let firstAudioChunk = true;

    const capturedTurnId = this._turnId;

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer      = lines.pop(); // retain incomplete last line

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const raw = line.slice('data: '.length).trim();
          if (!raw) continue;

          let payload;
          try { payload = JSON.parse(raw); } catch (_) { continue; }

          switch (payload.type) {
            case 'transcript':
              if (this._onTranscript) this._onTranscript(payload.data ?? payload.text ?? raw);
              break;

            case 'audio_chunk': {
              // Discard stale chunks from a previous turn
              if (capturedTurnId !== this._turnId) break;

              if (firstAudioChunk) {
                firstAudioChunk = false;
                if (
                  this._state === STATES.PROCESSING ||
                  this._state === STATES.ASSISTANT_SPEAKING
                ) {
                  this.transition(STATES.ASSISTANT_SPEAKING);
                }
              }

              // Decode base64 → Blob → object URL
              const b64    = payload.data;
              const binary = atob(b64);
              const bytes  = new Uint8Array(binary.length);
              for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
              const blob   = new Blob([bytes], { type: 'audio/mpeg' });
              const url    = URL.createObjectURL(blob);
              this._audioQueue.push({ url, turnId: this._turnId });
              this._playNext();
              break;
            }

            case 'done':
              if (
                this._state === STATES.PROCESSING ||
                this._state === STATES.ASSISTANT_SPEAKING
              ) {
                this.transition(STATES.LISTENING);
              }
              break;

            case 'error':
              if (payload.data === 'cancelled') {
                if (this._state !== STATES.INTERRUPTING && this._state !== STATES.ENDED) {
                  this.transition(STATES.LISTENING);
                }
              } else {
                this.transition(STATES.ERROR);
                if (this._onError) this._onError(new Error(payload.data || 'SSE error'));
              }
              break;

            default:
              break;
          }
        }
      }
    } catch (err) {
      // Reader cancelled or network error — only error if not already stopped
      if (this._state !== STATES.ENDED && this._state !== STATES.INTERRUPTING) {
        this.transition(STATES.ERROR);
        if (this._onError) this._onError(err);
      }
    } finally {
      this._sseReader = null;
    }
  }

  // -------------------------------------------------------------------------
  // _playNext()
  // -------------------------------------------------------------------------
  _playNext() {
    // Don't start a new clip if one is already playing or queue is empty
    if (this._currentAudio || this._audioQueue.length === 0) return;

    const item = this._audioQueue.shift();

    // Skip stale items from a previous turn
    if (item.turnId !== this._turnId) {
      URL.revokeObjectURL(item.url);
      this._playNext();
      return;
    }

    const audio       = new Audio(item.url);
    this._currentAudio = audio;

    audio.onended = () => {
      URL.revokeObjectURL(item.url);
      this._currentAudio = null;
      this._playNext();
    };

    audio.onerror = () => {
      URL.revokeObjectURL(item.url);
      this._currentAudio = null;
      this._playNext();
    };

    audio.play().catch(() => {
      URL.revokeObjectURL(item.url);
      this._currentAudio = null;
      this._playNext();
    });
  }

  // -------------------------------------------------------------------------
  // stop()
  // -------------------------------------------------------------------------
  async stop() {
    this.transition(STATES.ENDED);

    // Stop MediaRecorder
    if (
      this._mediaRecorder &&
      (this._mediaRecorder.state === 'recording' ||
       this._mediaRecorder.state === 'paused')
    ) {
      this._mediaRecorder.stop();
    }
    this._mediaRecorder = null;

    // Stop all mic tracks
    if (this._stream) {
      this._stream.getTracks().forEach((t) => t.stop());
      this._stream = null;
    }

    // Cancel SSE reader
    if (this._sseReader) {
      try { this._sseReader.cancel(); } catch (_) { /* ignore */ }
      this._sseReader = null;
    }

    // Stop current audio playback
    if (this._currentAudio) {
      this._currentAudio.pause();
      this._currentAudio = null;
    }
    this._audioQueue = [];

    // Destroy VAD
    if (this._vad) {
      try { this._vad.destroy?.(); } catch (_) { /* ignore */ }
      try { this._vad.stop?.();    } catch (_) { /* ignore */ }
      this._vad = null;
    }

    // Fire-and-forget DELETE /realtime/session
    if (this._token) {
      const tokenSnapshot = this._token;
      this._token = null;
      fetch('/realtime/session', {
        method:  'DELETE',
        headers: { 'X-Session-Token': tokenSnapshot },
      }).catch(() => {});
    }

    this._sessionId = null;
    this._config    = null;
    this._chunks    = [];
  }

  // -------------------------------------------------------------------------
  // getState()
  // -------------------------------------------------------------------------
  getState() {
    return this._state;
  }
}

export { RealtimeVoiceController };

# Robot Validation

Use this checklist when validating the Gemini Live + DeepSeek path on Reachy
Mini hardware. The app under test is `baby-reachy-mini-companion`; the
standalone `gemini-deepseek-companion` app is only a rollback path and does not
exercise baby companion tools.

## Preconditions

- `reachy-ollama-cloud-sidecar` is running and exposes
  `http://127.0.0.1:11435/v1`.
- The app instance config uses:
  - `VOICE_FRONTEND=gemini_live`
  - `LOCAL_LLM_URL=http://127.0.0.1:11435/v1`
  - `LOCAL_LLM_MODEL=reachy-companion`
  - `LOCAL_LLM_API_KEY=sidecar`
- The settings UI microphone selector remains on `Reachy SDK audio
  (recommended)`.
- Stop `gemini-deepseek-companion` before validating this app so it cannot hold
  robot audio devices.

## Startup Proof

1. Launch `baby-reachy-mini-companion` from the Reachy Mini dashboard.
2. Click `Start pipeline`.
3. Confirm `/app_state` reports `running`.
4. Confirm logs show media preparation before SDK recording/playback:
   - daemon media release or logged release failure,
   - stale IPC cleanup summary,
   - `record_loop (SDK) started`,
   - Gemini Live session ready with baby companion tool loop.

## Behavior Proof

- Ask a normal spoken question and confirm:
  - user transcript is logged,
  - baby tool loop starts and finishes,
  - Gemini output audio is heard.
- Ask for a physical action, such as head movement, and confirm:
  - the existing baby tool dispatcher logs the tool call,
  - the robot visibly performs the action,
  - the final spoken answer does not claim success unless the tool returned
    success.
- Ask `what do you see?` and confirm one of:
  - a fresh camera frame is processed and described, or
  - the camera tool returns an explicit unavailable result that is reflected in
    the spoken answer.

## Restart Proof

1. Stop the app from the dashboard.
2. Start `baby-reachy-mini-companion` again without SSH cleanup.
3. Confirm the app reaches `running` and answers a spoken question.

If restart requires manual daemon restart or `ipcrm`, capture logs and IPC state
before cleanup; that is a follow-up daemon/media lifecycle bug.

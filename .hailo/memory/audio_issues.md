# Audio & Microphone Issues (Multi-Machine)

## AudioPlayer Race Conditions (voice_assistant)
File: `hailo_apps/python/gen_ai_apps/voice_assistant/audio_player.py`

### Core Problem
Audio output stops after several iterations due to queue items being lost during stream reinit.

### Race Conditions Identified
1. **Queue lost on reinit**: `stop()` preserves queue (size 2-7), sets `_reinit_event`, but playback worker breaks immediately and items vanish before stream recreation (`queue_size_after_reinit: 0`)
2. **Consume-before-check**: Worker calls `queue.get()` before checking stream state; if `_reinit_event` is set, worker breaks after consuming item
3. **Write error drops data**: On write error with `_reinit_event` set, preservation check requires stream to be reported inactive — race on stream state timing
4. **50ms timeout window**: `queue.get(timeout=0.05)` creates a window where items can be queued and then lost when `_reinit_event` triggers a break

### Recommended Fixes
- Always preserve data when `_reinit_event` is set, regardless of stream state
- Don't call `queue.get()` when stream is known inactive
- Use locks to synchronize queue access during `stop()` and stream recreation
- Consider a separate preserved-items queue for reinit scenarios

---

## Headset Microphone Setup (PulseAudio/ALSA)

### Common Problem
Headset mic not working even though audio output works fine.

### Root Cause
Wrong PulseAudio port selected: `analog-input-headset-mic` vs correct `analog-input-headphone-mic`.

### Quick Fix Commands
```bash
# Switch to correct port
pactl set-source-port alsa_input.pci-0000_00_1f.3.analog-stereo analog-input-headphone-mic

# Increase mic boost (both to max)
amixer -c 0 set 'Headphone Mic Boost' 3
amixer -c 0 set 'Headset Mic Boost' 3
```

### Persistence
- PulseAudio port selection does NOT persist across reboots
- ALSA mixer settings may also reset
- Fix: `sudo alsactl store` or add commands to startup script
- Card profile must be "Analog Stereo Duplex" (input + output)

### Verification
```bash
# Check active port (should show analog-input-headphone-mic)
pactl list sources | grep "Active Port"

# Test mic signal strength (should be 0.4+ max amplitude, not 0.001)
python3 -c "import sounddevice as sd; import numpy as np; rec = sd.rec(int(2*16000), samplerate=16000, channels=1, dtype='float32', blocking=True); print('Max amplitude:', np.max(np.abs(rec)))"
```

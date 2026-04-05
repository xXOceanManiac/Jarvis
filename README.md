README.md (Jarvis v5.1)
# Jarvis v5.1

A local, voice-driven desktop assistant built for real-world control on Linux.

Jarvis is designed to execute actual tasks on your machine — not just respond conversationally.  
It integrates voice, system control, screen awareness, and gesture-based input into a single assistant.

---

## Current Capabilities (v5.1)

### Voice Assistant Core
- Push-to-talk interaction (space bar)
- Speech-to-text via OpenAI Realtime API
- Natural language understanding
- Spoken responses
- Low-friction command execution

---

### Deterministic Tool Execution
Jarvis can reliably trigger local actions such as:
- Opening applications (VS Code, Chrome, Spotify, etc.)
- Opening URLs
- Running predefined system actions
- Executing Home Assistant scripts

All critical actions are routed deterministically to avoid hallucinated behavior.

---

### Screen Awareness
- Captures screenshots of the current desktop
- Uses vision-based reasoning to understand what’s on screen
- Enables context-aware commands

Note: This currently introduces some latency and is being optimized.

---

### Camera Perception
- Uses `/dev/video0` for camera input
- Supports real-time hand tracking via MediaPipe
- Camera feed is **hidden from the user** during operation

---

### Gesture Control System
Fully functional gesture-based mouse control with:

- Hand tracking using MediaPipe
- Cursor movement mapped to hand position
- Pinch gesture for click
- Drag support
- Scroll gestures
- Screenshot gesture
- On-screen hand overlay (instead of camera preview)
- Bottom-left status indicator

This runs as a separate subsystem and integrates cleanly with the desktop.

---

### Desktop HUD
- Visual Jarvis HUD with simple logs output and system metric readouts (CPU load, Memory usage, Net Download, Net Upload)
- Visual updates for state changes (idle = blue, processing = purple, speaking = orange)
- HUD works with window managers (tested on Krohnkite) 
- When HUD drops below 1/4 screen, layout switches to Compact Mode (kinda cool).

---

### Desktop Overlay "Holographic" Gesture Control
- Visual hand overlay instead of visible camera feed
- Minimal UI for gesture feedback
- Designed to stay out of the way while remaining informative

---

### Home Assistant Integration
- Executes scripts via API
- Supports real-world control (lights, devices, etc.)
- Deterministic routing (no guessing)

---

## System Environment

- **OS:** Ubuntu (KDE Plasma)
- **Python:** 3.12
- **Runtime:** Local desktop environment
- **Assistant style:** Voice-first, low-friction execution

---

## Project Structure

```text
Jarvis.v5.1/
├── main.py
├── tools.py
├── behavior_learning.py
├── gesture_control/
│   ├── camera_input.py
│   ├── hand_tracker.py
│   ├── gesture_engine.py
│   ├── mouse_router.py
│   ├── overlay_hud.py
│   └── gesture_service.py
├── models/
│   └── hand_landmarker.task
├── screenshots/
├── logs/



Setup

1. Clone the repository

git clone <https://github.com/xXOceanManiac/Jarvis>
cd Jarvis.v5.1

2. Create virtual environment

python3 -m venv .venv
source .venv/bin/activate

3. Install dependencies

pip install openai opencv-python mediapipe pyautogui pillow mss pyside6

4. Environment Variables

Create a .env file:

OPENAI_API_KEY=your_key_here
HOME_ASSISTANT_URL=your_url ***Not needed
HOME_ASSISTANT_TOKEN=your_token ***Not needed

5. Add MediaPipe Model

Place the hand tracking model here:

models/hand_landmarker.task
Or update model_path in gesture_service.py



Running Jarvis:

Start the assistant
python3 main.py

Start the HUD
python3 jarvis_desktop_hud.py

Start gesture control
cd gesture_control
python3 gesture_service.py


Known Limitations:

Screen context checks introduce noticeable latency
No workspace sandbox for code generation yet
Gesture system requires tuning depending on lighting and camera position\


Design Philosophy:

Jarvis v5.1 is built around:

Local-first execution
Deterministic tool routing
Minimal UI friction
Real control over the machine
No fake actions or hallucinated results
What This Version Is


Jarvis v5.1 is a functional foundation:

reliable voice control
real desktop interaction
working gesture system
integrated smart home control


What This Version Is NOT (Yet):

Not a full autonomous agent (yet)
Not a planner/executor system (yet)
Not a coding assistant (yet)
Not a CAD system (yet)




Author

Built by Tate Lehenbauer.

This project is part of a larger vision to create a fully capable local AI assistant that operates with real control, real awareness, and real execution.
<!-- AGENT_METADATA
generated_from: internal_agent/data/project_registry.yaml
generated_at: 2026-03-21T17:00:41.997110
generator: internal_agent/scripts/generate_index.py
-->

<div align="center">

# 🔥 Hailo AI Community Projects & Demos

### The ultimate collection of projects built with Hailo edge AI accelerators

[![Projects](https://img.shields.io/badge/projects-90+-blue?style=for-the-badge)](https://github.com/hailo-ai)
[![Videos](https://img.shields.io/badge/videos-30+-red?style=for-the-badge&logo=youtube)](https://www.youtube.com/@hailo2062)
[![Hardware](https://img.shields.io/badge/Hailo--8_|_8L_|_10H_|_15-green?style=for-the-badge)](https://hailo.ai)

</div>

---

> **For humans:** Browse for inspiration, watch demos, find your next project.
> **For agents:** Parse the [YAML source](../internal_agent/data/project_registry.yaml) for structured data.

## Hardware at a Glance

| | Accelerator | Performance | Best For | Price Point |
|---|---|---|---|---|
| 🟢 | **Hailo-8** | 26 TOPS (INT8) | Full vision pipelines, multi-stream | M.2 module |
| 🔵 | **Hailo-8L** | 13 TOPS (INT8) | RPi AI Kit ($70), lower power | M.2 / AI Kit |
| 🟣 | **Hailo-10H** | 40 TOPS (INT4) | **GenAI**: LLM, VLM, Whisper, Stable Diffusion | AI HAT+ 2 ($130) |
| ⚪ | **Hailo-15** | Varies | On-camera AI-ISP, 4K analytics | Vision SoC |

---


## 📋 Table of Contents

- [🎬 YouTube Showcases & Tutorials](#youtube-showcases--tutorials)
- [🏆 Hackathon Winners (2025)](#hackathon-winners-2025)
- [🧠 GenAI & LLM Projects](#genai--llm-projects)
- [🏠 Smart Home & Surveillance](#smart-home--surveillance)
- [👁️ Computer Vision — Detection](#computer-vision--detection)
- [🤖 Robotics & Drones](#robotics--drones)
- [🦴 Pose, Segmentation & Depth](#pose-segmentation--depth)
- [🏭 Industrial & Retail](#industrial--retail)
- [🚗 Automotive & ADAS](#automotive--adas)
- [🏥 Healthcare & Medical](#healthcare--medical)
- [🦊 Wildlife & Environment](#wildlife--environment)
- [🎙️ Speech & Audio](#speech--audio)
- [🎨 Creative & Fun](#creative--fun)
- [🔧 Tools & Utilities](#tools--utilities)
- [📚 Tutorials & Learning Resources](#tutorials--learning-resources)

---

## 🎬 YouTube Showcases & Tutorials

*Must-watch videos from creators and the Hailo community*

### Testing Raspberry Pi's AI Kit — 13 TOPS for $70
**Channel:** Jeff Geerling · **Hardware:** Hailo-8L, AI Kit, Raspberry Pi 5

> Jeff Geerling tests the Hailo-8L AI Kit, runs YOLO object detection, and builds a 51 TOPS CoPilot+ PC — without Windows.


<div align="center">

[![Testing Raspberry Pi's AI Kit — 13 TOPS for $70](https://img.youtube.com/vi/HgIMJbN0DS0/hqdefault.jpg)](https://www.youtube.com/watch?v=HgIMJbN0DS0)

**▶️ [Watch: Testing Raspberry Pi's AI Kit — 13 TOPS for $70](https://www.youtube.com/watch?v=HgIMJbN0DS0)**

</div>

---

### On-device GenAI on Raspberry Pi AI HAT+ 2
**Channel:** Hailo · **Hardware:** Hailo-10H, AI HAT+ 2, Raspberry Pi 5

> Full GenAI stack demo — LLM chat, VLM image understanding, Stable Diffusion, and Whisper speech-to-text, all running locally on a $130 board.


<div align="center">

[![On-device GenAI on Raspberry Pi AI HAT+ 2](https://img.youtube.com/vi/8dwVnmcZ9v0/hqdefault.jpg)](https://www.youtube.com/watch?v=8dwVnmcZ9v0)

**▶️ [Watch: On-device GenAI on Raspberry Pi AI HAT+ 2](https://www.youtube.com/watch?v=8dwVnmcZ9v0)**

</div>

---

### LLM Chat Running Offline on Hailo-10H
**Channel:** Hailo · **Hardware:** Hailo-10H

> ChatGPT-style interactive LLM chat with Ollama interface — completely offline, no cloud needed.


<div align="center">

[![LLM Chat Running Offline on Hailo-10H](https://img.youtube.com/vi/ENb7CiL-EYc/hqdefault.jpg)](https://www.youtube.com/watch?v=ENb7CiL-EYc)

**▶️ [Watch: LLM Chat Running Offline on Hailo-10H](https://www.youtube.com/watch?v=ENb7CiL-EYc)**

</div>

---

### Qwen2-VL Vision-Language Model on Hailo-10H
**Channel:** Hailo · **Hardware:** Hailo-10H

> Real-time image analysis and visual Q&A with a 2B parameter VLM running on edge hardware.


<div align="center">

[![Qwen2-VL Vision-Language Model on Hailo-10H](https://img.youtube.com/vi/DkGeRaFxRSE/hqdefault.jpg)](https://www.youtube.com/watch?v=DkGeRaFxRSE)

**▶️ [Watch: Qwen2-VL Vision-Language Model on Hailo-10H](https://www.youtube.com/watch?v=DkGeRaFxRSE)**

</div>

---

### Stable Diffusion on Edge — Text to Image in 5 Seconds
**Channel:** Hailo · **Hardware:** Hailo-10H

> Stable Diffusion 1.5 running fully offline on Hailo-10H. Under 5W power, no cloud.


<div align="center">

[![Stable Diffusion on Edge — Text to Image in 5 Seconds](https://img.youtube.com/vi/rsXylrnyNLM/hqdefault.jpg)](https://www.youtube.com/watch?v=rsXylrnyNLM)

**▶️ [Watch: Stable Diffusion on Edge — Text to Image in 5 Seconds](https://www.youtube.com/watch?v=rsXylrnyNLM)**

</div>

---

### CLIP Zero-Shot Classification — Type Anything, Detect It Live
**Channel:** Hailo · **Hardware:** Hailo-8/8L, Raspberry Pi 5

> Real-time zero-shot classification: type any text prompt and see it matched against live video. Three modes: full-frame, person, face.


<div align="center">

[![CLIP Zero-Shot Classification — Type Anything, Detect It Live](https://img.youtube.com/vi/XXizBHtCLew/hqdefault.jpg)](https://www.youtube.com/watch?v=XXizBHtCLew)

**▶️ [Watch: CLIP Zero-Shot Classification — Type Anything, Detect It Live](https://www.youtube.com/watch?v=XXizBHtCLew)**

</div>

---

### Whisper Speech Recognition on Raspberry Pi + Hailo
**Channel:** Hailo · **Hardware:** Hailo-8, AI HAT+, Raspberry Pi 5

> OpenAI Whisper running on-device with Hailo acceleration. Live microphone transcription in a web app.


<div align="center">

[![Whisper Speech Recognition on Raspberry Pi + Hailo](https://img.youtube.com/vi/rbSKieDLrw4/hqdefault.jpg)](https://www.youtube.com/watch?v=rbSKieDLrw4)

**▶️ [Watch: Whisper Speech Recognition on Raspberry Pi + Hailo](https://www.youtube.com/watch?v=rbSKieDLrw4)**

</div>

---

### YOLO Real-Time Object Detection on Hailo-8
**Channel:** Hailo · **Hardware:** Hailo-8

> YOLOv5m running in real-time at ultra-low power. See how 26 TOPS transforms edge AI.


<div align="center">

[![YOLO Real-Time Object Detection on Hailo-8](https://img.youtube.com/vi/X4xcEUKaA0o/hqdefault.jpg)](https://www.youtube.com/watch?v=X4xcEUKaA0o)

**▶️ [Watch: YOLO Real-Time Object Detection on Hailo-8](https://www.youtube.com/watch?v=X4xcEUKaA0o)**

</div>

---

### Real-Time Object Recognition on RPi 5 + AI HAT+
**Channel:** Hailo · **Hardware:** Hailo-8, AI HAT+, Raspberry Pi 5

> Bringing cutting-edge AI performance to developers on Raspberry Pi 5.


<div align="center">

[![Real-Time Object Recognition on RPi 5 + AI HAT+](https://img.youtube.com/vi/m0O1r1ijFjk/hqdefault.jpg)](https://www.youtube.com/watch?v=m0O1r1ijFjk)

**▶️ [Watch: Real-Time Object Recognition on RPi 5 + AI HAT+](https://www.youtube.com/watch?v=m0O1r1ijFjk)**

</div>

---

### AI Pose Estimation on Raspberry Pi
**Channel:** Hailo · **Hardware:** Hailo-8/8L, AI HAT+, Raspberry Pi 5

> Real-time human body keypoint detection and pose analysis running on edge.


<div align="center">

[![AI Pose Estimation on Raspberry Pi](https://img.youtube.com/vi/xL013eHuSeI/hqdefault.jpg)](https://www.youtube.com/watch?v=xL013eHuSeI)

**▶️ [Watch: AI Pose Estimation on Raspberry Pi](https://www.youtube.com/watch?v=xL013eHuSeI)**

</div>

---

### Husqvarna Automower — AI Lawn Mowing with Hailo-8
**Channel:** Hailo · **Hardware:** Hailo-8

> Production autonomous lawn mower with real-time obstacle detection. No cloud, no fuss — just AI at the edge.


<div align="center">

[![Husqvarna Automower — AI Lawn Mowing with Hailo-8](https://img.youtube.com/vi/auBB_o1GCeU/hqdefault.jpg)](https://www.youtube.com/watch?v=auBB_o1GCeU)

**▶️ [Watch: Husqvarna Automower — AI Lawn Mowing with Hailo-8](https://www.youtube.com/watch?v=auBB_o1GCeU)**

</div>

---

### Dynamic Privacy Masking at 4K30 — Hailo-15
**Channel:** Hailo · **Hardware:** Hailo-15

> Intelligent real-time privacy masking detecting and blurring people in busy office scenes.


<div align="center">

[![Dynamic Privacy Masking at 4K30 — Hailo-15](https://img.youtube.com/vi/YYFCxhCQyuc/hqdefault.jpg)](https://www.youtube.com/watch?v=YYFCxhCQyuc)

**▶️ [Watch: Dynamic Privacy Masking at 4K30 — Hailo-15](https://www.youtube.com/watch?v=YYFCxhCQyuc)**

</div>

---

### Free-Text Video Search — 'Person with Red Backpack'
**Channel:** Hailo · **Hardware:** Hailo-15

> CLIP-powered natural language search across recorded video. Type what you're looking for.


<div align="center">

[![Free-Text Video Search — 'Person with Red Backpack'](https://img.youtube.com/vi/Ocpqzuy2kI4/hqdefault.jpg)](https://www.youtube.com/watch?v=Ocpqzuy2kI4)

**▶️ [Watch: Free-Text Video Search — 'Person with Red Backpack'](https://www.youtube.com/watch?v=Ocpqzuy2kI4)**

</div>

---

### Multi-Camera Person Re-Identification
**Channel:** Hailo · **Hardware:** Hailo-8

> Track the same individual across multiple cameras over time and location.


<div align="center">

[![Multi-Camera Person Re-Identification](https://img.youtube.com/vi/Gos90gTxaWw/hqdefault.jpg)](https://www.youtube.com/watch?v=Gos90gTxaWw)

**▶️ [Watch: Multi-Camera Person Re-Identification](https://www.youtube.com/watch?v=Gos90gTxaWw)**

</div>

---

### 100 Video Channels — AI Analytics on One Server
**Channel:** Hailo · **Hardware:** 8x dual Hailo-8

> 100+ simultaneous video streams with AI on an air-cooled 2U server using 8x dual Hailo-8 modules.


<div align="center">

[![100 Video Channels — AI Analytics on One Server](https://img.youtube.com/vi/zdo8glzoKyo/hqdefault.jpg)](https://www.youtube.com/watch?v=zdo8glzoKyo)

**▶️ [Watch: 100 Video Channels — AI Analytics on One Server](https://www.youtube.com/watch?v=zdo8glzoKyo)**

</div>

---

### Smart City — Multi-Sensor Video Analytics
**Channel:** Hailo · **Hardware:** Hailo-8

> Multiple neural networks on multiple video streams simultaneously for smart city, traffic, and retail.


<div align="center">

[![Smart City — Multi-Sensor Video Analytics](https://img.youtube.com/vi/a70CR94c1ro/hqdefault.jpg)](https://www.youtube.com/watch?v=a70CR94c1ro)

**▶️ [Watch: Smart City — Multi-Sensor Video Analytics](https://www.youtube.com/watch?v=a70CR94c1ro)**

</div>

---

### Limelight 4 — Zero-Code AI Robot Controller
**Channel:** Hailo · **Hardware:** Hailo-8, RPi CM5

> Smart camera for FIRST Robotics competitions, powered by RPi CM5 + Hailo-8.


<div align="center">

[![Limelight 4 — Zero-Code AI Robot Controller](https://img.youtube.com/vi/GUFeYl4cV04/hqdefault.jpg)](https://www.youtube.com/watch?v=GUFeYl4cV04)

**▶️ [Watch: Limelight 4 — Zero-Code AI Robot Controller](https://www.youtube.com/watch?v=GUFeYl4cV04)**

</div>

---

### AI-Powered Surgical Intelligence — Akara
**Channel:** Hailo · **Hardware:** Hailo-8

> Privacy-preserving surgical event tracking in hospitals using thermal sensors and Hailo-8.


<div align="center">

[![AI-Powered Surgical Intelligence — Akara](https://img.youtube.com/vi/rQHs5Ym2VvA/hqdefault.jpg)](https://www.youtube.com/watch?v=rQHs5Ym2VvA)

**▶️ [Watch: AI-Powered Surgical Intelligence — Akara](https://www.youtube.com/watch?v=rQHs5Ym2VvA)**

</div>

---

### ASUS UGen300 — USB AI Accelerator for Any Laptop
**Channel:** Hailo · **Hardware:** Hailo-10H (USB)

> World's first USB edge AI stick with Hailo-10H. Run LLMs and vision AI on any device, offline.


<div align="center">

[![ASUS UGen300 — USB AI Accelerator for Any Laptop](https://img.youtube.com/vi/Pg5hse3lfMs/hqdefault.jpg)](https://www.youtube.com/watch?v=Pg5hse3lfMs)

**▶️ [Watch: ASUS UGen300 — USB AI Accelerator for Any Laptop](https://www.youtube.com/watch?v=Pg5hse3lfMs)**

</div>

---

### AI X-Ray Bag Screening — Evolv eXpedite
**Channel:** Hailo · **Hardware:** Hailo-8 M.2

> Autonomous threat detection in baggage screening for stadiums and high-traffic venues. In production.


<div align="center">

[![AI X-Ray Bag Screening — Evolv eXpedite](https://img.youtube.com/vi/-_QYrpPgKnM/hqdefault.jpg)](https://www.youtube.com/watch?v=-_QYrpPgKnM)

**▶️ [Watch: AI X-Ray Bag Screening — Evolv eXpedite](https://www.youtube.com/watch?v=-_QYrpPgKnM)**

</div>

---

## 🏆 Hackathon Winners (2025)

*Projects from the 3rd annual Hailo Hackathon — 60 employees, 24 hours, Raspberry Pi 5 + AI HAT+*

### TAILO — AI-Powered Smart Pet Companion
![Grade: A](https://img.shields.io/badge/grade-A-brightgreen)

> Privacy-first pet monitoring with behavioral reinforcement, treat dispensing, and AI-driven camera tracking for multi-pet recognition and activity monitoring. 1st place, Hailo Hackathon 2025.

| | |
|---|---|
| **Hardware** | Hailo-8/8L, AI HAT+, Raspberry Pi 5 |
| **GitHub** | [hailo-ai/hailo-rpi5-examples/tree/main/community_projects/TAILO](https://github.com/hailo-ai/hailo-rpi5-examples/tree/main/community_projects/TAILO) |
| **Key Features** | Pet tracking, Treat dispensing, Multi-pet recognition |


<div align="center">

[![TAILO — AI-Powered Smart Pet Companion](https://img.youtube.com/vi/dAok4_63W8E/hqdefault.jpg)](https://www.youtube.com/watch?v=dAok4_63W8E)

**▶️ [Watch: TAILO — AI-Powered Smart Pet Companion](https://www.youtube.com/watch?v=dAok4_63W8E)**

</div>

---

### AD GENIE — Personalized Advertisement
![Grade: A](https://img.shields.io/badge/grade-A-brightgreen)

> Offline AI system using CLIP outfit recognition to deliver fashion-based advertising recommendations on public displays — no cloud dependency. 3rd place, Hailo Hackathon 2025.

| | |
|---|---|
| **Hardware** | Hailo-8/8L, AI HAT+, Raspberry Pi 5 |
| **GitHub** | [hailo-ai/hailo-CLIP/tree/main/community_projects/ad_genie](https://github.com/hailo-ai/hailo-CLIP/tree/main/community_projects/ad_genie) |
| **Key Features** | CLIP, Outfit recognition, Offline ads |


<div align="center">

[![AD GENIE — Personalized Advertisement](https://img.youtube.com/vi/0_v2V7lV514/hqdefault.jpg)](https://www.youtube.com/watch?v=0_v2V7lV514)

**▶️ [Watch: AD GENIE — Personalized Advertisement](https://www.youtube.com/watch?v=0_v2V7lV514)**

</div>

---

### TEMPO — AI Music from Heart Rate
![Grade: B](https://img.shields.io/badge/grade-B-blue)

> AI-generated MIDI music tailored to your heartbeat with real-time synchronization to heart monitors. Applications in adaptive workout music and biofeedback. 2nd place, Hailo Hackathon 2025.

| | |
|---|---|
| **Hardware** | Hailo-8/8L, AI HAT+, Raspberry Pi 5 |
| **GitHub** | [hailo-ai/hailo-rpi5-examples/tree/main/community_projects/TEMPO](https://github.com/hailo-ai/hailo-rpi5-examples/tree/main/community_projects/TEMPO) |
| **Key Features** | MIDI generation, Heart rate sync, Biofeedback |


<div align="center">

[![TEMPO — AI Music from Heart Rate](https://img.youtube.com/vi/nQr9nL7bH3k/hqdefault.jpg)](https://www.youtube.com/watch?v=nQr9nL7bH3k)

**▶️ [Watch: TEMPO — AI Music from Heart Rate](https://www.youtube.com/watch?v=nQr9nL7bH3k)**

</div>

---

### Dynamic Captioning
![Grade: B](https://img.shields.io/badge/grade-B-blue)

> Image captioning using Florence2 on Hailo-8 that updates when the scene changes.

| | |
|---|---|
| **Hardware** | Hailo-8, Raspberry Pi 5 |
| **GitHub** | [hailo-ai/hailo-rpi5-examples/tree/main/community_projects/dynamic_captioning](https://github.com/hailo-ai/hailo-rpi5-examples/tree/main/community_projects/dynamic_captioning) |
| **Key Features** | Florence2, Scene-change aware |


<div align="center">

[![Dynamic Captioning](https://img.youtube.com/vi/kLqhP2z9qtI/hqdefault.jpg)](https://www.youtube.com/watch?v=kLqhP2z9qtI)

**▶️ [Watch: Dynamic Captioning](https://www.youtube.com/watch?v=kLqhP2z9qtI)**

</div>

---

### NavigAItor
![Grade: B](https://img.shields.io/badge/grade-B-blue)

> Autonomous robot navigation using visual landmarks without GPS.

| | |
|---|---|
| **Hardware** | Hailo-8/8L, Raspberry Pi 5 |
| **GitHub** | [hailo-ai/hailo-rpi5-examples/tree/main/community_projects/Navigator](https://github.com/hailo-ai/hailo-rpi5-examples/tree/main/community_projects/Navigator) |
| **Key Features** | Visual SLAM, No GPS, Autonomous navigation |


<div align="center">

[![NavigAItor](https://img.youtube.com/vi/E0Z55e1KyOo/hqdefault.jpg)](https://www.youtube.com/watch?v=E0Z55e1KyOo)

**▶️ [Watch: NavigAItor](https://www.youtube.com/watch?v=E0Z55e1KyOo)**

</div>

---

### B-AI-BY Monitor
![Grade: B](https://img.shields.io/badge/grade-B-blue)

> Smart baby monitor with cry and activity detection using CLIP, real-time alerts.

| | |
|---|---|
| **Hardware** | Hailo-8/8L, Raspberry Pi 5 |
| **GitHub** | [hailo-ai/hailo-CLIP/tree/main/community_projects/baiby_monitor](https://github.com/hailo-ai/hailo-CLIP/tree/main/community_projects/baiby_monitor) |
| **Key Features** | CLIP, Cry detection, Activity alerts |


<div align="center">

[![B-AI-BY Monitor](https://img.youtube.com/vi/sXgL5g_A-u0/hqdefault.jpg)](https://www.youtube.com/watch?v=sXgL5g_A-u0)

**▶️ [Watch: B-AI-BY Monitor](https://www.youtube.com/watch?v=sXgL5g_A-u0)**

</div>

---

### ChessMate (RoboChess)
![Grade: B](https://img.shields.io/badge/grade-B-blue)

> Fully automated robotic chess system with AI-powered piece detection.

| | |
|---|---|
| **Hardware** | Hailo-8/8L, Raspberry Pi 5 |
| **GitHub** | [hailo-ai/hailo-rpi5-examples/tree/main/community_projects/RoboChess](https://github.com/hailo-ai/hailo-rpi5-examples/tree/main/community_projects/RoboChess) |
| **Key Features** | Robotic arm, Piece detection, Full game play |


<div align="center">

[![ChessMate (RoboChess)](https://img.youtube.com/vi/aXNgmYCEgDc/hqdefault.jpg)](https://www.youtube.com/watch?v=aXNgmYCEgDc)

**▶️ [Watch: ChessMate (RoboChess)](https://www.youtube.com/watch?v=aXNgmYCEgDc)**

</div>

---

### HailoGames (Sailted Fish)
![Grade: C](https://img.shields.io/badge/grade-C-yellow)

> 'Red Light, Green Light' game using real-time pose estimation.

| | |
|---|---|
| **Hardware** | Hailo-8/8L, Raspberry Pi 5 |
| **GitHub** | [hailo-ai/hailo-rpi5-examples/tree/main/community_projects/sailted_fish](https://github.com/hailo-ai/hailo-rpi5-examples/tree/main/community_projects/sailted_fish) |
| **Key Features** | Pose estimation, Game logic |


<div align="center">

[![HailoGames (Sailted Fish)](https://img.youtube.com/vi/q8ZG8zzRlzE/hqdefault.jpg)](https://www.youtube.com/watch?v=q8ZG8zzRlzE)

**▶️ [Watch: HailoGames (Sailted Fish)](https://www.youtube.com/watch?v=q8ZG8zzRlzE)**

</div>

---

## 🧠 GenAI & LLM Projects

*On-device large language models, vision-language models, image generation, and AI agents*

### be-more-hailo — Local AI Agent
![Grade: A](https://img.shields.io/badge/grade-A-brightgreen) [![Stars](https://img.shields.io/github/stars/moorew/be-more-hailo?style=social)](https://github.com/moorew/be-more-hailo) ![Last Commit](https://img.shields.io/github/last-commit/moorew/be-more-hailo)

> Fully local AI agent on Raspberry Pi 5 — listens for wake word ('Hey BMO'), understands speech via Whisper, reasons with Qwen 2.5 1.5B LLM, uses Qwen2-VL-2B for vision, responds with TTS. Features animated face GUI, timers, minigames, web interface, and Tailscale remote access.

| | |
|---|---|
| **Hardware** | Hailo-10H, AI HAT+ 2, Raspberry Pi 5 |
| **GitHub** | [moorew/be-more-hailo](https://github.com/moorew/be-more-hailo) |
| **Key Features** | Wake word, LLM, VLM, TTS, Web UI, Tailscale |

---

### Hailo-10H Multi-Service AI Platform
![Grade: B](https://img.shields.io/badge/grade-B-blue) [![Stars](https://img.shields.io/github/stars/gregm123456/raspberry_pi_hailo_ai_services?style=social)](https://github.com/gregm123456/raspberry_pi_hailo_ai_services) ![Last Commit](https://img.shields.io/github/last-commit/gregm123456/raspberry_pi_hailo_ai_services)

> Runs 8 concurrent AI services (vision, CLIP, Whisper, OCR, pose, depth, TTS, LLM) with intelligent device management, Gradio web portal, and Unix socket IPC.

| | |
|---|---|
| **Hardware** | Hailo-10H, Raspberry Pi 5 |
| **GitHub** | [gregm123456/raspberry_pi_hailo_ai_services](https://github.com/gregm123456/raspberry_pi_hailo_ai_services) |
| **Key Features** | 8 services, Gradio portal, Device manager |

---

### PiSovereign — Privacy-First AI Assistant
![Grade: C](https://img.shields.io/badge/grade-C-yellow) [![Stars](https://img.shields.io/github/stars/twohreichel/PiSovereign?style=social)](https://github.com/twohreichel/PiSovereign) ![Last Commit](https://img.shields.io/github/last-commit/twohreichel/PiSovereign)

> Self-hosted, privacy-first AI assistant platform with Docker Compose. Built in Rust.

| | |
|---|---|
| **Hardware** | Hailo, Raspberry Pi |
| **GitHub** | [twohreichel/PiSovereign](https://github.com/twohreichel/PiSovereign) |

---

### Hailo-10H LLM Demo

> ChatGPT-style interactive offline LLM chat using Ollama interface — no internet required.

| | |
|---|---|
| **Hardware** | Hailo-10H |
| **Official Demo** | [hailo.ai](https://hailo.ai/resources/industries/personal-compute/llm-demo-with-hailo-10h-ai-accelerator/) |


<div align="center">

[![Hailo-10H LLM Demo](https://img.youtube.com/vi/ENb7CiL-EYc/hqdefault.jpg)](https://www.youtube.com/watch?v=ENb7CiL-EYc)

**▶️ [Watch: Hailo-10H LLM Demo](https://www.youtube.com/watch?v=ENb7CiL-EYc)**

</div>

---

### Hailo-10H VLM Demo

> Qwen2-VL (2B params) vision-language model for real-time image analysis, visual Q&A, and chatbots.

| | |
|---|---|
| **Hardware** | Hailo-10H |
| **Official Demo** | [hailo.ai](https://hailo.ai/resources/industries/personal-compute/vlm-demo-with-hailo-10h-ai-accelerator/) |


<div align="center">

[![Hailo-10H VLM Demo](https://img.youtube.com/vi/DkGeRaFxRSE/hqdefault.jpg)](https://www.youtube.com/watch?v=DkGeRaFxRSE)

**▶️ [Watch: Hailo-10H VLM Demo](https://www.youtube.com/watch?v=DkGeRaFxRSE)**

</div>

---

### Stable Diffusion on the Edge

> Text-to-image generation with Stable Diffusion 1.5/2.1 running fully offline. Under 5 seconds per image at under 5W power.

| | |
|---|---|
| **Hardware** | Hailo-10H |
| **Official Demo** | [hailo.ai](https://hailo.ai/resources/industries/personal-compute/hailo-10h-demo-stable-diffusion-on-the-edge/) |


<div align="center">

[![Stable Diffusion on the Edge](https://img.youtube.com/vi/rsXylrnyNLM/hqdefault.jpg)](https://www.youtube.com/watch?v=rsXylrnyNLM)

**▶️ [Watch: Stable Diffusion on the Edge](https://www.youtube.com/watch?v=rsXylrnyNLM)**

</div>

---

### On-device GenAI on RPi AI HAT+ 2

> Full GenAI stack demo — LLM, VLM, image generation, and speech recognition all running locally on Raspberry Pi 5.

| | |
|---|---|
| **Hardware** | Hailo-10H, AI HAT+ 2, Raspberry Pi 5 |
| **Official Demo** | [hailo.ai](https://hailo.ai/resources/industries/personal-compute/on-device-genai-on-raspberry-pi-ai-hat-2-with-hailo-10h/) |


<div align="center">

[![On-device GenAI on RPi AI HAT+ 2](https://img.youtube.com/vi/8dwVnmcZ9v0/hqdefault.jpg)](https://www.youtube.com/watch?v=8dwVnmcZ9v0)

**▶️ [Watch: On-device GenAI on RPi AI HAT+ 2](https://www.youtube.com/watch?v=8dwVnmcZ9v0)**

</div>

---

### ASUS UGen300 USB AI Accelerator
![Status](https://img.shields.io/badge/status-production-brightgreen)

> World's first USB edge AI accelerator for laptops — enables offline LLM, VLM, and classic vision workloads on any device.

| | |
|---|---|
| **Hardware** | Hailo-10H (USB) |
| **Official Demo** | [hailo.ai](https://hailo.ai/resources/industries/personal-compute/asus-ugen300-powered-by-hailo-10h-on-device-ai-anywhere/) |
| **Partner** | ASUS |


<div align="center">

[![ASUS UGen300 USB AI Accelerator](https://img.youtube.com/vi/Pg5hse3lfMs/hqdefault.jpg)](https://www.youtube.com/watch?v=Pg5hse3lfMs)

**▶️ [Watch: ASUS UGen300 USB AI Accelerator](https://www.youtube.com/watch?v=Pg5hse3lfMs)**

</div>

---

### RPI-Hailo-Hat-Ollama
![Grade: C](https://img.shields.io/badge/grade-C-yellow) [![Stars](https://img.shields.io/github/stars/DWestbury-PP/RPI-Hailo-Hat-Ollama?style=social)](https://github.com/DWestbury-PP/RPI-Hailo-Hat-Ollama) ![Last Commit](https://img.shields.io/github/last-commit/DWestbury-PP/RPI-Hailo-Hat-Ollama)

> Run local LLMs (Llama 3.2, Qwen, DeepSeek) via Ollama-compatible API with Open WebUI on AI HAT+ 2.

| | |
|---|---|
| **Hardware** | Hailo-10H, AI HAT+ 2, Raspberry Pi 5 |
| **GitHub** | [DWestbury-PP/RPI-Hailo-Hat-Ollama](https://github.com/DWestbury-PP/RPI-Hailo-Hat-Ollama) |
| **Key Features** | Ollama, Open WebUI, systemd autostart |

---

### HP AI Accelerator for Retail
![Status](https://img.shields.io/badge/status-production-brightgreen)

> First commercial Hailo-10H solution for point-of-sale: cashier-less checkout, personalized ads, theft prevention.

| | |
|---|---|
| **Hardware** | Hailo-10H (M.2) |
| **Official Demo** | [hailo.ai](https://hailo.ai/company-overview/newsroom/news/hp-selects-hailos-next-gen-ai-accelerator-to-transform-retail-and-hospitality-operations/) |
| **Partner** | HP |

---

## 🏠 Smart Home & Surveillance

*NVR systems, Home Assistant integrations, multi-camera analytics, and privacy solutions*

### Frigate NVR with Hailo
![Grade: A](https://img.shields.io/badge/grade-A-brightgreen) [![Stars](https://img.shields.io/github/stars/theNetworkChuck/frigate-nvr-guide?style=social)](https://github.com/theNetworkChuck/frigate-nvr-guide) ![Last Commit](https://img.shields.io/github/last-commit/theNetworkChuck/frigate-nvr-guide)

> Complete local AI surveillance system — object detection, motion recording, face recognition, semantic search, PTZ control, Home Assistant integration. Official Hailo support since Frigate v0.16.0.

| | |
|---|---|
| **Hardware** | Hailo-8L, AI HAT |
| **GitHub** | [theNetworkChuck/frigate-nvr-guide](https://github.com/theNetworkChuck/frigate-nvr-guide) |
| **Key Features** | AI detection, HA integration, Semantic search, PTZ |

---

### Mini Object Detection Server
![Grade: B](https://img.shields.io/badge/grade-B-blue) [![Stars](https://img.shields.io/github/stars/serg987/hailo-mini-od-server?style=social)](https://github.com/serg987/hailo-mini-od-server) ![Last Commit](https://img.shields.io/github/last-commit/serg987/hailo-mini-od-server)

> CodeProject.AI-compatible REST API server for Frigate/Blue Iris NVR integration. 300-600MB RAM, Docker support, multiple YOLO models.

| | |
|---|---|
| **Hardware** | Hailo-8/8L |
| **GitHub** | [serg987/hailo-mini-od-server](https://github.com/serg987/hailo-mini-od-server) |
| **Key Features** | REST API, Docker, Web UI, CodeProject.AI compatible |

---

### Hailo Libero 3.0 for Home Assistant
![Grade: B](https://img.shields.io/badge/grade-B-blue) [![Stars](https://img.shields.io/github/stars/voldemarpanso/ha_hailolibero?style=social)](https://github.com/voldemarpanso/ha_hailolibero) ![Last Commit](https://img.shields.io/github/last-commit/voldemarpanso/ha_hailolibero)

> HACS-compatible Home Assistant custom integration for Hailo devices.

| | |
|---|---|
| **Hardware** | Hailo |
| **GitHub** | [voldemarpanso/ha_hailolibero](https://github.com/voldemarpanso/ha_hailolibero) |
| **Key Features** | HACS, Home Assistant |

---

### HailoHome — Smart Home AI
![Grade: C](https://img.shields.io/badge/grade-C-yellow) [![Stars](https://img.shields.io/github/stars/imvipgit/HailoHome?style=social)](https://github.com/imvipgit/HailoHome) ![Last Commit](https://img.shields.io/github/last-commit/imvipgit/HailoHome)

> Fully offline smart home assistant with wake word detection, STT, TTS, face recognition, Home Assistant integration, and learning systems.

| | |
|---|---|
| **Hardware** | Hailo-8, Raspberry Pi |
| **GitHub** | [imvipgit/HailoHome](https://github.com/imvipgit/HailoHome) |
| **Key Features** | Wake word, STT, TTS, Face recognition, HA integration |

---

### Smart Retail with reComputer
[![Stars](https://img.shields.io/github/stars/Seeed-Projects/Smart-Retail-with-reComputerR11-and-AI-kit?style=social)](https://github.com/Seeed-Projects/Smart-Retail-with-reComputerR11-and-AI-kit) ![Last Commit](https://img.shields.io/github/last-commit/Seeed-Projects/Smart-Retail-with-reComputerR11-and-AI-kit)

> Intelligent retail system with YOLOv8n product detection, intrusion detection, Node-RED dashboard, and RS485 controls.

| | |
|---|---|
| **Hardware** | Hailo (AI Kit) |
| **GitHub** | [Seeed-Projects/Smart-Retail-with-reComputerR11-and-AI-kit](https://github.com/Seeed-Projects/Smart-Retail-with-reComputerR11-and-AI-kit) |
| **Key Features** | YOLOv8n, Node-RED, Intrusion detection |

---

### Multi-Camera Multi-Person Re-Identification

> Track the same individual across multiple cameras over time and location changes.

| | |
|---|---|
| **Hardware** | Hailo-8 |
| **Official Demo** | [hailo.ai](https://hailo.ai/resources/industries/security/multi-camera-multi-person-re-identification-demo/) |


<div align="center">

[![Multi-Camera Multi-Person Re-Identification](https://img.youtube.com/vi/Gos90gTxaWw/hqdefault.jpg)](https://www.youtube.com/watch?v=Gos90gTxaWw)

**▶️ [Watch: Multi-Camera Multi-Person Re-Identification](https://www.youtube.com/watch?v=Gos90gTxaWw)**

</div>

---

### Multi-Sensor Smart City Analytics

> Multiple neural networks on multiple video streams simultaneously in real-time for smart city, ITS, retail, and industrial automation.

| | |
|---|---|
| **Hardware** | Hailo-8 |
| **Official Demo** | [hailo.ai](https://hailo.ai/resources/industries/security/multi-sensor-intelligent-video-analytics-for-smart-city/) |


<div align="center">

[![Multi-Sensor Smart City Analytics](https://img.youtube.com/vi/a70CR94c1ro/hqdefault.jpg)](https://www.youtube.com/watch?v=a70CR94c1ro)

**▶️ [Watch: Multi-Sensor Smart City Analytics](https://www.youtube.com/watch?v=a70CR94c1ro)**

</div>

---

### 100-Channel VMS Analytics

> 100+ simultaneous video channels with AI analytics on an air-cooled 2U server.

| | |
|---|---|
| **Hardware** | 8x dual Hailo-8 modules |
| **Partner** | Network Optix EVOS |


<div align="center">

[![100-Channel VMS Analytics](https://img.youtube.com/vi/zdo8glzoKyo/hqdefault.jpg)](https://www.youtube.com/watch?v=zdo8glzoKyo)

**▶️ [Watch: 100-Channel VMS Analytics](https://www.youtube.com/watch?v=zdo8glzoKyo)**

</div>

---

### Dynamic Privacy Masking (Hailo-15)

> Real-time 4K30 intelligent privacy masking detecting and masking people in busy scenes.

| | |
|---|---|
| **Hardware** | Hailo-15 |
| **Official Demo** | [hailo.ai](https://hailo.ai/resources/industries/security/dpm-with-hailo-15-ai-vision-processor/) |


<div align="center">

[![Dynamic Privacy Masking (Hailo-15)](https://img.youtube.com/vi/YYFCxhCQyuc/hqdefault.jpg)](https://www.youtube.com/watch?v=YYFCxhCQyuc)

**▶️ [Watch: Dynamic Privacy Masking (Hailo-15)](https://www.youtube.com/watch?v=YYFCxhCQyuc)**

</div>

---

### Free-Text Video Search (Hailo-15)

> CLIP-based natural language search across recorded video. Search queries like 'person with red backpack near entrance.'

| | |
|---|---|
| **Hardware** | Hailo-15 |
| **Official Demo** | [hailo.ai](https://hailo.ai/resources/industries/security/free-text-video-search-powered-by-hailo-15/) |


<div align="center">

[![Free-Text Video Search (Hailo-15)](https://img.youtube.com/vi/Ocpqzuy2kI4/hqdefault.jpg)](https://www.youtube.com/watch?v=Ocpqzuy2kI4)

**▶️ [Watch: Free-Text Video Search (Hailo-15)](https://www.youtube.com/watch?v=Ocpqzuy2kI4)**

</div>

---

### Evolv eXpedite AI X-Ray Screening
![Status](https://img.shields.io/badge/status-production-brightgreen)

> Autonomous threat detection in baggage screening for high-traffic venues.

| | |
|---|---|
| **Hardware** | Hailo-8 M.2 |
| **Official Demo** | [hailo.ai](https://hailo.ai/resources/industries/security/evolv-expedite-ai-powered-x-ray-bag-screening-with-hailo-8-m-2-ai-acceleration-module/) |
| **Partner** | Evolv, Advantech |


<div align="center">

[![Evolv eXpedite AI X-Ray Screening](https://img.youtube.com/vi/-_QYrpPgKnM/hqdefault.jpg)](https://www.youtube.com/watch?v=-_QYrpPgKnM)

**▶️ [Watch: Evolv eXpedite AI X-Ray Screening](https://www.youtube.com/watch?v=-_QYrpPgKnM)**

</div>

---

### Art of Logic City+ Smart City Security
![Status](https://img.shields.io/badge/status-production-brightgreen)

> 10 IP cameras monitoring 65 parking spots in Sydney — 75-80% drop in repeat offenders. Solar/wind powered.

| | |
|---|---|
| **Hardware** | Hailo-8 |
| **Official Demo** | [hailo.ai](https://hailo.ai/resources/industries/security/art-of-logic-city-smart-city-security-solution/) |
| **Partner** | Art of Logic |

---

## 👁️ Computer Vision — Detection

*Object detection, face recognition, license plate reading, and zero-shot classification*

### CLIP Zero-Shot Classification
![Grade: A](https://img.shields.io/badge/grade-A-brightgreen) [![Stars](https://img.shields.io/github/stars/hailo-ai/hailo-CLIP?style=social)](https://github.com/hailo-ai/hailo-CLIP) ![Last Commit](https://img.shields.io/github/last-commit/hailo-ai/hailo-CLIP)

> Real-time zero-shot classification using CLIP — type any text prompt and match it against live video. Three modes: full-frame, person, face. Includes threshold slider and probability bars.

| | |
|---|---|
| **Hardware** | Hailo-8/8L, Raspberry Pi 5 |
| **GitHub** | [hailo-ai/hailo-CLIP](https://github.com/hailo-ai/hailo-CLIP) |
| **Key Features** | Zero-shot, 3 modes, Threshold slider |


<div align="center">

[![CLIP Zero-Shot Classification](https://img.youtube.com/vi/XXizBHtCLew/hqdefault.jpg)](https://www.youtube.com/watch?v=XXizBHtCLew)

**▶️ [Watch: CLIP Zero-Shot Classification](https://www.youtube.com/watch?v=XXizBHtCLew)**

</div>

---

### YOLOv11 Tracker with Speed & Loitering
![Grade: B](https://img.shields.io/badge/grade-B-blue) [![Stars](https://img.shields.io/github/stars/Seeed-Projects/YOLOv11-Hailo-Tracker?style=social)](https://github.com/Seeed-Projects/YOLOv11-Hailo-Tracker) ![Last Commit](https://img.shields.io/github/last-commit/Seeed-Projects/YOLOv11-Hailo-Tracker)

> Real-time detection with ByteTrack tracking, speed estimation, and loitering detection. Web dashboard included.

| | |
|---|---|
| **Hardware** | Hailo-8 |
| **GitHub** | [Seeed-Projects/YOLOv11-Hailo-Tracker](https://github.com/Seeed-Projects/YOLOv11-Hailo-Tracker) |
| **Key Features** | ByteTrack, Speed estimation, Loitering detection, Web dashboard |

---

### Face Recognition API
![Grade: B](https://img.shields.io/badge/grade-B-blue) [![Stars](https://img.shields.io/github/stars/Seeed-Solution/face-recognition-api?style=social)](https://github.com/Seeed-Solution/face-recognition-api) ![Last Commit](https://img.shields.io/github/last-commit/Seeed-Solution/face-recognition-api)

> 512-dimension face embedding generation at 3-18ms latency. Uses ArcFace + SCRFD models with SQLite vector DB. 28 tests.

| | |
|---|---|
| **Hardware** | Hailo-8 |
| **GitHub** | [Seeed-Solution/face-recognition-api](https://github.com/Seeed-Solution/face-recognition-api) |
| **Key Features** | REST API, ArcFace, SCRFD, Vector DB |

---

### Real-Time Emotion Detection
![Grade: C](https://img.shields.io/badge/grade-C-yellow) [![Stars](https://img.shields.io/github/stars/NecheSeTopper/hailo8-realtime-emotion-detection?style=social)](https://github.com/NecheSeTopper/hailo8-realtime-emotion-detection) ![Last Commit](https://img.shields.io/github/last-commit/NecheSeTopper/hailo8-realtime-emotion-detection)

> 7-class facial emotion detection at 30-40 FPS with 15-20ms latency. INT8 quantized, FER2013 benchmark (61.7%).

| | |
|---|---|
| **Hardware** | Hailo-8, Raspberry Pi 5 |
| **GitHub** | [NecheSeTopper/hailo8-realtime-emotion-detection](https://github.com/NecheSeTopper/hailo8-realtime-emotion-detection) |
| **Key Features** | 7 emotions, 30-40 FPS, INT8 |

---

### YOLO 4K Detection on Hailo-10H

> Real-time YOLO object detection on 4K video streams using Hailo-10H.

| | |
|---|---|
| **Hardware** | Hailo-10H |
| **Official Demo** | [hailo.ai](https://hailo.ai/resources/industries/personal-compute/object-detection-demo-with-hailo-10h-ai-accelerator/) |


<div align="center">

[![YOLO 4K Detection on Hailo-10H](https://img.youtube.com/vi/2W7IUimI-IQ/hqdefault.jpg)](https://www.youtube.com/watch?v=2W7IUimI-IQ)

**▶️ [Watch: YOLO 4K Detection on Hailo-10H](https://www.youtube.com/watch?v=2W7IUimI-IQ)**

</div>

---

### YOLO on Hailo-8

> YOLOv5m running real-time at ultra-low power consumption on Hailo-8.

| | |
|---|---|
| **Hardware** | Hailo-8 |


<div align="center">

[![YOLO on Hailo-8](https://img.youtube.com/vi/X4xcEUKaA0o/hqdefault.jpg)](https://www.youtube.com/watch?v=X4xcEUKaA0o)

**▶️ [Watch: YOLO on Hailo-8](https://www.youtube.com/watch?v=X4xcEUKaA0o)**

</div>

---

### Real-Time Detection on RPi5 + AI HAT+

> Cutting-edge AI performance for developers doing real-time computer vision on Raspberry Pi 5.

| | |
|---|---|
| **Hardware** | Hailo-8, AI HAT+, Raspberry Pi 5 |


<div align="center">

[![Real-Time Detection on RPi5 + AI HAT+](https://img.youtube.com/vi/m0O1r1ijFjk/hqdefault.jpg)](https://www.youtube.com/watch?v=m0O1r1ijFjk)

**▶️ [Watch: Real-Time Detection on RPi5 + AI HAT+](https://www.youtube.com/watch?v=m0O1r1ijFjk)**

</div>

---

### Detection with RPi AI Kit

> Fast, power-efficient AI processing with the $70 Raspberry Pi AI Kit.

| | |
|---|---|
| **Hardware** | Hailo-8L, AI Kit, Raspberry Pi 5 |


<div align="center">

[![Detection with RPi AI Kit](https://img.youtube.com/vi/-huMW13Fp7U/hqdefault.jpg)](https://www.youtube.com/watch?v=-huMW13Fp7U)

**▶️ [Watch: Detection with RPi AI Kit](https://www.youtube.com/watch?v=-huMW13Fp7U)**

</div>

---

### License Plate Recognition (High-Speed)

> 3-network pipeline (vehicle detection + plate detection + LPRNet OCR) on GStreamer, real-time 1080p.

| | |
|---|---|
| **Hardware** | Hailo-8 |
| **Official Demo** | [hailo.ai](https://hailo.ai/resources/industries/security/license-plate-recognition-for-high-speed-vehicles/) |

---

## 🤖 Robotics & Drones

*ROS2 integrations, autonomous drones, competition robots, and agricultural bots*

### Hailo TAPPAS + ROS2
![Grade: B](https://img.shields.io/badge/grade-B-blue) [![Stars](https://img.shields.io/github/stars/kyrikakis/hailo_tappas_ros2?style=social)](https://github.com/kyrikakis/hailo_tappas_ros2) ![Last Commit](https://img.shields.io/github/last-commit/kyrikakis/hailo_tappas_ros2)

> Combines Hailo TAPPAS and ROS2 for edge AI in robotics — YOLO, face recognition, object detection with ROS2 Jazzy. Docker container available.

| | |
|---|---|
| **Hardware** | Hailo-8 |
| **GitHub** | [kyrikakis/hailo_tappas_ros2](https://github.com/kyrikakis/hailo_tappas_ros2) |
| **Key Features** | ROS2 Jazzy, Docker, YOLO, Face recognition |

---

### OpenCastor — AI Robotics Framework
![Grade: B](https://img.shields.io/badge/grade-B-blue) [![Stars](https://img.shields.io/github/stars/craigm26/OpenCastor?style=social)](https://github.com/craigm26/OpenCastor) ![Last Commit](https://img.shields.io/github/last-commit/craigm26/OpenCastor)

> Open-source AI robotics framework with tiered brain, 8 AI providers, multi-robot swarm, and self-improving loop.

| | |
|---|---|
| **Hardware** | Hailo, OAK-D |
| **GitHub** | [craigm26/OpenCastor](https://github.com/craigm26/OpenCastor) |
| **Key Features** | Swarm robotics, 8 AI providers, Self-improving |

---

### PX4-ROS2 Drone Payload Drop
![Grade: B](https://img.shields.io/badge/grade-B-blue) [![Stars](https://img.shields.io/github/stars/GAUTHAMPSANKAR/PX4-ROS2-hailo-payload-drop?style=social)](https://github.com/GAUTHAMPSANKAR/PX4-ROS2-hailo-payload-drop) ![Last Commit](https://img.shields.io/github/last-commit/GAUTHAMPSANKAR/PX4-ROS2-hailo-payload-drop)

> PX4 + ROS2 autonomous payload-drop system with YOLOv8 real-time detection. Includes Gazebo simulation.

| | |
|---|---|
| **Hardware** | Hailo-8L |
| **GitHub** | [GAUTHAMPSANKAR/PX4-ROS2-hailo-payload-drop](https://github.com/GAUTHAMPSANKAR/PX4-ROS2-hailo-payload-drop) |
| **Key Features** | PX4, ROS2, YOLOv8, Gazebo sim |

---

### GAP-Bot Agricultural Hexapod
![Grade: C](https://img.shields.io/badge/grade-C-yellow) [![Stars](https://img.shields.io/github/stars/PelleNybe/CoraxCoLABs-GAP-GreenAutomatedPlatform---GAPbot?style=social)](https://github.com/PelleNybe/CoraxCoLABs-GAP-GreenAutomatedPlatform---GAPbot) ![Last Commit](https://img.shields.io/github/last-commit/PelleNybe/CoraxCoLABs-GAP-GreenAutomatedPlatform---GAPbot)

> Edge AI hexapod robot for agricultural automation using ROS2.

| | |
|---|---|
| **Hardware** | Hailo-8L |
| **GitHub** | [PelleNybe/CoraxCoLABs-GAP-GreenAutomatedPlatform---GAPbot](https://github.com/PelleNybe/CoraxCoLABs-GAP-GreenAutomatedPlatform---GAPbot) |
| **Key Features** | ROS2, Hexapod, AgTech |

---

### Lego NXT2 + Hailo
[![Stars](https://img.shields.io/github/stars/schnaggelz/rpi-nxt2?style=social)](https://github.com/schnaggelz/rpi-nxt2) ![Last Commit](https://img.shields.io/github/last-commit/schnaggelz/rpi-nxt2)

> Lego NXT2 C/C++ firmware with AI capabilities via RPi5 + Hailo.

| | |
|---|---|
| **Hardware** | Hailo-8, Raspberry Pi 5 |
| **GitHub** | [schnaggelz/rpi-nxt2](https://github.com/schnaggelz/rpi-nxt2) |

---

### Klevor — WRO Competition Robot
[![Stars](https://img.shields.io/github/stars/teamsteelbot/klevor?style=social)](https://github.com/teamsteelbot/klevor) ![Last Commit](https://img.shields.io/github/last-commit/teamsteelbot/klevor)

> Autonomous robotics using YOLOv11 for WRO 2025 competition.

| | |
|---|---|
| **Hardware** | Hailo-8 |
| **GitHub** | [teamsteelbot/klevor](https://github.com/teamsteelbot/klevor) |
| **Key Features** | YOLOv11, WRO |

---

### Limelight 4 — AI Robot Controller

> Zero-code smart camera and robot controller for FIRST Robotics competitions.

| | |
|---|---|
| **Hardware** | Hailo-8, RPi CM5 |
| **Official Demo** | [hailo.ai](https://hailo.ai/resources/industries/security/limelight-4-ai-powered-robot-controller/) |
| **Partner** | Limelight Vision |


<div align="center">

[![Limelight 4 — AI Robot Controller](https://img.youtube.com/vi/GUFeYl4cV04/hqdefault.jpg)](https://www.youtube.com/watch?v=GUFeYl4cV04)

**▶️ [Watch: Limelight 4 — AI Robot Controller](https://www.youtube.com/watch?v=GUFeYl4cV04)**

</div>

---

### Husqvarna Automower with Hailo-8
![Status](https://img.shields.io/badge/status-production-brightgreen)

> AI-powered autonomous lawn mower with real-time obstacle detection, no cloud needed.

| | |
|---|---|
| **Hardware** | Hailo-8 |
| **Official Demo** | [hailo.ai](https://hailo.ai/resources/industries/industrial-automation/smarter-autonomy-at-the-edge-husqvarna-automower-with-hailo-8/) |
| **Partner** | Husqvarna |


<div align="center">

[![Husqvarna Automower with Hailo-8](https://img.youtube.com/vi/auBB_o1GCeU/hqdefault.jpg)](https://www.youtube.com/watch?v=auBB_o1GCeU)

**▶️ [Watch: Husqvarna Automower with Hailo-8](https://www.youtube.com/watch?v=auBB_o1GCeU)**

</div>

---

### Hailo AI for Drones

> People counting, face detection on drone platform (Astrial board).

| | |
|---|---|
| **Hardware** | Hailo-8, Hailo-15 |
| **Official Demo** | [hailo.ai](https://hailo.ai/resources/industries/drones/hailo-ai-processors-for-drones/) |
| **Partner** | System Electronics |

---

## 🦴 Pose, Segmentation & Depth

*Human pose estimation, semantic segmentation, and monocular depth estimation*

### Bird's Eye View Perception
[![Stars](https://img.shields.io/github/stars/hailo-ai/hailo-BEV?style=social)](https://github.com/hailo-ai/hailo-BEV) ![Last Commit](https://img.shields.io/github/last-commit/hailo-ai/hailo-BEV)

> Multi-view 3D object detection for autonomous driving, based on PETR architecture.

| | |
|---|---|
| **Hardware** | Hailo-8 |
| **GitHub** | [hailo-ai/hailo-BEV](https://github.com/hailo-ai/hailo-BEV) |

---

### Pose Estimation on Raspberry Pi

> Real-time human body keypoint detection and pose analysis on Raspberry Pi with Hailo.

| | |
|---|---|
| **Hardware** | Hailo-8/8L, AI HAT+, Raspberry Pi 5 |
| **Official Demo** | [hailo.ai](https://hailo.ai/resources/industries/security/raspberry-pi-ai-kit-pose-estimation/) |


<div align="center">

[![Pose Estimation on Raspberry Pi](https://img.youtube.com/vi/xL013eHuSeI/hqdefault.jpg)](https://www.youtube.com/watch?v=xL013eHuSeI)

**▶️ [Watch: Pose Estimation on Raspberry Pi](https://www.youtube.com/watch?v=xL013eHuSeI)**

</div>

---

### Subject Segmentation on Raspberry Pi

> Real-time image segmentation on single-board computer.

| | |
|---|---|
| **Hardware** | Hailo-8/8L, AI Kit |
| **Official Demo** | [hailo.ai](https://hailo.ai/resources/industries/automotive/raspberry-pi-ai-kit-subject-segmentation/) |

---

### Depth + Detection from Mono Camera

> Combined depth estimation and object detection from a single camera — useful for automotive and industrial.

| | |
|---|---|
| **Hardware** | Hailo-8 |
| **Official Demo** | [hailo.ai](https://ai.hailo.ai/depth-estimation-and-object-detection-for-mono-camera) |

---

## 🏭 Industrial & Retail

*Manufacturing inspection, conveyor sorting, retail analytics, and ruggedized controllers*

### Xplorer Industrial Controller
![Grade: C](https://img.shields.io/badge/grade-C-yellow) [![Stars](https://img.shields.io/github/stars/austral-electronics/Xplorer?style=social)](https://github.com/austral-electronics/Xplorer) ![Last Commit](https://img.shields.io/github/last-commit/austral-electronics/Xplorer)

> Rugged industrial and marine edge IoT/AIoT controller with GNSS, Zigbee, 4G LTE, NMEA2000, Frigate, and Home Assistant integration.

| | |
|---|---|
| **Hardware** | Hailo, RPi5/CM5 |
| **GitHub** | [austral-electronics/Xplorer](https://github.com/austral-electronics/Xplorer) |
| **Key Features** | GNSS, Zigbee, 4G, Frigate, HA |

---

### VisionSort-RPi — Conveyor Belt Sorting
![Grade: C](https://img.shields.io/badge/grade-C-yellow) [![Stars](https://img.shields.io/github/stars/GBR-RL/VisionSort-RPi?style=social)](https://github.com/GBR-RL/VisionSort-RPi) ![Last Commit](https://img.shields.io/github/last-commit/GBR-RL/VisionSort-RPi)

> Conveyor belt sorting system using YOLOv8 for real-time object detection and automated sorting.

| | |
|---|---|
| **Hardware** | Hailo-8, Raspberry Pi |
| **GitHub** | [GBR-RL/VisionSort-RPi](https://github.com/GBR-RL/VisionSort-RPi) |
| **Key Features** | YOLOv8, Automated sorting |

---

### B&R AI Smart Camera

> Industrial camera for manufacturing: optical inspection, anomaly detection, sorting, OCR, pick & place.

| | |
|---|---|
| **Hardware** | Hailo |
| **Official Demo** | [hailo.ai](https://hailo.ai/resources/industries/industrial-automation/ai-smart-camera-for-real-time-automation/) |
| **Partner** | B&R |

---

### Idein AI Cast Smart Camera (Retail)
![Status](https://img.shields.io/badge/status-production-brightgreen)

> Retail analytics camera deployed in Japanese retail chains (Sogo & Seibu). Customer counting, journey tracking, shoplifting detection.

| | |
|---|---|
| **Hardware** | Hailo-8 |
| **Official Demo** | [hailo.ai](https://hailo.ai/resources/industries/retail/idein-ai-cast-smart-camera/) |
| **Partner** | Idein, AISIN (Toyota Group) |

---

## 🚗 Automotive & ADAS

*Surround perception, radar, LiDAR fusion, and driving scene understanding*

### L2-L3 Full Surround Perception

> 6x 2MP cameras, 3D detection and Bird's Eye View for ADAS and automated driving.

| | |
|---|---|
| **Hardware** | Hailo-8, Renesas V4H |
| **Official Demo** | [hailo.ai](https://hailo.ai/resources/industries/automotive/l2-l3-full-surround-perception-for-adas-and-automated-driving/) |

---

### PercivAI Radar-Based 3D Perception
![Status](https://img.shields.io/badge/status-production-brightgreen)

> Low-cost radar 3D perception for detecting free space and objects in darkness and severe weather.

| | |
|---|---|
| **Hardware** | Hailo |
| **Official Demo** | [hailo.ai](https://hailo.ai/resources/industries/automotive/percivai-radar-based-3d-perception/) |
| **Partner** | PercivAI |

---

### Tier IV LiDAR + Camera Sensor Fusion
![Status](https://img.shields.io/badge/status-production-brightgreen)

> Long-range pedestrian detection with on-device anonymization.

| | |
|---|---|
| **Hardware** | Hailo |
| **Official Demo** | [hailo.ai](https://hailo.ai/resources/industries/automotive/tier-iv-lidar-and-camera-sensor-fusion-for-high-accuracy-perception/) |
| **Partner** | Tier IV |

---

### TT Control Ruggedized ECU
![Status](https://img.shields.io/badge/status-production-brightgreen)

> 6-camera surround views protecting workers near industrial machinery.

| | |
|---|---|
| **Hardware** | Hailo |
| **Official Demo** | [hailo.ai](https://hailo.ai/resources/industries/automotive/tt-control-ruggedized-ecu-for-off-road-vehicles/) |
| **Partner** | TT Control |

---

## 🏥 Healthcare & Medical

*Surgical intelligence, medical imaging, and ultrasound training*

### Akara AI Sensor — Surgical Intelligence
![Status](https://img.shields.io/badge/status-production-brightgreen)

> Privacy-preserving surgical event tracking in hospitals. Automates procedure documentation with thermal sensors.

| | |
|---|---|
| **Hardware** | Hailo-8 |
| **Official Demo** | [hailo.ai](https://hailo.ai/resources/industries/healthcare/akara-ai-sensor-privacy-preserving-surgical-intelligence-powered-by-hailo-8/) |
| **Partner** | Akara |


<div align="center">

[![Akara AI Sensor — Surgical Intelligence](https://img.youtube.com/vi/rQHs5Ym2VvA/hqdefault.jpg)](https://www.youtube.com/watch?v=rQHs5Ym2VvA)

**▶️ [Watch: Akara AI Sensor — Surgical Intelligence](https://www.youtube.com/watch?v=rQHs5Ym2VvA)**

</div>

---

### Intelligent Ultrasound NeedleTrainer

> AI-enhanced ultrasound training for regional anesthesia — real-time anatomical segmentation overlays during needle insertion practice. Licensed as medical device in UK/EU/US.

| | |
|---|---|
| **Hardware** | Hailo-8 |
| **Official Demo** | [hailo.ai](https://hailo.ai/resources/industries/other/intelligent-ultrasound-needletrainer/) |
| **Partner** | Intelligent Ultrasound |

---

## 🦊 Wildlife & Environment

*Wildlife detection cameras and environmental monitoring*

### Pi Hailo Wildlife Camera v3
![Grade: B](https://img.shields.io/badge/grade-B-blue) [![Stars](https://img.shields.io/github/stars/Gordon999/Pi_Hailo_Wildlife_3?style=social)](https://github.com/Gordon999/Pi_Hailo_Wildlife_3) ![Last Commit](https://img.shields.io/github/last-commit/Gordon999/Pi_Hailo_Wildlife_3)

> Wildlife video capture with pre-capture buffer, detection masking, camera zoom, and autostart. Records MP4 when animals are detected.

| | |
|---|---|
| **Hardware** | Hailo-8L, Hailo-10H, Raspberry Pi 5 |
| **GitHub** | [Gordon999/Pi_Hailo_Wildlife_3](https://github.com/Gordon999/Pi_Hailo_Wildlife_3) |
| **Key Features** | Pre-capture buffer, Detection masking, Zoom, Autostart |

---

### Pi Hailo Wildlife Camera (Original)
[![Stars](https://img.shields.io/github/stars/Gordon999/Pi_Hailo_Wildlife?style=social)](https://github.com/Gordon999/Pi_Hailo_Wildlife) ![Last Commit](https://img.shields.io/github/last-commit/Gordon999/Pi_Hailo_Wildlife)

> Original wildlife video capture system with configurable animal detection and GPIO LED indicator.

| | |
|---|---|
| **Hardware** | Hailo-8L, Raspberry Pi 5 |
| **GitHub** | [Gordon999/Pi_Hailo_Wildlife](https://github.com/Gordon999/Pi_Hailo_Wildlife) |
| **Key Features** | MP4 capture, GPIO LED |

---

## 🎙️ Speech & Audio

*Speech-to-text, voice assistants, and audio processing*

### Hailo Whisper — Speech-to-Text
![Grade: B](https://img.shields.io/badge/grade-B-blue) [![Stars](https://img.shields.io/github/stars/hailocs/hailo-whisper?style=social)](https://github.com/hailocs/hailo-whisper) ![Last Commit](https://img.shields.io/github/last-commit/hailocs/hailo-whisper)

> Tools to export, convert, and evaluate OpenAI Whisper on Hailo accelerators. Supports tiny/base models, multilingual and English-only.

| | |
|---|---|
| **Hardware** | Hailo-8, Hailo-8L, Hailo-10H |
| **GitHub** | [hailocs/hailo-whisper](https://github.com/hailocs/hailo-whisper) |
| **Key Features** | Whisper tiny/base, Multilingual, Evaluation scripts |


<div align="center">

[![Hailo Whisper — Speech-to-Text](https://img.youtube.com/vi/rbSKieDLrw4/hqdefault.jpg)](https://www.youtube.com/watch?v=rbSKieDLrw4)

**▶️ [Watch: Hailo Whisper — Speech-to-Text](https://www.youtube.com/watch?v=rbSKieDLrw4)**

</div>

---

## 🎨 Creative & Fun

*Style transfer, games, and artistic applications*

### Edge AI Art Generator
![Grade: C](https://img.shields.io/badge/grade-C-yellow) [![Stars](https://img.shields.io/github/stars/hrishikeshgokhale01/Edge-AI-Art-Generator?style=social)](https://github.com/hrishikeshgokhale01/Edge-AI-Art-Generator) ![Last Commit](https://img.shields.io/github/last-commit/hrishikeshgokhale01/Edge-AI-Art-Generator)

> Real-time style transfer on live video from USB camera with dynamic style switching.

| | |
|---|---|
| **Hardware** | Hailo, Raspberry Pi 5 |
| **GitHub** | [hrishikeshgokhale01/Edge-AI-Art-Generator](https://github.com/hrishikeshgokhale01/Edge-AI-Art-Generator) |
| **Key Features** | Style transfer, Live video, Dynamic switching |

---

### Squid Game Doll — Red Light, Green Light
![Grade: C](https://img.shields.io/badge/grade-C-yellow) [![Stars](https://img.shields.io/github/stars/fablab-bergamo/squid-game-doll?style=social)](https://github.com/fablab-bergamo/squid-game-doll) ![Last Commit](https://img.shields.io/github/last-commit/fablab-bergamo/squid-game-doll)

> 'Red Light, Green Light' robot using YOLOv8/YOLOv11 + ByteTrack for player recognition with ESP32.

| | |
|---|---|
| **Hardware** | Hailo-8L, Raspberry Pi 5 |
| **GitHub** | [fablab-bergamo/squid-game-doll](https://github.com/fablab-bergamo/squid-game-doll) |
| **Key Features** | YOLOv8, ByteTrack, ESP32 |

---

## 🔧 Tools & Utilities

*Model converters, Docker images, Kubernetes plugins, and development aids*

### HailoConverter — ONNX to HEF
![Grade: B](https://img.shields.io/badge/grade-B-blue) [![Stars](https://img.shields.io/github/stars/cyclux/HailoConverter?style=social)](https://github.com/cyclux/HailoConverter) ![Last Commit](https://img.shields.io/github/last-commit/cyclux/HailoConverter)

> Docker image to convert ONNX YOLOv8s models to Hailo HEF format using Dataflow Compiler v3.28.0.

| | |
|---|---|
| **Hardware** | Hailo-8L |
| **GitHub** | [cyclux/HailoConverter](https://github.com/cyclux/HailoConverter) |
| **Key Features** | Docker, Calibration quantization |

---

### Hailo Custom Model via GCP
![Grade: B](https://img.shields.io/badge/grade-B-blue) [![Stars](https://img.shields.io/github/stars/marcory-hub/hailo_gcp?style=social)](https://github.com/marcory-hub/hailo_gcp) ![Last Commit](https://img.shields.io/github/last-commit/marcory-hub/hailo_gcp)

> Deploy custom models on RPi5 Hailo-8L using Google Colab and GCP — no local x86/GPU needed. Free-tier workflow.

| | |
|---|---|
| **Hardware** | Hailo-8L |
| **GitHub** | [marcory-hub/hailo_gcp](https://github.com/marcory-hub/hailo_gcp) |
| **Key Features** | Google Colab, Free tier, 148 commits |

---

### HAILO-YOLO-INFERENCE for RPi5
[![Stars](https://img.shields.io/github/stars/rybkady/HAILO-YOLO-INFERENCE-for-RPi5?style=social)](https://github.com/rybkady/HAILO-YOLO-INFERENCE-for-RPi5) ![Last Commit](https://img.shields.io/github/last-commit/rybkady/HAILO-YOLO-INFERENCE-for-RPi5)

> Step-by-step guide for verifying ONNX to HEF conversion with side-by-side comparison. Docker-based.

| | |
|---|---|
| **Hardware** | Hailo-8/8L |
| **GitHub** | [rybkady/HAILO-YOLO-INFERENCE-for-RPi5](https://github.com/rybkady/HAILO-YOLO-INFERENCE-for-RPi5) |
| **Key Features** | ONNX vs HEF comparison, Docker |

---

### Hailo Toolbox
![Grade: C](https://img.shields.io/badge/grade-C-yellow) [![Stars](https://img.shields.io/github/stars/Seeed-Projects/hailo_toolbox?style=social)](https://github.com/Seeed-Projects/hailo_toolbox) ![Last Commit](https://img.shields.io/github/last-commit/Seeed-Projects/hailo_toolbox)

> Comprehensive model conversion and inference toolkit with ONNX-to-HEF, multi-task inference, CLI and Python API.

| | |
|---|---|
| **Hardware** | Hailo-8 |
| **GitHub** | [Seeed-Projects/hailo_toolbox](https://github.com/Seeed-Projects/hailo_toolbox) |
| **Key Features** | CLI, Python API, Multi-task |

---

### Hailo YOLO Guide
[![Stars](https://img.shields.io/github/stars/seapanda0/hailo-yolo-guide?style=social)](https://github.com/seapanda0/hailo-yolo-guide) ![Last Commit](https://img.shields.io/github/last-commit/seapanda0/hailo-yolo-guide)

> Three-stage guide to convert and inference YOLO models on Hailo. Includes sample HEF.

| | |
|---|---|
| **Hardware** | Hailo-8L |
| **GitHub** | [seapanda0/hailo-yolo-guide](https://github.com/seapanda0/hailo-yolo-guide) |
| **Key Features** | 3-stage workflow, Sample HEF |

---

### PiAIKitCompiler
[![Stars](https://img.shields.io/github/stars/Eagleshot/PiAIKitCompiler?style=social)](https://github.com/Eagleshot/PiAIKitCompiler) ![Last Commit](https://img.shields.io/github/last-commit/Eagleshot/PiAIKitCompiler)

> Jupyter Notebook-based workflow to convert custom YOLO models to HEF for Hailo-8L.

| | |
|---|---|
| **Hardware** | Hailo-8L |
| **GitHub** | [Eagleshot/PiAIKitCompiler](https://github.com/Eagleshot/PiAIKitCompiler) |
| **Key Features** | Jupyter, Step-by-step |

---

### Hailo Docker Ubuntu
[![Stars](https://img.shields.io/github/stars/jpm-canonical/hailo-docker-ubuntu?style=social)](https://github.com/jpm-canonical/hailo-docker-ubuntu) ![Last Commit](https://img.shields.io/github/last-commit/jpm-canonical/hailo-docker-ubuntu)

> Hailo Runtime + TAPPAS framework in Ubuntu 24.04 Docker image.

| | |
|---|---|
| **Hardware** | Hailo-8L |
| **GitHub** | [jpm-canonical/hailo-docker-ubuntu](https://github.com/jpm-canonical/hailo-docker-ubuntu) |
| **Key Features** | Docker, Ubuntu 24.04 |

---

### Hailo-10H Web Dashboard
[![Stars](https://img.shields.io/github/stars/kristoffersingleton/RPI-Hailo-10H-Web-Dashboard?style=social)](https://github.com/kristoffersingleton/RPI-Hailo-10H-Web-Dashboard) ![Last Commit](https://img.shields.io/github/last-commit/kristoffersingleton/RPI-Hailo-10H-Web-Dashboard)

> Real-time web-based monitoring dashboard for Hailo-10H device status.

| | |
|---|---|
| **Hardware** | Hailo-10H, Raspberry Pi 5 |
| **GitHub** | [kristoffersingleton/RPI-Hailo-10H-Web-Dashboard](https://github.com/kristoffersingleton/RPI-Hailo-10H-Web-Dashboard) |
| **Key Features** | Web UI, Real-time monitoring |

---

### Viam Modular Resource for RPi AI Kit
[![Stars](https://img.shields.io/github/stars/HipsterBrown/viam-pi-hailo-ml?style=social)](https://github.com/HipsterBrown/viam-pi-hailo-ml) ![Last Commit](https://img.shields.io/github/last-commit/HipsterBrown/viam-pi-hailo-ml)

> Viam robotics platform integration for Raspberry Pi AI Kit and AI HAT+.

| | |
|---|---|
| **Hardware** | Hailo-8L |
| **GitHub** | [HipsterBrown/viam-pi-hailo-ml](https://github.com/HipsterBrown/viam-pi-hailo-ml) |
| **Key Features** | Viam platform |

---

### Hailo Model Generator
[![Stars](https://img.shields.io/github/stars/arsatyants/hailo_model_generator?style=social)](https://github.com/arsatyants/hailo_model_generator) ![Last Commit](https://img.shields.io/github/last-commit/arsatyants/hailo_model_generator)

> Complete YOLOv8 training-to-deployment pipeline for Hailo-8 HEF model generation.

| | |
|---|---|
| **Hardware** | Hailo-8 |
| **GitHub** | [arsatyants/hailo_model_generator](https://github.com/arsatyants/hailo_model_generator) |
| **Key Features** | End-to-end pipeline |

---

### Zig-Hailo — Zig Language Bindings
[![Stars](https://img.shields.io/github/stars/ssttevee/zig-hailo?style=social)](https://github.com/ssttevee/zig-hailo) ![Last Commit](https://img.shields.io/github/last-commit/ssttevee/zig-hailo)

> Zig reimplementation of some HailoRT functions.

| | |
|---|---|
| **Hardware** | Hailo-8 |
| **GitHub** | [ssttevee/zig-hailo](https://github.com/ssttevee/zig-hailo) |
| **Key Features** | Zig |

---

### Kubernetes Device Plugin
![Grade: C](https://img.shields.io/badge/grade-C-yellow) [![Stars](https://img.shields.io/github/stars/gllm-dev/hailo-device-plugin?style=social)](https://github.com/gllm-dev/hailo-device-plugin) ![Last Commit](https://img.shields.io/github/last-commit/gllm-dev/hailo-device-plugin)

> K8s Device Plugin for Hailo AI accelerators — enables edge MLOps and container orchestration.

| | |
|---|---|
| **Hardware** | Hailo |
| **GitHub** | [gllm-dev/hailo-device-plugin](https://github.com/gllm-dev/hailo-device-plugin) |
| **Key Features** | Go, Kubernetes |

---

## 📚 Tutorials & Learning Resources

*Step-by-step guides, benchmarks, and reference designs*

### AI Kit: Zero to Hero (Seeed)
![Grade: A](https://img.shields.io/badge/grade-A-brightgreen) [![Stars](https://img.shields.io/github/stars/Seeed-Projects/Tutorial-of-AI-Kit-with-Raspberry-Pi-From-Zero-to-Hero?style=social)](https://github.com/Seeed-Projects/Tutorial-of-AI-Kit-with-Raspberry-Pi-From-Zero-to-Hero) ![Last Commit](https://img.shields.io/github/last-commit/Seeed-Projects/Tutorial-of-AI-Kit-with-Raspberry-Pi-From-Zero-to-Hero)

> Step-by-step guide from setup to Ollama integration on Raspberry Pi with Hailo AI Kit.

| | |
|---|---|
| **Hardware** | Hailo-8/8L |
| **GitHub** | [Seeed-Projects/Tutorial-of-AI-Kit-with-Raspberry-Pi-From-Zero-to-Hero](https://github.com/Seeed-Projects/Tutorial-of-AI-Kit-with-Raspberry-Pi-From-Zero-to-Hero) |
| **Key Features** | Detection, Pose, Segmentation, Ollama |

---

### Zynq UltraScale+ with Hailo-8
![Grade: A](https://img.shields.io/badge/grade-A-brightgreen) [![Stars](https://img.shields.io/github/stars/fpgadeveloper/zynqmp-hailo-ai?style=social)](https://github.com/fpgadeveloper/zynqmp-hailo-ai) ![Last Commit](https://img.shields.io/github/last-commit/fpgadeveloper/zynqmp-hailo-ai)

> FPGA reference design combining Zynq UltraScale+ MPSoC with Hailo-8 for multi-camera YOLOv5.

| | |
|---|---|
| **Hardware** | Hailo-8 (M.2) |
| **GitHub** | [fpgadeveloper/zynqmp-hailo-ai](https://github.com/fpgadeveloper/zynqmp-hailo-ai) |
| **Key Features** | FPGA, 4 cameras, PetaLinux, Vivado |

---

### DeGirum Hailo Examples
![Grade: B](https://img.shields.io/badge/grade-B-blue) [![Stars](https://img.shields.io/github/stars/DeGirum/hailo_examples?style=social)](https://github.com/DeGirum/hailo_examples) ![Last Commit](https://img.shields.io/github/last-commit/DeGirum/hailo_examples)

> DeGirum PySDK usage examples with Jupyter notebooks and benchmarking.

| | |
|---|---|
| **Hardware** | Hailo-8/8L |
| **GitHub** | [DeGirum/hailo_examples](https://github.com/DeGirum/hailo_examples) |
| **Key Features** | Jupyter, PySDK, Benchmarks |

---

### JeVois-Pro Smart Camera
[![Stars](https://img.shields.io/github/stars/jevois/jevois?style=social)](https://github.com/jevois/jevois) ![Last Commit](https://img.shields.io/github/last-commit/jevois/jevois)

> Open-source standalone AI smart camera with Hailo-8 M.2. 31 TOPS combined. YOLOv7 640x640 at 11.5fps, YOLOv5m at 40fps.

| | |
|---|---|
| **Hardware** | Hailo-8 |
| **GitHub** | [jevois/jevois](https://github.com/jevois/jevois) |
| **Key Features** | Standalone camera, 31 TOPS, Multi-framework |

---

### Benchmarking YOLOv8 on RPi + Hailo
[![Stars](https://img.shields.io/github/stars/Seeed-Projects/Benchmarking-YOLOv8-on-Raspberry-PI-reComputer-r1000-and-AIkit-Hailo-8L?style=social)](https://github.com/Seeed-Projects/Benchmarking-YOLOv8-on-Raspberry-PI-reComputer-r1000-and-AIkit-Hailo-8L) ![Last Commit](https://img.shields.io/github/last-commit/Seeed-Projects/Benchmarking-YOLOv8-on-Raspberry-PI-reComputer-r1000-and-AIkit-Hailo-8L)

> Object detection, segmentation, and pose estimation benchmarks on RPi CM4 with Hailo-8L.

| | |
|---|---|
| **Hardware** | Hailo-8L |
| **GitHub** | [Seeed-Projects/Benchmarking-YOLOv8-on-Raspberry-PI-reComputer-r1000-and-AIkit-Hailo-8L](https://github.com/Seeed-Projects/Benchmarking-YOLOv8-on-Raspberry-PI-reComputer-r1000-and-AIkit-Hailo-8L) |
| **Key Features** | Benchmarks, Multiple tasks |

---

### GStreamer Examples with Hailo
[![Stars](https://img.shields.io/github/stars/JarnoRalli/gstreamer-examples?style=social)](https://github.com/JarnoRalli/gstreamer-examples) ![Last Commit](https://img.shields.io/github/last-commit/JarnoRalli/gstreamer-examples)

> Image processing pipelines using GStreamer, DeepStream, and Hailo.

| | |
|---|---|
| **Hardware** | Hailo-8 |
| **GitHub** | [JarnoRalli/gstreamer-examples](https://github.com/JarnoRalli/gstreamer-examples) |
| **Key Features** | GStreamer, Tracking, Pipelines |

---


---

<div align="center">

**[Hailo GitHub](https://github.com/hailo-ai)** · **[Hailo YouTube](https://www.youtube.com/@hailo2062)** · **[Hailo Resources](https://hailo.ai/resources/)** · **[Hailo Community](https://community.hailo.ai)**

*Auto-generated from [`project_registry.yaml`](../internal_agent/data/project_registry.yaml) by [`generate_index.py`](../internal_agent/scripts/generate_index.py)*

</div>

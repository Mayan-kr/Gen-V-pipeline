# Gen-V-Pipeline 🎬

An end-to-end automated AI Video Generation Pipeline that generates cinematic reels with consistent face identity using a novel **Image-to-Video** architecture.

## 🏗️ Architecture (I2V Pipeline)

The pipeline uses a three-stage rendering process to achieve flicker-free, face-consistent video:

```
┌─────────────────────┐     ┌──────────────────┐     ┌─────────────────────┐
│  DreamShaper 8      │     │  ReActor          │     │  LTX-Video 2B       │
│  (Text-to-Image)    │────▶│  (Face Swap)      │────▶│  (Image-to-Video)   │
│                     │     │  on SINGLE frame   │     │  Animates the frame │
│  Generates a        │     │  Perfect, no       │     │  Face is baked in   │
│  cinematic still    │     │  flickering!       │     │  = zero flicker!    │
└─────────────────────┘     └──────────────────┘     └─────────────────────┘
```

1. **Stage 1 — T2I**: Generates a high-quality cinematic still frame using DreamShaper 8 (SD 1.5) from a Gemini-written image prompt
2. **Stage 2 — Face Swap**: ReActor swaps the client's face onto the single generated image with CodeFormer restoration — perfect quality, no temporal artifacts
3. **Stage 3 — I2V Animation**: LTX-Video takes the face-swapped image as the first frame and animates it using a motion prompt — the face is embedded in the latent space, so it moves naturally with zero flickering

## 🚀 How It Works

1. **Local Controller (`agent.py`)**: Runs on your machine. Uses the Gemini 2.5 API to write a 12-scene screenplay with dual prompts (image + motion), generates Edge-TTS voiceovers, orchestrates the remote GPU, and stitches the final reel with MoviePy
2. **Cloud Worker (`comfyui-kaggle.ipynb`)**: Runs on Kaggle dual-T4 GPUs. Hosts ComfyUI with DreamShaper 8, LTX-Video, and ReActor, tunneled via Cloudflare

## 🛠️ Key Features

- **Dual-Prompt Gemini System**: Generates separate "image prompt" (for the static frame) and "motion prompt" (for the animation) per scene
- **Face-Consistent Characters**: Face is swapped on a single high-res image before animation — no frame-by-frame inconsistency
- **CodeFormer Restoration**: Neural face enhancement on the swapped image for maximum realism
- **Robust HTTP Polling**: No fragile WebSocket connections — safely polls ComfyUI through Cloudflare tunnels
- **Full AV Pipeline**: Automatic TTS voiceover generation and audio-video merging per scene

## 📦 Setup & Usage

### 1. Cloud Setup (Kaggle)
1. Upload `comfyui-kaggle.ipynb` to a Kaggle Notebook with **T4x2 GPU** accelerator
2. Add the `inswapper_128.onnx` InsightFace model as a Kaggle Dataset
3. Click **"Run All"** — the notebook downloads all models and spawns a Cloudflare tunnel
4. Copy the `.trycloudflare.com` URL printed at the bottom

### 2. Local Setup
1. Clone this repository
2. Install dependencies: `pip install -r requirements.txt`
3. Create `key.txt` with your Gemini API key: `Gemini API Key: YOUR_KEY_HERE`
4. Place a clear face photo as `client_face.jpg` in the project root
5. Update `config.json` with your Cloudflare URL and master prompt

### 3. Run
```bash
python agent.py
```

The output folder will contain:
- `storyboard.json` — The Gemini-generated screenplay
- `audio_scene_*.mp3` — Individual voiceovers
- `scene_*.mp4` — Individual scene videos with audio
- `final_viral_reel.mp4` — The complete 60-second reel

## ⚙️ Technical Stack
| Component | Technology |
|-----------|-----------|
| LLM Engine | Google Gemini 2.5 Flash |
| Text-to-Image | DreamShaper 8 (Stable Diffusion 1.5) |
| Image-to-Video | LTX-Video 2B (v0.9.1) |
| Face Swap | ReActor + CodeFormer |
| Audio | Edge-TTS |
| Compositing | MoviePy |
| Orchestration | ComfyUI API |
| Tunneling | Cloudflared |

## 📐 Default Settings
- **Resolution**: 384×640 (9:16 portrait)
- **Frame count**: 81 frames at 16 fps (~5 seconds per scene)
- **Scenes**: 12 × 5 seconds = 60 second reel
- **VRAM Peak**: ~10 GB (fits on T4 with 6 GB headroom)

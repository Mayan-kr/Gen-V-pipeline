# Gen-V-Pipeline 🎬

An end-to-end automated AI Video Generation Pipeline that dynamically constructs storyboards, orchestrates remote cloud GPUs to render AI video and face-swaps, generates voiceovers, and stitches it all into a final cinematic reel.

## 🚀 Architecture overview

This pipeline splits the heavy lifting between your local machine and a Kaggle Cloud environment:

1. **Local Controller (`agent.py`)**: Runs on your local machine. It uses the Gemini 2.5 API to write a 12-scene screenplay, pings the remote cloud GPU to render video, generates Edge-TTS audio locally, and uses `moviepy` to stitch everything together.
2. **Cloud Worker (`comfyui-kaggle.ipynb`)**: Runs on a Kaggle dual-T4 GPU instance. It spins up an optimized ComfyUI server containing the **LTX-Video** generation models and **ReActor** face-swapping nodes, seamlessly tunneling the API endpoints back to your local machine via Cloudflare.

## 🛠️ Key Features

- **Automated Storyboarding:** Feeds a master concept to Gemini to generate descriptive, continuous prompts and dramatic voiceover lines.
- **Consistent Characters:** Dynamically forces the LLM to generate character descriptions matching the source image to ensure optimal face-swapping compatibility.
- **Remote ComfyUI Automation:** Programmatically manipulates a raw `workflow_api.json` to inject random seeds, custom prompts, and image assets into the ComfyUI nodes.
- **Robust Cloudflare Polling:** Safely monitors remote generation progress without dropping connections or succumbing to idle timeouts.
- **Full AV Stitching:** Automatically pairs each generated video clip with its TTS voiceover and concatenates them into a master MP4.

## 📦 Setup & Usage

### 1. Cloud Setup (Kaggle)
1. Upload `comfyui-kaggle.ipynb` to a Kaggle Notebook configured with a **T4x2 GPU** accelerator.
2. Click "Run All". 
3. The notebook will download optimized GGUF LTX-Video models and InsightFace binaries, then spawn a Cloudflare tunnel. Note the `.trycloudflare.com` URL printed at the bottom.

### 2. Local Setup
1. Clone this repository.
2. Create a `key.txt` file containing your API key: `Gemini API Key: YOUR_KEY_HERE`.
3. Provide a clear image of the target face named `client_face.jpg` in the root folder.
4. Update `config.json` with your master prompt, resolution settings, and the active Cloudflare URL.

### 3. Execution
Run the primary controller:
```bash
python agent.py
```
The script will output progress directly to the console and drop the master reel in the auto-generated `outputs/` folder.

## ⚙️ Technical Stack
* **LLM Engine**: Google Gemini 2.5 Flash
* **Video Generation**: LTX-Video (2B parameter model)
* **Face Swapping**: ReActor (inswapper_128)
* **Audio Engine**: Edge-TTS
* **Compositing**: MoviePy
* **Infrastructure**: ComfyUI API, Cloudflared Tunneling

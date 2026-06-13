import os
import sys
import json
import base64
import requests
import asyncio
import time
import random
import uuid
import urllib.request
import urllib.parse
import edge_tts
from concurrent.futures import ThreadPoolExecutor, as_completed
from moviepy import VideoFileClip, AudioFileClip, concatenate_videoclips

# Force standard output to use UTF-8 to prevent encoding errors on Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# ============================================================
# Utility Functions
# ============================================================

def load_pipeline_config(config_path="config.json"):
    with open(config_path, "r") as f:
        return json.load(f)

def load_gemini_key():
    if os.path.exists("key.txt"):
        with open("key.txt", "r") as f:
            for line in f:
                if "Gemini API Key:" in line:
                    key = line.split("Gemini API Key:")[-1].strip()
                    if key:
                        return key
    return os.environ.get("GEMINI_API_KEY")

def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

# ============================================================
# Gemini Storyboard Engine (Dual-Prompt: Image + Motion)
# ============================================================

def generate_storyboard(master_prompt, api_key, client_image_path):
    print("[Storyboard Engine] Consulting Gemini LLM to construct a 12-scene screenplay...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    
    prompt_instruction = (
        "You are a professional storyboard writer and prompt engineer for AI-generated cinematic reels. "
        "Your task is to split the following master concept into exactly 12 continuous scenes. "
        "Each scene lasts exactly 5 seconds (totaling 60 seconds of video). "
        "\n\n"
        "For EACH scene, you must provide THREE separate outputs:\n"
        "1. 'image_prompt': A highly detailed description of a SINGLE STATIC FRAME — a cinematic photograph capturing the peak moment of the scene. "
        "This prompt will be fed to a text-to-image model (Stable Diffusion). "
        "Describe the composition, subject, lighting, colors, environment, and camera angle as if describing a movie still. "
        "Include cinematic quality keywords: 'photorealistic, 8k, cinematic lighting, depth of field, film grain, dramatic composition'. "
        "\n"
        "2. 'motion_prompt': A short description of how the static frame should be ANIMATED. "
        "Describe the camera motion and subtle character movement. Examples: "
        "'Slow camera dolly forward, character slowly turns head to the right, soft wind moves hair', "
        "'Camera slowly pans left revealing the alley, rain falls gently, distant police lights flicker'. "
        "Keep it natural and subtle — no extreme jumps or teleportation. "
        "\n"
        "3. 'voiceover_text': A dramatic narration line that fits within 5 seconds when spoken. "
        "\n\n"
        "CRITICAL RULES:\n"
        "1. CHARACTER CONSISTENCY: Analyze the provided image. Note their age, gender, build, hair style/color, and attire. "
        "Describe this EXACT same person in EVERY scene's image_prompt so the generated images are compatible with face-swapping. "
        "2. FRAMING: Use 'medium wide shot' or 'full body shot'. NEVER use extreme close-ups. "
        "Always ensure the character's upper body and face are clearly visible in the frame. "
        "3. LIGHTING: Even night scenes must be 'well-lit with cinematic night lighting'. No pitch black scenes. "
        "4. CRITICAL JSON RULE: Do NOT use double quotes inside text values. Use single quotes only. "
        "\n\n"
        "Output ONLY a raw JSON object matching this exact schema:\n"
        "{\n"
        "  \"project_title\": \"ShortTitle\",\n"
        "  \"scenes\": [\n"
        "    {\n"
        "      \"scene_id\": 1,\n"
        "      \"image_prompt\": \"Photorealistic cinematic still frame, medium wide shot. A [age] year old [gender]...\",\n"
        "      \"motion_prompt\": \"Camera slowly dollies forward, character looks up...\",\n"
        "      \"voiceover_text\": \"The dramatic line spoken during this scene...\",\n"
        "      \"duration_seconds\": 5\n"
        "    }\n"
        "  ]\n"
        "}"
    )
    
    base64_image = encode_image(client_image_path)
    
    payload = {
        "contents": [{
            "parts": [
                {"text": f"{prompt_instruction}\n\nMaster Concept: {master_prompt}"},
                {
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": base64_image
                    }
                }
            ]
        }],
        "generationConfig": {
            "responseMimeType": "application/json"
        }
    }
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=payload)
            if response.status_code == 200:
                try:
                    res_json = response.json()
                    text_response = res_json['candidates'][0]['content']['parts'][0]['text']
                    storyboard_data = json.loads(text_response.strip())
                    print(f"[Storyboard Engine] Storyboard '{storyboard_data.get('project_title', 'Untitled')}' created successfully with {len(storyboard_data.get('scenes', []))} scenes.")
                    return storyboard_data
                except Exception as e:
                    print(f"[Storyboard Engine] Error parsing LLM response: {e}")
                    return None
            elif response.status_code == 503:
                print(f"[Storyboard Engine] Gemini API returned 503 (High Demand). Retrying in {2 ** attempt} seconds...")
                time.sleep(2 ** attempt)
            else:
                print(f"[Storyboard Engine] Gemini API error: {response.status_code} - {response.text[:200]}")
                return None
        except requests.exceptions.RequestException as e:
            print(f"[Storyboard Engine] Network error: {e}")
            return None
            
    print("[Storyboard Engine] Max retries reached. Failed to contact Gemini.")
    return None

# ============================================================
# ComfyUI Client (HTTP Polling — no WebSockets)
# ============================================================

class ComfyUIClient:
    def __init__(self, server_address):
        self.server_address = server_address.replace("https://", "").replace("http://", "").rstrip('/')
        if "trycloudflare.com" in self.server_address or "ngrok" in self.server_address:
            self.scheme = "https"
        else:
            self.scheme = "http"
        self.client_id = str(uuid.uuid4())
        
    def upload_image(self, image_path):
        url = f"{self.scheme}://{self.server_address}/upload/image"
        with open(image_path, 'rb') as f:
            files = {'image': (os.path.basename(image_path), f, 'image/jpeg')}
            res = requests.post(url, files=files)
            if res.status_code == 200:
                return res.json().get('name')
            else:
                print(f"[ComfyUI] Failed to upload image: {res.text}")
                return None
                
    def queue_prompt(self, prompt_workflow, retries=3):
        p = {"prompt": prompt_workflow, "client_id": self.client_id}
        data = json.dumps(p).encode('utf-8')
        req = urllib.request.Request(f"{self.scheme}://{self.server_address}/prompt", data=data)
        req.add_header('Content-Type', 'application/json')
        
        for attempt in range(retries):
            try:
                response = urllib.request.urlopen(req)
                return json.loads(response.read())
            except urllib.error.HTTPError as e:
                err_body = e.read().decode('utf-8')
                print(f"[ComfyUI] HTTP {e.code} on queue_prompt (attempt {attempt+1}/{retries}): {err_body[:300]}")
                if attempt == retries - 1:
                    raise
                time.sleep(2 * (attempt + 1))
            except Exception as e:
                print(f"[ComfyUI] Error on queue_prompt (attempt {attempt+1}/{retries}): {e}")
                if attempt == retries - 1:
                    raise
                time.sleep(2 * (attempt + 1))
        
    def get_file(self, filename, subfolder, folder_type):
        data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
        url_values = urllib.parse.urlencode(data)
        url = f"{self.scheme}://{self.server_address}/view?{url_values}"
        req = urllib.request.Request(url)
        response = urllib.request.urlopen(req)
        return response.read()

    def get_history(self, prompt_id):
        url = f"{self.scheme}://{self.server_address}/history/{prompt_id}"
        req = urllib.request.Request(url)
        response = urllib.request.urlopen(req)
        return json.loads(response.read())

    def render_and_download(self, prompt_workflow, scene_id):
        """Queue a prompt, poll for completion, and download the resulting video."""
        # Stagger submissions to avoid Cloudflare rate limits
        time.sleep(random.uniform(0.5, 3.0))
        try:
            prompt_res = self.queue_prompt(prompt_workflow)
            prompt_id = prompt_res['prompt_id']
            print(f"[ComfyUI] Scene {scene_id} queued (Prompt ID: {prompt_id})")
        except Exception as e:
            print(f"[ComfyUI] Error queuing Scene {scene_id}: {e}")
            return None
            
        # Poll /history every 10 seconds until the job completes
        print(f"[ComfyUI] Scene {scene_id} rendering... (polling for completion)")
        poll_count = 0
        while True:
            try:
                history_data = self.get_history(prompt_id)
                if prompt_id in history_data:
                    history = history_data[prompt_id]
                    # Check for errors
                    status = history.get('status', {})
                    if status.get('status_str') == 'error':
                        msgs = status.get('messages', [])
                        print(f"[ComfyUI] Scene {scene_id} FAILED on server: {msgs}")
                        return None
                    break
            except Exception:
                pass
            poll_count += 1
            if poll_count % 6 == 0:
                print(f"[ComfyUI] Scene {scene_id} still rendering... ({poll_count * 10}s elapsed)")
            time.sleep(10)
            
        if 'outputs' not in history:
            print(f"[ComfyUI] No outputs in history for Scene {scene_id}")
            return None
            
        # Search for the video file in outputs
        for node_id, node_output in history['outputs'].items():
            if 'gifs' in node_output:
                for video in node_output['gifs']:
                    return self.get_file(video['filename'], video['subfolder'], video['type'])
            elif 'images' in node_output:
                for image in node_output['images']:
                    if image['filename'].endswith(".mp4"):
                        return self.get_file(image['filename'], image['subfolder'], image['type'])
        
        print(f"[ComfyUI] Video file not found in outputs for Scene {scene_id}")
        return None

# ============================================================
# Audio Engine (Edge-TTS)
# ============================================================

async def generate_audio_for_scene(text, output_filename):
    voice = "en-US-ChristopherNeural"
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_filename)

# ============================================================
# Scene Renderer (New I2V Architecture)
# ============================================================

def render_scene(client, scene_data, uploaded_image_name, workflow_api, output_dir, audio_path=None, width=384, height=640, num_frames=81, fps=16):
    """
    New I2V Pipeline per scene:
    1. Inject image_prompt into T2I node (101)
    2. Inject motion_prompt into LTX I2V motion node (6)
    3. Queue the workflow → ComfyUI generates image, swaps face, animates
    4. Download the video, merge with pre-generated audio
    """
    scene_id = scene_data['scene_id']
    print(f"[Pipeline] Processing Scene {scene_id}...")
    
    # Deep-clone the workflow template
    workflow = json.loads(json.dumps(workflow_api))
    
    # If wrapped in graphToPrompt "output" key, unwrap
    if "output" in workflow:
        workflow = workflow["output"]
    
    try:
        # === T2I Stage (DreamShaper 8) ===
        workflow["101"]["inputs"]["text"] = scene_data["image_prompt"]
        workflow["104"]["inputs"]["seed"] = random.randint(1, 999999999999999)
        workflow["103"]["inputs"]["width"] = width
        workflow["103"]["inputs"]["height"] = height
        
        # === Face Swap Stage (ReActor) ===
        workflow["81"]["inputs"]["image"] = uploaded_image_name
        
        # === I2V Stage (LTX-Video) ===
        workflow["6"]["inputs"]["text"] = scene_data["motion_prompt"]
        workflow["72"]["inputs"]["noise_seed"] = random.randint(1, 999999999999999)
        workflow["70"]["inputs"]["width"] = width
        workflow["70"]["inputs"]["height"] = height
        workflow["70"]["inputs"]["length"] = num_frames
        workflow["69"]["inputs"]["frame_rate"] = fps
        workflow["78"]["inputs"]["fps"] = fps
        
    except KeyError as e:
        print(f"[Pipeline] Error injecting values into workflow nodes: {e}")
        return None
    
    # Submit to ComfyUI and wait for result
    video_bytes = client.render_and_download(workflow, scene_id)
    
    if video_bytes:
        raw_video_path = os.path.join(output_dir, f"raw_scene_{scene_id}.mp4")
        with open(raw_video_path, "wb") as f:
            f.write(video_bytes)
            
        print(f"[Pipeline] Scene {scene_id} video downloaded successfully.")
        
        # If no audio available, return raw video
        if not audio_path or not os.path.exists(audio_path):
            print(f"[Pipeline] Warning: No audio for Scene {scene_id}, returning raw video.")
            return raw_video_path
            
        # Merge video + audio
        final_output_path = os.path.join(output_dir, f"scene_{scene_id}.mp4")
        print(f"[Pipeline] Merging audio into Scene {scene_id}...")
        try:
            video_clip = VideoFileClip(raw_video_path)
            audio_clip = AudioFileClip(audio_path)
            
            # Trim audio if longer than video
            if audio_clip.duration > video_clip.duration:
                audio_clip = audio_clip.subclip(0, video_clip.duration)
                
            final_clip = video_clip.set_audio(audio_clip)
            final_clip.write_videofile(final_output_path, codec="libx264", audio_codec="aac", logger=None)
            
            video_clip.close()
            audio_clip.close()
            final_clip.close()
            
            # Clean up raw video (keep audio for debugging)
            if os.path.exists(raw_video_path):
                os.remove(raw_video_path)
            
            print(f"[Pipeline] Scene {scene_id} complete: {final_output_path}")
            return final_output_path
        except Exception as e:
            print(f"[Pipeline] Error merging audio for Scene {scene_id}: {e}")
            return raw_video_path
    else:
        print(f"[Pipeline] Failed to retrieve video for Scene {scene_id}.")
        return None

# ============================================================
# Final Reel Compilation
# ============================================================

def compile_final_reel(video_paths, output_name, fps=16):
    print("[Pipeline] Assembling final reel from all scenes...")
    clips = [VideoFileClip(path) for path in video_paths if path is not None]
    
    if not clips:
        print("[Pipeline] No valid scenes to compile.")
        return
        
    final_clip = concatenate_videoclips(clips, method="compose")
    final_clip.write_videofile(output_name, fps=fps, codec="libx264", audio_codec="aac")
    print(f"[Pipeline] Final reel: {output_name}")

# ============================================================
# Main Pipeline
# ============================================================

def main():
    config = load_pipeline_config()
    api_url = config.get("api_endpoint")
    client_image_path = config.get("client_image_path", "client_face.jpg")
    master_prompt = config.get("master_prompt")
    
    width = config.get("width", 384)
    height = config.get("height", 640)
    num_frames = config.get("num_frames", 81)
    fps = config.get("fps", 16)
    
    if not api_url:
        print("[Pipeline] Error: 'api_endpoint' not set in config.json.")
        return
        
    if not os.path.exists("workflow_api.json"):
        print("[Pipeline] Error: 'workflow_api.json' not found.")
        return
        
    with open("workflow_api.json", "r", encoding="utf-8") as f:
        workflow_api = json.load(f)
        
    gemini_key = load_gemini_key()
    if not gemini_key:
        print("[Pipeline] Error: Gemini API Key not found in 'key.txt'.")
        return
        
    if not master_prompt:
        print("[Pipeline] Error: 'master_prompt' not set in config.json.")
        return
        
    # Initialize ComfyUI Client
    print(f"[Pipeline] Connecting to ComfyUI at {api_url}...")
    client = ComfyUIClient(api_url)
    
    print("[Pipeline] Uploading client face image...")
    uploaded_image_name = client.upload_image(client_image_path)
    if not uploaded_image_name:
        print("[Pipeline] Failed to upload client image. Exiting.")
        return
    print(f"[Pipeline] Face image uploaded as: {uploaded_image_name}")
    
    # Step 1: Generate Storyboard via Gemini
    storyboard_data = generate_storyboard(master_prompt, gemini_key, client_image_path)
    if not storyboard_data or "scenes" not in storyboard_data:
        print("[Pipeline] Failed to generate storyboard. Exiting.")
        return
        
    project_title = storyboard_data.get("project_title", "Untitled").replace(" ", "_")
    timestamp = int(time.time())
    output_dir = os.path.join("outputs", f"{project_title}_{timestamp}")
    os.makedirs(output_dir, exist_ok=True)
    
    # Save storyboard for reference
    with open(os.path.join(output_dir, "storyboard.json"), "w") as f:
        json.dump(storyboard_data, f, indent=2)
        
    scenes = storyboard_data["scenes"]
    downloaded_scenes = [None] * len(scenes)
    
    print(f"[Pipeline] Output directory: {output_dir}")
    
    # Step 2: Generate TTS Audio (sequentially to avoid Windows asyncio issues)
    print(f"[Pipeline] Generating {len(scenes)} TTS voiceovers...")
    audio_paths = {}
    for scene in scenes:
        audio_path = os.path.join(output_dir, f"audio_scene_{scene['scene_id']}.mp3")
        try:
            asyncio.run(generate_audio_for_scene(scene["voiceover_text"], audio_path))
            audio_paths[scene['scene_id']] = audio_path
            print(f"  [Audio] Scene {scene['scene_id']} voiceover generated.")
        except Exception as e:
            print(f"  [Audio] Scene {scene['scene_id']} failed: {e}")
            audio_paths[scene['scene_id']] = None
            
    # Step 3: Render all scenes via ComfyUI (parallel with 3 workers)
    print(f"[Pipeline] Submitting {len(scenes)} scenes to ComfyUI...")
    
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_index = {
            executor.submit(
                render_scene, client, scene, uploaded_image_name, workflow_api,
                output_dir, audio_paths.get(scene['scene_id']),
                width, height, num_frames, fps
            ): i for i, scene in enumerate(scenes)
        }
        
        for future in as_completed(future_to_index):
            idx = future_to_index[future]
            try:
                scene_file = future.result()
                if scene_file:
                    downloaded_scenes[idx] = scene_file
            except Exception as exc:
                print(f"[Pipeline] Scene {scenes[idx]['scene_id']} exception: {exc}")
            
    # Step 4: Compile final reel
    valid_scenes = [s for s in downloaded_scenes if s is not None]
    if valid_scenes:
        final_reel_path = os.path.join(output_dir, "final_viral_reel.mp4")
        compile_final_reel(valid_scenes, output_name=final_reel_path, fps=fps)
    else:
        print("[Pipeline] All scenes failed. Compilation skipped.")

if __name__ == "__main__":
    main()
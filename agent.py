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
import websocket
import edge_tts
from concurrent.futures import ThreadPoolExecutor, as_completed
from moviepy import VideoFileClip, AudioFileClip, CompositeVideoClip, concatenate_videoclips

# Force standard output to use UTF-8 to prevent encoding errors on Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

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

def generate_storyboard(master_prompt, api_key, client_image_path):
    print("[Storyboard Engine] Consulting Gemini LLM to construct a 12-scene screenplay with character resemblance...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    
    prompt_instruction = (
        "You are a professional storyboard writer and prompt engineer. "
        "Your task is to split the following master concept into exactly 12 continuous scenes. "
        "Each scene must last exactly 5 seconds (totaling 60 seconds of video). "
        "For each scene, write a highly descriptive visual prompt suitable for a video generation model (like LTX-Video). "
        "CRITICAL RULES: "
        "1. CHARACTER CONSISTENCY: Analyze the provided image of the client. Carefully note their age, gender, body build, hair style/color, and general attire. YOU MUST explicitly describe this exact person as the main character in EVERY SINGLE scene's visual prompt so the video model generates a body type that matches them perfectly before face-swapping. "
        "2. FRAMING: Explicitly define the camera shot (e.g., 'Medium wide shot', 'Full body shot'). NEVER use extreme close-ups where the face fills the screen. Always ensure the character's upper body and environment are clearly visible so face-swapping works naturally. "
        "3. LIGHTING: Ensure the lighting is described as clear, bright, cinematic, or highly visible. Even if the scene is at night, specify 'well-lit cinematic night lighting' or 'neon lights illuminating the scene'. Do NOT make the scenes too dark or shadowy where action is unreadable. "
        "4. AUDIO/VOICEOVER: Write a short dramatic voiceover script for EACH scene that fits within 5 seconds when spoken. "
        "5. CRITICAL JSON RULE: Do NOT use double quotes inside any of your text descriptions or voiceover values. If you need to quote a word or phrase, use single quotes (e.g., 'The Golden Spoon'). Using double quotes inside values will break the JSON parser. "
        "Output ONLY a raw JSON object matching this exact schema: \n"
        "{\n"
        "  \"project_title\": \"A short 2-3 word title without spaces or special characters, e.g. Gritty_Restaurant_Thriller\",\n"
        "  \"scenes\": [\n"
        "    {\n"
        "      \"scene_id\": 1,\n"
        "      \"prompt\": \"Cinematic 9:16 vertical video, medium wide shot. A [age] year old [gender] with [build]... description of the scene...\",\n"
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
                print(f"[Storyboard Engine] Gemini API error: {response.status_code}")
                return None
        except requests.exceptions.RequestException as e:
            print(f"[Storyboard Engine] Network error: {e}")
            return None
            
    print("[Storyboard Engine] Max retries reached. Failed to contact Gemini.")
    return None

class ComfyUIClient:
    def __init__(self, server_address):
        self.server_address = server_address.replace("https://", "").replace("http://", "").rstrip('/')
        self.scheme = "https" if "trycloudflare.com" in server_address else "http"
        self.ws_scheme = "wss" if self.scheme == "https" else "ws"
        self.client_id = str(uuid.uuid4())
        
    def upload_image(self, image_path):
        url = f"{self.scheme}://{self.server_address}/upload/image"
        with open(image_path, "rb") as f:
            files = {"image": f}
            res = requests.post(url, files=files)
            if res.status_code == 200:
                return res.json().get("name")
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
                print(f"[ComfyUI] HTTP {e.code} on queue_prompt: {err_body}")
                if attempt == retries - 1:
                    raise
                time.sleep(2)
            except Exception as e:
                print(f"[ComfyUI] Error on queue_prompt: {e}")
                if attempt == retries - 1:
                    raise
                time.sleep(2)
        
    def get_image(self, filename, subfolder, folder_type):
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

    def get_video(self, prompt_workflow, scene_id):
        # Stagger submissions slightly to avoid Cloudflare rate limits
        time.sleep(random.uniform(0.5, 3.0))
        try:
            prompt_res = self.queue_prompt(prompt_workflow)
            prompt_id = prompt_res['prompt_id']
            print(f"[Pipeline] Scene {scene_id} submitted to ComfyUI queue (Prompt ID: {prompt_id})")
        except Exception as e:
            print(f"[Pipeline] Error queuing prompt for Scene {scene_id}: {e}")
            return None
            
        # Poll the /history endpoint instead of WebSockets to completely avoid Cloudflare idle timeouts
        print(f"[Pipeline] Scene {scene_id} is processing. Polling for completion...")
        while True:
            try:
                history_data = self.get_history(prompt_id)
                if prompt_id in history_data:
                    history = history_data[prompt_id]
                    break
            except Exception as e:
                pass
            time.sleep(10) # Poll every 10 seconds
            
        if 'outputs' not in history:
            print(f"[Pipeline] No outputs found in history for Scene {scene_id}")
            return None
            
        for node_id, node_output in history['outputs'].items():
            if 'gifs' in node_output:
                for video in node_output['gifs']:
                    return self.get_image(video['filename'], video['subfolder'], video['type'])
            elif 'images' in node_output:
                for image in node_output['images']:
                    if image['filename'].endswith(".mp4"):
                        return self.get_image(image['filename'], image['subfolder'], image['type'])
        
        print(f"[Pipeline] Video file not found in outputs for Scene {scene_id}")
        return None

async def generate_audio_for_scene(text, output_filename):
    print(f"[Audio Engine] Generating voiceover for '{output_filename}'...")
    voice = "en-US-ChristopherNeural"
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_filename)

def render_scene_from_comfy(client, scene_data, uploaded_image_name, workflow_api, output_dir, width=768, height=512, num_frames=97, fps=24):
    print(f"[Pipeline] Processing Scene {scene_data['scene_id']} locally...")
    
    # Clone the json dictionary
    workflow_data = json.loads(json.dumps(workflow_api))
    
    # If the JSON was generated via graphToPrompt, the actual node list is inside "output"
    if "output" in workflow_data:
        workflow = workflow_data["output"]
    else:
        workflow = workflow_data
        
    # Inject dynamic values into the ComfyUI nodes
    try:
        workflow["6"]["inputs"]["text"] = scene_data["prompt"]
        workflow["72"]["inputs"]["noise_seed"] = random.randint(1, 999999999999999)
        workflow["81"]["inputs"]["image"] = uploaded_image_name
        workflow["70"]["inputs"]["width"] = width
        workflow["70"]["inputs"]["height"] = height
        workflow["70"]["inputs"]["length"] = num_frames
        workflow["78"]["inputs"]["fps"] = fps
        
        # Override the default models with the optimized ones we actually downloaded in Phase 1
        workflow["44"]["inputs"]["ckpt_name"] = "LTX-Video/ltx-video-2b-v0.9.1.safetensors"
        workflow["38"]["inputs"]["clip_name"] = "t5xxl_fp8_e4m3fn.safetensors"
    except KeyError as e:
        print(f"[Pipeline] Error parsing workflow_api.json nodes: {e}")
        return None
    
    video_bytes = client.get_video(workflow, scene_data['scene_id'])
    
    if video_bytes:
        raw_video_path = os.path.join(output_dir, f"raw_scene_{scene_data['scene_id']}.mp4")
        with open(raw_video_path, "wb") as f:
            f.write(video_bytes)
            
        print(f"[Pipeline] Scene {scene_data['scene_id']} video rendering completed.")
        
        # Generate Audio
        audio_path = os.path.join(output_dir, f"audio_scene_{scene_data['scene_id']}.mp3")
        asyncio.run(generate_audio_for_scene(scene_data["voiceover_text"], audio_path))
        
        # Merge Video and Audio
        final_output_path = os.path.join(output_dir, f"scene_{scene_data['scene_id']}.mp4")
        print(f"[Pipeline] Merging video and audio for Scene {scene_data['scene_id']}...")
        try:
            video_clip = VideoFileClip(raw_video_path)
            audio_clip = AudioFileClip(audio_path)
            
            if audio_clip.duration > video_clip.duration:
                audio_clip = audio_clip.subclip(0, video_clip.duration)
                
            final_clip = video_clip.set_audio(audio_clip)
            final_clip.write_videofile(final_output_path, codec="libx264", audio_codec="aac", logger=None)
            
            video_clip.close()
            audio_clip.close()
            final_clip.close()
            
            if os.path.exists(raw_video_path): os.remove(raw_video_path)
            if os.path.exists(audio_path): os.remove(audio_path)
            
            print(f"[Pipeline] Scene {scene_data['scene_id']} fully completed: {final_output_path}")
            return final_output_path
        except Exception as e:
            print(f"[Pipeline] Error merging audio for scene {scene_data['scene_id']}: {e}")
            return raw_video_path
    else:
        print(f"[Pipeline] Failed to retrieve video for Scene {scene_data['scene_id']}.")
        return None

def compile_final_reel(video_paths, output_name, fps=24):
    print("[Pipeline] Assembling individual scene renders into a single timeline asset...")
    clips = [VideoFileClip(path) for path in video_paths if path is not None]
    
    if not clips:
        print("[Pipeline] Compilation aborted: No valid source video assets found.")
        return
        
    final_clip = concatenate_videoclips(clips, method="compose")
    final_clip.write_videofile(output_name, fps=fps, codec="libx264", audio_codec="aac")
    print(f"[Pipeline] Master video file generated: {output_name}")

def main():
    config = load_pipeline_config()
    api_url = config.get("api_endpoint")
    client_image_path = config.get("client_image_path", "client_face.jpg")
    master_prompt = config.get("master_prompt")
    
    width = config.get("width", 768)
    height = config.get("height", 512)
    num_frames = config.get("num_frames", 97)
    fps = config.get("fps", 24)
    
    if not api_url or "trycloudflare" not in api_url:
        print(f"[Pipeline] Warning: Your api_endpoint in config.json doesn't look like a Cloudflare tunnel URL ({api_url}). Continuing anyway...")
        
    if not os.path.exists("workflow_api.json"):
        print("[Pipeline] Error: 'workflow_api.json' not found. Please ensure Phase 2 is complete.")
        return
        
    # We must load the JSON with utf-8 encoding because ComfyUI uses emojis in node metadata
    with open("workflow_api.json", "r", encoding="utf-8") as f:
        workflow_api = json.load(f)
        
    gemini_key = load_gemini_key()
    if not gemini_key:
        print("[Pipeline] Error: Gemini API Key not found. Please ensure it is present in 'key.txt'.")
        return
        
    if not master_prompt:
        print("[Pipeline] Error: 'master_prompt' not configured in config.json.")
        return
        
    # Initialize ComfyUI Client
    print(f"[Pipeline] Initializing ComfyUI Connection to {api_url}...")
    client = ComfyUIClient(api_url)
    
    print("[Pipeline] Uploading client face image to ComfyUI...")
    uploaded_image_name = client.upload_image(client_image_path)
    if not uploaded_image_name:
        print("[Pipeline] Failed to upload client image. Exiting.")
        return
    print(f"[Pipeline] Successfully uploaded face image as: {uploaded_image_name}")
    
    # Step 1: Generate the Storyboard
    storyboard_data = generate_storyboard(master_prompt, gemini_key, client_image_path)
    if not storyboard_data or "scenes" not in storyboard_data:
        print("[Pipeline] Failed to generate storyboard. Exiting.")
        return
        
    project_title = storyboard_data.get("project_title", "Untitled_Project").replace(" ", "_")
    timestamp = int(time.time())
    output_dir = os.path.join("outputs", f"{project_title}_{timestamp}")
    os.makedirs(output_dir, exist_ok=True)
    
    with open(os.path.join(output_dir, "storyboard.json"), "w") as f:
        json.dump(storyboard_data, f, indent=2)
        
    scenes = storyboard_data["scenes"]
    downloaded_scenes = [None] * len(scenes)
    
    print(f"[Pipeline] Output directory created: {output_dir}")
    print(f"[Pipeline] Submitting {len(scenes)} scenes to ComfyUI processing queue...")
    
    # ComfyUI queue handles parallel submissions internally on a single GPU
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_index = {
            executor.submit(
                render_scene_from_comfy, client, scene, uploaded_image_name, workflow_api, output_dir, width, height, num_frames, fps
            ): i for i, scene in enumerate(scenes)
        }
        
        for future in as_completed(future_to_index):
            idx = future_to_index[future]
            try:
                scene_file = future.result()
                if scene_file:
                    downloaded_scenes[idx] = scene_file
            except Exception as exc:
                print(f"[Pipeline] Scene {scenes[idx]['scene_id']} generated an exception: {exc}")
            
    # Compile
    valid_scenes = [s for s in downloaded_scenes if s is not None]
    if valid_scenes:
        final_reel_path = os.path.join(output_dir, f"final_viral_reel.mp4")
        compile_final_reel(valid_scenes, output_name=final_reel_path, fps=fps)
    else:
        print("[Pipeline] All scenes failed. Compilation skipped.")

if __name__ == "__main__":
    main()
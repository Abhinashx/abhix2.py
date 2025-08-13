#!/usr/bin/env python3

-- coding: utf-8 --

""" ABHI X2 — Final merged build (auto‑mic detect + Ubuntu→Termux auto‑switch + text fallback)

Voice assistant (hi/en) with safe fallbacks

Termux device controls (screenshot, camera, volume, lock/unlock, notifications)

Friendly small‑talk + simple intent normalizer

Optional Hugging Face reply fallback (set HF_API_KEY)

Ethical pentest flow: whitelist + invite token + typed confirmation + approved command list

Logs, audit, memory, suggested fixes

Self‑update daemon from GitHub raw URL (optional)


Owner: ARVIND """

import os, sys, time, json, re, subprocess, threading, platform, argparse, requests from collections import Counter

───────────────────────── Config / Paths ─────────────────────────

ASSISTANT_NAME = "ABHI" OPERATOR_NAME  = "ARVIND"

Optional: HuggingFace text fallback

HF_API_KEY  = ""  # e.g. "hf_xxx" (leave blank to disable) HF_MODEL    = "gpt2" HF_API_URL  = f"https://api-inference.huggingface.co/models/{HF_MODEL}"

Optional: self‑update from your repo raw URL (leave blank to disable)

UPDATE_URL  = ""  # e.g. "https://raw.githubusercontent.com/<you>/<repo>/main/abhi_x2_final.py" UPDATE_INTERVAL = 3600  # seconds

Where to store logs/files

IS_TERMUX   = "com.termux" in os.environ.get("PREFIX", "") or 
"/data/data/com.termux/files/usr" in os.environ.get("PREFIX", "") or 
os.path.exists("/data/data/com.termux/files/usr") ANDROID_ROOT = os.environ.get("ANDROID_ROOT") or (os.path.exists("/system/bin") and "android") HOME = os.path.expanduser("~")

if IS_TERMUX: LOG_DIR = "/sdcard/vega_logs" SCREENSHOT_DIR = "/sdcard/vega_screenshots" else: LOG_DIR = os.path.join(HOME, ".abhi_logs") SCREENSHOT_DIR = os.path.join(LOG_DIR, "screenshots")

os.makedirs(LOG_DIR, exist_ok=True) os.makedirs(SCREENSHOT_DIR, exist_ok=True) SELF_FILE = os.path.abspath(sys.argv[0])

Files

FEEDBACK_FILE       = os.path.join(LOG_DIR, "feedback.json") USAGE_FILE          = os.path.join(LOG_DIR, "usage.json") SUGGESTED_FIXES     = os.path.join(LOG_DIR, "suggested_fixes.json") APP_MAP_FILE        = os.path.join(LOG_DIR, "app_mapping.json") MEMORY_FILE         = os.path.join(LOG_DIR, "memory.json") AUDIT_LOG           = os.path.join(LOG_DIR, "audit.log") APPROVED_CMDS_FILE  = os.path.join(LOG_DIR, "approved_commands.json") WHITELIST_FILE      = os.path.join(LOG_DIR, "whitelist.json")

Defaults

DEFAULT_APP_MAP = { "whatsapp": "com.whatsapp", "youtube": "com.google.android.youtube", "camera":  "com.android.camera" }

DEFAULT_APPROVED = { "ping":      ["ping","-c","4","{target}"], "http_head": ["curl","-I","{target}"], "port_scan": ["nmap","-sT","-p","1-1024","{target}"] }

───────────────────────── Small Utils ─────────────────────────

def load_json(path, default): try: if os.path.exists(path): with open(path, "r", encoding="utf-8") as f: return json.load(f) except Exception: pass return default

def save_json(path, data): try: with open(path, "w", encoding="utf-8") as f: json.dump(data, f, indent=2, ensure_ascii=False) except Exception: pass

for p, d in [ (FEEDBACK_FILE, []), (USAGE_FILE, []), (SUGGESTED_FIXES, []), (APP_MAP_FILE, DEFAULT_APP_MAP.copy()), (MEMORY_FILE, {"conversations": []}), (APPROVED_CMDS_FILE, DEFAULT_APPROVED.copy()), (WHITELIST_FILE, { "198.51.100.23": { "owner": "security@acme.example", "token": "invite-ACME-2025-08", "notes": "ACME invite scope: single host" }, "lab.local": {"owner": "me", "token": "local-lab", "notes": "local test only"} }) ]: if not os.path.exists(p): save_json(p, d)

───────────────────────── Speech / Mic detect ─────────────────────────

def list_input_devices_sounddevice(): try: import sounddevice as sd devs = sd.query_devices() return [d for d in devs if d.get('max_input_channels', 0) > 0] except Exception: return []

def any_microphone_available(): # Try sounddevice first if list_input_devices_sounddevice(): return True # Fallback: SpeechRecognition device list try: import speech_recognition as sr names = sr.Microphone.list_microphone_names() return bool(names) except Exception: return False

def is_inside_proot_like_linux(): # Heuristic: Linux, AND /system/bin exists (Android root visible), but not Termux PREFIX if IS_TERMUX: return False if platform.system().lower() == "linux" and os.path.exists("/system/bin"): return True return False

def termux_python_path(): # Common Termux python locations candidates = [ "/data/data/com.termux/files/usr/bin/python", "/data/data/com.termux/files/usr/bin/python3" ] for c in candidates: if os.path.exists(c): return c return None

def try_relaunch_in_termux(script_path: str, extra_args=None): """Attempt to relaunch this script under Termux's Python if available. Works best when the script lives in /sdcard (shared storage). """ py = termux_python_path() if not py: return False, "termux python not found" if not os.path.exists(script_path): return False, "script not visible at given path" cmd = [py, script_path] if extra_args: cmd += extra_args try: subprocess.Popen(cmd) return True, "spawned" except Exception as e: return False, str(e)

───────────────────────── TTS / Notify ─────────────────────────

def speak(text: str): print(f"{ASSISTANT_NAME}: {text}") if IS_TERMUX: try: subprocess.run(["termux-tts-speak", "-l", "hi", text], check=False) except Exception: pass else: try: import pyttsx3 eng = pyttsx3.init() eng.say(text) eng.runAndWait() except Exception: pass

def notify(text: str): if IS_TERMUX: try: subprocess.run(["termux-notification", "--title", ASSISTANT_NAME, "--content", text], check=False) except Exception: pass

───────────────────────── Logging / Memory / Audit ─────────────────────────

def audit_log(entry: dict): rec = {"ts": time.time(), "human_time": time.ctime(), **entry} try: with open(AUDIT_LOG, "a", encoding="utf-8") as f: f.write(json.dumps(rec, ensure_ascii=False) + "\n") except Exception: pass

def log_feedback(cmd, status, details=""): arr = load_json(FEEDBACK_FILE, []) arr.append({"time": time.time(), "human_time": time.ctime(), "command": cmd, "status": status, "details": details}) save_json(FEEDBACK_FILE, arr)

def log_usage(cmd): arr = load_json(USAGE_FILE, []) arr.append({"time": time.time(), "command": cmd}) save_json(USAGE_FILE, arr)

def save_memory(user, assistant): mem = load_json(MEMORY_FILE, {"conversations": []}) mem["conversations"].append({"time": time.time(), "human_time": time.ctime(), "user": user, "assistant": assistant}) mem["conversations"] = mem["conversations"][-500:] save_json(MEMORY_FILE, mem)

───────────────────────── Device actions (Termux) ─────────────────────────

def termux_cmd(args, label, timeout=120): try: proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout, check=True) log_feedback(label, "success") return True, proc.stdout except subprocess.CalledProcessError as e: log_feedback(label, "fail", e.stderr or str(e)) return False, e.stderr or str(e) except Exception as e: log_feedback(label, "fail", str(e)) return False, str(e)

def take_screenshot(): path = os.path.join(SCREENSHOT_DIR, f"screenshot_{int(time.time())}.png") if IS_TERMUX: ok, _ = termux_cmd(["termux-screenshot", path], "screenshot") speak("स्क्रीनशॉट ले लिया गया" if ok else "स्क्रीनशॉट लेने में समस्या आई") else: # Desktop fallback via ImageMagick (if available) try: subprocess.run(["import", path], check=True) speak("स्क्रीनशॉट लिया") except Exception: speak("स्क्रीनशॉट कमांड उपलब्ध नहीं")

def camera_photo(): if not IS_TERMUX: speak("कैमरा केवल Termux/Android पर उपलब्ध") return path = f"/sdcard/camera_{int(time.time())}.jpg" ok, _ = termux_cmd(["termux-camera-photo", path], "camera_photo") speak("फोटो ले ली गई" if ok else "कैमरा खोलने में समस्या")

def set_volume(level: int): if not IS_TERMUX: speak("वॉल्यूम परिवर्तन Ubuntu/Desktop पर समर्थित नहीं") return ok, _ = termux_cmd(["termux-volume", "music", str(level)], f"volume_{level}") if ok: if level == 0: speak("वॉल्यूम म्यूट कर दिया गया") elif level >= 12: speak("वॉल्यूम पूरा बढ़ा दिया गया") else: speak("वॉल्यूम सेट कर दिया गया") else: speak("वॉल्यूम बदलने में समस्या आई")

def lock_device(): if not IS_TERMUX: speak("लॉक केवल Android/Termux पर") return ok, _ = termux_cmd(["termux-lock"], "lock") speak("फोन लॉक हो गया" if ok else "लॉक करने में समस्या")

def unlock_device(): if not IS_TERMUX: speak("अनलॉक केवल Android/Termux पर") return ok, _ = termux_cmd(["termux-wake-unlock"], "unlock") speak("फोन अनलॉक हो गया" if ok else "अनलॉक करने में समस्या")

def open_app(name_raw: str): if not IS_TERMUX: speak("ऐप खोलना केवल Android/Termux पर") return False mapping = load_json(APP_MAP_FILE, DEFAULT_APP_MAP.copy()) key = (name_raw or "").strip().lower() pkg = mapping.get(key) if not pkg: push_suggest_fix(f"open_app:{key}", "Add package mapping in app_mapping.json") speak(f"{name_raw} mapping missing — CONFIRM कर के placeholder जोड़ो") return False # Attempt via Activity (best effort, actual activity may vary) ok, _ = termux_cmd(["am","start","-n", f"{pkg}/.MainActivity"], f"open_app_{key}") speak(f"{name_raw} खोल दिया" if ok else f"{name_raw} नहीं खुल पाया") return ok

───────────────────────── Suggestions / Analyze ─────────────────────────

def push_suggest_fix(command, suggestion): arr = load_json(SUGGESTED_FIXES, []) arr.append({"time": time.time(), "command": command, "suggestion": suggestion}) save_json(SUGGESTED_FIXES, arr)

def analyze(): data = load_json(FEEDBACK_FILE, []) fails = [d for d in data if d.get("status") == "fail"] if not fails: return counts = Counter([f.get("command") for f in fails]) if not counts: return most, cnt = counts.most_common(1)[0] if cnt >= 3: speak(f"ध्यान दें: '{most}' बार‑बार फेल हो रहा है — CONFIRM टाइप करके placeholder जोड़ें") push_suggest_fix(most, "Recurring failure; check mapping/permissions")

───────────────────────── Safety / Pentest Flow ─────────────────────────

DANGEROUS_KEYWORDS = [ "exploit","ddos","reverse shell","rootkit","attack","payload","crack", "hydra","sqlmap","metasploit","subfinder","ffuf","port scan","scan subnet" ]

def contains_dangerous(text): t = (text or "").lower() return any(kw in t for kw in DANGEROUS_KEYWORDS)

def is_valid_hostname_or_ip(s): return bool(re.match(r"^\d{1,3}(?:.\d{1,3}){3}$", s) or re.match(r"^[a-z0-9.-]{1,253}$", s, re.I))

def verify_invite_token(target, token): wl = load_json(WHITELIST_FILE, {}) return target in wl and wl[target].get("token") == token

def require_typed_confirmation(timeout_seconds=60): print("Dangerous action requested. TYPE: CONFIRM: YES") speak("ध्यान दें: खतरनाक कार्रवाई के लिए टाइप करके पुष्टि करिए — CONFIRM: YES") start = time.time() try: while time.time() - start < timeout_seconds: if sys.stdin in select_readable(0.5): return input().strip() == "CONFIRM: YES" except Exception: pass return False

def select_readable(timeout): import select r, _, _ = select.select([sys.stdin], [], [], timeout) return r

def run_approved_action(action_name, target=None, extra_args=None): approved = load_json(APPROVED_CMDS_FILE, {}) if action_name not in approved: return False, f"Action '{action_name}' not found" base = approved[action_name] final = [] for part in base: if "{target}" in part: if not target or not is_valid_hostname_or_ip(target): return False, "Invalid/no target" final.append(part.replace("{target}", target)) else: final.append(part) if extra_args: final += extra_args audit_log({"phase": "pre-exec", "action": action_name, "cmd": final, "target": target}) try: proc = subprocess.run(final, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, timeout=300) out = proc.stdout ok = True except subprocess.CalledProcessError as e: out = (e.stderr or str(e)) ok = False audit_log({"phase": "post-exec", "action": action_name, "cmd": final, "target": target, "success": ok, "stdout_snippet": (out or "")[:1000]}) return ok, out

───────────────────────── Trading helper ─────────────────────────

def get_coin_price(coin_id="bitcoin", vs_currency="usd"): try: r = requests.get( f"https://api.coingecko.com/api/v3/simple/price", params={"ids": coin_id, "vs_currencies": vs_currency, "include_24hr_change": True}, timeout=10) return r.json().get(coin_id, {}) except Exception: return {}

def trading_suggestion_for_btc(): data = get_coin_price("bitcoin","usd") if not data: return "Market data unavailable right now." price = data.get("usd") change24 = data.get("usd_24h_change", 0) trend = "up" if (change24 or 0) > 0 else "down" sl_pct = 0.01 if trend == "up" else 0.02 entry = float(price) sl = round(entry*(1 - sl_pct), 2) tp = round(entry*(1 + 0.03), 2) return f"BTC price ${entry:.2f}, 24h change {change24:.2f}%. Suggested entry ${entry:.2f}, stop-loss ${sl:.2f}, take-profit ${tp:.2f} (trend {trend})."

───────────────────────── HF helper (optional) ─────────────────────────

def hf_query(prompt, max_tokens=180): if not HF_API_KEY: return None, "no_token" headers = {"Authorization": f"Bearer {HF_API_KEY}"} payload = {"inputs": prompt, "parameters": {"max_new_tokens": max_tokens, "temperature": 0.1}} try: resp = requests.post(HF_API_URL, headers=headers, json=payload, timeout=30) if resp.status_code != 200: return None, f"HF {resp.status_code}: {resp.text[:200]}" j = resp.json() if isinstance(j, list) and j and isinstance(j[0], dict) and "generated_text" in j[0]: return j[0]["generated_text"], None if isinstance(j, dict) and "generated_text" in j: return j["generated_text"], None return str(j)[:1000], None except Exception as e: return None, str(e)

───────────────────────── Intent normalizer ─────────────────────────

TRIGGERS = { "kaise ho abhi": [ "main theek hoon, ekdum mast 😎", "ARVIND, main bilkul badhiya hoon! tum kaise ho?" ] } FALLBACKS = [ "ARVIND, main samajh nahi paya — phir se bol do?", "ek minute — yeh mujhe clear nahi hua. Dobara bolo, please." ]

def is_trigger(text): t = (text or "").strip().lower() for k in TRIGGERS: if k in t: return k return None

def smalltalk_reply(text): key = is_trigger(text) if key: return TRIGGERS[key][0] low = (text or "").lower() if any(w in low for w in ("hello","hi","hey","namaste","salam")): return "Namaste ARVIND! kaise ho?" return None

def normalize_and_intent(text): if contains_dangerous(text): return ("DANGEROUS", None) t = (text or "").lower() # local intents (fast) if any(x in t for x in ["screenshot","स्क्रीनशॉट","screen shot"]): return ("SCREENSHOT", None) if any(x in t for x in ["lock","लॉक"]): return ("LOCK", None) if any(x in t for x in ["unlock","अनलॉक"]): return ("UNLOCK", None) if any(x in t for x in ["camera","कैमरा","photo","फोटो"]): return ("CAMERA", None) if any(x in t for x in ["volume","वॉल्यूम","आवाज़","आवाज"]): if any(x in t for x in ["increase","बढ़ा","फुल","up","ऊपर"]): return ("VOLUME_UP", None) if any(x in t for x in ["decrease","कम","down","घटा"]): return ("VOLUME_DOWN", None) if "mute" in t or "म्यूट" in t: return ("VOLUME_MUTE", None) if any(x in t for x in ["time","समय","टाइम"]): return ("TIME", None) if ("battery" in t) or ("बैटरी" in t): return ("BATTERY", None) if ("खोलो" in t) or ("open" in t): app_name = t.replace("खोलो"," ").replace("open"," ").strip() return ("OPEN_APP", app_name) if any(x in t for x in ["bitcoin","btc","buy bitcoin"]): return ("TRADE_ADVICE", "bitcoin") if any(x in t for x in ["scan","port scan","run scan","run port"]): m = re.search(r"((?:\d{1,3}.){3}\d{1,3})|([a-z0-9.-]+.[a-z]{2,})", t) tgt = m.group(0) if m else None return ("AUTHORIZED_SCAN", tgt) return ("UNKNOWN", text)

───────────────────────── STT (Voice) ─────────────────────────

LISTEN_SECONDS = 7

try: import speech_recognition as sr except Exception: sr = None

def listen_google_stt(timeout=LISTEN_SECONDS, phrase_limit=LISTEN_SECONDS): if not sr: return "" try: r = sr.Recognizer() with sr.Microphone() as source: r.adjust_for_ambient_noise(source, duration=0.8) print("सुन रहा हूँ... (Google STT)") audio = r.listen(source, timeout=timeout, phrase_time_limit=phrase_limit) try: return r.recognize_google(audio, language='hi-IN') except sr.UnknownValueError: try: return r.recognize_google(audio, language='en-US') except Exception: return "" except Exception as e: print("[listen]", e) return ""

def listen_vosk_offline(): try: from vosk import Model, KaldiRecognizer import pyaudio except Exception: return "" model_path = "vosk-model-small-hi-0.22" if not os.path.exists(model_path): return "" wf_rate = 16000 model = Model(model_path) rec = KaldiRecognizer(model, wf_rate) p = pyaudio.PyAudio() stream = p.open(format=pyaudio.paInt16, channels=1, rate=wf_rate, input=True, frames_per_buffer=8000) stream.start_stream() print("सुन रहा हूँ... (Vosk offline)") while True: data = stream.read(4000, exception_on_overflow=False) if rec.AcceptWaveform(data): res = json.loads(rec.Result()) return res.get("text", "")

───────────────────────── Mode Runners ─────────────────────────

def handle_intent(intent, meta, original_text): if intent == "DANGEROUS": speak("माफ़ कीजिए — मैं यह काम करने में मदद नहीं कर सकता।") log_feedback(original_text, "blocked", "dangerous") save_memory(original_text, "blocked_dangerous") return

if intent == "SCREENSHOT":
    take_screenshot(); save_memory(original_text, "screenshot"); return
if intent == "LOCK":
    lock_device(); save_memory(original_text, "lock"); return
if intent == "UNLOCK":
    unlock_device(); save_memory(original_text, "unlock"); return
if intent == "CAMERA":
    camera_photo(); save_memory(original_text, "camera"); return
if intent == "VOLUME_UP":
    set_volume(15); save_memory(original_text, "volume_up"); return
if intent == "VOLUME_DOWN":
    set_volume(3); save_memory(original_text, "volume_down"); return
if intent == "VOLUME_MUTE":
    set_volume(0); save_memory(original_text, "volume_mute"); return
if intent == "TIME":
    speak(time.strftime("अभी समय है %H:%M:%S")); save_memory(original_text, "time"); return
if intent == "BATTERY":
    if IS_TERMUX:
        try:
            out = subprocess.check_output(["dumpsys","battery"], text=True)
            m = re.search(r"level: (\d+)", out)
            level = m.group(1) if m else "unknown"
            speak(f"बैटरी {level}% है")
        except Exception:
            speak("बैटरी लेवल नहीं मिला")
    else:
        speak("बैटरी info केवल Android/Termux पर")
    save_memory(original_text, "battery"); return
if intent == "OPEN_APP":
    opened = open_app(meta); save_memory(original_text, f"open_app:{meta}:{opened}"); return
if intent == "TRADE_ADVICE":
    if meta == "bitcoin":
        speak(trading_suggestion_for_btc()); save_memory(original_text, "trade_btc"); return
if intent == "AUTHORIZED_SCAN":
    target = meta
    if not target:
        speak("कृपया लक्ष्य बताइए — IP या domain."); return
    if not is_valid_hostname_or_ip(target):
        speak("लक्ष्य invalid है."); return
    wl = load_json(WHITELIST_FILE, {})
    if target not in wl:
        speak("यह लक्ष्य whitelist में नहीं है — मालिक से invitation token लें.")
        audit_log({"action":"scan_blocked","target":target,"reason":"not_whitelisted"})
        return
    speak("Owner invite token terminal में डालिए.")
    token = input("Invite token: ").strip()
    if not verify_invite_token(target, token):
        speak("Token invalid. Aborting.")
        audit_log({"action":"token_invalid","target":target})
        return
    if not require_typed_confirmation():
        speak("Confirmation नहीं मिला — Aborting."); return
    ok, out = run_approved_action("port_scan", target=target)
    speak("Scan complete. Summary:" if ok else "Scan failed:")
    if out:
        for ln in (out[:300] if len(out) > 300 else out).splitlines()[:6]:
            print(ln)
    return

# Unknown → smalltalk or HF
st = smalltalk_reply(original_text)
if st:
    speak(st); save_memory(original_text, st); return
speak("सोच रहा हूँ…")
hf_out, err = hf_query(original_text)
if hf_out:
    trimmed = hf_out.strip()
    speak(trimmed if len(trimmed) < 300 else trimmed[:300] + "…")
    save_memory(original_text, trimmed)
    log_feedback(original_text, "success", "hf_reply")
else:
    speak("समझ नहीं आया — क्या सरल शब्दों में बोलोगे?")
    log_feedback(original_text, "fail", err or "hf_fail")
    save_memory(original_text, "hf_fail")

def run_voice_loop(): while True: try: text = listen_google_stt() if not text: text = listen_vosk_offline() if not text: continue print(f"तुम बोले: {text}") log_usage(text) intent, meta = normalize_and_intent(text) handle_intent(intent, meta, text) except KeyboardInterrupt: speak("सर्विस बंद कर रहा हूँ — बाय") break except Exception as e: print("[voice_loop]", e) time.sleep(0.8)

def run_text_loop(): speak("Text mode चालू है. Type commands (exit/quit to stop)") while True: try: cmd = input("[ABHI] >>> ").strip() if not cmd: continue if cmd.lower() in ("exit","quit","bye"): speak("बाय 👋"); break log_usage(cmd) intent, meta = normalize_and_intent(cmd) handle_intent(intent, meta, cmd) except KeyboardInterrupt: speak("बाय 👋"); break except Exception as e: print("[text_loop]", e)

───────────────────────── Updater Daemon ─────────────────────────

def check_and_update(): if not UPDATE_URL: return try: r = requests.get(UPDATE_URL, timeout=10) if r.status_code != 200: return new_code = r.text with open(SELF_FILE, "r", encoding="utf-8") as f: cur = f.read() if new_code and new_code != cur: speak("नया संस्करण उपलब्ध — अपडेट कर रहा हूँ") with open(SELF_FILE, "w", encoding="utf-8") as f: f.write(new_code) speak("अपडेट पूरा — कृपया script दोबारा चलाएँ") except Exception: pass

def updater_daemon(): while True: time.sleep(UPDATE_INTERVAL) check_and_update()

───────────────────────── Boot / Auto‑mic + Auto‑switch ─────────────────────────

def boot(auto_native_hint=False): # 1) updater threading.Thread(target=updater_daemon, daemon=True).start()

# 2) greet + analyze hint
speak("ABHI ready!")
analyze()

# 3) mic & environment
mic_ok = any_microphone_available()
env = "termux" if IS_TERMUX else ("linux-proot" if is_inside_proot_like_linux() else platform.system().lower())
print(f"[ABHI] Env: {env} | Mic: {'yes' if mic_ok else 'no'}")

if mic_ok:
    run_voice_loop(); return

# No mic available
if not IS_TERMUX and is_inside_proot_like_linux() and not auto_native_hint:
    # We are likely inside Ubuntu/proot on Android via Termux; attempt auto‑switch to Termux native
    # Best effort: only works if this script is in /sdcard visible to Termux
    sdcard_candidates = [SELF_FILE]
    # If script not already in /sdcard, try to locate same name in /sdcard
    base = os.path.basename(SELF_FILE)
    if not SELF_FILE.startswith("/sdcard/"):
        sdcard_candidates.append(f"/sdcard/{base}")
    for candidate in sdcard_candidates:
        ok, msg = try_relaunch_in_termux(candidate, extra_args=["--native"])
        if ok:
            speak("Mic नहीं — Termux native mode में स्विच कर रहा हूँ")
            # Do not wait; exit current process to avoid double instances
            time.sleep(1)
            os._exit(0)
    # If relaunch failed → fall through to text mode
    print("[ABHI] Auto‑switch failed:", msg)

# Final fallback: text mode
speak("Mic नहीं मिला — Text mode पर शिफ्ट कर रहा हूँ")
run_text_loop()

───────────────────────── Argparse / Terminal helper ─────────────────────────

def terminal_monitor(): while True: try: cmd = input().strip() if not cmd: continue C = cmd.upper() if C == "CONFIRM": suggested = load_json(SUGGESTED_FIXES, []) if not suggested: print("कोई suggested fixes नहीं है."); continue first = suggested.pop(0); save_json(SUGGESTED_FIXES, suggested) action = first.get("command", "") if action.startswith("open_app:"): app_name = action.split(":",1)[1] mapping = load_json(APP_MAP_FILE, DEFAULT_APP_MAP.copy()) mapping[app_name] = "com.example.placeholder" save_json(APP_MAP_FILE, mapping) print(f"Placeholder mapping added for '{app_name}'. Edit {APP_MAP_FILE} for real package.") speak(f"{app_name} के लिए placeholder जोड़ दिया — फ़ाइल एडिट करके सही package डाल देना") else: print("Applied safe non‑destructive suggestion (logged).") elif C == "ANALYZE": analyze(); print("Analyze complete.") elif C == "SHOWLOGS": fb = load_json(FEEDBACK_FILE, []) print("Recent feedback (last 10):") for e in fb[-10:]: print(e) elif C in ("EXIT","QUIT"): speak("सर्विस बंद कर रहा हूँ — बाय"); os._exit(0) else: print("Commands: CONFIRM, ANALYZE, SHOWLOGS, EXIT") except Exception as e: print("[term_mon]", e) time.sleep(0.5)

def parse_args(): ap = argparse.ArgumentParser() ap.add_argument("--native", action="store_true", help="hint: running under Termux native") ap.add_argument("--command", help="run single normalized command in text mode then exit") return ap.parse_args()

if name == "main": args = parse_args()

# Start terminal helper (so CONFIRM etc. work while voice/text loop runs)
threading.Thread(target=terminal_monitor, daemon=True).start()

if args.command:
    # one‑shot command execution (useful for bridges)
    intent, meta = normalize_and_intent(args.command)
    handle_intent(intent, meta, args.command)
    sys.exit(0)

boot(auto_native_hint=args.native)


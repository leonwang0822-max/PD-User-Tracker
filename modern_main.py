
import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
import threading
import json
import os
import time
import urllib.request
import re
import socket
import queue
import requests
import random
from PIL import Image, ImageTk
from io import BytesIO
import webbrowser
import winsound

# Configuration Constants
CONFIG_FILE = "config.json"
DEFAULT_CONFIG = {
    "platform": "YouTube",
    "target_id": "",
    "cmd_prefix": "",
    "limit": 2,
    "auto_copy": True,
    "history": {},
    "blacklist": ["roblox", "builderman", "robux"],
    "webhook_url": "",
    "theme": "Dark",
    "color_theme": "blue"
}

# Twitch Client (Reuse existing logic with minor cleanups)
class TwitchClient:
    def __init__(self, channel):
        self.sock = socket.socket()
        self.channel = channel.lower().replace("#", "")
        self.running = True
        self.buffer = ""
        self.connected = False

    def connect(self):
        try:
            self.sock = socket.socket()
            self.sock.settimeout(2)
            self.sock.connect(("irc.chat.twitch.tv", 6667))
            self.sock.send(f"NICK justinfan{int(time.time())}\n".encode("utf-8"))
            self.sock.send(f"JOIN #{self.channel}\n".encode("utf-8"))
            self.connected = True
            return True
        except:
            return False

    def get_messages(self):
        if not self.connected:
            return []
        try:
            try:
                resp = self.sock.recv(2048).decode("utf-8")
            except socket.timeout:
                return []
            self.buffer += resp
            msgs = []
            if "\n" in self.buffer:
                lines = self.buffer.split("\n")
                self.buffer = lines.pop()
                for line in lines:
                    if "PRIVMSG" in line:
                        parts = line.split(":", 2)
                        if len(parts) > 2:
                            # Parse author from :nick!user@host
                            author = "Unknown"
                            if "!" in parts[1]:
                                author = parts[1].split("!")[0]
                            msgs.append((author, parts[2].strip()))
            return msgs
        except:
            return []

    def close(self):
        self.running = False
        self.connected = False
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except:
            pass
        try:
            self.sock.close()
        except:
            pass

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.cfg = self.load_config()
        ctk.set_appearance_mode(self.cfg.get("theme", "Dark"))
        ctk.set_default_color_theme(self.cfg.get("color_theme", "blue"))

        self.title("PD User Tracker Pro")
        self.geometry("900x600")
        self.minsize(800, 500)

        # State variables
        self.seen = self.cfg.get("history", {})
        if isinstance(self.seen, list):
            self.seen = {u: 1 for u in self.seen}
        
        self.listener = None
        self.run = False
        self.pause = False
        self.current_user = None
        self.processing_queue = queue.Queue()
        self.thread = None
        self.avatar_cache = {}
        self.candidates = []
        
        # Performance Queues
        self.log_queue = queue.Queue()
        self.raffle_queue = queue.Queue()

        # Setup UI
        self.setup_ui()
        
        # Start UI updaters
        self.after(100, self.process_log_queue)
        self.after(200, self.process_raffle_queue)
        
        # Handle protocol
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                loaded = json.load(open(CONFIG_FILE))
                return {**DEFAULT_CONFIG, **loaded}
            except:
                pass
        return DEFAULT_CONFIG.copy()

    def save_config(self):
        self.cfg["platform"] = self.platform_var.get()
        self.cfg["target_id"] = self.target_entry.get()
        self.cfg["cmd_prefix"] = self.prefix_entry.get()
        self.cfg["auto_copy"] = self.auto_copy_var.get()
        self.cfg["webhook_url"] = self.webhook_entry.get()
        try:
            self.cfg["limit"] = int(self.limit_entry.get())
        except:
            self.cfg["limit"] = 1
        
        self.cfg["history"] = self.seen
        
        json.dump(self.cfg, open(CONFIG_FILE, "w"), indent=4)

    def setup_ui(self):
        # Grid layout
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- Sidebar ---
        self.sidebar = ctk.CTkFrame(self, width=250, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(8, weight=1)

        self.logo_label = ctk.CTkLabel(self.sidebar, text="PD Tracker Pro", font=ctk.CTkFont(size=20, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        # Controls
        self.start_btn = ctk.CTkButton(self.sidebar, text="Start Listening", command=self.start_listening, fg_color="green")
        self.start_btn.grid(row=1, column=0, padx=20, pady=10)
        
        self.stop_btn = ctk.CTkButton(self.sidebar, text="Stop", command=self.stop_listening, fg_color="red", state="disabled")
        self.stop_btn.grid(row=2, column=0, padx=20, pady=10)

        self.next_btn = ctk.CTkButton(self.sidebar, text="Next User >>", command=self.on_next, height=40)
        self.next_btn.grid(row=3, column=0, padx=20, pady=(20, 10))

        self.copy_btn = ctk.CTkButton(self.sidebar, text="Copy Username", command=self.copy_user)
        self.copy_btn.grid(row=4, column=0, padx=20, pady=10)

        # Raffle Mode
        self.raffle_mode_var = ctk.BooleanVar(value=False)
        self.raffle_switch = ctk.CTkSwitch(self.sidebar, text="Raffle Mode", variable=self.raffle_mode_var)
        self.raffle_switch.grid(row=5, column=0, padx=20, pady=10)

        self.pick_btn = ctk.CTkButton(self.sidebar, text="Pick Random Winner", command=self.pick_winner, fg_color="purple")
        self.pick_btn.grid(row=6, column=0, padx=20, pady=10)

        # Settings Section
        ctk.CTkLabel(self.sidebar, text="Settings", anchor="w").grid(row=7, column=0, padx=20, pady=(20, 0), sticky="w")
        
        self.platform_var = ctk.StringVar(value=self.cfg.get("platform"))
        self.platform_menu = ctk.CTkOptionMenu(self.sidebar, values=["YouTube", "Twitch"], variable=self.platform_var)
        self.platform_menu.grid(row=8, column=0, padx=20, pady=10)

        self.target_entry = ctk.CTkEntry(self.sidebar, placeholder_text="Video ID / Channel Name")
        self.target_entry.insert(0, self.cfg.get("target_id", ""))
        self.target_entry.grid(row=9, column=0, padx=20, pady=10)

        # Bottom of sidebar
        self.status_label = ctk.CTkLabel(self.sidebar, text="Status: Ready", text_color="gray")
        self.status_label.grid(row=10, column=0, padx=20, pady=10)

        # --- Main Content Area ---
        self.main_area = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.main_area.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        self.main_area.grid_rowconfigure(1, weight=1)
        self.main_area.grid_columnconfigure(0, weight=1)

        # Tabview
        self.tabview = ctk.CTkTabview(self.main_area)
        self.tabview.grid(row=0, column=0, sticky="nsew")
        self.tabview.add("Live Feed")
        self.tabview.add("Configuration")
        self.tabview.add("History & Blacklist")

        # -- Live Feed Tab --
        self.feed_frame = self.tabview.tab("Live Feed")
        self.feed_frame.grid_columnconfigure(0, weight=1)
        self.feed_frame.grid_rowconfigure(1, weight=1)
        self.feed_frame.grid_rowconfigure(3, weight=1)

        # Current User Card
        self.user_card = ctk.CTkFrame(self.feed_frame, fg_color=("gray90", "gray20"))
        self.user_card.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        self.user_card.grid_columnconfigure(1, weight=1)

        # Avatar placeholder
        self.avatar_label = ctk.CTkLabel(self.user_card, text="[No User]", width=150, height=150, corner_radius=10, fg_color="black")
        self.avatar_label.grid(row=0, column=0, rowspan=3, padx=15, pady=15)

        # Username info
        self.username_label = ctk.CTkLabel(self.user_card, text="Waiting...", font=ctk.CTkFont(size=24, weight="bold"))
        self.username_label.grid(row=0, column=1, sticky="w", padx=10, pady=(15, 0))

        self.user_stats_label = ctk.CTkLabel(self.user_card, text="Stats: -")
        self.user_stats_label.grid(row=1, column=1, sticky="w", padx=10)
        
        self.open_roblox_btn = ctk.CTkButton(self.user_card, text="Open Profile", command=self.open_profile, width=100)
        self.open_roblox_btn.grid(row=2, column=1, sticky="w", padx=10, pady=(0, 15))

        # Log Box
        self.log_box = ctk.CTkTextbox(self.feed_frame, font=ctk.CTkFont(family="Consolas", size=12), height=150)
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=10, pady=(10, 5))
        self.log_box.configure(state="disabled")
        
        # Configure tags for log colors
        # Accessing the underlying tk.Text widget to configure tags
        try:
            self.log_box._textbox.tag_config("success", foreground="#00FF00") # Green
            self.log_box._textbox.tag_config("error", foreground="#FF5555")   # Red
            self.log_box._textbox.tag_config("chat", foreground="#AAAAAA")    # Grey
        except:
            pass # Fallback if internal API changes

        # Raffle Entries Box
        ctk.CTkLabel(self.feed_frame, text="Raffle Entries:", anchor="w").grid(row=2, column=0, sticky="w", padx=10)
        self.entries_box = ctk.CTkTextbox(self.feed_frame, font=ctk.CTkFont(family="Consolas", size=12), height=100)
        self.entries_box.grid(row=3, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.entries_box.configure(state="disabled")

        # -- Configuration Tab --
        self.config_frame = self.tabview.tab("Configuration")

        ctk.CTkLabel(self.config_frame, text="Command Prefix (e.g. !donate):").pack(pady=(10, 0), anchor="w", padx=20)
        self.prefix_entry = ctk.CTkEntry(self.config_frame)
        self.prefix_entry.insert(0, self.cfg.get("cmd_prefix", ""))
        self.prefix_entry.pack(fill="x", padx=20, pady=5)

        ctk.CTkLabel(self.config_frame, text="Limit per User (0 = infinite):").pack(pady=(10, 0), anchor="w", padx=20)
        self.limit_entry = ctk.CTkEntry(self.config_frame)
        self.limit_entry.insert(0, str(self.cfg.get("limit", 2)))
        self.limit_entry.pack(fill="x", padx=20, pady=5)

        self.auto_copy_var = ctk.BooleanVar(value=self.cfg.get("auto_copy", False))
        ctk.CTkCheckBox(self.config_frame, text="Auto-Copy Username on Find", variable=self.auto_copy_var).pack(pady=10, anchor="w", padx=20)

        ctk.CTkLabel(self.config_frame, text="Discord Webhook URL (Optional):").pack(pady=(10, 0), anchor="w", padx=20)
        self.webhook_entry = ctk.CTkEntry(self.config_frame, placeholder_text="https://discord.com/api/webhooks/...")
        self.webhook_entry.insert(0, self.cfg.get("webhook_url", ""))
        self.webhook_entry.pack(fill="x", padx=20, pady=5)

        ctk.CTkButton(self.config_frame, text="Save Settings", command=self.save_config_manual).pack(pady=20, padx=20, fill="x")

        # -- History & Blacklist Tab --
        self.hist_frame = self.tabview.tab("History & Blacklist")
        
        self.blacklist_entry = ctk.CTkEntry(self.hist_frame, placeholder_text="Username to blacklist")
        self.blacklist_entry.pack(pady=(10, 5), padx=20, fill="x")
        
        btn_frame = ctk.CTkFrame(self.hist_frame, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20)
        ctk.CTkButton(btn_frame, text="Add to Blacklist", command=self.add_blacklist).pack(side="left", expand=True, padx=5)
        ctk.CTkButton(btn_frame, text="Clear History", command=self.clear_history, fg_color="red").pack(side="right", expand=True, padx=5)

        self.bl_listbox = ctk.CTkTextbox(self.hist_frame, height=150)
        self.bl_listbox.pack(fill="both", expand=True, padx=20, pady=10)
        self.refresh_blacklist_ui()

    def log(self, message, type="info"):
        self.log_queue.put((message, type))

    def process_log_queue(self):
        if not self.log_queue.empty():
            self.log_box.configure(state="normal")
            
            # Process up to 50 messages at a time to avoid freezing
            count = 0
            while not self.log_queue.empty() and count < 50:
                message, type = self.log_queue.get()
                timestamp = time.strftime("[%H:%M:%S] ")
                
                tag = "info"
                if type == "success": tag = "success"
                elif type == "error": tag = "error"
                elif type == "chat": tag = "chat"
                
                self.log_box.insert("end", timestamp + message + "\n", tag)
                count += 1
            
            # Limit history to ~1000 lines
            # A rough approximation: 1000 chars * 100 lines? 
            # Easier: check line count
            try:
                lines = int(self.log_box._textbox.index('end-1c').split('.')[0])
                if lines > 1000:
                    self.log_box.delete("1.0", f"{lines-800}.0") # Keep last ~800
            except:
                pass

            self.log_box.see("end")
            self.log_box.configure(state="disabled")
            
        self.after(100, self.process_log_queue)

    def status(self, msg):
        self.status_label.configure(text=f"Status: {msg}")

    def save_config_manual(self):
        self.save_config()
        self.status("Configuration Saved!")
        messagebox.showinfo("Saved", "Configuration saved successfully.")

    def refresh_blacklist_ui(self):
        self.bl_listbox.configure(state="normal")
        self.bl_listbox.delete("0.0", "end")
        for user in self.cfg.get("blacklist", []):
            self.bl_listbox.insert("end", f"{user}\n")
        self.bl_listbox.configure(state="disabled")

    def add_blacklist(self):
        user = self.blacklist_entry.get().strip().lower()
        if user:
            bl = self.cfg.get("blacklist", [])
            if user not in bl:
                bl.append(user)
                self.cfg["blacklist"] = bl
                self.save_config()
                self.refresh_blacklist_ui()
                self.blacklist_entry.delete(0, "end")
                self.log(f"Blacklisted: {user}")

    def clear_history(self):
        if messagebox.askyesno("Confirm", "Are you sure you want to clear all history?"):
            self.seen = {}
            self.save_config()
            self.log("History cleared.")

    def start_listening(self):
        if self.run: return
        
        # Save config before starting
        self.save_config()
        
        target = self.cfg["target_id"]
        if not target:
            messagebox.showerror("Error", "Please enter a Channel ID or Video ID")
            return

        self.current_user = None
        self.processing_queue = queue.Queue()
        self.candidates = []
        
        platform = self.cfg.get("platform", "YouTube")
        
        try:
            if platform == "YouTube":
                import pytchat
                try:
                    self.listener = pytchat.create(video_id=target)
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to connect to YouTube: {e}")
                    return
            else:
                self.listener = TwitchClient(target)
                if not self.listener.connect():
                    messagebox.showerror("Error", "Failed to connect to Twitch")
                    return

            self.run = True
            self.pause = False
            self.start_btn.configure(state="disabled", fg_color="gray")
            self.stop_btn.configure(state="normal", fg_color="red")
            
            self.thread = threading.Thread(target=self.loop, daemon=True)
            self.thread.start()
            
            self.status(f"Listening on {platform}...")
            self.log(f"Started listening on {platform} ({target})")
            
        except Exception as e:
            messagebox.showerror("Error", str(e))
            self.stop_listening()

    def stop_listening(self):
        self.run = False
        self.pause = False
        
        if hasattr(self, "listener") and self.listener:
            try:
                if isinstance(self.listener, TwitchClient):
                    self.listener.close()
                else:
                    self.listener.terminate()
            except:
                pass
        self.listener = None
        
        self.start_btn.configure(state="normal", fg_color="green")
        self.stop_btn.configure(state="disabled", fg_color="gray")
        self.status("Stopped")
        self.log("Stopped listening.")

    def on_next(self):
        if not self.run:
            self.status("Not running")
            return
        
        self.pause = False
        self.current_user = None
        
        # Reset UI
        self.username_label.configure(text="Scanning...")
        self.avatar_label.configure(image=None, text="[Scanning]")
        self.user_stats_label.configure(text="Stats: -")
        
        self.status("Scanning...")
        
        # Clear entries box if raffle mode is off or we want fresh start
        if not self.raffle_mode_var.get():
             self.candidates = []
             self.entries_box.configure(state="normal")
             self.entries_box.delete("0.0", "end")
             self.entries_box.configure(state="disabled")

    def pick_winner(self):
        if not self.candidates:
            self.status("Raffle pool is empty!")
            messagebox.showinfo("Raffle", "No candidates in the pool yet.")
            return

        # Pick random
        winner = random.choice(self.candidates)
        self.log(f"Picking winner... Selected: {winner}")
        
        # Verify
        info = self.fetch_roblox_info(winner)
        if info:
            self.candidates.remove(winner) # Remove winner from pool
            
            # Update history
            current_count = self.seen.get(winner, 0) + 1
            self.seen[winner] = current_count
            self.save_config()
            
            self.current_user = winner
            self.update_ui_for_user(winner, info)
            self.log(f"WINNER: {winner}", "success")
            self.status(f"Winner: {winner}")
            
            if self.cfg.get("auto_copy"):
                self.copy_user()
        else:
            self.log(f"Invalid winner: {winner}. Picking again...", "error")
            self.candidates.remove(winner)
            self.pick_winner() # Recursive retry

    def copy_user(self):
        if self.current_user:
            self.clipboard_clear()
            self.clipboard_append(self.current_user)
            self.log(f"Copied {self.current_user} to clipboard")
            self.status(f"Copied {self.current_user}")
        else:
            self.status("No user to copy")

    def add_entry_ui(self, username):
        self.raffle_queue.put(username)

    def process_raffle_queue(self):
        if not self.raffle_queue.empty():
            self.entries_box.configure(state="normal")
            
            count = 0
            while not self.raffle_queue.empty() and count < 20:
                username = self.raffle_queue.get()
                self.entries_box.insert("end", f"{username}\n")
                count += 1
            
            self.entries_box.see("end")
            self.entries_box.configure(state="disabled")
            
        self.after(200, self.process_raffle_queue)

    def open_profile(self):
        if self.current_user:
            webbrowser.open(f"https://www.roblox.com/search/users?keyword={self.current_user}")

    def fetch_roblox_info(self, username):
        try:
            # 1. Get ID
            payload = {"usernames": [username], "excludeBannedUsers": True}
            resp = requests.post("https://users.roproxy.com/v1/usernames/users", json=payload, timeout=3)
            data = resp.json()
            
            if data.get("data") and len(data["data"]) > 0:
                user_data = data["data"][0]
                user_id = user_data["id"]
                display_name = user_data["displayName"]
                
                # 2. Get Avatar
                avatar_url = f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=420x420&format=Png&isCircular=false"
                av_resp = requests.get(avatar_url, timeout=3)
                av_data = av_resp.json()
                
                if av_data.get("data") and len(av_data["data"]) > 0:
                    img_url = av_data["data"][0]["imageUrl"]
                    return {"id": user_id, "display": display_name, "image_url": img_url}
                    
            return None
        except Exception as e:
            print(f"Error fetching roblox info: {e}")
            return None

    def update_ui_for_user(self, username, info):
        self.username_label.configure(text=username)
        
        limit_str = self.cfg.get("limit", 2)
        count = self.seen.get(username, 1)
        self.user_stats_label.configure(text=f"Seen: {count}/{limit_str} | ID: {info['id']}")

        # Load image
        try:
            if info["image_url"]:
                response = requests.get(info["image_url"])
                img_data = BytesIO(response.content)
                pil_image = Image.open(img_data)
                pil_image = pil_image.resize((150, 150), Image.Resampling.LANCZOS)
                ctk_image = ctk.CTkImage(light_image=pil_image, dark_image=pil_image, size=(150, 150))
                self.avatar_label.configure(image=ctk_image, text="")
                self.current_avatar_image = ctk_image # Keep reference to prevent GC
        except Exception as e:
            self.log(f"Failed to load avatar: {e}")
            self.avatar_label.configure(image=None, text="[Img Error]")

        # Play sound
        try:
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except:
            pass

        # Webhook
        webhook_url = self.cfg.get("webhook_url")
        if webhook_url:
            self.send_webhook(username, info, webhook_url)

    def send_webhook(self, username, info, url):
        try:
            data = {
                "content": f"Found User: **{username}**",
                "embeds": [{
                    "title": "PD User Tracker",
                    "description": f"User **{username}** found in chat!",
                    "thumbnail": {"url": info.get("image_url", "")},
                    "fields": [
                        {"name": "Roblox ID", "value": str(info.get("id")), "inline": True},
                        {"name": "Display Name", "value": info.get("display", "N/A"), "inline": True}
                    ],
                    "color": 65280
                }]
            }
            requests.post(url, json=data)
        except:
            pass

    def loop(self):
        while self.run:
            while self.pause and self.run:
                time.sleep(0.1)
            if not self.run:
                break

            try:
                raw_msgs = []
                if isinstance(self.listener, TwitchClient):
                    raw_msgs = self.listener.get_messages()
                else:
                    if self.listener.is_alive():
                        data = self.listener.get()
                        if data:
                            raw_msgs = [(i.author.name, str(i.message)) for i in data.items]
                    else:
                        self.log("Connection lost, retrying...", "error")
                        time.sleep(2)
                        continue

                prefix = self.cfg.get("cmd_prefix", "")
                user_limit = int(self.cfg.get("limit", 2))
                blacklist = [x.lower() for x in self.cfg.get("blacklist", [])]

                for author, msg in raw_msgs:
                    clean_msg = re.sub(r":[a-zA-Z0-9_-]+:", "", msg).strip()
                    if not clean_msg: continue
                    
                    # Display in log only if it looks interesting or debug mode (optional)
                    # Use log_queue directly to avoid creating too many lambdas/after calls
                    self.log_queue.put((f"Chat [{author}]: {clean_msg}", "chat"))

                    m = clean_msg.replace(" ", "").lower()
                    if m.startswith(prefix):
                        u = m[len(prefix):]
                        times_seen = self.seen.get(u, 0)
                        
                        if u and (user_limit == 0 or times_seen < user_limit):
                            if u.lower() not in blacklist:
                                self.processing_queue.put(u)

                # Process queue
                while not self.processing_queue.empty() and not self.pause and self.run:
                    candidate = self.processing_queue.get()
                    
                    # Double check blacklist/limit
                    if candidate.lower() in blacklist: continue
                    if user_limit != 0 and self.seen.get(candidate, 0) >= user_limit: continue

                    if self.raffle_mode_var.get():
                        # Raffle Mode: Collect only
                        if candidate not in self.candidates:
                            self.candidates.append(candidate)
                            # Direct queue push to avoid main thread overhead
                            self.log_queue.put((f"Entry: {candidate} (Pool: {len(self.candidates)})", "info"))
                            self.raffle_queue.put(candidate)
                            self.after(0, lambda c=len(self.candidates): self.status(f"Raffle Pool: {c}"))
                        continue

                    # Verify User
                    info = self.fetch_roblox_info(candidate)
                    if info:
                        # Success!
                        current_count = self.seen.get(candidate, 0) + 1
                        self.seen[candidate] = current_count
                        self.current_user = candidate
                        self.pause = True
                        
                        self.save_config()
                        
                        self.after(0, lambda u=candidate, i=info: self.update_ui_for_user(u, i))
                        self.after(0, lambda u=candidate: self.log(f"FOUND: {u}", "success"))
                        self.after(0, lambda: self.status("User Found! Paused."))
                        
                        if self.cfg.get("auto_copy"):
                            self.after(0, self.copy_user)
                            
                        break # Stop processing queue, we found one
                    
            except Exception as e:
                print(f"Loop error: {e}")
            
            time.sleep(0.5)

    def on_close(self):
        self.stop_listening()
        self.destroy()

if __name__ == "__main__":
    app = App()
    app.mainloop()

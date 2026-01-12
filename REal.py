import customtkinter as ctk
from PIL import Image, ImageTk
import cv2
from tkinter import filedialog, messagebox
import json
import base64
import requests
from io import BytesIO
import os
from datetime import datetime
import time
from functools import wraps
import sqlite3
import hashlib

# -------------------- CONFIGURATION --------------------
GEMINI_API_KEY = 'AIzaSyDusA-lDLw_kg_1PJzo6FZY0RtFQGKhkTc' # Note: Keep your API key private
API_URL = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={GEMINI_API_KEY}'
HISTORY_FILE = 'scan_history.json'
DB_FILE = 'user_data.db'

# Rate limiting settings (15 RPM safe limit)
last_api_call = 0
MIN_CALL_INTERVAL = 4

# -------------------- DATABASE FUNCTIONS --------------------
def init_db():
    """Initialize the local SQLite database for users"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        # Create users table if not exists
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT
            )
        ''')
        conn.commit()
        conn.close()
    except Exception as e:
        messagebox.showerror("Database Error", f"Could not initialize database: {e}")

def hash_password(password):
    """Hash a password using SHA-256 for security"""
    return hashlib.sha256(password.encode()).hexdigest()

def register_user(full_name, email, password):
    """Register a new user in the database"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        # Check if email already exists
        c.execute("SELECT email FROM users WHERE email=?", (email,))
        if c.fetchone():
            conn.close()
            return False, "Email already registered."
        
        hashed_pw = hash_password(password)
        created_at = datetime.now().isoformat()
        
        c.execute("INSERT INTO users (full_name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                  (full_name, email, hashed_pw, created_at))
        conn.commit()
        conn.close()
        return True, "Account created successfully!"
    except Exception as e:
        return False, str(e)

def login_user(email, password):
    """Verify user credentials"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        hashed_pw = hash_password(password)
        
        c.execute("SELECT * FROM users WHERE email=? AND password_hash=?", (email, hashed_pw))
        user = c.fetchone()
        conn.close()
        
        if user:
            # user structure: (id, name, email, pass, date)
            return True, user[1] # Return success and Full Name
        else:
            return False, "Invalid email or password."
    except Exception as e:
        return False, str(e)

# -------------------- HELPER FUNCTIONS --------------------
def encode_image_to_base64(image_path, max_size=(600, 600)):
    try:
        img = Image.open(image_path)
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
            img = background
        buffered = BytesIO()
        img.save(buffered, format="JPEG", quality=85, optimize=True)
        return base64.b64encode(buffered.getvalue()).decode('utf-8')
    except Exception as e:
        raise Exception(f"Image encoding failed: {str(e)}")

def rate_limit(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        global last_api_call
        current_time = time.time()
        time_since_last = current_time - last_api_call
        if time_since_last < MIN_CALL_INTERVAL:
            wait_time = MIN_CALL_INTERVAL - time_since_last
            raise Exception(f"Please wait {wait_time:.1f} seconds.")
        last_api_call = current_time
        return func(*args, **kwargs)
    return wrapper

@rate_limit
def analyze_plant_with_gemini(image_path):
    try:
        image_base64 = encode_image_to_base64(image_path)
        prompt = """Analyze this plant for the Philippines. Provide in plain text (no asterisks/markdown):
1. Common Name (Philippine)
2. Scientific Name
3. Brief Description
4. Uses
5. Health Benefits
6. Safety Notes"""

        payload = {
            "contents": [{"parts": [{"text": prompt}, {"inline_data": {"mime_type": "image/jpeg", "data": image_base64}}]}],
            "generationConfig": {"temperature": 0.4, "maxOutputTokens": 800},
            "safetySettings": [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
            ]
        }
        
        response = requests.post(API_URL, json=payload, headers={"Content-Type": "application/json"})
        if response.status_code != 200:
            raise Exception(f"API Error: {response.status_code}")
        
        data = response.json()
        if data.get('candidates') and len(data['candidates']) > 0:
            text = data['candidates'][0]['content']['parts'][0]['text']
            # Clean text
            clean_text = text.replace('**', '').replace('*', '').replace('###', '').replace('#', '').strip()
            return {'success': True, 'response': clean_text, 'timestamp': datetime.now().isoformat()}
        
        raise Exception('Invalid response format')
    except Exception as e:
        return {'success': False, 'error': str(e), 'timestamp': datetime.now().isoformat()}

def save_to_history(image_path, result):
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'r') as f: history = json.load(f)
        else: history = []
        
        entry = {
            'id': datetime.now().strftime('%Y%m%d_%H%M%S'),
            'image_path': image_path,
            'timestamp': result['timestamp'],
            'response': result.get('response', ''),
            'success': result['success']
        }
        history.insert(0, entry)
        with open(HISTORY_FILE, 'w') as f: json.dump(history[:50], f, indent=2)
        return True
    except Exception as e:
        print(f"History Save Error: {e}")
        return False

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r') as f: return json.load(f)
    return []

# -------------------- UI SETTINGS --------------------
ctk.set_appearance_mode("light")
ctk.set_default_color_theme("green")

# -------------------- MAIN APP --------------------
class HerbalScannerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        # Initialize Database on startup
        init_db()
        
        self.title("Herbal Scanner")
        self.geometry("950x670")
        self.resizable(False, False)
        
        # Track current user
        self.current_user_name = None

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.frames = {}
        for F in (LoginFrame, RegisterFrame, HomeFrame, ScannerFrame, HistoryFrame):
            frame = F(self)
            self.frames[F] = frame
            frame.grid(row=0, column=0, sticky="nsew")

        self.show_frame(LoginFrame)

    def show_frame(self, frame_class):
        frame = self.frames[frame_class]
        frame.tkraise()
        # Auto-refresh history when opening that tab
        if frame_class == HistoryFrame:
            frame.refresh_history()

# -------------------- HEADER --------------------
class Header(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent, fg_color="#295222", height=80)
        self.controller = controller
        self.pack_propagate(False)

        ctk.CTkLabel(self, text="🌿 HerbalScan ", font=("Arial", 24, "bold"), text_color="white").pack(side="left", padx=20)

        for nav, target in [("HOME", HomeFrame), ("SCANNER", ScannerFrame), ("HISTORY", HistoryFrame)]:
            ctk.CTkButton(
                self, text=nav, fg_color="#406343", text_color="white",
                hover_color="#2d4a30", command=lambda t=target: controller.show_frame(t),
                corner_radius=8, height=35
            ).pack(side="left", padx=5)

        ctk.CTkButton(self, text="LOGOUT", fg_color="#dc3545", text_color="white",
                      hover_color="#c82333", command=lambda: self.logout(controller),
                      corner_radius=8, height=35).pack(side="right", padx=20)
    
    def logout(self, controller):
        controller.current_user_name = None
        controller.show_frame(LoginFrame)

# -------------------- LOGIN FRAME --------------------
class LoginFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color="#f0f2f0")
        self.parent = parent
        
        self.login_box = ctk.CTkFrame(self, fg_color="white", width=350, height=450, corner_radius=15)
        self.login_box.place(relx=0.5, rely=0.5, anchor="center")
        self.login_box.pack_propagate(False)

        ctk.CTkLabel(self.login_box, text="🌿", font=("Arial", 40)).pack(pady=(40, 10))
        ctk.CTkLabel(self.login_box, text="HerbalScan Login", font=("Arial", 22, "bold"), text_color="#295222").pack(pady=(0,20))

        self.email_entry = ctk.CTkEntry(self.login_box, placeholder_text="Email Address", width=250, height=40)
        self.email_entry.pack(pady=10)
        
        self.password_entry = ctk.CTkEntry(self.login_box, placeholder_text="Password", show="*", width=250, height=40)
        self.password_entry.pack(pady=10)

        login_btn = ctk.CTkButton(self.login_box, text="Login", width=250, height=40, fg_color="#295222", 
                                  hover_color="#1f3d1a", font=("Arial", 14, "bold"),
                                  command=self.perform_login)
        login_btn.pack(pady=20)

        ctk.CTkButton(self.login_box, text="Create new account", fg_color="transparent", 
                      text_color="#295222", hover_color="#f0f0f0",
                      command=lambda: parent.show_frame(RegisterFrame)).pack(pady=5)
    
    def perform_login(self):
        email = self.email_entry.get().strip()
        password = self.password_entry.get().strip()
        
        if not email or not password:
            messagebox.showwarning("Input Error", "Please fill in all fields.")
            return

        success, message = login_user(email, password)
        if success:
            self.parent.current_user_name = message
            messagebox.showinfo("Success", f"Welcome back, {message}!")
            self.email_entry.delete(0, 'end')
            self.password_entry.delete(0, 'end')
            self.parent.show_frame(HomeFrame)
        else:
            messagebox.showerror("Login Failed", message)

# -------------------- REGISTER FRAME --------------------
class RegisterFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color="#f0f2f0")
        self.parent = parent
        
        self.reg_box = ctk.CTkFrame(self, fg_color="white", width=350, height=520, corner_radius=15)
        self.reg_box.place(relx=0.5, rely=0.5, anchor="center")
        self.reg_box.pack_propagate(False)

        ctk.CTkLabel(self.reg_box, text="📝", font=("Arial", 40)).pack(pady=(30, 10))
        ctk.CTkLabel(self.reg_box, text="Create Account", font=("Arial", 22, "bold"), text_color="#295222").pack(pady=(0,20))

        self.fullname_entry = ctk.CTkEntry(self.reg_box, placeholder_text="Full Name", width=250, height=40)
        self.fullname_entry.pack(pady=5)

        self.email_entry = ctk.CTkEntry(self.reg_box, placeholder_text="Email Address", width=250, height=40)
        self.email_entry.pack(pady=5)
        
        self.password_entry = ctk.CTkEntry(self.reg_box, placeholder_text="Password", show="*", width=250, height=40)
        self.password_entry.pack(pady=5)

        self.confirm_pass_entry = ctk.CTkEntry(self.reg_box, placeholder_text="Confirm Password", show="*", width=250, height=40)
        self.confirm_pass_entry.pack(pady=5)

        ctk.CTkButton(self.reg_box, text="Register", width=250, height=40, fg_color="#406343", 
                      hover_color="#2d4a30", font=("Arial", 14, "bold"),
                      command=self.perform_register).pack(pady=20)

        ctk.CTkButton(self.reg_box, text="Back to Login", fg_color="transparent", 
                      text_color="gray", hover_color="#f0f0f0",
                      command=lambda: parent.show_frame(LoginFrame)).pack(pady=5)

    def perform_register(self):
        fullname = self.fullname_entry.get().strip()
        email = self.email_entry.get().strip()
        password = self.password_entry.get().strip()
        confirm = self.confirm_pass_entry.get().strip()
        
        if not fullname or not email or not password:
            messagebox.showwarning("Error", "All fields are required.")
            return
        
        if password != confirm:
            messagebox.showerror("Error", "Passwords do not match.")
            return
            
        success, message = register_user(fullname, email, password)
        
        if success:
            messagebox.showinfo("Success", message)
            # Clear fields
            self.fullname_entry.delete(0, 'end')
            self.email_entry.delete(0, 'end')
            self.password_entry.delete(0, 'end')
            self.confirm_pass_entry.delete(0, 'end')
            self.parent.show_frame(LoginFrame)
        else:
            messagebox.showerror("Registration Failed", message)

# -------------------- HOME FRAME --------------------
class HomeFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color="white")
        # FIX: Remove padding so header touches top
        Header(self, parent).pack(fill="x", pady=0)
        
        features_frame = ctk.CTkFrame(self, fg_color="white")
        features_frame.pack(expand=True, fill="both", padx=20, pady=10)
        
        features = [(" Scanner", "Capture or upload plant images", ScannerFrame),
                    (" History", "View your scan history", HistoryFrame)]
        
        for i, (title, desc, target) in enumerate(features):
            card = ctk.CTkFrame(features_frame, fg_color="#f0f0f0", corner_radius=10)
            card.grid(row=0, column=i, padx=15, pady=15, sticky="nsew")
            features_frame.grid_columnconfigure(i, weight=1)
            
            ctk.CTkLabel(card, text=title, font=("Arial", 20, "bold"), text_color="#295222").pack(pady=(20, 10))
            ctk.CTkLabel(card, text=desc, text_color="gray", wraplength=200).pack(pady=(0, 15))
            
            if target:
                ctk.CTkButton(card, text="Go", fg_color="#295222", 
                              command=lambda t=target: parent.show_frame(t)).pack(pady=(0, 20))

# -------------------- SCANNER FRAME --------------------
class ScannerFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color="white")
        self.popup_visible = False
        self.current_image_path = None

        # FIX: Remove padding so header touches top
        Header(self, parent).pack(fill="x", pady=0)

        content = ctk.CTkFrame(self, fg_color="white")
        content.pack(fill="both", expand=True, padx=20, pady=10)
        content.grid_columnconfigure((0,1), weight=1)

        # Left: Scanner
        scanner_col = ctk.CTkFrame(content, fg_color="white")
        scanner_col.grid(row=0, column=0, sticky="nsew", padx=10)
        ctk.CTkLabel(scanner_col, text="Scanner", font=("Arial", 20, "bold"), text_color="#295222").pack(pady=10)

        self.camera_placeholder = ctk.CTkLabel(scanner_col, text="[Camera Preview]", 
                                                fg_color="#e0e0e0", text_color="gray", 
                                                width=350, height=350, corner_radius=10)
        self.camera_placeholder.pack(pady=10)

        btn_row = ctk.CTkFrame(scanner_col, fg_color="white")
        btn_row.pack(pady=5)
        ctk.CTkButton(btn_row, text=" Capture", fg_color="#295222", width=110, 
                      command=self.open_camera).pack(side="left", padx=5)
        ctk.CTkButton(btn_row, text=" Upload", fg_color="#406343", width=110, 
                      command=self.upload_image).pack(side="left", padx=5)
        
        self.analyze_btn = ctk.CTkButton(btn_row, text=" Analyze", fg_color="#4CAF50", width=110, 
                                         command=self.analyze_current_image)
        self.analyze_btn.pack(side="left", padx=5)

        ctk.CTkButton(scanner_col, text="❔ Guide", fg_color="#6c757d", 
                      command=self.toggle_popup).pack(pady=10)

        # Right: Results
        self.result_col = ctk.CTkScrollableFrame(content, fg_color="#f8f9fa", corner_radius=10)
        self.result_col.grid(row=0, column=1, sticky="nsew", padx=10)
        ctk.CTkLabel(self.result_col, text="Analysis Result", font=("Arial", 20, "bold"), text_color="#295222").pack(pady=10)
        
        self.result_text = ctk.CTkTextbox(self.result_col, fg_color="white", text_color="#333", width=400, height=500, wrap="word", font=("Arial", 12))
        self.result_text.pack(pady=10, padx=10, fill="both", expand=True)
        self.result_text.insert("1.0", "Upload or capture an image, then click 'Analyze'.")

        # Popup Guide
        self.popup = ctk.CTkFrame(scanner_col, fg_color="white", corner_radius=10, border_width=2, border_color="#295222")
        ctk.CTkLabel(self.popup, text="Guide", font=("Arial", 16, "bold"), text_color="#295222").pack(pady=(10,5))
        ctk.CTkLabel(self.popup, text="1. Capture or Upload\n2. Click Analyze\n3. Wait for AI", text_color="black").pack(pady=(0,10), padx=10)
        self.popup.place_forget()

    def open_camera(self):
        cap = None
        for idx in range(0, 6):
            try:
                c = cv2.VideoCapture(idx, cv2.CAP_V4L2)
                if c.isOpened():
                    cap = c; break
                c.release()
            except: pass
            c = cv2.VideoCapture(idx)
            if c.isOpened():
                cap = c; break
            c.release()

        if cap is None or not cap.isOpened():
            messagebox.showerror("Error", "❌ No camera found.")
            return

        cv2.namedWindow("Press 'c' to capture")
        while True:
            ret, frame = cap.read()
            if not ret: break
            cv2.imshow("Press 'c' to capture", frame)
            if cv2.waitKey(1) == ord('c'):
                if not os.path.exists('captures'): os.makedirs('captures')
                img_name = f"captures/capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                cv2.imwrite(img_name, frame)
                self.current_image_path = img_name
                self.display_image(img_name)
                break
        cap.release()
        cv2.destroyAllWindows()

    def upload_image(self):
        file_path = filedialog.askopenfilename(filetypes=[("Image Files", "*.jpg *.jpeg *.png")])
        if file_path:
            self.current_image_path = file_path
            self.display_image(file_path)

    def display_image(self, file_path):
        img = Image.open(file_path).convert("RGB")
        img.thumbnail((350, 350), Image.Resampling.LANCZOS)
        ctk_img = ctk.CTkImage(light_image=img, size=img.size)
        self.camera_placeholder.configure(image=ctk_img, text="")
        self.camera_placeholder._img_ref = ctk_img

    def analyze_current_image(self):
        if not self.current_image_path:
            messagebox.showwarning("No Image", "Select an image first!")
            return
        
        self.analyze_btn.configure(state="disabled", text="⏳ Analyzing...")
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", "🔄 Analyzing...")
        self.update()
        
        result = analyze_plant_with_gemini(self.current_image_path)
        self.analyze_btn.configure(state="normal", text="🔍 Analyze")
        self.result_text.delete("1.0", "end")
        
        if result['success']:
            self.result_text.insert("end", result['response'])
            save_to_history(self.current_image_path, result)
        else:
            self.result_text.insert("end", f"Error: {result.get('error')}")

    def toggle_popup(self):
        if self.popup_visible: self.popup.place_forget()
        else: self.popup.place(relx=0.5, rely=0.45, anchor="center")
        self.popup_visible = not self.popup_visible

# -------------------- HISTORY FRAME --------------------
class HistoryFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color="white")
        # FIX: Remove padding so header touches top
        Header(self, parent).pack(fill="x", pady=0)
        
        header_frame = ctk.CTkFrame(self, fg_color="white")
        header_frame.pack(fill="x", padx=20, pady=10)
        ctk.CTkLabel(header_frame, text="📚 Scan History", font=("Arial", 24, "bold"), text_color="#295222").pack(side="left")
        
        # CHANGED: "Refresh" is now "Clear History"
        ctk.CTkButton(header_frame, text="🗑️ Clear History", fg_color="#dc3545", hover_color="#c82333", 
                      command=self.clear_history).pack(side="right")
        
        self.history_list = ctk.CTkScrollableFrame(self, fg_color="#f8f9fa")
        self.history_list.pack(fill="both", expand=True, padx=20, pady=10)
        self.refresh_history()
    
    def refresh_history(self):
        for widget in self.history_list.winfo_children(): widget.destroy()
        history = load_history()
        
        if not history:
             ctk.CTkLabel(self.history_list, text="No scan history yet.", text_color="gray", font=("Arial", 14)).pack(pady=40)
             return

        for i, entry in enumerate(history): self.create_history_card(entry, i)
        
    def clear_history(self):
        """Deletes history file and refreshes UI"""
        if messagebox.askyesno("Confirm Delete", "Delete all scan history?"):
            try:
                if os.path.exists(HISTORY_FILE): os.remove(HISTORY_FILE)
                self.refresh_history()
                messagebox.showinfo("Success", "History deleted.")
            except Exception as e:
                messagebox.showerror("Error", str(e))
    
    def create_history_card(self, entry, index):
        card = ctk.CTkFrame(self.history_list, fg_color="white", corner_radius=10)
        card.pack(fill="x", pady=5, padx=5)
        
        try:
            img = Image.open(entry['image_path'])
            img.thumbnail((80, 80))
            tk_img = ImageTk.PhotoImage(img)
            lbl = ctk.CTkLabel(card, image=tk_img, text="")
            lbl.image = tk_img
            lbl.pack(side="left", padx=10, pady=10)
        except:
            ctk.CTkLabel(card, text="[No Image]", width=80).pack(side="left", padx=10)

        plant_name = entry.get('response', 'Unknown').split('\n')[0][:50]
        info_frame = ctk.CTkFrame(card, fg_color="white")
        info_frame.pack(side="left", fill="both", expand=True, padx=10)
        ctk.CTkLabel(info_frame, text=plant_name, font=("Arial", 14, "bold"), text_color="#295222", anchor="w").pack(fill="x")
        ctk.CTkLabel(info_frame, text=entry['timestamp'], text_color="gray", anchor="w", font=("Arial", 10)).pack(fill="x")
        
        ctk.CTkButton(card, text="View", fg_color="#295222", width=80, command=lambda e=entry: self.view_detail(e)).pack(side="right", padx=10)

    def view_detail(self, entry):
        detail_window = ctk.CTkToplevel(self)
        detail_window.title("Scan Detail")
        detail_window.geometry("700x600")
        
        # --- FIXED IMAGE FRAME ---
        img_frame = ctk.CTkFrame(detail_window, height=300) 
        img_frame.pack_propagate(False) # Forces size
        img_frame.pack(pady=(10, 0), padx=10, fill="x")
        
        try:
            if os.path.exists(entry['image_path']):
                img = Image.open(entry['image_path'])
                img.thumbnail((500, 280)) 
                tk_img = ImageTk.PhotoImage(img)
                img_label = ctk.CTkLabel(img_frame, image=tk_img, text="")
                img_label.image = tk_img
                img_label.place(relx=0.5, rely=0.5, anchor="center")
            else:
                ctk.CTkLabel(img_frame, text="[Image Not Available]").place(relx=0.5, rely=0.5, anchor="center")
        except:
            ctk.CTkLabel(img_frame, text="[Error]").place(relx=0.5, rely=0.5, anchor="center")
        
        # --- FIXED TEXT AREA (WHITE BACKGROUND) ---
        text_frame = ctk.CTkFrame(detail_window, fg_color="white") 
        text_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # FIX: Added fg_color="white" and text_color="black" so it blends seamlessly
        response_text = ctk.CTkTextbox(text_frame, wrap="word", font=("Arial", 12), fg_color="white", text_color="black")
        response_text.pack(fill="both", expand=True)
        response_text.insert("1.0", entry.get('response', 'No Data'))
        response_text.configure(state="disabled")

if __name__ == "__main__":
    app = HerbalScannerApp()
    app.mainloop()
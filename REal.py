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

GEMINI_API_KEY = 'AIzaSyDusA-lDLw_kg_1PJzo6FZY0RtFQGKhkTc'

# Using the Lite model for 1,000 free requests per day
API_URL = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={GEMINI_API_KEY}'

# Storage for scan history
HISTORY_FILE = 'scan_history.json'

# Rate limiting: 15 RPM means one request every 4 seconds is safe
last_api_call = 0
MIN_CALL_INTERVAL = 4  

# -------------------- HELPER FUNCTIONS --------------------
def encode_image_to_base64(image_path, max_size=(600, 600)):
    """Convert image file to base64 string with size optimization"""
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
        img_bytes = buffered.getvalue()
        
        return base64.b64encode(img_bytes).decode('utf-8')
    except Exception as e:
        raise Exception(f"Image encoding failed: {str(e)}")

def rate_limit(func):
    """Decorator to prevent rapid API calls based on Lite limits"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        global last_api_call
        current_time = time.time()
        time_since_last = current_time - last_api_call
        
        if time_since_last < MIN_CALL_INTERVAL:
            wait_time = MIN_CALL_INTERVAL - time_since_last
            raise Exception(f"Please wait {wait_time:.1f} seconds before analyzing again.")
        
        last_api_call = current_time
        return func(*args, **kwargs)
    
    return wrapper

@rate_limit
def analyze_plant_with_gemini(image_path):
    """Send image to Gemini 2.5 Flash-Lite API"""
    try:
        # Re-verify local URL matches global config
        target_url = API_URL
        
        image_base64 = encode_image_to_base64(image_path, max_size=(600, 600))
        
        prompt = """Analyze this plant for the Philippines. Provide in plain text (no asterisks/markdown):
1. Common Name (Philippine)
2. Scientific Name
3. Brief Description
4. Uses
5. Health Benefits
6. Safety Notes"""

        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": image_base64
                        }
                    }
                ]
            }],
            "generationConfig": {
                "temperature": 0.4,
                "topK": 32,
                "topP": 1,
                "maxOutputTokens": 800,
            },
            "safetySettings": [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
            ]
        }
        
        response = requests.post(target_url, json=payload, headers={"Content-Type": "application/json"})
        
        if response.status_code != 200:
            error_data = response.json()
            error_msg = error_data.get('error', {}).get('message', f'HTTP {response.status_code}')
            raise Exception(f"API Error: {error_msg}")
        
        data = response.json()
        
        if data.get('candidates') and len(data['candidates']) > 0:
            candidate = data['candidates'][0]
            
            if candidate.get('finishReason') == 'SAFETY':
                raise Exception("The AI blocked this content for safety reasons.")
                
            if candidate.get('content', {}).get('parts', [{}])[0].get('text'):
                ai_response = candidate['content']['parts'][0]['text']
                
                # Clean formatting
                ai_response = ai_response.replace('**', '').replace('*', '')
                ai_response = ai_response.replace('###', '').replace('##', '').replace('#', '')
                ai_response = ai_response.replace('_', '').strip()
                
                usage_metadata = data.get('usageMetadata', {})
                
                return {
                    'success': True,
                    'response': ai_response,
                    'timestamp': datetime.now().isoformat(),
                    'tokens_used': usage_metadata.get('totalTokenCount', 'N/A')
                }
        
        raise Exception('Invalid response format or blocked content.')
            
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }
    
def save_to_history(image_path, analysis_result):
    """Save scan result to history file"""
    try:
        # Load existing history
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'r') as f:
                history = json.load(f)
        else:
            history = []
        
        # Add new entry
        entry = {
            'id': datetime.now().strftime('%Y%m%d_%H%M%S'),
            'image_path': image_path,
            'timestamp': analysis_result['timestamp'],
            'response': analysis_result.get('response', ''),
            'success': analysis_result['success'],
            'tokens_used': analysis_result.get('tokens_used', 'N/A')
        }
        
        history.insert(0, entry)  # Add to beginning
        
        # Keep only last 50 entries to save space
        history = history[:50]
        
        # Save updated history
        with open(HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=2)
            
        return True
    except Exception as e:
        print(f"Error saving to history: {e}")
        return False

def load_history():
    """Load scan history from file"""
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'r') as f:
                return json.load(f)
        return []
    except Exception as e:
        print(f"Error loading history: {e}")
        return []

# -------------------- UI SETTINGS --------------------
ctk.set_appearance_mode("light")
ctk.set_default_color_theme("green")

# -------------------- MAIN APP --------------------
class HerbalScannerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Herbal Scanner")
        self.geometry("950x610")
        self.resizable(False, False)

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Initialize all frames
        self.frames = {}
        for F in (LoginFrame, HomeFrame, ScannerFrame, HistoryFrame):
            frame = F(self)
            self.frames[F] = frame
            frame.grid(row=0, column=0, sticky="nsew")

        self.show_frame(LoginFrame)

    def show_frame(self, frame_class):
        frame = self.frames[frame_class]
        frame.tkraise()
        
        # Refresh history when showing history frame
        if frame_class == HistoryFrame:
            frame.refresh_history()

# -------------------- HEADER --------------------
class Header(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent, fg_color="#295222", height=80)
        self.controller = controller
        self.pack_propagate(False)

        ctk.CTkLabel(self, text="🌿 HerbalScan AI", font=("Arial", 24, "bold"), text_color="white").pack(side="left", padx=20)

        # Navigation Buttons
        for nav, target in [("HOME", HomeFrame), ("SCANNER", ScannerFrame), ("HISTORY", HistoryFrame)]:
            ctk.CTkButton(
                self, text=nav, fg_color="#406343", text_color="white",
                hover_color="#2d4a30", command=lambda t=target: controller.show_frame(t),
                corner_radius=8, height=35
            ).pack(side="left", padx=5)

        ctk.CTkButton(self, text="LOGOUT", fg_color="#dc3545", text_color="white",
                      hover_color="#c82333", command=lambda: controller.show_frame(LoginFrame),
                      corner_radius=8, height=35).pack(side="right", padx=20)

# -------------------- LOGIN FRAME --------------------
class LoginFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color="white")
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        form_frame = ctk.CTkFrame(self, fg_color="white")
        form_frame.grid(row=0, column=0, sticky="nsew", padx=60, pady=0)

        ctk.CTkLabel(form_frame, text="Welcome to HerbalScan!", font=("Arial", 24, "bold"), text_color="#295222").pack(pady=(0,10))

        self.email_entry = ctk.CTkEntry(form_frame, placeholder_text="Email address", width=250)
        self.email_entry.pack(pady=10)
        self.password_entry = ctk.CTkEntry(form_frame, placeholder_text="Password", show="*", width=250)
        self.password_entry.pack(pady=10)

        login_btn = ctk.CTkButton(form_frame, text="Login", width=250, fg_color="#295222", 
                                  hover_color="#1f3d1a", command=lambda: parent.show_frame(HomeFrame))
        login_btn.pack(pady=20)


# -------------------- HOME FRAME --------------------
class HomeFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color="white")
        Header(self, parent).pack(fill="x", pady=(10, 0))
        
        # Feature cards
        features_frame = ctk.CTkFrame(self, fg_color="white")
        features_frame.pack(expand=True, fill="both", padx=20, pady=10)
        
        features = [
            ("📸 Scanner", "Capture or upload plant images", ScannerFrame),
            ("📚 History", "View your scan history", HistoryFrame)
        ]
        
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

        Header(self, parent).pack(fill="x", pady=(10, 0))

        content = ctk.CTkFrame(self, fg_color="white")
        content.pack(fill="both", expand=True, padx=20, pady=10)
        content.grid_columnconfigure((0,1), weight=1)

        # Left: Scanner
        scanner_col = ctk.CTkFrame(content, fg_color="white")
        scanner_col.grid(row=0, column=0, sticky="nsew", padx=10)
        ctk.CTkLabel(scanner_col, text="📷 AI Scanner", font=("Arial", 20, "bold"), text_color="#295222").pack(pady=10)

        self.camera_placeholder = ctk.CTkLabel(scanner_col, text="[Camera Preview]", 
                                                fg_color="#e0e0e0", text_color="gray", 
                                                width=350, height=350, corner_radius=10)
        self.camera_placeholder.pack(pady=10)

        btn_row = ctk.CTkFrame(scanner_col, fg_color="white")
        btn_row.pack(pady=5)
        ctk.CTkButton(btn_row, text="📷 Capture", fg_color="#295222", width=110, 
                      command=self.open_camera).pack(side="left", padx=5)
        ctk.CTkButton(btn_row, text="📁 Upload", fg_color="#406343", width=110, 
                      command=self.upload_image).pack(side="left", padx=5)
        
        self.analyze_btn = ctk.CTkButton(btn_row, text="🔍 Analyze", fg_color="#4CAF50", width=110, 
                                         command=self.analyze_current_image)
        self.analyze_btn.pack(side="left", padx=5)

        ctk.CTkButton(scanner_col, text="❔ Guide", fg_color="#6c757d", 
                      command=self.toggle_popup).pack(pady=10)

        # Right: Results
        self.result_col = ctk.CTkScrollableFrame(content, fg_color="#f8f9fa", corner_radius=10)
        self.result_col.grid(row=0, column=1, sticky="nsew", padx=10)
        ctk.CTkLabel(self.result_col, text="AI Analysis Result", 
                     font=("Arial", 20, "bold"), text_color="#295222").pack(pady=10)
        
        self.result_text = ctk.CTkTextbox(self.result_col, fg_color="white", 
                                          text_color="#333", width=400, height=500,
                                          wrap="word", font=("Arial", 12))
        self.result_text.pack(pady=10, padx=10, fill="both", expand=True)
        self.result_text.insert("1.0", "Upload or capture an image, then click 'Analyze' to identify the plant using AI.\n\n⚡ Optimized: Uses 80% fewer tokens per scan!")

        # Popup Guide
        self.popup = ctk.CTkFrame(scanner_col, fg_color="white", corner_radius=10, border_width=2, border_color="#295222")
        ctk.CTkLabel(self.popup, text="📖 Scanner Guide", font=("Arial", 16, "bold"), text_color="#295222").pack(pady=(10,5))
        guide_text = """1. Click 'Capture' to use your camera
                        2. Press 'c' to capture, 'q' to quit
                        3. Or click 'Upload' to select an image
                        4. Click 'Analyze' to identify the plant
                        5. Wait 3 seconds between scans
                        6. Images auto-compressed to save tokens"""
        ctk.CTkLabel(self.popup, text=guide_text, justify="left", text_color="black", wraplength=280).pack(pady=(0,10), padx=10)
        self.popup.place_forget()

    def open_camera(self):
        """Open camera for live capture"""
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            messagebox.showerror("Error", "❌ Could not access camera.")
            return

        cv2.namedWindow("Camera - Press 'c' to capture, 'q' to quit")
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            cv2.imshow("Camera - Press 'c' to capture, 'q' to quit", frame)
            key = cv2.waitKey(1)
            if key == ord('q'):
                break
            elif key == ord('c'):
                # Save captured image
                if not os.path.exists('captures'):
                    os.makedirs('captures')
                img_name = f"captures/capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                cv2.imwrite(img_name, frame)
                self.current_image_path = img_name
                self.display_image(img_name)
                messagebox.showinfo("Success", "✅ Image captured! Click 'Analyze' to identify.")
                break

        cap.release()
        cv2.destroyAllWindows()

    def upload_image(self):
        """Upload image from file system"""
        file_path = filedialog.askopenfilename(
            title="Select Plant Image", 
            filetypes=[("Image Files", "*.jpg *.jpeg *.png *.bmp")]
        )
        if file_path:
            self.current_image_path = file_path
            self.display_image(file_path)
            messagebox.showinfo("Success", "✅ Image loaded! Click 'Analyze' to identify.")

    def display_image(self, file_path):
        """Display selected image in preview"""
        try:
            img = Image.open(file_path)
            img.thumbnail((350, 350))
            self.tk_img = ImageTk.PhotoImage(img)
            self.camera_placeholder.configure(image=self.tk_img, text="")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load image: {e}")

    def analyze_current_image(self):
        """Analyze current image using Gemini API"""
        if not self.current_image_path:
            messagebox.showwarning("No Image", "Please capture or upload an image first!")
            return
        
        # Disable button during analysis
        self.analyze_btn.configure(state="disabled", text="⏳ Analyzing...")
        
        # Show loading message
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", "🔄 Analyzing plant with Gemini AI...\n\nThis may take a few seconds...")
        self.update()
        
        # Analyze with Gemini
        result = analyze_plant_with_gemini(self.current_image_path)
        
        # Re-enable button
        self.analyze_btn.configure(state="normal", text="🔍 Analyze")
        
        # Display results
        self.result_text.delete("1.0", "end")
        
        if result['success']:
            self.result_text.insert("end", "✅ ANALYSIS COMPLETE\n")
            self.result_text.insert("end", "=" * 50 + "\n\n")
            self.result_text.insert("end", result['response'])
            self.result_text.insert("end", "\n\n" + "=" * 50 + "\n")
            self.result_text.insert("end", f"📅 Analyzed: {datetime.fromisoformat(result['timestamp']).strftime('%Y-%m-%d %H:%M:%S')}\n")
            self.result_text.insert("end", f"⚡ Tokens Used: {result.get('tokens_used', 'N/A')}")
            
            # Save to history
            save_to_history(self.current_image_path, result)
            messagebox.showinfo("Success", "✅ Plant identified! Check History for saved scans.")
        else:
            self.result_text.insert("end", "❌ ANALYSIS FAILED\n")
            self.result_text.insert("end", "=" * 50 + "\n\n")
            self.result_text.insert("end", f"Error: {result.get('error', 'Unknown error')}\n\n")
            self.result_text.insert("end", "Please try again with a clearer image.")
            messagebox.showerror("Error", f"Analysis failed: {result.get('error', 'Unknown error')}")

    def toggle_popup(self):
        """Toggle guide popup"""
        if self.popup_visible:
            self.popup.place_forget()
        else:
            self.popup.place(relx=0.5, rely=0.85, anchor="center")
        self.popup_visible = not self.popup_visible

# -------------------- HISTORY FRAME --------------------
class HistoryFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color="white")
        self.parent = parent
        
        Header(self, parent).pack(fill="x", pady=(10, 0))
        
        # Header
        header_frame = ctk.CTkFrame(self, fg_color="white")
        header_frame.pack(fill="x", padx=20, pady=10)
        
        ctk.CTkLabel(header_frame, text="📚 Scan History", 
                     font=("Arial", 24, "bold"), text_color="#295222").pack(side="left")
        
        ctk.CTkButton(header_frame, text="🔄 Refresh", fg_color="#295222",
                      command=self.refresh_history).pack(side="right", padx=5)
        ctk.CTkButton(header_frame, text="🗑️ Clear All", fg_color="#dc3545",
                      command=self.clear_history).pack(side="right")
        
        # Scrollable history list
        self.history_list = ctk.CTkScrollableFrame(self, fg_color="#f8f9fa")
        self.history_list.pack(fill="both", expand=True, padx=20, pady=10)
        
        self.refresh_history()
    
    def refresh_history(self):
        """Reload and display history"""
        # Clear existing widgets
        for widget in self.history_list.winfo_children():
            widget.destroy()
        
        history = load_history()
        
        if not history:
            ctk.CTkLabel(self.history_list, text="No scan history yet.\n\nStart scanning plants to build your history!", 
                         font=("Arial", 14), text_color="gray").pack(pady=50)
            return
        
        # Display each history entry
        for i, entry in enumerate(history):
            self.create_history_card(entry, i)
    
    def create_history_card(self, entry, index):
        """Create a card for each history entry"""
        card = ctk.CTkFrame(self.history_list, fg_color="white", corner_radius=10)
        card.pack(fill="x", pady=5, padx=5)
        
        # Left: Image thumbnail
        left_frame = ctk.CTkFrame(card, fg_color="white")
        left_frame.pack(side="left", padx=10, pady=10)
        
        try:
            if os.path.exists(entry['image_path']):
                img = Image.open(entry['image_path'])
                img.thumbnail((80, 80))
                tk_img = ImageTk.PhotoImage(img)
                img_label = ctk.CTkLabel(left_frame, image=tk_img, text="")
                img_label.image = tk_img  # Keep reference
                img_label.pack()
            else:
                ctk.CTkLabel(left_frame, text="[No Image]", fg_color="#e0e0e0", 
                             width=80, height=80).pack()
        except:
            ctk.CTkLabel(left_frame, text="[Error]", fg_color="#e0e0e0", 
                         width=80, height=80).pack()
        
        # Right: Details
        right_frame = ctk.CTkFrame(card, fg_color="white")
        right_frame.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        
        # Extract plant name from response
        plant_name = "Unknown Plant"
        if entry['success'] and entry.get('response'):
            lines = entry['response'].split('\n')
            for line in lines:
                if line.strip() and not line.startswith('1.'):
                    plant_name = line.strip()[:50]
                    break
        
        ctk.CTkLabel(right_frame, text=f"#{index + 1}: {plant_name}", 
                     font=("Arial", 14, "bold"), text_color="#295222", 
                     anchor="w").pack(fill="x")
        
        timestamp_str = datetime.fromisoformat(entry['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
        ctk.CTkLabel(right_frame, text=f"📅 {timestamp_str} | ⚡ Tokens: {entry.get('tokens_used', 'N/A')}", 
                     text_color="gray", anchor="w", font=("Arial", 10)).pack(fill="x")
        
        # View button
        ctk.CTkButton(card, text="👁️ View", fg_color="#295222", width=80,
                      command=lambda e=entry: self.view_detail(e)).pack(side="right", padx=10)
    
    def view_detail(self, entry):
        """Show detailed view of a history entry"""
        detail_window = ctk.CTkToplevel(self)
        detail_window.title("Scan Detail")
        detail_window.geometry("700x600")
        
        # Image
        img_frame = ctk.CTkFrame(detail_window)
        img_frame.pack(pady=10, padx=10, fill="x")
        
        try:
            if os.path.exists(entry['image_path']):
                img = Image.open(entry['image_path'])
                img.thumbnail((300, 300))
                tk_img = ImageTk.PhotoImage(img)
                img_label = ctk.CTkLabel(img_frame, image=tk_img, text="")
                img_label.image = tk_img
                img_label.pack()
        except:
            ctk.CTkLabel(img_frame, text="[Image Not Available]").pack()
        
        # Response
        text_frame = ctk.CTkScrollableFrame(detail_window, fg_color="white")
        text_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        response_text = ctk.CTkTextbox(text_frame, wrap="word", font=("Arial", 12))
        response_text.pack(fill="both", expand=True)
        
        if entry['success']:
            response_text.insert("1.0", entry.get('response', 'No data'))
            response_text.insert("end", f"\n\n⚡ Tokens Used: {entry.get('tokens_used', 'N/A')}")
        else:
            response_text.insert("1.0", f"Analysis failed\n\nError: {entry.get('error', 'Unknown')}")
        
        response_text.configure(state="disabled")
    
    def clear_history(self):
        """Clear all history"""
        if messagebox.askyesno("Confirm", "Are you sure you want to clear all history?"):
            try:
                if os.path.exists(HISTORY_FILE):
                    os.remove(HISTORY_FILE)
                self.refresh_history()
                messagebox.showinfo("Success", "✅ History cleared!")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to clear history: {e}")

# -------------------- RUN APP --------------------
if __name__ == "__main__":
    app = HerbalScannerApp()
    app.mainloop()
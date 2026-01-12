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
import re  # Added for text parsing

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
        # UPDATED PROMPT: Requesting '###' headers instead of numbered lists
        prompt = """Analyze this plant for the Philippines. 
        Format the output using '### ' as a header prefix for each section. 
        Do not use numbered lists (1. 2. 3.) for the section titles.
        
        Required Sections:
        ### Common Name (Philippine)
        ### Scientific Name
        ### Brief Description
        ### Uses
        ### Health Benefits
        ### Safety Notes"""

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
            clean_text = text.replace('**', '').strip()
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
        for F in (LoginFrame, RegisterFrame, HomeFrame, ScannerFrame, HistoryFrame, PlantDetailFrame):
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


PLANTS_DATABASE = [
    {
        'image': 'akapulko.jpg',
        'name': 'AKAPULKO',
        'scientific': 'Cassia alata',
        'short_description': 'For fungal infections (tinea, ringworm), insect bites, skin itching.',
        'full_description': 'Akapulko (Cassia alata), also known as ringworm bush or candle bush, is a medicinal shrub known for its antifungal properties. The leaves contain chrysophanic acid which effectively treats various skin conditions.',
        'benefits': [
            'Treats fungal infections like tinea and ringworm',
            'Relieves insect bites and skin itching',
            'Natural antifungal properties',
            'Anti-inflammatory effects',
            'Traditional skin remedy'
        ],
        'uses': [
            'Topical application for skin infections',
            'Poultice for insect bites',
            'Traditional medicine for skin conditions',
            'Leaf extract for fungal treatment'
        ]
    },
    {
        'image': 'aloevera.png',
        'name': 'ALOE VERA',
        'scientific': 'Aloe barbadensis',
        'short_description': 'For burns, hair growth, moisturizing skin, wound healing.',
        'full_description': 'Aloe Vera (Aloe barbadensis) is a succulent plant species known for its medicinal properties. The gel inside its leaves contains vitamins, minerals, and antioxidants that promote healing and skin health.',
        'benefits': [
            'Soothes burns and sunburns',
            'Promotes hair growth and scalp health',
            'Deeply moisturizes skin',
            'Accelerates wound healing',
            'Anti-inflammatory properties'
        ],
        'uses': [
            'Topical gel for burns and wounds',
            'Hair care products',
            'Skin moisturizers',
            'Cosmetic formulations',
            'Traditional medicinal applications'
        ]
    },
    {
        'image': 'alugbati.jpg',
        'name': 'ALUGBATI',
        'scientific': 'Basella alba',
        'short_description': 'Mild laxative, anti-inflammatory; good for constipation.',
        'full_description': 'Alugbati (Basella alba), also known as Malabar spinach or vine spinach, is a fast-growing perennial vine with medicinal properties. Its leaves are rich in vitamins and have both nutritional and therapeutic value.',
        'benefits': [
            'Acts as mild laxative',
            'Anti-inflammatory properties',
            'Relieves constipation',
            'Rich in vitamins A and C',
            'Contains antioxidants'
        ],
        'uses': [
            'Leaf decoction for constipation',
            'Poultice for inflammation',
            'Culinary vegetable',
            'Traditional digestive aid'
        ]
    },
    {
        'image': 'ampalaya.jpg',
        'name': 'AMPALAYA',
        'scientific': 'Momordica charantia',
        'short_description': 'Lowers blood sugar, for diabetes, improves digestion.',
        'full_description': 'Ampalaya (Momordica charantia), also known as bitter melon or bitter gourd, is a tropical vine cultivated for its edible fruit. It\'s particularly valued for its anti-diabetic properties and numerous health benefits.',
        'benefits': [
            'Lowers blood sugar levels',
            'Helps manage diabetes',
            'Improves digestion',
            'Rich in antioxidants',
            'Boosts immune system'
        ],
        'uses': [
            'Diabetes management',
            'Culinary vegetable dishes',
            'Juice for medicinal purposes',
            'Traditional herbal remedy',
            'Digestive aid'
        ]
    },
    {
        'image': 'anislag.jpg',
        'name': 'ANISLAG',
        'scientific': 'Securinega flexuosa',
        'short_description': 'Decoction used for cough and fever.',
        'full_description': 'Anislag (Securinega flexuosa) is a medicinal plant traditionally used in Philippine folk medicine. Various parts of the plant are used to prepare remedies for common ailments.',
        'benefits': [
            'Relieves cough symptoms',
            'Reduces fever',
            'Respiratory health support',
            'Traditional medicinal uses'
        ],
        'uses': [
            'Leaf decoction for cough',
            'Fever remedy',
            'Traditional herbal preparation',
            'Respiratory ailment treatment'
        ]
    },
    {
        'image': 'atis.jpg',
        'name': 'ATIS',
        'scientific': 'Annona squamosa',
        'short_description': 'Leaves for lice, head lice, and skin parasites.',
        'full_description': 'Anona or Atis (Annona squamosa), also known as sugar apple or sweetsop, is a tropical fruit tree whose leaves have traditional medicinal uses, particularly for treating parasites.',
        'benefits': [
            'Treats head lice and skin parasites',
            'Antiparasitic properties',
            'Fruit provides nutritional benefits',
            'Traditional medicinal applications'
        ],
        'uses': [
            'Leaf preparation for lice treatment',
            'Fruit as food source',
            'Traditional parasite remedy',
            'Skin treatment applications'
        ]
    },
    {
        'image': 'anahaw.jpg',
        'name': 'ANAHAW',
        'scientific': 'Livistona rotundifolia',
        'short_description': 'Roots used for stomach pains (folk practice).',
        'full_description': 'Anahaw (Livistona rotundifolia), also known as the Philippine round-leaf fan palm, is the national leaf of the Philippines. Its roots have been used in traditional folk medicine.',
        'benefits': [
            'Relieves stomach pains',
            'Traditional digestive aid',
            'Ornamental and cultural significance'
        ],
        'uses': [
            'Root decoction for stomach pains',
            'Ornamental plant',
            'Traditional folk medicine',
            'Cultural ceremonies'
        ]
    },
    {
        'image': 'balimbing.jpg',
        'name': 'BALIMBING',
        'scientific': 'Averrhoa carambola',
        'short_description': 'For fever, cough, and headaches.',
        'full_description': 'Balimbing (Averrhoa carambola), also known as star fruit, is a tropical fruit tree whose various parts have medicinal properties in traditional healing practices.',
        'benefits': [
            'Reduces fever',
            'Relieves cough',
            'Alleviates headaches',
            'Rich in vitamin C',
            'Contains antioxidants'
        ],
        'uses': [
            'Fruit consumption for health',
            'Traditional fever remedy',
            'Cough treatment',
            'Headache relief preparation'
        ]
    },
    {
        'image': 'banaba.jpg',
        'name': 'BANABA',
        'scientific': 'Lagerstroemia speciosa',
        'short_description': 'Anti-diabetic, diuretic, helps with weight management.',
        'full_description': 'Banaba (Lagerstroemia speciosa) is a flowering tree native to Southeast Asia. Its leaves contain corosolic acid, which has shown potential for treating diabetes and other health conditions.',
        'benefits': [
            'Anti-diabetic properties',
            'Diuretic effects',
            'Aids in weight management',
            'Lowers blood sugar',
            'Antioxidant properties'
        ],
        'uses': [
            'Diabetes management',
            'Weight loss supplements',
            'Diuretic preparations',
            'Traditional herbal tea',
            'Blood sugar regulation'
        ]
    }
]

# -------------------- HOME FRAME --------------------
class HomeFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color="white")
        Header(self, parent).pack(fill="x", pady=0)
        
        # Search and Filter Bar
        search_frame = ctk.CTkFrame(self, fg_color="white")
        search_frame.pack(fill="x", padx=20, pady=(15, 10))
        
        # Search Box
        self.search_entry = ctk.CTkEntry(
            search_frame,
            placeholder_text="🔍 Search plants...",
            width=500,
            height=45,
            font=("Arial", 14),
            corner_radius=25,
            border_width=0,
            fg_color="#e8e8e8"
        )
        self.search_entry.pack(side="left", padx=(0, 15))
        self.search_entry.bind("<KeyRelease>", self.filter_plants)
        
        # Filter Button
        filter_btn = ctk.CTkButton(
            search_frame,
            text="Filter ▼",
            width=120,
            height=45,
            font=("Arial", 14, "bold"),
            fg_color="#e8e8e8",
            text_color="black",
            hover_color="#d0d0d0",
            corner_radius=25
        )
        filter_btn.pack(side="left")
        
        # Scrollable Plant Gallery
        self.gallery_frame = ctk.CTkScrollableFrame(self, fg_color="white")
        self.gallery_frame.pack(fill="both", expand=True, padx=20, pady=10)
        
        # Configure grid for 3 columns
        for i in range(3):
            self.gallery_frame.grid_columnconfigure(i, weight=1)
        
        # FIXED: Assign the global database to self.plants
        self.plants = PLANTS_DATABASE
        
        # Store all plant cards for filtering
        self.plant_cards = []
        
        # Display all plants initially
        self.display_plants()
    
    def display_plants(self, filtered_plants=None):
        """Display plant cards in grid layout"""
        # Clear existing cards
        for widget in self.gallery_frame.winfo_children():
            widget.destroy()
        self.plant_cards.clear()
        
        # Use filtered list or all plants
        plants_to_show = filtered_plants if filtered_plants is not None else self.plants
        
        if not plants_to_show:
            # Show "No results" message
            no_result = ctk.CTkLabel(
                self.gallery_frame,
                text="No plants found",
                font=("Arial", 18),
                text_color="gray"
            )
            no_result.grid(row=0, column=0, columnspan=3, pady=50)
            return
        
        # FIXED: Create plant cards using dictionary structure
        for idx, plant_data in enumerate(plants_to_show):
            row = idx // 3
            col = idx % 3
            
            # Card Container
            card = ctk.CTkFrame(self.gallery_frame, fg_color="#f5f5f5", corner_radius=15)
            card.grid(row=row, column=col, padx=15, pady=15, sticky="nsew")
            
            # Plant Image
            try:
                img = Image.open(f"assets/{plant_data['image']}")
                img.thumbnail((196, 196))
                ctk_img = ctk.CTkImage(light_image=img, size=(196, 196))
                img_label = ctk.CTkLabel(card, image=ctk_img, text="")
                img_label.image = ctk_img
                img_label.pack(pady=(10, 8))
            except:
                # Fallback placeholder
                placeholder = ctk.CTkLabel(
                    card,
                    text="🌿",
                    font=("Arial", 70),
                    text_color="#295222",
                    width=196,
                    height=196
                )
                placeholder.pack(pady=(10, 8))
            
            # Plant Name
            name_label = ctk.CTkLabel(
                card,
                text=plant_data['name'],
                font=("Arial", 16, "bold"),
                text_color="#295222"
            )
            name_label.pack(pady=(3, 0))
            
            # Scientific Name
            sci_label = ctk.CTkLabel(
                card,
                text=plant_data.get('scientific', ''),
                font=("Arial", 10, "italic"),
                text_color="gray"
            )
            sci_label.pack(pady=(0, 8))
            
            # FIXED: View Button now passes plant_data to PlantDetailFrame
            view_btn = ctk.CTkButton(
                card,
                text="View",
                width=120,
                height=32,
                font=("Arial", 12, "bold"),
                fg_color="#295222",
                hover_color="#1f3d1a",
                corner_radius=8,
                command=lambda p=plant_data: self.view_plant_detail(p)
            )
            view_btn.pack(pady=(0, 12))
            
            # Store card info for filtering
            self.plant_cards.append({
                'card': card,
                'name': plant_data['name'].lower(),
                'scientific': plant_data.get('scientific', '').lower(),
                'data': plant_data
            })
    
    def filter_plants(self, event=None):
        """Filter plants based on search input"""
        search_term = self.search_entry.get().lower().strip()
        
        if not search_term:
            # Show all plants if search is empty
            self.display_plants()
            return
        
        # Filter plants that match search term
        filtered = [
            card['data'] for card in self.plant_cards
            if search_term in card['name'] or search_term in card['scientific']
        ]
        
        # If no cards loaded yet, filter from original list
        if not self.plant_cards:
            filtered = [
                plant for plant in self.plants
                if search_term in plant['name'].lower() or 
                   search_term in plant.get('scientific', '').lower()
            ]
        
        self.display_plants(filtered)
    
    def view_plant_detail(self, plant_data):
        """Navigate to plant detail view"""
        detail_frame = self.master.frames.get(PlantDetailFrame)
        if detail_frame:
            detail_frame.load_plant(plant_data)
            self.master.show_frame(PlantDetailFrame)

# -------------------- SCANNER FRAME (BEAUTIFIED) --------------------
class ScannerFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color="white")
        self.popup_visible = False
        self.current_image_path = None

        Header(self, parent).pack(fill="x", pady=0)

        content = ctk.CTkFrame(self, fg_color="white")
        content.pack(fill="both", expand=True, padx=20, pady=10)
        content.grid_columnconfigure((0,1), weight=1)
        content.grid_rowconfigure(0, weight=1) # Ensure rows expand

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
        ctk.CTkButton(btn_row, text=" Capture", fg_color="#295222", width=110, command=self.open_camera).pack(side="left", padx=5)
        ctk.CTkButton(btn_row, text=" Upload", fg_color="#406343", width=110, command=self.upload_image).pack(side="left", padx=5)
        self.analyze_btn = ctk.CTkButton(btn_row, text=" Analyze", fg_color="#4CAF50", width=110, command=self.analyze_current_image)
        self.analyze_btn.pack(side="left", padx=5)

        ctk.CTkButton(scanner_col, text="❔ Guide", fg_color="#6c757d", command=self.toggle_popup).pack(pady=10)

        # Right: Results (CHANGED FROM TEXTBOX TO SCROLLABLE FRAME)
        self.result_container = ctk.CTkScrollableFrame(content, fg_color="#f8f9fa", corner_radius=10)
        self.result_container.grid(row=0, column=1, sticky="nsew", padx=10)
        
        # Initial Placeholder text in Result container
        self.status_label = ctk.CTkLabel(self.result_container, text="Analysis Result", font=("Arial", 20, "bold"), text_color="#295222")
        self.status_label.pack(pady=(10, 5))
        
        self.instruction_label = ctk.CTkLabel(self.result_container, text="Upload or capture an image,\nthen click 'Analyze'.", text_color="gray")
        self.instruction_label.pack(pady=20)

        # Popup Guide
        self.popup = ctk.CTkFrame(scanner_col, fg_color="white", corner_radius=10, border_width=2, border_color="#295222")
        ctk.CTkLabel(self.popup, text="Guide", font=("Arial", 16, "bold"), text_color="#295222").pack(pady=(10,5))
        ctk.CTkLabel(self.popup, text="1. Capture or Upload\n2. Click Analyze\n3. Wait for AI", text_color="black").pack(pady=(0,10), padx=10)
        self.popup.place_forget()

    def open_camera(self):
        # (Same camera logic)
        cap = None
        for idx in range(0, 6):
            try:
                c = cv2.VideoCapture(idx, cv2.CAP_V4L2)
                if c.isOpened(): cap = c; break
                c.release()
            except: pass
            c = cv2.VideoCapture(idx)
            if c.isOpened(): cap = c; break
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
        
        # Clear previous results
        for widget in self.result_container.winfo_children():
            widget.destroy()
            
        # Show loading state
        ctk.CTkLabel(self.result_container, text="Analysis Result", font=("Arial", 20, "bold"), text_color="#295222").pack(pady=(10,5))
        loading_lbl = ctk.CTkLabel(self.result_container, text="⏳ Analyzing... Please wait...", font=("Arial", 16), text_color="#e65100")
        loading_lbl.pack(pady=50)
        self.analyze_btn.configure(state="disabled")
        self.update()
        
        result = analyze_plant_with_gemini(self.current_image_path)
        
        self.analyze_btn.configure(state="normal")
        
        # FIX: Clear everything (loading text + temporary title) before showing results
        for widget in self.result_container.winfo_children():
            widget.destroy()
        
        if result['success']:
            self.render_analysis_result(result['response'])
            save_to_history(self.current_image_path, result)
        else:
            # Re-add Title if error
            ctk.CTkLabel(self.result_container, text="Analysis Result", font=("Arial", 20, "bold"), text_color="#295222").pack(pady=(10,5))
            err_label = ctk.CTkLabel(self.result_container, text=f"Error: {result.get('error')}", text_color="red")
            err_label.pack(pady=20)

    def render_analysis_result(self, text):
        """
        Parses text with '### Header' format and creates beautiful cards.
        """
        # Split text by '###' to find sections
        sections = re.split(r'###\s*', text)
        
        # Add Main Title
        ctk.CTkLabel(self.result_container, text="Analysis Result", font=("Arial", 22, "bold"), text_color="#295222").pack(pady=(10, 15))

        for section in sections:
            section = section.strip()
            if not section: continue
            
            # Split header from body (first line is header)
            lines = section.split('\n', 1)
            header_text = lines[0].strip()
            body_text = lines[1].strip() if len(lines) > 1 else ""

            # Card Container for each section
            card = ctk.CTkFrame(self.result_container, fg_color="white", corner_radius=10)
            card.pack(fill="x", pady=5, padx=5)
            
            # Header Label (Green, Bold)
            header_lbl = ctk.CTkLabel(card, text=header_text.upper(), font=("Arial", 14, "bold"), text_color="#295222", anchor="w")
            header_lbl.pack(fill="x", padx=15, pady=(10, 5))
            
            # Separator Line
            ctk.CTkFrame(card, height=2, fg_color="#e0e0e0").pack(fill="x", padx=15, pady=(0, 8))
            
            # Body Text (Wrapped, Dark Gray)
            # Remove any residual markdown like asterisks or bullet points
            body_text = body_text.replace('*', '•') 
            
            body_lbl = ctk.CTkLabel(card, text=body_text, font=("Arial", 13), text_color="#444", 
                                  anchor="w", justify="left", wraplength=400) # Wrap fits the width
            body_lbl.pack(fill="x", padx=15, pady=(0, 15))

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

        # Attempt to grab the Common Name for the title
        raw_response = entry.get('response', 'Unknown')
        first_line = raw_response.split('\n')[0]
        # Clean up ### if present from new format
        plant_name = first_line.replace('###', '').replace('Common Name', '').strip()[:30]
        if not plant_name: plant_name = "Scan Result"

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
        text_frame = ctk.CTkScrollableFrame(detail_window, fg_color="white") 
        text_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Simple rendering for history
        ctk.CTkLabel(text_frame, text=entry.get('response', ''), wraplength=650, justify="left", anchor="w").pack(padx=10, pady=10)

# -------------------- PLANT DETAIL FRAME --------------------
class PlantDetailFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color="white")
        self.parent = parent
        self.current_plant = None
        
        # Header with back button
        header_frame = ctk.CTkFrame(self, fg_color="#295222", height=80)
        header_frame.pack(fill="x")
        header_frame.pack_propagate(False)
        
        # Back button
        back_btn = ctk.CTkButton(
            header_frame,
            text="← Back",
            fg_color="transparent",
            hover_color="#1f3d1a",
            font=("Arial", 16, "bold"),
            width=100,
            command=lambda: parent.show_frame(HomeFrame)
        )
        back_btn.pack(side="left", padx=20, pady=20)
        
        # Title
        self.title_label = ctk.CTkLabel(
            header_frame,
            text="Plant Details",
            font=("Arial", 26, "bold"),
            text_color="white"
        )
        self.title_label.pack(side="left", padx=20)
        
        # Scrollable content area
        self.content_scroll = ctk.CTkScrollableFrame(self, fg_color="white")
        self.content_scroll.pack(fill="both", expand=True, padx=0, pady=0)
        
    def load_plant(self, plant_data):
        """Load and display plant information"""
        self.current_plant = plant_data
        
        # Clear existing content
        for widget in self.content_scroll.winfo_children():
            widget.destroy()
        
        # Main container
        container = ctk.CTkFrame(self.content_scroll, fg_color="white")
        container.pack(fill="both", expand=True, padx=30, pady=20)
        
        # === TOP SECTION: Image + Quick Info ===
        top_section = ctk.CTkFrame(container, fg_color="#f8f9fa", corner_radius=15)
        top_section.pack(fill="x", pady=(0, 20))
        
        # Left: Plant Image
        image_frame = ctk.CTkFrame(top_section, fg_color="white", corner_radius=12)
        image_frame.pack(side="left", padx=25, pady=25)
        
        try:
            img = Image.open(f"assets/{plant_data['image']}")
            img.thumbnail((350, 350))
            ctk_img = ctk.CTkImage(light_image=img, size=(350, 350))
            img_label = ctk.CTkLabel(image_frame, image=ctk_img, text="")
            img_label.image = ctk_img
            img_label.pack(padx=10, pady=10)
        except:
            placeholder = ctk.CTkLabel(
                image_frame,
                text="🌿",
                font=("Arial", 120),
                text_color="#295222",
                width=350,
                height=350
            )
            placeholder.pack(padx=10, pady=10)
        
        # Right: Quick Info
        info_frame = ctk.CTkFrame(top_section, fg_color="transparent")
        info_frame.pack(side="left", fill="both", expand=True, padx=25, pady=25)
        
        # Plant Name (Large)
        name_label = ctk.CTkLabel(
            info_frame,
            text=plant_data['name'],
            font=("Arial", 36, "bold"),
            text_color="#295222",
            anchor="w"
        )
        name_label.pack(anchor="w", pady=(10, 5))
        
        # Scientific Name
        if 'scientific' in plant_data:
            sci_label = ctk.CTkLabel(
                info_frame,
                text=plant_data['scientific'],
                font=("Arial", 16, "italic"),
                text_color="gray",
                anchor="w"
            )
            sci_label.pack(anchor="w", pady=(0, 20))
        
        # Short Description Box
        desc_box = ctk.CTkFrame(info_frame, fg_color="white", corner_radius=10)
        desc_box.pack(fill="x", pady=(0, 15))
        
        desc_label = ctk.CTkLabel(
            desc_box,
            text=plant_data.get('short_description', ''),
            font=("Arial", 14),
            text_color="#333",
            wraplength=450,
            justify="left",
            anchor="w"
        )
        desc_label.pack(padx=20, pady=15, anchor="w")
        
        # Action Buttons
        btn_frame = ctk.CTkFrame(info_frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(10, 0))
        
        scan_btn = ctk.CTkButton(
            btn_frame,
            text="🔍 Scan Similar",
            fg_color="#295222",
            hover_color="#1f3d1a",
            font=("Arial", 14, "bold"),
            height=45,
            width=180,
            corner_radius=10
        )
        scan_btn.pack(side="left", padx=(0, 10))
        
        save_btn = ctk.CTkButton(
            btn_frame,
            text="💾 Save",
            fg_color="#4CAF50",
            hover_color="#45a049",
            font=("Arial", 14, "bold"),
            height=45,
            width=120,
            corner_radius=10
        )
        save_btn.pack(side="left")
        
        # === FULL DESCRIPTION ===
        if 'full_description' in plant_data:
            self._create_section(container, "About This Plant", plant_data['full_description'])
        
        # === HEALTH BENEFITS ===
        if 'benefits' in plant_data and plant_data['benefits']:
            benefits_frame = ctk.CTkFrame(container, fg_color="#e8f5e9", corner_radius=15)
            benefits_frame.pack(fill="x", pady=(0, 20))
            
            title = ctk.CTkLabel(
                benefits_frame,
                text="💊 Health Benefits",
                font=("Arial", 22, "bold"),
                text_color="#2e7d32",
                anchor="w"
            )
            title.pack(anchor="w", padx=25, pady=(20, 10))
            
            for benefit in plant_data['benefits']:
                benefit_item = ctk.CTkFrame(benefits_frame, fg_color="white", corner_radius=8)
                benefit_item.pack(fill="x", padx=25, pady=5)
                
                ctk.CTkLabel(
                    benefit_item,
                    text=f"✓ {benefit}",
                    font=("Arial", 13),
                    text_color="#333",
                    anchor="w",
                    justify="left"
                ).pack(anchor="w", padx=15, pady=10)
            
            # Bottom padding
            ctk.CTkLabel(benefits_frame, text="", height=15).pack()
        
        # === USES ===
        if 'uses' in plant_data and plant_data['uses']:
            uses_frame = ctk.CTkFrame(container, fg_color="#fff3e0", corner_radius=15)
            uses_frame.pack(fill="x", pady=(0, 20))
            
            title = ctk.CTkLabel(
                uses_frame,
                text="🌿 Common Uses",
                font=("Arial", 22, "bold"),
                text_color="#e65100",
                anchor="w"
            )
            title.pack(anchor="w", padx=25, pady=(20, 10))
            
            for use in plant_data['uses']:
                use_item = ctk.CTkFrame(uses_frame, fg_color="white", corner_radius=8)
                use_item.pack(fill="x", padx=25, pady=5)
                
                ctk.CTkLabel(
                    use_item,
                    text=f"• {use}",
                    font=("Arial", 13),
                    text_color="#333",
                    anchor="w",
                    justify="left"
                ).pack(anchor="w", padx=15, pady=10)
            
            # Bottom padding
            ctk.CTkLabel(uses_frame, text="", height=15).pack()
        
        # === SAFETY WARNING (if applicable) ===
        if plant_data.get('warning'):
            warning_frame = ctk.CTkFrame(container, fg_color="#ffebee", corner_radius=15)
            warning_frame.pack(fill="x", pady=(0, 30))
            
            ctk.CTkLabel(
                warning_frame,
                text="⚠️ Safety Information",
                font=("Arial", 18, "bold"),
                text_color="#c62828",
                anchor="w"
            ).pack(anchor="w", padx=25, pady=(15, 5))
            
            ctk.CTkLabel(
                warning_frame,
                text=plant_data['warning'],
                font=("Arial", 13),
                text_color="#333",
                wraplength=850,
                justify="left",
                anchor="w"
            ).pack(anchor="w", padx=25, pady=(0, 15))
    
    def _create_section(self, parent, title, content):
        """Helper to create a text section"""
        section = ctk.CTkFrame(parent, fg_color="#f8f9fa", corner_radius=15)
        section.pack(fill="x", pady=(0, 20))
        
        title_label = ctk.CTkLabel(
            section,
            text=title,
            font=("Arial", 22, "bold"),
            text_color="#295222",
            anchor="w"
        )
        title_label.pack(anchor="w", padx=25, pady=(20, 10))
        
        content_label = ctk.CTkLabel(
            section,
            text=content,
            font=("Arial", 13),
            text_color="#333",
            wraplength=850,
            justify="left",
            anchor="w"
        )
        content_label.pack(anchor="w", padx=25, pady=(0, 20))

        

if __name__ == "__main__":
    app = HerbalScannerApp()
    app.mainloop()
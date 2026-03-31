#!/usr/bin/env python3
"""
Nexeo IG Creator - Premium Instagram Account Generator
For Vercel Deployment
"""

import os
import random
import string
import time
import json
import sqlite3
import secrets
import hashlib
from datetime import datetime, timedelta
from functools import wraps

import requests
from flask import Flask, render_template_string, request, jsonify, session, redirect, url_for
from flask_cors import CORS

# ======================== CONFIGURATION ========================
DAILY_LIMIT_PER_EMAIL = 5
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "nexeo@2024"
RATE_LIMIT_WINDOW = 86400
SECRET_KEY = secrets.token_hex(32)

# For Vercel - use /tmp for database
if os.environ.get('VERCEL'):
    DB_PATH = '/tmp/nexeo_ig.db'
else:
    DB_PATH = 'nexeo_ig.db'

# ======================== FLASK APP ========================
app = Flask(__name__)
app.secret_key = SECRET_KEY
CORS(app)

# ======================== INDIAN NAMES DATABASE (Hardcoded) ========================
INDIAN_FIRST_NAMES = ["Aarav","Vihaan","Vivaan","Ananya","Diya","Advik","Kabir","Aaradhya","Reyansh","Sai","Arjun","Ishaan","Rudra","Sia","Myra","Ayaan","Shaurya","Anaya","Krisha","Kavya","Rohan","Shreya","Ishita","Yash","Priya","Riya","Rahul","Amit","Sumit","Pooja","Neha","Raj","Simran","Aditya","Krishna","Laksh","Tanvi","Ishika","Ved","Yuvraj","Anushka","Divya","Sanya","Ria","Jay","Virat","Ravindra","Sneha","Nikhil"]
INDIAN_LAST_NAMES = ["Sharma","Verma","Gupta","Kumar","Singh","Patel","Reddy","Rao","Yadav","Jha","Malhotra","Mehta","Choudhary","Thakur","Mishra","Trivedi","Dwivedi","Pandey","Tiwari","Joshi","Desai","Shah","Nair","Menon","Iyer","Khan","Ansari","Sheikh"]

def generate_full_name():
    return f"{random.choice(INDIAN_FIRST_NAMES)} {random.choice(INDIAN_LAST_NAMES)}"

def generate_username(first_name=None):
    if first_name:
        base = first_name.lower()
    else:
        base = random.choice(INDIAN_FIRST_NAMES).lower()
    
    num = random.randint(10, 9999)
    patterns = [
        f"{base}{num}", f"{base}_{num}", f"{base}.{num}",
        f"{base}{random.randint(100,999)}", f"{base}{random.choice(['_official', '_real', '_ig'])}"
    ]
    return random.choice(patterns)

# ======================== DATABASE FUNCTIONS ========================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS accounts
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  email TEXT NOT NULL,
                  username TEXT NOT NULL,
                  password TEXT NOT NULL,
                  full_name TEXT NOT NULL,
                  cookie TEXT NOT NULL,
                  session_id TEXT NOT NULL,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS rate_limits
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  email TEXT NOT NULL,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS api_keys
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  key_name TEXT NOT NULL,
                  api_key TEXT UNIQUE NOT NULL,
                  is_active INTEGER DEFAULT 1,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS admin_settings
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  setting_key TEXT UNIQUE NOT NULL,
                  setting_value TEXT,
                  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS ip_blacklist
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  ip_address TEXT UNIQUE NOT NULL,
                  reason TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS user_sessions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  session_token TEXT UNIQUE NOT NULL,
                  ip_address TEXT,
                  user_agent TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS user_agreements
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  session_token TEXT NOT NULL,
                  agreed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  ip_address TEXT)''')
    
    # Insert default settings
    c.execute("INSERT OR IGNORE INTO admin_settings (setting_key, setting_value) VALUES (?, ?)", 
              ("daily_limit", str(DAILY_LIMIT_PER_EMAIL)))
    c.execute("INSERT OR IGNORE INTO admin_settings (setting_key, setting_value) VALUES (?, ?)", 
              ("maintenance_mode", "false"))
    
    # Insert default API key
    c.execute("INSERT OR IGNORE INTO api_keys (key_name, api_key) VALUES (?, ?)", 
              ("Default Production Key", "nexeo_ig_prod_key_2024"))
    
    conn.commit()
    conn.close()

# Initialize database
init_db()

# ======================== HELPER FUNCTIONS ========================
def get_client_ip():
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0]
    return request.remote_addr

def get_daily_limit():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT setting_value FROM admin_settings WHERE setting_key = 'daily_limit'")
    result = c.fetchone()
    conn.close()
    return int(result[0]) if result else DAILY_LIMIT_PER_EMAIL

def is_maintenance_mode():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT setting_value FROM admin_settings WHERE setting_key = 'maintenance_mode'")
    result = c.fetchone()
    conn.close()
    return result and result[0] == 'true'

def check_daily_limit(email):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    cutoff = datetime.now() - timedelta(seconds=RATE_LIMIT_WINDOW)
    c.execute("SELECT COUNT(*) FROM rate_limits WHERE email = ? AND created_at > ?", 
              (email, cutoff))
    count = c.fetchone()[0]
    conn.close()
    daily_limit = get_daily_limit()
    return count < daily_limit

def log_creation(email, username, password, full_name, cookie, session_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""INSERT INTO accounts (email, username, password, full_name, cookie, session_id) 
                 VALUES (?, ?, ?, ?, ?, ?)""",
              (email, username, password, full_name, cookie, session_id))
    c.execute("INSERT INTO rate_limits (email) VALUES (?)", (email,))
    conn.commit()
    conn.close()

def get_stats():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM accounts")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(DISTINCT email) FROM accounts")
    unique_emails = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM rate_limits WHERE created_at > datetime('now', '-1 day')")
    today = c.fetchone()[0]
    conn.close()
    return {
        "total": total, 
        "unique_emails": unique_emails, 
        "today": today, 
        "daily_limit": get_daily_limit()
    }

def get_history(limit=20):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT username, full_name, email, created_at FROM accounts 
                 ORDER BY created_at DESC LIMIT ?""", (limit,))
    rows = c.fetchall()
    conn.close()
    return [{"username": r[0], "full_name": r[1], "email": r[2], "created_at": r[3]} for r in rows]

# ======================== INSTAGRAM API ========================
def get_headers():
    while True:
        try:
            an_agent = f'Mozilla/5.0 (Linux; Android {random.randint(9,13)}; {"".join(random.choices(string.ascii_uppercase, k=3))}{random.randint(111,999)}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'
            
            r = requests.get('https://www.instagram.com/api/v1/web/accounts/login/ajax/', 
                           headers={'user-agent': an_agent}, timeout=30).cookies
            
            resp = requests.get('https://www.instagram.com/', headers={'user-agent': an_agent}, timeout=30)
            appid = resp.text.split('APP_ID":"')[1].split('"')[0]
            rollout = resp.text.split('rollout_hash":"')[1].split('"')[0]

            headers = {
                'authority': 'www.instagram.com',
                'accept': '*/*',
                'accept-language': 'en-US,en;q=0.8',
                'content-type': 'application/x-www-form-urlencoded',
                'cookie': f'dpr=3; csrftoken={r["csrftoken"]}; mid={r["mid"]}; ig_did={r["ig_did"]}',
                'origin': 'https://www.instagram.com',
                'referer': 'https://www.instagram.com/accounts/signup/email/',
                'user-agent': an_agent,
                'x-csrftoken': r["csrftoken"],
                'x-ig-app-id': appid,
                'x-instagram-ajax': rollout,
                'x-web-device-id': r["ig_did"],
            }
            return headers
        except:
            time.sleep(1)

def send_verification(headers, email):
    try:
        device_id = headers['cookie'].split('mid=')[1].split(';')[0]
        data = {'device_id': device_id, 'email': email}
        r = requests.post('https://www.instagram.com/api/v1/accounts/send_verify_email/', 
                         headers=headers, data=data, timeout=30)
        return r.text
    except:
        return None

def verify_code(headers, email, code):
    try:
        device_id = headers['cookie'].split('mid=')[1].split(';')[0]
        data = {'code': code, 'device_id': device_id, 'email': email}
        r = requests.post('https://www.instagram.com/api/v1/accounts/check_confirmation_code/', 
                         headers=headers, data=data, timeout=30)
        return r
    except:
        return None

def create_account(headers, email, signup_code, custom_data):
    try:
        if custom_data.get('full_name'):
            full_name = custom_data['full_name']
            first_name = full_name.split()[0] if ' ' in full_name else full_name
        else:
            full_name = generate_full_name()
            first_name = full_name.split()[0]
        
        if custom_data.get('username'):
            username = custom_data['username']
        else:
            username = generate_username(first_name)
        
        if custom_data.get('password'):
            password = custom_data['password']
        else:
            password = f"{first_name}{random.randint(100,999)}@{random.choice(['ig', 'insta', 'gram'])}"

        data = {
            'enc_password': f'#PWD_INSTAGRAM_BROWSER:0:{round(time.time())}:{password}',
            'email': email,
            'username': username,
            'first_name': first_name,
            'month': random.randint(1, 12),
            'day': random.randint(1, 28),
            'year': random.randint(1990, 2001),
            'client_id': headers['cookie'].split('mid=')[1].split(';')[0],
            'seamless_login_enabled': '1',
            'tos_version': 'row',
            'force_sign_up_code': signup_code,
        }

        response = requests.post(
            'https://www.instagram.com/api/v1/web/accounts/web_create_ajax/',
            headers=headers, data=data, timeout=40
        )

        if '"account_created":true' in response.text:
            session_id = response.cookies.get('sessionid')
            csrftoken = headers.get('x-csrftoken')
            cookie_str = f"sessionid={session_id}; csrftoken={csrftoken}"
            
            return {
                "success": True,
                "username": username,
                "password": password,
                "full_name": full_name,
                "cookie": cookie_str,
                "session_id": session_id
            }
        else:
            return {"success": False, "error": "Creation failed"}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ======================== HTML TEMPLATES ========================
MAIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Nexeo IG | Premium Account Generator</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Inter', sans-serif;
            background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
            min-height: 100vh;
            transition: all 0.3s ease;
        }
        body.light-mode { background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%); }
        .glass-card {
            background: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(12px);
            border-radius: 32px;
            border: 1px solid rgba(255, 255, 255, 0.2);
            padding: 2rem;
            box-shadow: 0 25px 45px rgba(0,0,0,0.2);
            transition: all 0.3s ease;
        }
        body.light-mode .glass-card { background: rgba(255, 255, 255, 0.95); color: #1a1a2e; }
        .btn-primary {
            background: linear-gradient(90deg, #ff6b6b, #ee5a24, #ff6b6b);
            background-size: 200% auto;
            border: none;
            padding: 1rem 2rem;
            border-radius: 50px;
            font-weight: 700;
            color: white;
            cursor: pointer;
            width: 100%;
            transition: all 0.3s ease;
        }
        .btn-primary:hover:not(:disabled) { transform: translateY(-2px); box-shadow: 0 15px 30px rgba(255,107,107,0.3); }
        .step-dot {
            width: 50px;
            height: 50px;
            border-radius: 50%;
            background: rgba(255,255,255,0.2);
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
            transition: all 0.3s ease;
        }
        .step-dot.active { background: #ff6b6b; box-shadow: 0 0 20px rgba(255,107,107,0.8); transform: scale(1.1); }
        .step-dot.completed { background: #4ecdc4; }
        .step { display: none; animation: fadeIn 0.4s ease; }
        .step.active { display: block; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
        .input-group input {
            width: 100%;
            padding: 1rem;
            border-radius: 16px;
            background: rgba(255,255,255,0.1);
            border: 2px solid rgba(255,255,255,0.2);
            color: inherit;
            margin-bottom: 1rem;
        }
        .toast-notification {
            position: fixed;
            bottom: 20px;
            right: 20px;
            background: #333;
            color: white;
            padding: 1rem 1.5rem;
            border-radius: 12px;
            z-index: 2000;
            animation: slideIn 0.3s ease;
        }
        @keyframes slideIn { from { transform: translateX(100%); } to { transform: translateX(0); } }
        .result-box {
            margin-top: 1.5rem;
            padding: 1rem;
            background: rgba(0,0,0,0.3);
            border-radius: 20px;
            border-left: 4px solid #ff6b6b;
        }
        .loading-spinner {
            width: 20px;
            height: 20px;
            border: 3px solid rgba(255,255,255,0.3);
            border-radius: 50%;
            border-top-color: white;
            animation: spin 1s ease-in-out infinite;
            display: inline-block;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .sidebar {
            position: fixed;
            left: 0;
            top: 0;
            height: 100%;
            width: 280px;
            background: rgba(15, 25, 35, 0.95);
            backdrop-filter: blur(10px);
            transform: translateX(-100%);
            transition: transform 0.3s;
            z-index: 1000;
            padding: 2rem 1rem;
        }
        .sidebar.open { transform: translateX(0); }
        .nav-item {
            padding: 1rem;
            border-radius: 12px;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 1rem;
            color: #e0e0e0;
        }
        .nav-item.active { background: linear-gradient(135deg, #ff6b6b, #ee5a24); color: white; }
        .menu-toggle {
            position: fixed;
            left: 20px;
            top: 20px;
            z-index: 1001;
            background: rgba(255,107,107,0.2);
            backdrop-filter: blur(8px);
            border-radius: 50%;
            width: 50px;
            height: 50px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
        }
        .main-content {
            margin-left: 0;
            transition: margin-left 0.3s;
            padding: 2rem;
        }
        .main-content.shifted { margin-left: 280px; }
        .stat-card {
            background: rgba(255,255,255,0.15);
            backdrop-filter: blur(8px);
            border-radius: 24px;
            padding: 1.2rem;
            text-align: center;
        }
        @media (max-width: 768px) { .main-content { padding: 1rem; } .glass-card { padding: 1.5rem; } .step-dot { width: 40px; height: 40px; } }
    </style>
</head>
<body>
    <div class="menu-toggle" onclick="toggleSidebar()">
        <i class="fas fa-bars" style="font-size: 1.5rem; color: #ff6b6b;"></i>
    </div>
    <div class="sidebar" id="sidebar">
        <div style="text-align: center; padding-bottom: 2rem; border-bottom: 1px solid rgba(255,255,255,0.1);">
            <i class="fas fa-bolt" style="font-size: 2.5rem; color: #ff6b6b;"></i>
            <h2>Nexeo IG</h2>
            <p style="font-size: 0.8rem;">Premium Creator v4.6</p>
        </div>
        <div style="display: flex; flex-direction: column; gap: 0.5rem; margin-top: 2rem;">
            <div class="nav-item active" data-page="creator"><i class="fas fa-plus-circle"></i> Account Creator</div>
            <div class="nav-item" data-page="history"><i class="fas fa-history"></i> History</div>
            <div class="nav-item" data-page="about"><i class="fas fa-info-circle"></i> About</div>
            <div class="nav-item" data-page="docs"><i class="fas fa-book"></i> Documentation</div>
            <div class="nav-item" data-page="settings"><i class="fas fa-cog"></i> Settings</div>
        </div>
        <div style="position: absolute; bottom: 2rem; left: 0; right: 0; text-align: center; font-size: 0.7rem;">
            <i class="fas fa-shield-alt"></i> v4.6
        </div>
    </div>
    <div class="main-content" id="mainContent">
        <div id="creatorPage">
            <div style="text-align: center; margin-bottom: 2rem;">
                <div style="display: inline-block; background: rgba(255,107,107,0.2); padding: 0.5rem 1.5rem; border-radius: 50px; margin-bottom: 1rem;">
                    <i class="fas fa-bolt" style="color: #ff6b6b;"></i> PREMIUM TOOL
                </div>
                <h1 style="font-size: 3rem; background: linear-gradient(135deg, #fff, #ff6b6b); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">Account Creator</h1>
                <p>Step by step Instagram account generator</p>
            </div>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 2rem;">
                <div class="stat-card"><i class="fas fa-users" style="font-size: 2rem; color: #ff6b6b;"></i><h3 id="totalStats">0</h3><p>Total</p></div>
                <div class="stat-card"><i class="fas fa-calendar-day" style="font-size: 2rem; color: #ff6b6b;"></i><h3 id="todayStats">0</h3><p>Today</p></div>
                <div class="stat-card"><i class="fas fa-chart-line" style="font-size: 2rem; color: #ff6b6b;"></i><h3 id="limitStats">5</h3><p>Daily Limit</p></div>
            </div>
            <div class="glass-card">
                <div style="display: flex; justify-content: center; gap: 2rem; margin-bottom: 2rem;">
                    <div class="step-dot" id="step1Dot">1</div>
                    <div class="step-dot" id="step2Dot">2</div>
                    <div class="step-dot" id="step3Dot">3</div>
                </div>
                <div class="step active" id="step1">
                    <div class="input-group"><label><i class="fas fa-envelope"></i> Email Address</label><input type="email" id="emailInput" placeholder="your@email.com"></div>
                    <button class="btn-primary" id="sendCodeBtn"><i class="fas fa-paper-plane"></i> Send Verification Code</button>
                </div>
                <div class="step" id="step2">
                    <div class="input-group"><label><i class="fas fa-qrcode"></i> 6-Digit Verification Code</label><input type="text" id="codeInput" placeholder="Enter code" maxlength="6"></div>
                    <button class="btn-primary" id="verifyBtn" style="background: linear-gradient(135deg, #4ecdc4, #44a08d);"><i class="fas fa-check-circle"></i> Verify Code</button>
                </div>
                <div class="step" id="step3">
                    <div class="input-group"><label><i class="fas fa-user"></i> Full Name (Optional)</label><input type="text" id="fullName" placeholder="Leave empty for auto-generate"></div>
                    <div class="input-group"><label><i class="fab fa-instagram"></i> Username (Optional)</label><input type="text" id="username" placeholder="Leave empty for auto-generate"></div>
                    <div class="input-group"><label><i class="fas fa-key"></i> Password (Optional)</label><input type="text" id="password" placeholder="Leave empty for auto-generate"></div>
                    <button class="btn-primary" id="createBtn"><i class="fas fa-user-plus"></i> Create Account</button>
                </div>
                <div id="resultArea" class="result-box" style="display: none;"><div id="resultContent"></div></div>
            </div>
        </div>
        <div id="historyPage" style="display: none;"><div class="glass-card"><h2><i class="fas fa-history"></i> History</h2><div id="historyList"></div></div></div>
        <div id="aboutPage" style="display: none;"><div class="glass-card"><h2>About</h2><p>Premium Instagram account generator with step-by-step process.</p><p>Version 4.6 | Made for educational purposes</p></div></div>
        <div id="docsPage" style="display: none;"><div class="glass-card"><h2>Documentation</h2><pre style="background:rgba(0,0,0,0.3); padding:1rem; border-radius:12px;">API Base: /api/v1\nAPI Key: nexeo_ig_prod_key_2024\n\nEndpoints:\nPOST /api/v1/send-code\nPOST /api/v1/verify-code  \nPOST /api/v1/create-account\nGET /api/v1/stats\nGET /api/v1/history</pre></div></div>
        <div id="settingsPage" style="display: none;"><div class="glass-card"><h2>Settings</h2><select id="themeSelect"><option value="dark">Dark</option><option value="light">Light</option></select></div></div>
    </div>
    <div id="agreementModal" style="position: fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.8); display:none; align-items:center; justify-content:center; z-index:3000;">
        <div style="background:rgba(30,30,40,0.95); border-radius:32px; padding:2rem; text-align:center; max-width:500px;">
            <i class="fas fa-shield-alt" style="font-size:3rem; color:#ff6b6b;"></i>
            <h2>Terms of Service</h2>
            <p>By using this tool, you agree to use it responsibly.</p>
            <div style="display:flex; gap:1rem; margin-top:1.5rem;">
                <button onclick="acceptTerms()" style="background:#4ecdc4; border:none; padding:0.8rem 2rem; border-radius:50px; color:white; cursor:pointer;">I Agree</button>
                <button onclick="declineTerms()" style="background:#ff6b6b; border:none; padding:0.8rem 2rem; border-radius:50px; color:white; cursor:pointer;">Decline</button>
            </div>
        </div>
    </div>
    <script>
        let currentEmail = '', signupCode = '', currentStep = 1;
        function updateSteps() {
            for(let i=1;i<=3;i++) {
                const step = document.getElementById(`step${i}`), dot = document.getElementById(`step${i}Dot`);
                if(i<currentStep) dot.className = 'step-dot completed';
                else if(i===currentStep) dot.className = 'step-dot active';
                else dot.className = 'step-dot';
                if(step) step.classList.toggle('active', i===currentStep);
            }
        }
        function nextStep() { if(currentStep<3) { currentStep++; updateSteps(); } }
        function showToast(msg, isError=false) {
            const toast = document.createElement('div');
            toast.className = 'toast-notification';
            toast.style.background = isError ? '#dc3545' : '#28a745';
            toast.innerHTML = `<i class="fas ${isError ? 'fa-exclamation-triangle' : 'fa-check-circle'}"></i> ${msg}`;
            document.body.appendChild(toast);
            setTimeout(() => toast.remove(), 3000);
        }
        function showLoader(msg) {
            const loader = document.createElement('div');
            loader.id = 'loader';
            loader.style.cssText = 'position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.8); display:flex; align-items:center; justify-content:center; z-index:2000;';
            loader.innerHTML = `<div><div class="loading-spinner"></div><p style="margin-top:1rem;">${msg}</p></div>`;
            document.body.appendChild(loader);
        }
        function hideLoader() { const l = document.getElementById('loader'); if(l) l.remove(); }
        function showResult(data, isError=false) {
            const div = document.getElementById('resultArea'), content = document.getElementById('resultContent');
            div.style.display = 'block';
            if(isError) content.innerHTML = `<div style="color:#ff6b6b;"><i class="fas fa-exclamation-circle"></i> Error: ${data.error||data}</div>`;
            else content.innerHTML = `<div style="margin-bottom:1rem;"><i class="fas fa-check-circle" style="color:#4ecdc4;"></i> Account Created!</div><div><strong>Name:</strong> ${data.full_name}</div><div><strong>Username:</strong> <code>${data.username}</code></div><div><strong>Password:</strong> <code>${data.password}</code></div><button onclick="copyCredentials('${data.username}','${data.password}')" style="margin-top:1rem; background:rgba(255,255,255,0.2); border:none; padding:0.5rem 1rem; border-radius:20px; cursor:pointer;"><i class="fas fa-copy"></i> Copy Credentials</button>`;
        }
        window.copyCredentials = (u,p) => { navigator.clipboard.writeText(`${u}:${p}`); showToast('Copied!'); };
        async function loadStats() {
            try { const res = await fetch('/api/stats'); const d = await res.json(); document.getElementById('totalStats').textContent = d.total; document.getElementById('todayStats').textContent = d.today; document.getElementById('limitStats').textContent = d.daily_limit; } catch(e) {}
        }
        async function loadHistory() {
            try { const res = await fetch('/api/history'); const d = await res.json(); const div = document.getElementById('historyList'); if(d.length===0) div.innerHTML = '<p>No accounts yet.</p>'; else div.innerHTML = d.map(item => `<div style="padding:0.8rem; border-bottom:1px solid rgba(255,255,255,0.1);"><i class="fab fa-instagram"></i> <strong>${item.username}</strong><br><small>${new Date(item.created_at).toLocaleString()}</small></div>`).join(''); } catch(e) {}
        }
        document.getElementById('sendCodeBtn').onclick = async () => {
            const email = document.getElementById('emailInput').value.trim();
            if(!email || !email.includes('@')) return showToast('Valid email required', true);
            currentEmail = email;
            const btn = document.getElementById('sendCodeBtn');
            btn.disabled = true; btn.innerHTML = '<span class="loading-spinner"></span> Sending...';
            try {
                const res = await fetch('/api/send_code', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({email}) });
                const data = await res.json();
                if(data.success) { showToast('Code sent!'); nextStep(); } else showToast(data.error || 'Failed', true);
            } catch(e) { showToast('Network error', true); }
            btn.disabled = false; btn.innerHTML = '<i class="fas fa-paper-plane"></i> Send Verification Code';
        };
        document.getElementById('verifyBtn').onclick = async () => {
            const code = document.getElementById('codeInput').value.trim();
            if(!code || code.length!==6) return showToast('Enter 6-digit code', true);
            showLoader('Verifying...');
            try {
                const res = await fetch('/api/verify', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({email:currentEmail, code}) });
                const data = await res.json();
                hideLoader();
                if(data.success) { signupCode = data.signup_code; showToast('Verified!'); nextStep(); } else showToast('Invalid code', true);
            } catch(e) { hideLoader(); showToast('Error', true); }
        };
        document.getElementById('createBtn').onclick = async () => {
            const custom = { full_name: document.getElementById('fullName').value.trim(), username: document.getElementById('username').value.trim(), password: document.getElementById('password').value.trim() };
            showLoader('Creating account...');
            try {
                const res = await fetch('/api/create', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({email:currentEmail, signup_code:signupCode, custom}) });
                const data = await res.json();
                hideLoader();
                if(data.success) { showToast('Account created!'); showResult(data); loadStats(); loadHistory(); currentStep=1; updateSteps(); document.getElementById('emailInput').value=''; document.getElementById('codeInput').value=''; document.getElementById('fullName').value=''; document.getElementById('username').value=''; document.getElementById('password').value=''; } else showToast(data.error || 'Failed', true);
            } catch(e) { hideLoader(); showToast('Error', true); }
        };
        document.querySelectorAll('.nav-item').forEach(item => {
            item.onclick = () => {
                document.querySelectorAll('.nav-item').forEach(n=>n.classList.remove('active'));
                item.classList.add('active');
                const page = item.dataset.page;
                document.getElementById('creatorPage').style.display = page==='creator'?'block':'none';
                document.getElementById('historyPage').style.display = page==='history'?'block':'none';
                document.getElementById('aboutPage').style.display = page==='about'?'block':'none';
                document.getElementById('docsPage').style.display = page==='docs'?'block':'none';
                document.getElementById('settingsPage').style.display = page==='settings'?'block':'none';
                if(page==='history') loadHistory();
            };
        });
        function toggleSidebar() {
            const s = document.getElementById('sidebar'), m = document.getElementById('mainContent');
            s.classList.toggle('open'); m.classList.toggle('shifted');
        }
        document.getElementById('themeSelect').onchange = (e) => { if(e.target.value==='light') document.body.classList.add('light-mode'); else document.body.classList.remove('light-mode'); localStorage.setItem('theme', e.target.value); };
        if(localStorage.getItem('theme')==='light') { document.body.classList.add('light-mode'); document.getElementById('themeSelect').value = 'light'; }
        async function checkAgreement() { try { const res = await fetch('/api/has_agreed'); const data = await res.json(); if(!data.agreed) document.getElementById('agreementModal').style.display = 'flex'; } catch(e) {} }
        window.acceptTerms = async () => { await fetch('/api/agree',{method:'POST'}); document.getElementById('agreementModal').style.display='none'; showToast('Welcome!'); };
        window.declineTerms = () => { document.getElementById('agreementModal').style.display='none'; showToast('You must agree to use',true); };
        loadStats(); loadHistory(); checkAgreement(); setInterval(loadStats,10000); updateSteps();
    </script>
</body>
</html>
"""

# ======================== FLASK ROUTES ========================
@app.route('/')
def index():
    return render_template_string(MAIN_HTML)

@app.route('/api/has_agreed')
def has_agreed():
    return jsonify({"agreed": True})

@app.route('/api/agree', methods=['POST'])
def agree():
    return jsonify({"success": True})

@app.route('/api/stats')
def api_stats():
    return jsonify(get_stats())

@app.route('/api/history')
def api_history():
    return jsonify(get_history(20))

@app.route('/api/send_code', methods=['POST'])
def api_send_code():
    if is_maintenance_mode():
        return jsonify({"success": False, "error": "Under maintenance"})
    
    data = request.json
    email = data.get('email', '').strip()
    if not email:
        return jsonify({"success": False, "error": "Email required"})
    
    if not check_daily_limit(email):
        return jsonify({"success": False, "error": f"Daily limit reached. Max {get_daily_limit()} accounts per email."})
    
    headers = get_headers()
    if not headers:
        return jsonify({"success": False, "error": "Failed to initialize"})
    
    result = send_verification(headers, email)
    if result and 'email_sent":true' in result:
        session['temp_headers'] = headers
        session['temp_email'] = email
        return jsonify({"success": True})
    else:
        return jsonify({"success": False, "error": "Failed to send verification code"})

@app.route('/api/verify', methods=['POST'])
def api_verify():
    data = request.json
    email = data.get('email', '').strip()
    code = data.get('code', '').strip()
    
    headers = session.get('temp_headers')
    if not headers or session.get('temp_email') != email:
        headers = get_headers()
    
    verify_resp = verify_code(headers, email, code)
    if verify_resp and 'status":"ok' in verify_resp.text:
        try:
            signup_code = verify_resp.json().get('signup_code')
            session['signup_code'] = signup_code
            return jsonify({"success": True, "signup_code": signup_code})
        except:
            pass
    return jsonify({"success": False, "error": "Invalid verification code"})

@app.route('/api/create', methods=['POST'])
def api_create():
    if is_maintenance_mode():
        return jsonify({"success": False, "error": "Under maintenance"})
    
    data = request.json
    email = data.get('email', '').strip()
    signup_code = data.get('signup_code', '')
    custom = data.get('custom', {})
    
    if not email or not signup_code:
        return jsonify({"success": False, "error": "Missing data"})
    
    if not check_daily_limit(email):
        return jsonify({"success": False, "error": f"Daily limit reached"})
    
    headers = session.get('temp_headers')
    if not headers:
        headers = get_headers()
    
    result = create_account(headers, email, signup_code, custom)
    if result.get("success"):
        log_creation(email, result["username"], result["password"], result["full_name"], result["cookie"], result["session_id"])
        session.pop('temp_headers', None)
        session.pop('temp_email', None)
        session.pop('signup_code', None)
        return jsonify(result)
    else:
        return jsonify({"success": False, "error": result.get("error", "Creation failed")})

# ======================== API v1 ENDPOINTS ========================
def validate_api_key():
    api_key = request.headers.get('X-API-Key')
    if not api_key:
        return False
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM api_keys WHERE api_key = ? AND is_active = 1", (api_key,))
    count = c.fetchone()[0]
    conn.close()
    return count > 0

def require_api_key_v1(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not validate_api_key():
            return jsonify({"error": "Invalid or missing API key"}), 401
        return f(*args, **kwargs)
    return decorated

@app.route('/api/v1/send-code', methods=['POST'])
@require_api_key_v1
def api_v1_send_code():
    if is_maintenance_mode():
        return jsonify({"success": False, "error": "Under maintenance"})
    
    data = request.json
    email = data.get('email', '').strip()
    if not email:
        return jsonify({"success": False, "error": "Email required"})
    
    headers = get_headers()
    if not headers:
        return jsonify({"success": False, "error": "Failed to initialize"})
    
    result = send_verification(headers, email)
    if result and 'email_sent":true' in result:
        return jsonify({"success": True, "message": "Code sent successfully"})
    else:
        return jsonify({"success": False, "error": "Failed to send code"})

@app.route('/api/v1/verify-code', methods=['POST'])
@require_api_key_v1
def api_v1_verify():
    data = request.json
    email = data.get('email', '').strip()
    code = data.get('code', '').strip()
    
    headers = get_headers()
    verify_resp = verify_code(headers, email, code)
    if verify_resp and 'status":"ok' in verify_resp.text:
        try:
            signup_code = verify_resp.json().get('signup_code')
            return jsonify({"success": True, "signup_code": signup_code})
        except:
            pass
    return jsonify({"success": False, "error": "Invalid code"})

@app.route('/api/v1/create-account', methods=['POST'])
@require_api_key_v1
def api_v1_create():
    if is_maintenance_mode():
        return jsonify({"success": False, "error": "Under maintenance"})
    
    data = request.json
    email = data.get('email', '').strip()
    signup_code = data.get('signup_code', '')
    custom = data.get('custom', {})
    
    if not email or not signup_code:
        return jsonify({"success": False, "error": "Missing data"})
    
    headers = get_headers()
    result = create_account(headers, email, signup_code, custom)
    if result.get("success"):
        log_creation(email, result["username"], result["password"], result["full_name"], result["cookie"], result["session_id"])
        return jsonify(result)
    else:
        return jsonify({"success": False, "error": result.get("error", "Creation failed")})

@app.route('/api/v1/stats')
@require_api_key_v1
def api_v1_stats():
    return jsonify(get_stats())

@app.route('/api/v1/history')
@require_api_key_v1
def api_v1_history():
    return jsonify(get_history(20))

# For Vercel serverless
app.config['SESSION_TYPE'] = 'filesystem'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)

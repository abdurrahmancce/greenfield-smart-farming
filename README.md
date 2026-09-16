<div align="center">

# 🌱 GreenField Smart Farming Platform

**A full-stack smart farming web application for modern agricultural management**

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.0-000000?style=flat&logo=flask&logoColor=white)](https://flask.palletsprojects.com)
[![SQLite](https://img.shields.io/badge/SQLite-3-003B57?style=flat&logo=sqlite&logoColor=white)](https://sqlite.org)
[![Chart.js](https://img.shields.io/badge/Chart.js-4.4-FF6384?style=flat&logo=chartdotjs&logoColor=white)](https://chartjs.org)
[![OpenWeather](https://img.shields.io/badge/OpenWeather-API-EB6E4B?style=flat&logo=openstreetmap&logoColor=white)](https://openweathermap.org)
[![Render](https://img.shields.io/badge/Deploy-Render-46E3B7?style=flat&logo=render&logoColor=white)](https://render.com)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat)](LICENSE)
[![PWA](https://img.shields.io/badge/PWA-Ready-5A0FC8?style=flat&logo=pwa&logoColor=white)](https://web.dev/progressive-web-apps)

<br/>

> GreenField gives farmers real-time crop monitoring, live weather insights,
> irrigation scheduling, fertilizer recommendations, and data-driven analytics —
> all in one clean, responsive dashboard.

<br/>

[🚀 Live Demo](#-live-demo) · [📖 Documentation](#-documentation) · [⚡ Quick Start](#-installation) · [🤝 Contributing](#-author)

</div>

---

## 📌 Overview

GreenField is a **full-stack web application** built with Python Flask and SQLite that provides farmers with a centralised platform to manage their farms, monitor crop health, track weather conditions, and make data-driven decisions.

The platform features a **secure multi-user authentication system** where each farmer has a private account and sees only their own data. It integrates with the **OpenWeather API** for live weather data and provides an intelligent **NPK fertilizer calculator** with persistent history. The app is **PWA-enabled**, meaning it can be installed on any mobile device and works offline.

Built as a portfolio project for the **CSE program at IIUC (International Islamic University Chittagong)**, GreenField demonstrates end-to-end full-stack development skills including REST API design, relational database management, secure authentication, and cloud deployment.

---

## 📖 Documentation

### Architecture

```
Client (Browser / Mobile PWA)
        │
        ▼
   Flask Routes (app.py)
        │
   ┌────┴────┐
   │  SQLite │  ←── farming.db (local) or /data/farming.db (Render)
   └────┬────┘
        │
   Jinja2 Templates ──► HTML Response
        │
   Static Assets (CSS, JS, Chart.js, Font Awesome)
        │
   OpenWeather API  ←── External HTTP call
```

### Data Flow
1. User registers/logs in → session created → `user_id` stored in session
2. Every DB query filters by `user_id` → complete data isolation
3. Farm/note CRUD → SQLite → flash message → redirect
4. Weather page → `get_weather()` → OpenWeather API → fallback to mock
5. Fertilizer calculator → `POST /api/fertilizer` → JSON → auto-save to DB

### Security Model
- Passwords hashed with **bcrypt** via Werkzeug — never stored in plain text
- All protected routes use `@login_required` decorator
- `SECRET_KEY` loaded from environment variable in production
- Parameterised SQL queries throughout — no string interpolation

---

## ✨ Features

### 🔐 Authentication & User Management
- Secure **Register / Login / Logout** system
- **bcrypt** password hashing — plain text never stored
- Session-based authentication with Flask `session`
- **Complete profile management:**
  - Edit name, phone, bio, location, farm name
  - 8-colour avatar picker with live preview
  - Change email (requires password confirmation)
  - Change password with real-time strength meter
  - Delete account with cascade (removes all data permanently)

### 📊 Dashboard
- Live stat cards — total farms, crop varieties, total area, temperature, notes
- Recent farms table with crop badges and status indicators
- Live weather snapshot with humidity, wind, UV index
- Quick action buttons for common tasks
- Crop distribution doughnut chart
- Recent notes feed with category colour-coding
- Farm areas overview bar chart

### 🌾 Farm Management (Full CRUD)
- **Add** farms via modal form (name, crop, location, area, date, status)
- **Edit** farms with pre-filled modal populated via API call
- **Delete** farms with confirmation dialog (cascades to notes)
- **Crop Monitor** cards with animated progress bars:
  - Growth stage percentage
  - Water level percentage
  - Soil moisture percentage
  - Health status badge (Good / Fair / Poor)
- **Irrigation Reminders** per crop with urgency alerts
- Embedded **OpenStreetMap** (no API key needed) — Google Maps ready

### 🌦️ Live Weather
- **OpenWeather API** integration (current + 5-day forecast)
- Automatic **fallback to mock data** when key not set
- 🟢 Live / ⚪ Mock source badge
- City search with dynamic page reload
- Detailed stats: temperature, feels like, min/max, humidity, wind, pressure, UV, visibility, cloud cover, sunrise/sunset
- **7-day animated forecast** strip
- **4 farming advice cards** dynamically generated from live conditions (irrigation, wind, temperature, cloud cover)

### 📈 Analytics
- **4 interactive Chart.js charts:**
  - Farm Areas — horizontal bar chart
  - Monthly Water Usage — filled line chart
  - Monthly Harvest — bar chart
  - Crop Distribution — doughnut with legend
- Summary stat cards (farms tracked, water used, last harvest, growth %)
- Farm statistics table (area, estimated yield, weekly water need, size category)
- Farms by status breakdown

### 🧮 Fertilizer Calculator
- Select crop type + enter farm area
- Calculates **N (Nitrogen), P (Phosphorus), K (Potassium), Urea equivalent, Total**
- Results **auto-save to database** with timestamp
- Full **CRUD on saved history:**
  - Edit crop type, area, label
  - Delete individual records
- NPK reference table (7 crop types)
- Live search filter on history table

### 📝 Farm Notes
- Add categorised observations per farm
- **6 categories:** General, Nutrition, Pest Control, Irrigation, Growth, Harvest
- Colour-coded icons per category
- **Edit** notes via modal (API-powered pre-fill)
- **Delete** notes with confirmation
- Live search filter across all notes
- Expert farming tips sidebar
- Notes count per farm summary table

### 📱 Progressive Web App (PWA)
- `manifest.json` — installable on Android & iOS home screen
- `sw.js` service worker — offline support with network-first caching
- App shortcuts for Dashboard, Farms, Weather
- Theme colour and splash screen configured

### 🚀 Production Deploy
- `Procfile` — Gunicorn WSGI server configuration
- `render.yaml` — Render.com auto-deploy settings
- Persistent disk at `/data` for database storage on Render
- `SECRET_KEY` and `OPENWEATHER_KEY` from environment variables
- Debug mode disabled in production via `FLASK_ENV`

---

## 🛠️ Technologies

### Backend
| Technology | Version | Purpose |
|---|---|---|
| Python | 3.11+ | Core language |
| Flask | 3.0.0 | Web framework, routing |
| SQLite3 | Built-in | Relational database |
| Werkzeug | 3.0.1 | Password hashing (bcrypt) |
| Gunicorn | 21.2.0 | Production WSGI server |
| Requests | 2.31.0 | OpenWeather API HTTP calls |

### Frontend
| Technology | Version | Purpose |
|---|---|---|
| HTML5 | — | Semantic markup, 11 templates |
| CSS3 | — | Custom stylesheet (900+ lines) |
| Vanilla JavaScript | ES6+ | Modular JS, fetch API, DOM |
| Chart.js | 4.4.1 | Interactive analytics charts |
| Font Awesome | 6.5.0 | Icon library |
| Google Fonts | — | Poppins typeface |

### Services & Tools
| Service | Purpose |
|---|---|
| OpenWeather API | Live weather data + 5-day forecast |
| Render.com | Cloud hosting + persistent disk |
| GitHub | Version control + CI/CD |
| OpenStreetMap | Embedded farm location map |

### Design System
| Token | Value |
|---|---|
| Primary | `#1B5E20` |
| Primary Mid | `#2E7D32` |
| Primary Light | `#43A047` |
| Accent | `#8BC34A` |
| Background | `#F0FAF0` |
| Border | `#C8E6C9` |
| Font | Poppins (400, 500, 600, 700, 800, 900) |

---

## 📁 Project Structure

```
Smart-Farming/
│
├── app.py                    ← Flask application (728 lines)
│                               Routes, DB logic, Auth, API, Weather
│
├── requirements.txt          ← Python dependencies
├── Procfile                  ← Gunicorn start command
├── render.yaml               ← Render.com deploy config
├── .gitignore                ← Git ignore rules
├── README.md                 ← This file
│
├── static/
│   ├── css/
│   │   └── style.css         ← Complete custom stylesheet (900+ lines)
│   │                           CSS variables, sidebar, cards, modals,
│   │                           tables, badges, buttons, forms, charts,
│   │                           progress bars, weather, animations
│   │
│   ├── js/
│   │   └── app.js            ← All client-side JavaScript
│   │                           Sidebar toggle, modal system, CRUD wiring,
│   │                           Chart.js init, fertilizer calculator,
│   │                           progress bar animations, live search,
│   │                           service worker registration
│   │
│   ├── manifest.json         ← PWA manifest (app name, icons, shortcuts)
│   └── sw.js                 ← Service Worker (offline cache strategy)
│
├── templates/
│   ├── base.html             ← Shared layout (sidebar, topbar, flash)
│   ├── index.html            ← Public landing page
│   ├── login.html            ← Login form
│   ├── register.html         ← Registration form
│   ├── dashboard.html        ← Main dashboard with charts
│   ├── farms.html            ← Farm CRUD + crop monitor + irrigation
│   ├── notes.html            ← Notes CRUD + tips sidebar
│   ├── weather.html          ← Live weather + forecast + farming advice
│   ├── analytics.html        ← 4 charts + fertilizer calculator page
│   ├── fertilizer.html       ← Saved NPK calculations CRUD
│   └── profile.html          ← Full profile management
│
└── database/
    └── farming.db            ← SQLite database (auto-created on first run)
                                 Tables: users, farms, crop_notes,
                                         fertilizer_history, activity_log
```

---

## ⚙️ Installation

### Prerequisites
- Python 3.11 or higher
- Git
- A free OpenWeather API key *(optional — app works with mock data without it)*

### Local Setup

**1. Clone the repository**
```bash
git clone https://github.com/abdur-rahman-akash26/greenfield-smart-farming.git
cd greenfield-smart-farming
```

**2. Create a virtual environment**
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

**3. Install dependencies**
```bash
pip install -r requirements.txt
```

**4. Configure environment *(optional)***
```bash
# Windows
set OPENWEATHER_KEY=your_api_key_here
set SECRET_KEY=your_secret_key_here

# macOS / Linux
export OPENWEATHER_KEY=your_api_key_here
export SECRET_KEY=your_secret_key_here
```
Or paste directly into `app.py` line 13:
```python
OPENWEATHER_KEY = os.environ.get("OPENWEATHER_KEY", "paste_key_here")
```

**5. Run the application**
```bash
python app.py
```

**6. Open in browser**
```
http://127.0.0.1:5000
```

The SQLite database is created automatically on first run with demo seed data.

---

### Deploy to Render (Free — Multi-device access)

**1. Push to GitHub** *(see Installation above)*

**2. Go to [render.com](https://render.com) → Sign up with GitHub**

**3. New + → Web Service → Select your repository**

**4. Configure:**
| Setting | Value |
|---|---|
| Build Command | `pip install -r requirements.txt` |
| Start Command | `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2` |

**5. Environment Variables:**
| Key | Value |
|---|---|
| `SECRET_KEY` | Click Generate |
| `FLASK_ENV` | `production` |
| `OPENWEATHER_KEY` | Your API key |

**6. Add Disk:**
| Setting | Value |
|---|---|
| Mount Path | `/data` |
| Size | `1 GB` |

**7. Click Deploy → Your live URL:**
```
https://greenfield-smart-farming.onrender.com
```

---

## 🚀 Usage

### Getting Started
1. Open the app at `http://127.0.0.1:5000`
2. Click **Get Started Free** → Register with your name, email, password
3. Login → You are inside the **Dashboard**

### Adding Your First Farm
1. Sidebar → **Farm Management** → **+ Add New Farm**
2. Enter farm name, crop type, location, area, planting date
3. Click **Add Farm** → Farm appears in the list and on the map

### Checking Live Weather
1. Sidebar → **Weather**
2. Default city is Chittagong — search any city
3. View temperature, humidity, wind, UV index, 7-day forecast
4. Read the farming advice cards generated from current conditions

### Calculating Fertilizer
1. Sidebar → **Fertilizer Calc**
2. Select crop type → enter area (acres) → optionally add a label
3. Click **Calculate & Save** — NPK values are calculated and saved automatically
4. Edit or delete saved calculations from the history table

### Managing Notes
1. Sidebar → **Farm Notes**
2. Select a farm, write a title, choose a category, write your observation
3. Click **Save Note** — appears in the list with a colour-coded icon
4. Use the search bar to filter notes instantly

### Profile Management
1. Topbar → your name dropdown → **My Profile**
2. Update personal info, phone, bio, location, farm name, avatar colour
3. Change email or password from the same page
4. View your stats and recent farm activity

---

## 📸 Screenshots / Preview

### 🏠 Landing Page
> Animated hero section with floating circles, feature cards, and dynamic CTA based on login state.

### 📊 Dashboard
> 5 stat cards, recent farms table, live weather widget, quick actions, crop distribution chart.

### 🌾 Farm Management
> CRUD table with edit/delete, crop monitor progress bars, irrigation reminders, embedded map.

### 🌦️ Weather
> Live weather hero card, 6 stat cards (humidity, wind, UV, pressure, visibility, clouds), 7-day forecast, 4 farming advice cards.

### 📈 Analytics
> 4 Chart.js charts side by side, farm statistics table, status breakdown.

### 🧮 Fertilizer Calculator
> Calculator form with label, NPK result cards (N, P, K, Urea, Total), saved history table with edit/delete.

### 👤 Profile
> Avatar with colour picker, editable fields, email/password change forms, danger zone with account delete.

---

## 📊 Results

| Metric | Value |
|---|---|
| Total pages | 11 (including auth) |
| Backend routes | 25+ (pages + API) |
| API endpoints | 8 JSON endpoints |
| Database tables | 5 |
| CSS lines | 900+ |
| JS lines | 400+ |
| Python lines | 728 |
| Tests passed | 27 / 27 ✅ |
| Lighthouse PWA score | ✅ Installable |
| Deploy platform | Render (free tier) |
| Avg page load | < 200ms (local) |

### Test Coverage
```
✅ All 8 pages load correctly
✅ Register / Login / Logout
✅ Wrong password blocked
✅ Duplicate email blocked
✅ Protected routes redirect when logged out
✅ Add / Edit / Delete Farm
✅ Add / Edit / Delete Note
✅ Add / Edit / Delete Fertilizer calculation
✅ Update profile info (6 fields)
✅ Change email with password confirmation
✅ Change password with strength validation
✅ Account delete with cascade
✅ Weather API live + mock fallback
✅ Fertilizer NPK API
✅ Home vs Dashboard fully separated
✅ PWA manifest + service worker
✅ Deploy config (Procfile + render.yaml)
```

---

## 🔮 Future Improvements

| Feature | Priority | Description |
|---|---|---|
| 📊 Yield & Expense Tracking | High | Record harvest yield and farm expenses per season, profit/loss reports |
| 📤 Export PDF / Excel | High | Download farm reports and fertilizer history as PDF or Excel |
| 📧 Email Reminders | Medium | Automated irrigation reminder emails via Flask-Mail |
| 🗺️ Google Maps Full | Medium | Interactive map with geocoded farm markers and info windows |
| 📱 React Native App | Medium | Native iOS/Android app using the existing JSON API |
| 🌐 Bangla Language | Medium | Full Bangla UI option for Bangladeshi farmers |
| 🤖 AI Crop Advisory | High | GPT-powered crop disease detection from photos |
| ☁️ PostgreSQL | High | Migrate from SQLite to PostgreSQL for multi-user scale |
| 📸 Farm Photo Upload | Low | Attach photos to farm records and notes |
| 🔔 Push Notifications | Low | Browser push notifications for irrigation reminders |

---

## 👨‍💻 Author

<div align="center">

**Abdur Rahman**

CSE Undergraduate · International Islamic University Chittagong (IIUC)

Student ID: E241018

[![LinkedIn](https://img.shields.io/badge/LinkedIn-abdur--rahman--akash26-0077B5?style=flat&logo=linkedin&logoColor=white)](https://linkedin.com/in/abdur-rahman-akash26)
[![GitHub](https://img.shields.io/badge/GitHub-abdur--rahman--akash26-181717?style=flat&logo=github&logoColor=white)](https://github.com/abdur-rahman-akash26)
[![Email](https://img.shields.io/badge/Email-akash.abdur.2002@gmail.com-D14836?style=flat&logo=gmail&logoColor=white)](mailto:akash.abdur.2002@gmail.com)

</div>

---

## 📄 License

```
MIT License

Copyright (c) 2024 Abdur Rahman

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

<div align="center">

**⭐ If this project helped you, please give it a star on GitHub!**

Made with ❤️ and 🌱 by [Abdur Rahman](https://github.com/abdur-rahman-akash26)

*Built for CSE Portfolio @ IIUC · 2024*

</div>

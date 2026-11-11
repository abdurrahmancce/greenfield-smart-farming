"""
GreenField — language layer.

Every page is written in English. When the visitor picks বাংলা, the rendered
HTML is passed through `translate_html()` which swaps each visible text node,
placeholder, tooltip and known JavaScript message for natural, everyday Bangla.
When English is selected, `polish_html()` applies a few wording refinements so
the interface reads professionally.

Keys are matched on whitespace-normalised, HTML-unescaped text, so adding a new
phrase is as simple as adding one line to BN (or EN_POLISH).
"""
import html as _html
import re

# ──────────────────────────────────────────────────────────────────────
#  BANGLA — exact text matches
# ──────────────────────────────────────────────────────────────────────
BN = {
    # ── Navigation / shell ────────────────────────────────────────────
    "GreenField": "গ্রিনফিল্ড",
    "Smart Farming Platform": "স্মার্ট কৃষি প্ল্যাটফর্ম",
    "Public": "সবার জন্য",
    "Account": "অ্যাকাউন্ট",
    "My Profile": "আমার প্রোফাইল",
    "Logout": "লগআউট",
    "Install App": "অ্যাপ ইনস্টল করুন",
    "Dashboard": "ড্যাশবোর্ড",
    "My Farms": "আমার খামার",
    "My Data": "আমার তথ্য",
    "Overview": "সারসংক্ষেপ",
    "Fertilizer Calc": "সার হিসাব",
    "Fertilizer Calculator": "সার ক্যালকুলেটর",
    "Close": "বন্ধ করুন",
    "User menu": "ব্যবহারকারী মেনু",
    "Toggle dark mode": "ডার্ক মোড পরিবর্তন",
    "Toggle menu": "মেনু খুলুন/বন্ধ করুন",
    "Language": "ভাষা",
    "Main": "প্রধান",
    "Management": "ব্যবস্থাপনা",
    "Farm Tools": "খামার টুলস",
    "Market & Planning": "বাজার ও পরিকল্পনা",
    "Insights": "বিশ্লেষণ",
    "Home Page": "হোম পেজ",
    "Farm Management": "খামার ব্যবস্থাপনা",
    "Farm Notes": "খামার নোট",
    "Growth Tracker": "ফসল ট্র্যাকার",
    "Irrigation Log": "সেচ লগ",
    "Expense Tracker": "আয়-ব্যয় ট্র্যাকার",
    "Market Prices": "বাজার দর",
    "Crop Calendar": "ফসল ক্যালেন্ডার",
    "Farm Report": "খামার রিপোর্ট",
    "Weather": "আবহাওয়া",
    "Analytics": "বিশ্লেষণ",
    "Disease Detector": "রোগ সনাক্তকারী",
    "Good": "ভালো",
    "Due Soon": "শীঘ্রই প্রয়োজন",

    # ── Page titles / subtitles (topbar) ──────────────────────────────
    "Crop Growth Tracker": "ফসল বৃদ্ধি ট্র্যাকার",
    "Track planting dates, growth stages & harvest timeline": "রোপণের তারিখ, বৃদ্ধির ধাপ ও ফসল তোলার সময় ট্র্যাক করুন",
    "Irrigation / Water Log": "সেচ / পানির লগ",
    "Farm Expense Tracker": "খামারের আয়-ব্যয় ট্র্যাকার",
    "Fertilizer Calculator": "সার ক্যালকুলেটর",
    "Market Price Tracker": "বাজার দর ট্র্যাকার",
    "Bangladesh climate-based monthly planting & harvest guide": "বাংলাদেশের আবহাওয়া অনুযায়ী মাসভিত্তিক রোপণ ও ফসল তোলার নির্দেশিকা",
    "Printable farm summary": "প্রিন্ট করার উপযোগী খামার সারসংক্ষেপ",
    "My Profile": "আমার প্রোফাইল",
    "Manage your account — info, email, password, and settings.": "আপনার অ্যাকাউন্ট পরিচালনা করুন — তথ্য, ইমেইল, পাসওয়ার্ড ও সেটিংস।",
    "Total Farms": "মোট খামার",
    "Farm Notes": "খামার নোট",
    "Total Area": "মোট জমি",
    "Fert. Calcs": "সার হিসাব",
    "Fertilizer Calculations": "সার হিসাব",

    # ── Dashboard ────────────────────────────────────────────────────
    "Recent Farms": "সাম্প্রতিক খামার",
    "All": "সব",
    "All Crops": "সব ফসল",
    "All Farms": "সব খামার",
    "Farm": "খামার",
    "Crop": "ফসল",
    "Area": "জমির পরিমাণ",
    "Status": "অবস্থা",
    "No farms yet": "এখনও কোনো খামার নেই",
    "Add your first farm": "আপনার প্রথম খামার যোগ করুন",
    "Full Report": "পূর্ণ রিপোর্ট",
    "Humidity": "আর্দ্রতা",
    "km/h Wind": "কিমি/ঘণ্টা বাতাস",
    "Wind (km/h)": "বাতাস (কিমি/ঘণ্টা)",
    "UV Index": "ইউভি সূচক",
    "Quick Actions": "দ্রুত কাজ",
    "Add Farm": "খামার যোগ করুন",
    "Add Note": "নোট যোগ করুন",
    "Crop Distribution": "ফসলের বণ্টন",
    "Full Charts": "সব চার্ট",
    "Recent Notes": "সাম্প্রতিক নোট",
    "View All": "সব দেখুন",
    "No notes yet": "এখনও কোনো নোট নেই",
    "Add a note": "একটি নোট যোগ করুন",
    "Farm Areas Overview": "খামারের জমির সারসংক্ষেপ",
    "Full Analytics": "পূর্ণ বিশ্লেষণ",
    "📊 Real": "📊 প্রকৃত তথ্য",
    "⏳ No data yet": "⏳ এখনও তথ্য নেই",
    "Loaded from your farms database": "আপনার খামারের তথ্য থেকে নেওয়া",
    "Loaded from irrigation_log table": "আপনার সেচ লগ থেকে নেওয়া",
    "No irrigation data yet": "এখনও সেচের তথ্য নেই",
    "Loaded from expense_log table": "আপনার আয়-ব্যয় লগ থেকে নেওয়া",

    # ── Crop calendar ────────────────────────────────────────────────
    "Current month:": "চলতি মাস:",
    "— crops you can sow or harvest this month are highlighted below.": "— এই মাসে যেসব ফসল বুনতে বা কাটতে পারবেন সেগুলো নিচে চিহ্নিত করা আছে।",
    "🌱 Sow Now": "🌱 এখন বুনুন",
    "✂️ Harvest Now": "✂️ এখন কাটুন",
    "Sow:": "বপন:",
    "Harvest:": "ফসল তোলা:",
    "🌱 Good time to sow this month!": "🌱 এই মাস বপনের জন্য উপযুক্ত!",
    "✂️ Harvest season is now!": "✂️ এখন ফসল তোলার মৌসুম!",
    "Rabi (Winter)": "রবি (শীতকাল)",
    "Kharif-I (Pre-monsoon)": "খরিফ-১ (বর্ষার আগে)",
    "Kharif-II (Monsoon)": "খরিফ-২ (বর্ষাকাল)",
    "Year-round": "সারা বছর",
    "Oct–Mar": "অক্টোবর–মার্চ",
    "Mar–Jun": "মার্চ–জুন",
    "Jun–Oct": "জুন–অক্টোবর",
    "All months": "সব মাস",
    "Jan": "জানু", "Feb": "ফেব্রু", "Mar": "মার্চ", "Apr": "এপ্রিল", "May": "মে", "Jun": "জুন",
    "Jul": "জুলাই", "Aug": "আগস্ট", "Sep": "সেপ্টে", "Oct": "অক্টো", "Nov": "নভে", "Dec": "ডিসে",
    "Rice (Boro)": "ধান (বোরো)", "Rice (Aman)": "ধান (আমন)", "Rice (Aus)": "ধান (আউশ)",
    "Wheat": "গম", "Potato": "আলু", "Tomato": "টমেটো", "Onion": "পেঁয়াজ", "Mustard": "সরিষা",
    "Jute": "পাট", "Maize": "ভুট্টা", "Brinjal": "বেগুন", "Chilli": "মরিচ", "Garlic": "রসুন",
    "Ginger": "আদা", "Lentil": "মসুর ডাল", "Rice": "ধান",
    "All Bangladesh": "সারা বাংলাদেশ", "North Bangladesh": "উত্তর বাংলাদেশ",
    "North & Central": "উত্তর ও মধ্যাঞ্চল", "South Bangladesh": "দক্ষিণ বাংলাদেশ",
    "Hilly regions": "পার্বত্য অঞ্চল",

    # ── Disease detector ─────────────────────────────────────────────
    "Symptom Checker": "লক্ষণ যাচাই",
    "AI Diagnosis": "এআই নির্ণয়",
    "Describe what you see on the plant — leaves, stem, fruit or roots.": "গাছে যা দেখছেন তা লিখুন — পাতা, কাণ্ড, ফল বা শিকড়।",
    "Crop Type *": "ফসলের ধরন *",
    "— Select crop —": "— ফসল বেছে নিন —",
    "🌾 Rice": "🌾 ধান", "🌿 Wheat": "🌿 গম", "🌽 Maize": "🌽 ভুট্টা", "🍅 Tomato": "🍅 টমেটো",
    "🥔 Potato": "🥔 আলু", "🪴 Jute": "🪴 পাট", "🌻 Mustard": "🌻 সরিষা",
    "🌱 Other / General": "🌱 অন্যান্য / সাধারণ",
    "Link to Farm": "খামারের সাথে যুক্ত করুন",
    "(optional)": "(ঐচ্ছিক)",
    "— None —": "— কোনোটি নয় —",
    "Describe Symptoms *": "লক্ষণ লিখুন *",
    "Be specific: color, shape, location on plant": "বিস্তারিত লিখুন: রং, আকার, গাছের কোথায়",
    "Additional Info": "অতিরিক্ত তথ্য",
    "Detect Disease": "রোগ নির্ণয় করুন",
    "Quick symptoms:": "দ্রুত লক্ষণ:",
    "Brown spots": "বাদামী দাগ", "Yellow leaves": "হলুদ পাতা", "White powder": "সাদা গুঁড়া",
    "Wilting": "নেতিয়ে পড়া", "Rust pustules": "মরিচা রঙের গুটি", "Water-soaked": "পানি-ভেজা দাগ",
    "Leaf curl": "পাতা কুঁকড়ে যাওয়া", "Black spots": "কালো দাগ",
    "Detection Tips": "রোগ চেনার টিপস",
    "Check both upper and lower leaf surfaces": "পাতার উপর ও নিচ দুই পাশই দেখুন",
    "Note size, shape and color of lesions": "দাগের আকার, আকৃতি ও রং লক্ষ্য করুন",
    "Recent weather helps narrow diagnosis": "সাম্প্রতিক আবহাওয়ার তথ্য রোগ নির্ণয়ে সাহায্য করে",
    "Note where symptoms started on the plant": "গাছের কোথা থেকে লক্ষণ শুরু হয়েছে তা লক্ষ্য করুন",
    "No diagnosis yet": "এখনও কোনো নির্ণয় হয়নি",
    "Describe symptoms and click": "লক্ষণ লিখে ক্লিক করুন",
    "Analyzing symptoms...": "লক্ষণ বিশ্লেষণ করা হচ্ছে...",
    "Confidence": "নিশ্চয়তা",
    "Matched symptoms:": "মিলে যাওয়া লক্ষণ:",
    "Treatment": "চিকিৎসা",
    "Prevention": "প্রতিরোধ",
    "Also possible:": "আরও হতে পারে:",
    "AI-assisted diagnosis. Consult a local agricultural expert for confirmation.": "এটি এআই-সহায়ক নির্ণয়। নিশ্চিত হতে স্থানীয় কৃষি কর্মকর্তার পরামর্শ নিন।",
    "No Match Found": "কোনো মিল পাওয়া যায়নি",
    "Try Again": "আবার চেষ্টা করুন",
    "e.g. Brown spots with yellow halo on lower leaves...": "যেমন: নিচের পাতায় হলুদ বলয়সহ বাদামী দাগ...",
    "e.g. After heavy rain, plants 3 weeks old...": "যেমন: ভারী বৃষ্টির পর, গাছের বয়স ৩ সপ্তাহ...",
    "Please select a crop and describe symptoms.": "অনুগ্রহ করে ফসল বেছে নিন এবং লক্ষণ লিখুন।",

    # ── Expense tracker ──────────────────────────────────────────────
    "Add Entry": "হিসাব যোগ করুন",
    "— Select Farm —": "— খামার বেছে নিন —",
    "Type": "ধরন",
    "💸 Expense": "💸 খরচ",
    "💵 Income": "💵 আয়",
    "Expense": "খরচ",
    "Income": "আয়",
    "Date": "তারিখ",
    "Category": "ক্যাটাগরি",
    "Seeds": "বীজ", "Fertilizer": "সার", "Pesticide": "কীটনাশক", "Labour": "শ্রমিক খরচ",
    "Equipment": "যন্ত্রপাতি", "Irrigation": "সেচ", "Transport": "পরিবহন", "Other": "অন্যান্য",
    "Sales": "বিক্রয়", "Sale": "বিক্রয়", "Subsidy": "ভর্তুকি",
    "Amount (৳ BDT)": "টাকার পরিমাণ (৳)",
    "Description": "বিবরণ",
    "Save Entry": "হিসাব সংরক্ষণ করুন",
    "Filter by Farm": "খামার অনুযায়ী ফিল্টার",
    "Total Income": "মোট আয়",
    "Total Expense": "মোট খরচ",
    "Net Profit": "নিট লাভ",
    "Net Loss": "নিট ক্ষতি",
    "Amount": "পরিমাণ",
    "No entries yet": "এখনও কোনো হিসাব নেই",
    "Start tracking income and expenses for your farms.": "আপনার খামারের আয় ও খরচের হিসাব রাখা শুরু করুন।",
    "Brief description…": "সংক্ষিপ্ত বিবরণ…",
    "Delete this entry?": "এই হিসাবটি মুছে ফেলবেন?",

    # ── Farms ────────────────────────────────────────────────────────
    "Add New Farm": "নতুন খামার যোগ করুন",
    "Farm Name": "খামারের নাম",
    "Location": "অবস্থান",
    "Planted": "রোপিত",
    "Actions": "কাজ",
    "Click": "ক্লিক করুন",
    "to get started.": "শুরু করতে।",
    "Crop Monitor": "ফসল পর্যবেক্ষণ",
    "Live Status": "সরাসরি অবস্থা",
    "Growth": "বৃদ্ধি",
    "Water Level": "পানির স্তর",
    "Soil Moisture": "মাটির আর্দ্রতা",
    "Farm Locations Map": "খামারের অবস্থান মানচিত্র",
    "Live Locations": "সরাসরি অবস্থান",
    "Loading map…": "মানচিত্র লোড হচ্ছে…",
    "Irrigation Reminders": "সেচের রিমাইন্ডার",
    "Smart Schedule": "স্মার্ট সময়সূচি",
    "Next:": "পরবর্তী:",
    "Farm Name *": "খামারের নাম *",
    "— Select Crop —": "— ফসল বেছে নিন —",
    "Location *": "অবস্থান *",
    "Area (acres) *": "জমির পরিমাণ (একর) *",
    "Planting Date *": "রোপণের তারিখ *",
    "Active": "সক্রিয়", "Harvesting": "ফসল তোলা হচ্ছে",
    "Inactive": "নিষ্ক্রিয়", "Harvested": "ফসল তোলা হয়েছে",
    "Cancel": "বাতিল",
    "Edit Farm": "খামার সম্পাদনা",
    "Save Changes": "পরিবর্তন সংরক্ষণ করুন",
    "Search farms…": "খামার খুঁজুন…",
    "Edit": "সম্পাদনা",
    "Delete": "মুছুন",
    "e.g. Green Valley Farm": "যেমন: সবুজ উপত্যকা খামার",
    "e.g. Chittagong": "যেমন: চট্টগ্রাম",
    "acres": "একর", "ac": "একর", "acre": "একর",

    # ── Fertilizer ───────────────────────────────────────────────────
    "Calculate": "হিসাব করুন",
    "Enter crop type and area — result saves automatically to your history.": "ফসলের ধরন ও জমির পরিমাণ দিন — ফলাফল আপনার ইতিহাসে নিজে থেকেই সংরক্ষিত হবে।",
    "Farm Area (acres) *": "জমির পরিমাণ (একর) *",
    "Label / Note (optional)": "লেবেল / নোট (ঐচ্ছিক)",
    "Calculate & Save": "হিসাব করে সংরক্ষণ করুন",
    "NPK Reference": "এনপিকে (NPK) নির্দেশিকা",
    "Values in kg/acre. Adjust based on soil test results.": "মান কেজি/একর হিসেবে। মাটি পরীক্ষার ফল অনুযায়ী সামঞ্জস্য করুন।",
    "Saved Calculations": "সংরক্ষিত হিসাব",
    "Auto-saved on calculate": "হিসাব করলেই নিজে থেকে সংরক্ষিত",
    "Total": "মোট",
    "Label": "লেবেল",
    "No calculations yet": "এখনও কোনো হিসাব নেই",
    "Use the calculator on the left — results save here automatically.": "ক্যালকুলেটর ব্যবহার করুন — ফলাফল এখানে নিজে থেকেই সংরক্ষিত হবে।",
    "Edit Calculation": "হিসাব সম্পাদনা",
    "Label / Note": "লেবেল / নোট",
    "e.g. North Field, Season 2024": "যেমন: উত্তরের জমি, ২০২৪ মৌসুম",
    "Search history…": "ইতিহাসে খুঁজুন…",
    "e.g. North Field": "যেমন: উত্তরের জমি",
    "Delete this record?": "এই রেকর্ডটি মুছে ফেলবেন?",
    "Please select a crop and enter a valid area.": "অনুগ্রহ করে ফসল বেছে নিন এবং সঠিক জমির পরিমাণ দিন।",
    "Save failed — please try again.": "সংরক্ষণ করা যায়নি — আবার চেষ্টা করুন।",
    "Could not load record.": "রেকর্ড লোড করা যায়নি।",
    "Enter a valid crop and positive area.": "সঠিক ফসল ও ধনাত্মক জমির পরিমাণ দিন।",
    "Calculation failed — please try again.": "হিসাব করা যায়নি — আবার চেষ্টা করুন।",
    "Urea": "ইউরিয়া", "TSP": "টিএসপি", "MOP": "এমওপি",

    # ── Forgot / reset password ──────────────────────────────────────
    "Forgot Password — GreenField": "পাসওয়ার্ড ভুলে গেছেন — গ্রিনফিল্ড",
    "Back to Login": "লগইনে ফিরে যান",
    "Forgot Password?": "পাসওয়ার্ড ভুলে গেছেন?",
    "We'll send you a reset link": "আমরা আপনাকে রিসেট লিংক পাঠাব",
    "Enter the email address linked to your account. We'll send a secure link to reset your password — valid for 1 hour.": "আপনার অ্যাকাউন্টের ইমেইল ঠিকানা দিন। পাসওয়ার্ড রিসেট করার একটি নিরাপদ লিংক পাঠানো হবে — লিংকটি ১ ঘণ্টা পর্যন্ত কার্যকর থাকবে।",
    "Email Address": "ইমেইল ঠিকানা",
    "Send Reset Link": "রিসেট লিংক পাঠান",
    "Remembered your password?": "পাসওয়ার্ড মনে পড়েছে?",
    "Sign in →": "সাইন ইন করুন →",
    "you@example.com": "you@example.com",
    "Reset Password — GreenField": "পাসওয়ার্ড রিসেট — গ্রিনফিল্ড",
    "Set New Password": "নতুন পাসওয়ার্ড দিন",
    "Choose a strong new password": "একটি শক্তিশালী নতুন পাসওয়ার্ড বেছে নিন",
    "New Password": "নতুন পাসওয়ার্ড",
    "Confirm New Password": "নতুন পাসওয়ার্ড নিশ্চিত করুন",
    "Reset Password": "পাসওয়ার্ড রিসেট করুন",
    "← Back to Sign In": "← সাইন ইনে ফিরে যান",

    # ── Growth tracker ───────────────────────────────────────────────
    "Add Growth Record": "বৃদ্ধির রেকর্ড যোগ করুন",
    "Planting Date": "রোপণের তারিখ",
    "Expected Days to Harvest": "ফসল তোলার আনুমানিক দিন",
    "Current Growth Stage": "বর্তমান বৃদ্ধির ধাপ",
    "Notes (optional)": "নোট (ঐচ্ছিক)",
    "Add Record": "রেকর্ড যোগ করুন",
    "Growth Stage Guide": "বৃদ্ধির ধাপের নির্দেশিকা",
    "Planted:": "রোপণ:",
    "Progress": "অগ্রগতি",
    "Update Stage": "ধাপ আপডেট করুন",
    "No growth records yet": "এখনও কোনো বৃদ্ধির রেকর্ড নেই",
    "Add your first crop tracking record using the form on the left.": "বাম পাশের ফর্ম ব্যবহার করে আপনার প্রথম ফসল ট্র্যাকিং রেকর্ড যোগ করুন।",
    "Any observations…": "কোনো পর্যবেক্ষণ থাকলে লিখুন…",
    "Notes…": "নোট…",
    "Seedling": "চারা", "Vegetative": "বাড়ন্ত পর্যায়", "Flowering": "ফুল ফোটা",
    "Fruiting": "ফল ধরা", "Ripening": "পাকার পর্যায়",
    "First 2 weeks after planting": "রোপণের পর প্রথম ২ সপ্তাহ",
    "Leaf & stem growth phase": "পাতা ও কাণ্ড বাড়ার সময়",
    "Blossom & pollination stage": "ফুল ফোটা ও পরাগায়নের সময়",
    "Fruit/grain development": "ফল/দানা গঠনের সময়",
    "Final maturation before harvest": "ফসল তোলার আগে চূড়ান্ত পরিপক্বতা",
    "Crop harvested ✅": "ফসল তোলা হয়েছে ✅",
    "Crop harvested": "ফসল তোলা হয়েছে",
    "days expected": "দিন প্রত্যাশিত",
    "days": "দিন", "day": "দিন",
    "Delete this record?": "এই রেকর্ডটি মুছে ফেলবেন?",

    # ── Landing page ─────────────────────────────────────────────────
    "GreenField — Smart Farming Platform": "গ্রিনফিল্ড — স্মার্ট কৃষি প্ল্যাটফর্ম",
    "Features": "বৈশিষ্ট্য",
    "How it works": "কীভাবে কাজ করে",
    "Go to Dashboard": "ড্যাশবোর্ডে যান",
    "Login": "লগইন",
    "Register Free": "বিনামূল্যে নিবন্ধন",
    "You're logged in. Jump straight to your farm dashboard.": "আপনি লগইন করা আছেন। সরাসরি আপনার খামারের ড্যাশবোর্ডে যান।",
    "Smart Agriculture Platform": "স্মার্ট কৃষি প্ল্যাটফর্ম",
    "Farm Smarter,": "স্মার্টভাবে চাষ করুন,",
    "Harvest Better": "আরও ভালো ফসল পান",
    "GreenField gives you real-time crop monitoring, live weather insights, irrigation scheduling, and data-driven analytics — all in one clean dashboard built for modern farmers.": "গ্রিনফিল্ড আপনাকে দেয় ফসলের সরাসরি পর্যবেক্ষণ, আবহাওয়ার তথ্য, সেচের সময়সূচি ও তথ্যভিত্তিক বিশ্লেষণ — আধুনিক কৃষকদের জন্য তৈরি একটি পরিচ্ছন্ন ড্যাশবোর্ডে।",
    "Open My Dashboard": "আমার ড্যাশবোর্ড খুলুন",
    "Manage Farms": "খামার পরিচালনা",
    "Get Started Free": "বিনামূল্যে শুরু করুন",
    "Sign In": "সাইন ইন",
    "Smart Modules": "স্মার্ট মডিউল",
    "Crop Types": "ফসলের ধরন",
    "Live": "সরাসরি",
    "Weather API": "আবহাওয়া এপিআই",
    "Free": "বিনামূল্যে",
    "Open Source": "ওপেন সোর্স",
    "Everything you need": "যা যা দরকার সবই আছে",
    "Built for Modern Agriculture": "আধুনিক কৃষির জন্য তৈরি",
    "From planting day to harvest — GreenField keeps you informed and in control.": "রোপণ থেকে ফসল তোলা পর্যন্ত — গ্রিনফিল্ড আপনাকে রাখে সবকিছুর নিয়ন্ত্রণে।",
    "Simple setup": "সহজ শুরু",
    "How It Works": "কীভাবে কাজ করে",
    "Ready in 3 steps — no credit card, no cloud required.": "মাত্র ৩ ধাপে প্রস্তুত — ক্রেডিট কার্ড লাগবে না।",
    "Get started in three simple steps — no credit card required.": "মাত্র তিনটি সহজ ধাপে শুরু করুন — ক্রেডিট কার্ড লাগবে না।",
    "Create Account": "অ্যাকাউন্ট খুলুন",
    "Register with your name, email and password. Your data stays private — only you can see your farms.": "নাম, ইমেইল ও পাসওয়ার্ড দিয়ে নিবন্ধন করুন। আপনার তথ্য গোপন থাকবে — শুধু আপনি আপনার খামার দেখতে পারবেন।",
    "Add Your Farms": "আপনার খামার যোগ করুন",
    "Enter farm name, crop type, location, area and planting date. Monitor crop health with live progress bars.": "খামারের নাম, ফসলের ধরন, অবস্থান, জমির পরিমাণ ও রোপণের তারিখ দিন। প্রগ্রেস বারে ফসলের অবস্থা দেখুন।",
    "Track & Analyse": "ট্র্যাক ও বিশ্লেষণ করুন",
    "Check live weather, view analytics charts, calculate fertilizer, log notes — all from one dashboard.": "সরাসরি আবহাওয়া দেখুন, বিশ্লেষণ চার্ট দেখুন, সারের হিসাব করুন, নোট রাখুন — সবই এক ড্যাশবোর্ড থেকে।",
    "Free & Open Source": "বিনামূল্যে ও ওপেন সোর্স",
    "OpenWeather API": "ওপেনওয়েদার এপিআই",
    "Secure": "নিরাপদ",
    "Password Hashing": "পাসওয়ার্ড এনক্রিপশন",
    "Ready to grow smarter?": "স্মার্টভাবে চাষ করতে প্রস্তুত?",
    "Join GreenField today — free forever, runs locally on your machine.": "আজই গ্রিনফিল্ডে যোগ দিন — সম্পূর্ণ বিনামূল্যে।",
    "Join GreenField today — free to use, with your data kept private to your account.": "আজই গ্রিনফিল্ডে যোগ দিন — বিনামূল্যে, আর আপনার তথ্য থাকবে শুধু আপনার অ্যাকাউন্টে।",
    "Go to My Dashboard": "আমার ড্যাশবোর্ডে যান",
    "Create Free Account": "বিনামূল্যে অ্যাকাউন্ট খুলুন",
    "Farms": "খামার",
    "Notes": "নোট",
    "Register": "নিবন্ধন",

    # ── Irrigation ───────────────────────────────────────────────────
    "Log Irrigation": "সেচ লিখে রাখুন",
    "Method": "পদ্ধতি",
    "Water Used (Litres)": "ব্যবহৃত পানি (লিটার)",
    "Duration (minutes)": "সময়কাল (মিনিট)",
    "Water-Saving Tips": "পানি সাশ্রয়ের টিপস",
    "Total Sessions": "মোট সেচের সংখ্যা",
    "Total Water": "মোট পানি",
    "Total Duration": "মোট সময়",
    "Recent Logs": "সাম্প্রতিক লগ",
    "Litres": "লিটার",
    "Mins": "মিনিট",
    "No irrigation logs yet": "এখনও কোনো সেচের লগ নেই",
    "Start logging your irrigation sessions to track water usage.": "পানির ব্যবহার ট্র্যাক করতে আপনার সেচের হিসাব লেখা শুরু করুন।",
    "Soil condition, issues…": "মাটির অবস্থা, সমস্যা…",
    "Manual": "হাতে", "Drip": "ড্রিপ", "Sprinkler": "স্প্রিংকলার", "Flood": "প্লাবন", "Canal": "খাল",
    "Drip irrigation saves 30–50% more water than flood irrigation.": "ড্রিপ সেচে প্লাবন সেচের চেয়ে ৩০–৫০% বেশি পানি বাঁচে।",
    "Water in early morning to reduce evaporation.": "বাষ্পীভবন কমাতে খুব ভোরে সেচ দিন।",
    "Check soil moisture before irrigating — overwatering harms roots.": "সেচের আগে মাটির আর্দ্রতা দেখুন — বেশি পানি শিকড়ের ক্ষতি করে।",
    "Mulch around plants to retain soil moisture.": "মাটির আর্দ্রতা ধরে রাখতে গাছের গোড়ায় মালচিং করুন।",
    "Bangladesh monsoon (Jun–Oct): reduce irrigation significantly.": "বাংলাদেশের বর্ষাকালে (জুন–অক্টোবর) সেচ অনেক কমিয়ে দিন।",
    "Delete this log?": "এই লগটি মুছে ফেলবেন?",
    "☀️ No rain expected — consider irrigating your crops.": "☀️ বৃষ্টির সম্ভাবনা নেই — ফসলে সেচ দেওয়ার কথা ভাবুন।",
    "🌧️ Rain expected in the next 24 hours — irrigation may not be needed.": "🌧️ আগামী ২৪ ঘণ্টায় বৃষ্টির সম্ভাবনা আছে — সেচ নাও লাগতে পারে।",

    # ── Login / register ─────────────────────────────────────────────
    "Login — GreenField": "লগইন — গ্রিনফিল্ড",
    "Home": "হোম",
    "Welcome Back": "আবার স্বাগতম",
    "Sign in to your GreenField account": "আপনার গ্রিনফিল্ড অ্যাকাউন্টে সাইন ইন করুন",
    "Password": "পাসওয়ার্ড",
    "Forgot password?": "পাসওয়ার্ড ভুলে গেছেন?",
    "or": "অথবা",
    "Continue with Google": "গুগল দিয়ে চালিয়ে যান",
    "First time here?": "প্রথমবার এসেছেন?",
    "Create a free account — no credit card needed.": "বিনামূল্যে অ্যাকাউন্ট খুলুন — ক্রেডিট কার্ড লাগবে না।",
    "Or": "অথবা",
    "register now →": "এখনই নিবন্ধন করুন →",
    "Don't have an account?": "অ্যাকাউন্ট নেই?",
    "Create one free": "বিনামূল্যে খুলুন",
    "Your password": "আপনার পাসওয়ার্ড",
    "Register — GreenField": "নিবন্ধন — গ্রিনফিল্ড",
    "Create Your Account": "আপনার অ্যাকাউন্ট খুলুন",
    "Start managing your farms smarter today": "আজই স্মার্টভাবে খামার পরিচালনা শুরু করুন",
    "Full Name": "পুরো নাম",
    "Enter a password": "একটি পাসওয়ার্ড দিন",
    "Confirm Password": "পাসওয়ার্ড নিশ্চিত করুন",
    "Already have an account?": "আগেই অ্যাকাউন্ট আছে?",
    "Sign in": "সাইন ইন",
    "By registering you agree to use this app responsibly.": "নিবন্ধন করে আপনি দায়িত্বশীলভাবে এই অ্যাপ ব্যবহারে সম্মত হচ্ছেন।",
    "Your data stays on your local machine — no cloud upload.": "আপনার তথ্য গোপন থাকে — শুধু আপনিই দেখতে পারবেন।",
    "Your data is private and visible only to you.": "আপনার তথ্য গোপন থাকে — শুধু আপনিই দেখতে পারবেন।",
    "Repeat your password": "পাসওয়ার্ডটি আবার লিখুন",
    "Creating account…": "অ্যাকাউন্ট তৈরি হচ্ছে…",
    "✓ Passwords match": "✓ পাসওয়ার্ড মিলেছে",
    "Passwords do not match": "পাসওয়ার্ড মিলছে না",

    # ── Market ───────────────────────────────────────────────────────
    "📈 Rising": "📈 বাড়ছে", "📉 Falling": "📉 কমছে", "➡️ Stable": "➡️ স্থিতিশীল",
    "Rising": "বাড়ছে", "Falling": "কমছে", "Stable": "স্থিতিশীল",
    "Prices last updated:": "দাম সর্বশেষ আপডেট:",
    "Source: Dhaka wholesale market averages": "সূত্র: ঢাকার পাইকারি বাজারের গড় দাম",
    "Good time to sell — Boro prices rising after harvest season.": "বিক্রির ভালো সময় — ফসল তোলার মৌসুমের পর বোরোর দাম বাড়ছে।",
    "Prices stable. Store 2–3 weeks for better return.": "দাম স্থিতিশীল। ভালো দামের জন্য ২–৩ সপ্তাহ মজুত রাখুন।",
    "Wheat prices rising due to import costs. Sell now.": "আমদানি খরচের কারণে গমের দাম বাড়ছে। এখন বিক্রি করুন।",
    "Prices dropping. Consider cold storage if possible.": "দাম কমছে। সম্ভব হলে হিমাগারে রাখার কথা ভাবুন।",
    "High demand in Dhaka markets. Good time to sell.": "ঢাকার বাজারে চাহিদা বেশি। বিক্রির ভালো সময়।",
    "Stable demand. Local market preferred.": "চাহিদা স্থিতিশীল। স্থানীয় বাজারে বিক্রি করা ভালো।",
    "Onion prices surging. Excellent selling opportunity.": "পেঁয়াজের দাম দ্রুত বাড়ছে। বিক্রির দারুণ সুযোগ।",
    "High value crop. Dhaka wholesale recommended.": "উচ্চমূল্যের ফসল। ঢাকার পাইকারি বাজারে বিক্রি করুন।",
    "Steady demand from oil mills.": "তেলকলগুলোর কাছ থেকে চাহিদা স্থির আছে।",
    "Export demand increasing. Consider bulk selling.": "রপ্তানির চাহিদা বাড়ছে। বেশি পরিমাণে বিক্রির কথা ভাবুন।",
    "Poultry feed demand is consistent. Fair price now.": "পোল্ট্রি ফিডের চাহিদা স্থির। এখন ন্যায্য দাম পাওয়া যাচ্ছে।",
    "High price due to low local production. Good return.": "স্থানীয় উৎপাদন কম হওয়ায় দাম বেশি। ভালো লাভ পাবেন।",
    "Best selling crop this season. Act fast.": "এই মৌসুমে সবচেয়ে ভালো বিক্রি হওয়া ফসল। দ্রুত সিদ্ধান্ত নিন।",
    "Consistent spice market demand.": "মসলার বাজারে চাহিদা স্থির আছে।",
    "Pharma and food industry demand is steady.": "ওষুধ ও খাদ্য শিল্পের চাহিদা স্থির আছে।",
    "Lentil (Masur)": "মসুর ডাল", "Chilli (dry)": "শুকনো মরিচ", "Dry Chilli": "শুকনো মরিচ", "Masur Dal": "মসুর ডাল",
    "Turmeric": "হলুদ", "Cotton": "তুলা",
    "Reference prices (DAM Nov 2026)": "রেফারেন্স দাম (ডিএএম, নভেম্বর ২০২৬)",
    "Live data from DAM": "ডিএএম থেকে সরাসরি তথ্য",
    "Last fetched:": "সর্বশেষ সংগ্রহ:",
    "Live fetch unavailable — will retry in 6 hours": "সরাসরি তথ্য পাওয়া যায়নি — ৬ ঘণ্টা পর আবার চেষ্টা করা হবে",
    "Indicative averages for Bangladesh wholesale markets. Actual prices may vary by region, quality, and season.": "এগুলো বাংলাদেশের পাইকারি বাজারের আনুমানিক গড় দাম। অঞ্চল, মান ও মৌসুম অনুযায়ী প্রকৃত দাম আলাদা হতে পারে।",
    "Prices last updated: ": "দাম সর্বশেষ আপডেট: ",

    # ── Notes ────────────────────────────────────────────────────────
    "Farm *": "খামার *",
    "— Choose a farm —": "— খামার বেছে নিন —",
    "Title": "শিরোনাম",
    "General": "সাধারণ", "Nutrition": "পুষ্টি", "Pest Control": "পোকা দমন",
    "Note *": "নোট *",
    "Save Note": "নোট সংরক্ষণ করুন",
    "Farming Tips": "চাষের টিপস",
    "Expert": "বিশেষজ্ঞ",
    "All Notes": "সব নোট",
    "Select a farm on the left and log your first observation.": "বাম পাশ থেকে একটি খামার বেছে নিন এবং আপনার প্রথম পর্যবেক্ষণ লিখুন।",
    "Edit Note": "নোট সম্পাদনা",
    "e.g. Fertilizer Applied": "যেমন: সার দেওয়া হয়েছে",
    "Write your observation here…": "এখানে আপনার পর্যবেক্ষণ লিখুন…",
    "Search notes…": "নোট খুঁজুন…",
    "Observation title": "পর্যবেক্ষণের শিরোনাম",
    "Weeding": "আগাছা পরিষ্কার", "Disease": "রোগ", "Pests": "পোকামাকড়",

    # ── Profile ──────────────────────────────────────────────────────
    "View Photo": "ছবি দেখুন",
    "Remove": "সরান",
    "Upload Photo": "ছবি আপলোড করুন",
    "Change Photo": "ছবি পরিবর্তন",
    "Your Stats": "আপনার পরিসংখ্যান",
    "Edit Profile Info": "প্রোফাইলের তথ্য সম্পাদনা",
    "Personal Details": "ব্যক্তিগত তথ্য",
    "Full Name *": "পুরো নাম *",
    "Phone Number": "ফোন নম্বর",
    "Location / City": "অবস্থান / শহর",
    "Farm / Business Name": "খামার / ব্যবসার নাম",
    "Bio / About You": "আপনার সম্পর্কে",
    "Avatar Colour": "অ্যাভাটারের রং",
    "Save Profile": "প্রোফাইল সংরক্ষণ করুন",
    "Change Email": "ইমেইল পরিবর্তন",
    "Current Email": "বর্তমান ইমেইল",
    "New Email *": "নতুন ইমেইল *",
    "Confirm with Password *": "পাসওয়ার্ড দিয়ে নিশ্চিত করুন *",
    "Update Email": "ইমেইল আপডেট করুন",
    "Change Password": "পাসওয়ার্ড পরিবর্তন",
    "Current Password *": "বর্তমান পাসওয়ার্ড *",
    "New Password *": "নতুন পাসওয়ার্ড *",
    "Confirm New Password *": "নতুন পাসওয়ার্ড নিশ্চিত করুন *",
    "Account Info": "অ্যাকাউন্টের তথ্য",
    "Account ID": "অ্যাকাউন্ট আইডি",
    "Email": "ইমেইল",
    "Role": "ভূমিকা",
    "Phone": "ফোন",
    "Farm Name": "খামারের নাম",
    "Member Since": "সদস্য হয়েছেন",
    "Member since": "সদস্য হয়েছেন",
    "Data Storage": "তথ্য সংরক্ষণ",
    "Local SQLite Database": "লোকাল এসকিউলাইট ডেটাবেস",
    "Secure Cloud Database": "নিরাপদ ক্লাউড ডেটাবেস",
    "Farmer": "কৃষক", "Admin": "অ্যাডমিন",
    "Danger Zone": "বিপজ্জনক এলাকা",
    "Irreversible": "ফেরানো যায় না",
    "Deleting your account will permanently remove": "আপনার অ্যাকাউন্ট মুছে ফেললে স্থায়ীভাবে মুছে যাবে",
    "all your farms, notes, fertilizer calculations, and activity logs": "আপনার সব খামার, নোট, সারের হিসাব ও কার্যকলাপের লগ",
    ". This cannot be undone.": "। এটি আর ফেরানো যাবে না।",
    "Delete My Account": "আমার অ্যাকাউন্ট মুছুন",
    "Delete Account": "অ্যাকাউন্ট মুছুন",
    "This will permanently delete your account and": "এটি আপনার অ্যাকাউন্ট ও",
    "ALL data": "সব তথ্য",
    "Enter your password *": "আপনার পাসওয়ার্ড দিন *",
    "DELETE": "DELETE",
    "to confirm *": "লিখে নিশ্চিত করুন *",
    "Yes, Delete Forever": "হ্যাঁ, চিরতরে মুছে ফেলুন",
    "+880 1xxx-xxxxxx": "+880 1xxx-xxxxxx",
    "e.g. Chittagong, Bangladesh": "যেমন: চট্টগ্রাম, বাংলাদেশ",
    "e.g. Green Valley Agro": "যেমন: সবুজ উপত্যকা এগ্রো",
    "e.g. Rice farmer from Sylhet with 10 years experience…": "যেমন: সিলেটের ধান চাষি, ১০ বছরের অভিজ্ঞতা…",
    "new@email.com": "new@email.com",
    "Enter your current password": "আপনার বর্তমান পাসওয়ার্ড দিন",
    "Your current password": "আপনার বর্তমান পাসওয়ার্ড",
    "Min. 6 characters": "কমপক্ষে ৬ অক্ষর",
    "Repeat new password": "নতুন পাসওয়ার্ড আবার লিখুন",
    "Type DELETE here": "এখানে DELETE লিখুন",
    "Image too large. Maximum size is 5 MB.": "ছবির সাইজ অনেক বড়। সর্বোচ্চ ৫ এমবি।",

    # ── Farm report ──────────────────────────────────────────────────
    "Print / Save PDF": "প্রিন্ট / পিডিএফ সংরক্ষণ",
    "Download HTML": "এইচটিএমএল ডাউনলোড",
    "Back to Dashboard": "ড্যাশবোর্ডে ফিরে যান",
    "GreenField Farm Report": "গ্রিনফিল্ড খামার রিপোর্ট",
    "Farmer:": "কৃষক:",
    "Date:": "তারিখ:",
    "Crop:": "ফসল:",
    "Area:": "জমির পরিমাণ:",
    "Location:": "অবস্থান:",
    "Status:": "অবস্থা:",
    "No farms recorded yet.": "এখনও কোনো খামার নথিভুক্ত হয়নি।",
    "Financial Summary": "আর্থিক সারসংক্ষেপ",
    "Amount (৳)": "পরিমাণ (৳)",
    "No expense records found.": "কোনো আয়-ব্যয়ের রেকর্ড পাওয়া যায়নি।",
    "Crop Growth Status": "ফসলের বৃদ্ধির অবস্থা",
    "Expected Harvest": "প্রত্যাশিত ফসল তোলা",
    "Stage": "ধাপ",
    "No growth records found.": "কোনো বৃদ্ধির রেকর্ড পাওয়া যায়নি।",
    "Water (L)": "পানি (লি.)",
    "Duration": "সময়কাল",
    "No irrigation records found.": "কোনো সেচের রেকর্ড পাওয়া যায়নি।",
    "Generated by": "তৈরি করেছে",
    "GreenField Smart Farming Platform": "গ্রিনফিল্ড স্মার্ট কৃষি প্ল্যাটফর্ম",
    "This report is for reference purposes. Verify data with local agricultural office.": "এই রিপোর্টটি শুধু তথ্যের জন্য। নিশ্চিত হতে স্থানীয় কৃষি অফিসে যাচাই করুন।",
    "Farm Overview": "খামারের সারসংক্ষেপ",
    "Notes": "নোট",

    # ── Weather ──────────────────────────────────────────────────────
    "Live API unavailable:": "সরাসরি আবহাওয়া পাওয়া যাচ্ছে না:",
    "Get a free API key →": "বিনামূল্যে এপিআই কী নিন →",
    "Search": "খুঁজুন",
    "Live Data": "সরাসরি তথ্য",
    "Mock Data": "নমুনা তথ্য",
    "Sample Data": "নমুনা তথ্য",
    "Feels like": "অনুভূত তাপমাত্রা",
    "Min / Max": "সর্বনিম্ন / সর্বোচ্চ",
    "Pressure": "বায়ুচাপ",
    "Visibility": "দৃশ্যমানতা",
    "Clouds": "মেঘ",
    "Farming Advice": "চাষের পরামর্শ",
    "Based on live conditions": "সরাসরি আবহাওয়ার ভিত্তিতে",
    "Based on mock data": "নমুনা তথ্যের ভিত্তিতে",
    "Based on sample data": "নমুনা তথ্যের ভিত্তিতে",
    "Moderate humidity — normal irrigation schedule is appropriate. Check soil moisture daily.": "আর্দ্রতা মাঝারি — স্বাভাবিক সেচের সময়সূচিই ঠিক আছে। প্রতিদিন মাটির আর্দ্রতা দেখুন।",
    "Wind & Spraying": "বাতাস ও স্প্রে",
    "Temperature": "তাপমাত্রা",
    "Cloud Cover": "মেঘের আচ্ছাদন",
    "7-Day Forecast": "৭ দিনের পূর্বাভাস",
    "Mock": "নমুনা", "Sample": "নমুনা",
    "Search city…": "শহর খুঁজুন…",
    "Weather for": "আবহাওয়া:",
    "Light Rain": "হালকা বৃষ্টি", "Partly Cloudy": "আংশিক মেঘলা", "Clear": "পরিষ্কার",
    "Rain": "বৃষ্টি", "Thunderstorm": "বজ্রসহ বৃষ্টি", "Mist": "কুয়াশা", "Haze": "ধোঁয়াশা",
    "Showers": "বৃষ্টির ঝাপটা", "Sunny": "রৌদ্রোজ্জ্বল", "Cloudy": "মেঘলা", "Overcast clouds": "ঘন মেঘ",
    "Scattered clouds": "ছড়ানো মেঘ", "Few clouds": "সামান্য মেঘ", "Broken clouds": "ভাঙা মেঘ",
    "Clear sky": "পরিষ্কার আকাশ", "Light rain": "হালকা বৃষ্টি", "Moderate rain": "মাঝারি বৃষ্টি",
    "Heavy intensity rain": "ভারী বৃষ্টি",
    "Mon": "সোম", "Tue": "মঙ্গল", "Wed": "বুধ", "Thu": "বৃহ", "Fri": "শুক্র", "Sat": "শনি", "Sun": "রবি",
    "Extreme heat — water at dawn and dusk only.": "প্রচণ্ড গরম — শুধু ভোর ও সন্ধ্যায় সেচ দিন।",
    "Cold stress risk — protect seedlings tonight.": "ঠান্ডার ঝুঁকি — আজ রাতে চারাগাছ ঢেকে রাখুন।",
    "High humidity — watch for fungal disease.": "আর্দ্রতা বেশি — ছত্রাকজনিত রোগের দিকে নজর রাখুন।",
    "Low humidity — increase irrigation frequency.": "আর্দ্রতা কম — সেচ আরও ঘন ঘন দিন।",
    "Strong winds — delay spraying and secure tall crops.": "জোরালো বাতাস — স্প্রে পিছিয়ে দিন এবং লম্বা ফসল বেঁধে রাখুন।",
    "Conditions look good for field operations today.": "আজ মাঠের কাজের জন্য আবহাওয়া ভালো।",
    "Good conditions for farming today.": "আজ চাষাবাদের জন্য আবহাওয়া ভালো।",

    # ── Flash / system messages ──────────────────────────────────────
    "Please log in to continue.": "চালিয়ে যেতে অনুগ্রহ করে লগইন করুন।",
    "Full name is required.": "পুরো নাম দিতে হবে।",
    "Email is required.": "ইমেইল দিতে হবে।",
    "Password must be at least 6 characters.": "পাসওয়ার্ড কমপক্ষে ৬ অক্ষরের হতে হবে।",
    "Passwords do not match.": "পাসওয়ার্ড মিলছে না।",
    "An account with this email already exists.": "এই ইমেইল দিয়ে আগেই একটি অ্যাকাউন্ট আছে।",
    "Invalid email or password. Please try again.": "ইমেইল বা পাসওয়ার্ড সঠিক নয়। আবার চেষ্টা করুন।",
    "You have been logged out.": "আপনি লগআউট হয়েছেন।",
    "Google login is not configured.": "গুগল লগইন এখনও চালু করা হয়নি।",
    "Could not get user info from Google.": "গুগল থেকে ব্যবহারকারীর তথ্য পাওয়া যায়নি।",
    "If that email is registered, a reset link has been sent. Check your inbox (and the server log if email isn't configured).": "ইমেইলটি নিবন্ধিত থাকলে একটি রিসেট লিংক পাঠানো হয়েছে। আপনার ইনবক্স দেখুন।",
    "This reset link is invalid or has expired. Please request a new one.": "এই রিসেট লিংকটি সঠিক নয় অথবা মেয়াদ শেষ হয়ে গেছে। নতুন লিংকের জন্য অনুরোধ করুন।",
    "✅ Password reset successfully. Please sign in.": "✅ পাসওয়ার্ড সফলভাবে রিসেট হয়েছে। এখন সাইন ইন করুন।",
    "Name cannot be empty.": "নাম ফাঁকা রাখা যাবে না।",
    "✅ Profile updated successfully.": "✅ প্রোফাইল সফলভাবে আপডেট হয়েছে।",
    "Incorrect password — email not changed.": "পাসওয়ার্ড ভুল — ইমেইল পরিবর্তন হয়নি।",
    "Enter a valid email address.": "সঠিক ইমেইল ঠিকানা দিন।",
    "That email is already in use.": "এই ইমেইলটি আগেই ব্যবহৃত হয়েছে।",
    "✅ Email updated.": "✅ ইমেইল আপডেট হয়েছে।",
    "Current password is incorrect.": "বর্তমান পাসওয়ার্ড সঠিক নয়।",
    "New password must be at least 6 characters.": "নতুন পাসওয়ার্ড কমপক্ষে ৬ অক্ষরের হতে হবে।",
    "✅ Password changed.": "✅ পাসওয়ার্ড পরিবর্তন হয়েছে।",
    "Only JPG, PNG, GIF or WebP images allowed.": "শুধু JPG, PNG, GIF বা WebP ছবি দেওয়া যাবে।",
    "✅ Profile photo updated.": "✅ প্রোফাইল ছবি আপডেট হয়েছে।",
    "No photo selected.": "কোনো ছবি বাছাই করা হয়নি।",
    "✅ Profile photo removed.": "✅ প্রোফাইল ছবি সরানো হয়েছে।",
    "Incorrect password — account not deleted.": "পাসওয়ার্ড ভুল — অ্যাকাউন্ট মোছা হয়নি।",
    "Type DELETE to confirm account deletion.": "অ্যাকাউন্ট মুছতে নিশ্চিত করার জন্য DELETE লিখুন।",
    "Your account has been permanently deleted.": "আপনার অ্যাকাউন্ট স্থায়ীভাবে মুছে ফেলা হয়েছে।",
    "Farm name is required.": "খামারের নাম দিতে হবে।",
    "Crop type is required.": "ফসলের ধরন দিতে হবে।",
    "Location is required.": "অবস্থান দিতে হবে।",
    "Planting date is required.": "রোপণের তারিখ দিতে হবে।",
    "Area must be a positive number.": "জমির পরিমাণ অবশ্যই ধনাত্মক সংখ্যা হতে হবে।",
    "Farm not found or access denied.": "খামার পাওয়া যায়নি অথবা প্রবেশাধিকার নেই।",
    "Farm and note text are required.": "খামার ও নোটের লেখা দিতে হবে।",
    "Invalid farm.": "খামারটি সঠিক নয়।",
    "📝 Note saved!": "📝 নোট সংরক্ষিত হয়েছে!",
    "✅ Note updated.": "✅ নোট আপডেট হয়েছে।",
    "🗑️ Note deleted.": "🗑️ নোট মুছে ফেলা হয়েছে।",
    "✅ Calculation updated.": "✅ হিসাব আপডেট হয়েছে।",
    "🗑️ Record deleted.": "🗑️ রেকর্ড মুছে ফেলা হয়েছে।",
    "Please describe the symptoms": "অনুগ্রহ করে লক্ষণগুলো লিখুন",
    "Farm and planting date are required.": "খামার ও রোপণের তারিখ দিতে হবে।",
    "✅ Growth record added.": "✅ বৃদ্ধির রেকর্ড যোগ হয়েছে।",
    "✅ Growth stage updated.": "✅ বৃদ্ধির ধাপ আপডেট হয়েছে।",
    "Growth record deleted.": "বৃদ্ধির রেকর্ড মুছে ফেলা হয়েছে।",
    "Farm and date are required.": "খামার ও তারিখ দিতে হবে।",
    "✅ Irrigation logged.": "✅ সেচের হিসাব সংরক্ষিত হয়েছে।",
    "Log deleted.": "লগ মুছে ফেলা হয়েছে।",
    "Farm, date and amount are required.": "খামার, তারিখ ও পরিমাণ দিতে হবে।",
    "✅ Entry saved.": "✅ হিসাব সংরক্ষিত হয়েছে।",
    "Entry deleted.": "হিসাব মুছে ফেলা হয়েছে।",
    # fragments of flash messages that wrap a <strong>name</strong>
    "🌱 Welcome to GreenField,": "🌱 গ্রিনফিল্ডে স্বাগতম,",
    "! Your account is ready.": "! আপনার অ্যাকাউন্ট তৈরি হয়ে গেছে।",
    "👋 Welcome back,": "👋 আবার স্বাগতম,",
    "🌱 Farm": "🌱 খামার",
    "added!": "যোগ হয়েছে!",
    "✅ Farm": "✅ খামার",
    "updated.": "আপডেট হয়েছে।",
    "🗑️ Farm": "🗑️ খামার",
    "deleted.": "মুছে ফেলা হয়েছে।",
    "Delete farm": "খামার মুছুন",

    # ── Disease knowledge base ───────────────────────────────────────
    "Rice Blast": "ধানের ব্লাস্ট রোগ",
    "Brown Spot": "বাদামী দাগ রোগ",
    "Bacterial Leaf Blight": "ব্যাকটেরিয়াজনিত পাতা ঝলসানো",
    "Sheath Blight": "খোল পচা রোগ",
    "Wheat Rust": "গমের মরিচা রোগ",
    "Powdery Mildew": "পাউডারি মিলডিউ (সাদা গুঁড়া রোগ)",
    "Loose Smut": "লুজ স্মাট (কালো গুঁড়া রোগ)",
    "Early Blight": "আর্লি ব্লাইট (আগাম পাতা ঝলসানো)",
    "Late Blight": "লেট ব্লাইট (নাবি ধসা রোগ)",
    "Leaf Curl": "পাতা কোঁকড়ানো রোগ",
    "Fusarium Wilt": "ফুসারিয়াম উইল্ট (ঢলে পড়া রোগ)",
    "Northern Corn Leaf Blight": "ভুট্টার পাতা ঝলসানো রোগ",
    "Common Rust": "সাধারণ মরিচা রোগ",
    "Stalk Rot": "কাণ্ড পচা রোগ",
    "Nutrient Deficiency": "পুষ্টির অভাব",
    "Overwatering / Root Rot": "অতিরিক্ত সেচ / শিকড় পচা",
    "Fungal Infection": "ছত্রাকজনিত সংক্রমণ",
    "Apply Tricyclazole or Carbendazim fungicide. Remove infected leaves. Ensure proper spacing.": "ট্রাইসাইক্লাজল বা কার্বেন্ডাজিম ছত্রাকনাশক দিন। আক্রান্ত পাতা সরিয়ে ফেলুন। গাছের মধ্যে যথেষ্ট দূরত্ব রাখুন।",
    "Use resistant varieties. Avoid excess nitrogen. Maintain proper water level.": "রোগ প্রতিরোধী জাত ব্যবহার করুন। বেশি নাইট্রোজেন সার দেবেন না। জমিতে সঠিক পানির স্তর বজায় রাখুন।",
    "Apply Mancozeb or Iprobenfos. Improve soil nutrition with potassium.": "ম্যানকোজেব বা আইপ্রোবেনফস দিন। পটাশ সার দিয়ে মাটির পুষ্টি বাড়ান।",
    "Use certified seeds. Balanced fertilization. Proper water management.": "প্রত্যয়িত বীজ ব্যবহার করুন। সুষম সার দিন। পানি ব্যবস্থাপনা ঠিক রাখুন।",
    "No effective chemical. Remove infected plants. Use copper-based bactericide.": "কার্যকর কোনো রাসায়নিক নেই। আক্রান্ত গাছ সরিয়ে ফেলুন। কপারজাতীয় ব্যাকটেরিয়ানাশক ব্যবহার করুন।",
    "Use resistant varieties. Avoid flood irrigation. Balanced nitrogen.": "প্রতিরোধী জাত ব্যবহার করুন। প্লাবন সেচ এড়িয়ে চলুন। নাইট্রোজেন সার পরিমিত দিন।",
    "Apply Hexaconazole or Validamycin. Reduce plant density.": "হেক্সাকোনাজল বা ভ্যালিডামাইসিন দিন। গাছের ঘনত্ব কমান।",
    "Avoid dense planting. Reduce nitrogen. Drain fields periodically.": "ঘন করে রোপণ করবেন না। নাইট্রোজেন কমান। মাঝে মাঝে জমির পানি বের করে দিন।",
    "Apply Propiconazole or Tebuconazole fungicide immediately.": "এখনই প্রোপিকোনাজল বা টেবুকোনাজল ছত্রাকনাশক দিন।",
    "Use rust-resistant varieties. Early planting. Remove volunteer plants.": "মরিচা-প্রতিরোধী জাত ব্যবহার করুন। আগাম রোপণ করুন। আপনা-আপনি গজানো গাছ তুলে ফেলুন।",
    "Apply sulfur-based fungicide or Triadimefon.": "সালফারযুক্ত ছত্রাকনাশক বা ট্রাইঅ্যাডিমেফন দিন।",
    "Avoid dense planting. Reduce humidity. Use resistant varieties.": "ঘন রোপণ এড়ান। আর্দ্রতা কমান। প্রতিরোধী জাত ব্যবহার করুন।",
    "Plant certified disease-free seeds. Hot water seed treatment.": "রোগমুক্ত প্রত্যয়িত বীজ বপন করুন। গরম পানিতে বীজ শোধন করুন।",
    "Use carboxin or thiram seed treatment.": "কার্বক্সিন বা থিরাম দিয়ে বীজ শোধন করুন।",
    "Apply Chlorothalonil or Mancozeb. Remove infected lower leaves.": "ক্লোরোথালোনিল বা ম্যানকোজেব দিন। নিচের আক্রান্ত পাতা সরিয়ে ফেলুন।",
    "Crop rotation. Mulching. Avoid overhead irrigation.": "ফসলের পর্যায়ক্রম মানুন। মালচিং করুন। উপর থেকে পানি ছিটানো এড়ান।",
    "Apply Metalaxyl or Cymoxanil immediately. Destroy infected plants.": "এখনই মেটালাক্সিল বা সাইমক্সানিল দিন। আক্রান্ত গাছ নষ্ট করে ফেলুন।",
    "Avoid overhead watering. Good air circulation. Use resistant varieties.": "উপর থেকে পানি দেবেন না। বাতাস চলাচলের ব্যবস্থা রাখুন। প্রতিরোধী জাত ব্যবহার করুন।",
    "Control whitefly vectors with imidacloprid. Remove infected plants.": "ইমিডাক্লোপ্রিড দিয়ে সাদা মাছি দমন করুন। আক্রান্ত গাছ সরিয়ে ফেলুন।",
    "Use virus-free seedlings. Control insect vectors. Reflective mulch.": "ভাইরাসমুক্ত চারা ব্যবহার করুন। বাহক পোকা দমন করুন। প্রতিফলক মালচ ব্যবহার করুন।",
    "No chemical cure. Remove infected plants. Soil solarization.": "রাসায়নিক প্রতিকার নেই। আক্রান্ত গাছ সরিয়ে ফেলুন। মাটি সৌরশোধন করুন।",
    "Use resistant varieties. Crop rotation. Sterilize tools.": "প্রতিরোধী জাত ব্যবহার করুন। ফসলের পর্যায়ক্রম মানুন। যন্ত্রপাতি জীবাণুমুক্ত করুন।",
    "Apply Metalaxyl or Mancozeb. Destroy infected tubers.": "মেটালাক্সিল বা ম্যানকোজেব দিন। আক্রান্ত কন্দ নষ্ট করে ফেলুন।",
    "Use certified seed potato. Avoid overhead irrigation. Good drainage.": "প্রত্যয়িত বীজ আলু ব্যবহার করুন। উপর থেকে সেচ এড়ান। পানি নিষ্কাশনের ব্যবস্থা রাখুন।",
    "Apply Chlorothalonil or Iprodione fungicide.": "ক্লোরোথালোনিল বা আইপ্রোডায়োন ছত্রাকনাশক দিন।",
    "Crop rotation. Remove plant debris. Balanced fertilization.": "ফসলের পর্যায়ক্রম মানুন। গাছের অবশিষ্টাংশ সরিয়ে ফেলুন। সুষম সার দিন।",
    "No effective treatment. Remove and destroy infected plants.": "কার্যকর কোনো চিকিৎসা নেই। আক্রান্ত গাছ তুলে নষ্ট করে ফেলুন।",
    "Use certified seed. Good drainage. Avoid injuring stems.": "প্রত্যয়িত বীজ ব্যবহার করুন। পানি নিষ্কাশনের ব্যবস্থা রাখুন। কাণ্ডে আঘাত লাগাবেন না।",
    "Apply Propiconazole. Remove infected debris after harvest.": "প্রোপিকোনাজল দিন। ফসল তোলার পর আক্রান্ত অবশিষ্টাংশ সরিয়ে ফেলুন।",
    "Use resistant hybrids. Crop rotation. Proper spacing.": "প্রতিরোধী হাইব্রিড ব্যবহার করুন। ফসলের পর্যায়ক্রম মানুন। সঠিক দূরত্বে রোপণ করুন।",
    "Apply Mancozeb or Trifloxystrobin fungicide.": "ম্যানকোজেব বা ট্রাইফ্লক্সিস্ট্রবিন ছত্রাকনাশক দিন।",
    "Use resistant varieties. Early planting. Proper plant nutrition.": "প্রতিরোধী জাত ব্যবহার করুন। আগাম রোপণ করুন। গাছের পুষ্টি ঠিক রাখুন।",
    "Balanced fertilization. Avoid stress. Control insects.": "সুষম সার দিন। গাছকে চাপে ফেলবেন না। পোকা দমন করুন।",
    "No effective chemical. Harvest early to prevent loss.": "কার্যকর কোনো রাসায়নিক নেই। ক্ষতি এড়াতে আগে ফসল তুলে ফেলুন।",
    "Apply balanced NPK fertilizer. Soil test to identify specific deficiency.": "সুষম এনপিকে সার দিন। কোন পুষ্টির অভাব আছে তা জানতে মাটি পরীক্ষা করান।",
    "Regular soil testing. Balanced fertilization. Proper pH management.": "নিয়মিত মাটি পরীক্ষা করান। সুষম সার দিন। মাটির পিএইচ ঠিক রাখুন।",
    "Reduce watering. Improve drainage. Apply fungicide to roots.": "সেচ কমান। পানি নিষ্কাশন ভালো করুন। শিকড়ে ছত্রাকনাশক দিন।",
    "Well-draining soil. Avoid waterlogging. Monitor soil moisture.": "পানি নিষ্কাশনের উপযোগী মাটি রাখুন। জলাবদ্ধতা এড়ান। মাটির আর্দ্রতা পর্যবেক্ষণ করুন।",
    "Apply broad-spectrum fungicide (Mancozeb or Copper oxychloride).": "বহুমুখী ছত্রাকনাশক (ম্যানকোজেব বা কপার অক্সিক্লোরাইড) দিন।",
    "Good air circulation. Avoid overhead irrigation. Remove debris.": "বাতাস চলাচলের ব্যবস্থা রাখুন। উপর থেকে সেচ এড়ান। আবর্জনা সরিয়ে ফেলুন।",
    "No specific disease matched. Try describing symptoms in more detail.": "নির্দিষ্ট কোনো রোগের সাথে মেলেনি। লক্ষণগুলো আরও বিস্তারিত লিখে দেখুন।",
    "brown spots": "বাদামী দাগ", "diamond shaped lesion": "হীরার আকৃতির ক্ষত", "gray center": "মাঝখানে ধূসর",
    "white lesion": "সাদা ক্ষত", "brown circular spots": "গোলাকার বাদামী দাগ", "brown spot": "বাদামী দাগ",
    "circular brown": "গোলাকার বাদামী", "dark brown": "গাঢ় বাদামী", "yellow halo": "হলুদ বলয়",
    "leaf edge yellow": "পাতার কিনারা হলুদ", "water soaked": "পানি-ভেজা দাগ", "yellow edge": "হলুদ কিনারা",
    "yellow stripe": "হলুদ রেখা", "gray lesion sheath": "খোলে ধূসর ক্ষত", "oval lesion": "ডিম্বাকৃতি ক্ষত",
    "water soaked sheath": "খোলে পানি-ভেজা দাগ", "white center sheath": "খোলের মাঝখানে সাদা",
    "orange powder": "কমলা গুঁড়া", "orange spots": "কমলা দাগ", "rust colored pustules": "মরিচা রঙের গুটি",
    "powdery coating": "গুঁড়ার মতো আস্তরণ", "white coat": "সাদা আস্তরণ", "white fungus": "সাদা ছত্রাক",
    "white powder": "সাদা গুঁড়া", "black dust": "কালো ধুলা", "black powder": "কালো গুঁড়া",
    "black spores": "কালো স্পোর", "dark powder": "গাঢ় গুঁড়া", "brown lesion": "বাদামী ক্ষত",
    "concentric rings": "বৃত্তাকার রেখা", "dark spots": "গাঢ় দাগ", "early blight": "আর্লি ব্লাইট",
    "target spot": "লক্ষ্যবস্তুর মতো দাগ", "greasy spots": "তেলতেলে দাগ", "late blight": "লেট ব্লাইট",
    "white mold underside": "পাতার নিচে সাদা ছাতা", "curling leaves": "কুঁকড়ানো পাতা", "leaf curl": "পাতা কুঁকড়ে যাওয়া",
    "twisted leaves": "পাকানো পাতা", "upward curl": "উপরের দিকে কোঁকড়ানো", "brown stem": "বাদামী কাণ্ড",
    "vascular discoloration": "নালিকা বিবর্ণ হওয়া", "brown patch": "বাদামী ছোপ", "dark lesion": "গাঢ় ক্ষত",
    "white mold": "সাদা ছাতা", "angular spots": "কোণাকার দাগ", "dark brown spots": "গাঢ় বাদামী দাগ",
    "black leg": "কালো পা", "black stem base": "কাণ্ডের গোড়া কালো", "soft rot": "নরম পচন", "stem rot": "কাণ্ড পচা",
    "cigar shaped": "চুরুটের আকৃতি", "gray streak": "ধূসর রেখা", "leaf blight": "পাতা ঝলসানো",
    "long gray lesion": "লম্বা ধূসর ক্ষত", "long lesion": "লম্বা ক্ষত", "brick red": "ইটের মতো লাল",
    "orange pustules": "কমলা গুটি", "powdery orange": "কমলা গুঁড়া", "rust colored": "মরিচা রঙের",
    "soft stalk": "নরম কাণ্ড", "stalk discoloration": "কাণ্ড বিবর্ণ", "stalk rot": "কাণ্ড পচা",
    "light green": "হালকা সবুজ", "pale leaves": "ফ্যাকাশে পাতা", "root rot": "শিকড় পচা",
    "soggy soil": "ভেজা সঁাতসেঁতে মাটি", "black growth": "কালো বৃদ্ধি", "white growth": "সাদা বৃদ্ধি",
    "yellowing": "হলুদ হয়ে যাওয়া", "wilt": "ঢলে পড়া",
}

# Phrases containing a number or name. {n} matches any text.
BN_PATTERNS = [
    ("{n} — Smart Farming", "{n} — স্মার্ট কৃষি"),
    ("Transactions ({n})", "লেনদেন ({n})"),
    ("Farm Overview ({n} Farms)", "খামারের সারসংক্ষেপ ({n}টি খামার)"),
    ("Farm Overview ({n} Farm)", "খামারের সারসংক্ষেপ ({n}টি খামার)"),
    ("Irrigation Log (Recent {n})", "সেচ লগ (সাম্প্রতিক {n}টি)"),
    ("{n} days expected", "{n} দিন প্রত্যাশিত"),
    ("{n} days | Planted {m}", "{n} দিন | রোপণ {m}"),
    ("{n} days", "{n} দিন"),
    ("{n} saved", "{n}টি সংরক্ষিত"),
    ("{n} farms", "{n}টি খামার"),
    ("{n} notes", "{n}টি নোট"),
    ("{n} logs", "{n}টি লগ"),
    ("{n} records", "{n}টি রেকর্ড"),
    ("{n} entries", "{n}টি হিসাব"),
    ("Delete farm \"{n}\"?", "\"{n}\" খামারটি মুছে ফেলবেন?"),
    ("Planted: {n}", "রোপণ: {n}"),
    ("Harvest: {n}", "ফসল তোলা: {n}"),
    ("Updated {n}", "আপডেট: {n}"),
    ("Next: {n}", "পরবর্তী: {n}"),
    ("Wind {n}", "বাতাস {n}"),
    ("Updated: {n}", "আপডেট: {n}"),
    ("Weather in {n}", "{n}-এর আবহাওয়া"),
    ("{n} acres", "{n} একর"),
    ("{n} ac", "{n} একর"),
    ("{n} kg", "{n} কেজি"),
    ("Member since {n}", "সদস্য হয়েছেন {n}"),
    ("Showing {n}", "দেখানো হচ্ছে {n}"),
    ("Added {n}", "যোগ করা হয়েছে {n}"),
    ("{n}min", "{n} মিনিট"),
    ("{n} min", "{n} মিনিট"),
]

# ──────────────────────────────────────────────────────────────────────
#  JavaScript messages (substring replace inside <script> blocks)
# ──────────────────────────────────────────────────────────────────────
BN_JS = {
    "Please select a crop and describe symptoms.": "অনুগ্রহ করে ফসল বেছে নিন এবং লক্ষণ লিখুন।",
    "'Error: '": "'ত্রুটি: '",
    "Delete this entry?": "এই হিসাবটি মুছে ফেলবেন?",
    "Delete this record?": "এই রেকর্ডটি মুছে ফেলবেন?",
    "Delete this log?": "এই লগটি মুছে ফেলবেন?",
    "Could not load record.": "রেকর্ড লোড করা যায়নি।",
    "Image too large. Maximum size is 5 MB.": "ছবির সাইজ অনেক বড়। সর্বোচ্চ ৫ এমবি।",
    "Please select a crop and enter a valid area.": "অনুগ্রহ করে ফসল বেছে নিন এবং সঠিক জমির পরিমাণ দিন।",
    "Save failed — please try again.": "সংরক্ষণ করা যায়নি — আবার চেষ্টা করুন।",
    "✓ Passwords match": "✓ পাসওয়ার্ড মিলেছে",
    "Passwords do not match": "পাসওয়ার্ড মিলছে না",
    "Creating account…": "অ্যাকাউন্ট তৈরি হচ্ছে…",
    "Analyzing symptoms...": "লক্ষণ বিশ্লেষণ করা হচ্ছে...",
}

# ──────────────────────────────────────────────────────────────────────
#  ENGLISH — wording polish (applied when English is selected)
# ──────────────────────────────────────────────────────────────────────
EN_POLISH = {
    "Fertilizer Calc": "Fertilizer Calculator",
    "Fert. Calcs": "Fertilizer Calculations",
    "km/h Wind": "Wind (km/h)",
    "Mock Data": "Sample Data",
    "Mock": "Sample",
    "Based on mock data": "Based on sample data",
    "Live API unavailable:": "Live weather is unavailable —",
    "Join GreenField today — free forever, runs locally on your machine.": "Join GreenField today — free to use, with your data kept private to your account.",
    "Ready in 3 steps — no credit card, no cloud required.": "Get started in three simple steps — no credit card required.",
    "Your data stays on your local machine — no cloud upload.": "Your data is private and visible only to you.",
    "🌱 GreenField Smart Farming": "🌱 GreenField Smart Farming",
    "Local SQLite Database": "Secure Cloud Database",
    "📊 Real": "📊 Live data",
    "⏳ No data yet": "⏳ No data yet",
    "Loaded from irrigation_log table": "Based on your irrigation log",
    "Loaded from expense_log table": "Based on your income & expense log",
    "Loaded from your farms database": "Based on your farm records",
    "No irrigation data yet": "No irrigation data recorded yet",
    "Describe symptoms and click": "Describe the symptoms, then click",
    "Click": "Click",
    "to get started.": "to get started.",
    "Prices last updated:": "Prices last updated:",
}

# ──────────────────────────────────────────────────────────────────────
#  Engine
# ──────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────
#  Extra vocabulary — page titles, subtitles, tips, weather advice, landing page
# ──────────────────────────────────────────────────────────────────────
BN.update({
    "Only JPG, PNG, GIF or WebP images allowed.": "শুধু JPG, PNG, GIF বা WebP ছবি দেওয়া যাবে।",
    "Type DELETE to confirm account deletion.": "অ্যাকাউন্ট মুছতে নিশ্চিত করার জন্য DELETE লিখুন।",
    # titles & subtitles
    "Crop Disease Detection": "ফসলের রোগ নির্ণয়",
    "Describe symptoms to identify diseases and get treatment advice.": "লক্ষণ লিখে রোগ শনাক্ত করুন এবং প্রতিকারের পরামর্শ নিন।",
    "Farm Expense Tracker": "খামারের আয়-ব্যয় ট্র্যাকার",
    "Track income, expenses & profit-loss per farm": "প্রতিটি খামারের আয়, ব্যয় ও লাভ-ক্ষতির হিসাব রাখুন",
    "Net Profit": "নিট লাভ",
    "Add, edit, delete and monitor all your farms.": "আপনার সব খামার যোগ, সম্পাদনা, মুছে ফেলা ও পর্যবেক্ষণ করুন।",
    "Calculate N-P-K requirements. Results are saved and editable.": "এন-পি-কে (NPK) সারের পরিমাণ হিসাব করুন। ফলাফল সংরক্ষিত থাকে এবং পরে সম্পাদনা করা যায়।",
    "Irrigation / Water Log": "সেচ / পানি ব্যবহার লগ",
    "Track water usage and get weather-based irrigation advice": "পানির ব্যবহার ট্র্যাক করুন এবং আবহাওয়া অনুযায়ী সেচের পরামর্শ নিন",
    "Market Price Tracker": "বাজার দর ট্র্যাকার",
    "Add, edit, delete observations per farm.": "প্রতিটি খামারের পর্যবেক্ষণ যোগ, সম্পাদনা ও মুছে ফেলুন।",
    "Crop Calendar ": "ফসল ক্যালেন্ডার",
    # farm notes tips
    "Harvest": "ফসল তোলা",
    "Water in the morning": "সকালে পানি দিন",
    "Reduces evaporation and prevents fungal disease.": "বাষ্পীভবন কমায় এবং ছত্রাকজনিত রোগ প্রতিরোধ করে।",
    "Soil test before fertilizing": "সার দেওয়ার আগে মাটি পরীক্ষা করুন",
    "Know your pH before applying any fertilizer.": "যেকোনো সার প্রয়োগের আগে মাটির পিএইচ জেনে নিন।",
    "Use IPM": "সমন্বিত বালাই ব্যবস্থাপনা (আইপিএম) মানুন",
    "Natural predators first, chemicals last.": "আগে প্রাকৃতিক শত্রু পোকা, রাসায়নিক সবশেষে।",
    "Crop rotation": "ফসলের পালাক্রম",
    "Breaks pest cycles and restores soil nutrients.": "পোকামাকড়ের জীবনচক্র ভাঙে এবং মাটির পুষ্টি ফিরিয়ে আনে।",
    "Check sun exposure": "রোদের পরিমাণ দেখুন",
    "Most crops need 6–8 hours of direct sunlight.": "বেশিরভাগ ফসলের প্রতিদিন ৬–৮ ঘণ্টা সরাসরি রোদ দরকার।",
    "Mulch your beds": "জমির বেডে মালচিং করুন",
    "5 cm of mulch retains moisture and suppresses weeds.": "৫ সেমি পুরু মালচ আর্দ্রতা ধরে রাখে এবং আগাছা দমন করে।",
    "Harden seedlings": "চারা শক্ত করে নিন",
    "7–10 days outdoor exposure before transplanting.": "রোপণের আগে ৭–১০ দিন খোলা জায়গায় রাখুন।",
    # weather
    "Wind Speed": "বাতাসের গতি", "Feels Like": "অনুভূত তাপমাত্রা", "Feels like": "অনুভূত তাপমাত্রা",
    "— Set": "— সেট করুন", "for live data.": "লাইভ তথ্য পেতে।", "Free key →": "বিনামূল্যে কী →",
    "Add irrigation logs and expense records to see real charts here instead of empty graphs.":
        "সেচ লগ ও খরচের হিসাব যোগ করলে এখানে আপনার নিজের তথ্যের চার্ট দেখা যাবে।",
    # profile
    "Click to upload photo": "ছবি আপলোড করতে ক্লিক করুন", "Click to view photo": "ছবি দেখতে ক্লিক করুন",
    "👋 Welcome back,": "👋 স্বাগতম,", "Welcome back,": "স্বাগতম,",
    # cities
    "Chittagong": "চট্টগ্রাম", "Dhaka": "ঢাকা", "Sylhet": "সিলেট", "Barishal": "বরিশাল", "Barisal": "বরিশাল",
    "Rajshahi": "রাজশাহী", "Khulna": "খুলনা", "Rangpur": "রংপুর", "Mymensingh": "ময়মনসিংহ",
    "Cox's Bazar": "কক্সবাজার", "Comilla": "কুমিল্লা", "Cumilla": "কুমিল্লা", "Gazipur": "গাজীপুর",
    "Narayanganj": "নারায়ণগঞ্জ", "Bogura": "বগুড়া", "Bogra": "বগুড়া", "Jessore": "যশোর", "Jashore": "যশোর",
    "Dinajpur": "দিনাজপুর", "Tangail": "টাঙ্গাইল", "Pabna": "পাবনা", "Faridpur": "ফরিদপুর",
    "Noakhali": "নোয়াখালী", "Feni": "ফেনী", "Kushtia": "কুষ্টিয়া", "Bangladesh": "বাংলাদেশ",
    # landing page
    "Live stats — total farms, crop varieties, area, weather snapshot and recent activity all in one view.":
        "এক নজরে সব তথ্য — মোট খামার, ফসলের ধরন, জমির পরিমাণ, আজকের আবহাওয়া ও সাম্প্রতিক কাজ।",
    "Add, edit, delete farms. Full crop monitor with growth stage, water level, soil moisture progress bars.":
        "খামার যোগ, সম্পাদনা ও মুছুন। ফসলের বৃদ্ধির ধাপ, পানির পরিমাণ ও মাটির আর্দ্রতা এক জায়গায় দেখুন।",
    "CRUD": "সহজ ব্যবস্থাপনা", "Live Weather": "সরাসরি আবহাওয়া",
    "Real OpenWeather API integration with 7-day forecast, farming advice and city search.":
        "৭ দিনের পূর্বাভাস, কৃষি পরামর্শ ও শহর অনুযায়ী আবহাওয়া খুঁজুন।",
    "API": "সরাসরি", "Charts": "চার্ট",
    "4 interactive Chart.js charts — farm areas, water usage, harvest trends, crop distribution doughnut.":
        "৪টি চার্টে দেখুন খামারের জমি, পানির ব্যবহার, ফসল তোলার ধারা ও ফসলের বণ্টন।",
    "N-P-K calculator with results that save to your account — edit and delete old calculations anytime.":
        "এন-পি-কে সারের হিসাব করুন। ফলাফল আপনার অ্যাকাউন্টে জমা থাকে — যেকোনো সময় সম্পাদনা বা মুছতে পারবেন।",
    "Saved": "সংরক্ষিত",
    "6-category farm log — add observations per farm, edit and delete notes with live search filter.":
        "৬টি বিভাগে খামারের নোট রাখুন — প্রতিটি খামারের পর্যবেক্ষণ যোগ করুন এবং খুঁজে নিন।",
    "Editable": "সম্পাদনাযোগ্য", "Irrigation Planner": "সেচ পরিকল্পনা",
    "Smart per-crop watering reminders with urgency alerts and water requirement calculations.":
        "প্রতিটি ফসলের জন্য সেচের স্মার্ট রিমাইন্ডার ও পানির প্রয়োজনের হিসাব।",
    "Smart": "স্মার্ট", "User Auth": "নিরাপদ অ্যাকাউন্ট",
    "Secure register, login, logout. Password hashing. Each user sees only their own farms and data.":
        "নিরাপদ নিবন্ধন ও লগইন। পাসওয়ার্ড এনক্রিপ্টেড থাকে এবং প্রত্যেকে শুধু নিজের খামার ও তথ্য দেখতে পায়।",
})
BN_PATTERNS.extend([
    ("Google login failed: {n}", "গুগল লগইন ব্যর্থ হয়েছে: {n}"),
    ("✅ Logged in with Google as {n}.", "✅ গুগল দিয়ে {n} হিসেবে লগইন হয়েছে।"),
    ("{n} registered", "{n}টি নিবন্ধিত"),
    ("{n} Temp", "{n}-এর তাপমাত্রা"),
    ("Weather — {n}", "আবহাওয়া — {n}"),
    ("{n}, BD", "{n}, বাংলাদেশ"),
    ("Live conditions for {n}, BD — updated {m}", "{n}, বাংলাদেশ-এর বর্তমান অবস্থা — আপডেট: {m}"),
    ("Bangladesh crop market prices & selling advice — updated {n}", "বাংলাদেশের ফসলের বাজার দর ও বিক্রির পরামর্শ — আপডেট: {n}"),
    ("Printable farm summary — {n}", "প্রিন্টযোগ্য খামার সারসংক্ষেপ — {n}"),
    ("Email: {n}", "ইমেইল: {n}"),
    ("including {n} farm(s), {m} note(s), and {k} calculation(s).", "এর মধ্যে রয়েছে {n}টি খামার, {m}টি নোট এবং {k}টি হিসাব।"),
    ("Calm conditions ({n} km/h) — ideal for fertilizer or pesticide spraying operations.",
     "শান্ত আবহাওয়া ({n} কিমি/ঘণ্টা) — সার বা কীটনাশক স্প্রে করার জন্য উপযুক্ত।"),
    ("Optimal growing temperature ({n}°C) — great day for transplanting, harvesting and fieldwork.",
     "ফসলের জন্য আদর্শ তাপমাত্রা ({n}°সে) — চারা রোপণ, ফসল তোলা ও মাঠের কাজের জন্য ভালো দিন।"),
    ("Clear sky ({n}%) — full sunlight available. Ideal for solar-powered irrigation systems.",
     "পরিষ্কার আকাশ ({n}%) — পূর্ণ রোদ পাওয়া যাবে। সৌরশক্তিচালিত সেচের জন্য উপযুক্ত।"),
])

_WS = re.compile(r"\s+")
_SCRIPT_STYLE = re.compile(r"(<script\b.*?</script>|<style\b.*?</style>)", re.S | re.I)
_TEXT = re.compile(r">([^<>]+)<")
_ATTR = re.compile(r'(\b(?:placeholder|title|aria-label|alt|data-tip)=")([^"]*)(")')
_TITLE_TAG = re.compile(r"(<title>)([^<]*)(</title>)", re.I)


def _compile_patterns(pairs):
    out = []
    for en, bn in pairs:
        rx = re.escape(en)
        rx = (rx.replace(r"\{n\}", r"(?P<n>.+?)").replace(r"\{m\}", r"(?P<m>.+?)")
                .replace(r"\{k\}", r"(?P<k>.+?)"))
        out.append((re.compile("^" + rx + "$"), bn))
    return out


_BN_PAT = _compile_patterns(BN_PATTERNS)


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_EMOJI_LEAD = re.compile(r"^([^\w\u0980-\u09FF(]+)(\S.*)$")
_BN_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")
_MONTHS = {"jan": "জানুয়ারি", "feb": "ফেব্রুয়ারি", "mar": "মার্চ", "apr": "এপ্রিল", "may": "মে",
           "jun": "জুন", "jul": "জুলাই", "aug": "আগস্ট", "sep": "সেপ্টেম্বর", "oct": "অক্টোবর",
           "nov": "নভেম্বর", "dec": "ডিসেম্বর"}
_DAYS = {"mon": "সোম", "tue": "মঙ্গল", "wed": "বুধ", "thu": "বৃহস্পতি", "fri": "শুক্র",
         "sat": "শনি", "sun": "রবি"}
_DATE_RX = re.compile(
    r"^(?:(Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,? )?(\d{1,2}) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* "
    r"(\d{4})(?:,? (\d{1,2}:\d{2})(?::\d{2})? ?(AM|PM)?)?$")


def _bn_date(text):
    """'Tue, 10 Nov 2026, 12:29 PM' -> 'মঙ্গল, ১০ নভেম্বর ২০২৬, ১২:২৯ অপরাহ্ণ'. None if not a date."""
    m = _DATE_RX.match(text)
    if not m:
        return None
    day, d, mon, y, hm, ap = m.groups()
    out = (_DAYS[day.lower()] + ", " if day else "") + f"{d} {_MONTHS[mon.lower()]} {y}"
    if hm:
        out += ", " + hm + ({"AM": " পূর্বাহ্ণ", "PM": " অপরাহ্ণ"}.get(ap, "") if ap else "")
    return out.translate(_BN_DIGITS)


def _part(value, table):
    """Translate a captured fragment (a city, a date, a known phrase) if we can."""
    v = _html.unescape(value).strip()
    if table is BN and re.fullmatch(r"[\d.,]+", v):
        return v.translate(_BN_DIGITS)
    return table.get(v) or (_bn_date(v) if table is BN else None) or value


def _lookup(core, table, patterns=(), _depth=0):
    """Return the replacement for `core` (already normalised) or None."""
    if core in table:
        return table[core]
    plain = _html.unescape(core)
    if plain in table:
        return table[plain]
    if table is BN:
        d = _bn_date(plain)
        if d:
            return d
    for rx, tpl in patterns:
        m = rx.match(plain)
        if m:
            return tpl.format(**{k: _part(v, table) for k, v in m.groupdict().items()})
    # "📅 Crop Calendar" -> keep the emoji / symbol, translate the words
    if _depth == 0:
        m = _EMOJI_LEAD.match(plain)
        if m:
            rest = _lookup(m.group(2), table, patterns, 1)
            if rest is not None:
                return m.group(1) + rest
    return None


def _swap_text(raw, table, patterns, escape):
    core = _WS.sub(" ", raw).strip()
    if not core:
        return raw
    rep = _lookup(core, table, patterns)
    if rep is None:
        return raw
    lead = raw[: len(raw) - len(raw.lstrip())]
    trail = raw[len(raw.rstrip()):]
    return lead + (_esc(rep) if escape else rep) + trail


def _apply(html_text, table, patterns, js_table):
    parts = _SCRIPT_STYLE.split(html_text)
    out = []
    for part in parts:
        low = part[:7].lower()
        if low.startswith("<script"):
            for en, tr in js_table.items():
                if en in part:
                    part = part.replace(en, tr)
            out.append(part)
            continue
        if low.startswith("<style"):
            out.append(part)
            continue
        part = _TEXT.sub(lambda m: ">" + _swap_text(m.group(1), table, patterns, True) + "<", part)
        part = _ATTR.sub(
            lambda m: m.group(1) + _swap_text(m.group(2), table, patterns, True) + m.group(3), part
        )
        part = _TITLE_TAG.sub(
            lambda m: m.group(1) + _swap_text(m.group(2), table, patterns, True) + m.group(3), part
        )
        out.append(part)
    return "".join(out)


def translate_html(html_text):
    """English page -> Bangla page."""
    return _apply(html_text, BN, _BN_PAT, BN_JS)


def polish_html(html_text):
    """English page -> refined English page."""
    return _apply(html_text, EN_POLISH, (), {})

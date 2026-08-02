import os, requests, json, re, hashlib, random
from bs4 import BeautifulSoup

TOKEN = os.getenv("TELEGRAM_TOKEN","").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID","").strip()
SENT_FILE = "sent.json"
FACTORIES_FILE = "factories_300.json"

PRIORITIES = {
    "1-تجهيزات مكتبية": ["mobilier", "meuble", "bureau", "chaise", "table", "armoire", "fourniture de bureau", "papier", "imprimante", "ordinateur", "climatiseur", "rayonnage"],
    "2-ترصيص وتدفئة": ["plomberie", "sanitaire", "chauffage", "chaudiere", "ppr", "per", "robinet", "pompe", "tuyau", "chauffe eau", "radiateur", "vanne", "raccord"],
    "3-كهرباء": ["electricite", "cable", "disjoncteur", "transformateur", "eclairage", "led", "armoire electrique", "groupe electrogene", "onduleur", "parafoudre"],
    "4-قطع غيار": ["piece de rechange", "pneu", "batterie", "filtre", "frein", "camion", "bus", "vehicule", "huile moteur", "courroie", "moteur", "boite vitesse"]
}

def load_factories():
    try:
        with open(FACTORIES_FILE,"r",encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

def load_sent():
    try:
        with open(SENT_FILE,"r",encoding="utf-8") as f: return set(json.load(f))
    except: return set()

def save_sent(s):
    with open(SENT_FILE,"w",encoding="utf-8") as f: json.dump(list(s), f, ensure_ascii=False)

def send(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": text, "parse_mode":"HTML", "disable_web_page_preview": False}
    requests.post(url, data=data, timeout=30)

def get_priority(title):
    tl = title.lower()
    for prio_name, kws in PRIORITIES.items():
        if any(k in tl for k in kws):
            return prio_name
    return None

# فلتر صارم جدا - من 2026 فقط
def is_recent_2026_strict(txt, anep=""):
    tl = txt.lower()
    # 1. إذا فيها أي سنة قديمة مباشرة، احذفها
    if "2023" in tl or "2024" in tl:
        return False
    # 2. فلتر 2025 - بأي شكل: 2025, /2025, 16/2025, N°16/2025
    if "2025" in tl:
        return False
    # 3. فلتر ANEP - ANEP 24xxxxx = 2024, 25xxxxx = 2025
    if anep != "N/A" and anep != "":
        # ANEP يبدأ ب 24 أو 25 = قديم
        if anep.startswith("24") or anep.startswith("25") or anep.startswith("23"):
            return False
        # ANEP يبدأ ب 2525xxx أو 2524xxx = 2025
        if len(anep) >= 4:
            try:
                # ANEP مثل 2525008932 - الرقمين الثاني والثالث هما السنة
                # 2525 = 2025
                year_part = anep[2:4] if anep.startswith("25") else ""
                if year_part == "25" or year_part == "24" or year_part == "23":
                    return False
            except: pass
    # 4. يجب أن تحتوي على 2026 أو 2027 للسماح (أو ANEP يبدأ ب 26)
    has_2026 = "2026" in tl or "2027" in tl
    has_anep_26 = anep.startswith("26") or anep.startswith("2526") or anep.startswith("2625")
    # إذا لا يوجد 2026 ولا ANEP 26، تجاهلها (لتجنب المناقصات بدون تاريخ قديمة)
    if not has_2026 and not has_anep_26:
        # نسمح فقط إذا النص لا يحتوي أي سنة قديمة وطويل بما يكفي (قد تكون جديدة بدون ذكر السنة)
        # لكن لتكون صارم، نطلب 2026
        return False
    return True

def extract_wilaya(txt):
    m = re.search(r"Wilaya (?:de|d')\s+([A-Za-zÀ-ÿ\- ]+)", txt, re.I)
    return m.group(1).strip()[:30] if m else "Algérie"

def find_factories_for_tender(all_factories, prio_short, wilaya, limit=3):
    candidates = [f for f in all_factories if prio_short in f["priority"]]
    same_wilaya = [f for f in candidates if f["wilaya"].lower() == wilaya.lower()]
    if len(same_wilaya) >= limit:
        return random.sample(same_wilaya, limit)
    others = [f for f in candidates if f["wilaya"].lower()!= wilaya.lower()]
    result = same_wilaya + random.sample(others, min(limit-len(same_wilaya), len(others))) if others else same_wilaya
    return result[:limit]

def fetch_bomop_real_2026():
    tenders = []
    headers = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    sectors = ["industrie","autres","tic","btph","equipements-industriels","transport","energie","hydraulique","habitat","sante","education"]
    for sector in sectors:
        try:
            url = f"https://bomop.anep.dz/secteur/{sector}/"
            r = requests.get(url, headers=headers, timeout=25)
            if r.status_code!= 200: continue
            soup = BeautifulSoup(r.text, "lxml")
            for el in soup.find_all(['article'], limit=80):
                txt = el.get_text(" ", strip=True)
                if len(txt) < 50: continue
                anep_m = re.search(r"ANEP\s*([0-9]+)", txt, re.I)
                anep = anep_m.group(1) if anep_m else "N/A"
                # فلتر التاريخ الصارم مع ANEP
                if not is_recent_2026_strict(txt, anep):
                    continue
                prio = get_priority(txt)
                if not prio: continue
                wilaya = extract_wilaya(txt)
                comp_m = re.search(r"(AADL|ANESRIF|SNTF|COSIDER|SONATRACH|SONELGAZ|NAFTAL|GICA|ENPC|ENICAB|SNVI|ADE|ONA|POSTE|TDA|EPTV|ENIE|CHIALI)", txt, re.I)
                company = comp_m.group(1).upper() if comp_m else "EPIC/EPE"
                link_tag = el.find("a")
                link = link_tag["href"] if link_tag and link_tag.get("href") else url
                tid = hashlib.md5((anep+txt[:100]+prio).encode()).hexdigest()
                tenders.append({
                    "id": tid, "title": txt[:500], "anep": anep, "wilaya": wilaya,
                    "link": link, "prio": prio, "sector": sector, "company": company
                })
        except Exception as e:
            print(f"sector {sector} error: {e}")
    return tenders

print("🚀 البوت الكامل - فلتر صارم 2026+ فقط - 68 شركة + 300 مصنع + 4 أولويات")
factories = load_factories()
print(f"تم تحميل {len(factories)} مصنع")
sent = load_sent()
all_tenders = fetch_bomop_real_2026()
print(f"وجدت {len(all_tenders)} مناقصة جديدة من 2026 فقط تطابق أولوياتك")
new_tenders = [t for t in all_tenders if t["id"] not in sent]

if not new_tenders:
    print("✅ لا يوجد مناقصات جديدة من 2026 اليوم - البوت يعمل ويفحص كل 30 دقيقة")
else:
    for t in new_tenders[:5]:
        prio_short = t["prio"].split("-")[1]
        matched_factories = find_factories_for_tender(factories, prio_short, t["wilaya"], limit=3)
        factories_text = ""
        for i, f in enumerate(matched_factories, 1):
            factories_text += f"{i}. 🏭 <b>{f['name']}</b>\n   📦 {f['product']} | 📞 {f['phone']}\n   📍 <a href=\"{f['map']}\">موقعه على الخريطة</a> | {'✅ مصنع مباشر' if f.get('is_direct_factory') else ''}\n"
        map_wilaya = f"https://www.google.com/maps/search/?api=1&query=Direction+{t['company']}+Wilaya+{t['wilaya']}"
        factory_search_map = f"https://www.google.com/maps/search/?api=1&query=Usine+{prio_short}+{t['wilaya']}+Algérie"
        msg = f"""🔔 <b>مناقصة حقيقية 2026 - {t['prio']}</b> 🔔

🏢 <b>الشركة:</b> {t['company']} ({t['sector']})
📍 <b>الولاية:</b> {t['wilaya']} | ANEP: {t['anep']}
📋 <b>الموضوع:</b> {t['title']}

📄 <a href="{t['link']}">فتح الإعلان الأصلي BOMOP 2026</a>
🗺️ <a href="{map_wilaya}">موقع الشركة على Google Maps</a>
🔍 <a href="{factory_search_map}">مصانع {prio_short} في {t['wilaya']} على Maps</a>

🏭 <b>أقرب 3 مصانع جزائرية مباشرة:</b>
{factories_text}
#2026 #EPIC_EPE #BOMOP
"""
        send(msg)
        sent.add(t["id"])
    save_sent(sent)
    print(f"✅ أرسلت {len(new_tenders[:5])} مناقصات 2026 حقيقية")
    

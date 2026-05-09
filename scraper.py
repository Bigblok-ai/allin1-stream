import requests
import json
import os
import copy
import re
from concurrent.futures import ThreadPoolExecutor

# ==========================================
# CONFIG
# ==========================================
CATEGORIES = {
    "Bóng đá": "⚽ Bóng Đá",
    "Tennis": "🎾 Tennis",
    "Cầu Lông": "🏸 Cầu Lông",
    "Bóng rổ": "🏀 Bóng Rổ",
    "Billiards": "🎱 Billiards",
    "Bóng chuyền": "🏐 Bóng Chuyền",
    "Đua xe F1": "🏎️ Đua Xe F1",
    "Bóng bàn": "🏓 Bóng Bàn",
    "Võ Thuật": "🥊 Võ Thuật",
    "Pickleball": "🏸 Pickleball"
}

SOURCES = [
    {"name": "Thapcam24h", "url": "https://raw.githubusercontent.com/Bigblok-ai/bigscraper/refs/heads/main/output.json"},
    {"name": "Cakhia247", "url": "https://raw.githubusercontent.com/jasminliu98/cakhia-stream/refs/heads/main/output.json"},
    {"name": "Buncha", "url": "https://raw.githubusercontent.com/xixixius-ai/buncha-stream/refs/heads/main/output.json"},
    {"name": "Giovang", "url": "https://raw.githubusercontent.com/jasminliu98/giovang-stream/refs/heads/main/output.json"},
    {"name": "Hoiquan", "url": "https://raw.githubusercontent.com/jasminliu98/hoiquan-stream/refs/heads/main/output.json"}
]

HOIQUAN_FILE = "hoiquan.json"

GROUP_SKELETON = [
    {"id": f"grp-{cate_raw.replace(' ', '-').lower()}", "name": cate_emoji, "display": "vertical", "grid_number": 2, "enable_detail": False, "channels": []}
    for cate_raw, cate_emoji in CATEGORIES.items()
]

# ==========================================
# HELPER FUNCTIONS
# ==========================================
def normalize(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return json.dumps(data, ensure_ascii=False, sort_keys=True)

def fetch_json(url):
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        return response.json()
    except Exception:
        return None

def normalize_cate_name(name):
    """Bỏ suffix '(X LIVE)' khỏi tên group"""
    return re.sub(r'\s*\(\d+\s+\w+\)\s*$', '', name, flags=re.IGNORECASE).strip()

def normalize_time_in_channel(channel):
    """Normalize GiovangTV time format: 'HH:MM:SS' + date → 'HH:MM DD/MM'"""
    meta = channel.get("org_metadata", {})
    time_val = meta.get("time", "").strip()
    date_val = meta.get("date", "").strip()
    
    if time_val and date_val:
        parts = time_val.split(":")
        if len(parts) == 3:
            meta["time"] = f"{parts[0]}:{parts[1]} {date_val}"
    
    return channel

def normalize_team_name(name):
    """Normalize team name for fuzzy matching"""
    name = name.strip().lower()
    # Remove common club suffixes
    suffixes = [
        " football club", " f.c.", " fc", " cf", " sc", " ac", " afc",
        " s.c.", " a.f.c.", " c.d.", " cd", " b", " a", " sv", " e.v.",
        " club", " de fútbol", " futebol"
    ]
    for suffix in suffixes:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    # Normalize whitespace
    name = " ".join(name.split())
    return name

def teams_match(team_a, team_b, old_a, old_b):
    """Check if two sets of teams refer to the same match"""
    a_clean = team_a.strip().lower()
    b_clean = team_b.strip().lower() if team_b else ""
    old_a_clean = old_a.strip().lower()
    old_b_clean = old_b.strip().lower() if old_b else ""
    
    # Exact match
    a_match = False
    b_match = False
    
    if a_clean:
        if a_clean == old_a_clean or a_clean == old_b_clean:
            a_match = True
    
    if b_clean:
        if b_clean == old_a_clean or b_clean == old_b_clean:
            b_match = True
    
    # If both teams match exactly
    if a_match and (not b_clean or b_match):
        return True
    if b_match and (not a_clean or a_match):
        return True
    
    # Normalized match (remove FC, AFC, etc.)
    a_norm = normalize_team_name(team_a)
    b_norm = normalize_team_name(team_b) if team_b else ""
    old_a_norm = normalize_team_name(old_a)
    old_b_norm = normalize_team_name(old_b) if old_b else ""
    
    a_norm_match = False
    b_norm_match = False
    
    if a_norm:
        if a_norm == old_a_norm or a_norm == old_b_norm:
            a_norm_match = True
    
    if b_norm:
        if b_norm == old_a_norm or b_norm == old_b_norm:
            b_norm_match = True
    
    if a_norm_match and (not b_norm or b_norm_match):
        return True
    if b_norm_match and (not a_norm or a_norm_match):
        return True
    
    # Substring match (e.g., "Chelsea" in "Chelsea FC", "Brighton" in "Brighton Hove Albion")
    if a_clean and not a_match and not a_norm_match:
        if (a_clean in old_a_clean or old_a_clean in a_clean) and len(a_clean) >= 4:
            a_match = True
        if (a_clean in old_b_clean or old_b_clean in a_clean) and len(a_clean) >= 4:
            a_match = True
    
    if b_clean and not b_match and not b_norm_match:
        if (b_clean in old_a_clean or old_a_clean in b_clean) and len(b_clean) >= 4:
            b_match = True
        if (b_clean in old_b_clean or old_b_clean in b_clean) and len(b_clean) >= 4:
            b_match = True
    
    if a_match and (not b_clean or b_match):
        return True
    if b_match and (not a_clean or a_match):
        return True
    
    return False

def extract_sort_key(channel):
    """LIVE lên đầu, sau đó sort theo thời gian tăng dần (HH:MM DD/MM)"""
    meta = channel.get("org_metadata", {})
    is_live = meta.get("is_live", False)
    time_val = meta.get("time", "").strip()

    if is_live or not time_val:
        return (0, 0, 0, 0, 0)

    try:
        parts = time_val.split(" ")
        if len(parts) == 2:
            hm = parts[0].split(":")
            dm = parts[1].split("/")
            h = int(hm[0])
            m = int(hm[1])
            d = int(dm[0])
            mo = int(dm[1])
            return (1, mo, d, h, m)
        elif len(parts) == 1 and ":" in parts[0]:
            # Fallback for "HH:MM:SS" or "HH:MM"
            hm = parts[0].split(":")
            h = int(hm[0])
            m = int(hm[1])
            return (1, 99, 99, h, m)
    except:
        pass

    return (2, 99, 99, 99, 99)

def find_channel_index(time_val, team_a, team_b, channels_list):
    """Tìm trận trùng khớp dựa trên thời gian và tên đội"""
    time_clean = time_val.strip().lower()

    for i, ch in enumerate(channels_list):
        meta = ch.get("org_metadata", {})
        old_time = meta.get("time", "").strip().lower()
        old_a = meta.get("team_a", "")
        old_b = meta.get("team_b", "")

        # Time matching:
        # - Both have same time → OK
        # - Both empty (both LIVE) → OK
        # - One empty (LIVE), other has time → OK (same match, different status)
        time_match = False
        
        if time_clean == old_time:
            time_match = True
        elif time_clean == "" or old_time == "":
            # One is LIVE, other has scheduled time → allow match
            time_match = True
        
        if not time_match:
            continue

        # Team matching with fuzzy logic
        if teams_match(team_a, team_b, old_a, old_b):
            return i

    return -1

# ==========================================
# LOGIC KÊNH TRUYỀN HÌNH
# ==========================================
def convert_ch(ch, i):
    return {
        "id": f"tv-{i}",
        "name": ch["name"],
        "type": "single",
        "display": "thumbnail-only",
        "enable_detail": False,
        "labels": [
            {"text": "● LIVE", "position": "top-left", "color": "#00000080", "text_color": "#ff4444"}
        ],
        "sources": [
            {
                "id": f"src-tv-{i}",
                "name": "TV Channel",
                "contents": [
                    {
                        "id": f"ct-tv-{i}",
                        "name": ch["name"],
                        "streams": [
                            {
                                "id": f"st-tv-{i}",
                                "name": "KT",
                                "stream_links": [
                                    {
                                        "id": f"lnk-tv-{i}",
                                        "name": "Link 1",
                                        "type": "hls",
                                        "default": True,
                                        "url": ch["url"],
                                        "request_headers": []
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ],
        "org_metadata": {
            "is_live": True,
            "time": "",
            "team_a": ch["name"],
            "team_b": ""
        },
        "image": {
            "padding": 1,
            "background_color": "#ffffff",
            "display": "contain",
            "url": ch.get("logo", ""),
            "width": 1600,
            "height": 1200
        }
    }

# ==========================================
# MAIN LOGIC
# ==========================================
def main():
    final_data = {
        "id": "allin1-stream",
        "name": "All In 1 Stream",
        "version": "V1.0",
        "description": "⚽ Bóng Đá, 🎾 Tennis, 🏸 Cầu Lông, 🏀 Bóng Rổ, 🎱 Billiards, 🏐 Bóng Chuyền, 🏎️ Đua Xe F1, 🏓 Bóng Bàn, 🥊 Võ Thuật, 🏸 Pickleball",
        "image": {
            "type": "cover",
            "url": "https://github.com/Bigblok-ai/allin1-stream/blob/main/logo.png"
        },
        "groups": copy.deepcopy(GROUP_SKELETON)
    }

    group_map = {}
    for g in final_data["groups"]:
        base_name = normalize_cate_name(g["name"])
        group_map[base_name] = g

    with ThreadPoolExecutor(max_workers=5) as executor:
        raw_jsons = list(executor.map(fetch_json, [s["url"] for s in SOURCES]))

    # ==========================================
    # BƯỚC 1: GỘP DỮ LIỆU TỪ 5 NGUỒN
    # ==========================================
    for index, raw_data in enumerate(raw_jsons):
        if not raw_data: continue
        source_name = SOURCES[index]["name"]

        for src_group in raw_data.get("groups", []):
            src_cate_name = normalize_cate_name(src_group.get("name", ""))
            if src_cate_name not in group_map: continue
            target_group = group_map[src_cate_name]

            for src_channel in src_group.get("channels", []):
                # Normalize GiovangTV time format FIRST
                src_channel = normalize_time_in_channel(src_channel)
                
                meta = src_channel.get("org_metadata", {})
                time_val = meta.get("time", "")
                team_a = meta.get("team_a", "")
                team_b = meta.get("team_b", "")
                blv_val = meta.get("blv", "")
                thumb_url = src_channel.get("image", {}).get("url", "")

                if not team_a: continue

                ch_idx = find_channel_index(time_val, team_a, team_b, target_group["channels"])

                if ch_idx == -1:
                    new_channel = copy.deepcopy(src_channel)
                    target_group["channels"].append(new_channel)
                else:
                    existing_channel = target_group["channels"][ch_idx]
                    
                    # Thumbnail: First wins
                    if thumb_url and not existing_channel["image"].get("url"):
                        existing_channel["image"]["url"] = thumb_url

                    # Update is_live if new source is LIVE
                    if meta.get("is_live"):
                        existing_channel["org_metadata"]["is_live"] = True
                        # If LIVE, also update label
                        for label in existing_channel.get("labels", []):
                            if label.get("text") == "🕐 Sắp":
                                label["text"] = "● LIVE"
                                label["text_color"] = "#ff4444"

                    existing_urls = set()
                    for ex_src in existing_channel.get("sources", []):
                        for ex_ct in ex_src.get("contents", []):
                            for ex_st in ex_ct.get("streams", []):
                                for link in ex_st.get("stream_links", []):
                                    if "url" in link:
                                        existing_urls.add(link["url"])

                    for inc_src in src_channel.get("sources", []):
                        has_new_link = False
                        temp_src = copy.deepcopy(inc_src)

                        for inc_ct in temp_src.get("contents", []):
                            for inc_st in inc_ct.get("streams", []):
                                new_valid_links = []
                                for link in inc_st.get("stream_links", []):
                                    link_url = link.get("url", "")
                                    if link_url and link_url not in existing_urls:
                                        new_valid_links.append(link)
                                        existing_urls.add(link_url)
                                        has_new_link = True

                                if new_valid_links:
                                    inc_st["stream_links"] = new_valid_links
                                    inc_st["name"] = f"{source_name} - {blv_val}".strip(" -")
                                else:
                                    inc_st["stream_links"] = []

                        if has_new_link:
                            existing_channel["sources"].append(temp_src)

    # ─────────────────────────────────────────────────────────────────
    # BƯỚC 2: GỘP KÊNH TRUYỀN HÌNH
    # ─────────────────────────────────────────────────────────────────
    try:
        if os.path.exists(HOIQUAN_FILE):
            with open(HOIQUAN_FILE, "r", encoding="utf-8") as f:
                tv_list = json.load(f)
            if tv_list:
                tv_group = {
                    "id": "grp-tv-hoiquan",
                    "name": "📺 Kênh Truyền Hình",
                    "display": "vertical",
                    "grid_number": 2,
                    "enable_detail": False,
                    "channels": [convert_ch(ch, i) for i, ch in enumerate(tv_list)]
                }
                final_data["groups"].insert(0, tv_group)
                print(f"Da gom {len(tv_list)} kenh truyen hinh vao output.")
        else:
            print(f"Canh bao: Khong tim thay file {HOIQUAN_FILE}.")
    except Exception as e:
        print(f"Canh bao: Loi xu ly {HOIQUAN_FILE} -> {e}")

    # ==========================================
    # BƯỚC 3: SẮP XẾP & ĐẾM LIVE
    # ==========================================
    for g in final_data["groups"]:
        g["channels"].sort(key=extract_sort_key)

        base_name = normalize_cate_name(g["name"])
        live_count = 0
        for ch in g.get("channels", []):
            meta = ch.get("org_metadata", {})
            if meta.get("is_live") == True or meta.get("time", "").strip() == "":
                live_count += 1
        
        if live_count > 0:
            g["name"] = f"{base_name} ({live_count} LIVE)"
        else:
            g["name"] = base_name

    # ==========================================
    # LOGIC SO SÁNH & GHI FILE
    # ==========================================
    staging = "staging.json"
    with open(staging, "w", encoding="utf-8") as f:
        json.dump(final_data, f, ensure_ascii=False, indent=2)

    if os.path.exists("output.json"):
        old_norm = normalize("output.json")
        new_norm = normalize(staging)

        if old_norm != new_norm:
            os.replace(staging, "output.json")
            total_ch = sum(len(g["channels"]) for g in final_data["groups"])
            active_grp = sum(1 for g in final_data["groups"] if len(g["channels"]) > 0)
            print(f"\nXong! {total_ch} kenh, {active_grp} nhom -> output.json (DA CAP NHAT)")
        else:
            os.remove(staging)
            print(f"\nXong! -> Khong co thay doi, giu nguyen output.json")
    else:
        os.replace(staging, "output.json")
        print(f"\nXong! -> output.json (TAO MOI)")

if __name__ == "__main__":
    main()

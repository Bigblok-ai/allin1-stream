import requests
import json
import os
import copy
import re
import unicodedata
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
# BẢNG DỊCH TÊN TIẾNG VIỆT ↔ TIẾNG ANH
# (sau khi bỏ dấu - key = không dấu, value = canonical)
# ==========================================
VI_EN_MAP = {
    # Quốc gia
    "duc": "germany",
    "nhat ban": "japan",
    "trung quoc": "china",
    "dai loan": "chinese taipei",
    "phap": "france",
    "han quoc": "south korea",
    "anh": "england",
    "y": "italy",
    "tay ban nha": "spain",
    "my": "united states",
    # Đội bóng V-League (các tên gọi khác nhau của cùng đội)
    "ha noi": "hanoi",
    "thanh hoa": "thanh hoa",
    "phu dong": "ninh binh",       # Phù Đổng = Ninh Bình
    "hai phong": "hai phong",
    "ninh binh": "ninh binh",
    # Võ thuật
    "chau la": "zhou luo",
    "ban van hoang": "ban van hoang",
    # Tên gọi tắt / biệt danh đội nước ngoài
    "wolves": "wolverhampton",
    "celta vigo": "celta vigo",
    "rc celta": "celta vigo",
    "espanyol": "espanyol",
    "rcd espanyol de barcelona": "espanyol",
    "bayer leverkusen": "bayer leverkusen",
    "bayer 04 leverkusen": "bayer leverkusen",
    "bayern munich": "bayern munich",
    "fc bayern munich": "bayern munich",
    "adelaide united fc": "adelaide united",
    "adelaide united": "adelaide united",
    "afc bournemouth": "bournemouth",
    "bournemouth afc": "bournemouth",
    "sevilla fc": "sevilla",
    "chelsea fc": "chelsea",
    "vfl wolfsburg": "wolfsburg",
    "wolfsburg": "wolfsburg",
    "xm hai phong fc": "hai phong",
    "brighton hove albion": "brighton",
    "wolverhampton wanderers": "wolverhampton",
    "manchester united": "manchester united",
    "inter milan": "inter milan",
    "fc inter milan": "inter milan",
}

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

def remove_diacritics(text):
    """Bỏ dấu tiếng Việt: 'Thanh Hóa' → 'Thanh Hoa'"""
    normalized = unicodedata.normalize('NFD', text)
    return ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')

# ──────────────────────────────────────────
# MỚI: Normalize thời gian cho so khớp
# ──────────────────────────────────────────
def normalize_time_for_match(time_val, date_val=""):
    """Chuẩn hóa mọi format thời gian → 'HH:MM DD/MM' hoặc '' (LIVE).
    
    Hỗ trợ:
      - ''           → ''
      - '14:00 09/05' → '14:00 09/05'
      - '14:00:00' + date='09/05' → '14:00 09/05'   (GiovangTV)
      - '14:00'     + date='09/05' → '14:00 09/05'
    """
    time_val = time_val.strip()
    date_val = date_val.strip()

    if not time_val:
        return ""

    # Đã đúng format "HH:MM DD/MM"
    if re.match(r'^\d{1,2}:\d{2}\s+\d{1,2}/\d{1,2}$', time_val):
        return time_val.lower()

    # Format "HH:MM:SS" (GiovangTV)
    parts = time_val.split(":")
    if len(parts) == 3:
        hh_mm = f"{parts[0]}:{parts[1]}"
        if date_val:
            return f"{hh_mm} {date_val}".lower()
        return hh_mm.lower()

    # Format "HH:MM" chưa có date
    if re.match(r'^\d{1,2}:\d{2}$', time_val):
        if date_val:
            return f"{time_val} {date_val}".lower()
        return time_val.lower()

    return time_val.lower()

# ──────────────────────────────────────────
# MỚI: Normalize tên đội cho so khớp
# ──────────────────────────────────────────
def normalize_team_for_match(name):
    """Chuẩn hóa tên đội → dạng canonical để so khớp.
    
    Quy trình:
      1. Strip + collapse whitespace
      2. Bỏ dấu tiếng Việt
      3. Lowercase
      4. Bỏ prefix (CLB, TTBD, …)
      5. Bỏ suffix (FC, AFC, …)
      6. Bỏ số đứng riêng (04, 1995, …)
      7. Tra bảng dịch VI_EN_MAP
    """
    if not name:
        return ""

    # 1. Strip + collapse whitespace
    name = " ".join(name.strip().split())

    # 2. Bỏ dấu tiếng Việt
    name = remove_diacritics(name)

    # 3. Lowercase
    name = name.lower()

    # 4. Bỏ prefix
    for prefix in ["clb ", "ttbd ", "dclb ", "sb "]:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break

    # 5. Bỏ suffix (thử nhiều lần để xử lý "Football Club" → "FC")
    for suffix in [
        " football club", " f.c.", " fc", " cf", " sc", " ac", " afc",
        " s.c.", " a.f.c.", " c.d.", " cd", " sv", " e.v.",
        " club", " de futbol", " futebol", " united club",
    ]:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
            break

    # 6. Bỏ số đứng riêng ("bayer 04 leverkusen" → "bayer leverkusen")
    name = re.sub(r'\b\d+\b', '', name)
    name = " ".join(name.split())

    # 7. Tra bảng dịch
    name_clean = name.strip()
    if name_clean in VI_EN_MAP:
        return VI_EN_MAP[name_clean]

    return name_clean

# ──────────────────────────────────────────
# SỬA: teams_match dùng normalize_team_for_match
# ──────────────────────────────────────────
def teams_match(team_a, team_b, old_a, old_b):
    """Check if two sets of teams refer to the same match"""
    norm_a = normalize_team_for_match(team_a)
    norm_b = normalize_team_for_match(team_b)
    norm_old_a = normalize_team_for_match(old_a)
    norm_old_b = normalize_team_for_match(old_b)

    if (not norm_a and not norm_b) or (not norm_old_a and not norm_old_b):
        return False

    def names_match(n1, n2):
        """So khớp 2 tên đã normalize: exact hoặc substring (min 4 chars)"""
        if not n1 or not n2:
            return False
        if n1 == n2:
            return True
        # Substring match – tránh match sai với tên quá ngắn
        if len(n1) >= 4 and (n1 in n2 or n2 in n1):
            return True
        return False

    a_ma = names_match(norm_a, norm_old_a)
    a_mb = names_match(norm_a, norm_old_b)
    b_ma = names_match(norm_b, norm_old_a)
    b_mb = names_match(norm_b, norm_old_b)

    # Cả 2 bên đều có 2 đội → phải match chéo
    if norm_a and norm_b and norm_old_a and norm_old_b:
        return (a_ma and b_mb) or (a_mb and b_ma)

    # Một bên chỉ có 1 đội
    if norm_a and norm_b:
        if not norm_old_b:
            return a_ma or b_ma
        if not norm_old_a:
            return a_mb or b_mb
    if norm_a:
        return a_ma or a_mb
    if norm_b:
        return b_ma or b_mb

    return False

def normalize_time_in_channel(channel):
    """Normalize GiovangTV time format: 'HH:MM:SS' + date → 'HH:MM DD/MM'
    Đồng thời XÓA field 'date' để tránh trùng lặp."""
    meta = channel.get("org_metadata", {})
    time_val = meta.get("time", "").strip()
    date_val = meta.get("date", "").strip()

    if time_val and date_val:
        parts = time_val.split(":")
        if len(parts) == 3:
            meta["time"] = f"{parts[0]}:{parts[1]} {date_val}"
            # XÓA field date sau khi đã gộp vào time
            meta.pop("date", None)

    return channel

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
            hm = parts[0].split(":")
            h = int(hm[0])
            m = int(hm[1])
            return (1, 99, 99, h, m)
    except:
        pass

    return (2, 99, 99, 99, 99)

# ──────────────────────────────────────────
# SỬA: find_channel_index dùng normalize_time_for_match
# ──────────────────────────────────────────
def find_channel_index(time_val, team_a, team_b, channels_list, date_val=""):
    """Tìm trận trùng khớp dựa trên thời gian và tên đội.
    
    THAY ĐỔI:
      - Dùng normalize_time_for_match() để so sánh thời gian
      - Truyền thêm date_val cho trường hợp GiovangTV
      - Lấy cả field 'date' từ channel cũ để normalize
    """
    norm_time = normalize_time_for_match(time_val, date_val)

    for i, ch in enumerate(channels_list):
        meta = ch.get("org_metadata", {})
        old_time_raw = meta.get("time", "").strip()
        old_date = meta.get("date", "").strip()
        old_norm_time = normalize_time_for_match(old_time_raw, old_date)
        old_a = meta.get("team_a", "")
        old_b = meta.get("team_b", "")

        # Time matching
        time_match = False

        if norm_time == old_norm_time:
            time_match = True
        elif norm_time == "" or old_norm_time == "":
            # Một bên LIVE, bên kia có giờ → vẫn tính là cùng trận
            time_match = True

        if not time_match:
            continue

        # Team matching
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
                # Normalize time FIRST (GiovangTV HH:MM:SS → HH:MM DD/MM)
                src_channel = normalize_time_in_channel(src_channel)

                meta = src_channel.get("org_metadata", {})
                time_val = meta.get("time", "")
                date_val = meta.get("date", "")  # Vẫn còn nếu không phải HH:MM:SS
                team_a = meta.get("team_a", "")
                team_b = meta.get("team_b", "")
                blv_val = meta.get("blv", "")
                thumb_url = src_channel.get("image", {}).get("url", "")

                if not team_a: continue

                # ★ TRUYỀN THÊM date_val ★
                ch_idx = find_channel_index(time_val, team_a, team_b, target_group["channels"], date_val)

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
                        for label in existing_channel.get("labels", []):
                            if label.get("text") == "🕐 Sắp":
                                label["text"] = "● LIVE"
                                label["text_color"] = "#ff4444"

                    # ★ NẾU channel cũ có time="" (LIVE) còn mới có giờ → cập nhật time ★
                    if time_val and not existing_channel["org_metadata"].get("time", ""):
                        existing_channel["org_metadata"]["time"] = time_val

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

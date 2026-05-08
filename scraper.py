import requests
import json
import os
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

# ==========================================
# LOGIC CỦA BẠN
# ==========================================
def normalize(filepath):
    """Đọc file JSON và chuẩn hóa lại chuỗi để so sánh chính xác nhất"""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    # sort_keys=True giúp sắp xếp lại các key, tránh việc đổi thứ tự bị nhận diện là khác
    return json.dumps(data, ensure_ascii=False, sort_keys=True)

# ==========================================
# LOGIC CÀO DỮ LIỆU
# ==========================================
def fetch_json(url):
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        return response.json()
    except Exception:
        return None

def find_match_index(time_val, team_a, team_b, match_list):
    time_clean = time_val.strip().lower()
    a_clean = team_a.strip().lower()
    b_clean = team_b.strip().lower() if team_b else ""

    for i, m in enumerate(match_list):
        if m["time"].strip().lower() != time_clean:
            continue
        old_match_str = m["match"].lower()
        old_a, old_b = (old_match_str.split(" vs ", 1) + [""])[:2]
        
        is_match = False
        if a_clean == old_a or a_clean == old_b: is_match = True
        if b_clean and (b_clean == old_a or b_clean == old_b): is_match = True
        
        if is_match: return i
    return -1

def extract_stream_links(channel_data):
    links = []
    try:
        for src in channel_data.get("sources", []):
            for content in src.get("contents", []):
                for stream in content.get("streams", []):
                    for link in stream.get("stream_links", []):
                        url = link if isinstance(link, str) else link.get("url")
                        if url: links.append(url)
    except Exception: pass
    return links

def main():
    merged_matches = []

    with ThreadPoolExecutor(max_workers=5) as executor:
        raw_jsons = list(executor.map(fetch_json, [s["url"] for s in SOURCES]))

    for index, raw_data in enumerate(raw_jsons):
        if not raw_data: continue
        source_name = SOURCES[index]["name"]

        for group in raw_data.get("groups", []):
            for ch in group.get("channels", []):
                meta = ch.get("org_metadata", {})
                time_val, team_a = meta.get("time", ""), meta.get("team_a", "")
                team_b, blv_val = meta.get("team_b", ""), meta.get("blv", "")
                cate_raw = meta.get("cate_name", "")
                thumb_val = ch.get("image", {}).get("url", "")
                raw_links = extract_stream_links(ch)
                
                if not time_val or not team_a: continue

                match_name = f"{team_a} vs {team_b}" if team_b else team_a
                mapped_cate = CATEGORIES.get(cate_raw, cate_raw)
                match_idx = find_match_index(time_val, team_a, team_b, merged_matches)

                if match_idx == -1:
                    merged_matches.append({"category": mapped_cate, "time": time_val, "match": match_name, "thumbnail": thumb_val, "links": []})
                    current_match = merged_matches[-1]
                else:
                    current_match = merged_matches[match_idx]
                    if thumb_val: current_match["thumbnail"] = thumb_val

                existing_urls = {lk["url"] for lk in current_match["links"]}
                for url in raw_links:
                    if url not in existing_urls:
                        label = f"{source_name} - {blv_val}".strip(" -")
                        current_match["links"].append({"label": label, "url": url})
                        existing_urls.add(url)

    # Nhóm kết quả
    final_output = {cat: [] for cat in CATEGORIES.values()}
    total = 0
    groups = 0
    
    for match_data in merged_matches:
        if not match_data.get("links"): continue
        cat = match_data["category"]
        if cat in final_output: 
            final_output[cat].append(match_data)
            if len(final_output[cat]) == 1: groups += 1 # Đếm số môn có dữ liệu
            total += 1 # Đếm tổng số kênh/trận

    # Ghi dữ liệu mới ra file tạm thời (staging)
    staging = "staging.json"
    with open(staging, "w", encoding="utf-8") as f:
        json.dump(final_output, f, ensure_ascii=False, indent=2)

    # ==========================================
    # ÁP DỤNG CHÍNH XÁC LOGIC SO SÁNH CỦA BẠN
    # ==========================================
    if os.path.exists("output.json"):
        old_norm = normalize("output.json")
        new_norm = normalize(staging)

        if old_norm != new_norm:
            os.replace(staging, "output.json")
            print(f"\nXong! {total} kenh, {groups} mon the thao -> output.json (DA CAP NHAT)")
        else:
            os.remove(staging)
            print(f"\nXong! {total} kenh, {groups} mon the thao -> Khong co thay doi, giu nguyen output.json")
    else:
        # Lần chạy đầu tiên chưa có file output.json
        os.replace(staging, "output.json")
        print(f"\nXong! {total} kenh, {groups} mon the thao -> output.json (TAO MOI)")

if __name__ == "__main__":
    main()

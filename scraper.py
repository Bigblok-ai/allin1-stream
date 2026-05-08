import requests
import json
import os
import copy
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

# Tạo bộ khung chuẩn 10 môn theo đúng cấu trúc gốc
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

def find_channel_index(time_val, team_a, team_b, channels_list):
    """Tìm kênh trùng theo: Cùng giờ + (Trùng đội A hoặc Trùng đội B)"""
    time_clean = time_val.strip().lower()
    a_clean = team_a.strip().lower()
    b_clean = team_b.strip().lower() if team_b else ""

    for i, ch in enumerate(channels_list):
        meta = ch.get("org_metadata", {})
        if meta.get("time", "").strip().lower() != time_clean:
            continue
            
        old_a = meta.get("team_a", "").strip().lower()
        old_b = meta.get("team_b", "").strip().lower()
        
        is_match = False
        if a_clean == old_a or a_clean == old_b: is_match = True
        if b_clean and (b_clean == old_a or b_clean == old_b): is_match = True
        
        if is_match: return i
    return -1

# ==========================================
# MAIN LOGIC
# ==========================================
def main():
    # Khởi tạo data chuẩn
    final_data = {
        "id": "allin1-stream",
        "name": "All In 1 Stream",
        "groups": copy.deepcopy(GROUP_SKELETON)
    }

    # Map tên để tìm nhanh group tương ứng
    group_map = {g["name"]: g for g in final_data["groups"]}

    with ThreadPoolExecutor(max_workers=5) as executor:
        raw_jsons = list(executor.map(fetch_json, [s["url"] for s in SOURCES]))

    for index, raw_data in enumerate(raw_jsons):
        if not raw_data: continue
        source_name = SOURCES[index]["name"]

        for src_group in raw_data.get("groups", []):
            src_cate_name = src_group.get("name", "") # VD: "⚽ Bóng Đá"
            
            # Bỏ qua nếu nhóm này không nằm trong 10 môn cố định
            if src_cate_name not in group_map: continue
            target_group = group_map[src_cate_name]

            for src_channel in src_group.get("channels", []):
                meta = src_channel.get("org_metadata", {})
                time_val = meta.get("time", "")
                team_a = meta.get("team_a", "")
                team_b = meta.get("team_b", "")
                blv_val = meta.get("blv", "")
                thumb_url = src_channel.get("image", {}).get("url", "")

                if not time_val or not team_a: continue

                # Tìm xem trận này đã có trong group chưa
                ch_idx = find_channel_index(time_val, team_a, team_b, target_group["channels"])

                if ch_idx == -1:
                    # TRẬN MỚI: Thêm nguyên cấu trúc channel vào
                    new_channel = copy.deepcopy(src_channel)
                    target_group["channels"].append(new_channel)
                else:
                    # TRẬN ĐÃ CÓ: Gộp link vào channel cũ
                    existing_channel = target_group["channels"][ch_idx]
                    
                    # 1. Luôn đè thumbnail mới nhất
                    if thumb_url:
                        existing_channel["image"]["url"] = thumb_url

                    # 2. Gộp Sources & Format lại tên BLV
                    # Lấy danh sách link đã có trong channel cũ để chống trùng
                    existing_links = set()
                    for ex_src in existing_channel.get("sources", []):
                        for ex_ct in ex_src.get("contents", []):
                            for ex_st in ex_ct.get("streams", []):
                                for link in ex_st.get("stream_links", []):
                                    existing_links.add(link)

                    # Duyệt qua các source của channel mới (ví dụ Cakhia)
                    for inc_src in src_channel.get("sources", []):
                        has_new_link = False
                        # Clone source ra để sửa tên không ảnh hưởng gốc
                        temp_src = copy.deepcopy(inc_src)
                        
                        for inc_ct in temp_src.get("contents", []):
                            for inc_st in inc_ct.get("streams", []):
                                new_valid_links = []
                                for link in inc_st.get("stream_links", []):
                                    if link not in existing_links:
                                        new_valid_links.append(link)
                                        existing_links.add(link)
                                        has_new_link = True
                                
                                # Chỉ cập nhật stream_links và đổi tên Stream nếu có link mới
                                if new_valid_links:
                                    inc_st["stream_links"] = new_valid_links
                                    # Format lại tên: "Cakhia247 - Giàng A Dập"
                                    inc_st["name"] = f"{source_name} - {blv_val}".strip(" -")
                                else:
                                    inc_st["stream_links"] = [] # Bỏ đi nếu link trùng

                        # Chỉ thêm source vào channel cũ nếu source đó thực sự có link mới
                        if has_new_link:
                            existing_channel["sources"].append(temp_src)

    # ==========================================
    # LOGIC SO SÁNH & GHI FILE (CỦA BẠN)
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
            print(f"\nXong! {total_ch} kenh, {active_grp} mon the thao -> output.json (DA CAP NHAT)")
        else:
            os.remove(staging)
            print(f"\nXong! -> Khong co thay doi, giu nguyen output.json")
    else:
        os.replace(staging, "output.json")
        print(f"\nXong! -> output.json (TAO MOI)")

if __name__ == "__main__":
    main()

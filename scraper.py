import requests
import yaml
import json
from concurrent.futures import ThreadPoolExecutor

def load_config(filepath="config.yaml"):
    with open(filepath, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def fetch_json(url):
    """Lấy dữ liệu từ URL raw"""
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"[Lỗi] Không thể lấy: {url} - {e}", flush=True)
        return None

def find_match_index(time_val, team_a, team_b, match_list):
    """Hàm tìm trận trùng: Cùng giờ + (Trùng đội A hoặc Trùng đội B)"""
    time_clean = time_val.strip().lower()
    a_clean = team_a.strip().lower()
    b_clean = team_b.strip().lower() if team_b else ""

    for i, m in enumerate(match_list):
        if m["time"].strip().lower() != time_clean:
            continue
            
        old_match_str = m["match"].lower()
        if " vs " in old_match_str:
            old_a, old_b = old_match_str.split(" vs ", 1)
        else:
            old_a, old_b = old_match_str, ""

        is_match = False
        if a_clean == old_a or a_clean == old_b:
            is_match = True
        if b_clean and (b_clean == old_a or b_clean == old_b):
            is_match = True

        if is_match:
            return i
            
    return -1

def extract_stream_links(channel_data):
    """Bóc tách sâu lấy link phát thực tế"""
    links = []
    try:
        sources = channel_data.get("sources", [])
        for src in sources:
            contents = src.get("contents", [])
            for content in contents:
                streams = content.get("streams", [])
                for stream in streams:
                    stream_links = stream.get("stream_links", [])
                    for link in stream_links:
                        if isinstance(link, str) and link:
                            links.append(link)
                        elif isinstance(link, dict) and link.get("url"):
                            links.append(link["url"])
    except Exception:
        pass
    return links

def main():
    config = load_config()
    cate_map = config.get("categories", {})
    sources = config.get("sources", [])
    
    merged_matches = []

    # Lấy dữ liệu từ 5 nguồn song song
    with ThreadPoolExecutor(max_workers=5) as executor:
        raw_jsons = list(executor.map(fetch_json, [s["url"] for s in sources]))

    for index, raw_data in enumerate(raw_jsons):
        if not raw_data:
            continue
            
        source_name = sources[index]["name"]
        groups = raw_data.get("groups", [])

        for group in groups:
            channels = group.get("channels", [])
            
            for ch in channels:
                meta = ch.get("org_metadata", {})
                
                time_val = meta.get("time", "")
                team_a = meta.get("team_a", "")
                team_b = meta.get("team_b", "")
                blv_val = meta.get("blv", "")
                cate_raw = meta.get("cate_name", "")
                thumb_val = ch.get("image", {}).get("url", "")
                
                raw_links = extract_stream_links(ch)
                
                if not time_val or not team_a:
                    continue

                match_name = f"{team_a} vs {team_b}" if team_b else team_a
                mapped_cate = cate_map.get(cate_raw, cate_raw)

                match_idx = find_match_index(time_val, team_a, team_b, merged_matches)

                if match_idx == -1:
                    merged_matches.append({
                        "category": mapped_cate,
                        "time": time_val,
                        "match": match_name,
                        "thumbnail": thumb_val,
                        "links": []
                    })
                    current_match = merged_matches[-1]
                else:
                    current_match = merged_matches[match_idx]
                    # Luôn đè thumbnail mới nhất (sau khi bạn sửa scraper nguồn không chèn BLV vào ảnh)
                    if thumb_val:
                        current_match["thumbnail"] = thumb_val

                # Gộp Link
                existing_urls = {lk["url"] for lk in current_match["links"]}
                for url in raw_links:
                    if url not in existing_urls:
                        label = f"{source_name} - {blv_val}".strip(" -")
                        current_match["links"].append({"label": label, "url": url})
                        existing_urls.add(url)

    # Nhóm theo 10 môn cố định
    final_output = {cat: [] for cat in cate_map.values()}

    for match_data in merged_matches:
        cat = match_data["category"]
        # Bỏ qua những trận không có link phát thực tế
        if not match_data.get("links"):
            continue
        if cat in final_output:
            final_output[cat].append(match_data)
        else:
            final_output[cat] = [match_data]

    # In thẳng JSON ra standard output (Dành cho cron-job.org gọi và đọc)
    print(json.dumps(final_output, ensure_ascii=False, indent=2), flush=True)

if __name__ == "__main__":
    main()

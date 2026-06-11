"""
점령전 족보 디스코드 자동 동기화 스크립트
GitHub Actions에서 매일 자정 실행
"""
import requests, json, time, re, os

TOKEN = os.environ['DISCORD_TOKEN']
FIREBASE_URL = os.environ['FIREBASE_URL']
GUILD_ID = "1409399655393005641"

HEADERS = {
    "Authorization": f"Bot {TOKEN}",
    "User-Agent": "DiscordBot (https://github.com, 1.0)",
    "Content-Type": "application/json"
}

EXCLUDE_KEYWORDS = ['옛날', '공지', '공유', '속연계', '프리셋', '로테', '방덱', '리스트', '연습', '일반', '프로젝트', '정복']

def get(url):
    while True:
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code == 429:
            wait = r.json().get("retry_after", 1)
            print(f"  rate limit {wait:.1f}초 대기...")
            time.sleep(float(wait) + 0.5)
            continue
        if r.status_code in (403, 404):
            return None
        try:
            return r.json()
        except:
            return None

def is_valid_dname(name):
    for kw in EXCLUDE_KEYWORDS:
        if kw in name:
            return False
    parts = [p.strip() for p in name.split('-') if p.strip()]
    return len(parts) >= 2

def parse_mobs(text):
    if not text: return []
    if '/' in text:
        return [p.strip() for p in text.split('/') if p.strip()][:3]
    parts = [p.strip() for p in text.split() if p.strip()]
    if len(parts) >= 2: return parts[:3]
    attrs = ['물','풍','불','빛','암']
    result, buf = [], text.strip()
    while buf and len(result) < 3:
        found = False
        for attr in attrs:
            if buf.startswith(attr) and len(buf) > 1:
                next_idx = len(buf)
                for i in range(2, len(buf)):
                    if buf[i] in attrs:
                        next_idx = i
                        break
                result.append(buf[:next_idx])
                buf = buf[next_idx:]
                found = True
                break
        if not found:
            result.append(buf)
            break
    return result[:3]

def clean_memo(memo):
    if not memo: return ''
    memo = re.sub(r'<@[!&]?\d+>', '', memo)
    memo = re.sub(r'<#\d+>', '', memo)
    memo = re.sub(r'<a?:\w+:\d+>', '', memo)
    memo = re.sub(r'\n{3,}', '\n\n', memo)
    return memo.strip()

def is_valid_mob(m):
    if not m: return False
    m = m.strip('-').strip()
    if not m or len(m) < 2: return False
    if re.search(r'<[@#]', m): return False
    if re.search(r'\d{10,}', m): return False
    if len(m) > 8: return False
    if any(c in m for c in ['(', ')', 'http', '+', '>', '<']): return False
    return True

def get_thread_first_message(thread_id):
    msgs = get(f"https://discord.com/api/v10/channels/{thread_id}/messages?limit=5&after=0")
    if not msgs or not isinstance(msgs, list): return ""
    msgs.sort(key=lambda m: int(m.get('id', 0)))
    for msg in msgs:
        content = msg.get('content', '').strip()
        if content: return content
    return ""

def get_tier_from_category(name):
    if not name: return 5
    if '4성' in name: return 4
    return 5

def get_firebase_existing():
    """Firebase에서 기존 데이터 가져오기"""
    r = requests.get(f"{FIREBASE_URL}/jokbo.json")
    if r.status_code == 200 and r.json():
        return r.json()  # {id: entry} 형태
    return {}

def push_to_firebase(new_entries):
    """새 항목만 Firebase에 추가"""
    for entry in new_entries:
        r = requests.put(
            f"{FIREBASE_URL}/jokbo/{entry['id']}.json",
            json=entry
        )
        if r.status_code == 200:
            print(f"  ✅ 추가: {entry['dname']} / {entry['my']}")
        else:
            print(f"  ❌ 실패: {entry['id']} - {r.status_code}")
        time.sleep(0.1)

def main():
    print("=== 디스코드 족보 동기화 시작 ===")

    # 1. 기존 Firebase 데이터 로드
    existing = get_firebase_existing()
    existing_keys = set(existing.keys()) if existing else set()
    # dname+my 조합으로 중복 체크
    existing_combos = set()
    for e in existing.values():
        if isinstance(e, dict):
            combo = e.get('dname','') + '|' + ','.join(e.get('my',[]))
            existing_combos.add(combo)
    print(f"기존 Firebase 데이터: {len(existing_keys)}개")

    # 2. 디스코드 채널 수집
    channels = get(f"https://discord.com/api/v10/guilds/{GUILD_ID}/channels")
    if not channels:
        print("채널 가져오기 실패")
        return

    categories = {c['id']: c['name'] for c in channels if c['type'] == 4}
    target = [c for c in channels if c['type'] in (0, 15) and is_valid_dname(c['name'])]
    print(f"유효 채널: {len(target)}개")

    new_entries = []
    uid_counter = [1]

    for idx, ch in enumerate(target):
        ch_name = ch['name']
        parent_id = ch.get('parent_id')
        category_name = categories.get(parent_id, '')
        tier = get_tier_from_category(category_name)
        enemy = [p.strip() for p in ch_name.split('-') if p.strip()][:3]

        threads = []
        if ch['type'] == 15:
            archived = get(f"https://discord.com/api/v10/channels/{ch['id']}/threads/archived/public?limit=100")
            if archived and isinstance(archived, dict):
                threads += archived.get('threads', [])
            active = get(f"https://discord.com/api/v10/guilds/{GUILD_ID}/threads/active")
            if active and isinstance(active, dict):
                threads += [t for t in active.get('threads', []) if t.get('parent_id') == ch['id']]

        for thread in threads:
            title = thread.get('name', '')
            my = parse_mobs(title)
            my = [m.strip('-') for m in my if is_valid_mob(m.strip('-'))]
            if not my: continue

            # 중복 체크
            combo = ch_name + '|' + ','.join(my)
            if combo in existing_combos:
                continue

            memo = clean_memo(get_thread_first_message(thread['id']))
            entry_id = f"dc_auto_{thread['id']}"

            new_entries.append({
                "id": entry_id,
                "tier": tier,
                "dname": ch_name,
                "enemy": enemy,
                "my": my,
                "rank": "1",
                "memo": memo,
                "addedBy": "auto-sync"
            })
            time.sleep(0.15)

        time.sleep(0.2)

    print(f"\n새로 추가할 항목: {len(new_entries)}개")

    if new_entries:
        push_to_firebase(new_entries)
        print(f"\n✅ 동기화 완료! {len(new_entries)}개 추가됨")
    else:
        print("\n변경사항 없음")

if __name__ == "__main__":
    main()

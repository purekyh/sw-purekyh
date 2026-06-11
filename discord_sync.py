"""
점령전 족보 디스코드 자동 동기화 스크립트 v3
urllib 사용으로 인코딩 문제 해결
"""
import json, time, re, os
import urllib.request, urllib.error

TOKEN = os.environ['DISCORD_TOKEN']
FIREBASE_URL = os.environ['FIREBASE_URL']
GUILD_ID = "1409399655393005641"

EXCLUDE_KEYWORDS = ['옛날', '공지', '공유', '속연계', '프리셋', '로테', '방덱', '리스트', '연습', '일반', '프로젝트', '정복']

def get(url):
    while True:
        try:
            req = urllib.request.Request(url)
            req.add_unredirected_header("Authorization", "Bot " + TOKEN)
            req.add_unredirected_header("User-Agent", "DiscordBot (https://github.com, 1.0)")
            with urllib.request.urlopen(req, timeout=30) as res:
                return json.loads(res.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                body = json.loads(e.read().decode('utf-8'))
                wait = body.get("retry_after", 1)
                print(f"  rate limit {wait:.1f}초 대기...")
                time.sleep(float(wait) + 0.5)
                continue
            elif e.code in (403, 404):
                return None
            else:
                print(f"  HTTP {e.code}: {url}")
                return None
        except Exception as ex:
            print(f"  오류: {ex}")
            return None

def firebase_get(path):
    try:
        req = urllib.request.Request(f"{FIREBASE_URL}/{path}.json")
        with urllib.request.urlopen(req, timeout=30) as res:
            return json.loads(res.read().decode('utf-8'))
    except:
        return None

def firebase_put(path, data):
    try:
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(
            f"{FIREBASE_URL}/{path}.json",
            data=body,
            method='PUT',
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=30) as res:
            return True
    except Exception as ex:
        print(f"  Firebase PUT 오류: {ex}")
        return False

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

def main():
    print("=== 디스코드 족보 동기화 시작 ===")

    # 기존 Firebase 데이터
    existing = firebase_get('jokbo')
    existing_combos = set()
    if existing and isinstance(existing, dict):
        for e in existing.values():
            if isinstance(e, dict):
                combo = e.get('dname','') + '|' + ','.join(e.get('my',[]))
                existing_combos.add(combo)
    print(f"기존 Firebase 데이터: {len(existing_combos)}개")

    # 디스코드 채널
    channels = get(f"https://discord.com/api/v10/guilds/{GUILD_ID}/channels")
    if not channels:
        print("채널 가져오기 실패")
        return

    categories = {c['id']: c['name'] for c in channels if c['type'] == 4}
    target = [c for c in channels if c['type'] in (0, 15) and is_valid_dname(c['name'])]
    print(f"유효 채널: {len(target)}개")

    new_count = 0

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

            combo = ch_name + '|' + ','.join(my)
            if combo in existing_combos: continue

            memo = clean_memo(get_thread_first_message(thread['id']))
            entry_id = f"dc_auto_{thread['id']}"

            entry = {
                "id": entry_id,
                "tier": tier,
                "dname": ch_name,
                "enemy": enemy,
                "my": my,
                "rank": "1",
                "memo": memo,
                "addedBy": "auto-sync"
            }

            if firebase_put(f"jokbo/{entry_id}", entry):
                print(f"  ✅ [{tier}성] {ch_name} / {my}")
                new_count += 1
                existing_combos.add(combo)
            time.sleep(0.15)

        time.sleep(0.2)

    print(f"\n✅ 완료! 새로 추가: {new_count}개")

if __name__ == "__main__":
    main()

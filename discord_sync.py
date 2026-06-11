"""
점령전 족보 디스코드 자동 동기화 v6
curl subprocess 사용 - latin-1 완전 우회
"""
import json, time, re, os, subprocess

TOKEN = os.environ['DISCORD_TOKEN']
FIREBASE_URL = os.environ['FIREBASE_URL']
GUILD_ID = "1409399655393005641"

EXCLUDE = ['옛날','공지','공유','속연계','프리셋','로테','방덱','리스트','연습','일반','프로젝트','정복']

def discord_get(path):
    """curl로 디스코드 API 호출"""
    while True:
        try:
            result = subprocess.run([
                'curl', '-s', '-w', '\n%{http_code}',
                '-H', f'Authorization: Bot {TOKEN}',
                '-H', 'User-Agent: python-bot',
                f'https://discord.com/api/v10{path}'
            ], capture_output=True, timeout=30)
            
            output = result.stdout.decode('utf-8')
            lines = output.rsplit('\n', 1)
            body = lines[0]
            status = int(lines[1]) if len(lines) > 1 else 0
            
            if status == 429:
                data = json.loads(body)
                wait = data.get("retry_after", 1)
                print(f"  rate limit {wait:.1f}초 대기...")
                time.sleep(float(wait) + 0.5)
                continue
            if status in (403, 404, 0):
                return None
            return json.loads(body)
        except Exception as ex:
            print(f"  오류: {ex}")
            return None

def firebase_get(path):
    try:
        result = subprocess.run([
            'curl', '-s', f'{FIREBASE_URL}/{path}.json'
        ], capture_output=True, timeout=30)
        return json.loads(result.stdout.decode('utf-8'))
    except: return None

def firebase_put(path, data):
    try:
        body = json.dumps(data, ensure_ascii=False)
        result = subprocess.run([
            'curl', '-s', '-X', 'PUT',
            '-H', 'Content-Type: application/json',
            '-d', body,
            f'{FIREBASE_URL}/{path}.json'
        ], capture_output=True, timeout=30)
        return result.returncode == 0
    except: return False

def is_valid(name):
    for k in EXCLUDE:
        if k in name: return False
    return len([p for p in name.split('-') if p.strip()]) >= 2

def parse_mobs(text):
    if not text: return []
    if '/' in text: return [p.strip() for p in text.split('/') if p.strip()][:3]
    parts = [p.strip() for p in text.split() if p.strip()]
    if len(parts) >= 2: return parts[:3]
    attrs = ['물','풍','불','빛','암']
    result, buf = [], text.strip()
    while buf and len(result) < 3:
        found = False
        for a in attrs:
            if buf.startswith(a) and len(buf) > 1:
                ni = len(buf)
                for i in range(2, len(buf)):
                    if buf[i] in attrs: ni = i; break
                result.append(buf[:ni]); buf = buf[ni:]; found = True; break
        if not found: result.append(buf); break
    return result[:3]

def clean(memo):
    if not memo: return ''
    memo = re.sub(r'<@[!&]?\d+>', '', memo)
    memo = re.sub(r'<#\d+>', '', memo)
    memo = re.sub(r'<a?:\w+:\d+>', '', memo)
    return re.sub(r'\n{3,}', '\n\n', memo).strip()

def valid_mob(m):
    m = m.strip('-').strip()
    if not m or len(m) < 2 or len(m) > 8: return False
    if re.search(r'<[@#]|\d{10,}', m): return False
    if any(c in m for c in '()http+><'): return False
    return True

def first_msg(tid):
    msgs = discord_get(f"/channels/{tid}/messages?limit=5&after=0")
    if not msgs or not isinstance(msgs, list): return ""
    msgs.sort(key=lambda m: int(m.get('id',0)))
    for msg in msgs:
        c = msg.get('content','').strip()
        if c: return c
    return ""

def tier_from_cat(name):
    return 4 if name and '4성' in name else 5

def main():
    print("=== 디스코드 족보 동기화 시작 ===")
    existing = firebase_get('jokbo')
    combos = set()
    if existing and isinstance(existing, dict):
        for e in existing.values():
            if isinstance(e, dict):
                combos.add(e.get('dname','')+'|'+','.join(e.get('my',[])))
    print(f"기존: {len(combos)}개")

    channels = discord_get(f"/guilds/{GUILD_ID}/channels")
    if not channels or not isinstance(channels, list):
        print("채널 응답 내용:", json.dumps(channels, ensure_ascii=False) if channels else "None")
        # dict면 에러 메시지일 수 있음 - 그래도 진행 시도
        if isinstance(channels, dict) and 'message' in channels:
            print("에러:", channels['message'])
        return

    cats = {c['id']: c['name'] for c in channels if c['type'] == 4}
    target = [c for c in channels if c['type'] in (0,15) and is_valid(c['name'])]
    print(f"유효 채널: {len(target)}개")

    new_count = 0
    for ch in target:
        name = ch['name']
        tier = tier_from_cat(cats.get(ch.get('parent_id'),''))
        enemy = [p.strip() for p in name.split('-') if p.strip()][:3]
        threads = []

        if ch['type'] == 15:
            ar = discord_get(f"/channels/{ch['id']}/threads/archived/public?limit=100")
            if ar and isinstance(ar, dict): threads += ar.get('threads',[])
            ac = discord_get(f"/guilds/{GUILD_ID}/threads/active")
            if ac and isinstance(ac, dict): threads += [t for t in ac.get('threads',[]) if t.get('parent_id')==ch['id']]

        for t in threads:
            my = parse_mobs(t.get('name',''))
            my = [m.strip('-') for m in my if valid_mob(m.strip('-'))]
            if not my: continue
            combo = name+'|'+','.join(my)
            if combo in combos: continue
            memo = clean(first_msg(t['id']))
            eid = f"dc_auto_{t['id']}"
            entry = {"id":eid,"tier":tier,"dname":name,"enemy":enemy,"my":my,"rank":"1","memo":memo,"addedBy":"auto-sync"}
            if firebase_put(f"jokbo/{eid}", entry):
                print(f"  [{tier}성] {name} / {my}")
                new_count += 1
                combos.add(combo)
            time.sleep(0.1)
        time.sleep(0.2)

    print(f"완료! 신규: {new_count}개")

if __name__ == "__main__":
    main()

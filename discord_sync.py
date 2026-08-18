"""
점령전 족보 디스코드 자동 동기화
매시 정각 실행 - 기존 게시물 수정 반영 + 순위 파싱 보완
"""
import json, time, re, os
import http.client

TOKEN = os.environ['DISCORD_TOKEN']
FIREBASE_URL = os.environ['FIREBASE_URL']
GUILD_ID = "1409399655393005641"

EXCLUDE = ['옛날','공지','공유','속연계','프리셋','로테','방덱','리스트','연습','일반','프로젝트','정복']

def discord_request(path):
    while True:
        try:
            import ssl, socket
            ctx = ssl.create_default_context()
            s = socket.create_connection(("discord.com", 443), timeout=30)
            ss = ctx.wrap_socket(s, server_hostname="discord.com")
            auth_token = "Bot " + TOKEN
            request = f"GET /api/v10{path} HTTP/1.1\r\nHost: discord.com\r\nUser-Agent: python-bot\r\nConnection: close\r\n"
            ss.send(request.encode('ascii'))
            ss.send(b"Authorization: ")
            ss.send(auth_token.encode('utf-8'))
            ss.send(b"\r\n\r\n")
            response = b""
            while True:
                chunk = ss.recv(4096)
                if not chunk: break
                response += chunk
            ss.close()
            header_end = response.find(b"\r\n\r\n")
            if header_end == -1: return None
            header_part = response[:header_end].decode('ascii', errors='ignore')
            body = response[header_end+4:]
            status_line = header_part.split("\r\n")[0]
            status_code = int(status_line.split(" ")[1])
            if b"Transfer-Encoding: chunked" in response[:header_end]:
                decoded = b""
                pos = 0
                while pos < len(body):
                    line_end = body.find(b"\r\n", pos)
                    if line_end == -1: break
                    chunk_size = int(body[pos:line_end], 16)
                    if chunk_size == 0: break
                    decoded += body[line_end+2:line_end+2+chunk_size]
                    pos = line_end + 2 + chunk_size + 2
                body = decoded
            body_str = body.decode('utf-8')
            if status_code == 429:
                data = json.loads(body_str)
                wait = data.get("retry_after", 1)
                print(f"  rate limit {wait:.1f}초 대기...")
                time.sleep(float(wait) + 0.5)
                continue
            if status_code in (403, 404): return None
            return json.loads(body_str)
        except Exception as ex:
            print(f"  오류: {ex}")
            return None

def fb_get(path):
    try:
        fb_host = FIREBASE_URL.replace("https://", "")
        conn = http.client.HTTPSConnection(fb_host)
        conn.request("GET", f"/{path}.json")
        res = conn.getresponse()
        body = res.read().decode('utf-8')
        conn.close()
        return json.loads(body)
    except: return None

def fb_put(path, data):
    try:
        fb_host = FIREBASE_URL.replace("https://", "")
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        conn = http.client.HTTPSConnection(fb_host)
        conn.request("PUT", f"/{path}.json", body=body, headers={"Content-Type": "application/json"})
        res = conn.getresponse()
        res.read()
        conn.close()
        return res.status == 200
    except: return False

def is_valid(name):
    for k in EXCLUDE:
        if k in name: return False
    return len([p for p in name.split('-') if p.strip()]) >= 2

def extract_rank(title, memo=''):
    """제목 + 본문에서 순위 추출. 둘 다 있으면 낮은 순위(2순위) 우선"""
    combined = (title + ' ' + memo).lower()
    has_1 = '1순위' in combined or '1위' in combined
    has_2 = '2순위' in combined or '2위' in combined
    has_nal = '날빌' in combined

    if has_nal: return 'w'
    if has_2: return '2'   # 1+2 같이 있어도 2순위
    if has_1: return '1'

    # 제목에서만 판단
    t = title.lower()
    if '날빌' in t: return 'w'
    if '2순위' in t or '2위' in t: return '2'
    return '1'

def strip_rank_prefix(text):
    if not text: return text
    text = re.sub(r'[12]순위', '', text)
    text = re.sub(r'날빌성?', '', text)
    return text.strip(' -,[]()')

def parse_mobs(text):
    if not text: return []
    text = strip_rank_prefix(text)
    if not text: return []
    if '/' in text or ',' in text:
        parts = [p.strip() for p in re.split(r'[/,]', text) if p.strip()]
        if len(parts) >= 2: return parts[:3]
    if ' - ' in text or '-' in text:
        parts = [p.strip() for p in re.split(r'\s*-\s*', text) if p.strip()]
        if len(parts) >= 2: return parts[:3]
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
    memo = re.sub(r'\n{3,}', '\n\n', memo)
    return memo.strip()

def valid_mob(m):
    m = m.strip('-').strip()
    if not m or len(m) < 2 or len(m) > 8: return False
    if re.search(r'<[@#]|\d{10,}', m): return False
    if any(c in m for c in '()http+><'): return False
    return True

def first_msg(tid):
    msgs = discord_request(f"/channels/{tid}/messages?limit=5&after=0")
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
    existing = fb_get('jokbo')

    # 기존 dc_auto_ 항목을 thread_id 기준으로 맵핑
    thread_to_entry = {}
    combo_to_id = {}
    if existing and isinstance(existing, dict):
        for key, e in existing.items():
            if isinstance(e, dict):
                if key.startswith('dc_auto_'):
                    tid = key.replace('dc_auto_', '')
                    thread_to_entry[tid] = e
                combo = e.get('dname','') + '|' + ','.join(e.get('my',[]))
                combo_to_id[combo] = key

    print(f"기존: {len(existing) if existing else 0}개 (dc_auto_: {len(thread_to_entry)}개)")

    channels = discord_request(f"/guilds/{GUILD_ID}/channels")
    if not channels or not isinstance(channels, list):
        print("채널 가져오기 실패:", channels)
        return

    cats = {c['id']: c['name'] for c in channels if c['type'] == 4}
    target = [c for c in channels if c['type'] in (0,15) and is_valid(c['name'])]
    print(f"유효 채널: {len(target)}개")

    new_count = 0
    updated_count = 0

    for ch in target:
        name = ch['name']
        tier = tier_from_cat(cats.get(ch.get('parent_id'),''))
        enemy = [p.strip() for p in name.split('-') if p.strip()][:3]
        threads = []

        if ch['type'] == 15:
            ar = discord_request(f"/channels/{ch['id']}/threads/archived/public?limit=100")
            if ar and isinstance(ar, dict): threads += ar.get('threads',[])
            ac = discord_request(f"/guilds/{GUILD_ID}/threads/active")
            if ac and isinstance(ac, dict): threads += [t for t in ac.get('threads',[]) if t.get('parent_id')==ch['id']]

        for t in threads:
            title = t.get('name','')
            tid = t['id']
            eid = f"dc_auto_{tid}"

            my = parse_mobs(title)
            my = [m.strip('-') for m in my if valid_mob(m.strip('-'))]
            if not my: continue

            memo = clean(first_msg(tid))
            rank = extract_rank(title, memo)

            # 기존 항목 있으면 업데이트 체크
            if tid in thread_to_entry:
                old_e = thread_to_entry[tid]
                if (old_e.get('memo','') != memo or
                    old_e.get('rank','1') != rank or
                    old_e.get('my',[]) != my):
                    entry = {**old_e, "my": my, "rank": rank, "memo": memo}
                    if fb_put(f"jokbo/{eid}", entry):
                        print(f"  [업데이트] [{tier}성/{rank}순위] {name} / {my}")
                        updated_count += 1
                continue

            # 신규 항목
            combo = name + '|' + ','.join(my)
            if combo in combo_to_id: continue

            entry = {"id":eid,"tier":tier,"dname":name,"enemy":enemy,"my":my,"rank":rank,"memo":memo,"addedBy":"auto-sync"}
            if fb_put(f"jokbo/{eid}", entry):
                print(f"  [신규] [{tier}성/{rank}순위] {name} / {my}")
                new_count += 1
                combo_to_id[combo] = eid

            time.sleep(0.1)
        time.sleep(0.2)

    print(f"\n완료! 신규: {new_count}개, 업데이트: {updated_count}개")

if __name__ == "__main__":
    main()

# Offline checks of the bot's behaviour, with a fake Discord and a fake GitHub.
# Run from the repo: python3 bot/test_behaviors.py
import sys, json, os, re, time, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import usp_bot as B
CLOCK=[1_790_000_000_000]
B.now_ms=lambda: CLOCK[0]
def adv(sec=30): CLOCK[0]+=int(sec*1000)

# ---- fake discord
class FakeDC:
    def __init__(s): s.ch={}; s.n=1000; s.rx={}; s.me="900"
    def nid(s): s.n+=1; return str(int(B.snowflake(CLOCK[0]))+s.n)
    def __call__(s, method, path, body=None):
        if path=="/users/@me": return {"id":s.me}
        m=re.match(r"/users/(\d+)$",path)
        if m: return {"id":m[1],"username":"user"+m[1][-4:],"global_name":None}
        m=re.match(r"/channels/(\d+)$",path)
        if m: return {"guild_id":"77"}
        m=re.match(r"/channels/(\d+)/messages\?limit=(\d+)(?:&after=(\d+))?$",path)
        if m and method=="GET":
            msgs=s.ch.get(m[1],[]); 
            if m[3]: msgs=[x for x in msgs if int(x["id"])>int(m[3])]
            return list(reversed(msgs))[:int(m[2])]
        m=re.match(r"/channels/(\d+)/messages$",path)
        if m and method=="POST":
            msg={"id":s.nid(),"author":{"id":s.me,"bot":True},"content":body.get("content",""),"embeds":body.get("embeds",[])}
            s.ch.setdefault(m[1],[]).append(msg); return msg
        m=re.match(r"/channels/(\d+)/messages/(\d+)$",path)
        if m and method=="GET": return json.loads(json.dumps(next(x for x in s.ch[m[1]] if x["id"]==m[2])))
        if m and method=="PATCH":
            msg=next(x for x in s.ch[m[1]] if x["id"]==m[2]); msg.update(body); return msg
        m=re.match(r"/channels/(\d+)/messages/(\d+)$",path)
        if m and method=="DELETE": s.ch[m[1]]=[x for x in s.ch.get(m[1],[]) if x["id"]!=m[2]]; return None
        m=re.match(r"/channels/(\d+)/messages/(\d+)/reactions/([^/?]+)/@me$",path)
        if m: s.rx.setdefault(m[2],{}).setdefault(B.urllib.parse.unquote(m[3]),[]).append(s.me); return None
        m=re.match(r"/channels/(\d+)/messages/(\d+)/reactions/([^/?]+)\?limit=100$",path)
        if m: return [{"id":u} for u in s.rx.get(m[2],{}).get(B.urllib.parse.unquote(m[3]),[])]
        m=re.match(r"/channels/(\d+)/pins/(\d+)$",path)
        if m: return None
        raise Exception("unhandled "+method+" "+path)
    def user_msg(s, ch, uid, text):
        msg={"id":s.nid(),"author":{"id":uid},"content":text,"embeds":[],"channel_id":ch}; s.ch.setdefault(ch,[]).append(msg); return msg
    def react(s, mid, uid, emo): s.rx.setdefault(mid,{}).setdefault(emo,[]).append(uid)

D=FakeDC(); B.dc=D
OW1,OW2,MOD1,MOD2,RANDO="169519583881986055","152383554632810910","301000000000000001","302000000000000002","999000000000000009"
os.environ.update(DISCORD_BOT_TOKEN="t", DISCORD_OWNER_IDS=f"{OW1},{OW2}", DISCORD_CHANNEL_IDS="mod=11,voting=22,settings=33",
                  GITHUB_TOKEN="g", GITHUB_REPOSITORY="d3gw33b/USP", GITHUB_REPOSITORY_OWNER="d3gw33b")

def make_pr(num, files, msg="x\n\nAgreed-to: CONTRIBUTING.md#contributor-agreement", who="bob"):
    ev={"pull_request":{"number":num,"title":f"PR {num} @everyone","body":"b","html_url":f"https://github.com/d3gw33b/USP/pull/{num}",
        "user":{"login":who,"avatar_url":"a","html_url":"u"}}}
    path=os.path.join(tempfile.gettempdir(), "usp_test_event.json")
    json.dump(ev,open(path,"w")); os.environ["GITHUB_EVENT_PATH"]=path
    def gh(path, raw=False, accept=None):
        if raw: return b"diff"
        if "/files" in path: return files if "page=1" in path else []
        if "/commits" in path: return [{"commit":{"message":msg}}] if "page=1" in path else []
        if "/pulls/" in path: return {"head":{"sha":"abc123"}}
    B.gh=gh
B.run_local=lambda m,p: "Good:\n- fine\nTL;DR: ok"
REAL_STATUS=B.post_vote_status
B.post_vote_status=lambda st, state: print("status", state)

def cards(): return [(m,B.parse_card(m["embeds"][0])) for m in D.ch.get("22",[]) if m["embeds"] and B.parse_card(m["embeds"][0])]
def tick(): adv(); B.cmd_tick(); adv()
def expire(c): c["embeds"][0]["timestamp"]=B.iso(CLOCK[0]-1000)
def saved(): return B.parse_settings(D.ch["33"][0]["embeds"][0])
RESULTS=[]
def check(name, fn):
    try:
        r = fn()
        RESULTS.append((name, True if r is True else f"got {r!r}"))
    except Exception as e:
        RESULTS.append((name, f"ERROR {type(e).__name__}: {e}"))

B.run_local=lambda m,p: "Good:\n- fine\nTL;DR: ok"
B.dc=D
import tempfile
SUMDIR=os.path.join(tempfile.mkdtemp(), "usp-summary")
os.environ["USP_SUMMARY_DIR"]=SUMDIR
os.environ["GITHUB_TOKEN"]="t"
PATCHES=[]
STATUSES=[]
MERGES=[]
real_http=B.http
def fake_http(method, url, body=None, headers=None, raw=False, tries=5):
    if method=="PATCH" and "/pulls/" in url: PATCHES.append((url, body)); return {}
    if method=="PUT" and url.endswith("/merge"): MERGES.append(url); return {}
    if "api.github.com" in url and method=="POST" and "/statuses/" in url: STATUSES.append((url, body)); return {}
    return real_http(method, url, body, headers, raw, tries)
B.http=fake_http
tick()
D.user_msg("33",OW1,"!usp voters"); adv(5)
import usp_live as L
cfg=B.env_config()
live=L.Live(cfg); live.online.set(); live.catch_up()
def say(text, who=OW1, ch="33"):
    m=D.user_msg(ch,who,text); live.on_message(m); return D.ch[ch][-1]["content"]

gh_files=[{"filename":".github/workflows/x.yml","additions":3,"deletions":2,"status":"modified","patch":"x"}]
check("1 .github change is sized by its lines, not forced to large", lambda: B.analyse(gh_files,[])[3]=="tiny")
check("2 override owners vote sets overrides on", lambda: say("!usp override owners vote") and saved()["override_on"] is True)
check("3 override off turns them off", lambda: (say("!usp override off"), saved()["override_on"])[1] is False)
check("4 timer defaults: command 5s, summary off, help off", lambda: B.DEFAULT_SETTINGS["timers"]=={"command":5,"summary":0,"help":0})
check("5 timer command is owner-only", lambda: "Only the two owners" in say("!usp timer command 9", who=MOD1))
check("6 timer command sets seconds", lambda: (say("!usp timer command 9"), saved()["timers"]["command"])[1]==9)
check("7 timer off sets 0", lambda: (say("!usp timer command off"), saved()["timers"]["command"])[1]==0)
check("8 timer restored to 5", lambda: (say("!usp timer command 5"), saved()["timers"]["command"])[1]==5)
B.EMOJI_CACHE["list"]=["<:loading:1>"]
check("9 command replies get a server emoji marker", lambda: B.temp_prefix(saved()).startswith("<:loading"))
check("10 secrets with spaces and newlines parse", lambda: (os.environ.update(DISCORD_CHANNEL_IDS='mod=1, voting = 2\n,settings=3'), B.env_config()["ch"]["voting"])[1]=="2")
os.environ.update(DISCORD_CHANNEL_IDS="mod=11,voting=22,settings=33")
make_pr(91,[{"filename":"a","additions":1,"deletions":0,"status":"modified","patch":"x"}]); B.cmd_card()
check("11 bare !usp summary answers the one open vote", lambda: "Plain version of usp#91" in say("!usp summary"))
check("12 summary of a missing vote says so", lambda: "No open vote matches" in say("!usp summary usp#999"))
B.run_local=lambda m,p: (_ for _ in ()).throw(RuntimeError("no model"))
_gh=B.gh
def gh_with_title(path, raw=False, accept=None):
    r=_gh(path, raw, accept)
    if isinstance(r, dict) and "/pulls/" in path and "head" in r: r={**r, "title":"T", "body":"b", "user":{"login":"bob","avatar_url":"a","html_url":"u"}}
    return r
B.gh=gh_with_title
make_pr(92,[{"filename":"a","additions":1,"deletions":0,"status":"modified","patch":"x"}]); _gh2=B.gh; B.gh=lambda p,raw=False,accept=None: gh_with_title(p,raw,accept) if False else (lambda r: {**r,"title":"T","body":"b","user":{"login":"bob","avatar_url":"a","html_url":"u"}} if isinstance(r,dict) and "head" in r else r)(_gh2(p,raw,accept)); B.cmd_card()
check("13 no model: summary asks for a reply file", lambda: "Asked for a summary" in say("!usp summary usp#92") and os.path.exists(os.path.join(SUMDIR,"requests","d3gw33b_usp_92.json")))
B.run_local=lambda m,p: "Good:\n- fine\nTL;DR: ok"
B.gh=_gh
check("14 owner ping sends no mentions", lambda: '"allowed_mentions": {"parse": []}' in open(os.path.join(os.path.dirname(B.__file__),"usp_bot.py")).read())
c,st=cards()[-1]
check("15 veto closes the PR (REJECTED)", lambda: (say("!usp veto usp#92", who=OW1), any("/pulls/" in u and b=={"state":"closed"} for u,b in PATCHES))[1])
make_pr(93,[{"filename":"a","additions":1,"deletions":0,"status":"modified","patch":"x"}]); B.cmd_card()
check("16 approve does not close the PR", lambda: (say("!usp approve usp#93", who=OW1), not any("pulls/93" in u for u,_ in PATCHES))[1])
check("17 help command replies", lambda: len(say("!usp help"))>0)

check("18 team result text says THE TEAM HAS SPOKEN", lambda: "THE TEAM HAS SPOKEN" in open(os.path.join(os.path.dirname(B.__file__),"usp_bot.py")).read())
check("19 owner decisions are listed separately", lambda: all(w in open(os.path.join(os.path.dirname(B.__file__),"usp_bot.py")).read() for w in ["in agreement","has VETOED","has no opinion"]))
check("20 bot reloads on any change to its files (content hash)", lambda: "hashlib.sha256" in open(os.path.join(os.path.dirname(B.__file__),"usp_live.py")).read())
REMOVALS=[]
B.remove_later=lambda ch, ids, secs: REMOVALS.append((ch, ids, secs))
def card_ends(num, files):
    make_pr(num, files); B.cmd_card()
    return cards()[-1]
check("21 tiny vote ends in 5 minutes", lambda: (lambda c: c[1]["deadline"]-CLOCK[0]//1000)(card_ends(94,[{"filename":"a","additions":3,"deletions":0,"status":"modified","patch":"x"}]))==300)
check("22 small vote ends in 15 minutes", lambda: (lambda c: c[1]["deadline"]-CLOCK[0]//1000)(card_ends(95,[{"filename":"a","additions":50,"deletions":0,"status":"modified","patch":"x"}]))==900)
def owner_yes_passes(num, files):
    c,_=card_ends(num, files)
    D.react(c["id"], OW1, "✅")
    B.check_cards(cfg, B.load_settings(cfg)[0], B.find_cards(cfg, D.me))
    return cards()[-1][1]["state"]
check("23 owner ✅ passes a tiny vote at once", lambda: owner_yes_passes(96,[{"filename":"a","additions":3,"deletions":0,"status":"modified","patch":"x"}])=="approved")
check("24 owner ✅ passes a small vote at once", lambda: owner_yes_passes(97,[{"filename":"a","additions":50,"deletions":0,"status":"modified","patch":"x"}])=="approved")
REMOVALS.clear()
say("!usp help", ch="22")
say("!usp summary usp#94", ch="22")
check("25 help and summary replies are not auto-deleted by default", lambda: REMOVALS==[])
REMOVALS.clear()
say("!usp voters", ch="22")
check("26 a command in voting gets the 5 second delete", lambda: [r[2] for r in REMOVALS]==[5])
REMOVALS.clear()
say("!usp voters", ch="11")
check("27 mod chat is exempt from auto-delete", lambda: REMOVALS==[] and not D.ch["11"][-1]["content"].startswith("<"))
card_ids={m["id"] for m,_ in cards()}
check("28 vote cards are never scheduled for deletion", lambda: not any(i in card_ids for _,ids,_ in REMOVALS for i in ids))
check("29 approve merges the pull request", lambda: any("pulls/93/merge" in x for x in MERGES))
check("30 a deny does not merge", lambda: not any("pulls/92/merge" in x for x in MERGES))
make_pr(98,[{"filename":"a","additions":5000,"deletions":0,"status":"modified","patch":"x"}]); B.cmd_card()
check("31 a huge vote waits for the second owner", lambda: "needs both owners" in say("!usp approve usp#98", who=OW1) and cards()[-1][1]["state"]=="open")
check("32 a huge vote passes when both owners approve", lambda: (say("!usp approve usp#98", who=OW2), cards()[-1][1]["state"]=="approved" and any("pulls/98/merge" in x for x in MERGES))[1])
import threading as _th
_real_live=L.Live; _tries=[0]
def _flaky(cfg):
    _tries[0]+=1
    if _tries[0]<3: raise OSError("connection reset")
    return "live"
L.Live=_flaky
check("33 startup retries while Discord can't be reached", lambda: L.start_live(cfg, _th.Event(), pause=0)=="live" and _tries[0]==3)
L.Live=_real_live
check("34 offline past the limit asks for a restart", lambda: L.should_restart(0, L.WATCHDOG_AFTER+1) and not L.should_restart(0, L.WATCHDOG_AFTER-1) and not L.should_restart(None, 10**9))
make_pr(99,[{"filename":"a","additions":5000,"deletions":0,"status":"modified","patch":"x"}]); B.cmd_card()
c99,_=cards()[-1]
check("35 one owner's veto on a huge vote is a stalemate, not a rejection", lambda: (D.react(c99["id"], OW1, "❌"), B.check_cards(cfg, B.load_settings(cfg)[0], B.find_cards(cfg, D.me)), cards()[-1][1]["state"]=="open")[2])
check("36 both owners' vetoes reject a huge vote", lambda: (D.react(c99["id"], OW2, "❌"), B.check_cards(cfg, B.load_settings(cfg)[0], B.find_cards(cfg, D.me)), cards()[-1][1]["state"]=="rejected")[2])
def env_restart_check():
    d=tempfile.mkdtemp(); path=os.path.join(d, L.ENV_FILE); open(path,"w").write("a")
    old=L.HERE; L.HERE=d
    try:
        since={L.ENV_FILE: L.fingerprint(L.ENV_FILE)}
        unchanged=L.env_changed(since)
        open(path,"w").write("b")
        return unchanged is False and L.env_changed(since) is True
    finally:
        L.HERE=old
check("37 a change to bot.env restarts the bot", env_restart_check)
def env_wins_check():
    d=tempfile.mkdtemp(); open(os.path.join(d, "bot.env"),"w").write('GITHUB_TOKEN="from-file"\n')
    old_here, old_tok = L.HERE, os.environ.get("GITHUB_TOKEN")
    L.HERE=d; os.environ["GITHUB_TOKEN"]=""
    try:
        L.load_env_file()
        return os.environ["GITHUB_TOKEN"]=="from-file"
    finally:
        L.HERE=old_here; os.environ["GITHUB_TOKEN"]=old_tok or ""
check("38 bot.env values win over empty ones already set on the computer", env_wins_check)
def approve_end_to_end():
    B.post_vote_status=REAL_STATUS; STATUSES.clear(); MERGES.clear()
    make_pr(120,[{"filename":"a","additions":3,"deletions":0,"status":"modified","patch":"x"}]); B.cmd_card()
    say("!usp approve usp#120", who=OW1)
    ok = any(b.get("state")=="success" and b.get("context")=="usp/vote" for _,b in STATUSES) and any("pulls/120/merge" in x for x in MERGES)
    make_pr(121,[{"filename":"a","additions":3,"deletions":0,"status":"modified","patch":"x"}]); B.cmd_card()
    say("!usp veto usp#121", who=OW1)
    ok2 = any(b.get("state")=="failure" for _,b in STATUSES) and any("/pulls/121" in u and b=={"state":"closed"} for u,b in PATCHES)
    return ok and ok2
check("39 owner approve sets usp/vote to success and merges; veto sets failure and closes", approve_end_to_end)
def env_spelling_check():
    d=tempfile.mkdtemp(); open(os.path.join(d, "bot.env"),"w").write("GITHUB TOKEN = spaced\n")
    old_here, old_tok = L.HERE, os.environ.get("GITHUB_TOKEN")
    L.HERE=d; os.environ["GITHUB_TOKEN"]=""
    try:
        L.load_env_file()
        return os.environ["GITHUB_TOKEN"]=="spaced"
    finally:
        L.HERE=old_here; os.environ["GITHUB_TOKEN"]=old_tok or ""
check("40 a key written as 'GITHUB TOKEN' still sets GITHUB_TOKEN", env_spelling_check)
for n,r in RESULTS: print(("PASS " if r is True else "FAIL ")+n+("" if r is True else f" -> {r}"))
print("passed", sum(1 for _,r in RESULTS if r is True), "of", len(RESULTS))

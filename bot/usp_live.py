#!/usr/bin/env python3
"""Keeps the USP bot online: answers !usp commands and counts votes the moment they happen.

Run it on any computer that stays on:  python usp_live.py
To check it connects and then stop:    python usp_live.py --for 90
To stop a copy that's running:          python usp_live.py --stop
It reads DISCORD_BOT_TOKEN, DISCORD_OWNER_IDS and DISCORD_CHANNEL_IDS from the environment, or from a
file called bot.env next to this one (one KEY=value per line). Never commit bot.env.

While it runs, the 15-minute GitHub check stands back. When it stops, the GitHub check takes over again.
Standard library only.
"""
import base64, hashlib, json, os, queue, random, re, socket, ssl, struct, sys, threading, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import usp_bot as B

GATEWAY = "gateway.discord.gg"
INTENTS = 1 | 512 | 1024 | 32768  # guilds, server messages, server message reactions, message content
FATAL = {4004: "the bot token is wrong (reset it and update bot.env)",
         4013: "the gateway intents are invalid",
         4014: "Message Content Intent is off (turn it on in the developer portal, Bot page)"}
CHECK_EVERY = 60  # seconds between timer checks; also how often it tells the GitHub check it's alive
SWEEP_EVERY = 60  # seconds between sweeps for owners' pull requests that are still waiting to merge
STUCK_AFTER = 90  # longest the bot waits on one command or check before moving on


class Closed(Exception):
    def __init__(self, code):
        super().__init__(f"closed with code {code}")
        self.code = code


class WebSocket:
    """Just enough of a websocket client for Discord's gateway."""

    def __init__(self, host, path):
        raw = socket.create_connection((host, 443), timeout=30)
        self.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\nUser-Agent: {B.UA}\r\n\r\n").encode())
        self.buf = b""
        while b"\r\n\r\n" not in self.buf:
            self._fill()
        head, self.buf = self.buf.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise ConnectionError("gateway refused the connection")
        self.sock.settimeout(None)
        self.lock = threading.Lock()

    def _fill(self):
        chunk = self.sock.recv(65536)
        if not chunk:
            raise Closed(1006)
        self.buf += chunk

    def _take(self, n):
        while len(self.buf) < n:
            self._fill()
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self):
        parts, kind = [], None
        while True:
            b1, b2 = self._take(2)
            op, n = b1 & 0x0F, b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._take(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._take(8))[0]
            mask = self._take(4) if b2 & 0x80 else None
            data = self._take(n)
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if op == 8:
                raise Closed(struct.unpack(">H", data[:2])[0] if len(data) >= 2 else 1005)
            if op == 9:
                self._send(10, data)
                continue
            if op == 10:
                continue
            if op in (1, 2):
                kind, parts = op, [data]
            elif op == 0:
                parts.append(data)
            if b1 & 0x80 and kind:
                return b"".join(parts).decode()

    def _send(self, op, data):
        mask = os.urandom(4)
        n = len(data)
        head = bytes([0x80 | op])
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        body = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        with self.lock:
            self.sock.sendall(head + mask + body)

    def send(self, obj):
        self._send(1, json.dumps(obj).encode())

    def close(self):
        try:
            self._send(8, struct.pack(">H", 1000))
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass


def gateway(token, events, online):
    """One connection. Puts (event name, data) on the queue until the connection ends."""
    ws = WebSocket(GATEWAY, "/?v=10&encoding=json")
    stop = threading.Event()
    try:
        hello = json.loads(ws.recv())
        every = hello["d"]["heartbeat_interval"] / 1000
        seq, acked = [None], [True]

        def beat():
            stop.wait(every * random.random())
            while not stop.is_set():
                if not acked[0]:  # Discord stopped answering: drop the connection and reconnect
                    ws.close()
                    return
                acked[0] = False
                try:
                    ws.send({"op": 1, "d": seq[0]})
                except Exception:
                    return
                stop.wait(every)

        threading.Thread(target=beat, daemon=True).start()
        ws.send({"op": 2, "d": {"token": token, "intents": INTENTS,
                                "properties": {"os": sys.platform, "browser": "usp-bot", "device": "usp-bot"},
                                "presence": {"status": "online", "afk": False, "since": None,
                                             "activities": [{"name": "USP votes", "type": 3}]}}})
        while True:
            p = json.loads(ws.recv())
            if p.get("s") is not None:
                seq[0] = p["s"]
            if p["op"] == 11:
                acked[0] = True
            elif p["op"] == 1:
                ws.send({"op": 1, "d": seq[0]})
            elif p["op"] in (7, 9):  # Discord asked for a fresh connection
                return
            elif p["op"] == 0:
                if p["t"] == "READY":
                    online.set()
                    print("Connected: the bot shows as online.")
                events.put((p["t"], p["d"]))
    finally:
        online.clear()
        stop.set()
        ws.close()


class Live:
    def __init__(self, cfg):
        self.cfg = cfg
        self.settings, self.sid, self.me = B.load_settings(cfg)
        self.chans = set(cfg["ch"].values())
        self.seen = set()
        self.online = threading.Event()
        self.synced = False  # caught up on commands sent while it was offline
        self.last_sweep = 0

    def save(self):
        B.save_settings(self.cfg, self.settings, self.sid)

    def catch_up(self):
        B.ensure_help(self.cfg, self.me)
        cards = B.find_cards(self.cfg, self.me)
        n = B.read_commands(self.cfg, self.settings, cards, B.now_ms(), self.seen)
        B.check_requests(self.cfg, self.settings, cards)
        B.check_cards(self.cfg, self.settings, cards)
        self.synced = True
        self.settings["live"] = True
        self.save()
        print(f"Caught up ({n} command(s) sent while offline).")

    def on_message(self, d):
        if d.get("channel_id") not in self.chans or d["id"] in self.seen:
            return
        self.seen.add(d["id"])
        before = json.dumps(self.settings, sort_keys=True)
        if B.run_command(self.cfg, self.settings, B.find_cards(self.cfg, self.me), d):
            print("Answered a command.")
            if json.dumps(self.settings, sort_keys=True) != before:
                self.save()

    def on_reaction(self, d):
        if d.get("channel_id") not in self.chans or d.get("user_id") == self.me:
            return
        m = B.dc("GET", f"/channels/{d['channel_id']}/messages/{d['message_id']}")
        if m["author"]["id"] != self.me:
            return
        m.setdefault("channel_id", d["channel_id"])
        before = json.dumps(self.settings, sort_keys=True)
        if B.answer_request(self.cfg, self.settings, B.find_cards(self.cfg, self.me), m):
            print("Answered a request.")
            if json.dumps(self.settings, sort_keys=True) != before:
                self.save()
            return
        if d["channel_id"] != self.cfg["ch"]["voting"] or not m.get("embeds"):
            return
        st = B.parse_card(m["embeds"][0])
        if st and st["state"] == "open" and B.check_card(self.cfg, self.settings, m, st, B.now_ms() // 1000):
            print("A vote was decided.")

    def check_in(self):
        """Timer check, and moves the cursor so the GitHub check knows this bot is alive."""
        B.check_cards(self.cfg, self.settings, B.find_cards(self.cfg, self.me))
        B.check_summary_requests(self.cfg)
        if time.time() - self.last_sweep >= SWEEP_EVERY:
            self.last_sweep = time.time()
            B.sweep_automerge(self.cfg, self.settings)
        if self.online.is_set() and self.synced:
            self.settings["cursor"] = max(self.settings["cursor"], B.now_ms() - 10_000)
            self.settings["live"] = True
            self.save()
        if len(self.seen) > 5000:
            self.seen = set(sorted(self.seen, key=int)[-1000:])

    def work(self, events):
        last = 0
        while True:
            try:
                name, d = events.get(timeout=5)
            except queue.Empty:
                name, d = None, None
            if name == "READY":
                self.synced = False
                self.guarded(self.catch_up)
            elif name == "MESSAGE_CREATE" and self.synced:
                self.guarded(self.on_message, d)
            elif name in ("MESSAGE_REACTION_ADD", "MESSAGE_REACTION_REMOVE") and self.synced:
                self.guarded(self.on_reaction, d)
            if time.time() - last >= CHECK_EVERY:
                last = time.time()
                self.guarded(self.check_in)

    def guarded(self, fn, *args):
        """Runs one job, but stops waiting after STUCK_AFTER seconds so one slow job can't freeze the bot."""
        def run():
            try:
                fn(*args)
            except Exception as e:
                print(f"Something failed ({type(e).__name__}: {e}); carrying on.")
        t = threading.Thread(target=run, daemon=True)
        t.start()
        t.join(STUCK_AFTER)
        if t.is_alive():
            print(f"A job took over {STUCK_AFTER}s; carrying on without it.")


HERE = os.path.dirname(os.path.abspath(__file__))
LOCK_PORT = 47613  # a local port held while the bot runs, so only one copy runs and --stop can reach it


def load_env_file():
    path = os.path.join(HERE, "bot.env")
    if not os.path.exists(path):
        return
    names = []
    for line in open(path, encoding="utf-8-sig"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            k = k.strip().removeprefix("export ").strip()
            k = re.sub(r"[\s-]+", "_", k).upper()  # "GITHUB TOKEN" or "github-token" still means GITHUB_TOKEN
            # bot.env wins: an empty or old value set elsewhere on the computer used to hide the token
            os.environ[k] = v.strip().strip('"\'')
            names.append(k + ("" if os.environ[k] else " (empty)"))
    print("Read from bot.env: " + (", ".join(names) or "nothing"))  # names only, never values


def hold_lock(stop):
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
    except OSError:
        return None
    s.listen(1)

    def serve():
        while not stop.is_set():
            c, _ = s.accept()
            with c:
                if c.recv(16) == b"stop":
                    stop.set()

    threading.Thread(target=serve, daemon=True).start()
    return s


def connect_loop(live, events, stop):
    wait = 1
    while not stop.is_set():
        started = time.time()
        try:
            gateway(os.environ["DISCORD_BOT_TOKEN"], events, live.online)
            print("Reconnecting...")
        except Closed as e:
            if e.code in FATAL:
                print(f"Stopped: {FATAL[e.code]}.")
                stop.set()
                return
            print(f"Connection dropped ({e.code}); reconnecting.")
        except (OSError, ConnectionError, ValueError) as e:
            print(f"Connection problem ({type(e).__name__}); retrying.")
        wait = 1 if time.time() - started > 60 else min(wait * 2, 60)
        stop.wait(wait)


WATCHED = ("usp_bot.py", "usp_live.py")


def fingerprint(name):
    """What the bot's own file holds now. Content, not modification time, so a copy always counts."""
    with open(os.path.join(HERE, name), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def changed_files(since):
    """The bot's own files whose contents changed, so a new version can load without a restart."""
    return [n for n in WATCHED if fingerprint(n) != since[n]]


ENV_FILE = "bot.env"  # the secrets file: read only at startup, so a change needs a restart too


def env_changed(since):
    """True when bot.env was changed or replaced since the bot started."""
    try:
        return fingerprint(ENV_FILE) != since[ENV_FILE]
    except OSError:
        return False


def reload_if_updated(live, lock, since):
    """Restarts this process on the new code, once the new files compile. Returns only if nothing changed."""
    if env_changed(since):
        print("bot.env changed; restarting so the new settings load.")
        restart_self(live, lock)
    if not changed_files(since):
        return
    for n in WATCHED:
        try:
            compile(open(os.path.join(HERE, n), encoding="utf-8").read(), n, "exec")
        except (OSError, SyntaxError) as e:
            print(f"{n} changed but doesn't load yet ({type(e).__name__}); keeping the current code.")
            for k in WATCHED:
                since[k] = fingerprint(k)
            return
    print("New bot code found; reloading.")
    restart_self(live, lock)


def restart_self(live, lock):
    """Starts a fresh copy of this bot and ends this one. The copy takes over the lock once this one lets go."""
    live.settings["live"] = False
    if live.synced:
        live.settings["cursor"] = max(live.settings["cursor"], B.now_ms() - 2000)
    try:
        live.save()
    except Exception:
        pass
    lock.close()  # free the port so the new copy can take it
    args = [sys.executable, os.path.abspath(sys.argv[0])] + sys.argv[1:]
    if os.name == "nt":  # Windows execv drops the quotes around paths with spaces, so start a fresh copy instead
        import subprocess
        subprocess.Popen(args, cwd=HERE, close_fds=True,
                         creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
        os._exit(0)
    os.execv(sys.executable, args)


WATCHDOG_AFTER = 180  # restart the bot if it has been disconnected from Discord this long


def should_restart(offline_since, now):
    """True once the bot has been offline longer than WATCHDOG_AFTER seconds."""
    return offline_since is not None and now - offline_since > WATCHDOG_AFTER


def start_live(cfg, stop, pause=5):
    """Builds the bot's state, retrying with a growing pause while Discord can't be reached. None if stopped first."""
    wait = pause
    while not stop.is_set():
        try:
            return Live(cfg)
        except Exception as e:  # a network error here used to end the whole process
            print(f"Can't reach Discord yet ({type(e).__name__}); trying again in {wait}s.")
            stop.wait(wait)
            wait = min(wait * 2, 60)
    return None


def main():
    if sys.stdout is None:  # started hidden (pythonw): write a log next to this file instead
        sys.stdout = sys.stderr = open(os.path.join(HERE, "bot.log"), "a", encoding="utf-8", buffering=1)
    if "--stop" in sys.argv:
        try:
            socket.create_connection(("127.0.0.1", LOCK_PORT), timeout=3).sendall(b"stop")
            print("Told the running bot to stop.")
        except OSError:
            print("The bot isn't running.")
        return
    load_env_file()
    cfg = B.env_config()
    if not cfg:
        print("Missing DISCORD_BOT_TOKEN, DISCORD_OWNER_IDS or DISCORD_CHANNEL_IDS (put them in bot.env).")
        sys.exit(1)
    stop = threading.Event()
    lock = hold_lock(stop)
    if lock is None:
        print("The bot is already running on this computer.")
        return
    print(time.strftime("%Y-%m-%d %H:%M ") + "Starting the bot.")
    if "--for" in sys.argv:  # run for a while, then stop cleanly (used by the bot-live-check workflow)
        threading.Timer(float(sys.argv[sys.argv.index("--for") + 1]), stop.set).start()
    since = {n: fingerprint(n) for n in WATCHED}
    since[ENV_FILE] = fingerprint(ENV_FILE) if os.path.exists(os.path.join(HERE, ENV_FILE)) else None
    print("Watching " + ", ".join(WATCHED) + " for new code.")
    B.LIVE = True
    live = start_live(cfg, stop)
    if live is None:
        print("Bot stopped.")
        return
    events = queue.Queue()
    threading.Thread(target=live.work, args=(events,), daemon=True).start()
    threading.Thread(target=connect_loop, args=(live, events, stop), daemon=True).start()
    offline_since = None
    try:
        while not stop.wait(1):
            reload_if_updated(live, lock, since)
            if live.online.is_set():
                offline_since = None
            elif offline_since is None:
                offline_since = time.time()
            if should_restart(offline_since, time.time()):
                print(f"Offline for over {WATCHDOG_AFTER}s; restarting the bot.")
                restart_self(live, lock)
    except KeyboardInterrupt:
        pass
    except Exception as e:  # never leave the bot down after a crash: start again after a short pause
        print(f"Crashed ({type(e).__name__}); restarting in 10s.")
        time.sleep(10)
        restart_self(live, lock)
    live.settings["live"] = False  # hand back to the GitHub check straight away
    if live.synced:
        live.settings["cursor"] = max(live.settings["cursor"], B.now_ms() - 2000)
    try:
        live.save()
    except Exception:
        pass
    print("Bot stopped.")


if __name__ == "__main__":
    main()

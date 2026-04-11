"""PvP Arena — FastAPI main application with WebSocket hub (Gomoku edition)."""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_
from datetime import datetime
import json, asyncio, uuid

from database import init_db, SessionLocal
from models import User, Match, Achievement
from auth import hash_password, verify_password, create_access_token, decode_token
from game import Gomoku, GomokuBot

# ── Achievement definitions ──────────────────────────────────────────────────
ACHIEVEMENTS = {
    "first_blood":  {"name": "First Blood",  "emoji": "🏆", "desc": "Win your first match"},
    "on_fire":      {"name": "On Fire",      "emoji": "🔥", "desc": "Win 3 matches in a row"},
    "unbreakable":  {"name": "Unbreakable",  "emoji": "🛡️", "desc": "Win 5 without a loss"},
    "speed_demon":  {"name": "Speed Demon",  "emoji": "⚡", "desc": "Win in ≤ 11 moves"},
    "friendly":     {"name": "Friendly",     "emoji": "🤝", "desc": "Play 10 total matches"},
}


def _check_achievements(db: Session, user: User, won: bool = False, move_cnt: int = 99):
    existing = {a.achievement_type for a in db.query(Achievement).filter(Achievement.user_id == user.id).all()}
    new = []
    checks = {
        "first_blood": user.wins >= 1,
        "on_fire":     user.win_streak >= 3,
        "unbreakable": user.max_win_streak >= 5,
        "friendly":    user.total_matches >= 10,
    }
    if won and move_cnt <= 11:
        checks["speed_demon"] = True
    for k, cond in checks.items():
        if k not in existing and cond:
            db.add(Achievement(user_id=user.id, achievement_type=k))
            new.append(k)
    return new


# ── Connection manager ───────────────────────────────────────────────────────
class Hub:
    def __init__(self):
        self.conns: dict[int, dict] = {}          # user_id → {ws, username}
        self.games: dict[str, dict] = {}          # game_id → game session
        self.challenges: dict[str, dict] = {}     # challenge_id → info

    async def connect(self, uid: int, name: str, ws: WebSocket):
        await ws.accept()
        self.conns[uid] = {"ws": ws, "username": name}
        await self._broadcast_online()

    def disconnect(self, uid: int):
        self.conns.pop(uid, None)

    async def send(self, uid: int, msg: dict):
        c = self.conns.get(uid)
        if c:
            try: await c["ws"].send_text(json.dumps(msg))
            except: pass

    async def _broadcast_online(self):
        players = [{"user_id": u, "username": d["username"]} for u, d in self.conns.items()]
        txt = json.dumps({"type": "online_list", "players": players})
        for d in self.conns.values():
            try: await d["ws"].send_text(txt)
            except: pass

    async def broadcast_chat(self, uid: int, name: str, text: str):
        msg = json.dumps({"type": "chat_message", "user_id": uid, "username": name,
                          "text": text, "timestamp": datetime.now().strftime("%H:%M")})
        for d in self.conns.values():
            try: await d["ws"].send_text(msg)
            except: pass


hub = Hub()

# ── FastAPI app ──────────────────────────────────────────────────────────────
app = FastAPI(title="PvP Arena — Gomoku")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def startup():
    init_db()


app.mount("/static", StaticFiles(directory="frontend"), name="static")


@app.get("/")
async def root():
    return FileResponse("frontend/index.html")


# ── Auth REST endpoints ──────────────────────────────────────────────────────
@app.post("/api/register")
async def register(req: Request):
    d = await req.json()
    name, pwd = d.get("username", "").strip(), d.get("password", "").strip()
    if not name or not pwd:
        raise HTTPException(400, "Username and password required")
    if len(name) < 2 or len(name) > 20:
        raise HTTPException(400, "Username must be 2-20 chars")
    if len(pwd) < 3:
        raise HTTPException(400, "Password ≥ 3 chars")
    db = SessionLocal()
    try:
        if db.query(User).filter(User.username == name).first():
            raise HTTPException(400, "Username taken")
        u = User(username=name, password_hash=hash_password(pwd))
        db.add(u); db.commit(); db.refresh(u)
        token = create_access_token({"user_id": u.id, "username": u.username})
        return {"token": token, "user_id": u.id, "username": u.username}
    finally:
        db.close()


@app.post("/api/login")
async def login(req: Request):
    d = await req.json()
    name, pwd = d.get("username", "").strip(), d.get("password", "").strip()
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == name).first()
        if not u or not verify_password(pwd, u.password_hash):
            raise HTTPException(401, "Invalid credentials")
        token = create_access_token({"user_id": u.id, "username": u.username})
        return {"token": token, "user_id": u.id, "username": u.username}
    finally:
        db.close()


# ── Data REST endpoints ──────────────────────────────────────────────────────
@app.get("/api/leaderboard")
async def leaderboard():
    db = SessionLocal()
    try:
        rows = db.query(User).filter(User.total_matches >= 1).order_by(desc(User.wins)).limit(20).all()
        return [{"user_id": u.id, "username": u.username, "wins": u.wins, "losses": u.losses,
                 "draws": u.draws, "total": u.total_matches,
                 "wr": round(u.wins / u.total_matches * 100, 1) if u.total_matches else 0,
                 "streak": u.max_win_streak} for u in rows]
    finally:
        db.close()


@app.get("/api/stats/{uid}")
async def stats(uid: int):
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.id == uid).first()
        if not u: raise HTTPException(404)
        achs = db.query(Achievement).filter(Achievement.user_id == uid).all()
        return {"username": u.username, "wins": u.wins, "losses": u.losses, "draws": u.draws,
                "total": u.total_matches,
                "wr": round(u.wins / u.total_matches * 100, 1) if u.total_matches else 0,
                "streak": u.win_streak, "max_streak": u.max_win_streak,
                "achievements": [{"type": a.achievement_type, "at": a.unlocked_at.isoformat()} for a in achs]}
    finally:
        db.close()


@app.get("/api/history/{uid}")
async def history(uid: int):
    db = SessionLocal()
    try:
        rows = db.query(Match).filter(or_(Match.player1_id == uid, Match.player2_id == uid)) \
            .order_by(desc(Match.created_at)).limit(20).all()
        out = []
        for m in rows:
            opp_id = m.player2_id if m.player1_id == uid else m.player1_id
            opp = db.query(User).filter(User.id == opp_id).first() if opp_id else None
            res = "draw" if m.is_draw else ("win" if m.winner_id == uid else "loss")
            out.append({"opponent": opp.username if opp else "Bot", "result": res,
                        "moves": m.moves_count, "pve": m.is_pve, "date": m.created_at.isoformat()})
        return out
    finally:
        db.close()


@app.get("/api/achievements")
async def all_achievements():
    return ACHIEVEMENTS


# ── Helpers ──────────────────────────────────────────────────────────────────
def _in_game(uid):
    for gid, g in hub.games.items():
        if uid in g.get("pids", []):
            return gid
    return None


def _record_result(winner_id, loser_id, game_data, is_forfeit=False):
    """Update stats, create match row, return new achievements for winner."""
    db = SessionLocal()
    try:
        game = game_data["game"]
        w = db.query(User).filter(User.id == winner_id).first()
        l = db.query(User).filter(User.id == loser_id).first()
        if w:
            w.wins += 1; w.total_matches += 1; w.win_streak += 1
            if w.win_streak > w.max_win_streak: w.max_win_streak = w.win_streak
        if l:
            l.losses += 1; l.total_matches += 1; l.win_streak = 0
        db.add(Match(player1_id=game_data["sym"]["X"], player2_id=game_data["sym"]["O"],
                     winner_id=winner_id, moves_count=game.moves_count, is_pve=False))
        nw = _check_achievements(db, w, True, game.moves_count) if w else []
        if l: _check_achievements(db, l)
        db.commit()
        return nw
    finally:
        db.close()


def _record_draw(game_data):
    db = SessionLocal()
    try:
        game = game_data["game"]
        for pid in game_data["pids"]:
            u = db.query(User).filter(User.id == pid).first()
            if u:
                u.draws += 1; u.total_matches += 1; u.win_streak = 0
        db.add(Match(player1_id=game_data["sym"]["X"], player2_id=game_data["sym"]["O"],
                     is_draw=True, moves_count=game.moves_count, is_pve=False))
        for pid in game_data["pids"]:
            u = db.query(User).filter(User.id == pid).first()
            if u: _check_achievements(db, u)
        db.commit()
    finally:
        db.close()


async def _finish_pvp(game_id, game_data, state):
    game = game_data["game"]
    if game.is_draw:
        _record_draw(game_data)
        for pid in game_data["pids"]:
            await hub.send(pid, {"type": "game_over", "game_id": game_id, "result": "draw",
                                 "state": state, "new_achievements": []})
    else:
        wid = game_data["sym"][game.winner]
        lid = [p for p in game_data["pids"] if p != wid][0]
        nachs = _record_result(wid, lid, game_data)
        for pid in game_data["pids"]:
            r = "win" if pid == wid else "loss"
            na = [ACHIEVEMENTS[a] for a in nachs] if pid == wid else []
            await hub.send(pid, {"type": "game_over", "game_id": game_id, "result": r,
                                 "state": state, "new_achievements": na})
    hub.games.pop(game_id, None)


async def _finish_pve(game_id, game_data, state, uid):
    game = game_data["game"]
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.id == uid).first()
        if game.is_draw:
            res = "draw"
            if u: u.draws += 1; u.total_matches += 1; u.win_streak = 0
            wid = None
        elif game.winner == "X":
            res = "win"
            if u:
                u.wins += 1; u.total_matches += 1; u.win_streak += 1
                if u.win_streak > u.max_win_streak: u.max_win_streak = u.win_streak
            wid = uid
        else:
            res = "loss"
            if u: u.losses += 1; u.total_matches += 1; u.win_streak = 0
            wid = None
        db.add(Match(player1_id=uid, winner_id=wid, is_draw=game.is_draw,
                     moves_count=game.moves_count, is_pve=True))
        nachs = _check_achievements(db, u, res == "win", game.moves_count) if u else []
        db.commit()
    finally:
        db.close()
    await hub.send(uid, {"type": "game_over", "game_id": game_id, "result": res,
                         "state": state, "is_pve": True,
                         "new_achievements": [ACHIEVEMENTS[a] for a in nachs]})
    hub.games.pop(game_id, None)


# ── WebSocket handler ────────────────────────────────────────────────────────
@app.websocket("/ws/{token}")
async def ws_endpoint(websocket: WebSocket, token: str):
    payload = decode_token(token)
    if not payload:
        await websocket.close(code=4001); return
    uid, uname = payload["user_id"], payload["username"]

    # kick old connection
    if uid in hub.conns:
        try: await hub.conns[uid]["ws"].close()
        except: pass
        hub.disconnect(uid)

    await hub.connect(uid, uname, websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            await _handle(uid, uname, msg)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WS error {uname}: {e}")
    finally:
        hub.disconnect(uid)
        await _on_disconnect(uid)
        await hub._broadcast_online()


async def _handle(uid, uname, msg):
    t = msg.get("type")

    # ── Chat ──
    if t == "chat_message":
        txt = msg.get("text", "").strip()
        if txt and len(txt) <= 500:
            await hub.broadcast_chat(uid, uname, txt)

    # ── Challenge ──
    elif t == "challenge":
        tid = msg.get("target_id")
        if tid == uid or tid not in hub.conns:
            await hub.send(uid, {"type": "error", "text": "Player unavailable"}); return
        if _in_game(uid):
            await hub.send(uid, {"type": "error", "text": "You are in a game"}); return
        if _in_game(tid):
            await hub.send(uid, {"type": "error", "text": "Player is in a game"}); return
        cid = str(uuid.uuid4())
        hub.challenges[cid] = {"from": uid, "to": tid, "name": uname}
        await hub.send(tid, {"type": "challenge_received", "challenge_id": cid,
                             "from_id": uid, "from_name": uname})
        await hub.send(uid, {"type": "challenge_sent", "challenge_id": cid,
                             "to_name": hub.conns[tid]["username"]})

    # ── Challenge response ──
    elif t == "challenge_response":
        cid = msg.get("challenge_id")
        acc = msg.get("accepted", False)
        ch = hub.challenges.pop(cid, None)
        if not ch: return
        if acc:
            gid = str(uuid.uuid4())
            game = Gomoku()
            hub.games[gid] = {"game": game, "sym": {"X": ch["from"], "O": ch["to"]},
                              "pids": [ch["from"], ch["to"]],
                              "names": {ch["from"]: ch["name"], ch["to"]: uname}}
            for sym, pid in hub.games[gid]["sym"].items():
                opp = hub.games[gid]["names"][[p for p in hub.games[gid]["pids"] if p != pid][0]]
                await hub.send(pid, {"type": "game_start", "game_id": gid, "your_symbol": sym,
                                     "opponent": opp, "state": game.get_state()})
        else:
            await hub.send(ch["from"], {"type": "challenge_declined", "from_name": uname})

    # ── PvP move ──
    elif t == "game_move":
        gid = msg.get("game_id")
        gd = hub.games.get(gid)
        if not gd or gd.get("pve"): return
        sym = None
        for s, p in gd["sym"].items():
            if p == uid: sym = s; break
        if not sym: return
        if gd["game"].make_move(msg.get("row"), msg.get("col"), sym):
            st = gd["game"].get_state()
            if gd["game"].game_over:
                await _finish_pvp(gid, gd, st)
            else:
                for pid in gd["pids"]:
                    await hub.send(pid, {"type": "game_update", "game_id": gid, "state": st})

    # ── PvE start ──
    elif t == "pve_start":
        if _in_game(uid):
            await hub.send(uid, {"type": "error", "text": "Already in a game"}); return
        diff = msg.get("difficulty", "easy")
        gid = str(uuid.uuid4())
        game = Gomoku()
        hub.games[gid] = {"game": game, "sym": {"X": uid, "O": "bot"}, "pids": [uid],
                          "names": {uid: uname}, "pve": True, "diff": diff}
        await hub.send(uid, {"type": "game_start", "game_id": gid, "your_symbol": "X",
                             "opponent": f"Bot ({diff.title()})", "is_pve": True,
                             "state": game.get_state()})

    # ── PvE move ──
    elif t == "pve_move":
        gid = msg.get("game_id")
        gd = hub.games.get(gid)
        if not gd or not gd.get("pve"): return
        game = gd["game"]
        if not game.make_move(msg.get("row"), msg.get("col"), "X"): return
        st = game.get_state()
        if game.game_over:
            await _finish_pve(gid, gd, st, uid); return
        # Send player move update
        await hub.send(uid, {"type": "game_update", "game_id": gid, "state": st})
        await asyncio.sleep(0.4)
        bot = GomokuBot.get_move(game.board, gd.get("diff", "easy"))
        if bot:
            game.make_move(bot[0], bot[1], "O")
        st = game.get_state()
        if game.game_over:
            await _finish_pve(gid, gd, st, uid)
        else:
            await hub.send(uid, {"type": "game_update", "game_id": gid, "state": st})

    # ── Leave game ──
    elif t == "leave_game":
        gid = msg.get("game_id")
        gd = hub.games.get(gid)
        if not gd: return
        if gd.get("pve"):
            hub.games.pop(gid, None)
            await hub.send(uid, {"type": "game_left"})
        else:
            game = gd["game"]
            if not game.game_over:
                other = [p for p in gd["pids"] if p != uid]
                if other:
                    oid = other[0]
                    nachs = _record_result(oid, uid, gd, is_forfeit=True)
                    await hub.send(oid, {"type": "game_over", "game_id": gid, "result": "win",
                                         "reason": "opponent_left", "state": game.get_state(),
                                         "new_achievements": [ACHIEVEMENTS[a] for a in nachs]})
            hub.games.pop(gid, None)
            await hub.send(uid, {"type": "game_left"})


async def _on_disconnect(uid):
    to_del = []
    for gid, gd in hub.games.items():
        if uid not in gd.get("pids", []): continue
        if gd.get("pve"):
            to_del.append(gid); continue
        game = gd["game"]
        if not game.game_over:
            other = [p for p in gd["pids"] if p != uid]
            if other:
                oid = other[0]
                nachs = _record_result(oid, uid, gd, is_forfeit=True)
                await hub.send(oid, {"type": "game_over", "game_id": gid, "result": "win",
                                     "reason": "opponent_disconnected", "state": game.get_state(),
                                     "new_achievements": [ACHIEVEMENTS[a] for a in nachs]})
        to_del.append(gid)
    for g in to_del:
        hub.games.pop(g, None)
    # clean challenges
    rm = [c for c, v in hub.challenges.items() if v["from"] == uid or v["to"] == uid]
    for c in rm:
        hub.challenges.pop(c, None)

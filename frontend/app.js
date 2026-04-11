/* ═══════════════════════════════════════════════════════════
   PvP Arena — Gomoku Client Application
   ═══════════════════════════════════════════════════════════ */

// ── State ──
let user = null;            // { token, user_id, username }
let ws = null;
let gameId = null;
let mySymbol = null;
let isPvE = false;
let pendingChallengeId = null;
let boardSize = 15;

const ACHS = {
    first_blood: { name: "First Blood", emoji: "🏆", desc: "Win your first match" },
    on_fire:     { name: "On Fire",     emoji: "🔥", desc: "Win 3 in a row" },
    unbreakable: { name: "Unbreakable", emoji: "🛡️", desc: "Win 5 without a loss" },
    speed_demon: { name: "Speed Demon", emoji: "⚡", desc: "Win in ≤ 11 moves" },
    friendly:    { name: "Friendly",    emoji: "🤝", desc: "Play 10 matches" },
};

// ── Init ──
document.addEventListener("DOMContentLoaded", () => {
    const saved = localStorage.getItem("pvp_user");
    if (saved) {
        user = JSON.parse(saved);
        document.getElementById("user-badge").textContent = user.username;
        showView("lobby-view");
        connectWS();
    }
    bindEvents();
});

// ── Event Bindings ──
function bindEvents() {
    // Auth tabs
    document.querySelectorAll(".auth-tab").forEach(tab => {
        tab.addEventListener("click", () => {
            document.querySelectorAll(".auth-tab").forEach(t => t.classList.remove("active"));
            tab.classList.add("active");
            const mode = tab.dataset.tab;
            document.getElementById("auth-btn-text").textContent = mode === "login" ? "Login" : "Register";
            document.getElementById("auth-error").textContent = "";
        });
    });

    // Auth form
    document.getElementById("auth-form").addEventListener("submit", handleAuth);

    // Lobby tabs
    document.querySelectorAll(".tab-bar .tab").forEach(tab => {
        tab.addEventListener("click", () => {
            document.querySelectorAll(".tab-bar .tab").forEach(t => t.classList.remove("active"));
            document.querySelectorAll(".tab-content").forEach(p => p.classList.remove("active"));
            tab.classList.add("active");
            document.getElementById("panel-" + tab.dataset.panel).classList.add("active");
            if (tab.dataset.panel === "lb") loadLeaderboard();
            if (tab.dataset.panel === "hist") loadHistory();
            if (tab.dataset.panel === "ach") loadAchievements();
        });
    });

    // Chat
    document.getElementById("chat-form").addEventListener("submit", e => {
        e.preventDefault();
        const inp = document.getElementById("chat-input");
        const txt = inp.value.trim();
        if (txt && ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "chat_message", text: txt }));
            inp.value = "";
        }
    });

    // PvE
    document.getElementById("pve-easy-btn").addEventListener("click", () => startPvE("easy"));
    document.getElementById("pve-hard-btn").addEventListener("click", () => startPvE("hard"));

    // Stats
    document.getElementById("stats-btn").addEventListener("click", openStats);
    document.getElementById("stats-close").addEventListener("click", () => {
        document.getElementById("stats-modal").classList.add("hidden");
    });

    // Leave game
    document.getElementById("leave-btn").addEventListener("click", leaveGame);

    // Logout
    document.getElementById("logout-btn").addEventListener("click", () => {
        localStorage.removeItem("pvp_user");
        if (ws) ws.close();
        user = null;
        showView("auth-view");
    });

    // Challenge popup
    document.getElementById("accept-btn").addEventListener("click", () => {
        if (pendingChallengeId && ws) {
            ws.send(JSON.stringify({ type: "challenge_response", challenge_id: pendingChallengeId, accepted: true }));
        }
        document.getElementById("challenge-popup").classList.add("hidden");
        pendingChallengeId = null;
    });
    document.getElementById("decline-btn").addEventListener("click", () => {
        if (pendingChallengeId && ws) {
            ws.send(JSON.stringify({ type: "challenge_response", challenge_id: pendingChallengeId, accepted: false }));
        }
        document.getElementById("challenge-popup").classList.add("hidden");
        pendingChallengeId = null;
    });

    // Game over -> lobby
    document.getElementById("go-lobby-btn").addEventListener("click", () => {
        document.getElementById("gameover-modal").classList.add("hidden");
        showView("lobby-view");
        loadLeaderboard();
    });
}

// ── Auth ──
async function handleAuth(e) {
    e.preventDefault();
    const mode = document.querySelector(".auth-tab.active").dataset.tab;
    const username = document.getElementById("auth-username").value.trim();
    const password = document.getElementById("auth-password").value;
    const errEl = document.getElementById("auth-error");
    errEl.textContent = "";

    try {
        const res = await fetch(`/api/${mode}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password })
        });
        if (!res.ok) {
            const data = await res.json();
            errEl.textContent = data.detail || "Error";
            return;
        }
        const data = await res.json();
        user = data;
        localStorage.setItem("pvp_user", JSON.stringify(user));
        document.getElementById("user-badge").textContent = user.username;
        showView("lobby-view");
        connectWS();
    } catch (err) {
        errEl.textContent = "Connection error";
    }
}

// ── WebSocket ──
function connectWS() {
    if (ws) ws.close();
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws/${user.token}`);

    ws.onopen = () => {
        toast("Connected to server", "success");
        loadLeaderboard();
    };

    ws.onmessage = (e) => {
        const msg = JSON.parse(e.data);
        handleMsg(msg);
    };

    ws.onclose = () => {
        toast("Disconnected — reconnecting…", "error");
        setTimeout(() => { if (user) connectWS(); }, 3000);
    };

    ws.onerror = () => {};
}

function handleMsg(msg) {
    switch (msg.type) {
        case "online_list":    renderOnline(msg.players); break;
        case "chat_message":   renderChat(msg); break;
        case "challenge_received": showChallenge(msg); break;
        case "challenge_sent": toast(`Challenge sent to ${msg.to_name}`, "info"); break;
        case "challenge_declined": toast(`${msg.from_name} declined`, "info"); break;
        case "game_start":     onGameStart(msg); break;
        case "game_update":    onGameUpdate(msg); break;
        case "game_over":      onGameOver(msg); break;
        case "game_left":      showView("lobby-view"); loadLeaderboard(); break;
        case "error":          toast(msg.text, "error"); break;
    }
}

// ── Views ──
function showView(id) {
    document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
    document.getElementById(id).classList.add("active");
}

// ── Online List ──
function renderOnline(players) {
    document.getElementById("online-count").textContent = players.length;
    const el = document.getElementById("online-list");
    if (!players.length) { el.innerHTML = '<div class="empty">No one online yet</div>'; return; }
    el.innerHTML = players.map(p => {
        const isMe = p.user_id === user.user_id;
        return `<div class="player-row">
            <div class="player-info">
                <span class="player-dot"></span>
                <span class="player-name">${esc(p.username)}</span>
                ${isMe ? '<span class="player-you">(you)</span>' : ''}
            </div>
            ${isMe ? '' : `<button class="challenge-btn" onclick="challengePlayer(${p.user_id},'${esc(p.username)}')">⚔️ Fight</button>`}
        </div>`;
    }).join("");
}

function challengePlayer(targetId, targetName) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "challenge", target_id: targetId }));
    }
}

// ── Challenge Popup ──
function showChallenge(msg) {
    pendingChallengeId = msg.challenge_id;
    document.getElementById("challenge-text").textContent = `${msg.from_name} wants to fight you!`;
    document.getElementById("challenge-popup").classList.remove("hidden");
}

// ── Chat ──
function renderChat(msg) {
    const log = document.getElementById("chat-log");
    const div = document.createElement("div");
    div.className = "chat-msg";
    div.innerHTML = `<span class="chat-name">${esc(msg.username)}:</span>${esc(msg.text)}<span class="chat-time">${msg.timestamp}</span>`;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
}

// ── Game ──
function onGameStart(msg) {
    gameId = msg.game_id;
    mySymbol = msg.your_symbol;
    isPvE = !!msg.is_pve;
    boardSize = msg.state.board_size || 15;
    showView("game-view");

    const blackLabel = mySymbol === "X" ? user.username : msg.opponent;
    const whiteLabel = mySymbol === "O" ? user.username : msg.opponent;
    document.getElementById("hud-x").textContent = `⚫ ${blackLabel}`;
    document.getElementById("hud-o").textContent = `⚪ ${whiteLabel}`;

    renderBoard(msg.state);
}

function onGameUpdate(msg) {
    renderBoard(msg.state);
}

function renderBoard(state) {
    const board = document.getElementById("board");
    const size = state.board_size || 15;

    // Set CSS grid for the correct board size
    board.style.gridTemplateColumns = `repeat(${size}, 1fr)`;
    board.style.gridTemplateRows = `repeat(${size}, 1fr)`;

    board.innerHTML = "";

    const lastMove = state.last_move;
    const winCells = new Set((state.winning_cells || []).map(([r, c]) => `${r},${c}`));

    for (let r = 0; r < size; r++) {
        for (let c = 0; c < size; c++) {
            const cell = document.createElement("div");
            cell.className = "cell";
            const val = state.board[r][c];

            // Add intersection marker styling
            const isCorner = (r === 0 || r === size - 1) && (c === 0 || c === size - 1);
            const isEdgeH = r === 0 || r === size - 1;
            const isEdgeV = c === 0 || c === size - 1;

            // Star points (traditional Go board markers) for 15×15
            const starPoints = [
                [3, 3], [3, 7], [3, 11],
                [7, 3], [7, 7], [7, 11],
                [11, 3], [11, 7], [11, 11]
            ];
            const isStar = starPoints.some(([sr, sc]) => sr === r && sc === c);
            if (isStar && !val) {
                cell.classList.add("star-point");
            }

            if (val) {
                cell.classList.add("taken");
                const stone = document.createElement("div");
                stone.className = `stone ${val.toLowerCase()}`;
                cell.appendChild(stone);

                // Highlight last move
                if (lastMove && lastMove[0] === r && lastMove[1] === c) {
                    cell.classList.add("last-move");
                }

                // Highlight winning cells
                if (winCells.has(`${r},${c}`)) {
                    cell.classList.add("win-cell");
                }
            } else {
                cell.addEventListener("click", () => makeMove(r, c));

                // Show hover preview
                cell.addEventListener("mouseenter", () => {
                    if (!state.game_over && state.current_turn === mySymbol) {
                        cell.classList.add("hover-preview");
                        cell.dataset.preview = mySymbol === "X" ? "black" : "white";
                    }
                });
                cell.addEventListener("mouseleave", () => {
                    cell.classList.remove("hover-preview");
                    delete cell.dataset.preview;
                });
            }
            board.appendChild(cell);
        }
    }

    // Move counter
    const mc = document.getElementById("move-counter");
    if (mc) mc.textContent = `Moves: ${state.moves_count}`;

    // Turn indicator
    const ti = document.getElementById("turn-indicator");
    if (state.game_over) {
        ti.textContent = "";
    } else if (state.current_turn === mySymbol) {
        ti.textContent = "Your turn";
        ti.style.color = "var(--cyan)";
    } else {
        ti.textContent = "Opponent's turn…";
        ti.style.color = "var(--text3)";
    }

    // HUD highlights
    const hx = document.getElementById("hud-x");
    const ho = document.getElementById("hud-o");
    hx.classList.toggle("active-x", state.current_turn === "X" && !state.game_over);
    ho.classList.toggle("active-o", state.current_turn === "O" && !state.game_over);
    hx.classList.remove("active-o");
    ho.classList.remove("active-x");
}

function makeMove(row, col) {
    if (!ws || !gameId) return;
    const type = isPvE ? "pve_move" : "game_move";
    ws.send(JSON.stringify({ type, game_id: gameId, row, col }));
}

function onGameOver(msg) {
    // Render the final board state with winning cells
    if (msg.state) {
        renderBoard(msg.state);
    }

    setTimeout(() => {
        const modal = document.getElementById("gameover-modal");
        const icon = document.getElementById("go-icon");
        const title = document.getElementById("go-title");
        const text = document.getElementById("go-text");
        const achDiv = document.getElementById("go-achievements");

        if (msg.result === "win") {
            icon.textContent = "🎉";
            title.textContent = "Victory!";
            title.style.color = "var(--green)";
            text.textContent = msg.reason === "opponent_left" ? "Opponent left the game!" :
                               msg.reason === "opponent_disconnected" ? "Opponent disconnected!" : "You won the match!";
        } else if (msg.result === "loss") {
            icon.textContent = "😔";
            title.textContent = "Defeat";
            title.style.color = "var(--red)";
            text.textContent = "Better luck next time!";
        } else {
            icon.textContent = "🤝";
            title.textContent = "Draw";
            title.style.color = "var(--yellow)";
            text.textContent = "It's a tie!";
        }

        // Achievements
        achDiv.innerHTML = "";
        if (msg.new_achievements && msg.new_achievements.length) {
            msg.new_achievements.forEach(a => {
                achDiv.innerHTML += `<span class="go-ach">${a.emoji} ${a.name}</span>`;
            });
        }

        modal.classList.remove("hidden");
        gameId = null; mySymbol = null; isPvE = false;
    }, 800);
}

function leaveGame() {
    if (ws && gameId) {
        ws.send(JSON.stringify({ type: "leave_game", game_id: gameId }));
    }
    gameId = null; mySymbol = null; isPvE = false;
    showView("lobby-view");
    loadLeaderboard();
}

// ── PvE ──
function startPvE(difficulty) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "pve_start", difficulty }));
    }
}

// ── Leaderboard ──
async function loadLeaderboard() {
    try {
        const res = await fetch("/api/leaderboard");
        const data = await res.json();
        const el = document.getElementById("lb-body");
        if (!data.length) { el.innerHTML = '<div class="empty">No matches played yet</div>'; return; }
        el.innerHTML = `<table class="lb-table">
            <thead><tr><th>#</th><th>Player</th><th>W</th><th>L</th><th>D</th><th>WR</th><th>Streak</th></tr></thead>
            <tbody>${data.map((p, i) => `<tr>
                <td class="lb-rank ${i < 3 ? 'rank-' + (i + 1) : ''}">${i + 1}</td>
                <td>${esc(p.username)}</td>
                <td style="color:var(--green)">${p.wins}</td>
                <td style="color:var(--red)">${p.losses}</td>
                <td>${p.draws}</td>
                <td class="lb-wr">${p.wr}%</td>
                <td>${p.streak}🔥</td>
            </tr>`).join("")}</tbody>
        </table>`;
    } catch { }
}

// ── History ──
async function loadHistory() {
    if (!user) return;
    try {
        const res = await fetch(`/api/history/${user.user_id}`);
        const data = await res.json();
        const el = document.getElementById("hist-body");
        if (!data.length) { el.innerHTML = '<div class="empty">No matches yet</div>'; return; }
        el.innerHTML = data.map(m => {
            const d = new Date(m.date);
            const dateStr = d.toLocaleDateString() + " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
            return `<div class="hist-item">
                <span class="hist-dot ${m.result}"></span>
                <div class="hist-info">
                    <div class="hist-opp">${esc(m.opponent)} ${m.pve ? '🤖' : ''}</div>
                    <div class="hist-meta">${dateStr} · ${m.moves} moves</div>
                </div>
                <span class="hist-result ${m.result}">${m.result}</span>
            </div>`;
        }).join("");
    } catch { }
}

// ── Achievements ──
async function loadAchievements() {
    if (!user) return;
    try {
        const res = await fetch(`/api/stats/${user.user_id}`);
        const data = await res.json();
        const unlocked = new Set(data.achievements.map(a => a.type));
        const el = document.getElementById("ach-body");
        el.innerHTML = `<div class="ach-grid">${Object.entries(ACHS).map(([k, v]) => `
            <div class="ach-card ${unlocked.has(k) ? 'unlocked' : 'locked'}">
                <span class="ach-emoji">${v.emoji}</span>
                <div>
                    <div class="ach-name">${v.name}</div>
                    <div class="ach-desc">${v.desc}</div>
                </div>
            </div>`).join("")}</div>`;
    } catch { }
}

// ── Stats Modal ──
async function openStats() {
    if (!user) return;
    try {
        const res = await fetch(`/api/stats/${user.user_id}`);
        const s = await res.json();
        const el = document.getElementById("stats-body");
        const unlocked = new Set(s.achievements.map(a => a.type));
        el.innerHTML = `
            <div class="stats-grid">
                <div class="stat-box"><span class="stat-val cyan">${s.total}</span><span class="stat-lbl">Matches</span></div>
                <div class="stat-box"><span class="stat-val green">${s.wins}</span><span class="stat-lbl">Wins</span></div>
                <div class="stat-box"><span class="stat-val red">${s.losses}</span><span class="stat-lbl">Losses</span></div>
                <div class="stat-box"><span class="stat-val yellow">${s.wr}%</span><span class="stat-lbl">Win Rate</span></div>
                <div class="stat-box"><span class="stat-val cyan">${s.streak}</span><span class="stat-lbl">Current Streak</span></div>
                <div class="stat-box"><span class="stat-val green">${s.max_streak}</span><span class="stat-lbl">Best Streak</span></div>
            </div>
            <div class="stats-section">
                <h3>Achievements (${s.achievements.length}/${Object.keys(ACHS).length})</h3>
                <div class="ach-grid">${Object.entries(ACHS).map(([k, v]) => `
                    <div class="ach-card ${unlocked.has(k) ? 'unlocked' : 'locked'}">
                        <span class="ach-emoji">${v.emoji}</span>
                        <div><div class="ach-name">${v.name}</div><div class="ach-desc">${v.desc}</div></div>
                    </div>`).join("")}</div>
            </div>`;
        document.getElementById("stats-modal").classList.remove("hidden");
    } catch { }
}

function closeStats() {
    document.getElementById("stats-modal").classList.add("hidden");
}

// ── Utils ──
function esc(str) {
    const d = document.createElement("div");
    d.textContent = str;
    return d.innerHTML;
}

function toast(msg, type = "info") {
    const c = document.getElementById("toasts");
    const t = document.createElement("div");
    t.className = `toast ${type}`;
    t.textContent = msg;
    c.appendChild(t);
    setTimeout(() => { t.style.opacity = "0"; setTimeout(() => t.remove(), 300); }, 3500);
}

// Expose globals for onclick handlers in HTML
window.challengePlayer = challengePlayer;
window.startPvE = startPvE;
window.leaveGame = leaveGame;
window.closeStats = closeStats;

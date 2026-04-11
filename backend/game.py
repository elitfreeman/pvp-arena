"""Gomoku (五目並べ) game logic and heuristic bot.

Rules (standard Gomoku):
  - Board: 15×15
  - No fouls
  - Win = exactly 5 stones in a row (horizontal / vertical / diagonal)
  - Overline (6+ in a row) is NOT a win, but is allowed on the board
"""
import random

BOARD_SIZE = 15
WIN_LENGTH = 5

# Directions: (dr, dc)
DIRECTIONS = [(0, 1), (1, 0), (1, 1), (1, -1)]


class Gomoku:
    def __init__(self):
        self.board = [["" for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
        self.current_turn = "X"  # Black (X) goes first
        self.moves_count = 0
        self.winner = None
        self.is_draw = False
        self.game_over = False
        self.last_move = None

    def make_move(self, row: int, col: int, symbol: str) -> bool:
        if self.game_over or symbol != self.current_turn:
            return False
        if not (0 <= row < BOARD_SIZE and 0 <= col < BOARD_SIZE):
            return False
        if self.board[row][col] != "":
            return False

        self.board[row][col] = symbol
        self.moves_count += 1
        self.last_move = (row, col)

        if self._check_winner(row, col, symbol):
            self.winner = symbol
            self.game_over = True
        elif self.moves_count >= BOARD_SIZE * BOARD_SIZE:
            self.is_draw = True
            self.game_over = True
        else:
            self.current_turn = "O" if symbol == "X" else "X"
        return True

    def _check_winner(self, row: int, col: int, s: str) -> bool:
        """Check if placing stone at (row, col) creates exactly 5 in a row."""
        for dr, dc in DIRECTIONS:
            count = 1
            # Forward
            r, c = row + dr, col + dc
            while 0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE and self.board[r][c] == s:
                count += 1
                r += dr
                c += dc
            # Backward
            r, c = row - dr, col - dc
            while 0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE and self.board[r][c] == s:
                count += 1
                r -= dr
                c -= dc
            if count == WIN_LENGTH:
                return True
        return False

    def get_winning_cells(self) -> list:
        """Return the list of (row, col) that form the winning line."""
        if not self.winner or not self.last_move:
            return []
        row, col = self.last_move
        s = self.winner
        for dr, dc in DIRECTIONS:
            cells = [(row, col)]
            r, c = row + dr, col + dc
            while 0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE and self.board[r][c] == s:
                cells.append((r, c))
                r += dr
                c += dc
            r, c = row - dr, col - dc
            while 0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE and self.board[r][c] == s:
                cells.append((r, c))
                r -= dr
                c -= dc
            if len(cells) == WIN_LENGTH:
                return cells
        return []

    def get_state(self) -> dict:
        return {
            "board": self.board,
            "current_turn": self.current_turn,
            "moves_count": self.moves_count,
            "winner": self.winner,
            "is_draw": self.is_draw,
            "game_over": self.game_over,
            "last_move": self.last_move,
            "winning_cells": self.get_winning_cells() if self.winner else [],
            "board_size": BOARD_SIZE,
        }


# ── Bot ──────────────────────────────────────────────────────────────────────
# Heuristic evaluation bot — minimax is infeasible on 15×15.
# Evaluates each empty cell near existing stones and picks the best one.

# Pattern scores for the bot's evaluation
PATTERN_SCORES = {
    "five":          100000,
    "open_four":      15000,
    "half_four":       3000,
    "open_three":      3000,
    "half_three":       500,
    "open_two":         200,
    "half_two":          50,
}


class GomokuBot:
    @staticmethod
    def get_move(board: list, difficulty: str = "hard") -> tuple | None:
        candidates = GomokuBot._get_candidates(board)
        if not candidates:
            # First move — go near center
            return (BOARD_SIZE // 2, BOARD_SIZE // 2)

        if difficulty == "easy":
            # Easy: pick a random candidate, but still block obvious wins
            for r, c in candidates:
                board[r][c] = "O"
                if GomokuBot._is_winner(board, r, c, "O"):
                    board[r][c] = ""
                    return (r, c)
                board[r][c] = ""
            for r, c in candidates:
                board[r][c] = "X"
                if GomokuBot._is_winner(board, r, c, "X"):
                    board[r][c] = ""
                    return (r, c)
                board[r][c] = ""
            return random.choice(candidates)

        # Hard difficulty — heuristic evaluation
        best_score = -1
        best_move = candidates[0]

        for r, c in candidates:
            # Score for bot (O) placing here
            board[r][c] = "O"
            attack = GomokuBot._evaluate_position(board, r, c, "O")
            board[r][c] = ""

            # Score for blocking opponent (X) from placing here
            board[r][c] = "X"
            defense = GomokuBot._evaluate_position(board, r, c, "X")
            board[r][c] = ""

            score = attack * 1.1 + defense  # Slightly prefer attack
            if score > best_score:
                best_score = score
                best_move = (r, c)

        return best_move

    @staticmethod
    def _get_candidates(board, radius=2):
        """Get empty cells within `radius` of any placed stone."""
        has_stones = False
        nearby = set()
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                if board[r][c] != "":
                    has_stones = True
                    for dr in range(-radius, radius + 1):
                        for dc in range(-radius, radius + 1):
                            nr, nc = r + dr, c + dc
                            if 0 <= nr < BOARD_SIZE and 0 <= nc < BOARD_SIZE and board[nr][nc] == "":
                                nearby.add((nr, nc))
        if not has_stones:
            return []
        return list(nearby)

    @staticmethod
    def _is_winner(board, row, col, s):
        """Check if (row, col) gives exactly 5 in a row."""
        for dr, dc in DIRECTIONS:
            count = 1
            r, c = row + dr, col + dc
            while 0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE and board[r][c] == s:
                count += 1
                r += dr
                c += dc
            r, c = row - dr, col - dc
            while 0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE and board[r][c] == s:
                count += 1
                r -= dr
                c -= dc
            if count == WIN_LENGTH:
                return True
        return False

    @staticmethod
    def _evaluate_position(board, row, col, symbol):
        """Evaluate the value of a position for `symbol` after placing at (row, col)."""
        total = 0
        for dr, dc in DIRECTIONS:
            count = 1
            open_ends = 0

            # Forward
            r, c = row + dr, col + dc
            while 0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE and board[r][c] == symbol:
                count += 1
                r += dr
                c += dc
            if 0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE and board[r][c] == "":
                open_ends += 1

            # Backward
            r, c = row - dr, col - dc
            while 0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE and board[r][c] == symbol:
                count += 1
                r -= dr
                c -= dc
            if 0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE and board[r][c] == "":
                open_ends += 1

            if count >= 5:
                total += PATTERN_SCORES["five"]
            elif count == 4:
                if open_ends == 2:
                    total += PATTERN_SCORES["open_four"]
                elif open_ends == 1:
                    total += PATTERN_SCORES["half_four"]
            elif count == 3:
                if open_ends == 2:
                    total += PATTERN_SCORES["open_three"]
                elif open_ends == 1:
                    total += PATTERN_SCORES["half_three"]
            elif count == 2:
                if open_ends == 2:
                    total += PATTERN_SCORES["open_two"]
                elif open_ends == 1:
                    total += PATTERN_SCORES["half_two"]

        return total

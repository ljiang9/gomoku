#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gomoku -- 五子棋人机对战(纯本地, 仅标准库)

玩法: 你执黑(●)先行, AI 执白(○)后行, 横/竖/斜连成 5 子即胜。
坐标: 列用字母(A 起), 行用数字, 如 H8 表示第 H 列第 8 行。

AI 为威胁启发式(非 minimax、无搜索树), 落子优先级(从高到低):
  1. 自己能连五      -> 直接取胜
  2. 对方下手能连五  -> 堵必胜点
  3. 堵对方的四(活四/冲四)
  4. 自己造活四
  5. 堵对方的活三
  6. 自己造活三
  7. 攻守综合评分最高点(进攻权重略高于防守, 靠近中心优先,
     微小随机量打破平局)
"""

import argparse
import random
import re
import sys

EMPTY, BLACK, WHITE = 0, 1, 2
STONE = {EMPTY: "· ", BLACK: "● ", WHITE: "○ "}
DIRS = ((0, 1), (1, 0), (1, 1), (1, -1))

# ---- 棋型分档 ----
S_WIN = 1_000_000    # 连五
S_OPEN4 = 100_000    # 活四(两端都能成五)
S_FOUR = 10_000      # 冲四(单端)
S_OPEN3 = 1_000      # 活三
S_THREE = 100        # 眠三
S_OPEN2 = 50         # 活二
S_TWO = 10           # 眠二
S_ONE = 1            # 单子


class Board:
    """棋盘。"""

    def __init__(self, size=15):
        self.size = size
        self.grid = [[EMPTY] * size for _ in range(size)]
        self.moves = 0
        self.last = None  # 上一手 (r, c)

    def inside(self, r, c):
        return 0 <= r < self.size and 0 <= c < self.size

    def play(self, r, c, color):
        """落子, 成功返回 True(越界或已有子返回 False)。"""
        if not self.inside(r, c) or self.grid[r][c] != EMPTY:
            return False
        self.grid[r][c] = color
        self.moves += 1
        self.last = (r, c)
        return True

    def full(self):
        return self.moves >= self.size * self.size

    def check_win(self, r, c, color):
        """以 (r, c) 为中心检查 color 是否连成 5 子。"""
        for dr, dc in DIRS:
            n = 1
            for s in (1, -1):
                rr, cc = r + dr * s, c + dc * s
                while self.inside(rr, cc) and self.grid[rr][cc] == color:
                    n += 1
                    rr += dr * s
                    cc += dc * s
            if n >= 5:
                return True
        return False


def _ray(board, r, c, color, dr, dc):
    """从 (r, c) 沿 (dr, dc) 数连续 color 子, 返回 (个数, 端口是否为空)。"""
    n, rr, cc = 0, r + dr, c + dc
    while board.inside(rr, cc) and board.grid[rr][cc] == color:
        n += 1
        rr += dr
        cc += dc
    open_end = board.inside(rr, cc) and board.grid[rr][cc] == EMPTY
    return n, open_end


def _pattern_score(total, opens):
    if total >= 5:
        return S_WIN
    if total == 4:
        return S_OPEN4 if opens == 2 else (S_FOUR if opens == 1 else 0)
    if total == 3:
        return S_OPEN3 if opens == 2 else (S_THREE if opens == 1 else 0)
    if total == 2:
        return S_OPEN2 if opens == 2 else (S_TWO if opens == 1 else 0)
    return S_ONE if opens else 0


def eval_point(board, r, c, color):
    """假设在 (r, c) 落 color 子, 返回该点的棋型综合分。"""
    scores = []
    for dr, dc in DIRS:
        n1, o1 = _ray(board, r, c, color, dr, dc)
        n2, o2 = _ray(board, r, c, color, -dr, -dc)
        scores.append(_pattern_score(n1 + n2 + 1, o1 + o2))
    best = max(scores)
    # 最强方向加权 + 四方向总和(奖励双重威胁, 如双活三)
    return best * 10 + sum(scores)


def candidates(board):
    """候选落点: 已有棋子周围(切比雪夫距离<=2)的空位; 空棋盘返回天元。"""
    if board.moves == 0:
        m = board.size // 2
        return [(m, m)]
    seen = set()
    out = []
    for r in range(board.size):
        for c in range(board.size):
            if board.grid[r][c] == EMPTY:
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    rr, cc = r + dr, c + dc
                    if (board.inside(rr, cc)
                            and board.grid[rr][cc] == EMPTY
                            and (rr, cc) not in seen):
                        seen.add((rr, cc))
                        out.append((rr, cc))
    return out


def ai_choose(board, color, rng):
    """按威胁优先级选一手, 返回 (r, c)。"""
    opp = BLACK if color == WHITE else WHITE
    cands = candidates(board)
    cx = cy = board.size // 2

    scored = []
    for (r, c) in cands:
        me = eval_point(board, r, c, color)
        if me >= S_WIN * 10:
            return (r, c)  # 优先级 1: 自己能赢
        op = eval_point(board, r, c, opp)
        scored.append((r, c, me, op))
    for (r, c, me, op) in scored:
        if op >= S_WIN * 10:
            return (r, c)  # 优先级 2: 堵对方的赢

    best, best_key = None, None
    for (r, c, me, op) in scored:
        if op >= S_FOUR * 10:
            rank = 5   # 优先级 3: 堵对方的四
        elif me >= S_OPEN4 * 10:
            rank = 4   # 优先级 4: 自己造活四
        elif op >= S_OPEN3 * 10:
            rank = 3   # 优先级 5: 堵对方活三
        elif me >= S_OPEN3 * 10:
            rank = 2   # 优先级 6: 自己造活三
        else:
            rank = 0   # 优先级 7: 综合评分
        center = (board.size - (abs(r - cx) + abs(c - cy))) * 2
        tiebreak = me * 1.1 + op + center + rng.random()
        key = (rank, tiebreak)
        if best_key is None or key > best_key:
            best_key, best = key, (r, c)
    return best


COORD_RE = re.compile(r"^([A-Za-z])\s*(\d{1,2})$")


def parse_coord(text, size):
    """解析 'H8' -> (7, 7); 非法时抛 ValueError(供上层重新提示)。"""
    m = COORD_RE.match(text.strip())
    if not m:
        raise ValueError("格式不对, 请用列字母+行数字, 例如 H8")
    col = ord(m.group(1).upper()) - ord("A")
    row = int(m.group(2)) - 1
    if not (0 <= col < size and 0 <= row < size):
        raise ValueError("坐标超出棋盘范围(棋盘为 %d×%d)" % (size, size))
    return row, col


def to_coord(r, c):
    return "%s%d" % (chr(ord("A") + c), r + 1)


def render(board):
    size = board.size
    print("   " + " ".join(chr(ord("A") + c) for c in range(size)))
    for r in range(size):
        line = "%2d " % (r + 1)
        for c in range(size):
            line += STONE[board.grid[r][c]]
        print(line)
    if board.last is not None:
        print("上一步: %s" % to_coord(*board.last))
    print()


def play_interactive(size, seed):
    rng = random.Random(seed)
    board = Board(size)
    print("五子棋: 你执黑(●)先行, AI 执白(○)后行, 连成 5 子获胜。输入 q 退出。")
    render(board)
    while True:
        while True:  # 玩家回合: 非法输入重新提示
            try:
                text = input("轮到你走棋(●), 输入坐标如 H8: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n已退出。")
                return
            if text.lower() in ("q", "quit", "exit"):
                print("你认输了, AI 获胜。")
                return
            try:
                r, c = parse_coord(text, size)
            except ValueError as e:
                print("坐标无效: %s, 请重新输入。" % e)
                continue
            if board.grid[r][c] != EMPTY:
                print("(%s)已有棋子, 请重新输入。" % text.upper())
                continue
            break
        board.play(r, c, BLACK)
        print("你下在 %s" % to_coord(r, c))
        render(board)
        if board.check_win(r, c, BLACK):
            print("恭喜! 你赢了! 🎉")
            return
        if board.full():
            print("棋盘下满, 和棋。")
            return
        r, c = ai_choose(board, WHITE, rng)
        board.play(r, c, WHITE)
        print("AI 下在 %s" % to_coord(r, c))
        render(board)
        if board.check_win(r, c, WHITE):
            print("AI 获胜, 再接再厉!")
            return
        if board.full():
            print("棋盘下满, 和棋。")
            return


DEMO_SCRIPT = [
    (BLACK, "H8"), (WHITE, "C3"),
    (BLACK, "I9"), (WHITE, "C4"),
    (BLACK, "J10"), (WHITE, "C5"),
    (BLACK, "K11"), (WHITE, "C6"),
    (BLACK, "L12"),
]


def play_demo(size):
    if size < 12:
        print("演示剧本需要棋盘至少 12×12。")
        return
    board = Board(size)
    print("演示对局(固定剧本, 黑方斜线连五获胜):")
    for color, coord in DEMO_SCRIPT:
        r, c = parse_coord(coord, size)
        board.play(r, c, color)
        who = "黑(●)" if color == BLACK else "白(○)"
        print("%s 下在 %s" % (who, coord))
        render(board)
        if board.check_win(r, c, color):
            print("对局结束: %s 获胜!" % who)
            return


def play_selfplay(size, seed):
    rng = random.Random(seed)
    board = Board(size)
    color = BLACK
    while True:  # 棋子只增不减, 至多 size*size 手必终止
        r, c = ai_choose(board, color, rng)
        board.play(r, c, color)
        who = "黑(●)" if color == BLACK else "白(○)"
        print("第 %d 手: %s %s" % (board.moves, who, to_coord(r, c)))
        if board.check_win(r, c, color):
            render(board)
            print("对局结束: %s 获胜, 共 %d 手。" % (who, board.moves))
            return
        if board.full():
            render(board)
            print("对局结束: 和棋, 共 %d 手。" % board.moves)
            return
        color = WHITE if color == BLACK else BLACK


def main(argv=None):
    ap = argparse.ArgumentParser(description="五子棋人机对战(纯本地, 仅标准库)")
    ap.add_argument("--size", type=int, default=15, help="棋盘边长, 默认 15 (5-19)")
    ap.add_argument("--demo", action="store_true", help="播放固定剧本演示对局")
    ap.add_argument("--selfplay", action="store_true", help="AI 自己跟自己下一盘")
    ap.add_argument("--seed", default=None, help="随机种子(默认随机)")
    args = ap.parse_args(argv)
    if not 5 <= args.size <= 19:
        ap.error("--size 须在 5 到 19 之间")
    if args.demo:
        play_demo(args.size)
    elif args.selfplay:
        play_selfplay(args.size, args.seed)
    else:
        play_interactive(args.size, args.seed)


if __name__ == "__main__":
    main()

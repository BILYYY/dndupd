# chipleaderTheGambler: Tiered EV volume + market learning + targeted counters
# Philosophy: "Money is a tool to buy points."
# Techniques explained inline; plug-and-play with dnd_auction_game server.

import os, random, math
from collections import deque
from dnd_auction_game.client import AuctionGameClient

# --- Expected dice values from course materials ---
AVG = {2:1.5, 3:2.0, 4:2.5, 6:3.5, 8:4.5, 10:5.5, 12:6.5, 20:10.5}  # EV per die face.
def EV(a): return AVG[a["die"]] * a["num"] + a["bonus"]

class ChipLeaderTheGambler:
    """
    Core ideas (GTO-ish):
    - Partition auctions by EV into LOW/MID/HIGH tiers each round.
    - Spray many SMALL bids on LOW EV (beats tiny bidders).
    - Pay MID on MID EV using market gold-per-point (R) percentiles.
    - Only a couple BIG bids on HIGH EV, mostly as smart_bid tie-snipes.
    - Keep rolling R = price/EV; adapt multipliers online.
    - Detect whale surges (p90 winners jump) -> cap per-auction spend and spread wider.
    """

    def __init__(self):
        # Rolling market learning windows
        self.r_samples  = deque(maxlen=400)  # R = winning_price / EV
        self.win_prices = deque(maxlen=150)  # absolute winning prices
        self.last_avg_win = None

        # Aggression scaler (nudged if we keep losing by small margins)
        self.agg = 1.00

        # Whale detection memory (recent p90 trend)
        self.p90_trend = deque(maxlen=12)

        # Keep last bids to measure shortfall if desired (not needed to run)
        self._last_bids = {}

    # ---------- helpers ----------
    @staticmethod
    def _quant(arr, q, default):
        if not arr: return default
        s = sorted(arr)
        if len(s) == 1: return s[0]
        x = q*(len(s)-1)
        lo, hi = int(x), int(math.ceil(x))
        if lo == hi: return s[lo]
        w = x-lo
        return s[lo]*(1-w)+s[hi]*w

    def _r_percentiles(self):
        # Defaults (aggressive but sane gold-per-point ladder)
        r50d, r70d, r85d = 28.0, 35.0, 45.0
        arr = list(self.r_samples)
        r50 = self._quant(arr, 0.50, r50d)
        r70 = self._quant(arr, 0.70, r70d)
        r85 = self._quant(arr, 0.85, r85d)
        return r50, r70, r85

    def _winner_percentiles(self):
        wins = list(self.win_prices)
        if not wins:
            return (200, 300, 600)
        return (
            self._quant(wins, 0.50, 200),
            self._quant(wins, 0.70, 300),
            self._quant(wins, 0.90, 600),
        )

    # ---------- learning from last round ----------
    def learn(self, prev, my_id):
        if not prev:
            self.last_avg_win = None
            return

        wins = []
        for _, info in prev.items():
            bids = info.get("bids", [])
            if not bids:
                continue
            win_price = int(bids[0]["gold"])
            wins.append(win_price)
            v = EV(info)
            if v > 0:
                self.r_samples.append(win_price / v)

        if wins:
            self.last_avg_win = sum(wins)/len(wins)
            self.win_prices.extend(wins)
            while len(self.win_prices) > self.win_prices.maxlen:
                self.win_prices.popleft()

        # Whale surge detection: track p90 trend
        _, _, p90 = self._winner_percentiles()
        self.p90_trend.append(p90)

    def whale_alert(self):
        # If recent p90 jumped >60% vs 10-round median -> whale surge
        if len(self.p90_trend) < 6:
            return False
        recent = list(self.p90_trend)
        base = self._quant(recent[:-3], 0.50, recent[-1])
        return recent[-1] > 1.6 * max(1, base)

    # ---------- POOL BUYING LOGIC ----------
    def calculate_pool_strategy(self, my_gold, my_points, pool_gold, phase, trailing):
        """
        Decides when to trade Points for Gold.
        """
        buy_amount = 0
        # 1. EMERGENCY: We are broke. We cannot bid. We MUST sell points to play.
        if my_gold < 150 and my_points > 50:
            buy_amount = 30 
        # 2. ARBITRAGE: The pool is fat. Gold is "on sale".
        if pool_gold > 3500 and my_points > 100:
            buy_amount = 60 if trailing else 25
        # Safety: Never sell if it drops us to 0
        if buy_amount > my_points:
            buy_amount = int(my_points * 0.9)
        return int(buy_amount)

    # ---------- main strategy ----------
    # FIX: Added pool_gold and prev_pool_buys to arguments to match server call
    def make_bid(self, agent_id, current_round, states, auctions, prev_auctions, pool_gold, prev_pool_buys, bank_state):
        # 0) learn market from last round
        self.learn(prev_auctions or {}, agent_id)

        me = states[agent_id]
        gold = me["gold"]
        my_pts = me["points"]

        # Horizon / phase
        rounds_left = 1 + len(bank_state.get("gold_income_per_round", []))
        total_rounds = max(1, current_round + rounds_left)
        phase = current_round / total_rounds

        # Trailing?
        others_pts = [s["points"] for aid, s in states.items() if aid != agent_id]
        trailing = bool(others_pts and my_pts < 0.8 * max(others_pts))

        # Tiny-bid detector from baseline agent:
        # next income > 1050 -> tiny may bid up to ~100; else ~20.
        nxt_income = bank_state.get("gold_income_per_round", [0])[0] if bank_state.get("gold_income_per_round") else 0
        beat_tiny = 107 if nxt_income > 1050 else 22

        # Market ratios for MID/HIGH
        r50, r70, r85 = self._r_percentiles()

        # Spending plan: small reserve, grow aggression later or if trailing
        reserve = max(200, int(0.05 * gold))
        spend_frac = 0.45 if phase < 0.30 else (0.58 if phase < 0.75 else 0.80)
        if trailing:
            spend_frac += 0.10
        spend_cap = min(gold - reserve, int(spend_frac * gold))
        spend_cap = max(0, spend_cap)

        # Whale surge -> tighter per-auction cap, more volume
        whale = self.whale_alert()
        per_auction_cap = max(1, int((0.22 if whale else 0.32) * gold))

        # Compute EV and keep only positive EV except very late
        evs = {aid: EV(a) for aid, a in auctions.items()}
        if rounds_left > 2:
            evs = {aid: v for aid, v in evs.items() if v > 0}
        if not evs:
            # FIX: Must return pool dictionary even if no bids
            pool_buy = self.calculate_pool_strategy(gold, my_pts, pool_gold, phase, trailing)
            return {"bids": {}, "pool": pool_buy}

        # EV tiers (rough thirds) and target coverage
        vals = sorted(evs.values())
        q1 = vals[len(vals)//3]
        q2 = vals[2*len(vals)//3]
        n_all = len(evs)
        # Aim to cover a lot: 16..28 bids depending on gold and surge
        target_count = min(n_all, (18 if not whale else 24) + (6 if gold > 3000 else 2))

        # --- Build planned bids ---
        planned = []
        for aid, v in evs.items():
            # LOW EV: beat tiny by a bit (volume farm)
            if v <= q1:
                base = beat_tiny + random.randint(0, 2)

            # MID EV: price = v * r70 (market mid) with slight aggression scaling
            elif v <= q2:
                base = int(v * r70 * self.agg)

            # HIGH EV: start from v * r85 (market high)
            else:
                base = int(v * r85 * self.agg)

            planned.append((aid, v, base))

        # --- Counter smart_bid on 1–2 top EV lots ---
        # smart_bid rule: avg_last_winners * 1.10 with a per-auction 30% cap.
        if self.last_avg_win and planned:
            TIE = int(self.last_avg_win * 1.10)
            cap = int(gold * 0.30)
            snipe = min(TIE, cap)
            # replace 1–2 highest-EV bases if they're below snipe
            top = sorted(planned, key=lambda t: t[1], reverse=True)
            bumped = 0
            for aid, v, b in top:
                if bumped >= 2: break
                if b < snipe:
                    idx = next(i for i,x in enumerate(planned) if x[0]==aid)
                    planned[idx] = (aid, v, snipe)
                    bumped += 1

        # --- Counter mean-of-EV players ---
        # If many winners fit price ≈ k * EV, our r50/r70 capture k. Add a candidate slightly above k*v on a few mid/high lots.
        k = r70  # typical slope estimate from winners
        extra_candidates = []
        for aid, v, b in sorted(planned, key=lambda t: t[1], reverse=True)[:6]:
            alt = int(v * k * 1.06)  # +6% to beat their mean
            if alt > b:
                extra_candidates.append((aid, v, alt))
        # replace bases if alt is higher but still under cap
        for aid, v, alt in extra_candidates:
            idx = next(i for i,x in enumerate(planned) if x[0]==aid)
            planned[idx] = (aid, v, alt)

        # Rank by a fast efficiency proxy (points per effective gold)
        # Effective burn ~ 0.5*b given 60% cashback on losses (rough and fast).
        ranked = []
        for aid, v, b in planned:
            if b <= 0:
                continue
            eff_cost = max(1, 0.5 * b)
            eff = v / eff_cost
            ranked.append((eff, aid, b, v))
        ranked.sort(reverse=True, key=lambda x: x[0])

        # Allocate: diversify heavily; cap per auction; add random jitter to break ties
        bids, spent = {}, 0
        for eff, aid, b, v in ranked:
            if len(bids) >= target_count: break
            b = min(b, per_auction_cap)
            # small jitter (GTO mix)
            b = int(b * random.uniform(1.00, 1.03))
            if b <= 0 or spent + b > spend_cap:
                continue
            bids[aid] = b
            spent += b

        # If we under-spent, add more LOW-tier tiny-beaters as filler
        if spent < spend_cap and len(bids) < target_count + 6:
            low_ids = [aid for aid, v in evs.items() if v <= q1 and aid not in bids]
            random.shuffle(low_ids)
            filler = 26 if beat_tiny <= 22 else 103
            for aid in low_ids:
                if len(bids) >= target_count + 6 or spent + filler > spend_cap:
                    break
                bids[aid] = filler
                spent += filler

        # Adapt aggression slightly based on relative price level vs winners (p70)
        if self.win_prices:
            _, p70, _ = self._winner_percentiles()
            my_avg = sum(bids.values())/max(1, len(bids))
            if my_avg < 0.9 * p70:
                self.agg = min(1.22, self.agg * 1.03)  # too low -> raise
            elif my_avg > 1.25 * p70:
                self.agg = max(0.92, self.agg * 0.985) # too high -> cool down

        # keep last bids (optional diagnostics)
        self._last_bids = dict(bids)
        
        # Calculate pool buy and return correct dictionary
        pool_buy = self.calculate_pool_strategy(gold, my_pts, pool_gold, phase, trailing)
        return {"bids": bids, "pool": pool_buy}


# ---- glue for the game server ----
_AGENT = None
# Updated glue signature to match client.py requirements
def make_bid(agent_id, current_round, states, auctions, prev_auctions, pool_gold, prev_pool_buys, bank_state):
    global _AGENT
    if _AGENT is None:
        _AGENT = ChipLeaderTheGambler()
    return _AGENT.make_bid(agent_id, current_round, states, auctions, prev_auctions, pool_gold, prev_pool_buys, bank_state)


if __name__ == "__main__":
    host = os.getenv("AH_HOST", "localhost")
    port = int(os.getenv("AH_PORT", "8000"))
    token = os.getenv("AH_GAME_TOKEN", "play123")
    name = f"ChipLeader_{random.randint(1, 999)}"
    player_id = os.getenv("AH_PLAYER_ID", "gambler_player")

    # Ensure AuctionGameClient is available
    if AuctionGameClient:
        game = AuctionGameClient(host=host, agent_name=name, token=token, player_id=player_id, port=port)
        try:
            game.run(make_bid)
        except KeyboardInterrupt:
            print("<interrupt - shutting down>")
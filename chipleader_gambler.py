import os
import random
import math
from collections import deque
from dnd_auction_game.client import AuctionGameClient

# --- Expected dice values ---
AVG = {2: 1.5, 3: 2.0, 4: 2.5, 6: 3.5, 8: 4.5, 10: 5.5, 12: 6.5, 20: 10.5}

def EV(a):
    return AVG[a["die"]] * a["num"] + a["bonus"]

class ChipLeaderTheGambler:
    """
    Philosophy: "Money is a tool to buy points."
    - Partition auctions by EV into LOW/MID/HIGH tiers.
    - Spray many SMALL bids on LOW EV.
    - Pay MID on MID EV using market gold-per-point (R) percentiles.
    - Only a couple BIG bids on HIGH EV.
    - BUY POOL logic added to convert Points -> Gold when profitable.
    """

    def __init__(self):
        self.r_samples = deque(maxlen=400)
        self.win_prices = deque(maxlen=150)
        self.last_avg_win = None
        self.agg = 1.00
        self.p90_trend = deque(maxlen=12)
        self._last_bids = {}

    # ---------- helpers ----------
    @staticmethod
    def _quant(arr, q, default):
        if not arr: return default
        s = sorted(arr)
        if len(s) == 1: return s[0]
        x = q * (len(s) - 1)
        lo, hi = int(x), int(math.ceil(x))
        if lo == hi: return s[lo]
        w = x - lo
        return s[lo] * (1 - w) + s[hi] * w

    def _r_percentiles(self):
        arr = list(self.r_samples)
        # Market ratios (Gold per EV Point)
        r50 = self._quant(arr, 0.50, 28.0)
        r70 = self._quant(arr, 0.70, 35.0)
        r85 = self._quant(arr, 0.85, 45.0)
        return r50, r70, r85

    def _winner_percentiles(self):
        wins = list(self.win_prices)
        if not wins: return (200, 300, 600)
        return (
            self._quant(wins, 0.50, 200),
            self._quant(wins, 0.70, 300),
            self._quant(wins, 0.90, 600),
        )

    # ---------- learning ----------
    def learn(self, prev, my_id):
        if not prev:
            self.last_avg_win = None
            return

        wins = []
        for _, info in prev.items():
            bids = info.get("bids", [])
            if not bids: continue
            win_price = int(bids[0]["gold"])
            wins.append(win_price)
            v = EV(info)
            if v > 0:
                self.r_samples.append(win_price / v)

        if wins:
            self.last_avg_win = sum(wins) / len(wins)
            self.win_prices.extend(wins)
            # Whale surge detection
            _, _, p90 = self._winner_percentiles()
            self.p90_trend.append(p90)

    def whale_alert(self):
        if len(self.p90_trend) < 6: return False
        recent = list(self.p90_trend)
        base = self._quant(recent[:-3], 0.50, recent[-1])
        return recent[-1] > 1.6 * max(1, base)

    # ---------- POOL STRATEGY (NEW) ----------
    def calculate_pool_strategy(self, my_gold, my_points, pool_gold, phase, trailing):
        """
        Decides when to trade Points for Gold.
        """
        buy_amount = 0

        # 1. EMERGENCY: We are broke. We cannot bid. We MUST sell points to play.
        # Threshold: < 150 gold is critical territory.
        if my_gold < 150 and my_points > 50:
            buy_amount = 30 

        # 2. ARBITRAGE: The pool is fat. Gold is "on sale".
        # If the pool > 3500, we get a lot of gold for very few points.
        if pool_gold > 3500 and my_points > 100:
            # If we are trailing, risk more points to get gold and bid aggressively
            buy_amount = 60 if trailing else 25

        # Safety: Never sell if it drops us to 0
        if buy_amount > my_points:
            buy_amount = int(my_points * 0.9)

        return int(buy_amount)

    # ---------- MAIN BID LOGIC ----------
    def make_bid(self, agent_id, current_round, states, auctions, prev_auctions, pool_gold, prev_pool_buys, bank_state):
        # 0) Learn
        self.learn(prev_auctions or {}, agent_id)

        me = states[agent_id]
        gold = me["gold"]
        my_pts = me["points"]

        # 1) Context
        rounds_left = 1 + len(bank_state.get("gold_income_per_round", []))
        total_rounds = max(1, current_round + rounds_left)
        phase = current_round / total_rounds
        
        others_pts = [s["points"] for aid, s in states.items() if aid != agent_id]
        trailing = bool(others_pts and my_pts < 0.8 * max(others_pts))

        # 2) Tiny Bidder Detection
        nxt_income = bank_state.get("gold_income_per_round", [0])[0] if bank_state.get("gold_income_per_round") else 0
        beat_tiny = 107 if nxt_income > 1050 else 22

        r50, r70, r85 = self._r_percentiles()

        # 3) Budgeting
        reserve = max(200, int(0.05 * gold))
        spend_frac = 0.45 if phase < 0.30 else (0.58 if phase < 0.75 else 0.80)
        if trailing: spend_frac += 0.10
        
        spend_cap = max(0, min(gold - reserve, int(spend_frac * gold)))

        whale = self.whale_alert()
        per_auction_cap = max(1, int((0.22 if whale else 0.32) * gold))

        # 4) Valuation
        evs = {aid: EV(a) for aid, a in auctions.items()}
        # Filter negative EV unless ending
        if rounds_left > 2:
            evs = {aid: v for aid, v in evs.items() if v > 0}
        
        if not evs: return {"bids": {}, "pool": 0}

        vals = sorted(evs.values())
        q1 = vals[len(vals) // 3]
        q2 = vals[2 * len(vals) // 3]
        target_count = min(len(evs), (18 if not whale else 24) + (6 if gold > 3000 else 2))

        # 5) Plan Bids
        planned = []
        for aid, v in evs.items():
            # LOW EV: Volume farm
            if v <= q1:
                base = beat_tiny + random.randint(0, 2)
            # MID EV: Market Rate
            elif v <= q2:
                base = int(v * r70 * self.agg)
            # HIGH EV: Premium Rate
            else:
                base = int(v * r85 * self.agg)
            planned.append((aid, v, base))

        # 6) Tactics: Smart Bid Snipe
        # If we know the market average win price, bid 10% over it to steal wins
        if self.last_avg_win and planned:
            TIE = int(self.last_avg_win * 1.10)
            cap = int(gold * 0.30)
            snipe = min(TIE, cap)
            
            top = sorted(planned, key=lambda t: t[1], reverse=True)
            bumped = 0
            for aid, v, b in top:
                if bumped >= 2: break
                if b < snipe:
                    # Update bid in planned list
                    idx = next(i for i, x in enumerate(planned) if x[0] == aid)
                    planned[idx] = (aid, v, snipe)
                    bumped += 1

        # 7) Ranking & Execution
        ranked = []
        for aid, v, b in planned:
            if b <= 0: continue
            eff_cost = max(1, 0.5 * b) # Effective cost assuming 50% kickback
            eff = v / eff_cost
            ranked.append((eff, aid, b, v))
        
        ranked.sort(reverse=True, key=lambda x: x[0])

        bids, spent = {}, 0
        for eff, aid, b, v in ranked:
            if len(bids) >= target_count: break
            b = min(b, per_auction_cap)
            b = int(b * random.uniform(1.00, 1.03)) # Jitter
            
            if b <= 0 or spent + b > spend_cap: continue
            bids[aid] = b
            spent += b

        # 8) Filler (if budget remains)
        if spent < spend_cap and len(bids) < target_count + 6:
            low_ids = [aid for aid, v in evs.items() if v <= q1 and aid not in bids]
            random.shuffle(low_ids)
            filler = 26 if beat_tiny <= 22 else 103
            for aid in low_ids:
                if len(bids) >= target_count + 6 or spent + filler > spend_cap: break
                bids[aid] = filler
                spent += filler

        # 9) Adapt Aggression
        if self.win_prices:
            _, p70, _ = self._winner_percentiles()
            my_avg = sum(bids.values()) / max(1, len(bids))
            if my_avg < 0.9 * p70: self.agg = min(1.22, self.agg * 1.03)
            elif my_avg > 1.25 * p70: self.agg = max(0.92, self.agg * 0.985)

        self._last_bids = dict(bids)
        
        # 10) POOL BUY DECISION
        pool_buy = self.calculate_pool_strategy(gold, my_pts, pool_gold, phase, trailing)

        return {"bids": bids, "pool": pool_buy}

# ---- Glue Code ----
_AGENT = None
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
    
    # Standard Client
    game = AuctionGameClient(host=host, agent_name=name, token=token, player_id="gambler_bot", port=port)
    print(f"Starting {name}...")
    try:
        game.run(make_bid)
    except KeyboardInterrupt:
        print("<interrupt - shutting down>")
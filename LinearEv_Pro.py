import os
import random
import math
from collections import deque
from dnd_auction_game.client import AuctionGameClient

# --- CONFIG ---
AVG = {2: 1.5, 3: 2.0, 4: 2.5, 6: 3.5, 8: 4.5, 10: 5.5, 12: 6.5, 20: 10.5}

def EV(a):
    return AVG[a["die"]] * a["num"] + a["bonus"]

class LinearEVPro:
    def __init__(self):
        # Stores (EV, WinningPrice) pairs for regression
        self.xy = deque(maxlen=200)
        # Stores just WinningPrices for averages
        self.wins = deque(maxlen=100)

    # --- PURE PYTHON MATH HELPERS (No Numpy needed) ---
    def _fit(self):
        """
        Simple Least Squares Linear Regression (y = kx + b)
        Returns slope (k) and intercept (b)
        """
        if len(self.xy) < 12: 
            return 35.0, 0.0  # Fallback: Price is approx 35x EV
        
        n = len(self.xy)
        sum_x = sum(x for x, y in self.xy)
        sum_y = sum(y for x, y in self.xy)
        sum_xy = sum(x*y for x, y in self.xy)
        sum_xx = sum(x*x for x, y in self.xy)
        
        denominator = (n * sum_xx - sum_x * sum_x)
        if denominator == 0: 
            return 35.0, 0.0
        
        k = (n * sum_xy - sum_x * sum_y) / denominator
        b = (sum_y - k * sum_x) / n
        return float(k), float(b)

    def _percentile(self, data, p):
        """Calculates percentile p (0-100) of a list"""
        if not data: return 0
        sorted_data = sorted(data)
        k = (len(sorted_data) - 1) * (p / 100.0)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c: return sorted_data[int(k)]
        d0 = sorted_data[int(f)] * (c - k)
        d1 = sorted_data[int(c)] * (k - f)
        return d0 + d1
    # --------------------------------------------------

    def learn(self, prev):
        if not prev: return
        for _, a in prev.items():
            bids = a.get("bids", [])
            if not bids: continue
            w = int(bids[0]["gold"])
            v = EV(a)
            if v > 0:
                self.xy.append((v, w))
                self.wins.append(w)

    def calculate_pool_buy(self, my_gold, my_points, pool_gold, trailing):
        """Pool Buyback Strategy"""
        buy_amount = 0
        # Emergency: Broke
        if my_gold < 150 and my_points > 50:
            buy_amount = 30
        # Opportunity: Pool is huge
        if pool_gold > 3500 and my_points > 100:
            buy_amount = 60 if trailing else 25
        # Safety
        if buy_amount > my_points:
            buy_amount = int(my_points * 0.9)
        return int(buy_amount)

    def make(self, agent_id, rnd, states, auctions, prev, pool_gold, bank):
        self.learn(prev or {})
        
        me = states[agent_id]
        gold = me["gold"]
        pts = me["points"]
        
        rem = bank.get("gold_income_per_round", [])
        rounds_left = 1 + len(rem)
        total = rnd + rounds_left
        phase = rnd / max(total, 1)
        
        others = [s["points"] for aid, s in states.items() if aid != agent_id]
        trailing = bool(others and pts < 0.8 * max(others))

        # 1. Budgeting
        reserve = max(150, int(0.05 * gold))
        spend_frac = 0.45 if phase < 0.3 else (0.55 if phase < 0.75 else 0.78)
        if trailing: spend_frac += 0.10
        spend_cap = min(gold - reserve, int(spend_frac * gold))
        spend_cap = max(0, spend_cap)

        # 2. Market Modeling (Linear Regression)
        k, b_intercept = self._fit()
        
        # 3. Smart Bid Tie Logic
        avg_last = (sum(self.wins) / len(self.wins)) if self.wins else 400
        tie = min(int(avg_last * 1.10), int(gold * 0.30))

        # 4. Valuation & Bidding
        evs = {aid: EV(a) for aid, a in auctions.items() if EV(a) > 0}
        scored = []
        
        # Calculate 80th percentile EV for this round to identify "Top Lots"
        if evs:
            ev_values = list(evs.values())
            top_lot_threshold = self._percentile(ev_values, 80)
        else:
            top_lot_threshold = 9999

        for aid, v in evs.items():
            # Linear Prediction: Price = k * EV + b
            pred = max(1, int(k * v + b_intercept))
            pred = min(pred, int(0.32 * gold)) # Cap per auction
            
            # If this is a high-value item, try to tie/snipe Smart_Bot
            if v >= top_lot_threshold:
                pred = max(pred, tie)
            
            # Efficiency Metric
            eff = v / max(1, 0.5 * pred)
            scored.append((eff, aid, pred, v))

        scored.sort(reverse=True)

        # 5. Allocation
        bids = {}
        spent = 0
        max_slots = min(len(scored), 16)
        
        for eff, aid, bid, _ in scored[:max_slots]:
            if spent + bid > spend_cap: continue
            
            # Random Jitter
            final_bid = int(bid * random.uniform(1.00, 1.02))
            
            if final_bid > 0 and final_bid <= gold - spent:
                bids[aid] = final_bid
                spent += final_bid

        # 6. Pool Strategy
        pool_buy = self.calculate_pool_buy(gold, pts, pool_gold, trailing)

        return {"bids": bids, "pool": pool_buy}

# --- GLUE ---
_AGENT = None
def make_bid(agent_id, current_round, states, auctions, prev_auctions, pool_gold, prev_pool_buys, bank_state):
    global _AGENT
    if _AGENT is None: _AGENT = LinearEVPro()
    return _AGENT.make(agent_id, current_round, states, auctions, prev_auctions, pool_gold, bank_state)

if __name__ == "__main__":
    host = os.getenv("AH_HOST", "localhost")
    port = int(os.getenv("AH_PORT", "8000"))
    token = os.getenv("AH_GAME_TOKEN", "play123")
    name = f"LinearEV_Pro_{random.randint(1, 999)}"
    
    game = AuctionGameClient(host=host, agent_name=name, token=token, player_id="lin_ev_pro", port=port)
    print(f"Starting {name}...")
    try: 
        game.run(make_bid)
    except KeyboardInterrupt: 
        print("<interrupt - shutting down>")
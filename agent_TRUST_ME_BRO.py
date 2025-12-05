import os
import random
import math
from dnd_auction_game.client import AuctionGameClient

# --- CONFIG ---
AVG = {2: 1.5, 3: 2.0, 4: 2.5, 6: 3.5, 8: 4.5, 10: 5.5, 12: 6.5, 20: 10.5}

def EV(a):
    return AVG[a["die"]] * a["num"] + a["bonus"]

class TrustMeBroV3:
    def __init__(self):
        self.wins = []

    def q(self, a, p, d):
        if not a: return d
        s = sorted(a)
        x = p * (len(s) - 1)
        lo = int(x)
        hi = int(math.ceil(x))
        return s[lo] if lo == hi else s[lo] * (1 - (x - lo)) + s[hi] * (x - lo)

    def learn(self, prev):
        if not prev: return
        for _, a in prev.items():
            b = a.get("bids", [])
            if b:
                self.wins.append(int(b[0]["gold"]))
        if len(self.wins) > 120:
            self.wins = self.wins[-120:]

    def calculate_pool_buy(self, my_gold, my_points, pool_gold, trailing):
        """Standard pool buyback logic to prevent bankruptcy"""
        buy_amount = 0
        if my_gold < 150 and my_points > 50:
            buy_amount = 30
        if pool_gold > 3500 and my_points > 100:
            buy_amount = 60 if trailing else 25
        if buy_amount > my_points:
            buy_amount = int(my_points * 0.9)
        return int(buy_amount)

    def make_bid(self, agent_id, current_round, states, auctions, prev, pool_gold, prev_pool_buys, bank):
        self.learn(prev or {})
        
        me = states[agent_id]
        gold = me["gold"]
        pts = me["points"]
        
        rem = bank.get("gold_income_per_round", [])
        rounds_left = 1 + len(rem)
        total = current_round + rounds_left
        phase = current_round / max(total, 1)
        
        others = [s["points"] for aid, s in states.items() if aid != agent_id]
        trailing = bool(others and pts < 0.8 * max(others))
        
        nxt = bank.get("gold_income_per_round", [0])[0] if bank.get("gold_income_per_round") else 0
        beat_tiny = 107 if nxt > 1050 else 22

        # Spend plan: Aggressive spending, minimal reserve
        reserve = max(150, int(0.03 * gold))
        spend_frac = 0.50 if phase < 0.3 else (0.60 if phase < 0.75 else 0.85)
        if trailing: spend_frac += 0.10
        
        spend_cap = min(gold - reserve, int(spend_frac * gold))
        spend_cap = max(0, spend_cap)

        # Price ladder from winners
        p50 = self.q(self.wins, 0.50, 300)
        p70 = self.q(self.wins, 0.70, 420)
        p90 = self.q(self.wins, 0.90, 700)

        evs = {aid: EV(a) for aid, a in auctions.items()}
        if rounds_left > 2:
            evs = {aid: v for aid, v in evs.items() if v > 0}
            
        if not evs: return {"bids": {}, "pool": 0}

        vals = sorted(evs.values())
        q1 = vals[len(vals) // 3]
        q2 = vals[2 * len(vals) // 3]
        target = min(len(evs), 18 + (6 if gold > 3000 else 2))
        per_auction_cap = max(1, int(0.30 * gold))

        planned = []
        for aid, v in evs.items():
            if v <= q1:
                b = beat_tiny + random.randint(0, 2)
            elif v <= q2:
                b = int(0.8 * p70)  # Mid tier: bid ~80% of market rate
            else:
                b = int(p90)        # High tier: bid aggressive market rate
            planned.append((aid, v, b))

        # Rank by efficiency (Points / Effective Cost)
        ranked = []
        for aid, v, b in planned:
            eff = v / max(1, 0.5 * b)
            ranked.append((eff, aid, int(b * random.uniform(1.00, 1.03))))
        ranked.sort(reverse=True)

        bids = {}
        spent = 0
        for _, aid, b in ranked:
            if len(bids) >= target: break
            b = min(b, per_auction_cap)
            
            if spent + b > spend_cap: continue
            
            bids[aid] = b
            spent += b

        # Top up low EV items if budget remains
        if spent < spend_cap and len(bids) < target + 6:
            low = [aid for aid, v in evs.items() if v <= q1 and aid not in bids]
            random.shuffle(low)
            filler = 26 if beat_tiny <= 22 else 103
            for aid in low:
                if len(bids) >= target + 6 or spent + filler > spend_cap: break
                bids[aid] = filler
                spent += filler

        # Pool Buyback
        pool_buy = self.calculate_pool_buy(gold, pts, pool_gold, trailing)

        return {"bids": bids, "pool": pool_buy}

# --- GLUE ---
_agent = None
def make_bid(agent_id, current_round, states, auctions, prev_auctions, pool_gold, prev_pool_buys, bank_state):
    global _agent
    if _agent is None:
        _agent = TrustMeBroV3()
    return _agent.make_bid(agent_id, current_round, states, auctions, prev_auctions, pool_gold, prev_pool_buys, bank_state)

if __name__ == "__main__":
    host = os.getenv("AH_HOST", "localhost")
    port = int(os.getenv("AH_PORT", "8000"))
    token = os.getenv("AH_GAME_TOKEN", "play123")
    name = f"TrustMeBroV3_{random.randint(1, 999)}"
    
    game = AuctionGameClient(host=host, agent_name=name, token=token, player_id="tmb_v3", port=port)
    print(f"Starting {name}...")
    try:
        game.run(make_bid)
    except KeyboardInterrupt:
        print("<interrupt - shutting down>")
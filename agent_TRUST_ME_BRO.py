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
        """Get percentile p from list a, or return default d"""
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
        """Buy back into the game if we are broke"""
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
        
        # --- CRITICAL FIX: DYNAMIC PRICING ---
        # Old code used fixed defaults (300, 700). 
        # New code scales based on our current wealth to fight inflation.
        default_low = int(gold * 0.05)  # 5% of wealth
        default_mid = int(gold * 0.15)  # 15% of wealth
        default_high = int(gold * 0.30) # 30% of wealth

        # If we have history, use it. If not, use wealth-based defaults.
        p50 = self.q(self.wins, 0.50, default_low)
        p70 = self.q(self.wins, 0.70, default_mid)
        p90 = self.q(self.wins, 0.90, default_high)
        # -------------------------------------

        rem = bank.get("gold_income_per_round", [])
        rounds_left = 1 + len(rem)
        
        # Check if we should filter out bad auctions
        evs = {aid: EV(a) for aid, a in auctions.items()}
        if rounds_left > 2:
            evs = {aid: v for aid, v in evs.items() if v > 0}
            
        if not evs: 
            pool_buy = self.calculate_pool_buy(gold, pts, pool_gold, False)
            return {"bids": {}, "pool": pool_buy}

        vals = sorted(evs.values())
        q1 = vals[len(vals) // 3]
        q2 = vals[2 * len(vals) // 3]
        
        # Target ~18 auctions, or more if we are rich
        target = min(len(evs), 18 + (6 if gold > 3000 else 2))
        
        # Cap single bids at 40% of gold so we don't blow it all on one item
        per_auction_cap = max(1, int(0.40 * gold))

        planned = []
        for aid, v in evs.items():
            if v <= q1: 
                # Low Value: Bid small
                b = int(gold * 0.01) + random.randint(1, 10)
            elif v <= q2: 
                # Mid Value: Bid competitive market rate
                b = int(0.8 * p70)
            else: 
                # High Value: Bid aggressive market rate
                b = int(p90)
            
            planned.append((aid, v, b))

        # Rank by efficiency
        ranked = [(v / max(1, 0.5 * b), aid, int(b * random.uniform(1.00, 1.03))) for aid, v, b in planned]
        ranked.sort(reverse=True)

        bids = {}
        spent = 0
        
        # Spend aggressive fraction of gold (Spend Plan)
        phase = current_round / max(current_round + rounds_left, 1)
        spend_frac = 0.50 if phase < 0.3 else (0.75 if phase < 0.8 else 0.95)
        spend_cap = int(gold * spend_frac)

        for _, aid, b in ranked:
            if len(bids) >= target: break
            
            # Ensure bid is at least 1 and within caps
            b = max(1, min(b, per_auction_cap))
            
            if spent + b > spend_cap: continue
            
            bids[aid] = b
            spent += b

        # Fill remaining budget on random items if we are under-spending
        if spent < spend_cap and len(bids) < target + 6:
            remaining_ids = [aid for aid in evs if aid not in bids]
            random.shuffle(remaining_ids)
            for aid in remaining_ids:
                filler = int(gold * 0.02) # 2% filler bid
                if spent + filler > spend_cap: break
                bids[aid] = filler
                spent += filler

        # Pool Buyback
        others = [s["points"] for aid, s in states.items() if aid != agent_id]
        trailing = bool(others and pts < 0.8 * max(others))
        pool_buy = self.calculate_pool_buy(gold, pts, pool_gold, trailing)

        return {"bids": bids, "pool": pool_buy}

# --- GLUE CODE ---
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
    print(f"Starting {name} (Inflation Fixed)...")
    try:
        game.run(make_bid)
    except KeyboardInterrupt:
        print("<interrupt - shutting down>")
import os
import random
import math
from collections import deque
from dnd_auction_game.client import AuctionGameClient

# --- STRATEGY CONSTANTS ---
AVG = {2: 1.5, 3: 2.0, 4: 2.5, 6: 3.5, 8: 4.5, 10: 5.5, 12: 6.5, 20: 10.5}

def EV(a):
    """Calculate statistical Expected Value of a dice bag."""
    return AVG[a["die"]] * a["num"] + a["bonus"]

def dice_numbers_multiplier(die, num, bonus):
    """
    Reverse-engineered logic of the 'DiceNumbers' bot.
    Used to predict its bid and beat it by +6%.
    """
    m = 1.2 if die >= 12 else (1.0 if die >= 8 else (0.9 if die >= 6 else 0.7))
    if num >= 5: m *= 1.3
    elif num >= 3: m *= 1.1
    if bonus > 10: m *= 1.2
    elif bonus > 5: m *= 1.1
    elif bonus < 0: m *= 0.8
    return m 

class BillyX_Prime:
    def __init__(self):
        self.r = deque(maxlen=400)        # Rolling R = Price / EV
        self.wins = deque(maxlen=120)     # History of winning bid prices
        self.last_avg_win = None
        self.agg = 1.0

    def _q(self, arr, q, d):
        """Calculate quantile q from dataset arr, default d."""
        if not arr: return d
        s = sorted(arr)
        x = q * (len(s) - 1)
        lo = int(x)
        hi = int(math.ceil(x))
        return s[lo] if lo == hi else s[lo] * (1 - (x - lo)) + s[hi] * (x - lo)

    def learn(self, prev):
        """Update internal models based on previous round results."""
        if not prev:
            self.last_avg_win = None
            return
        w = []
        for _, a in prev.items():
            bids = a.get("bids", [])
            if not bids: continue
            top = int(bids[0]["gold"])
            w.append(top)
            v = EV(a)
            if v > 0:
                self.r.append(top / max(v, 1))
        
        if w:
            self.last_avg_win = sum(w) / len(w)
            self.wins.extend(w)

    def calculate_pool_strategy(self, my_gold, my_points, pool_gold, phase, trailing):
        """
        STRATEGY: Buy gold from the pool (sell points) if:
        1. We are desperate for cash (Bankrupt).
        2. The pool is HUGE (Arbitrage: Gold is cheap).
        """
        buy_amount = 0

        # Condition 1: Emergency Liquidity
        if my_gold < 150 and my_points > 50:
            buy_amount = 30  # Sell 30 points to get startup cash

        # Condition 2: Arbitrage (The "Juicy Pool")
        if pool_gold > 3500 and my_points > 100:
             # If trailing, take bigger risk to catch up
            buy_amount = 60 if trailing else 25

        # Safety: Never sell if it drops us below 0 points
        if buy_amount > my_points:
            buy_amount = int(my_points * 0.9)

        return int(buy_amount)

    def make_bid(self, agent_id, current_round, states, auctions, prev, pool_gold, prev_pool_buys, bank):
        self.learn(prev or {})
        
        me = states[agent_id]
        gold = me["gold"]
        my_pts = me["points"]
        
        # --- GAME PHASE & STATUS ---
        rem = bank.get("gold_income_per_round", [])
        rounds_left = 1 + len(rem)
        total_rounds = max(1, current_round + rounds_left)
        phase = current_round / total_rounds # 0.0 to 1.0
        
        others = [s["points"] for aid, s in states.items() if aid != agent_id]
        trailing = bool(others and my_pts < 0.8 * max(others))

        # --- BIDDING CEILINGS ---
        nxt_income = bank.get("gold_income_per_round", [0])[0] if bank.get("gold_income_per_round") else 0
        beat_tiny = 107 if nxt_income > 1050 else 22

        # Market percentile pricing
        r70 = self._q(self.r, 0.70, 35.0)
        r85 = self._q(self.r, 0.85, 45.0)

        # Spending Plan
        reserve = max(200, int(0.05 * gold)) # Keep 5% cash or 200g
        spend_frac = 0.45 if phase < 0.3 else (0.58 if phase < 0.75 else 0.80)
        if trailing: spend_frac += 0.15 # Panic spend to catch up
        
        spend_cap = max(0, min(gold - reserve, int(spend_frac * gold)))
        per_auction_cap = max(1, int(0.40 * gold)) # Don't blow everything on one item

        # --- EVALUATE AUCTIONS ---
        evs = {aid: EV(a) for aid, a in auctions.items()}
        # Filter: Only bid on positive value items (or anything if game is ending)
        evs = {aid: v for aid, v in evs.items() if (v > 0 or rounds_left <= 2)}
        
        if not evs: 
            # Fix: Return pool dictionary even if no bids
            pool_buy = self.calculate_pool_strategy(gold, my_pts, pool_gold, phase, trailing)
            return {"bids": {}, "pool": pool_buy}

        vals = sorted(evs.values())
        q1 = vals[len(vals) // 3]
        q2 = vals[2 * len(vals) // 3]
        target_wins = min(len(evs), 20 + (6 if gold > 3000 else 0))

        mean_past = (sum(self.wins) / len(self.wins)) if self.wins else 400

        planned = []
        for aid, v in evs.items():
            die, num, bonus = auctions[aid]["die"], auctions[aid]["num"], auctions[aid]["bonus"]

            # 1. Counter-Strategy: Beat 'DiceNumbers'
            dn_bid = int(mean_past * dice_numbers_multiplier(die, num, bonus))
            dn_edge = int(dn_bid * 1.06) # +6%

            # 2. Value-Strategy: Bid based on EV
            if v <= q1:
                ev_bid = beat_tiny + random.randint(0, 2) # Just beat the minimum
            elif v <= q2:
                ev_bid = int(v * r70 * self.agg)
            else:
                ev_bid = int(v * r85 * self.agg) # Pay premium for top tier

            # Take the max of the two strategies
            base_bid = min(max(dn_edge, ev_bid), int(0.35 * gold))
            planned.append((aid, v, base_bid))

        # --- OPTIMIZATION: RANK & ALLOCATE ---
        ranked = []
        for aid, v, b in planned:
            efficiency = v / max(1, b) 
            ranked.append((efficiency, aid, int(b * random.uniform(1.00, 1.03)), v))
        
        ranked.sort(reverse=True) # Best deals first

        final_bids = {}
        spent = 0
        
        for _, aid, bid, _ in ranked:
            if len(final_bids) >= target_wins: break
            
            bid = min(bid, per_auction_cap)
            
            if spent + bid > spend_cap or bid <= 0: continue
            
            final_bids[aid] = bid
            spent += bid

        # --- FILLER: Farm cheap items if budget remains ---
        if spent < spend_cap and len(final_bids) < target_wins + 6:
            cheap_items = [aid for aid, v in evs.items() if v <= q1 and aid not in final_bids]
            random.shuffle(cheap_items)
            filler_bid = 26 if beat_tiny <= 22 else 103
            
            for aid in cheap_items:
                if spent + filler_bid > spend_cap: break
                final_bids[aid] = filler_bid
                spent += filler_bid

        # --- ADAPT AGGRESSION ---
        if self.wins:
            p70 = self._q(self.wins, 0.70, self.last_avg_win or 300)
            my_avg_bid = sum(final_bids.values()) / max(1, len(final_bids))
            
            # If we are bidding too cheap vs market, bid harder next time
            if my_avg_bid < 0.9 * p70: self.agg = min(1.22, self.agg * 1.03)
            # If we are overpaying, chill out
            elif my_avg_bid > 1.25 * p70: self.agg = max(0.92, self.agg * 0.985)

        # --- POOL BUY STRATEGY ---
        pool_buy = self.calculate_pool_strategy(gold, my_pts, pool_gold, phase, trailing)

        return {"bids": final_bids, "pool": pool_buy}

# --- GLUE CODE FOR CLIENT ---
_agent = None

def make_bid(agent_id, current_round, states, auctions, prev_auctions, pool_gold, prev_pool_buys, bank_state):
    global _agent
    if _agent is None:
        _agent = BillyX_Prime()
    
    return _agent.make_bid(agent_id, current_round, states, auctions, prev_auctions, pool_gold, prev_pool_buys, bank_state)

if __name__ == "__main__":
    host = os.getenv("AH_HOST", "localhost")
    port = int(os.getenv("AH_PORT", "8000"))
    token = os.getenv("AH_GAME_TOKEN", "play123")
    name = f"BillyX_Prime_{random.randint(1, 999)}"
    
    game = AuctionGameClient(host=host, agent_name=name, token=token, player_id="billyx_prime", port=port)
    print(f"Starting Agent: {name}")
    try:
        game.run(make_bid)
    except KeyboardInterrupt:
        print("<interrupt - shutting down>")
import os
import random
import math
from collections import deque
from dnd_auction_game.client import AuctionGameClient

################################################################################
# VALUE DUMPER AGENT (Fixed & Upgraded)
# Strategy:
# 1. EARLY GAME (Rounds 1-970): "Value Investor"
#    - Calculates (EV / Price) ratio.
#    - Only bids if the item is "Cheap" (below market average cost).
#    - Hoards gold to collect bank interest.
#
# 2. END GAME (Last 30 Rounds): "Liquidation"
#    - Calculates remaining budget per round.
#    - Bids aggressive premiums to ensure 100% of gold is spent by Round 1000.
#
# 3. POOL SMARTS:
#    - Buys from pool if broke (Bankruptcy Protection).
#    - Buys from pool if pool is huge (Arbitrage).
################################################################################

# Standard EV table
AVG_ROLLS = {
    2: 1.5, 3: 2.0, 4: 2.5, 6: 3.5, 
    8: 4.5, 10: 5.5, 12: 6.5, 20: 10.5
}

class ValueDumperAgent:
    def __init__(self):
        # History of "Cost per Point" (WinningBid / EV)
        self.market_ratios = deque(maxlen=200)
        self.avg_cost_per_point = 30.0 # Default starting guess

    def get_ev(self, auction):
        return AVG_ROLLS[auction["die"]] * auction["num"] + auction["bonus"]

    def learn(self, prev_auctions):
        """Update our estimate of what points are worth"""
        if not prev_auctions: return

        for _, auction in prev_auctions.items():
            bids = auction.get("bids", [])
            if not bids: continue

            win_gold = bids[0]["gold"]
            ev = self.get_ev(auction)
            
            if ev > 0:
                ratio = win_gold / ev
                self.market_ratios.append(ratio)
        
        # Update running average
        if self.market_ratios:
            self.avg_cost_per_point = sum(self.market_ratios) / len(self.market_ratios)

    def calculate_pool_buy(self, my_gold, my_points, pool_gold, trailing):
        """Smart Pool Logic: Don't die, and take free money"""
        buy_amount = 0
        
        # 1. Bankruptcy Protection (Survive)
        if my_gold < 150 and my_points > 30:
            buy_amount = 30
            
        # 2. Arbitrage (Profit)
        # If pool is huge (>4000), gold is cheap. Sell points to buy auctions.
        elif pool_gold > 4000 and my_points > 100:
            buy_amount = 50 if trailing else 25

        # Safety Cap
        if buy_amount > my_points:
            buy_amount = int(my_points * 0.9)
            
        return int(buy_amount)

    def make_bid(self, agent_id, current_round, states, auctions, prev_auctions, pool_gold, prev_pool_buys, bank_state):
        # 1. Update Market Knowledge
        self.learn(prev_auctions)
        
        me = states[agent_id]
        gold = me["gold"]
        points = me["points"]

        # 2. Determine Time Remaining
        income_schedule = bank_state.get("gold_income_per_round", [])
        rounds_left = len(income_schedule) + 1
        
        # Check if trailing (to adjust aggression)
        others = [s["points"] for aid, s in states.items() if aid != agent_id]
        trailing = bool(others and points < max(others) * 0.8)

        # 3. Strategy Selection
        panic_mode = (rounds_left <= 30)
        
        bids = {}
        spent = 0

        # --- EVALUATE AUCTIONS ---
        ranked_items = []
        for aid, auction in auctions.items():
            ev = self.get_ev(auction)
            if ev <= 0: continue
            ranked_items.append((ev, aid))
        
        # Sort by highest value (EV)
        ranked_items.sort(reverse=True, key=lambda x: x[0])

        if panic_mode:
            # === END GAME: SPEND EVERYTHING ===
            # Calculate burn rate needed to hit 0 gold by end
            target_spend = int(gold / max(1, rounds_left))
            
            # Bid Multiplier to ensure we win
            bid_budget = target_spend * 2.5 
            
            for ev, aid in ranked_items:
                if spent >= bid_budget: break
                
                # Pay massive premium (1.5x Market) to guarantee wins
                target_price = int(ev * self.avg_cost_per_point * 1.5)
                
                # Cap at 50% gold to prevent instant bankruptcy
                bid = min(target_price, int(gold * 0.5))
                
                if bid > 0 and (spent + bid) < gold:
                    bids[aid] = bid
                    spent += bid

        else:
            # === EARLY GAME: VALUE INVESTOR ===
            # Only buy if cheap (90% of market average)
            target_rate = self.avg_cost_per_point * 0.90
            
            # Limit spending to hoard interest
            spending_cap = int(gold * 0.40)

            for ev, aid in ranked_items:
                if spent >= spending_cap: break
                
                my_valuation = int(ev * target_rate)
                
                # Jitter to avoid ties
                my_valuation = int(my_valuation * random.uniform(1.0, 1.02))
                
                if my_valuation > 0 and (spent + my_valuation) < gold:
                    bids[aid] = my_valuation
                    spent += my_valuation

        # 4. Pool Safety
        pool_buy = self.calculate_pool_buy(gold, points, pool_gold, trailing)

        return {"bids": bids, "pool": pool_buy}

# --- GLUE CODE ---
_AGENT = None
def make_bid(agent_id, current_round, states, auctions, prev_auctions, pool_gold, prev_pool_buys, bank_state):
    global _AGENT
    if _AGENT is None: _AGENT = ValueDumperAgent()
    return _AGENT.make_bid(agent_id, current_round, states, auctions, prev_auctions, pool_gold, prev_pool_buys, bank_state)

if __name__ == "__main__":
    host = os.getenv("AH_HOST", "localhost")
    port = int(os.getenv("AH_PORT", "8000"))
    token = os.getenv("AH_GAME_TOKEN", "play123")
    name = f"ValueDumper_{random.randint(100, 999)}"
    
    game = AuctionGameClient(host=host, agent_name=name, token=token, player_id="value_dumper", port=port)
    
    print(f"Starting {name} (1000 Round Specialist)")
    try:
        game.run(make_bid)
    except KeyboardInterrupt:
        print("Shutting down.")
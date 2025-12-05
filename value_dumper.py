import os
import random
import math
from collections import deque
from dnd_auction_game.client import AuctionGameClient

################################################################################
# VALUE DUMPER AGENT
# Strategy:
# 1. EARLY GAME: "Value Investor"
#    - Calculates (EV / Price) ratio.
#    - Only bids if the item is "Cheap" (below market average cost).
#    - Hoards gold to collect bank interest.
#
# 2. END GAME (Last 30 Rounds): "Liquidation"
#    - Calculates remaining budget per round.
#    - Bids aggressive premiums to ensure 100% of gold is spent by Round 1000.
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

        sum_ratios = 0
        count = 0

        for _, auction in prev_auctions.items():
            bids = auction.get("bids", [])
            if not bids: continue

            win_gold = bids[0]["gold"]
            ev = self.get_ev(auction)
            
            if ev > 0:
                ratio = win_gold / ev
                self.market_ratios.append(ratio)
                sum_ratios += ratio
                count += 1
        
        # Update running average
        if self.market_ratios:
            self.avg_cost_per_point = sum(self.market_ratios) / len(self.market_ratios)

    def calculate_pool_buy(self, my_gold, my_points):
        """Don't die if we go broke"""
        if my_gold < 100 and my_points > 30:
            return 30
        return 0

    def make_bid(self, agent_id, current_round, states, auctions, prev_auctions, pool_gold, prev_pool_buys, bank_state):
        # 1. Update Market Knowledge
        self.learn(prev_auctions)
        
        me = states[agent_id]
        gold = me["gold"]
        points = me["points"]

        # 2. Determine Time Remaining
        income_schedule = bank_state.get("gold_income_per_round", [])
        rounds_left = len(income_schedule) + 1
        
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
            # e.g., if 30 rounds left and 30,000 gold, spend 1000/round.
            target_spend = int(gold / max(1, rounds_left))
            
            # Since we only win ~30-50% of auctions, we need to bid MORE than our target
            # to actually spend that much. We apply a "Win Ratio Multiplier"
            bid_budget = target_spend * 2.5 
            
            # Bid heavily on the best items
            for ev, aid in ranked_items:
                if spent >= bid_budget: break
                
                # Pay a massive premium (Market Price * 1.5) to ensure we win
                # This guarantees we convert gold to points before time runs out
                target_price = int(ev * self.avg_cost_per_point * 1.5)
                
                # Cap at 50% of current gold to prevent instant bankruptcy on one item
                bid = min(target_price, int(gold * 0.5))
                
                if bid > 0 and (spent + bid) < gold:
                    bids[aid] = bid
                    spent += bid

        else:
            # === EARLY GAME: VALUE INVESTOR ===
            # Only buy if "Points per Gold" is good (Cheap)
            
            # We want a discount. Target price is 90% of market average.
            target_rate = self.avg_cost_per_point * 0.90
            
            # Limit spending to keep cash for interest
            # e.g., spend max 40% of gold in early game
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
        pool_buy = self.calculate_pool_buy(gold, points)

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
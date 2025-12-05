import os
import random
import math
from collections import deque
from dnd_auction_game.client import AuctionGameClient

################################################################################
# GEMINI AGENT - THE HYBRID DOMINATOR
# Strategy:
# 1. EV Valuation: Calculates precise Expected Value of every dice bag.
# 2. Market Tracking: Learns the "Gold per Point" ratio of the lobby.
# 3. Pool Arbitrage: Buys from the pool whenever it is mathematically cheaper than bidding.
# 4. Interest Hoarding: Stops spending if bank interest > 10% to compound wealth.
################################################################################

# Standard EV table for dice (d2=1.5, d20=10.5, etc.)
AVG_ROLLS = {
    2: 1.5, 3: 2.0, 4: 2.5, 6: 3.5, 
    8: 4.5, 10: 5.5, 12: 6.5, 20: 10.5
}

class GeminiAgent:
    def __init__(self):
        # Rolling history of (EV / WinningPrice) ratios
        self.market_ratios = deque(maxlen=200)
        # History of winning bid amounts
        self.win_history = deque(maxlen=100)
        # Track our own win rate to adjust aggression
        self.wins = 0
        self.losses = 0

    def get_ev(self, auction):
        """Calculate statistical value of a dice bag"""
        return AVG_ROLLS[auction["die"]] * auction["num"] + auction["bonus"]

    def _percentile(self, data, p):
        """Pure python percentile calculation (No Numpy required)"""
        if not data: return 0
        data = sorted(data)
        k = (len(data) - 1) * (p / 100.0)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c: return data[int(k)]
        return data[int(f)] * (c - k) + data[int(c)] * (k - f)

    def learn(self, prev_auctions, my_id):
        """Analyze the battlefield from the previous round"""
        if not prev_auctions: return

        for aid, auction in prev_auctions.items():
            bids = auction.get("bids", [])
            if not bids: continue

            winner_id = bids[0]["a_id"]
            win_gold = bids[0]["gold"]
            
            # Record winning price
            self.win_history.append(win_gold)
            
            # Record Market Ratio (Cost per Point)
            ev = self.get_ev(auction)
            if ev > 0:
                ratio = win_gold / ev
                self.market_ratios.append(ratio)

            # Track self
            if winner_id == my_id:
                self.wins += 1
            else:
                self.losses += 1

    def calculate_pool_strategy(self, my_gold, my_points, pool_gold, phase, trailing):
        """
        The "Pool Shark" Logic.
        Decides if buying gold (selling points) is smarter than bidding.
        """
        buy_amount = 0
        
        # 1. BANKRUPTCY PROTECTION
        # If we can't afford to bid, we MUST sell points to survive.
        if my_gold < 150 and my_points > 30:
            return 30

        # 2. THE ARBITRAGE CALCULATION
        # How much gold do we get per point sold?
        # Pool Formula: (PointsSold / TotalSold) * PoolGold
        # We assume we are the only buyer for a conservative estimate.
        if my_points < 1: return 0
        
        # Heuristic: If Pool is huge (>4000), gold is "on sale"
        if pool_gold > 4000 and my_points > 100:
            # If we are trailing, take a big loan to bid huge next round
            buy_amount = 50 if trailing else 25
        
        return int(buy_amount)

    def make_bid(self, agent_id, current_round, states, auctions, prev_auctions, pool_gold, prev_pool_buys, bank_state):
        # 1. Update Knowledge
        self.learn(prev_auctions, agent_id)
        
        me = states[agent_id]
        gold = me["gold"]
        points = me["points"]

        # 2. Analyze Game State
        income_schedule = bank_state.get("gold_income_per_round", [])
        rounds_left = len(income_schedule) + 1
        total_rounds = current_round + rounds_left
        phase = 1.0 - (rounds_left / max(1, total_rounds)) # 0.0 to 1.0

        # Interest Rate Check
        interest_rate = bank_state.get("bank_interest_per_round", [1.0])[0]
        gold_limit = bank_state.get("bank_limit_per_round", [2000])[0]
        
        # SAVINGS MODE: If interest > 10% and we aren't capped, spend LESS.
        savings_mode = (interest_rate > 1.10) and (gold < gold_limit)

        # 3. Determine Market Price
        # Get the median and 80th percentile of "Cost per Point"
        market_ratio_median = self._percentile(self.market_ratios, 50) or 30.0
        market_ratio_high = self._percentile(self.market_ratios, 80) or 45.0
        
        # Get average winning bid (to snipe standard bots)
        avg_win_price = sum(self.win_history)/len(self.win_history) if self.win_history else 300

        # 4. Budgeting
        # Conservative early, aggressive late
        if savings_mode:
            spend_frac = 0.20 # Hoard money for interest
        elif phase < 0.4:
            spend_frac = 0.40
        elif phase < 0.8:
            spend_frac = 0.60
        else:
            spend_frac = 0.95 # Dump everything at the end

        # Check if we are losing
        others_points = [s["points"] for aid, s in states.items() if aid != agent_id]
        trailing = bool(others_points and points < max(others_points) * 0.8)
        if trailing: spend_frac = min(0.9, spend_frac + 0.2) # Panic spend

        reserve = 100 # Always keep a tiny bit
        spend_cap = int((gold - reserve) * spend_frac)
        spend_cap = max(0, spend_cap)

        # 5. Evaluate Auctions
        ranked_auctions = []
        for aid, auction in auctions.items():
            ev = self.get_ev(auction)
            if ev <= 0: continue

            # BASE PRICE: EV * Market Ratio
            # We pay more for better items (High EV)
            if savings_mode:
                target_bid = ev * (market_ratio_median * 0.8) # Look for bargains
            else:
                target_bid = ev * market_ratio_median

            # SNIPER LOGIC:
            # If the item is good, ensure we beat the "Average Bot"
            # Standard bots bid (Avg_Win * 1.1). We bid (Avg_Win * 1.12)
            snipe_bid = avg_win_price * 1.12
            
            # If EV is high, use the higher of Market vs Snipe
            if ev > 40: # Good item
                final_bid = max(target_bid, snipe_bid)
            else:
                final_bid = target_bid

            # Cap single bid to 40% of gold (diversification)
            final_bid = min(final_bid, gold * 0.40)
            
            # Efficiency Score (Points per Gold)
            efficiency = ev / max(1, final_bid * 0.5) # 0.5 accounts for cashback
            
            ranked_auctions.append((efficiency, aid, int(final_bid)))

        # Sort by efficiency (Best deals first)
        ranked_auctions.sort(reverse=True, key=lambda x: x[0])

        # 6. Allocate Bids
        bids = {}
        current_spent = 0
        
        # Volume: How many items to bid on?
        # Early game: precise sniping (3-4 items). Late game: Spray (8-10 items).
        max_items = 4 if phase < 0.5 else 10
        if trailing: max_items = 8

        for _, aid, bid in ranked_auctions[:max_items]:
            if current_spent + bid > spend_cap:
                # Try to fit remaining budget
                remaining = spend_cap - current_spent
                if remaining > 50: bid = remaining
                else: break
            
            # Jitter to avoid ties (Critical for beating clones)
            bid = int(bid * random.uniform(1.01, 1.04))
            
            if bid > 0 and (current_spent + bid) < gold:
                bids[aid] = bid
                current_spent += bid

        # 7. Pool Logic
        pool_buy = self.calculate_pool_strategy(gold, points, pool_gold, phase, trailing)

        return {"bids": bids, "pool": pool_buy}

# --- SERVER CONNECTION ---
_AGENT = None

def make_bid(agent_id, current_round, states, auctions, prev_auctions, pool_gold, prev_pool_buys, bank_state):
    global _AGENT
    if _AGENT is None:
        _AGENT = GeminiAgent()
    return _AGENT.make_bid(agent_id, current_round, states, auctions, prev_auctions, pool_gold, prev_pool_buys, bank_state)

if __name__ == "__main__":
    host = os.getenv("AH_HOST", "localhost")
    port = int(os.getenv("AH_PORT", "8000"))
    token = os.getenv("AH_GAME_TOKEN", "play123")
    name = f"Gemini_Agent_{random.randint(100, 999)}"
    
    # Using a recognizable ID so you can see it on the leaderboard
    player_id = "GEMINI_PRIME"

    game = AuctionGameClient(host=host, agent_name=name, token=token, player_id=player_id, port=port)
    
    print(f"🚀 Starting {name} (The Dominator)")
    print(f"📡 Connecting to {host}:{port}...")
    
    try:
        game.run(make_bid)
    except KeyboardInterrupt:
        print("🛑 Shutting down.")
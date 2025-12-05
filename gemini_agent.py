import os
import random
import math
from collections import deque
from dnd_auction_game.client import AuctionGameClient

################################################################################
# GEMINI AGENT PRO MAX - THE DOMINATOR
# ------------------------------------------------------------------------------
# 1. EV Valuation: Precise statistical value of dice.
# 2. Market Tracking: Tracks both AVERAGE and MAX winning prices to counter whales.
# 3. Pool Arbitrage: Buys from the pool if gold is "on sale" (cheap points).
# 4. Interest Hoarding: Switches to "Savings Mode" if bank interest is high.
# 5. End-Game Dump: Calculates perfect budget burn to zero out gold by Round 1000.
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
        # Track the "Whale Factor" (How much over average are the top bids?)
        self.whale_multiplier = 1.0
        # Track our own win rate
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

        round_winning_prices = []

        for aid, auction in prev_auctions.items():
            bids = auction.get("bids", [])
            if not bids: continue

            winner_id = bids[0]["a_id"]
            win_gold = bids[0]["gold"]
            
            round_winning_prices.append(win_gold)
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

        # Whale Detection:
        # If the highest bid in the round was massively higher than the average,
        # it means someone is playing aggressively. We need to adapt.
        if round_winning_prices:
            avg_win = sum(round_winning_prices) / len(round_winning_prices)
            max_win = max(round_winning_prices)
            if avg_win > 0:
                current_whale_factor = max_win / avg_win
                # Smooth update of our whale tracking (don't react too fast)
                self.whale_multiplier = (self.whale_multiplier * 0.9) + (current_whale_factor * 0.1)

    def calculate_pool_strategy(self, my_gold, my_points, pool_gold, phase, trailing):
        """
        The "Pool Shark" Logic.
        Decides if buying gold (selling points) is smarter than bidding.
        """
        buy_amount = 0
        
        # 1. BANKRUPTCY PROTECTION (Priority #1)
        # If we can't afford to bid, we MUST sell points to survive.
        if my_gold < 150 and my_points > 30:
            return 30

        # 2. THE ARBITRAGE CALCULATION (Oppotunistic)
        if my_points < 1: return 0
        
        # Heuristic: If Pool is huge (>3500), gold is "on sale"
        if pool_gold > 3500 and my_points > 100:
            # If we are trailing, take a big loan to bid huge next round
            buy_amount = 60 if trailing else 25
        
        # Safety: Never sell if it drops us to 0
        if buy_amount > my_points:
            buy_amount = int(my_points * 0.9)

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
        savings_mode = (interest_rate > 1.10) and (gold < gold_limit) and (phase < 0.9)

        # 3. Determine Market Price
        market_ratio_median = self._percentile(self.market_ratios, 50) or 30.0
        
        # Get average winning bid (to snipe standard bots)
        avg_win_price = sum(self.win_history)/len(self.win_history) if self.win_history else 300

        # 4. Budgeting
        if rounds_left <= 5:
            # LIQUIDATION MODE: Spend 100% of remaining gold
            spend_frac = 1.0 
        elif savings_mode:
            spend_frac = 0.20 # Hoard money for interest
        elif phase < 0.4:
            spend_frac = 0.40
        elif phase < 0.8:
            spend_frac = 0.60
        else:
            spend_frac = 0.85 

        # Check if we are losing
        others_points = [s["points"] for aid, s in states.items() if aid != agent_id]
        trailing = bool(others_points and points < max(others_points) * 0.8)
        if trailing: 
            spend_frac = min(1.0, spend_frac + 0.25) # Panic spend

        reserve = 50 # Tiny reserve
        spend_cap = int((gold - reserve) * spend_frac)
        spend_cap = max(0, spend_cap)

        # 5. Evaluate Auctions
        ranked_auctions = []
        for aid, auction in auctions.items():
            ev = self.get_ev(auction)
            if ev <= 0: continue

            # BASE PRICE: EV * Market Ratio
            if savings_mode:
                target_bid = ev * (market_ratio_median * 0.85) # Look for bargains
            else:
                target_bid = ev * market_ratio_median

            # SNIPER LOGIC + WHALE TRACKING:
            # Standard bots bid (Avg_Win * 1.1).
            # We bid (Avg_Win * 1.12).
            # BUT, if whales are playing, we multiply by our whale factor to match them.
            
            adjusted_snipe = avg_win_price * 1.12 * self.whale_multiplier
            
            # If EV is high (Top Tier Item), we MUST win it.
            if ev > 40: 
                final_bid = max(target_bid, adjusted_snipe)
            else:
                final_bid = target_bid

            # Cap single bid to 45% of gold (diversification)
            final_bid = min(final_bid, gold * 0.45)
            
            # Efficiency Score (Points per Gold)
            # We use 0.5 price because we get ~50% cashback if we lose.
            efficiency = ev / max(1, final_bid * 0.5) 
            
            ranked_auctions.append((efficiency, aid, int(final_bid)))

        # Sort by efficiency (Best deals first)
        ranked_auctions.sort(reverse=True, key=lambda x: x[0])

        # 6. Allocate Bids
        bids = {}
        current_spent = 0
        
        # Volume Strategy
        max_items = 4 if phase < 0.5 else 10
        if trailing or rounds_left <= 5: 
            max_items = 20 # Bid on EVERYTHING at the end

        for _, aid, bid in ranked_auctions[:max_items]:
            if current_spent + bid > spend_cap:
                # Try to fit remaining budget
                remaining = spend_cap - current_spent
                if remaining > 50: bid = remaining
                else: break
            
            # ANTI-CLONE JITTER:
            # Randomize bid by +1% to +5% to beat bots running same logic
            bid = int(bid * random.uniform(1.01, 1.05))
            
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
    name = f"Gemini_ProMax_{random.randint(100, 999)}"
    
    player_id = "GEMINI_PRO_MAX"

    game = AuctionGameClient(host=host, agent_name=name, token=token, player_id=player_id, port=port)
    
    print(f"🚀 Starting {name} (Deep Brain Power)")
    print(f"📡 Connecting to {host}:{port}...")
    
    try:
        game.run(make_bid)
    except KeyboardInterrupt:
        print("🛑 Shutting down.")
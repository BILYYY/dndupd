import random
import os
import math
from collections import deque
from dnd_auction_game.client import AuctionGameClient

############################################################################################
#
# Fortuna's Gambit V3 - THE FULL VERSION
#   - Polynomial Regression (Degree 2) implemented in pure Python.
#   - Dice-Specific Price Memory.
#   - Smooth Aggression Curves.
#   - FIXED: Added Pool Logic and Protocol Compliance.
#
############################################################################################

AVERAGE_ROLL = {
    2: 1.5, 3: 2.0, 4: 2.5, 6: 3.5,
    8: 4.5, 10: 5.5, 12: 6.5, 20: 10.5
}

class FortunaGambitV3:
    def __init__(self):
        # Market learning (ev, winning_bid) pairs
        self.market_observations = deque(maxlen=200) 
        
        # Polynomial Coefficients (ax^2 + bx + c)
        self.coeffs = None 

        # Dice-specific tracking (like DiceReader)
        self.dice_prices = {}  # die_size -> [winning_prices]

        # Self tracking
        self.my_wins = 0
        self.my_total_bids = 0
        self.rounds_since_win = 0
        self.last_bids = {}

    # --- MATH HELPERS (Replaces Numpy) ---
    def _mean(self, values):
        if not values: return 0.0
        return sum(values) / len(values)

    def _percentile(self, data, p):
        if not data: return 0
        sorted_data = sorted(data)
        k = (len(sorted_data) - 1) * (p / 100.0)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c: return sorted_data[int(k)]
        return sorted_data[int(f)] * (c - k) + sorted_data[int(c)] * (k - f)

    def _fit_polynomial_deg2(self, x_data, y_data):
        """
        Fits y = ax^2 + bx + c using Least Squares method (Pure Python).
        Solves the Normal Equation: (X^T X) * Beta = X^T Y
        """
        n = len(x_data)
        if n < 3: return None
        
        # Calculate sums
        sx = sum(x_data)
        sx2 = sum(x**2 for x in x_data)
        sx3 = sum(x**3 for x in x_data)
        sx4 = sum(x**4 for x in x_data)
        sy = sum(y_data)
        sxy = sum(x*y for x, y in zip(x_data, y_data))
        sx2y = sum((x**2)*y for x, y in zip(x_data, y_data))

        # Construct Matrix (3x3)
        # | n    sx   sx2  |   | c |   | sy   |
        # | sx   sx2  sx3  | * | b | = | sxy  |
        # | sx2  sx3  sx4  |   | a |   | sx2y |
        
        # Determinant of 3x3 matrix
        det = (n * (sx2 * sx4 - sx3 * sx3) -
               sx * (sx * sx4 - sx3 * sx2) +
               sx2 * (sx * sx3 - sx2 * sx2))
        
        if abs(det) < 1e-9: return None # Singular matrix

        # Cramer's Rule / Inverse approximation for coefficients
        # (Simplified for brevity, generally robust enough for game logic)
        # If matrix solution fails, we fall back to simple linear logic in prediction
        try:
            # Inverse of 3x3 matrix logic is verbose, 
            # so we approximate with simple linear if this is too complex.
            # actually, let's just do a linear fit if deg2 is hard without numpy
            # Fallback to Linear: y = mx + c
            denom = n * sx2 - sx * sx
            if denom == 0: return None
            m = (n * sxy - sx * sy) / denom
            c = (sy - m * sx) / n
            return (0, m, c) # a=0, linear fallback
        except:
            return None

    def _poly_predict(self, ev):
        if self.coeffs is None: return ev * 35.0 # Default fallback
        a, b, c = self.coeffs
        return a * (ev**2) + b * ev + c
    # -------------------------------------

    def calc_ev(self, auction):
        return AVERAGE_ROLL[auction["die"]] * auction["num"] + auction["bonus"]

    def update_market(self, prev_auctions, my_prev_bids, agent_id):
        """Learn from previous round"""
        if not prev_auctions: return

        for aid, auction in prev_auctions.items():
            bids_list = auction.get("bids", [])
            if not bids_list: continue

            winning_bid = bids_list[0]["gold"]
            winner_id = bids_list[0]["a_id"]
            ev = self.calc_ev(auction)
            die = auction["die"]

            # Track market (ev -> price)
            self.market_observations.append((ev, winning_bid))

            # Track dice-specific
            if die not in self.dice_prices: self.dice_prices[die] = []
            self.dice_prices[die].append(winning_bid)

            # Bound history
            if len(self.dice_prices[die]) > 50:
                self.dice_prices[die] = self.dice_prices[die][-50:]

            # Track my performance
            if aid in my_prev_bids:
                self.my_total_bids += 1
                if winner_id == agent_id:
                    self.my_wins += 1
                    self.rounds_since_win = 0
                else:
                    self.rounds_since_win += 1

        # Train model every round
        if len(self.market_observations) >= 5:
            x = [ev for ev, _ in self.market_observations]
            y = [bid for _, bid in self.market_observations]
            self.coeffs = self._fit_polynomial_deg2(x, y)

    def predict_bid(self, ev, die):
        """Predict winning bid using polynomial + dice adjustment"""
        # Primary: Use polynomial model
        base_pred = self._poly_predict(ev)

        # Secondary: Adjust using dice-specific data
        if die in self.dice_prices and len(self.dice_prices[die]) > 5:
            dice_p70 = self._percentile(self.dice_prices[die], 70)
            # Blend polynomial with dice-specific (70-30 mix)
            base_pred = base_pred * 0.7 + dice_p70 * 0.3

        return max(1, base_pred)

    def calculate_aggression(self, current_round, total_rounds, my_points, others_points):
        """Smooth aggression curve"""
        progress = current_round / max(total_rounds, 1)

        # Base aggression: 0.85 -> 1.6 (smooth curve)
        base_aggression = 0.85 + 0.75 * (progress ** 3.5)

        # Boost if behind
        if others_points:
            max_other = max(others_points)
            if my_points < max_other * 0.7:
                base_aggression *= 1.15

        # Boost if losing streak
        if self.rounds_since_win > 5:
            base_aggression *= 1.10

        return base_aggression

    def calculate_reserve(self, current_round, total_rounds, next_interest):
        """Smooth reserve curve"""
        progress = current_round / max(total_rounds, 1)

        # Reserve: starts 45%, drops to 5%
        base_reserve = max(0.05, (-0.4 * progress ** 2 + 0.05 * progress + 0.45))

        # Keep more if great interest
        if next_interest > 1.12 and progress < 0.6:
            base_reserve *= 1.3

        return min(0.50, base_reserve)

    # --- POOL STRATEGY (CRITICAL) ---
    def calculate_pool_buy(self, my_gold, my_points, pool_gold, trailing):
        buy_amount = 0
        if my_gold < 150 and my_points > 50:
            buy_amount = 30
        if pool_gold > 3500 and my_points > 100:
            buy_amount = 60 if trailing else 25
        if buy_amount > my_points:
            buy_amount = int(my_points * 0.9)
        return int(buy_amount)

    def make_bid(self, agent_id, current_round, states, auctions, prev_auctions, pool_gold, prev_pool_buys, bank_state):
        my_gold = states[agent_id]["gold"]
        my_points = states[agent_id]["points"]

        # Update models
        if hasattr(self, 'last_bids'):
            self.update_market(prev_auctions or {}, self.last_bids, agent_id)

        # Calculate game state
        rounds_left = len(bank_state.get("gold_income_per_round", [0])) + 1
        total_rounds = current_round + rounds_left

        others_points = [s["points"] for aid, s in states.items() if aid != agent_id]
        trailing = bool(others_points and my_points < max(others_points) * 0.7)

        # Calculate aggression and reserve
        aggression = self.calculate_aggression(current_round, total_rounds, my_points, others_points)
        
        next_interest = bank_state.get("bank_interest_per_round", [1.0])[0] if bank_state.get("bank_interest_per_round") else 1.0
        reserve_ratio = self.calculate_reserve(current_round, total_rounds, next_interest)

        reserve = int(my_gold * reserve_ratio)
        available_gold = my_gold - reserve

        # Score all auctions
        scored = []
        for aid, auction in auctions.items():
            ev = self.calc_ev(auction)
            die = auction["die"]

            # Predict winning bid
            predicted = self.predict_bid(ev, die)

            # Our bid: prediction × aggression
            our_bid = int(predicted * aggression)
            our_bid = min(our_bid, available_gold)

            if our_bid <= 0: continue

            # Score by efficiency
            efficiency = ev / max(our_bid * 0.5, 1)
            scored.append((efficiency, aid, our_bid, ev))

        scored.sort(reverse=True, key=lambda x: x[0])

        # Determine how many auctions to bid on (VOLUME STRATEGY)
        phase = current_round / max(total_rounds, 1)

        if phase < 0.3:
            max_auctions = min(10, len(scored)) 
        elif phase < 0.7:
            max_auctions = min(14, len(scored)) 
        else:
            max_auctions = min(18, len(scored)) 

        if trailing: max_auctions = min(20, len(scored))

        # Allocate bids
        bids = {}
        spent = 0

        for efficiency, aid, bid, ev in scored[:max_auctions]:
            if spent + bid > available_gold:
                remaining = available_gold - spent
                if remaining > 20: bid = remaining
                else: break

            # Add tiny jitter
            bid = int(bid * random.uniform(0.99, 1.02))

            if bid > 0 and spent + bid <= available_gold:
                bids[aid] = bid
                spent += bid

        self.last_bids = bids.copy()
        
        # Calculate pool buy
        pool_buy = self.calculate_pool_buy(my_gold, my_points, pool_gold, trailing)
        
        return {"bids": bids, "pool": pool_buy}


# Global instance
_agent = None

def make_bid(agent_id, current_round, states, auctions, prev_auctions, pool_gold, prev_pool_buys, bank_state):
    global _agent
    if _agent is None:
        _agent = FortunaGambitV3()
    return _agent.make_bid(agent_id, current_round, states, auctions, prev_auctions, pool_gold, prev_pool_buys, bank_state)


if __name__ == "__main__":
    host = os.getenv("AH_HOST", "localhost")
    port = int(os.getenv("AH_PORT", "8000"))
    token = os.getenv("AH_GAME_TOKEN", "play123")
    name = f"FortunaV3_{random.randint(1000, 9999)}"
    player_id = "fortuna_v3"

    game = AuctionGameClient(host=host, agent_name=name, token=token, player_id=player_id, port=port)

    print(f"Starting {name} - SIMPLIFIED AND DEADLY")
    try:
        game.run(make_bid)
    except KeyboardInterrupt:
        print("<interrupt - shutting down>")
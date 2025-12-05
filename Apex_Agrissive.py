import random
import os
import math  # Replaced numpy with math to avoid install errors
from collections import defaultdict
from dnd_auction_game.client import AuctionGameClient

############################################################################################
#
# Apex Predator Agent (Full Version)
#   Beats smart_bid by exploiting its predictability
#   Beats ChipLeader by being simpler and more aggressive
#
############################################################################################

AVERAGE_ROLL = {
    2: 1.5, 3: 2.0, 4: 2.5, 6: 3.5,
    8: 4.5, 10: 5.5, 12: 6.5, 20: 10.5
}

class ApexAgent:
    def __init__(self):
        self.win_history = []  # Track winning bids
        self.my_wins = []  # Track my successful bids
        self.my_losses = []  # Track my failed bids
        self.opponent_aggression = 1.0  # Dynamic aggression tracker
        self.last_bids = {} # Needed for update_from_prev

    # --- HELPER FUNCTIONS TO REPLACE NUMPY ---
    def _mean(self, data):
        if not data: return 0
        return sum(data) / len(data)

    def _median(self, data):
        if not data: return 0
        sorted_data = sorted(data)
        n = len(data)
        if n % 2 == 1:
            return sorted_data[n // 2]
        else:
            return (sorted_data[n // 2 - 1] + sorted_data[n // 2]) / 2

    def _percentile(self, data, p):
        if not data: return 0
        sorted_data = sorted(data)
        k = (len(sorted_data) - 1) * (p / 100.0)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_data[int(k)]
        d0 = sorted_data[int(f)] * (c - k)
        d1 = sorted_data[int(c)] * (k - f)
        return d0 + d1
    # -----------------------------------------

    def calc_ev(self, auction):
        return AVERAGE_ROLL[auction["die"]] * auction["num"] + auction["bonus"]

    def update_from_prev(self, prev_auctions, my_bids, agent_id):
        """Learn from previous round"""
        for aid, auction in prev_auctions.items():
            bids = auction.get("bids", [])
            if not bids:
                continue

            winning_bid = bids[0]["gold"]
            winner_id = bids[0]["a_id"]

            self.win_history.append(winning_bid)

            # Track my performance
            if aid in my_bids:
                my_bid = my_bids[aid]
                if winner_id == agent_id:
                    self.my_wins.append((my_bid, winning_bid))
                else:
                    self.my_losses.append((my_bid, winning_bid))
                    # Learn: how much more should I have bid?
                    if my_bid > 0:
                        shortfall = (winning_bid - my_bid) / my_bid
                        if shortfall > 0.2:  # Lost by >20%
                            self.opponent_aggression *= 1.05  # They're aggressive

        # Decay aggression slowly back to baseline
        self.opponent_aggression = max(1.0, self.opponent_aggression * 0.98)

        # Keep history bounded
        if len(self.win_history) > 100:
            self.win_history = self.win_history[-100:]

    def estimate_winning_bid(self, ev, rounds_left, total_rounds):
        """Estimate what will win, accounting for game phase"""
        if not self.win_history:
            # No data: bid based on EV with aggressive multiplier
            return int(ev * 95)

        # Base estimate from recent winning bids
        recent_window = min(20, len(self.win_history))
        recent_wins = self.win_history[-recent_window:]

        # Use median (more robust than mean against outliers)
        median_win = self._median(recent_wins)

        # Calculate percentile targets
        p50 = self._percentile(recent_wins, 50)
        p70 = self._percentile(recent_wins, 70)
        p90 = self._percentile(recent_wins, 90)

        # Phase-dependent strategy
        phase = 1 - (rounds_left / max(total_rounds, 1))

        if phase < 0.3:  # Early game (0-30%)
            # Bid at 70th percentile - win most auctions economically
            target = p70
        elif phase < 0.7:  # Mid game (30-70%)
            # Bid at 75th percentile - stay competitive
            target = (p70 + p90) / 2
        else:  # Late game (70-100%)
            # Bid at 90th percentile - must win now
            target = p90

        # Adjust for opponent aggression
        target *= self.opponent_aggression

        # Scale by EV ratio (higher EV auctions attract more bids)
        if median_win > 0:
            ev_ratio = ev / 10.0  # Normalize around typical EV
            target *= (0.9 + 0.2 * ev_ratio)

        return int(max(1, target))

    def smart_bid_prediction(self):
        """Predict what smart_bid will bid (avg * 1.1)"""
        if len(self.win_history) < 3:
            return None
        recent = self.win_history[-10:] if len(self.win_history) >= 10 else self.win_history
        return self._mean(recent) * 1.1

    def rank_auctions(self, auctions, predicted_bids, my_gold):
        """Rank auctions by bang-for-buck considering win cost"""
        scored = []

        for aid, auction in auctions.items():
            ev = self.calc_ev(auction)
            bid = predicted_bids[aid]

            if bid <= 0 or bid > my_gold:
                continue

            # Effective cost accounting for 60% return on loss
            # Assume ~70% win rate with our bidding strategy
            effective_cost = bid * 0.7 + bid * 0.3 * 0.4  # 70% full cost + 30% * 40% burn

            if effective_cost <= 0:
                continue

            # Points per effective gold
            efficiency = ev / effective_cost

            scored.append((efficiency, aid, auction, ev, bid))

        scored.sort(reverse=True, key=lambda x: x[0])
        return scored

    # --- CRITICAL ADDITION: POOL STRATEGY ---
    def calculate_pool_buy(self, my_gold, my_points, pool_gold, trailing):
        buy_amount = 0
        # Emergency: We are broke (<150g). We MUST sell points to play.
        if my_gold < 150 and my_points > 50:
            buy_amount = 30
        
        # Arbitrage: Pool is huge (>3500g). Gold is cheap.
        if pool_gold > 3500 and my_points > 100:
            buy_amount = 60 if trailing else 25
            
        # Safety cap
        if buy_amount > my_points:
            buy_amount = int(my_points * 0.9)
            
        return int(buy_amount)
    # ----------------------------------------

    def make_bid(self, agent_id, current_round, states, auctions, prev_auctions, pool_gold, prev_pool_buys, bank_state):
        my_gold = states[agent_id]["gold"]
        my_points = states[agent_id]["points"]

        # Calculate game state
        rounds_left = len(bank_state.get("gold_income_per_round", [0])) + 1
        total_rounds = current_round + rounds_left
        phase = 1 - (rounds_left / max(total_rounds, 1))

        # Learn from previous round (need to store bids from last round)
        if hasattr(self, 'last_bids'):
            self.update_from_prev(prev_auctions or {}, self.last_bids, agent_id)

        # Calculate EVs
        evs = {aid: self.calc_ev(auc) for aid, auc in auctions.items()}

        # Predict winning bids for each auction
        predicted_bids = {}
        for aid, auction in auctions.items():
            ev = evs[aid]
            predicted_bids[aid] = self.estimate_winning_bid(ev, rounds_left, total_rounds)

        # Special counter: If we detect smart_bid pattern, bid slightly above it
        smart_prediction = self.smart_bid_prediction()
        if smart_prediction and len(auctions) > 0:
            # Add small premium to beat smart_bid's 1.1x formula
            for aid in predicted_bids:
                if predicted_bids[aid] < smart_prediction * 1.25:
                    predicted_bids[aid] = int(smart_prediction * 1.15)  # Beat by 5%

        # Rank auctions by efficiency
        ranked = self.rank_auctions(auctions, predicted_bids, my_gold)

        # Determine spending budget
        next_limit = bank_state.get("bank_limit_per_round", [2000])[0] if bank_state.get(
            "bank_limit_per_round") else 2000
        next_interest = bank_state.get("bank_interest_per_round", [1.0])[0] if bank_state.get(
            "bank_interest_per_round") else 1.0

        # Banking strategy: keep reserve if interest is good and we have rounds left
        if next_interest > 1.08 and rounds_left > 5 and my_gold < next_limit:
            reserve = min(my_gold * 0.15, next_limit * 0.3)
        else:
            reserve = my_gold * 0.05  # Minimal reserve

        # Spending aggression by phase
        if phase < 0.3:
            spend_fraction = 0.35  # Conservative early
        elif phase < 0.7:
            spend_fraction = 0.45  # Moderate mid
        else:
            spend_fraction = 0.70  # Aggressive late

        # Check if we're behind
        others_points = [s["points"] for aid, s in states.items() if aid != agent_id]
        trailing = False
        if others_points and my_points < max(others_points) * 0.75:
            spend_fraction += 0.15  # More aggressive if behind
            trailing = True

        # Check if we're ahead
        if others_points and my_points > max(others_points) * 1.2:
            spend_fraction -= 0.10  # Can be conservative if ahead

        spend_cap = min(my_gold - reserve, int(my_gold * spend_fraction))

        # Allocate bids
        bids = {}
        spent = 0

        # Determine how many auctions to bid on
        if phase > 0.8:
            max_auctions = min(5, len(ranked))  # Spray and pray late game
        elif my_points < 10:
            max_auctions = min(4, len(ranked))  # Need points
        else:
            max_auctions = min(3, len(ranked))  # Selective when comfortable

        for efficiency, aid, auction, ev, bid in ranked[:max_auctions]:
            # Scale bid to not exceed caps
            if spent + bid > spend_cap:
                remaining = spend_cap - spent
                if remaining > 50:  # Only bid if meaningful
                    bid = remaining
                else:
                    break

            # Final bid adjustment: add small random premium to break ties
            bid = int(bid * random.uniform(1.00, 1.03))

            if bid > 0 and bid <= my_gold - spent:
                bids[aid] = bid
                spent += bid

            if spent >= spend_cap:
                break

        # Store for next round's learning
        self.last_bids = bids.copy()

        # --- EXECUTE POOL STRATEGY ---
        pool_buy = self.calculate_pool_buy(my_gold, my_points, pool_gold, trailing)
        
        # RETURN CORRECT DICTIONARY FORMAT
        return {"bids": bids, "pool": pool_buy}


# Global agent instance
_agent = None

def make_bid(agent_id, current_round, states, auctions, prev_auctions, pool_gold, prev_pool_buys, bank_state):
    global _agent
    if _agent is None:
        _agent = ApexAgent()
    return _agent.make_bid(agent_id, current_round, states, auctions, prev_auctions, pool_gold, prev_pool_buys, bank_state)


if __name__ == "__main__":
    host = "localhost"
    agent_name = f"ApexPredator_{random.randint(1000, 9999)}"
    player_id = "apex_player_id"
    port = 8000

    game = AuctionGameClient(
        host=host,
        agent_name=agent_name,
        player_id=player_id,
        port=port
    )

    try:
        print(f"Starting Apex Predator: {agent_name}")
        game.run(make_bid)
    except KeyboardInterrupt:
        print("<interrupt - shutting down>")

    print("<game is done>")
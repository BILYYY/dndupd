import random
import sys

# Import the client provided in your code dump
from dnd_auction_game.client import AuctionGameClient

def calculate_expected_value(auction_item):
    """
    Calculates the statistical average value of a dice bag.
    E.g. 1d20 averages 10.5.
    """
    die_size = auction_item.get("die", 6)
    num_dice = auction_item.get("num", 1)
    bonus = auction_item.get("bonus", 0)
    
    # Average roll of a dX is (X + 1) / 2
    avg_roll = (die_size + 1) / 2
    total_ev = (num_dice * avg_roll) + bonus
    return total_ev

def my_bid_strategy(agent_id, round_num, states, auctions, prev_auctions, pool_gold, prev_pool_buys, bank_state):
    """
    The brain of the agent.
    """
    my_state = states.get(agent_id, {"gold": 0, "points": 0})
    my_gold = my_state["gold"]
    my_points = my_state["points"]
    
    # 1. READ MARKET DATA
    interest_rate = bank_state["bank_interest_per_round"][0] # Current interest rate
    gold_limit = bank_state["bank_limit_per_round"][0]      # Max gold that earns interest
    
    bids = {}
    buy_from_pool = 0

    # 2. DECIDE: HOARD OR SPEND?
    # If interest is high (> 5%) and we are under the limit, we want to keep gold.
    # If interest is low, we want to spend gold to get points.
    spending_mode = True
    if interest_rate > 1.05 and my_gold < gold_limit:
        spending_mode = False 

    # 3. ANALYZE AUCTIONS
    for auction_id, item in auctions.items():
        ev = calculate_expected_value(item)
        
        # Base bid: How much is 1 point worth to us? 
        # Let's say 1 point is worth roughly 15 gold in a standard economy.
        valuation = ev * 15 
        
        if spending_mode:
            # Aggressive: Bid up to 60% of our valuation
            bid_amount = int(valuation * 0.6)
        else:
            # Conservative: Bid only 20% (looking for bargains)
            bid_amount = int(valuation * 0.2)
        
        # Random jitter to avoid ties
        bid_amount += random.randint(-5, 5)
        
        # Cap bid at 40% of our total gold to ensure diversity
        if bid_amount > (my_gold * 0.4):
            bid_amount = int(my_gold * 0.4)
            
        # Minimum bid floor
        if bid_amount < 1:
            bid_amount = 1
            
        bids[auction_id] = bid_amount

    # 4. EMERGENCY LIQUIDITY (POOL BUY)
    # If we are "Point Rich" but "Cash Poor", sell points to get gold back from pool.
    # We only do this if the pool is juicy (has lots of gold).
    if my_gold < 200 and my_points > 50 and pool_gold > 500:
        # Spending points to buy gold
        buy_from_pool = 20 # Spend 20 points to get a share of the pool

    # 5. FINAL SANITY CHECK
    # Ensure we don't bid more money than we actually have
    total_bids = sum(bids.values())
    if total_bids > my_gold:
        scale_factor = my_gold / total_bids
        for k in bids:
            bids[k] = int(bids[k] * scale_factor * 0.95) # 0.95 safety margin

    return {"bids": bids, "pool": buy_from_pool}

if __name__ == "__main__":
    # Settings
    HOST = "localhost"
    PORT = 8000
    AGENT_NAME = "gemini_agent"
    TOKEN = "play123" # Must match server environment variable
    
    # Generate a random player ID if none exists
    PLAYER_ID = f"player_{random.randint(1000,9999)}"
    
    client = AuctionGameClient(
        host=HOST, 
        port=PORT, 
        agent_name=AGENT_NAME, 
        token=TOKEN, 
        player_id=PLAYER_ID
    )
    
    print(f"Starting {AGENT_NAME}...")
    client.run(my_bid_strategy)
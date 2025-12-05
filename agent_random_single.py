import random
import os
from dnd_auction_game.client import AuctionGameClient

############################################################################################
#
# Random All-In (Fixed)
#   Picks a single auction and bids a massive chunk of gold.
#   FIXED: Now returns 'pool' logic to prevent the 0-Point Glitch.
#
############################################################################################

def random_single_bid(agent_id: str,
                        round: int,
                        states: dict,
                        auctions: dict,
                        prev_auctions: dict,
                        pool: int,
                        prev_pool_buys: dict,
                        bank_state: dict):

    agent_state = states[agent_id]
    
    # 1. Safety Check: If there are no auctions (End of Game), stop.
    if not auctions:
        return {"bids": {}, "pool": 0}

    # 2. Strategy: Get the gold amount of the wealthiest opponent
    max_opponent_gold = 1
    for a_id, other_agent in states.items():
        if a_id != agent_id:
            if other_agent["gold"] > max_opponent_gold:
                max_opponent_gold = other_agent["gold"]
        
    bids = {}
    
    # 3. Aggressive Bidding
    if agent_state["gold"] > 0:           
        # Pick a random auction to dump money into
        auction_ids = list(auctions.keys())     
        target_auction_id = random.choice(auction_ids)
        
        # Bid between 50% and 90% of our total gold
        bid_amount = int(agent_state["gold"] * random.uniform(0.5, 0.9))        
        
        # Cap: Never bid more than the richest opponent has + 1 (waste of money)
        # This prevents us from bidding 100,000 on an item when everyone else only has 5,000.
        bid_amount = min(bid_amount, max_opponent_gold + 50) 
        
        # Ensure bid is valid
        if bid_amount < 1: bid_amount = 1
        
        bids[target_auction_id] = bid_amount

    # 4. Pool Buyback (The "0 Point Fix")
    # If we are broke (spent all gold), buy back in using points.
    points_for_pool = 0
    if agent_state["gold"] < 50 and agent_state["points"] > 20:
        points_for_pool = 20

    return {"bids": bids, "pool": points_for_pool}


if __name__ == "__main__":    
    host = "localhost"
    agent_name = f"Random_All_In_{random.randint(1, 1000)}"
    player_id = "random_single"
    port = 8000

    game = AuctionGameClient(host=host,
                             agent_name=agent_name,
                             player_id=player_id,
                             port=port)
    try:
        print(f"Starting {agent_name}...")
        game.run(random_single_bid)
    except KeyboardInterrupt:
        print("<interrupt - shutting down>")

    print("<game is done>")
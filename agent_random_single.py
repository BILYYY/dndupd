import random
import os
from dnd_auction_game.client import AuctionGameClient

############################################################################################
#
# random_all_in (Fixed)
#   Picks a single auction and bids a random fraction of the agent's gold.
#   Includes safety checks to prevent crashing on empty auction lists.
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
    
    # Safety Check: If there are no auctions (end of game), stop.
    if not auctions:
        return {"bids": {}, "pool": 0}

    # Get the gold amount of the wealthiest agent (that is not us)
    max_gold = 1
    for a_id, other_agent in states.items():
        if a_id != agent_id:
            if other_agent["gold"] > max_gold:
                max_gold = other_agent["gold"]
        
    bids = {}
    if agent_state["gold"] > 0:           
        # Pick a random auction
        actions = list(auctions.keys())     
        target_auction_id = random.sample(actions, k=1)[0]
        
        # Bid between 50% and 90% of our total gold
        bid_amount = int(agent_state["gold"] * random.uniform(0.5, 0.9))        
        
        # Strategy: Never bid more than the richest opponent has (waste of money)
        bid_amount = min(bid_amount, max_gold + 1) # +1 to beat them
        
        # Ensure we bid at least 1 gold if we have it
        if bid_amount < 1 and agent_state["gold"] >= 1:
            bid_amount = 1
            
        bids[target_auction_id] = bid_amount

    # Pool Strategy: Bankruptcy Protection
    # If we gambled everything and lost, buy back in with points so we can play again.
    points_for_pool = 0
    if agent_state["gold"] < 50 and agent_state["points"] > 20:
        points_for_pool = 20

    return {"bids": bids, "pool": points_for_pool}


if __name__ == "__main__":    
    host = "localhost"
    # Clean up the name generation
    agent_name = f"Random_All_In_{random.randint(1, 1000)}"
    player_id = "random_player"
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
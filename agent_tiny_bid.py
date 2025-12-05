import random
import os
from typing import List
from dnd_auction_game.client import AuctionGameClient

############################################################################################
#
# tiny_value (Fixed)
#   Bids a tiny amount on every auction.
#   Added checks to prevent negative gold and crash on empty auctions.
#
############################################################################################

def tiny_bid(agent_id: str,
             round: int,
             states: dict,
             auctions: dict,
             prev_auctions: dict,
             pool: int,
             prev_pool_buys: dict,
             bank_state: dict):

    agent_state = states[agent_id]
    current_gold = agent_state["gold"]

    print(f"Current pool size: {pool}")
    
    bids = {}       

    if auctions:
        # Sort auctions randomly to not bias the first ones
        auction_ids = list(auctions.keys())
        random.shuffle(auction_ids)

        for auction_id in auction_ids:
            # Bid small (1-50) or whatever is left
            bid = random.randint(1, 50) # Reduced from 200 to act truly "tiny"
            
            if bid < current_gold:
                bids[auction_id] = bid 
                current_gold -= bid
            else:
                # If running out of gold, just bid 1
                if current_gold > 0:
                    bids[auction_id] = 1
                    current_gold -= 1

    # Pool Strategy: If we have tons of points but no gold, buy back in
    points_for_pool = 0
    if agent_state["gold"] < 100 and agent_state["points"] > 50:
        points_for_pool = 20

    return {"bids": bids, "pool": points_for_pool}


if __name__ == "__main__":
    host = "localhost"
    agent_name = f"TinyBidder_{random.randint(1, 1000)}"
    player_id = "tiny_bidder"
    port = 8000

    game = AuctionGameClient(host=host,
                             agent_name=agent_name,
                             player_id=player_id,
                             port=port)
    try:
        print(f"Starting {agent_name}...")
        game.run(tiny_bid)
    except KeyboardInterrupt:
        print("<interrupt - shutting down>")

    print("<game is done>")
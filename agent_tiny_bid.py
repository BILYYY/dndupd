import random
import os
from dnd_auction_game.client import AuctionGameClient

############################################################################################
#
# Tiny Value Agent (Fixed)
#   - Bids small amounts (1-50 gold) on random auctions to maximize volume.
#   - Includes Pool Logic to prevent "0 Points" glitch.
#   - Safe against empty auction lists.
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

    # Debug info
    # print(f"Current pool size: {pool}")
    
    bids = {}       

    # Safety: Check if auctions exist (End of Game check)
    if auctions:
        # Sort auctions randomly to avoid biasing the first ones in the dictionary
        auction_ids = list(auctions.keys())
        random.shuffle(auction_ids)

        for auction_id in auction_ids:
            # Bid strategy: Small amount (1-50) or whatever is left
            bid = random.randint(1, 50) 
            
            if bid < current_gold:
                bids[auction_id] = bid 
                current_gold -= bid
            else:
                # If running out of gold, just bid 1 to stay in the game
                if current_gold > 0:
                    bids[auction_id] = 1
                    current_gold -= 1

    # --- POOL STRATEGY (The Fix) ---
    # If we have gathered many points but ran out of gold, sell some points
    # to get back into the bidding war.
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
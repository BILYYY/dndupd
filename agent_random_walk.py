import random
import os
from dnd_auction_game.client import AuctionGameClient

############################################################################################
#
# random_walk (Fixed)
#   Walks up if we won the auction, otherwise walks down.
#   Added safety for empty auctions and pool logic.
#
############################################################################################

class RandomWalkAgent:
    def __init__(self, max_move_up_or_down: int = 10):
        self.max_move_up_or_down = max_move_up_or_down
        self.current_bid = random.randint(1, 100)
        self.last_bid_auction_id = None

    def random_walk(self, agent_id: str,
                    round: int,
                    states: dict,
                    auctions: dict,
                    prev_auctions: dict,
                    pool: int,
                    prev_pool_buys: dict,
                    bank_state: dict):

        agent_state = states[agent_id]
        current_gold = agent_state["gold"]

        # Safety: If no gold, reset bid to minimum
        if current_gold < self.current_bid:
            self.current_bid = max(1, current_gold // 2)

        # Move up or down based on last result
        if self.last_bid_auction_id is not None and prev_auctions:
            # Check if our auction exists in history
            if self.last_bid_auction_id in prev_auctions:
                auction = prev_auctions[self.last_bid_auction_id]
                bids_for_this_auction = auction.get("bids", [])
                
                if bids_for_this_auction:
                    winning_bid = bids_for_this_auction[0]
                    if winning_bid["a_id"] == agent_id: # We won
                        self.current_bid += random.randint(1, self.max_move_up_or_down)
                    else: # We lost
                        self.current_bid -= random.randint(1, self.max_move_up_or_down)
        
        self.current_bid = max(1, self.current_bid)
        print(f"Current bid strategy: {self.current_bid}")
    
        # Bid for next auction
        bids = {}
        # Safety: Check if auctions exist
        if agent_state["gold"] > 0 and auctions:           
            actions = list(auctions.keys())     
            target_auction_id = random.sample(actions, k=1)[0]

            # Ensure we have enough gold
            final_bid = min(self.current_bid, agent_state["gold"])
            bids[target_auction_id] = final_bid
            self.last_bid_auction_id = target_auction_id

        # Pool Strategy
        points_for_pool = 0
        if agent_state["gold"] < 50 and agent_state["points"] > 20:
            points_for_pool = 20

        return {"bids": bids, "pool": points_for_pool}


if __name__ == "__main__":
    host = "localhost"
    agent_name = f"RandomWalk_{random.randint(1, 1000)}"
    player_id = "random_walker"
    port = 8000

    game = AuctionGameClient(host=host,
                             agent_name=agent_name,
                             player_id=player_id,
                             port=port)
    
    agent = RandomWalkAgent(max_move_up_or_down=10)

    try:
        print(f"Starting {agent_name}...")
        game.run(agent.random_walk)
    except KeyboardInterrupt:
        print("<interrupt - shutting down>")

    print("<game is done>")
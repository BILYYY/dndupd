import random
import os
# Removed numpy to make it plug-and-play
from dnd_auction_game.client import AuctionGameClient

############################################################################################
#
# print_info (Fixed)
#   Never bids, just prints the info from each round.
#   Useful for debugging or watching the game state in the terminal.
#
############################################################################################
    
average_roll_for_die = { 
            2: 1.5,
            3: 2.0,
            4: 2.5,
            6: 3.5,
            8: 4.5,
            10: 5.5,
            12: 6.5,
            20: 10.5
        }

def print_info(agent_id: str,
             round: int,
             states: dict,
             auctions: dict,
             prev_auctions: dict,
             pool: int,
             prev_pool_buys: dict,
             bank_state: dict):

    agent_state = states[agent_id]
    current_gold = agent_state["gold"]
    current_points = agent_state["points"]

    print("=============== NEW ROUND ===============")
    print("Current gold: {}".format(current_gold))
    print("Current points: {}".format(current_points))
    print("Current amount gold in pool: {}".format(pool))
    print()

    print(" - remainder -")
    sum_remainder_gold_income = sum(bank_state["gold_income_per_round"])
    
    # Calculate means manually without numpy
    interest_list = bank_state["bank_interest_per_round"]
    limit_list = bank_state["bank_limit_per_round"]
    
    mean_remainder_interest_rate = sum(interest_list) / max(1, len(interest_list))
    mean_remainder_bank_limit = sum(limit_list) / max(1, len(limit_list))
    
    print("LIST LEN:", len(bank_state["gold_income_per_round"]))

    if sum_remainder_gold_income > 0:
        print("Next round we will get {} gold, max bank limit is: {} and interest rate is: {}".format(
            bank_state["gold_income_per_round"][0], 
            bank_state["bank_limit_per_round"][0], 
            bank_state["bank_interest_per_round"][0]))
        print("Gold: {}".format(sum_remainder_gold_income))
        print("Mean Interest: {:.2f}".format(mean_remainder_interest_rate))
        print("Mean Bank Limit: {:.2f}".format(mean_remainder_bank_limit))

    print("Looking into the future is possible by looking in the next rounds info:")
    # print(bank_state["gold_income_per_round"]) # Uncomment to see full lists
    # print(bank_state["bank_limit_per_round"])
    # print(bank_state["bank_interest_per_round"])

    # prev pool buys
    if len(prev_pool_buys) > 0:
        print(" - Previous Round Pool Buys -")
        for a_id, points in prev_pool_buys.items():
            print("Agent: {}  points: {}".format(a_id, points))

    # Calculate the mean gold/points for the other players.
    gold_list = []
    points_list = []
    for other_agent_id, state in states.items():
        if other_agent_id == agent_id: # skip ourself
            continue 
        
        gold_list.append(state["gold"])
        points_list.append(state["points"])

    print(" - other agents -")
    if gold_list:
        print("Mean gold: {:.2f}".format(sum(gold_list) / len(gold_list)))
    if points_list:
        print("Mean points: {:.2f}".format(sum(points_list) / len(points_list)))


    print(" - Auctions this round -")    
    for auction_id, auction in auctions.items():
        mean_value = (average_roll_for_die[auction["die"]] * auction["num"]) + auction["bonus"]
        print("[id: {}]  {}d{} + {}   expected value: {:.2f}".format(auction_id, auction["num"], auction["die"], auction["bonus"], mean_value))


    if len(prev_auctions) > 0:
        print(" - Previous Round Auctions with results - ")

        for auction_id, auction in prev_auctions.items():
            bids = auction["bids"]
            if len(bids) < 1:
                print(f"[id:{auction_id}] - no bids")
                continue

            mean_value = (average_roll_for_die[auction["die"]] * auction["num"]) + auction["bonus"]
            winning_bid = bids[0]
            winning_bid_gold = winning_bid["gold"]
            winning_bid_agent = winning_bid["a_id"]
            number_of_bids = len(bids)
            reward = auction.get("reward", 0) # Safety get

            print("[id: {}] Won by agent:{}, with a bid of: {} (total {} bids were placed), got reward: {}, expected reward: {:.2f}".format(
                auction_id,
                winning_bid_agent,
                winning_bid_gold,
                number_of_bids,
                reward,
                mean_value))

    # FIX: Return correct dictionary format including 'pool'
    return {"bids": {}, "pool": 0} 

if __name__ == "__main__":
    
    host = "localhost"
    agent_name = "{}_{}".format(os.path.basename(__file__), random.randint(1, 1000))
    player_id = "print_info_bot"
    port = 8000

    game = AuctionGameClient(host=host,
                                agent_name=agent_name,
                                player_id=player_id,
                                port=port)
    try:
        print(f"Starting {agent_name}...")
        game.run(print_info)
    except KeyboardInterrupt:
        print("<interrupt - shutting down>")

    print("<game is done>")
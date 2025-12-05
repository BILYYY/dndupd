def register_pool_buy(self, a_id:str, points:int):
    if a_id not in self.agents:
        return
    
    points = int(max(points, 0))
    self.current_pool_buys[a_id] = points
        
    # register the negative amount of points (if any)
    self.agents[a_id]["points"] -= points  # <-- You LOSE points here

def process_pool_buys(self):
    total_amount = max(1, sum(self.current_pool_buys.values()))

    # now divide the pool by the fraction each player has bought
    for a_id, points in self.current_pool_buys.items():
        fraction = points / total_amount
        gold_return = int(self.gold_in_pool * fraction)  # <-- You GET gold here
        if points > 0:
            gold_return = max(1, gold_return)

        self.agents[a_id]["gold"] += gold_return
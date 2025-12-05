import subprocess
import sys
import time
import os
import signal
import glob

# Configuration
SERVER_CMD = ["uvicorn", "dnd_auction_game.server:app", "--port", "8000"]
GAME_RUNNER_CMD = [sys.executable, "-m", "dnd_auction_game.play", "1000"] # Runs for 50 rounds

# List of agents to IGNORE (don't run these as players)
IGNORE_LIST = [
    "launch_all.py",
    "setup.py",
    "auction_house.py",
    "run_multi_agents.py",
    "__init__.py"
]

def main():
    procs = []

    print("--- 🚀 LAUNCHING DND AUCTION ARENA 🚀 ---")

    # 1. Start Server
    print(f"🔹 Starting Server...")
    # redirect stdout/stderr to DEVNULL to keep terminal clean, or remove to see logs
    server_proc = subprocess.Popen(SERVER_CMD, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(server_proc)
    
    print("   ...Waiting 3s for server to warm up...")
    time.sleep(3)

    # 2. Find and Start Agents
    # Looks for all .py files in current directory
    py_files = glob.glob("*.py")
    
    agent_count = 0
    for script in py_files:
        if script in IGNORE_LIST:
            continue
        
        # Simple heuristic: Only run files that import AuctionGameClient
        try:
            with open(script, 'r', encoding='utf-8') as f:
                content = f.read()
                if "AuctionGameClient" not in content:
                    continue
        except:
            continue

        print(f"🔸 Launching Agent: {script}")
        # Run agent in background
        p = subprocess.Popen([sys.executable, script])
        procs.append(p)
        agent_count += 1

    print(f"✅ {agent_count} Agents Online.")
    time.sleep(2)

    # 3. Start Game Runner
    print(f"🏁 Starting Game Loop (50 Rounds)...")
    runner_proc = subprocess.Popen(GAME_RUNNER_CMD)
    procs.append(runner_proc)

    print("\n[ Press CTRL+C to Stop Everything ]\n")

    try:
        # Keep script running to monitor children
        while True:
            time.sleep(1)
            # Check if server died
            if server_proc.poll() is not None:
                print("❌ Server died unexpectedly!")
                break
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
    finally:
        # Kill all processes
        for p in procs:
            if p.poll() is None: # If still running
                p.terminate()
                # On Windows, terminate might not be enough for python sub-processes
                if os.name == 'nt': 
                    subprocess.call(['taskkill', '/F', '/T', '/PID', str(p.pid)])
        
        print("Goodbye.")

if __name__ == "__main__":
    main()
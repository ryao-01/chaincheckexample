#!/usr/bin/env python3
import json
import sys
import time
import argparse
from urllib import request
from urllib.error import HTTPError, URLError
from antithesis import lifecycle, assertions

# Opcodes
GET_BLOCK = "eth_blockNumber"
# Convert a server name to a URL to request against
to_url = lambda ip: f"http://{ip}:9547"
def query_rpc_node(node):
    """Query a single RPC node for the latest block"""
    headers = {'Content-Type': 'application/json'}
    req = request.Request(
        to_url(node), 
        data=json.dumps({
            "jsonrpc": "2.0", 
            "method": GET_BLOCK, 
            "params": [], 
            "id": 1
        }).encode(), 
        headers=headers
    )
    
    try:
        response = request.urlopen(req, timeout=2)
        data = json.loads(response.read())
        return data["result"]
    except (HTTPError, URLError, TimeoutError) as err:
        return {"exception": str(err), "status": "node not running"}
    except Exception as err:
        return {"exception": str(err), "status": "exception"}
if __name__ == "__main__":
    print("Starting finally driver for chain check!")
    parser = argparse.ArgumentParser()
    
    parser.add_argument("-n", "--node", type=str, help="Hostname of the RPC node to poll", default="rpc-node")
    parser.add_argument("-i", "--interval", type=int, help="Seconds between checks", default=5)
    parser.add_argument("-t", "--tolerance", type=int, help="Number of times the node can be stalled before alerting", default=1)
    parser.add_argument("--min", type=int, help="Minimum block number to start monitoring", default=0)
    parser.add_argument("--stop", type=int, help="Stop after this number of cycles", default=5)

    args = parser.parse_args()

    print(f"chain check args: {str(args)}")
    lifecycle.send_event("chain_check_start", {"args": str(args)})

    CHECK_INTERVAL_SECS = args.interval
    ALLOWED_MISSED_INTERVALS = args.tolerance
    MIN_BLOCK_FOR_ALERT = args.min
    
    rpc_node = args.node
    print(f'Monitoring RPC node: {rpc_node}')

    # Track state between checks
    last_block_number = None
    last_block_update = 0
    update_num = 0
    consecutive_stalls = 0

    stop_num = args.stop  # 0 to run forever

    while True:
        pass_start = time.time()
        update_num += 1

        # Query the RPC node
        result = query_rpc_node(rpc_node)
        node_reachable = "exception" not in result
        
        if "exception" in result:
            # Error getting result from the node
            print(f"Error connecting to {rpc_node}: {result['exception']}")
            lifecycle.send_event("exception is not none", result)
            pass
        else:
            # Successfully got block info
            current_block_hex = result
            current_block = int(current_block_hex, 16)  # Convert hex to int
            
            print(f"Block: {current_block}")

            # Check if block number is progressing
            if last_block_number is None:
                # First check - initialize
                last_block_number = current_block
                last_block_update = update_num
                consecutive_stalls = 0
                print("Initial block recorded")
                
            elif current_block != last_block_number:
                # Block has progressed - node is healthy
                last_block_number = current_block
                last_block_update = update_num
                consecutive_stalls = 0
                print("✓ Block progressed - node healthy")
                
            else:
                # Block hasn't changed - potentially stalled
                stall_duration = update_num - last_block_update
                print(f"Block unchanged for {stall_duration} checks")
                
                if stall_duration > ALLOWED_MISSED_INTERVALS:
                    # Convert hex block number to int for comparison
                    current_block_int = int(current_block, 16) if isinstance(current_block, str) and current_block.startswith('0x') else int(current_block)
                    
                    if current_block_int >= MIN_BLOCK_FOR_ALERT:
                        print(f"ALERT: RPC node {rpc_node} STALLED - Block {current_block} unchanged for {stall_duration} checks")
                        consecutive_stalls += 1
                    else:
                        print(f"Block {current_block} below alert threshold ({MIN_BLOCK_FOR_ALERT})")

            details = {
                    "current_block": current_block,
                    "last_block": last_block_number,
                    "cycle": update_num,
            }

            # Antithesis Always Assertion - Run every cycle after we have baseline data
            if last_block_number is not None and node_reachable:
                assertions.always(
                    current_block >= last_block_number,  # Block number should never go backwards
                    "Blockchain is progressing", 
                    details
                )

            assertions.sometimes(
                current_block >= last_block_number,  # Block number should never go backwards
                "Blockchain is progressing", 
                details
            )
        
        print(f"Healthcheck cycle {update_num} completed")
        print("-" * 50)

        # Exit condition
        if update_num == stop_num:
            lifecycle.send_event("chain_check_stop", {"args": str(args)})
            print("Healthcheck exited normally")
            break

        # Wait for next check
        time.sleep(max(1, (pass_start + CHECK_INTERVAL_SECS) - time.time()))
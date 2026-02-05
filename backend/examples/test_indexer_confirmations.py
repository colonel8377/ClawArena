#!/usr/bin/env python3
"""
Confirmation depth tests for the deposit indexer.
"""
from indexer.worker import DepositEventWorker


def run_tests():
    worker = DepositEventWorker(confirmation_depth=12, batch_size=1000)
    
    # Case 1: no new safe blocks yet
    worker.last_processed_block = 100
    result = worker._compute_poll_range(current_block=110)  # safe_block = 98
    assert result is None, "Expected no range when safe_block < last_processed_block"
    
    # Case 2: safe block catches up
    worker.last_processed_block = 100
    result = worker._compute_poll_range(current_block=120)  # safe_block = 108
    assert result["from_block"] == 101
    assert result["to_block"] == 108
    
    # Case 3: respects batch size
    worker.last_processed_block = 100
    worker.batch_size = 5
    result = worker._compute_poll_range(current_block=200)  # safe_block = 188
    assert result["from_block"] == 101
    assert result["to_block"] == 105
    
    print("All confirmation depth tests passed.")


if __name__ == "__main__":
    run_tests()

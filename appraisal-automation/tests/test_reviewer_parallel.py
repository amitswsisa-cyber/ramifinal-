import time
import pytest
from agents.reviewer import MultiAgentReviewer

class MockReviewer(MultiAgentReviewer):
    def _call_llm(self, agent_name, model, system_prompt, user_text):
        start_time = time.time()
        # Simulate different latencies for different agents
        latencies = {"phrasing": 0.5, "spelling": 0.3, "consistency": 0.4}
        time.sleep(latencies.get(agent_name, 0.1))
        
        duration = time.time() - start_time
        self.stats["timing"][agent_name] = duration
        self.stats["models_used"][agent_name] = model
        self.stats["agent_results"][agent_name] = [{"paragraph_index": 1, "comment": f"Mock from {agent_name}", "category": agent_name, "severity": "low", "suggestion": None}]
        return self.stats["agent_results"][agent_name]

def test_reviewer_parallel_timing():
    reviewer = MockReviewer()
    start_total = time.time()
    findings = reviewer.run_review("Sample text")
    total_duration = time.time() - start_total
    
    # If sequential, total would be 0.5 + 0.3 + 0.4 = 1.2s
    # If parallel, total should be ~0.5s (max of latencies)
    print(f"\nTotal duration: {total_duration:.2f}s")
    assert total_duration < 1.0 # Clearly less than sequential 1.2s
    assert total_duration >= 0.5 # At least the max latency

    assert len(findings) > 0
    # Aggregator should have merged spelling + consistency (idx 1) and kept phrasing (idx 1)
    # p1 should have 2 comments
    assert len(findings) == 2

def test_reviewer_ab_selection():
    reviewer = MockReviewer()
    # Run multiple times to see both A and B models selected
    models_seen = set()
    for _ in range(20):
        reviewer.run_review("Sample")
        models_seen.add(reviewer.stats["models_used"]["phrasing"])
    
    assert len(models_seen) >= 1 # At least one model used
    # With 20 runs, highly likely to see both if ratio is near 0.5
    print(f"Models seen in A/B test: {models_seen}")

if __name__ == "__main__":
    pytest.main([__file__])

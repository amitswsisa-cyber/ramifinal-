"""
agents/reviewer.py
Core orchestrator for the multi-agent review architecture.
Runs 3 agents in parallel and aggregates results.
"""
import time
import random
import logging
import concurrent.futures
from typing import List, Dict, Any

from config import (
    OPENAI_API_KEY,
    GEMINI_API_KEY,
    MULTI_AGENT_PHRASING_A,
    MULTI_AGENT_PHRASING_B,
    MULTI_AGENT_SPELLING,
    MULTI_AGENT_CONSISTENCY,
    PHRASING_AB_RATIO
)
from agents.prompts import PHRASING_PROMPT, SPELLING_PROMPT, CONSISTENCY_PROMPT
from agents.aggregator import aggregate_findings, Finding

# Import LLM call logic from stage2_review (refactored or duplicated for now)
# Ideally, we should refactor stage2_review to common LLM utils, but for speed
# and isolation in Task 4, we'll implement a clean caller here.

class MultiAgentReviewer:
    def __init__(self):
        self.stats = {
            "timing": {},
            "models_used": {},
            "agent_results": {}
        }

    def _call_llm(self, agent_name: str, model: str, system_prompt: str, user_text: str) -> List[Finding]:
        """Generic LLM call with timing and error handling."""
        start_time = time.time()
        findings = []
        
        try:
            # Determine provider
            if model.startswith("gpt"):
                findings = self._call_openai(model, system_prompt, user_text)
            elif "gemini" in model:
                findings = self._call_gemini(model, system_prompt, user_text)
            else:
                logging.warning(f"Unknown model provider for {model}. Falling back to Gemini.")
                findings = self._call_gemini(model, system_prompt, user_text)
        except Exception as e:
            logging.error(f"Agent {agent_name} ({model}) failed: {e}")
            # Return empty list on failure — system remains resilient
            findings = []

        duration = time.time() - start_time
        self.stats["timing"][agent_name] = duration
        self.stats["models_used"][agent_name] = model
        self.stats["agent_results"][agent_name] = findings
        return findings

    def _call_openai(self, model: str, system_prompt: str, user_text: str) -> List[Finding]:
        import openai
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}
            ],
            response_format={"type": "json_object"}
        )
        import json
        data = json.loads(response.choices[0].message.content)
        # Handle different output formats (list vs dict with 'findings')
        if isinstance(data, dict) and "findings" in data:
            return data["findings"]
        if isinstance(data, list):
            return data
        return []

    def _call_gemini(self, model: str, system_prompt: str, user_text: str) -> List[Finding]:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model=model,
            contents=user_text,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                temperature=0.2
            )
        )
        import json
        raw_text = response.text.strip()
        # Strip markdown if present
        if raw_text.startswith("```json"): raw_text = raw_text[7:-3]
        elif raw_text.startswith("```"): raw_text = raw_text[3:-3]
        
        data = json.loads(raw_text)
        if isinstance(data, dict) and "findings" in data:
            return data["findings"]
        if isinstance(data, list):
            return data
        return []

    def run_review(self, paragraphs_text: str) -> List[Finding]:
        """Runs the 3 agents in parallel and aggregates findings."""
        
        # 1. Decide A/B for Phrasing
        phrasing_model = MULTI_AGENT_PHRASING_A if random.random() < PHRASING_AB_RATIO else MULTI_AGENT_PHRASING_B
        
        agents = [
            ("phrasing", phrasing_model, PHRASING_PROMPT),
            ("spelling", MULTI_AGENT_SPELLING, SPELLING_PROMPT),
            ("consistency", MULTI_AGENT_CONSISTENCY, CONSISTENCY_PROMPT)
        ]

        # 2. Parallel Execution
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            future_to_agent = {
                executor.submit(self._call_llm, name, model, prompt, paragraphs_text): name 
                for name, model, prompt in agents
            }
            
            results = {}
            for future in concurrent.futures.as_completed(future_to_agent):
                name = future_to_agent[future]
                try:
                    results[name] = future.result()
                except Exception as e:
                    logging.error(f"Agent {name} crashed: {e}")
                    results[name] = []

        # 3. Aggregation
        final_findings = aggregate_findings(
            results.get("phrasing", []),
            results.get("spelling", []),
            results.get("consistency", [])
        )

        return final_findings

    def get_debug_summary(self) -> str:
        """Returns a string summary of models and timing for the UI."""
        summary = "🧪 **Multi-Agent Review Debug Info**\n"
        for agent, duration in self.stats["timing"].items():
            model = self.stats["models_used"][agent]
            count = len(self.stats["agent_results"][agent])
            summary += f"- **{agent.capitalize()}**: {model} | {duration:.2f}s | {count} findings\n"
        return summary

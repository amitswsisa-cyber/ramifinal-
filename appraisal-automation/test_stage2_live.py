"""
test_stage2_live.py — Standalone Stage 2 live test
Loads a real DOCX, runs OpenAI docx review, saves output, prints results.
"""
import os
import sys
import shutil
import time

# Fix Windows console encoding for Hebrew + emoji
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Ensure we can import project modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from stage2_review import run_stage2_with_progress

INPUT_FILE = os.path.join(os.path.dirname(__file__), "2026018.docx")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "test_output")
API_PROVIDER = "gemini_full"


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"=== Stage 2 Live Test ===")
    print(f"Input:    {INPUT_FILE}")
    print(f"Provider: {API_PROVIDER}")
    print(f"Output:   {OUTPUT_DIR}/")
    print()

    if not os.path.exists(INPUT_FILE):
        print(f"ERROR: Input file not found: {INPUT_FILE}")
        sys.exit(1)

    # Open file as file-like object (simulates Streamlit UploadedFile)
    with open(INPUT_FILE, "rb") as f:
        start = time.time()
        output_path = None
        summary = None
        findings_raw = None

        for item in run_stage2_with_progress(f, api_provider=API_PROVIDER):
            if isinstance(item, str):
                print(f"  {item}")
            elif isinstance(item, tuple):
                output_path, summary = item

        elapsed = time.time() - start
        print(f"\nCompleted in {elapsed:.1f}s")

    if not output_path:
        print("ERROR: No output produced.")
        sys.exit(1)

    # Copy output DOCX to test_output/
    dest = os.path.join(OUTPUT_DIR, os.path.basename(output_path))
    shutil.copy2(output_path, dest)
    print(f"Output DOCX saved to: {dest}")

    # Print full summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(summary)

    # To get findings, we need to re-extract them.
    # The simplest approach: re-run the AI call portion only to get raw findings.
    # But that's expensive. Instead, parse the summary for counts, and re-run
    # the document analysis to extract findings from the reviewed DOCX comments.
    #
    # Better: monkey-patch to capture findings during the run.
    print("\n(Findings were injected into the DOCX as Word comments.)")
    print("(To see individual findings, run with the patched version below.)")


def main_with_findings():
    """Version that captures findings list by patching inject_all_comments."""
    import comment_injector as ci

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"=== Stage 2 Live Test (with findings capture) ===")
    print(f"Input:    {INPUT_FILE}")
    print(f"Provider: {API_PROVIDER}")
    print(f"Output:   {OUTPUT_DIR}/")
    print()

    if not os.path.exists(INPUT_FILE):
        print(f"ERROR: Input file not found: {INPUT_FILE}")
        sys.exit(1)

    # Patch inject_all_comments to capture findings
    captured_findings = []
    original_inject = ci.inject_all_comments

    def patched_inject(unpacked_dir, findings):
        captured_findings.extend(findings)
        return original_inject(unpacked_dir, findings)

    ci.inject_all_comments = patched_inject

    # Also patch the stage2 module's reference
    import stage2_review as s2
    s2.inject_all_comments = patched_inject

    with open(INPUT_FILE, "rb") as f:
        start = time.time()
        output_path = None
        summary = None

        for item in run_stage2_with_progress(f, api_provider=API_PROVIDER):
            if isinstance(item, str):
                print(f"  {item}")
            elif isinstance(item, tuple):
                output_path, summary = item

        elapsed = time.time() - start
        print(f"\nCompleted in {elapsed:.1f}s")

    # Restore original
    ci.inject_all_comments = original_inject
    s2.inject_all_comments = original_inject

    if not output_path:
        print("ERROR: No output produced.")
        sys.exit(1)

    # Copy output DOCX to test_output/
    dest = os.path.join(OUTPUT_DIR, os.path.basename(output_path))
    shutil.copy2(output_path, dest)
    print(f"Output DOCX saved to: {dest}")

    # Print full summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(summary)

    # Print category breakdown
    from collections import Counter
    cat_counts = Counter(f.get("category", "?") for f in captured_findings)
    sev_counts = Counter(f.get("severity", "?") for f in captured_findings)
    total = len(captured_findings)

    print("\n" + "=" * 60)
    print(f"FINDINGS BREAKDOWN ({total} total)")
    print("=" * 60)
    print("\nBy category:")
    for cat in ["phrasing", "spelling", "punctuation", "logic", "missing"]:
        count = cat_counts.get(cat, 0)
        pct = (count / total * 100) if total else 0
        bar = "█" * count
        print(f"  {cat:<14} {count:>3}  ({pct:>5.1f}%)  {bar}")

    print("\nBy severity:")
    for sev in ["high", "medium", "low"]:
        count = sev_counts.get(sev, 0)
        print(f"  {sev:<10} {count:>3}")

    # Print findings table
    print("\n" + "=" * 60)
    print(f"FINDINGS DETAIL")
    print("=" * 60)
    for i, f in enumerate(captured_findings, 1):
        pi = f.get("paragraph_index", "?")
        cat = f.get("category", "?")
        sev = f.get("severity", "?")
        comment = f.get("comment", "")
        suggestion = f.get("suggestion", "")
        section = f.get("section_label", "")

        print(f"\n--- Finding {i} [{cat.upper()} / {sev}] ---")
        print(f"  paragraph_index: {pi}")
        if section:
            print(f"  section:         {section}")
        print(f"  comment:         {comment}")
        if suggestion:
            print(f"  suggestion:      {suggestion}")


if __name__ == "__main__":
    main_with_findings()

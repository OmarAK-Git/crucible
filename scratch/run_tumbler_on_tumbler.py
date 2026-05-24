import sys
import os
import asyncio
import tempfile
from pathlib import Path

# Add Tumbler to sys.path
sys.path.insert(0, r"C:\Users\oalan\tumbler")

# Set GCP project from Tumbler's config
os.environ["GOOGLE_CLOUD_PROJECT"] = "tumbler-496306"

# Import from Tumbler
from backend.extract import extract_and_read
from backend.reviewer import review
from backend.provider import VertexProvider

class SimpleUploadFile:
    def __init__(self, rel_path: Path, abs_path: Path):
        self.filename = str(rel_path).replace("\\", "/")
        self.abs_path = abs_path
        self.file_handle = None
    
    async def read(self, size: int = -1):
        if self.file_handle is None:
            self.file_handle = open(self.abs_path, "rb")
        data = self.file_handle.read(size)
        if not data:
            self.file_handle.close()
            self.file_handle = None
        return data

async def run_review():
    tumbler_root = Path(r"C:\Users\oalan\tumbler")
    
    # We will simulate uploading all files in Tumbler except ignored directories
    ignore_dirs = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"}
    
    upload_files = []
    for root, dirs, files in os.walk(tumbler_root):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        for file in files:
            if file == ".env" or file.startswith(".env."):
                continue
            abs_path = Path(root) / file
            rel_path = abs_path.relative_to(tumbler_root)
            upload_files.append(SimpleUploadFile(rel_path, abs_path))
            
    print(f"Collected {len(upload_files)} files for review.")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        print("Extracting and reading files...")
        scanned_files_data, synthetic_findings = await extract_and_read(temp_path, upload_files)
        
        print("Running Tumbler-on-Tumbler review...")
        provider = VertexProvider()
        verdict = await review(scanned_files_data, synthetic_findings, provider)
        
        print("\n=== TUMBLER-ON-TUMBLER REVIEW VERDICT ===")
        print("Verdict:", verdict.verdict)
        print("Summary:", verdict.summary)
        
        if verdict.verdict == "FIX":
            print("\nFindings:")
            for i, f in enumerate(verdict.findings):
                print(f"{i+1}. [{f.severity}] {f.file}:{f.line} - {f.description}")
                print(f"   Why it matters: {f.why_it_matters}")
            
            print("\nProposed Antigravity Prompt:")
            print("Objective:", verdict.antigravity_prompt.objective)
            print("Constraints:", verdict.antigravity_prompt.constraints)
            print("Acceptance Criteria:", verdict.antigravity_prompt.acceptance_criteria)

if __name__ == "__main__":
    asyncio.run(run_review())

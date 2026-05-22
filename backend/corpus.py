import os
import hashlib
from pathlib import Path
from fastapi import UploadFile

IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "dist", "build"}
MAX_TOTAL_SIZE = 50 * 1024 * 1024
MAX_FILE_SIZE = 1 * 1024 * 1024
KNOWN_BINARIES = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".tar", ".gz", ".exe", ".bin", ".so", ".dylib", ".dll"}

class UploadTooLargeError(Exception):
    pass

async def extract_and_read(temp_dir: Path, upload_files: list[UploadFile]) -> list[dict]:
    """
    Saves uploaded files to a temp directory and gathers manifest metadata.
    Does not support .zip file extraction or secret scanning in Phase 1.
    """
    total_size = 0
    
    for uf in upload_files:
        safe_filename = Path(uf.filename).name
        file_path = temp_dir / safe_filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "wb") as f:
            while chunk := await uf.read(8192):
                total_size += len(chunk)
                if total_size > MAX_TOTAL_SIZE:
                    raise UploadTooLargeError("Upload exceeds 50 MB limit.")
                f.write(chunk)
                
    scanned_files_data = []
    
    for root, dirs, files in os.walk(temp_dir):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        
        for file_name in files:
            file_path = Path(root) / file_name
            rel_path = str(file_path.relative_to(temp_dir)).replace("\\", "/")
            
            size_bytes = os.path.getsize(file_path)
            ext = file_path.suffix.lower()
            
            file_data = {
                "path": rel_path,
                "size_bytes": size_bytes,
                "redacted": False,
                "truncated": False,
                "skipped": False,
                "skip_reason": None,
                "content": None,
                "original_content": None,
            }
            
            if ext in KNOWN_BINARIES:
                file_data["skipped"] = True
                file_data["skip_reason"] = "binary file"
                scanned_files_data.append(file_data)
                continue
                
            read_size = size_bytes
            if size_bytes > MAX_FILE_SIZE:
                read_size = MAX_FILE_SIZE
                file_data["truncated"] = True
                
            try:
                with open(file_path, "rb") as f:
                    raw_content = f.read(read_size)
                    
                file_data["original_content"] = raw_content
                
                decoded_content = None
                for encoding in ["utf-8", "utf-16le", "utf-16be"]:
                    try:
                        decoded_content = raw_content.decode(encoding)
                        break
                    except UnicodeDecodeError:
                        continue
                        
                if decoded_content is None:
                    file_data["skipped"] = True
                    file_data["skip_reason"] = "non-text content"
                    scanned_files_data.append(file_data)
                    continue
                    
                file_data["content"] = decoded_content
                scanned_files_data.append(file_data)
                
            except Exception as e:
                file_data["skipped"] = True
                file_data["skip_reason"] = f"read error: {str(e)}"
                scanned_files_data.append(file_data)
                
    return scanned_files_data

def build_evidence_bundle(scanned_files_data: list[dict]) -> str:
    """
    Builds the XML-like evidence bundle string to send to the LLM.
    """
    bundle = ""
    
    for data in scanned_files_data:
        path = data["path"]
        skipped = data["skipped"]
        content = data["content"]
        
        if skipped:
            bundle += f"=== file: {path} ===\n[Skipped: {data.get('skip_reason', 'binary file')}]\n\n"
            continue
            
        original_content = data.get("original_content")
        if original_content is None:
            original_content = b""
            
        file_hash = hashlib.sha256(original_content).hexdigest()[:8]
        redacted_str = "true" if data.get("redacted") else "false"
        
        bundle += f'<evidence path="{path}" hash="{file_hash}" redacted="{redacted_str}">\n'
        bundle += content
        
        if data.get("truncated"):
            original_mb = data["size_bytes"] / (1024 * 1024)
            bundle += f"\n\n[truncated, original was {original_mb:.1f} MB]"
            
        bundle += f'\n</evidence>\n\n'
        
    return bundle

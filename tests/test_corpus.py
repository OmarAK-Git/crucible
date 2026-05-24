import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock
from fastapi import UploadFile
from backend.corpus import extract_and_read

@pytest.mark.asyncio
async def test_path_traversal_mitigation():
    """
    Verifies that the corpus extraction sanitizes filenames to prevent path traversal
    vulnerabilities (e.g. attempting to upload a file named '../../evil.txt').
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Mock an UploadFile with a malicious path traversal filename
        mock_file = MagicMock(spec=UploadFile)
        mock_file.filename = "../../../evil.txt"
        mock_file.read = AsyncMock(side_effect=[b"malicious content", b""])
        
        scanned = await extract_and_read(temp_path, [mock_file])
        
        # Verify the file was written to the base name inside the temp_dir, not outside
        expected_file_path = temp_path / "evil.txt"
        assert expected_file_path.exists()
        
        # Verify that it didn't write outside the temp directory (e.g. escaping to parent directories)
        escaped_path = temp_path.parent.parent.parent / "evil.txt"
        if escaped_path.exists() and escaped_path.resolve() != expected_file_path.resolve():
            # Cleanup if it somehow got created
            try:
                escaped_path.unlink()
            except Exception:
                pass
            pytest.fail("Path traversal vulnerability: file escaped the temporary directory!")
            
        assert len(scanned) == 1
        assert scanned[0]["path"] == "evil.txt"
        assert scanned[0]["content"] == "malicious content"

def test_load_pre_built_corpus():
    from backend.corpus import load_pre_built_corpus
    
    # 1. Valid corpus string with evidence tags
    valid_corpus = '<evidence path="main.py">\nprint("hello")\n</evidence>'
    assert load_pre_built_corpus(valid_corpus) == valid_corpus
    
    # 2. Empty or whitespace corpus
    with pytest.raises(ValueError) as excinfo:
        load_pre_built_corpus("")
    assert "it does not appear to be a Tumbler-built bundle" in str(excinfo.value)
    
    with pytest.raises(ValueError) as excinfo:
        load_pre_built_corpus("   \n   ")
    assert "it does not appear to be a Tumbler-built bundle" in str(excinfo.value)
    
    # 3. Non-empty but missing evidence tags
    with pytest.raises(ValueError) as excinfo:
        load_pre_built_corpus("print('hello world')")
    assert "it does not appear to be a Tumbler-built bundle" in str(excinfo.value)


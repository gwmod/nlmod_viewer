import sys
import os

def find_context(filepath, search_str):
    try:
        if isinstance(search_str, str):
            sb_bytes = search_str.encode('ascii')
        else:
            sb_bytes = search_str

        with open(filepath, 'rb') as f:
            data = f.read()
            idx = data.find(sb_bytes)
            if idx != -1:
                # Print 500 bytes around it
                start = max(0, idx - 100)
                end = min(len(data), idx + 200)
                chunk = data[start:end]
                print(f"Found {sb_bytes} at {idx}")
                # Print ASCII
                ascii_parts = []
                for b in chunk:
                    if 32 <= b <= 126:
                        ascii_parts.append(chr(b))
                    else:
                        ascii_parts.append('.')
                print(f"ASCII context: {''.join(ascii_parts)}")
            else:
                print(f"String {sb_bytes} not found in file")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 2:
        find_context(sys.argv[1], sys.argv[2])
    else:
        find_context(sys.argv[1], 'HLc')

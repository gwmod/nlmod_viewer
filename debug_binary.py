import sys
import os

def find_context(filepath, search_str=b'PZWAz1'):
    try:
        with open(filepath, 'rb') as f:
            data = f.read()
            idx = data.find(search_str)
            if idx != -1:
                # Print 500 bytes around it
                start = max(0, idx - 100)
                end = min(len(data), idx + 1000)
                chunk = data[start:end]
                print(f"Found {search_str} at {idx}")
                print(f"Hex context: {chunk.hex(' ', 1)}")
                # Print ASCII
                ascii_parts = []
                for b in chunk:
                    if 32 <= b <= 126:
                        ascii_parts.append(chr(b))
                    else:
                        ascii_parts.append('.')
                print(f"ASCII context: {''.join(ascii_parts)}")
            else:
                print(f"String {search_str} not found in file")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    find_context(sys.argv[1])

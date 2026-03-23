import sys
import re

def find_layer_names(filepath, count=48):
    try:
        with open(filepath, 'rb') as f:
            data = f.read(1024 * 1024 * 5) # Read first 5MB
            
        # REGIS layer names are usually uppercase alphanumeric and short (2-12 chars)
        # Search for sequences of such strings
        # We look for \x00 padding or just a dense block
        
        # Try to find common REGIS unit names to locate the block
        # Codes: WA, A, B, BX, DR, DO, KR, MS, TE...
        common = [b'WAK', b'PZWA', b'KR', b'UR']
        for c in common:
            idx = data.find(c)
            if idx != -1:
                # Found a candidate start. Look around for 48 strings.
                # Try a window of 48 * max_len
                window = data[idx-500:idx+2000]
                # Extract all alphanumeric strings
                found = re.findall(b'[A-Z0-9_.-]{2,16}', window)
                if len(found) >= count:
                    # Return the longest sequence that might be our layers
                    return [s.decode(errors='ignore') for s in found[:count]]

        # General search for ANY block of 48 strings
        found = re.findall(b'[A-Z0-9_.-]{2,11}', data)
        # Filter for sequences that look like it
        for i in range(len(found) - count + 1):
             sub = found[i:i+count]
             lengths = [len(s) for s in sub]
             # If most lengths are similar, it's a good candidate
             if len(set(lengths)) <= 3 and all(l >= 2 for l in lengths):
                  return [s.decode(errors='ignore') for s in sub]
    except:
        pass
    return None

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: scan_layers.py <filepath>")
        sys.exit(1)
    # Use 48 as default count but count can be passed
    # and we can search for the string 'layer' to find the count
    names = find_layer_names(sys.argv[1])
    if names:
        # Check if they are actually 48
        print("|".join(names))
    else:
        print("NOT_FOUND")

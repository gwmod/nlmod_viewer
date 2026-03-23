from osgeo import gdal
import json

def get_json_info(filepath):
    try:
        ds = gdal.OpenEx(filepath, gdal.OF_MULTIDIM_RASTER)
        if ds:
            info = gdal.Info(ds, format='json', allMetadata=True)
            with open('full_info.json', 'w') as f:
                f.write(info)
            # Log the length and keys
            data = json.loads(info)
            print(f"Info keys: {list(data.keys())}")
            # Search for the strings HLc or OOz1 in the JSON
            if 'HLc' in info:
                print("FOUND HLc in JSON!")
            else:
                print("HLc NOT in JSON")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    import sys
    get_json_info(sys.argv[1])

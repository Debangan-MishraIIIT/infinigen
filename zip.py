import os
import zipfile

root_dir = "./v3001_final_outputs/DiningRoom_v6001_AA_Final_Part4"
target_rel_path = os.path.join("coarse", "scene.blend")  # relative path to match

# print(root_dir)

for dirpath, dirnames, filenames in os.walk(root_dir):
    # print(dirpath)
    for filename in filenames:
        file_path = os.path.join(dirpath, filename)
        rel_path = os.path.relpath(file_path, root_dir)

        # Match only the specific file path
        if rel_path.endswith(target_rel_path):
            print("Target relative path found")
            processed_json = os.path.join(dirpath, "../visible_objects.json")
            processed_1_json = os.path.join(dirpath, "../cameras.json")

            if os.path.exists(processed_json):    
                print("Processed json found")
                zip_path = file_path + ".zip"
                print(rel_path)

                orig_size = os.path.getsize(file_path)
                print(f"Original size: {orig_size} bytes")

                # Create a zip file and add the .blend file
                with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as zipf:
                    zipf.write(file_path, arcname=os.path.basename(file_path))

                zip_size = os.path.getsize(zip_path)
                print(f"Zipped size: {zip_size} bytes")

                # Delete the original .blend file
                os.remove(file_path)
                print(f"Zipped and removed: {file_path}")
            else:
                print(f"Skipping {file_path} (no processed.json found)")

import os
import sys

# Import your existing indexing function
from indexer import index_file

# 1. Get the folder path from the terminal command
folder_path = sys.argv[1]

# 2. Loop through every file in that folder
for filename in os.listdir(folder_path):
    # 3. Create the full path to the file
    full_path = os.path.join(folder_path, filename)

    # 4. Make sure it's a file and not a sub-folder
    if os.path.isfile(full_path):

        # 5. Ignore CSV files completely
        if filename.endswith(".csv"):
            print(f"Skipping CSV: {filename}")
            continue

        print(f"Indexing {filename}...")

        try:
            # 6. Try to index the file
            result = index_file(full_path)
            print(result)
        except Exception as e:
            # If it's too big or causes an error, skip it
            print(f"Skipped {filename} because of an error.")
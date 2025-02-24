import pandas as pd
import numpy as np

# Constants
THRESHOLD = 100
ORIGINAL_TXTL_PATH = 'worklists/TXTL_Wklist.csv'
NEW_TXTL_PATH = 'worklists/TXTL_Wklist_filtered.csv'
ORIGINAL_SUBSTRATE_PATH = 'worklists/Assay_substrate.csv'
NEW_SUBSTRATE_PATH = 'worklists/Assay_substrate_filtered.csv'
ORIGINAL_PROTEIN_PATH = 'worklists/Assay_protein.csv'
NEW_PROTEIN_PATH = 'worklists/Assay_protein_filtered.csv'
EVAGREEN_PATH = 'data/raw_evagreen_data.csv'

# Read the file line by line
with open(EVAGREEN_PATH, 'r') as f:
    lines = f.readlines()

# Initialize data storage
evagreen_data = {}

# Process each line
for i, line in enumerate(lines):
    line = line.strip()
    if not line:
        continue
    
    # Skip header row
    if line.startswith('\t'):
        continue
        
    # Remove section labels from end of lines
    if 'Read 1:485,535' in line:
        line = line.split('Read 1:485,535')[0]
            
    # Split by tabs
    parts = line.split('\t')
    
    # Check for valid row
    if not parts[0] or not parts[0][0].isalpha() or len(parts[0]) != 1:
        continue
        
    row_id = parts[0]
    
    # Process values
    for col, value in enumerate(parts[1:], 1):
        if value.strip():
            well = f"{row_id}{col}"
            try:
                evagreen_data[well] = float(value)
            except ValueError:
                continue

# Get values from positions A12, C12, E12
values = {
    'A12': evagreen_data.get('A12', 0),
    'C12': evagreen_data.get('C12', 0),
    'E12': evagreen_data.get('E12', 0)
}

print(f"Detected values: {values}")  # Debug print

# Create mapping of which indices/wells to remove based on well positions
txtl_remove_mapping = {
    'A12': [1, 4, 7],
    'C12': [2, 5, 8],
    'E12': [3, 6, 9]
}

substrate_remove_mapping = {
    'A12': ['01', '04', '07'],
    'C12': ['02', '05', '08'],
    'E12': ['03', '06', '09']
}

# Determine which values to remove
txtl_indices_to_remove = []
substrate_wells_to_remove = []
for well, value in values.items():
    if value < THRESHOLD:
        print(f"Well {well} value {value} is below threshold {THRESHOLD}")
        txtl_indices_to_remove.extend(txtl_remove_mapping[well])
        substrate_wells_to_remove.extend(substrate_remove_mapping[well])

# Process TXTL worklist
df_txtl = pd.read_csv(ORIGINAL_TXTL_PATH)
df_txtl = df_txtl[~df_txtl['Index'].isin(txtl_indices_to_remove)]
new_indices = [f"{i+1:02d}" for i in range(len(df_txtl))]
df_txtl['Index'] = new_indices
df_txtl.to_csv(NEW_TXTL_PATH, index=False)

# Process Substrate worklist
df_substrate = pd.read_csv(ORIGINAL_SUBSTRATE_PATH)
df_substrate = df_substrate[~df_substrate['Destination_Well'].str[-2:].isin(substrate_wells_to_remove)]
new_indices = [f"{i+1:02d}" for i in range(len(df_substrate))]
df_substrate['Index'] = new_indices
df_substrate.to_csv(NEW_SUBSTRATE_PATH, index=False)

# Process Protein worklist
df_protein = pd.read_csv(ORIGINAL_PROTEIN_PATH)
df_protein = df_protein[~df_protein['Destination_Well'].str[-2:].isin(substrate_wells_to_remove)]
new_indices = [f"{i+1:02d}" for i in range(len(df_protein))]
df_protein['Index'] = new_indices
df_protein.to_csv(NEW_PROTEIN_PATH, index=False)

print(f"TXTL indices removed: {txtl_indices_to_remove}")
print(f"Wells removed from substrate and protein: {substrate_wells_to_remove}")

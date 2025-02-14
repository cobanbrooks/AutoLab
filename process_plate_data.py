import pandas as pd
import numpy as np

def normalize_plate_data(input_file, output_file):

    # Read the file line by line
    with open(input_file, 'r') as f:
        lines = f.readlines()
    
    # Initialize data storage
    fluorescein_data = {}
    rfu_data = {}
    
    # Initialize section
    current_section = None
    
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        
        # Detect sections
        if line.startswith('Read 1:494,512'):
            current_section = 'fluorescein'
            continue
        elif line.startswith('Mean RFU'):
            current_section = 'rfu'
            continue
        
        # Skip header row
        if line.startswith('\t'):
            continue
            
        # Remove section labels from end of lines
        if 'Read 1:494,512' in line:
            line = line.split('Read 1:494,512')[0]
        elif 'Mean RFU' in line:
            line = line.split('Mean RFU')[0]
            
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
                    if current_section == 'fluorescein':
                        fluorescein_data[well] = float(value)
                    elif current_section == 'rfu':
                        rfu_data[well] = float(value)
                except ValueError:
                    continue
    
    # Calculate column averages
    col_averages = {}
    for well, value in fluorescein_data.items():
        col = well[1:]
        if col not in col_averages:
            col_averages[col] = 0
            col_averages[col] = sum(value for w, value in fluorescein_data.items() 
                                  if w[1:] == col) / 3
    
    # Calculate normalized values
    normalized_data = {}
    for well, rfu_value in rfu_data.items():
        col = well[1:]
        if col in col_averages and col_averages[col] > 0:
            fluor_value = fluorescein_data.get(well, 0)
            if fluor_value > 0:
                norm_constant = fluor_value / col_averages[col]
                normalized_data[well] = rfu_value / norm_constant
    
    # Create output DataFrame
    rows = 'ABCDEFGH'
    cols = range(1, 13)
    output_data = []
    
    for row in rows:
        row_data = []
        for col in cols:
            well = f"{row}{col}"
            row_data.append(normalized_data.get(well, None))
        output_data.append(row_data)
    
    df_output = pd.DataFrame(output_data, 
                           index=list(rows),
                           columns=[str(i) for i in cols])
    
    # Save to CSV
    df_output.to_csv(output_file)
    return df_output

if __name__ == "__main__":
    input_file = "data/raw_plate_data.csv"
    output_file = "data/normalized_plate_data.csv"
    normalized_data = normalize_plate_data(input_file, output_file)
    print("\nNormalized values:")
    print(normalized_data)
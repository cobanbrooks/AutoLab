import pandas as pd
import numpy as np
from scipy.stats import sem

def normalize_plate_data(input_file, output_file, sequence_file):
    """
    Normalize plate reader data and create sequence-to-means mapping.
    """
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
    
    # Calculate column averages for fluorescein
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
    
    # Group replicates and calculate statistics
    replicate_stats = {}
    cols = sorted(set(well[1:] for well in normalized_data.keys()))
    
    for col in cols:
        # Get normalized values for this column's replicates (rows A, C, E)
        replicates = [normalized_data.get(f"A{col}"),
                     normalized_data.get(f"C{col}"),
                     normalized_data.get(f"E{col}")]
        replicates = [x for x in replicates if x is not None]  # Remove None values
        
        if len(replicates) >= 2:  # Need at least 2 values for statistics
            mean = np.mean(replicates)
            replicate_stats[col] = {
                'mean': mean,
            }
    
    # Create sequence mapping
    with open(sequence_file, 'r') as f:
        sequences = [line.strip() for line in f.readlines()]
    
    # Define column groupings for each sequence
    col_groups = {
        0: ['1', '4', '7'],    # First sequence gets columns 1,4,7
        1: ['2', '5', '8'],    # Second sequence gets columns 2,5,8
        2: ['3', '6', '9']     # Third sequence gets columns 3,6,9
    }
    
    # Create sequence to mean mapping
    sequence_mapping = {}
    for i, seq in enumerate(sequences):
        cols = col_groups[i]
        means = []
        for col in cols:
            if col in replicate_stats:
                means.append(replicate_stats[col]['mean'])
            else:
                means.append(None)
        sequence_mapping[seq] = means
    
    # Create output DataFrames for normalized values
    rows = 'ABCDEFGH'
    cols = range(1, 13)
    output_data = []
    for row in rows:
        row_data = []
        for col in cols:
            well = f"{row}{col}"
            row_data.append(normalized_data.get(well, None))
        output_data.append(row_data)
    
    df_normalized = pd.DataFrame(output_data, 
                               index=list(rows),
                               columns=[str(i) for i in cols])
    
    # Save normalized data to CSV
    df_normalized.to_csv(output_file)
    
    return df_normalized, sequence_mapping

if __name__ == "__main__":
    input_file = "data/raw_plate_data.csv"
    output_file = "data/normalized_plate_data.csv"
    sequence_file = "data/sequence_query.txt"
    phenotype_file = 'data/phenotype.txt'
    
    df_norm, seq_mapping = normalize_plate_data(input_file, output_file, sequence_file)
    
    print("\nNormalized values:")
    print(df_norm)
    print("\nSequence mapping:")
    print(seq_mapping)

    with open(phenotype_file, 'w') as f:
        f.write(str(seq_mapping))
        f.close()

    
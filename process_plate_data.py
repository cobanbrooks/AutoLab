import pandas as pd
import numpy as np
import argparse
import json

def normalize_plate_data(input_file, output_file, sequence_file):
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
        elif line.startswith('Mean V'):
            current_section = 'rfu'
            continue
        
        # Skip header row
        if line.startswith('\t'):
            continue
            
        # Remove section labels from end of lines
        if 'Read 1:494,512' in line:
            line = line.split('Read 1:494,512')[0]
        elif 'Mean V' in line:
            line = line.split('Mean V')[0]
            
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
    
    # Get negative control values from column 10
    glucose_control = normalized_data.get("A10")
    xylose_control = normalized_data.get("C10")
    mannose_control = normalized_data.get("E10")
    
    # Subtract negative controls from respective rows
    background_subtracted = {}
    for well, value in normalized_data.items():
        row = well[0]
        if row == 'A' and glucose_control is not None:
            background_subtracted[well] = max(0, value - glucose_control)
        elif row == 'C' and xylose_control is not None:
            background_subtracted[well] = max(0, value - xylose_control)
        elif row == 'E' and mannose_control is not None:
            background_subtracted[well] = max(0, value - mannose_control)
        else:
            background_subtracted[well] = value
    
    # Group replicates and calculate statistics
    replicate_stats = {}
    cols = sorted(set(well[1:] for well in background_subtracted.keys()))
    
    for col in cols:
        # Get background-subtracted values for this column's replicates (rows A, C, E)
        replicates = [background_subtracted.get(f"A{col}"),
                     background_subtracted.get(f"C{col}"),
                     background_subtracted.get(f"E{col}")]
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
    
    # Load existing phenotype data to get 'valid' values
    try:
        with open(output_file, 'r') as f:
            existing_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        existing_data = {}

    # Create new phenotype data structure
    phenotype_data = {}
    for seq, measurements in sequence_mapping.items():
        phenotype_data[seq] = {
            "measurements": measurements,
            # Keep existing valid status if it exists, otherwise default to True
            "valid": existing_data.get(seq, {}).get("valid", True)
        }
    
    # Create output DataFrames for background-subtracted normalized values
    rows = 'ABCDEFGH'
    cols = range(1, 13)
    output_data = []
    for row in rows:
        row_data = []
        for col in cols:
            well = f"{row}{col}"
            row_data.append(background_subtracted.get(well, None))
        output_data.append(row_data)
    
    df_normalized = pd.DataFrame(output_data, 
                               index=list(rows),
                               columns=[str(i) for i in cols])
    
    return df_normalized, phenotype_data

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True, help="Path to input file")
    parser.add_argument('--output', required=True, help="Path to output file")
    parser.add_argument('--sequence_file', required=True, help="Path to sequence file")

    args = parser.parse_args()

    df_norm, phenotype_data = normalize_plate_data(args.input, args.output, args.sequence_file)

    # Save the phenotype data
    with open(args.output, 'w') as f:
        json.dump(phenotype_data, f, indent=4)
        print("\nPhenotype file written")

if __name__ == "__main__":
    main() 

    
import csv
import json
import sys
import os

def read_sequence_file(file_path):
    """Read multiple sequences from a file and clean them."""
    try:
        with open(file_path, 'r') as file:
            sequences = [line.strip() for line in file.readlines() if line.strip()]
        
        print(f"Read {len(sequences)} sequences:")
        for i, seq in enumerate(sequences, 1):
            print(f"Sequence {i} (length: {len(seq)}): {seq[:50]}...")
        
        if not sequences:
            raise ValueError("Sequence file is empty")
        return sequences
    except FileNotFoundError:
        raise FileNotFoundError(f"Sequence file not found: {file_path}")
    except Exception as e:
        raise ValueError(f"Error reading sequence file: {e}")

def find_sequence_fragments(sequence, csv_file_path, sequence_number):
    """Find fragments for a given sequence."""
    try:
        with open(csv_file_path, 'r') as file:
            csv_reader = csv.reader(file)
            headers = next(csv_reader)
            data = {row[0]: row[1:] for row in csv_reader}
    except FileNotFoundError:
        raise FileNotFoundError(f"CSV file not found: {csv_file_path}")
    except csv.Error as e:
        raise ValueError(f"Error reading CSV file: {e}")

    result = []
    start = 0
    while start < len(sequence):
        found = False
        for p in data:
            for f, fragment in enumerate(data[p]):
                if fragment and sequence.startswith(fragment, start):
                    result.append(f"{p}f{f}")
                    start += len(fragment)
                    found = True
                    break
            if found:
                break
        if not found:
            raise ValueError(f"No matching fragment found for sequence starting at position {start}")

    return result

def get_parent_sequence(fragments):
    """Create parent sequence string from list of fragments"""
    sorted_fragments = sorted(fragments, key=lambda x: int(x[3:]))
    parent_sequence = ''.join(fragment[1:2] for fragment in sorted_fragments)
    return parent_sequence

def create_plate_layout(sequences):
    """Create plate layout dictionary for first fragment only"""
    layout = {}
    rows = 'ABC'  # 3 rows for replicates
    sugars = ['glu', 'xyl', 'man']
    
    # Get parent sequences for each sequence
    parent_sequences = {
        seq_num: get_parent_sequence(fragments)
        for seq_num, fragments in sequences.items()
    }
    
    # For each sugar type (3 blocks of 3 columns each)
    for sugar_idx, sugar in enumerate(sugars):
        # Base column for this sugar block
        sugar_col_start = (sugar_idx * 3) + 1
        
        # For each replicate (row)
        for rep_idx, row in enumerate(rows, 1):
            # For each sequence (column within sugar block)
            for seq_idx, seq_num in enumerate(sorted(sequences.keys()), 0):
                # Calculate well position
                col = sugar_col_start + seq_idx
                well = f"{row}{col}"
                
                # Create well identifier using full parent sequence
                layout[well] = f"{parent_sequences[seq_num]}-R{rep_idx}-{sugar}"

    return layout

def main():
    if len(sys.argv) != 4:
        print("Usage: python script.py <sequence_file> <csv_file> <output_json>")
        sys.exit(1)

    sequence_file = sys.argv[1]
    csv_file = sys.argv[2]
    output_json = sys.argv[3]

    try:
        # Read sequences
        sequences = read_sequence_file(sequence_file)

        # Process each sequence to get fragments
        sequence_fragments = {}
        for i, sequence in enumerate(sequences, 1):
            fragments = find_sequence_fragments(sequence, csv_file, i)
            sequence_fragments[str(i)] = fragments
            print(f"\nSequence {i} fragments: {fragments}")

        # Create plate layout
        layout = create_plate_layout(sequence_fragments)

        # Write JSON output
        with open(output_json, 'w') as f:
            json.dump(layout, f, indent=2)

        print(f"\nPlate layout written to {output_json}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
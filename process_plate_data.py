import pandas as pd
import argparse
from datetime import datetime

def process_plate_data(input_file: str, output_file: str):
    """
    Dummy processing - just copies the file and adds a timestamp
    """
    try:
        # Read the input CSV
        df = pd.read_csv(input_file)
        
        # Add timestamp column
        df['processed_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Save processed data
        df.to_csv(output_file, index=False)
        print(f"Successfully processed {input_file}")
        print(f"Processed data saved to {output_file}")
        
        return True
        
    except Exception as e:
        print(f"Error processing data: {str(e)}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Process plate reader data')
    parser.add_argument('--input', required=True, help='Input CSV file')
    parser.add_argument('--output', required=True, help='Output CSV file')
    
    args = parser.parse_args()
    
    success = process_plate_data(args.input, args.output)
    exit(0 if success else 1)
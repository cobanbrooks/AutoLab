import os
import time
import yaml
from lab_controller import LabController

def test_config_loading():
    """Test configuration file loading"""
    print("Testing config loading...")
    try:
        automation = LabController('lab_config.yml')
        print("✓ Config loaded successfully")
        return automation
    except Exception as e:
        print(f"✗ Config loading failed: {e}")
        return None

def test_github_polling(automation):
    """Test GitHub polling functionality"""
    print("\nTesting GitHub polling...")
    try:
        result = automation.check_sequence_updates()
        print(f"✓ GitHub polling {'detected changes' if result else 'no changes detected'}")
    except Exception as e:
        print(f"✗ GitHub polling failed: {e}")

def test_file_generation(automation):
    """Test worklist and plate layout generation"""
    print("\nTesting file generation...")
    try:
        result = automation.generate_lab_files()
        print("✓ File generation completed")
        
        # Verify files exist
        files_to_check = [
            'output/fragment_assembly_worklist.csv',
            'plate_layout.json'
        ]
        
        for file in files_to_check:
            if os.path.exists(file):
                print(f"✓ {file} generated successfully")
            else:
                print(f"✗ {file} not found")
    except Exception as e:
        print(f"✗ File generation failed: {e}")

def test_plate_monitoring(automation):
    """Test plate data monitoring"""
    print("\nTesting plate data monitoring...")
    try:
        observer = automation.start_plate_monitoring()
        print("✓ Monitoring started")
        
        # Create test plate data
        with open('plate_data.csv', 'w') as f:
            f.write("test_data")
        print("✓ Created test plate data")
        
        # Wait for processing
        time.sleep(5)
        
        if os.path.exists('processed_plate_data.csv'):
            print("✓ Processed data file generated")
        else:
            print("✗ Processed data file not found")
            
        observer.stop()
        observer.join()
    except Exception as e:
        print(f"✗ Monitoring test failed: {e}")

def main():
    print("Starting Lab Automation Tests\n")
    
    # Run tests
    automation = test_config_loading()
    if automation:
        test_github_polling(automation)
        test_file_generation(automation)
        test_plate_monitoring(automation)
    
    print("\nTest suite completed")

if __name__ == "__main__":
    main()